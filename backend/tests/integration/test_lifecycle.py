"""Lifecycle runner (specification 003-A3) and mail expiry (003-A4) on disposable PostgreSQL."""

import secrets
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import (
    AgencyInvitation,
    AuthRateLimit,
    AuthSession,
    AuthToken,
    MailOutbox,
    OAuthTransaction,
    User,
    VerificationChallenge,
)
from app.security import now_utc
from app.services.lifecycle import CREDENTIAL_STATE_JOB, LOCK_NAMESPACE, run_lifecycle
from app.services.mail import process_mail

pytestmark = pytest.mark.integration

EDGE = timedelta(microseconds=1)
DAY = timedelta(days=1)
MODELS = {
    "auth_sessions": AuthSession,
    "auth_tokens": AuthToken,
    "verification_challenges": VerificationChallenge,
    "oauth_transactions": OAuthTransaction,
    "auth_rate_limits": AuthRateLimit,
    "mail_outbox": MailOutbox,
}


def synthetic_user(db) -> object:
    with Session(db.migration, expire_on_commit=False) as session, session.begin():
        user = User(email_normalized=f"{uuid4().hex}@example.test", display_name="Lifecycle")
        session.add(user)
    return user.id


# A row of the given model that has not ended, then the named end timestamp applied.
def row(name, user_id, cutoff, **ended):
    future, old = cutoff + timedelta(days=365), cutoff - timedelta(days=400)
    digest = secrets.token_hex(32)
    base = {
        "auth_sessions": dict(
            user_id=user_id,
            token_digest=digest,
            created_at=old,
            last_seen_at=cutoff,
            expires_at=future,
        ),
        "auth_tokens": dict(
            user_id=user_id,
            token_digest=digest,
            purpose="reset",
            created_at=old,
            expires_at=future,
        ),
        "verification_challenges": dict(
            user_id=user_id,
            purpose="email_verification",
            verifier=digest,
            created_at=old,
            expires_at=future,
        ),
        "oauth_transactions": dict(
            purpose="login",
            state_digest=digest,
            binding_digest=secrets.token_hex(32),
            created_at=old,
            expires_at=future,
        ),
        "auth_rate_limits": dict(bucket_key=digest, attempts=1, expires_at=future),
        "mail_outbox": dict(purpose="reset", created_at=old, next_attempt_at=old),
    }[name]
    return MODELS[name](**{**base, **ended})


def remaining(db, name) -> int:
    with db.migration.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()


def test_runner_deletes_only_rows_strictly_past_each_approved_boundary(
    db, lifecycle_engine, lifecycle_settings
):
    cutoff, user = now_utc(), synthetic_user(db)
    idle = timedelta(seconds=lifecycle_settings.session_idle_seconds)
    cases = [
        ("auth_sessions", "revoked_at", 30 * DAY),
        ("auth_sessions", "expires_at", 30 * DAY),
        ("auth_sessions", "last_seen_at", 30 * DAY + idle),
        ("auth_tokens", "consumed_at", 7 * DAY),
        ("auth_tokens", "expires_at", 7 * DAY),
        ("verification_challenges", "consumed_at", 7 * DAY),
        ("verification_challenges", "invalidated_at", 7 * DAY),
        ("verification_challenges", "expires_at", 7 * DAY),
        ("oauth_transactions", "consumed_at", DAY),
        ("oauth_transactions", "expires_at", DAY),
        ("auth_rate_limits", "expires_at", timedelta(0)),
        ("mail_outbox", "delivered_at", 30 * DAY),
        ("mail_outbox", "expires_at", 30 * DAY),
    ]
    expected = dict.fromkeys(MODELS, 0)
    with Session(db.migration) as session, session.begin():
        for name in MODELS:
            session.add(row(name, user, cutoff))  # not ended: kept
        for name, field, period in cases:
            session.add(row(name, user, cutoff, **{field: cutoff - period}))  # at boundary: kept
            session.add(row(name, user, cutoff, **{field: cutoff - period - EDGE}))  # past
            expected[name] += 1
    kept = {name: remaining(db, name) - expected[name] for name in MODELS}

    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=cutoff)
    assert result == {
        "status": "completed",
        "deleted": {**expected, "local_mail_files": 0},
        "incomplete": [],
    }
    assert {name: remaining(db, name) for name in MODELS} == kept
    again = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=cutoff)
    assert again["deleted"] == {**dict.fromkeys(MODELS, 0), "local_mail_files": 0}


