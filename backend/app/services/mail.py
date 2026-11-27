"""Durable encrypted mail outbox with local capture and an opt-in Gmail transport."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import MailOutbox
from app.security import now_utc
from app.services.gmail import GmailError, GmailSender


# Add an encrypted outbox row in the caller's transaction. Verification messages carry a
# numeric code (D-022); every message carries an expires_at matching its code or link
# (D-022, D-024), so the worker clears stale content unsent. Reset and invitation messages keep
# links that carry the raw token in the URL fragment, which
# browsers do not send to the frontend server. The payload is Fernet-encrypted with the separate
# mail key; this function neither commits nor delivers. The worker delivers after commit.
def queue_mail(
    session: Session,
    settings: Settings,
    email: str,
    purpose: str,
    secret: str,
    *,
    expires_at: datetime | None = None,
) -> None:
    identifier = uuid4()
    subject = {
        "verify": "Verify your email",
        "reset": "Reset your password",
        "invitation": "Agency invitation",
    }[purpose]
    if purpose == "verify":
        minutes = max(1, settings.verification_code_lifetime_seconds // 60)
        content = f"Your verification code: {secret}\n\nIt expires in {minutes} minutes."
    else:
        path = {"reset": "reset-password", "invitation": "accept-invitation"}[purpose]
        content = f"{settings.frontend_origin}/auth/{path}#token={secret}"
    payload = {
        "to": email,
        "subject": subject,
        "body": f"{subject}\n\n{content}\n\nIf you did not request this, ignore this message.\n",
    }
    _store(session, settings, identifier, purpose, payload, expires_at)


def _store(
    session: Session,
    settings: Settings,
    identifier: UUID,
    purpose: str,
    payload: dict[str, str],
    expires_at: datetime | None,
) -> None:
    encrypted = (
        Fernet(settings.mail_encryption_key.get_secret_value().encode())
        .encrypt(json.dumps(payload).encode())
        .decode()
    )
    session.add(
        MailOutbox(
            id=identifier, purpose=purpose, encrypted_payload=encrypted, expires_at=expires_at
        )
    )


REPORT_KINDS = {
    "social": "Social",
    "spend": "Advertising spend",
    "revenue": "Revenue",
    "attribution": "Attribution",
    "roas": "ROAS",
    "funnel": "Funnel",
}


@dataclass(frozen=True)
class ReportReady:
    """The only fields a report_ready email carries (016-C, D-095 D9): no figure, no client
    name and no token. The identifiers in the link are not secrets; the application
    authorizes the reader again."""

    display_name: str
    schedule_name: str
    family: str
    period_start: date
    period_end: date
    agency_id: UUID
    client_id: UUID
    export_id: UUID
    expires_at: datetime


def report_ready_message(settings: Settings, item: ReportReady) -> tuple[str, str]:
    subject = f"Report ready: {item.schedule_name}"
    link = (
        f"{settings.frontend_origin}/agencies/{item.agency_id}/clients/{item.client_id}"
        f"/reports/exports/{item.export_id}"
    )
    last_day = item.period_end - timedelta(days=1)
    until = item.expires_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    body = (
        f"{item.display_name}\n\n"
        f'The scheduled report "{item.schedule_name}" is ready.\n\n'
        f"Report: {REPORT_KINDS[item.family]}\n"
        f"Period: {item.period_start.isoformat()} to {last_day.isoformat()}\n\n"
        f"Open it in the application:\n{link}\n\n"
        f"The report can be downloaded until {until} UTC. You receive this message because "
        "you are a recipient of this schedule.\n"
    )
    return subject, body


# Add one encrypted report_ready message in the caller's transaction; it expires with its
# export, so an undelivered message is cleared unsent once the export is gone.
def queue_report_mail(session: Session, settings: Settings, email: str, item: ReportReady) -> None:
    subject, body = report_ready_message(settings, item)
    _store(
        session,
        settings,
        uuid4(),
        "report_ready",
        {"to": email, "subject": subject, "body": body},
        item.expires_at,
    )


# Decrypt a claimed message payload ({"to", "subject", "body"}); raises on a missing or
# undecryptable payload. Decrypted content is never logged.
def message_payload(message: MailOutbox, settings: Settings) -> dict[str, str]:
    if message.encrypted_payload is None:
        raise ValueError("Message payload unavailable.")
    return json.loads(
        Fernet(settings.mail_encryption_key.get_secret_value().encode()).decrypt(
            message.encrypted_payload.encode()
        )
    )


# Development transport: decrypt one claimed message and publish it as an .eml file named by
# the outbox ID. Any other environment or mail mode raises, so no external mail is sent. An
# identical existing file makes a retry idempotent; a differing file is refused.
def deliver_local(message: MailOutbox, settings: Settings) -> None:
    if settings.environment != "development" or settings.mail_mode != "local":
        raise RuntimeError("External email delivery is not configured.")
    payload = message_payload(message, settings)
    email = EmailMessage(policy=SMTP)
    email["From"], email["To"], email["Subject"] = (
        "development@tracking.invalid",
        payload["to"],
        payload["subject"],
    )
    email["Message-ID"] = f"<{message.id}@tracking.invalid>"
    email.set_content(payload["body"])
    settings.mail_directory.mkdir(parents=True, exist_ok=True)
    target: Path = settings.mail_directory / f"{message.id}.eml"
    content = email.as_bytes()
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("Existing local message differs; refusing replacement.")
        return
    # A complete file is atomically published; retries use the same message ID.
    temporary = target.with_suffix(".pending")
    temporary.write_bytes(content)
    temporary.replace(target)


# Deliver up to `limit` due messages, each in its own short transaction. SKIP LOCKED lets
# concurrent workers claim different rows. A message past its expires_at is cleared without
# sending. Success sets delivered_at and clears the encrypted payload; a failure records a
# sanitized code and exponential backoff capped at one hour. Local mode detects a file
# published before a failed commit; Gmail mode can deliver twice after an ambiguous timeout.
# The sender argument lets tests substitute the Gmail transport. Returns counts only.
def process_mail(
    engine: Engine, settings: Settings, *, limit: int = 50, sender: GmailSender | None = None
) -> dict[str, int]:
    if not 1 <= limit <= 100:
        raise ValueError("Mail batch size must be between 1 and 100.")
    if settings.mail_mode == "gmail" and sender is None:
        sender = GmailSender(settings)
    results = {"delivered": 0, "failed": 0, "expired": 0}
    for _ in range(limit):
        with Session(engine) as session, session.begin():
            message = session.scalar(
                select(MailOutbox)
                .where(
                    MailOutbox.delivered_at.is_(None),
                    MailOutbox.encrypted_payload.is_not(None),
                    MailOutbox.next_attempt_at <= now_utc(),
                )
                .order_by(MailOutbox.created_at, MailOutbox.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if message is None:
                break
            if message.expires_at is not None and message.expires_at <= now_utc():
                message.encrypted_payload, message.failure_code = None, "expired_before_delivery"
                results["expired"] += 1
                continue
            message.attempts += 1
            try:
                if settings.mail_mode == "gmail":
                    assert sender is not None
                    sender.send(message.id, message_payload(message, settings))
                else:
                    deliver_local(message, settings)
            except GmailError as error:
                message.failure_code = error.code
            except (OSError, ValueError, InvalidToken, RuntimeError):
                message.failure_code = (
                    "local_delivery_failed"
                    if settings.mail_mode == "local"
                    else "payload_unavailable"
                )
            else:
                message.delivered_at = now_utc()
                message.encrypted_payload, message.failure_code = None, None
                results["delivered"] += 1
                continue
            message.next_attempt_at = now_utc() + timedelta(
                seconds=min(3600, 2 ** min(message.attempts, 10))
            )
            results["failed"] += 1
    return results
