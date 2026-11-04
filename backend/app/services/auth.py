"""Email/password identity, server-side sessions, and single-use recovery tokens."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import Engine, case, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    AuthRateLimit,
    AuthSession,
    AuthToken,
    PasswordCredential,
    SecurityEvent,
    User,
)
from app.security import (
    AuthError,
    RateLimited,
    digest,
    keyed_digest,
    new_token,
    normalize_email,
    now_utc,
    password_hash,
    verify_password,
)
from app.services.mail import queue_mail


# Persistent fixed-window throttle shared by all API processes. The bucket key is an HMAC of
# scope and subject, so raw emails/IPs are not stored. One atomic upsert increments or restarts
# the window and commits in its own short transaction on the given (security) engine, so the
# count survives a later rollback of the request transaction. Raises RateLimited over the limit.
def enforce_rate_limit(
    engine: Engine,
    settings: Settings,
    scope: str,
    subject: str,
    *,
    limit: int,
    period: int,
) -> None:
    """Commit attempt counters independently, including attempts that fail authentication."""
    now = now_utc()
    expires = now + timedelta(seconds=period)
    stmt = insert(AuthRateLimit).values(
        bucket_key=keyed_digest(settings, "rate:" + scope, subject),
        attempts=1,
        expires_at=expires,
    )
    expired = AuthRateLimit.expires_at <= now
    stmt = stmt.on_conflict_do_update(
        index_elements=[AuthRateLimit.bucket_key],
        set_={
            "attempts": case((expired, 1), else_=AuthRateLimit.attempts + 1),
            "expires_at": case((expired, expires), else_=AuthRateLimit.expires_at),
        },
    ).returning(AuthRateLimit.attempts, AuthRateLimit.expires_at)
    with engine.begin() as connection:
        attempts, deadline = connection.execute(stmt).one()
    if attempts > limit:
        raise RateLimited(max(1, int((deadline - now).total_seconds()) + 1))


# Authentication operations within a caller-owned transaction. The service adds, locks, and
# flushes rows but never commits; the route's SessionDep (or a test's explicit transaction)
# commits or rolls back everything together, including security events and queued mail.
class AuthService:
    # Bind the caller's database Session and the validated application settings.
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session, self.settings = session, settings

    # Append a security event in the current transaction; it commits only if the caller commits.
    def event(self, action: str, user_id: UUID | None = None) -> None:
        self.session.add(SecurityEvent(action=action, user_id=user_id))

    # Lock the active user row with SELECT ... FOR NO KEY UPDATE. That mode still conflicts with
    # itself, so credential, verification, and session changes for one user stay serialized,
    # but it is compatible with the FOR KEY SHARE locks taken by foreign keys. Other
    # transactions can therefore insert audit/membership rows that reference this user (for
    # example invitation acceptance attributed to an inviter) without a user/agency lock
    # cycle. These locks protect only non-key user columns. populate_existing refreshes stale
    # identity-map state. A missing or disabled user raises the generic AuthError.
    def _lock_user(self, user_id: UUID) -> User:
        user = self.session.scalar(
            select(User)
            .where(User.id == user_id, User.status == "active")
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise AuthError()
        return user

    # Find and lock an active user by normalized email with the same FOR NO KEY UPDATE mode as
    # _lock_user; returns None when absent so callers can keep generic responses.
    def _user_by_email(self, email: str) -> User | None:
        return self.session.scalar(
            select(User)
            .where(User.email_normalized == normalize_email(email), User.status == "active")
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )

    # Issue a single-use token for "verify" or "reset" and return None. Prior unconsumed tokens
    # are consumed only for the same user and purpose; the SHA-256 digest is persisted, and an
    # encrypted outbox message containing a link with the raw token is queued. It neither
    # commits nor sends mail; a worker delivers queued messages after the caller commits.
    def _issue_token(self, user: User, purpose: str) -> None:
        now = now_utc()
        self.session.execute(
            update(AuthToken)
            .where(
                AuthToken.user_id == user.id,
                AuthToken.purpose == purpose,
                AuthToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        raw = new_token()
        lifetime = (
            self.settings.verification_lifetime_seconds
            if purpose == "verify"
            else self.settings.reset_lifetime_seconds
        )
        self.session.add(
            AuthToken(
                user_id=user.id,
                token_digest=digest(raw),
                purpose=purpose,
                expires_at=now + timedelta(seconds=lifetime),
            )
        )
        queue_mail(self.session, self.settings, user.email_normalized, purpose, raw)

    # Create an unverified active account with its password credential, a verification token,
    # an encrypted outbox entry, and a security event in the caller's transaction. A
    # transaction-scoped advisory lock per email serializes duplicate registrations; an
    # existing email returns silently without changing that account or its password.
    def register(self, email: str, display_name: str, password: str) -> None:
        email = normalize_email(email)
        hashed = password_hash.hash(password)
        # Serialize duplicate registration without leaking uniqueness violations to callers.
        lock_key = int.from_bytes(bytes.fromhex(digest(email))[:8], signed=True)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        existing = self.session.scalar(select(User.id).where(User.email_normalized == email))
        if existing is not None:
            return
        user = User(email_normalized=email, display_name=display_name.strip())
        self.session.add(user)
        self.session.flush()
        self.session.add(PasswordCredential(user_id=user.id, password_hash=hashed))
        self._issue_token(user, "verify")
        self.event("registered", user.id)

    # Reissue a verification token only for an active, still unverified account; otherwise do
    # nothing so the route's generic acknowledgement reveals nothing.
    def request_verification(self, email: str) -> None:
        user = self._user_by_email(email)
        if user is not None and user.email_verified_at is None:
            self._issue_token(user, "verify")

    # Atomically consume a token of the given purpose: find its owner by digest, lock the user
    # first and then the token row (the shared user-before-token order), and reject unknown,
    # disabled, consumed, or expired tokens with one generic error. Replays therefore fail.
    def _consume_token(self, raw: str, purpose: str) -> tuple[User, AuthToken]:
        user_id = self.session.scalar(
            select(AuthToken.user_id).where(
                AuthToken.token_digest == digest(raw), AuthToken.purpose == purpose
            )
        )
        if user_id is None:
            raise AuthError("invalid_or_expired_token", 400)
        try:
            user = self._lock_user(user_id)
        except AuthError as error:
            raise AuthError("invalid_or_expired_token", 400) from error
        token = self.session.scalar(
            select(AuthToken)
            .where(AuthToken.token_digest == digest(raw), AuthToken.purpose == purpose)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if token is None or token.consumed_at is not None or token.expires_at <= now_utc():
            raise AuthError("invalid_or_expired_token", 400)
        token.consumed_at = now_utc()
        return user, token

    # Consume a verification token and record verified mailbox ownership. This is separate from
    # User.status, which only records whether the account is administratively enabled.
    def verify_email(self, raw: str) -> None:
        user, _ = self._consume_token(raw, "verify")
        user.email_verified_at = now_utc()
        self.event("email_verified", user.id)

    # Verify the password against the locked active user (with dummy-hash work for unknown
    # emails), require a verified email, then create a server-side session row storing only the
    # token digest. Returns the user and the raw token for the cookie. The route records failed
    # attempts separately because this transaction rolls back on failure.
    def login(self, email: str, password: str) -> tuple[User, str]:
        user = self._user_by_email(email)
        credential = self.session.get(PasswordCredential, user.id) if user else None
        if not verify_password(password, credential.password_hash if credential else None):
            raise AuthError()
        assert user is not None
        if user.email_verified_at is None:
            raise AuthError("email_verification_required", 403)
        raw = new_token()
        now = now_utc()
        self.session.add(
            AuthSession(
                user_id=user.id,
                token_digest=digest(raw),
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(seconds=self.settings.session_lifetime_seconds),
            )
        )
        self.event("login_succeeded", user.id)
        return user, raw

    # Resolve a raw session cookie on every authenticated browser request: look up its digest,
    # lock the user and then the session row, and reject revoked, absolutely expired, idle, or
    # unverified sessions. Disabled users fail in _lock_user. Refreshes last_seen_at.
    def authenticate(self, raw: str) -> tuple[User, AuthSession]:
        if not 32 <= len(raw) <= 128:
            raise AuthError("authentication_required")
        item = self.session.scalar(
            select(AuthSession).where(AuthSession.token_digest == digest(raw))
        )
        if item is None:
            raise AuthError("authentication_required")
        # Password recovery and session operations use the same user -> session lock order.
        user = self._lock_user(item.user_id)
        item = self.session.scalar(
            select(AuthSession)
            .where(AuthSession.token_digest == digest(raw))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = now_utc()
        if (
            item is None
            or item.revoked_at is not None
            or item.expires_at <= now
            or item.last_seen_at <= now - timedelta(seconds=self.settings.session_idle_seconds)
        ):
            raise AuthError("authentication_required")
        if user.email_verified_at is None:
            raise AuthError("authentication_required")
        item.last_seen_at = now
        return user, item

    # Revoke the current session row (already locked by authenticate) and record the event.
    def logout(self, user: User, item: AuthSession) -> None:
        item.revoked_at = now_utc()
        self.event("logout", user.id)

    # Mark every unrevoked session of the user revoked in one statement. Used by logout-all and
    # by password changes/resets; rows are kept for later retention review, not deleted.
    def revoke_sessions(self, user_id: UUID) -> None:
        self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now_utc())
        )

    # Revoke all sessions of the authenticated user and record logout_all.
    def logout_all(self, user: User) -> None:
        self.revoke_sessions(user.id)
        self.event("logout_all", user.id)

    # Issue a reset token only for an active verified account; otherwise do nothing so the
    # route's generic acknowledgement does not reveal account state.
    def request_reset(self, email: str) -> None:
        user = self._user_by_email(email)
        if user is not None and user.email_verified_at is not None:
            self._issue_token(user, "reset")
            self.event("reset_requested", user.id)

    # Replace the stored hash of an existing credential, revoke all sessions, and consume any
    # other outstanding reset tokens. The caller already holds the user lock.
    def _set_password(self, user: User, hashed: str) -> None:
        credential = self.session.get(PasswordCredential, user.id)
        if credential is None:
            raise AuthError("invalid_or_expired_token", 400)
        credential.password_hash, credential.changed_at = hashed, now_utc()
        self.revoke_sessions(user.id)
        self.session.execute(
            update(AuthToken)
            .where(
                AuthToken.user_id == user.id,
                AuthToken.purpose == "reset",
                AuthToken.consumed_at.is_(None),
            )
            .values(consumed_at=now_utc())
        )

    # Complete recovery: hash first (outside the locks), consume the reset token, then set the
    # password and revoke every session.
    def reset_password(self, raw: str, password: str) -> None:
        hashed = password_hash.hash(password)
        user, _ = self._consume_token(raw, "reset")
        self._set_password(user, hashed)
        self.event("reset_completed", user.id)

    # Authenticated change: lock the user, re-verify the current password, then set the new
    # hash and revoke all sessions.
    def change_password(self, user_id: UUID, current: str, replacement: str) -> None:
        user = self._lock_user(user_id)
        credential = self.session.get(PasswordCredential, user.id)
        if not verify_password(current, credential.password_hash if credential else None):
            raise AuthError()
        self._set_password(user, password_hash.hash(replacement))
        self.event("password_changed", user.id)
