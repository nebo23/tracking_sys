"""Account closure and erasure (specification 003-A5, D-024) on disposable PostgreSQL."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
import test_google as google_tests
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_google import count, finish

from app.config import BACKEND_ROOT
from app.models import (
    Agency,
    AgencyMembership,
    AuditEvent,
    AuthSession,
    ExternalIdentity,
    OAuthTransaction,
    PasswordCredential,
    SecurityEvent,
    User,
)
from app.security import AuthError, csrf_token, now_utc
from app.services.auth import AuthService
from app.services.google import apply_account_policy
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import Role, tenancy_transaction

pytestmark = pytest.mark.integration
google_provider = google_tests.google

EMAIL = "closing.user@example.test"
CLAIMS = {
    "iss": "https://accounts.google.com",
    "sub": "synthetic-google-subject-closure",
    "email": "closing.google@workspace.example.test",
    "hd": "workspace.example.test",
    "email_verified": True,
    "name": "Synthetic Google User",
}


def close(client, password=None):
    return client.post(
        "/auth/close-account", json={} if password is None else {"password": password}
    )


def user_row(db, user_id):
    with Session(db.migration) as session:
        return session.get(User, user_id)


def active_owners(db, agency_id) -> int:
    with Session(db.migration) as session:
        return session.scalar(
            select(func.count())
            .select_from(AgencyMembership)
            .join(User, User.id == AgencyMembership.user_id)
            .where(
                AgencyMembership.agency_id == agency_id,
                AgencyMembership.role == "owner",
                AgencyMembership.status == "active",
                User.status == "active",
            )
        )


def registered_user(api, email=EMAIL, browser=None):
    response = api.client.post(
        "/auth/register",
        json={"email": email, "display_name": "Closing Person", "password": api.password},
    )
    assert response.status_code == 202
    code = api.mail_tokens()[-1][2]
    assert (
        api.client.post("/auth/verify-email-code", json={"email": email, "code": code}).status_code
        == 204
    )
    if browser is None:
        browser = api.new_client()
    user_id = api.login(browser, email).json()["user"]["id"]
    return browser, user_id


# Sign up through the Google account policy (provider validation is covered elsewhere) and
# return a browser carrying a fresh session for that Google-only account.
def google_user(api, db):
    with Session(db.runtime, expire_on_commit=False) as session, session.begin():
        user = apply_account_policy(session, api.config, CLAIMS, "login", None)
        raw = AuthService(session, api.config).issue_session(user)
    browser = api.new_client()
    browser.cookies.set(api.config.cookie_name, raw)
    browser.headers["X-CSRF-Token"] = csrf_token(api.config, raw)
    return browser, user.id


def test_password_account_closure_pseudonymizes_and_frees_the_email(api, db):
    browser, user_id = registered_user(api)
    other = api.new_client()
    api.login(other, EMAIL)
    response = close(browser, api.password)
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert other.get("/auth/me").status_code == 401
    user = user_row(db, user_id)
    assert (user.email_normalized, user.display_name, user.status) == (
        f"closed-{user_id}@tracking.invalid",
        "Closed account",
        "disabled",
    )
    assert user.closed_at is not None
    with Session(db.migration) as session:
        actions = set(
            session.scalars(select(SecurityEvent.action).where(SecurityEvent.user_id == user_id))
        )
        open_sessions = session.scalar(
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        )
    assert "account_closed" in actions and open_sessions == 0
    failed = api.new_client().post("/auth/login", json={"email": EMAIL, "password": api.password})
    assert failed.status_code == 401
    assert (
        api.client.post(
            "/auth/register",
            json={"email": EMAIL, "display_name": "New Person", "password": api.password},
        ).status_code
        == 202
    )
    with Session(db.migration) as session:
        reused = session.scalar(select(User.id).where(User.email_normalized == EMAIL))
    assert reused is not None and str(reused) != str(user_id)


@pytest.mark.parametrize("password", [None, "Wrong synthetic password 123"])
def test_wrong_or_missing_password_changes_nothing(api, db, password):
    browser, user_id = registered_user(api)
    response = close(browser, password)
    assert (response.status_code, response.json()) == (401, {"error": "invalid_credentials"})
    user = user_row(db, user_id)
    assert (user.email_normalized, user.status, user.closed_at) == (EMAIL, "active", None)
    assert browser.get("/auth/me").status_code == 200


def test_closure_requires_the_session_csrf_token(api, db):
    browser, user_id = registered_user(api)
    del browser.headers["X-CSRF-Token"]
    assert close(browser, api.password).status_code == 403
    assert user_row(db, user_id).status == "active"


def test_google_only_closure_needs_a_recent_session_and_frees_the_subject(
    api, db, lifecycle_engine, lifecycle_settings
):
    browser, user_id = google_user(api, db)
    with Session(db.migration) as session, session.begin():
        session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id)
            .values(created_at=now_utc() - timedelta(minutes=11))
        )
    stale = close(browser)
    assert (stale.status_code, stale.json()) == (403, {"error": "reauthentication_required"})
    with Session(db.migration) as session, session.begin():
        session.execute(
            update(AuthSession).where(AuthSession.user_id == user_id).values(created_at=now_utc())
        )
    assert close(browser).status_code == 204
    with Session(db.runtime) as session, session.begin(), pytest.raises(AuthError):
        apply_account_policy(session, api.config, CLAIMS, "login", None)

    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed"
    assert result["deleted"]["external_identities"] == 1
    assert result["deleted"]["auth_sessions"] == 1
    with Session(db.migration) as session:
        assert (
            session.scalar(select(ExternalIdentity).where(ExternalIdentity.user_id == user_id))
            is None
        )
    with Session(db.runtime, expire_on_commit=False) as session, session.begin():
        again = apply_account_policy(session, api.config, CLAIMS, "login", None)
    assert again.id != user_id and again.email_normalized == CLAIMS["email"]


def test_runner_deletes_the_closed_accounts_credential(
    api, db, lifecycle_engine, lifecycle_settings
):
    browser, user_id = registered_user(api)
    assert close(browser, api.password).status_code == 204
    with Session(db.migration) as session:
        assert session.get(PasswordCredential, user_id) is not None
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["deleted"]["password_credentials"] == 1
    with Session(db.migration) as session:
        assert session.get(PasswordCredential, user_id) is None
        assert session.get(User, user_id).status == "disabled"


def add_second_owner(world):
    with tenancy_transaction(world.db.runtime, world.users.owner_a) as service:
        return service.add_member(world.a, world.users.second_owner, Role.OWNER).id


def test_last_owner_is_refused_and_memberships_are_disabled_with_audit(api, authenticated_world):
    world, db = authenticated_world, authenticated_world.db
    owner = world.signed_in("owner_a")
    refused = close(owner, api.password)
    assert (refused.status_code, refused.json()) == (409, {"error": "state_conflict"})
    assert user_row(db, world.users.owner_a).status == "active"

    add_second_owner(world)
    assert close(owner, api.password).status_code == 204
    assert active_owners(db, world.a) == 1
    analyst = world.signed_in("analyst")  # analyst in agency A, admin in agency B
    assert close(analyst, api.password).status_code == 204
    with Session(db.migration) as session:
        statuses = {
            (membership.agency_id, membership.user_id): membership.status
            for membership in session.scalars(
                select(AgencyMembership).where(
                    AgencyMembership.user_id.in_([world.users.owner_a, world.users.analyst])
                )
            )
        }
        audits = session.scalars(
            select(AuditEvent.actor_user_id).where(AuditEvent.action == "membership.updated")
        ).all()
    assert set(statuses.values()) == {"disabled"} and len(statuses) == 3
    assert sorted(map(str, audits)) == sorted(
        map(str, [world.users.owner_a, world.users.analyst, world.users.analyst])
    )


def test_concurrent_co_owner_closures_leave_one_owner(api, authenticated_world):
    world = authenticated_world
    add_second_owner(world)
    clients = [world.signed_in("owner_a"), world.signed_in("second_owner")]
    barrier = Barrier(2)

    def attempt(client):
        barrier.wait()
        return close(client, api.password).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(attempt, clients))
    assert statuses == [204, 409]
    assert active_owners(world.db, world.a) == 1


def test_closure_and_concurrent_owner_demotion_cannot_both_succeed(api, authenticated_world):
    world = authenticated_world
    membership = add_second_owner(world)
    closing, demoting = world.signed_in("owner_a"), world.signed_in("second_owner")
    barrier = Barrier(2)

    def close_owner():
        barrier.wait()
        return close(closing, api.password).status_code

    def demote_self():
        barrier.wait()
        return demoting.patch(
            f"/agencies/{world.a}/members/{membership}", json={"role": "admin"}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        closed, demoted = executor.submit(close_owner), executor.submit(demote_self)
        outcome = (closed.result(), demoted.result())
    assert outcome in {(204, 409), (409, 200)}
    assert active_owners(world.db, world.a) == 1


def test_downgrade_refuses_populated_closure_state(api, db):
    browser, _ = registered_user(api)
    assert close(browser, api.password).status_code == 204
    with pytest.raises(RuntimeError, match="account-closure state"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0005_lifecycle")
    with db.migration.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == ("0006_account_closure")


# Observe the API's own role: PostgreSQL hides other roles' activity details.
def closure_waiting_on_lock(db) -> bool:
    with db.runtime.connect() as connection:
        return bool(
            connection.exec_driver_sql(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND query ILIKE '%%FROM agencies%%FOR UPDATE%%'"
            ).scalar_one()
        )


def test_closure_waits_for_the_agency_lock_and_rechecks_owners(api, authenticated_world):
    world = authenticated_world
    membership = add_second_owner(world)
    closing = world.signed_in("owner_a")
    with world.db.runtime.connect() as holder, ThreadPoolExecutor(max_workers=1) as executor:
        # A concurrent tenancy mutation holds the agency lock, as update_member does.
        holder.execute(select(Agency.id).where(Agency.id == world.a).with_for_update())
        pending = executor.submit(close, closing, api.password)
        deadline = time.monotonic() + 5
        while not closure_waiting_on_lock(world.db):
            assert time.monotonic() < deadline and not pending.done()
            time.sleep(0.02)
        holder.execute(
            update(AgencyMembership).where(AgencyMembership.id == membership).values(role="admin")
        )
        holder.commit()
        response = pending.result(timeout=10)
    assert (response.status_code, response.json()) == (409, {"error": "state_conflict"})
    assert user_row(world.db, world.users.owner_a).status == "active"
    assert active_owners(world.db, world.a) == 1


def test_owner_demotion_after_a_co_owner_closure_is_refused(api, authenticated_world):
    world = authenticated_world
    membership = add_second_owner(world)
    assert close(world.signed_in("owner_a"), api.password).status_code == 204
    demoted = world.signed_in("second_owner").patch(
        f"/agencies/{world.a}/members/{membership}", json={"role": "admin"}
    )
    assert (demoted.status_code, demoted.json()) == (409, {"error": "state_conflict"})
    assert active_owners(world.db, world.a) == 1


LINK_SUBJECT = "synthetic-google-subject-closure-link"


# A verified password user signed in on a Google-enabled browser that has started a link.
# Returns the browser, the provider substitute, the authorization parameters, and the user ID.
def pending_google_link(api, google_provider):
    browser, provider = google_provider
    client, user_id = registered_user(api, browser=browser())
    response = client.post("/auth/google/link")
    assert response.status_code == 200
    params = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    return client, provider, params, UUID(user_id)


# Queries of the API's role waiting for a lock that the given backend holds. PostgreSQL shows
# query text only for the observing role's own sessions.
def queries_blocked_by(db, pid) -> list[str]:
    with db.runtime.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT query FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND :pid = ANY(pg_blocking_pids(pid))"
                ),
                {"pid": pid},
            ).scalars()
        )


# True while another transaction holds the row lock of the OAuth transaction.
def oauth_row_locked(db, transaction_id) -> bool:
    with db.runtime.connect() as connection:
        free = connection.execute(
            select(OAuthTransaction.id)
            .where(OAuthTransaction.id == transaction_id)
            .with_for_update(skip_locked=True)
        ).scalar()
        connection.rollback()
    return free is None


# Review finding R003-01. Closure holds the user and session locks from authentication; the
# Google callback locks and consumes its OAuth transaction and then waits for the user lock.
# Closure previously updated the user's open OAuth transactions at this point, completing a
# lock cycle that PostgreSQL aborted with SQLSTATE 40P01 (the callback returned 503).
def test_closure_completes_while_a_google_link_callback_waits(
    api, db, google_provider, lifecycle_engine, lifecycle_settings
):
    client, provider, params, user_id = pending_google_link(api, google_provider)
    raw = client.cookies.get(client.app.state.settings.cookie_name)
    with Session(db.migration) as session:
        transaction_id = session.scalar(select(OAuthTransaction.id))
    with ThreadPoolExecutor(max_workers=1) as executor:
        with Session(db.runtime) as closing, closing.begin():
            closing_pid = closing.scalar(text("SELECT pg_backend_pid()"))
            service = AuthService(closing, api.config)
            user, auth_session = service.authenticate(raw)
            callback = executor.submit(finish, client, provider, params, sub=LINK_SUBJECT)
            deadline = time.monotonic() + 5
            while not (waiting := queries_blocked_by(db, closing_pid)):
                assert time.monotonic() < deadline, "The callback never waited for closure."
                assert not callback.done(), "The callback finished without waiting for closure."
                time.sleep(0.02)
            # The callback holds its OAuth transaction row and waits for the user row.
            assert len(waiting) == 1
            assert "FROM users" in waiting[0] and "FOR NO KEY UPDATE" in waiting[0]
            assert oauth_row_locked(db, transaction_id)
            try:
                service.close_account(user, auth_session, api.password)
            except DBAPIError as error:
                pytest.fail(f"Closure failed with SQLSTATE {getattr(error.orig, 'sqlstate', None)}")
        # Closure committed; the waiting callback resumes and finds the account disabled.
        response, result = callback.result(timeout=10)
    assert result == {"error": ["google_sign_in_failed"]}
    assert all("tracking_session=" not in item for item in response.headers.get_list("set-cookie"))
    assert count(db, ExternalIdentity) == 0
    assert count(db, SecurityEvent, SecurityEvent.action == "google_identity_linked") == 0
    assert count(db, SecurityEvent, SecurityEvent.action == "account_closed") == 1
    closed = user_row(db, user_id)
    assert closed.status == "disabled" and closed.closed_at is not None
    with Session(db.migration) as session:
        assert session.get(OAuthTransaction, transaction_id).consumed_at is not None
    assert client.get("/auth/me").status_code == 401

    run = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert run["status"] == "completed"
    assert run["deleted"]["oauth_transactions"] == 1
    assert run["deleted"]["password_credentials"] == 1
    with Session(db.migration) as session:
        for model in (OAuthTransaction, AuthSession, PasswordCredential):
            assert not session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )


def test_pending_google_link_cannot_complete_after_closure(
    api, db, google_provider, lifecycle_engine, lifecycle_settings
):
    client, provider, params, user_id = pending_google_link(api, google_provider)
    settings = client.app.state.settings
    raw = client.cookies.get(settings.cookie_name)
    assert close(client, api.password).status_code == 204
    with Session(db.migration) as session:
        pending = session.scalar(
            select(OAuthTransaction).where(OAuthTransaction.user_id == user_id)
        )
    # Closure leaves the row to the callback's own checks and to the lifecycle runner.
    assert pending.consumed_at is None
    # A retained cookie must not matter: the server rejects the closed account's session.
    client.cookies.set(settings.cookie_name, raw, domain="localhost.local", path="/")
    _, result = finish(client, provider, params, sub=LINK_SUBJECT)
    assert result == {"error": ["google_sign_in_failed"]}
    assert count(db, ExternalIdentity) == 0
    assert client.get("/auth/me").status_code == 401
    assert user_row(db, user_id).status == "disabled"

    run = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert run["status"] == "completed" and run["deleted"]["oauth_transactions"] == 1
    assert count(db, OAuthTransaction) == 0
