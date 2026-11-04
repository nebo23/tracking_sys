"""Session-binding and serialized verification regressions for R-01 through R-03."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
import test_google as google_tests
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session
from test_google import count, finish

from app.database import create_database_engine
from app.models import (
    AuthRateLimit,
    AuthSession,
    ExternalIdentity,
    OAuthTransaction,
    User,
    VerificationChallenge,
)
from app.security import AuthError, RateLimited, digest, keyed_digest, now_utc
from app.services import auth as auth_module
from app.services.auth import AuthService

pytestmark = pytest.mark.integration
google_provider = google_tests.google


@pytest.mark.parametrize(
    "change",
    [
        "logout",
        "logout-all",
        "change-password",
        "reset-password",
        "absolute-expiry",
        "idle-expiry",
        "switch-user",
        "same-user-new-session",
        "legacy-binding",
    ],
)
def test_pending_google_link_requires_original_live_session(
    api,
    db,
    google_provider,
    authenticated_world,
    change,
):
    browser, provider = google_provider
    client = browser()
    api.login(client, "owner_a@example.test")
    settings = client.app.state.settings
    original_cookie = client.cookies.get(settings.cookie_name)
    response = client.post("/auth/google/link")
    assert response.status_code == 200
    params = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    if change in {"logout", "logout-all"}:
        assert client.post("/auth/" + change).status_code == 204
    elif change == "change-password":
        assert (
            client.post(
                "/auth/change-password",
                json={
                    "current_password": api.password,
                    "new_password": "New synthetic password 456!",
                },
            ).status_code
            == 204
        )
    elif change == "reset-password":
        assert (
            client.post("/auth/forgot-password", json={"email": "owner_a@example.test"}).status_code
            == 202
        )
        token = [v for _, s, v in api.mail_tokens() if s == "Reset your password"][-1]
        assert (
            client.post(
                "/auth/reset-password",
                json={
                    "token": token,
                    "password": "New synthetic password 456!",
                },
            ).status_code
            == 204
        )
    elif change in {"absolute-expiry", "idle-expiry", "legacy-binding"}:
        with Session(db.migration) as session, session.begin():
            item = session.scalar(
                select(AuthSession).where(AuthSession.token_digest == digest(original_cookie))
            )
            if change == "absolute-expiry":
                item.expires_at = now_utc() - timedelta(seconds=1)
            elif change == "idle-expiry":
                item.last_seen_at = now_utc() - timedelta(seconds=settings.session_idle_seconds + 1)
            else:
                transaction = session.scalar(select(OAuthTransaction))
                transaction.binding_digest = digest(client.cookies.get(settings.oauth_cookie_name))
    else:
        # Both replacement sessions are valid, but neither initiated this transaction.
        email = "owner_b@example.test" if change == "switch-user" else "owner_a@example.test"
        api.login(client, email)
    if change in {"logout", "logout-all", "change-password", "reset-password"}:
        # An attacker can retain the revoked cookie; deletion in the honest browser is not
        # the security boundary. Restore it to prove server-side invalidation is enforced.
        client.cookies.set(
            settings.cookie_name, original_cookie, domain="localhost.local", path="/"
        )
    _, result = finish(client, provider, params, sub="regression-link-subject")
    assert result == {"error": ["google_sign_in_failed"]}
    assert count(db, ExternalIdentity) == 0


def test_logout_all_during_provider_exchange_prevents_link(
    api,
    db,
    google_provider,
    authenticated_world,
    monkeypatch,
):
    browser, provider = google_provider
    client, revoker = browser(), browser()
    api.login(client, "owner_a@example.test")
    settings = client.app.state.settings
    revoker.cookies.set(settings.cookie_name, client.cookies.get(settings.cookie_name))
    revoker.headers["X-CSRF-Token"] = client.headers["X-CSRF-Token"]
    response = client.post("/auth/google/link")
    params = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    reached, release = threading.Event(), threading.Event()
    original = provider.exchange

    def delayed_exchange(*args):
        result = original(*args)
        reached.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(provider, "exchange", delayed_exchange)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(finish, client, provider, params)
        try:
            assert reached.wait(3)
            assert revoker.post("/auth/logout-all").status_code == 204
        finally:
            release.set()
        _, result = future.result(timeout=5)
    assert result == {"error": ["google_sign_in_failed"]}
    assert count(db, ExternalIdentity) == 0


def register_code(api, db):
    email = "regression.otp@example.test"
    assert (
        api.client.post(
            "/auth/register",
            json={
                "email": email,
                "display_name": "Regression",
                "password": api.password,
            },
        ).status_code
        == 202
    )
    code = [v for _, s, v in api.mail_tokens() if s == "Verify your email"][-1]
    with Session(db.migration) as session:
        challenge = session.scalar(select(VerificationChallenge))
        return email, code, challenge.id, challenge.user_id


@pytest.mark.parametrize("competitor", ["correct-code", "resend"])
def test_final_failure_serializes_with_correct_code_and_resend(api, db, monkeypatch, competitor):
    email, code, challenge_id, user_id = register_code(api, db)
    bucket = keyed_digest(api.config, "rate:verify-code-failures", email)
    with Session(db.migration) as session, session.begin():
        item = session.get(VerificationChallenge, challenge_id)
        item.failed_attempts = 4
        item.created_at = now_utc() - timedelta(minutes=2)
        session.add(
            AuthRateLimit(bucket_key=bucket, attempts=9, expires_at=now_utc() + timedelta(days=1))
        )
    reached, release, started = threading.Event(), threading.Event(), threading.Event()
    original = auth_module.verification_verifier
    comparisons, worker_pid = [], []

    def delayed_verifier(*args):
        comparisons.append(args[-1])
        if len(comparisons) == 1:
            reached.set()
            assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(auth_module, "verification_verifier", delayed_verifier)
    security = create_database_engine(api.config, pool_size=2)

    def operation(first):
        try:
            with Session(db.runtime) as session, session.begin():
                if not first:
                    worker_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                    started.set()
                service = AuthService(session, api.config)
                if not first and competitor == "resend":
                    service.request_verification(email)
                    return "resent"
                submitted = f"{(int(code) + 1) % 1000000:06d}" if first else code
                service.verify_email_code(email, submitted, security)
        except AuthError:
            return "invalid"
        except RateLimited:
            return "limited"
        return "accepted"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(operation, True)
            try:
                assert reached.wait(3)
                second = pool.submit(operation, False)
                assert started.wait(2)
                with db.runtime.connect() as monitor:
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        waiting = monitor.execute(
                            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                            {"pid": worker_pid[0]},
                        ).scalar_one()
                        monitor.commit()
                        if waiting == "Lock":
                            break
                        time.sleep(0.01)
                    else:
                        pytest.fail("Competing operation did not serialize before comparison")
            finally:
                release.set()
            assert first.result(timeout=4) == "invalid"
            assert second.result(timeout=4) == ("resent" if competitor == "resend" else "limited")
    finally:
        security.dispose()
    with Session(db.migration) as session:
        assert session.get(VerificationChallenge, challenge_id).failed_attempts == 5
        assert session.get(AuthRateLimit, bucket).attempts == 10
        assert session.get(User, user_id).email_verified_at is None
        if competitor == "resend":
            assert session.get(VerificationChallenge, challenge_id).invalidated_at is not None
    # A resend does not reset the account budget, even for its newly issued valid code.
    if competitor == "resend":
        latest = [v for _, s, v in api.mail_tokens() if s == "Verify your email"][-1]
        assert (
            api.client.post(
                "/auth/verify-email-code", json={"email": email, "code": latest}
            ).status_code
            == 429
        )


@pytest.mark.parametrize("daily", [0, 9])
def test_concurrent_wrong_codes_cannot_share_last_challenge_allowance(api, db, monkeypatch, daily):
    email, code, challenge_id, _ = register_code(api, db)
    bucket = keyed_digest(api.config, "rate:verify-code-failures", email)
    with Session(db.migration) as session, session.begin():
        session.get(VerificationChallenge, challenge_id).failed_attempts = 4
        session.add(
            AuthRateLimit(
                bucket_key=bucket, attempts=daily, expires_at=now_utc() + timedelta(days=1)
            )
        )
    start, release = threading.Barrier(4, timeout=5), threading.Event()
    guard = threading.Lock()
    comparisons, pids = [], []
    original = auth_module.verification_verifier

    def paused(*args):
        with guard:
            comparisons.append(1)
        assert release.wait(4)
        return original(*args)

    monkeypatch.setattr(auth_module, "verification_verifier", paused)
    security = create_database_engine(api.config, pool_size=3)

    def attempt(index):
        try:
            with Session(db.runtime) as session, session.begin():
                pids.append(session.scalar(text("SELECT pg_backend_pid()")))
                start.wait()
                AuthService(session, api.config).verify_email_code(
                    email,
                    f"{(int(code) + index) % 1000000:06d}",
                    security,
                )
        except AuthError:
            return 400
        except RateLimited:
            return 429
        return 204

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(attempt, i) for i in (1, 2, 3)]
            try:
                start.wait()
                deadline = time.monotonic() + 2
                # The fixed implementation blocks two database sessions. The old one lets
                # all three reach comparison; release either schedule and assert the budget.
                with db.runtime.connect() as monitor:
                    while time.monotonic() < deadline:
                        waiting = monitor.execute(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE pid = ANY(:pids) AND wait_event_type = 'Lock'"
                            ),
                            {"pids": pids},
                        ).scalar_one()
                        monitor.commit()
                        if waiting == 2 or len(comparisons) == 3:
                            break
                        time.sleep(0.01)
                    else:
                        pytest.fail("Workers did not reach the controlled concurrency schedule")
            finally:
                release.set()
            outcomes = [future.result(timeout=5) for future in futures]
    finally:
        security.dispose()
    assert len(comparisons) == 1
    assert sorted(outcomes) == ([400, 429, 429] if daily else [400, 400, 400])
    with Session(db.migration) as session:
        assert session.get(VerificationChallenge, challenge_id).failed_attempts == 5
        assert session.get(AuthRateLimit, bucket).attempts == (10 if daily else 3)


@pytest.mark.parametrize("lock_model", [User, VerificationChallenge])
def test_code_expiring_during_lock_wait_is_not_consumed(api, db, lock_model):
    email, code, challenge_id, user_id = register_code(api, db)
    expiry = now_utc() + timedelta(seconds=1.2)
    with Session(db.migration) as session, session.begin():
        session.get(VerificationChallenge, challenge_id).expires_at = expiry
    reached = threading.Event()

    def query_started(conn, cursor, statement, parameters, context, executemany):
        if lock_model.__tablename__ in statement and "FOR " in statement:
            reached.set()

    event.listen(db.runtime, "before_cursor_execute", query_started)
    security = create_database_engine(api.config, pool_size=2)

    def verify():
        try:
            with Session(db.runtime) as session, session.begin():
                AuthService(session, api.config).verify_email_code(email, code, security)
        except AuthError as error:
            return error.code
        return "accepted"

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with Session(db.migration) as blocker, blocker.begin():
                identifier = user_id if lock_model is User else challenge_id
                blocker.scalar(
                    select(lock_model).where(lock_model.id == identifier).with_for_update()
                )
                future = pool.submit(verify)
                assert reached.wait(2) and now_utc() < expiry
                while now_utc() <= expiry + timedelta(milliseconds=50):
                    time.sleep(0.01)
                assert not future.done()
            assert future.result(timeout=4) == "invalid_or_expired_code"
    finally:
        event.remove(db.runtime, "before_cursor_execute", query_started)
        security.dispose()
    with Session(db.migration) as session:
        assert session.get(VerificationChallenge, challenge_id).consumed_at is None
        assert session.get(User, user_id).email_verified_at is None
