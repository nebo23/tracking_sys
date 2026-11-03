"""Durable encrypted mail outbox with an explicitly local development transport."""

import json
from datetime import timedelta
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import MailOutbox
from app.security import now_utc


def queue_mail(session: Session, settings: Settings, email: str, purpose: str, token: str) -> None:
    identifier = uuid4()
    paths = {"verify": "verify-email", "reset": "reset-password", "invitation": "accept-invitation"}
    link = f"{settings.frontend_origin}/auth/{paths[purpose]}#token={token}"
    subject = {
        "verify": "Verify your email",
        "reset": "Reset your password",
        "invitation": "Agency invitation",
    }[purpose]
    payload = {
        "to": email,
        "subject": subject,
        "body": f"{subject}\n\n{link}\n\nIf you did not request this, ignore this message.\n",
    }
    encrypted = (
        Fernet(settings.mail_encryption_key.get_secret_value().encode())
        .encrypt(json.dumps(payload).encode())
        .decode()
    )
    session.add(MailOutbox(id=identifier, purpose=purpose, encrypted_payload=encrypted))


def deliver_local(message: MailOutbox, settings: Settings) -> None:
    if settings.environment != "development" or settings.mail_mode != "local":
        raise RuntimeError("External email delivery is not configured.")
    if message.encrypted_payload is None:
        raise ValueError("Message payload unavailable.")
    payload = json.loads(
        Fernet(settings.mail_encryption_key.get_secret_value().encode()).decrypt(
            message.encrypted_payload.encode()
        )
    )
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


def process_mail(engine: Engine, settings: Settings, *, limit: int = 50) -> dict[str, int]:
    if not 1 <= limit <= 100:
        raise ValueError("Mail batch size must be between 1 and 100.")
    results = {"delivered": 0, "failed": 0}
    for _ in range(limit):
        with Session(engine) as session, session.begin():
            message = session.scalar(
                select(MailOutbox)
                .where(MailOutbox.delivered_at.is_(None), MailOutbox.next_attempt_at <= now_utc())
                .order_by(MailOutbox.created_at, MailOutbox.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if message is None:
                break
            message.attempts += 1
            try:
                deliver_local(message, settings)
            except (OSError, ValueError, InvalidToken, RuntimeError):
                message.failure_code = "local_delivery_failed"
                message.next_attempt_at = now_utc() + timedelta(
                    seconds=min(3600, 2 ** min(message.attempts, 10))
                )
                results["failed"] += 1
            else:
                message.delivered_at = now_utc()
                message.encrypted_payload, message.failure_code = None, None
                results["delivered"] += 1
    return results
