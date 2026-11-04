"""Small cryptographic primitives; passwords use the maintained Argon2 implementation."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.config import Settings

# pwdlib's recommended hasher (Argon2id). The dummy hash is computed once at import so a
# missing credential still costs one verification, reducing timing differences.
password_hash = PasswordHash.recommended()
_dummy_hash = password_hash.hash(secrets.token_urlsafe(32))


# Authentication failure carrying a public error code and HTTP status for the sanitized
# handler in main.py; the default represents generic invalid credentials.
class AuthError(Exception):
    # Store the public code/status; the exception message is the code, never secret input.
    def __init__(self, code: str = "invalid_credentials", status: int = 401) -> None:
        self.code, self.status = code, status
        super().__init__(code)


# Raised by persistent throttles when a bucket exceeds its limit.
class RateLimited(Exception):
    # retry_after is the whole number of seconds reported in the Retry-After header.
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("rate_limited")


# Timezone-aware current UTC time, used for all expiry and audit timestamps.
def now_utc() -> datetime:
    return datetime.now(UTC)


# Validate email syntax and normalize under the existing case-insensitive account policy
# without DNS or network checks. It neither proves mailbox ownership nor detects disposable or
# spam addresses, and it applies no provider-specific dot/plus rewriting.
def normalize_email(value: str) -> str:
    try:
        return validate_email(
            value, check_deliverability=False, test_environment=True
        ).normalized.lower()
    except EmailNotValidError as error:
        raise ValueError("A valid email address is required.") from error


# High-entropy URL-safe random token for sessions, links, invitations, and service keys.
def new_token() -> str:
    return secrets.token_urlsafe(32)


# SHA-256 hex digest used to store and look up high-entropy tokens. It is not password
# hashing; passwords use the Argon2 password_hash above.
def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# Purpose-separated HMAC-SHA256 under the application auth secret. It is a one-way keyed
# derivation for rate-limit buckets and CSRF values, not reversible encryption.
def keyed_digest(settings: Settings, purpose: str, value: str) -> str:
    return hmac.new(
        bytes.fromhex(settings.auth_secret.get_secret_value()),
        (purpose + "\0" + value).encode(),
        hashlib.sha256,
    ).hexdigest()


# Six-digit numeric verification code from the operating system CSPRNG. It is returned as a
# string so leading zeroes survive (D-022).
def new_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# Keyed verifier for a numeric code: HMAC-SHA256 under the independent OTP key, bound to the
# purpose, challenge, and user. A plain hash of a six-digit code could be enumerated offline,
# so only this keyed value is stored, and checks compare it in constant time.
def verification_verifier(settings: Settings, challenge_id: UUID, user_id: UUID, code: str) -> str:
    return hmac.new(
        bytes.fromhex(settings.otp_secret.get_secret_value()),
        f"email_verification\0{challenge_id}\0{user_id}\0{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


# Derive the CSRF value bound to one browser session token. Verification happens in the API
# dependencies, together with the exact Origin check.
def csrf_token(settings: Settings, session_token: str) -> str:
    return keyed_digest(settings, "csrf", session_token)


# Check a submitted password against the stored Argon2 hash. A missing credential is checked
# against the dummy hash to reduce timing differences, but it is still rejected.
def verify_password(password: str, stored_hash: str | None) -> bool:
    try:
        valid = password_hash.verify(password, stored_hash or _dummy_hash)
    except (UnknownHashError, ValueError):
        return False
    return valid and stored_hash is not None
