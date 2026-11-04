"""Real PostgreSQL HTTP tests for identity, sessions, recovery, and local delivery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import (
    AuthRateLimit,
    AuthSession,
    AuthToken,
    MailOutbox,
    PasswordCredential,
    User,
    VerificationChallenge,
)
from app.security import RateLimited, digest, now_utc, verify_password
from app.services.auth import enforce_rate_limit
from app.services.mail import deliver_local, process_mail

pytestmark = pytest.mark.integration
EMAIL = "synthetic@example.test"


def register(api, client=None, email=EMAIL, password=None):
    return (client or api.client).post(
        "/auth/register",
        json={
            "email": email,
            "display_name": "Synthetic Person",
            "password": password or api.password,
        },
    )


def verify_code(client, code, email=EMAIL):
    return client.post("/auth/verify-email-code", json={"email": email, "code": code})


def verified(api):
    assert register(api).status_code == 202
    code = api.mail_tokens()[-1][2]
    assert verify_code(api.client, code).status_code == 204
    return code


def test_registration_verification_and_authenticated_agency_flow(api, db):
    assert register(api).status_code == 202
    assert (
        api.client.post(
            "/auth/login",
            json={
                "email": EMAIL,
                "password": api.password,
            },
        ).status_code
        == 403
    )
    with Session(db.migration) as session:
        user = session.scalar(select(User))
        stored = session.get(PasswordCredential, user.id).password_hash
        assert stored.startswith("$argon2id$") and api.password not in stored
        assert verify_password(api.password, stored)
        encrypted = session.scalar(select(MailOutbox.encrypted_payload))
        assert EMAIL not in encrypted and "#token" not in encrypted
    code = api.mail_tokens()[-1][2]
    with Session(db.migration) as session:
        verifier = session.scalar(select(VerificationChallenge.verifier))
        assert len(verifier) == 64 and code not in verifier and verifier != digest(code)
        assert session.scalar(select(MailOutbox.encrypted_payload)) is None
    assert verify_code(api.client, code).status_code == 204
    login = api.login(api.client, EMAIL)
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Domain=" not in cookie
    assert login.headers["cache-control"] == "no-store"
    assert login.headers["referrer-policy"] == "no-referrer"
    raw = api.client.cookies[api.config.cookie_name]
    assert raw not in login.text
    with Session(db.migration) as session:
        assert session.scalar(select(AuthSession.token_digest)) == digest(raw)
    assert api.client.get("/auth/me").json() == login.json()
    agency = api.client.post("/agencies", json={"name": "Synthetic Agency"})
    assert agency.status_code == 201
    aid = agency.json()["id"]
    assert api.client.get("/agencies").json() == [{"agency_id": aid, "role": "owner"}]
    client = api.client.post(f"/agencies/{aid}/clients", json={"name": "Synthetic Client"})
    assert client.status_code == 201
    assert api.client.get(f"/agencies/{aid}/clients").json() == [client.json()]
    assert api.client.post("/auth/logout").status_code == 204
    assert api.client.get("/auth/me").status_code == 401


def test_duplicate_registration_is_generic_and_preserves_password(api, db):
    first = register(api)
    second = register(api, email=EMAIL.upper(), password="Different synthetic password")
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    with Session(db.migration) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(MailOutbox)) == 1
        assert verify_password(
            api.password, session.scalar(select(PasswordCredential.password_hash))
        )


def test_concurrent_registration_creates_one_identity(api, db):
    clients = [api.new_client(), api.new_client()]
    barrier = Barrier(2)

    def submit(client):
        barrier.wait(timeout=10)
        return register(api, client).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(submit, clients)) == [202, 202]
    with Session(db.migration) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(VerificationChallenge)) == 1


@pytest.mark.parametrize("action", ["reuse", "expiry", "resend", "wrong_email"])
def test_verification_rejects_invalid_codes(api, db, action):
    assert register(api).status_code == 202
    code = api.mail_tokens()[-1][2]
    email = EMAIL
    if action == "reuse":
        assert verify_code(api.client, code).status_code == 204
    elif action == "expiry":
        with Session(db.migration) as session, session.begin():
            session.execute(
                update(VerificationChallenge).values(expires_at=now_utc() - timedelta(seconds=1))
            )
    elif action == "resend":
        with Session(db.migration) as session, session.begin():
            session.execute(
                update(VerificationChallenge).values(created_at=now_utc() - timedelta(minutes=2))
            )
        assert (
            api.client.post("/auth/resend-verification", json={"email": EMAIL}).status_code == 202
        )
        assert api.mail_tokens()[-1][2] is not None
    else:
        email = "other.person@example.test"
    response = verify_code(api.client, code, email)
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_or_expired_code"}


def test_concurrent_code_consumption_has_one_winner(api):
    register(api)
    code = api.mail_tokens()[-1][2]
    clients = [api.new_client(), api.new_client()]
    barrier = Barrier(2)

    def consume(client):
        barrier.wait(timeout=10)
        return verify_code(client, code).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(consume, clients)) == [204, 400]


def test_secure_cookie_and_cors_are_explicit(api):
    verified(api)
    secure = api.new_client(api.config.model_copy(update={"cookie_secure": True}))
    response = api.login(secure, EMAIL)
    cookie = response.headers["set-cookie"]
    assert "__Host-tracking_session=" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "Path=/" in cookie
    allowed = api.client.options(
        "/auth/login",
        headers={
            "Access-Control-Request-Method": "POST",
        },
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    denied = api.client.options(
        "/auth/login",
        headers={
            "Origin": "https://untrusted.invalid",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize("mode", ["expired", "superseded"])
def test_reset_rejects_expired_or_superseded_tokens(api, db, mode):
    verified(api)
    assert api.client.post("/auth/forgot-password", json={"email": EMAIL}).status_code == 202
    token = [t for _, subject, t in api.mail_tokens() if subject == "Reset your password"][-1]
    if mode == "expired":
        with Session(db.migration) as session, session.begin():
            session.execute(
                update(AuthToken)
                .where(AuthToken.purpose == "reset")
                .values(
                    expires_at=now_utc() - timedelta(seconds=1),
                )
            )
    else:
        assert api.client.post("/auth/forgot-password", json={"email": EMAIL}).status_code == 202
    assert (
        api.client.post(
            "/auth/reset-password",
            json={
                "token": token,
                "password": "Replacement synthetic password",
            },
        ).status_code
        == 400
    )
    api.login(api.client, EMAIL)


def test_recovery_is_generic_and_reset_revokes_all_sessions(api):
    verified(api)
    api.login(api.client, EMAIL)
    other = api.new_client()
    api.login(other, EMAIL)
    existing = api.client.post("/auth/forgot-password", json={"email": EMAIL})
    missing = api.client.post("/auth/forgot-password", json={"email": "absent@example.test"})
    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json()
    token = [t for _, subject, t in api.mail_tokens() if subject == "Reset your password"][-1]
    replacement = "Replacement synthetic password 123!"
    result = api.client.post("/auth/reset-password", json={"token": token, "password": replacement})
    assert result.status_code == 204
    assert other.get("/auth/me").status_code == 401
    assert (
        api.client.post(
            "/auth/reset-password", json={"token": token, "password": replacement}
        ).status_code
        == 400
    )
    assert (
        api.client.post("/auth/login", json={"email": EMAIL, "password": api.password}).status_code
        == 401
    )
    api.login(api.client, EMAIL, replacement)


def test_password_change_needs_old_password_and_revokes_other_sessions(api):
    verified(api)
    api.login(api.client, EMAIL)
    other = api.new_client()
    api.login(other, EMAIL)
    replacement = "Replacement synthetic password 123!"
    payload = {"current_password": "wrong", "new_password": replacement}
    assert api.client.post("/auth/change-password", json=payload).status_code == 401
    payload["current_password"] = api.password
    assert api.client.post("/auth/change-password", json=payload).status_code == 204
    assert other.get("/auth/me").status_code == 401
    api.login(api.client, EMAIL, replacement)


def test_independent_security_commits_work_with_request_pool_exhausted(api):
    from contextlib import ExitStack

    verified(api)
    api.login(api.client, EMAIL)
    # One remaining connection is needed by authentication; all others are occupied.
    # The rate counter must not wait for a second connection from that same full pool.
    with ExitStack() as stack:
        engine = api.client.app.state.engine
        for _ in range(engine.pool.size() - 1):
            stack.enter_context(engine.connect())
        response = api.client.post(
            "/auth/change-password",
            json={
                "current_password": api.password,
                "new_password": "Replacement synthetic password",
            },
        )
    assert response.status_code == 204


@pytest.mark.parametrize("mode", ["logout", "logout-all", "idle", "absolute", "disabled"])
def test_session_revocation_and_expiry(api, db, mode):
    verified(api)
    api.login(api.client, EMAIL)
    other = api.new_client()
    api.login(other, EMAIL)
    raw = api.client.cookies[api.config.cookie_name]
    if mode in {"logout", "logout-all"}:
        assert api.client.post(f"/auth/{mode}").status_code == 204
        api.client.cookies.set(api.config.cookie_name, raw)
    else:
        with Session(db.migration) as session, session.begin():
            if mode == "disabled":
                session.execute(update(User).values(status="disabled"))
            else:
                column = "last_seen_at" if mode == "idle" else "expires_at"
                session.execute(
                    update(AuthSession).values(**{column: now_utc() - timedelta(days=2)})
                )
    assert api.client.get("/auth/me").status_code == 401
    assert other.get("/auth/me").status_code == (200 if mode == "logout" else 401)


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://untrusted.invalid"},
        {"Origin": "null"},
        {"X-CSRF-Token": ""},
        {"X-CSRF-Token": "wrong"},
    ],
)
def test_cookie_mutations_require_origin_and_session_csrf(api, headers):
    verified(api)
    api.login(api.client, EMAIL)
    result = api.client.post("/agencies", json={"name": "Forbidden"}, headers=headers)
    assert result.status_code == 403


def test_csrf_cannot_be_reused_across_sessions_and_missing_origin_is_denied(api):
    verified(api)
    api.login(api.client, EMAIL)
    other = api.new_client()
    api.login(other, EMAIL)
    result = other.post(
        "/agencies",
        json={"name": "Forbidden"},
        headers={
            "X-CSRF-Token": api.client.headers["X-CSRF-Token"],
        },
    )
    assert result.status_code == 403
    del other.headers["Origin"]
    assert (
        other.post("/auth/login", json={"email": EMAIL, "password": api.password}).status_code
        == 403
    )


def test_failed_login_rate_limits_are_shared_and_persist_after_rollback(api, db):
    config = api.config.model_copy(update={"login_attempts_per_minute": 2})
    clients = [api.new_client(config), api.new_client(config)]
    payload = {"email": EMAIL, "password": "incorrect"}
    for client in clients:
        assert client.post("/auth/login", json=payload).status_code == 401
    blocked = clients[0].post("/auth/login", json=payload)
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    with Session(db.migration) as session, session.begin():
        rows = list(session.scalars(select(AuthRateLimit)))
        assert all(len(row.bucket_key) == 64 and EMAIL not in row.bucket_key for row in rows)
        session.execute(update(AuthRateLimit).values(expires_at=now_utc() - timedelta(seconds=1)))
    assert clients[1].post("/auth/login", json=payload).status_code == 401


def test_concurrent_rate_limit_cannot_oversubscribe(api, db):
    def attempt(_):
        try:
            enforce_rate_limit(
                db.runtime, api.config, "synthetic-race", "fixture", limit=3, period=60
            )
            return True
        except RateLimited:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(attempt, range(8))) == 3


def test_validation_body_limit_and_errors_do_not_echo_secrets(api, capsys):
    secret = "short-secret"
    response = register(api, password=secret)
    assert response.status_code == 422 and secret not in response.text
    oversized = api.client.post("/auth/register", content=b"x" * 16385)
    assert oversized.status_code == 413
    response = api.client.post("/auth/login", json={"email": EMAIL, "password": secret})
    assert response.status_code == 401 and secret not in response.text
    assert secret not in capsys.readouterr().err
    assert api.client.get("/agencies").status_code == 401
    assert api.client.get("/auth/google").status_code == 404
    assert api.client.get("/auth/facebook").status_code == 404


def test_mail_failure_retries_idempotently_and_clears_payload(api, db):
    register(api)
    directory = api.config.mail_directory
    directory.write_text("A file deliberately obstructs the mail directory.")
    assert process_mail(db.runtime, api.config) == {"delivered": 0, "failed": 1, "expired": 0}
    with Session(db.migration) as session, session.begin():
        message = session.scalar(select(MailOutbox))
        assert message.failure_code == "local_delivery_failed" and message.encrypted_payload
        assert message.next_attempt_at > now_utc()
        message.next_attempt_at = now_utc() - timedelta(seconds=1)
    directory.unlink()
    # Simulate delivery succeeding before its database transaction can commit.
    with Session(db.runtime) as session:
        message = session.scalar(select(MailOutbox))
        deliver_local(message, api.config)
    first = next(directory.glob("*.eml")).read_bytes()
    assert process_mail(db.runtime, api.config) == {"delivered": 1, "failed": 0, "expired": 0}
    assert next(directory.glob("*.eml")).read_bytes() == first
    assert process_mail(db.runtime, api.config) == {"delivered": 0, "failed": 0, "expired": 0}
    with Session(db.migration) as session:
        message = session.scalar(select(MailOutbox))
        assert message.encrypted_payload is None and message.delivered_at is not None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE security_events SET action='logout'",
        "DELETE FROM security_events",
        "TRUNCATE security_events",
        "UPDATE users SET created_at = now()",
        "UPDATE users SET id = gen_random_uuid()",
        "DELETE FROM users",
        "DELETE FROM auth_sessions",
    ],
)
def test_auth_runtime_privileges_remain_restricted(db, statement):
    with pytest.raises(DBAPIError), db.runtime.begin() as connection:
        connection.execute(text(statement))