def test_bounded_runs_resume_without_skipping_eligible_rows(
    db, lifecycle_engine, lifecycle_settings
):
    cutoff, user = now_utc(), synthetic_user(db)
    with Session(db.migration) as session, session.begin():
        session.add_all(
            row("auth_tokens", user, cutoff, consumed_at=cutoff - 8 * DAY) for _ in range(5)
        )
    settings = lifecycle_settings.model_copy(update={"lifecycle_batch_size": 2})
    first = run_lifecycle(lifecycle_engine, settings, cutoff=cutoff, max_batches=1)
    assert (first["status"], first["deleted"]["auth_tokens"], first["incomplete"]) == (
        "partial",
        2,
        ["auth_tokens"],
    )
    second = run_lifecycle(lifecycle_engine, settings, cutoff=cutoff, max_batches=1)
    assert second["deleted"]["auth_tokens"] == 2
    last = run_lifecycle(lifecycle_engine, settings, cutoff=cutoff)
    assert (last["status"], last["deleted"]["auth_tokens"]) == ("completed", 1)
    assert remaining(db, "auth_tokens") == 0


def test_a_concurrent_runner_exits_without_deleting(db, lifecycle_engine, lifecycle_settings):
    cutoff, user = now_utc(), synthetic_user(db)
    with Session(db.migration) as session, session.begin():
        session.add(row("auth_tokens", user, cutoff, expires_at=cutoff - 8 * DAY))
    with db.migration.connect() as holder:
        holder.execute(select(func.pg_advisory_lock(LOCK_NAMESPACE, CREDENTIAL_STATE_JOB)))
        result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=cutoff)
        assert result == {"status": "skipped_concurrent_run", "deleted": {}, "incomplete": []}
        assert remaining(db, "auth_tokens") == 1
        holder.execute(select(func.pg_advisory_unlock(LOCK_NAMESPACE, CREDENTIAL_STATE_JOB)))
    assert run_lifecycle(lifecycle_engine, lifecycle_settings)["deleted"]["auth_tokens"] == 1


def test_a_row_locked_by_a_request_defers_only_its_target(db, lifecycle_engine, lifecycle_settings):
    cutoff, user = now_utc(), synthetic_user(db)
    session_row = row("auth_sessions", user, cutoff, revoked_at=cutoff - 31 * DAY)
    session_row.id = locked_id = uuid4()
    with Session(db.migration) as session, session.begin():
        session.add_all(
            [session_row, row("auth_tokens", user, cutoff, consumed_at=cutoff - 8 * DAY)]
        )
    with db.runtime.connect() as request:
        # A request transaction holds the row lock, as session authentication does.
        request.execute(select(AuthSession.id).where(AuthSession.id == locked_id).with_for_update())
        started = time.monotonic()
        result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=cutoff)
        assert time.monotonic() - started < 2
        assert result["status"] == "partial" and result["incomplete"] == ["auth_sessions"]
        assert result["deleted"]["auth_tokens"] == 1
        # The request transaction was not aborted by the runner.
        request.execute(
            update(AuthSession).where(AuthSession.id == locked_id).values(last_seen_at=cutoff)
        )
        request.commit()
    assert (
        run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=cutoff)["deleted"][
            "auth_sessions"
        ]
        == 1
    )


