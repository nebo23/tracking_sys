"""Small cryptographic primitives; passwords use the maintained Argon2 implementation."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from email_validator import EmailNotValidError, validate_email
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.config import Settings

password_hash = PasswordHash.recommended()
_dummy_hash = password_hash.hash(secrets.token_urlsafe(32))


class AuthError(Exception):
    def __init__(self, code: str = "invalid_credentials", status: int = 401) -> None:
        self.code, self.status = code, status
        super().__init__(code)


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("rate_limited")


def now_utc() -> datetime:
    return datetime.now(UTC)


def normalize_email(value: str) -> str:
    try:
        return validate_email(
            value, check_deliverability=False, test_environment=True
        ).normalized.lower()
    except EmailNotValidError as error:
        raise ValueError("A valid email address is required.") from error


def new_token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def keyed_digest(settings: Settings, purpose: str, value: str) -> str:
    return hmac.new(
        bytes.fromhex(settings.auth_secret.get_secret_value()),
        (purpose + "\0" + value).encode(),
        hashlib.sha256,
    ).hexdigest()


def csrf_token(settings: Settings, session_token: str) -> str:
    return keyed_digest(settings, "csrf", session_token)


def verify_password(password: str, stored_hash: str | None) -> bool:
    try:
        valid = password_hash.verify(password, stored_hash or _dummy_hash)
    except (UnknownHashError, ValueError):
        return False
    return valid and stored_hash is not None
