"""Numeric email verification, legacy-link transition, and outbox expiry (D-022)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    AuthToken,
    MailOutbox,
    PasswordCredential,
    SecurityEvent,
    User,
    VerificationChallenge,
)
from app.security import digest, now_utc
from app.services.mail import process_mail

pytestmark = pytest.mark.integration
EMAIL = "code.person@example.test"


def register(client, password, email=EMAIL):
    body = {"email": email, "display_name": "Code Person", "password": password}
    assert client.post("/auth/register", json=body).status_code == 202


def verify(client, code, email=EMAIL):
    return client.post("/auth/verify-email-code", json={"email": email, "code": code})


def codes(api):
    return [value for _, subject, value in api.mail_tokens() if subject == "Verify your email"]


def other_codes(code, count):
    return [f"{(int(code) + step) % 1_000_000:06d}" for step in range(1, count + 1)]


def age_challenges(db, seconds=120):
    with Session(db.migration) as session, session.begin():
        session.execute(
            update(VerificationChallenge).values(created_at=now_utc() - timedelta(seconds=seconds))
        )


def test_leading_zero_code_is_preserved_and_format_is_bounded(api, monkeypatch):
    monkeypatch.setattr("app.services.auth.new_verification_code", lambda: "000123")
    register(api.client, api.password)
    assert codes(api) == ["000123"]
    assert verify(api.client, "123").status_code == 422
    assert verify(api.client, "0001234").status_code == 422
    assert verify(api.client, "000123").status_code == 204
    api.login(api.client, EMAIL)


def test_failed_checks_persist_and_exhaust_the_challenge(api, db):
    register(api.client, api.password)
    (code,) = codes(api)
    for wrong in other_codes(code, 5):
        response = verify(api.client, wrong)
        assert response.status_code == 400
        assert response.json() == {"error": "invalid_or_expired_code"}
    with Session(db.migration) as session:
        assert session.scalar(select(VerificationChallenge.failed_attempts)) == 5
        assert (
            session.scalar(
                select(func.count())
                .select_from(SecurityEvent)
                .where(SecurityEvent.action == "verification_code_failed")
            )
            == 5
        )
    # The correct code no longer works once the challenge reached five failed checks.
    assert verify(api.client, code).status_code == 400
    age_challenges(db)
    assert api.client.post("/auth/resend-verification", json={"email": EMAIL}).status_code == 202
    assert verify(api.client, codes(api)[-1]).status_code == 204


def test_daily_failure_cap_is_per_email_and_indistinguishable(api):
    settings = api.config.model_copy(update={"verification_daily_failures": 2})
    client = api.new_client(settings)
    register(client, api.password)
    (code,) = codes(api)
    wrong = other_codes(code, 2)
    assert [verify(client, item).status_code for item in wrong] == [400, 400]
    limited = verify(client, code)
    assert limited.status_code == 429 and limited.json() == {"error": "rate_limited"}
    assert 1 <= int(limited.headers["Retry-After"]) <= 86401
    # An unknown email follows the same path: two generic failures, then the same limit.
    absent = "absent.person@example.test"
    assert [verify(client, "123456", absent).status_code for _ in range(2)] == [400, 400]
    assert verify(client, "123456", absent).status_code == 429


def test_resend_cooldown_keeps_the_latest_code(api, db):
    register(api.client, api.password)
    (code,) = codes(api)
    assert api.client.post("/auth/resend-verification", json={"email": EMAIL}).status_code == 202
    assert codes(api) == [code]
    age_challenges(db)
    assert api.client.post("/auth/resend-verification", json={"email": EMAIL}).status_code == 202
    first, latest = codes(api)
    assert first == code
    assert verify(api.client, code).status_code == 400
    assert verify(api.client, latest).status_code == 204


def test_legacy_verification_links_are_honored_until_resend(api, db, test_password_hash):
    raw_first = "synthetic-legacy-verification-token-000000000001"
    raw_second = "synthetic-legacy-verification-token-000000000002"
    with Session(db.migration) as session, session.begin():
        for email, raw in (
            ("legacy.one@example.test", raw_first),
            ("legacy.two@example.test", raw_second),
        ):
            user = User(email_normalized=email, display_name="Legacy")
            session.add(user)
            session.flush()
            session.add(PasswordCredential(user_id=user.id, password_hash=test_password_hash))
            session.add(
                AuthToken(
                    user_id=user.id,
                    token_digest=digest(raw),
                    purpose="verify",
                    expires_at=now_utc() + timedelta(hours=1),
                )
            )
    assert api.client.post("/auth/verify-email", json={"token": raw_first}).status_code == 204
    api.login(api.client, "legacy.one@example.test")
    # A resend issues a code and consumes the outstanding legacy link.
    email = "legacy.two@example.test"
    assert api.client.post("/auth/resend-verification", json={"email": email}).status_code == 202
    assert api.client.post("/auth/verify-email", json={"token": raw_second}).status_code == 400
    assert verify(api.client, codes(api)[-1], email).status_code == 204


def test_expired_code_message_is_cleared_without_delivery(api, db):
    register(api.client, api.password)
    with Session(db.migration) as session, session.begin():
        message = session.scalar(select(MailOutbox))
        assert message.expires_at is not None
        assert message.expires_at <= now_utc() + timedelta(minutes=10, seconds=5)
        message.expires_at = now_utc() - timedelta(seconds=1)
    assert process_mail(db.runtime, api.config) == {"delivered": 0, "failed": 0, "expired": 1}
    with Session(db.migration) as session:
        message = session.scalar(select(MailOutbox))
        assert message.encrypted_payload is None and message.delivered_at is None
        assert message.failure_code == "expired_before_delivery"
    assert not list(api.config.mail_directory.glob("*.eml"))


class RecordingSender:
    """Controlled Gmail substitute: records payloads or raises a configured failure."""

    def __init__(self, failure=None):
        self.failure, self.sent = failure, []

    def send(self, message_id, payload):
        if self.failure is not None:
            raise self.failure
        self.sent.append((message_id, payload))


def test_gmail_mode_uses_the_sender_and_records_sanitized_failures(api, db):
    from app.services.gmail import GmailError

    register(api.client, api.password)
    settings = api.config.model_copy(update={"mail_mode": "gmail"})
    failing = RecordingSender(GmailError("gmail_rate_limited"))
    assert process_mail(db.runtime, settings, sender=failing) == {
        "delivered": 0,
        "failed": 1,
        "expired": 0,
    }
    with Session(db.migration) as session, session.begin():
        message = session.scalar(select(MailOutbox))
        assert message.failure_code == "gmail_rate_limited" and message.encrypted_payload
        message.next_attempt_at = now_utc() - timedelta(seconds=1)
    working = RecordingSender()
    assert process_mail(db.runtime, settings, sender=working)["delivered"] == 1
    (_, payload), *_ = working.sent
    assert payload["to"] == EMAIL and payload["subject"] == "Verify your email"
    assert "verification code: " in payload["body"]
    with Session(db.migration) as session:
        message = session.scalar(select(MailOutbox))
        assert message.encrypted_payload is None and message.delivered_at is not None
    assert not list(api.config.mail_directory.glob("*.eml"))


def test_google_only_account_sets_first_password_through_reset(api, db):
    email = "google.only@gmail.com"
    with Session(db.migration) as session, session.begin():
        session.add(
            User(email_normalized=email, display_name="Google Only", email_verified_at=now_utc())
        )
    assert api.client.post("/auth/forgot-password", json={"email": email}).status_code == 202
    token = [t for _, subject, t in api.mail_tokens() if subject == "Reset your password"][-1]
    password = "Synthetic first password 123!"
    body = {"token": token, "password": password}
    assert api.client.post("/auth/reset-password", json=body).status_code == 204
    api.login(api.client, email, password)
    with Session(db.migration) as session:
        assert session.scalar(select(func.count()).select_from(PasswordCredential)) == 1


def test_populated_identity_schema_cannot_be_downgraded(api, db):
    from alembic import command
    from alembic.config import Config

    from app.config import BACKEND_ROOT
    from app.database import expected_revision, readiness_failure

    register(api.client, api.password)
    with pytest.raises(RuntimeError, match="non-empty identity state"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0003_auth")
    assert readiness_failure(db.runtime, expected_revision()) is None
    assert verify(api.client, codes(api)[-1]).status_code == 204


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM verification_challenges",
        "UPDATE verification_challenges SET verifier = 'x'",
        "UPDATE verification_challenges SET user_id = user_id",
        "DELETE FROM oauth_transactions",
        "UPDATE oauth_transactions SET state_digest = 'x'",
        "DELETE FROM external_identities",
        "UPDATE external_identities SET subject = 'x'",
        "UPDATE external_identities SET user_id = user_id",
    ],
)
def test_identity_runtime_privileges_remain_restricted(db, statement):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError), db.runtime.begin() as connection:
        connection.execute(text(statement))
