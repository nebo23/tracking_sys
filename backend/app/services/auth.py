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


class AuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session, self.settings = session, settings

    def event(self, action: str, user_id: UUID | None = None) -> None:
        self.session.add(SecurityEvent(action=action, user_id=user_id))

    def _lock_user(self, user_id: UUID) -> User:
        user = self.session.scalar(
            select(User)
            .where(User.id == user_id, User.status == "active")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise AuthError()
        return user

    def _user_by_email(self, email: str) -> User | None:
        return self.session.scalar(
            select(User)
            .where(User.email_normalized == normalize_email(email), User.status == "active")
            .with_for_update()
            .execution_options(populate_existing=True)
        )

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

    def request_verification(self, email: str) -> None:
        user = self._user_by_email(email)
        if user is not None and user.email_verified_at is None:
            self._issue_token(user, "verify")

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

    def verify_email(self, raw: str) -> None:
        user, _ = self._consume_token(raw, "verify")
        user.email_verified_at = now_utc()
        self.event("email_verified", user.id)

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

    def logout(self, user: User, item: AuthSession) -> None:
        item.revoked_at = now_utc()
        self.event("logout", user.id)

    def revoke_sessions(self, user_id: UUID) -> None:
        self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now_utc())
        )

    def logout_all(self, user: User) -> None:
        self.revoke_sessions(user.id)
        self.event("logout_all", user.id)

    def request_reset(self, email: str) -> None:
        user = self._user_by_email(email)
        if user is not None and user.email_verified_at is not None:
            self._issue_token(user, "reset")
            self.event("reset_requested", user.id)

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

    def reset_password(self, raw: str, password: str) -> None:
        hashed = password_hash.hash(password)
        user, _ = self._consume_token(raw, "reset")
        self._set_password(user, hashed)
        self.event("reset_completed", user.id)

    def change_password(self, user_id: UUID, current: str, replacement: str) -> None:
        user = self._lock_user(user_id)
        credential = self.session.get(PasswordCredential, user.id)
        if not verify_password(current, credential.password_hash if credential else None):
            raise AuthError()
        self._set_password(user, password_hash.hash(replacement))
        self.event("password_changed", user.id)