def test_purging_ended_state_leaves_authentication_working(
    api, db, lifecycle_engine, lifecycle_settings
):
    email = "lifecycle.user@example.test"
    client = api.client
    assert (
        client.post(
            "/auth/register",
            json={"email": email, "display_name": "Synthetic", "password": api.password},
        ).status_code
        == 202
    )
    code = api.mail_tokens()[-1][2]
    assert (
        client.post("/auth/verify-email-code", json={"email": email, "code": code}).status_code
        == 204
    )
    old_browser, current = api.new_client(), api.new_client()
    api.login(old_browser, email)
    assert old_browser.post("/auth/logout").status_code == 204
    old_cookie = api.login(old_browser, email).cookies
    assert old_browser.post("/auth/logout").status_code == 204
    api.login(current, email)
    assert client.post("/auth/forgot-password", json={"email": email}).status_code == 202
    reset_token = api.mail_tokens()[-1][2]
    month_ago = now_utc() - 31 * DAY
    with Session(db.migration) as session, session.begin():
        session.execute(
            update(AuthSession)
            .where(AuthSession.revoked_at.is_not(None))
            .values(revoked_at=month_ago, last_seen_at=month_ago)
        )
        session.execute(update(AuthToken).values(expires_at=month_ago))
        session.execute(
            update(VerificationChallenge).values(consumed_at=month_ago, expires_at=month_ago)
        )
        session.execute(update(MailOutbox).values(delivered_at=month_ago))

    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed"
    assert result["deleted"]["auth_sessions"] == 2
    assert result["deleted"]["auth_tokens"] == 1
    assert result["deleted"]["verification_challenges"] == 1
    assert result["deleted"]["mail_outbox"] == 2
    assert current.get("/auth/me").status_code == 200
    stale = api.new_client()
    stale.cookies.update(old_cookie)
    assert stale.get("/auth/me").status_code == 401
    replay = client.post(
        "/auth/reset-password", json={"token": reset_token, "password": "Another password 456!"}
    )
    assert (replay.status_code, replay.json()) == (400, {"error": "invalid_or_expired_token"})
    api.login(api.new_client(), email)


def test_reset_and_invitation_mail_expire_with_their_links(api, authenticated_world, db):
    world = authenticated_world
    owner = world.signed_in("owner_a")
    response = owner.post(
        f"/agencies/{world.a}/invitations",
        json={"email": "invitee@example.test", "role": "analyst", "clients": []},
    )
    assert response.status_code == 201, response.text
    assert (
        api.client.post("/auth/forgot-password", json={"email": "admin@example.test"}).status_code
        == 202
    )
    with Session(db.migration) as session:
        token_expiry = session.scalar(select(AuthToken.expires_at))
        invitation_expiry = session.scalar(select(AgencyInvitation.expires_at))
        messages = {m.purpose: m.expires_at for m in session.scalars(select(MailOutbox))}
    assert messages == {"reset": token_expiry, "invitation": invitation_expiry}
    with Session(db.migration) as session, session.begin():
        session.execute(update(MailOutbox).values(expires_at=now_utc() - timedelta(seconds=1)))
    assert process_mail(db.runtime, api.config) == {"delivered": 0, "failed": 0, "expired": 2}
    with Session(db.migration) as session:
        cleared = session.execute(
            select(MailOutbox.encrypted_payload, MailOutbox.failure_code, MailOutbox.attempts)
        ).all()
    assert cleared == [(None, "expired_before_delivery", 0)] * 2
    assert not api.config.mail_directory.exists() or not any(api.config.mail_directory.iterdir())


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM users",
        "DELETE FROM password_credentials",
        "DELETE FROM external_identities",
        "DELETE FROM security_events",
        "DELETE FROM audit_events",
        "DELETE FROM agency_memberships",
        "DELETE FROM agency_invitations",
        "SELECT count(*) FROM users",
        "UPDATE auth_sessions SET revoked_at = now()",
        "UPDATE mail_outbox SET encrypted_payload = NULL",
        "INSERT INTO auth_rate_limits (bucket_key, attempts, expires_at) VALUES ('x', 1, now())",
        "CREATE TABLE lifecycle_probe (id integer)",
    ],
)
def test_lifecycle_role_is_limited_to_its_grants(db, lifecycle_engine, statement):
    with pytest.raises(DBAPIError), lifecycle_engine.begin() as connection:
        connection.execute(text(statement))


def test_lifecycle_role_attributes(db, lifecycle_engine):
    with lifecycle_engine.connect() as connection:
        attributes = connection.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolinherit "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
    assert tuple(attributes) == (False, False, False, False, False)
