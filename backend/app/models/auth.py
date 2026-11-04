"""Authentication state contains digests, password hashes, or encrypted mail only."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# Reference queries below are manual read-only diagnostics for an authorized database operator.
# Replace the synthetic literals before use. They deliberately omit password hashes, token
# digests, rate-limit bucket keys, and encrypted mail payloads. They are not authorization.
#
# One Argon2 password hash per user, kept apart from the identity row.
# SELECT user_id, changed_at
# FROM public.password_credentials
# WHERE user_id = '00000000-0000-0000-0000-000000000001'::uuid;
class PasswordCredential(Base):
    __tablename__ = "password_credentials"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Opaque browser session: only the SHA-256 digest of the cookie token is stored, with absolute
# expiry, last activity for idle timeout, and revocation time.
# SELECT id, user_id, created_at, last_seen_at, expires_at, revoked_at
# FROM public.auth_sessions
# WHERE id = '00000000-0000-0000-0000-000000000005'::uuid;
# SELECT id, created_at, last_seen_at, expires_at, revoked_at
# FROM public.auth_sessions
# WHERE user_id = '00000000-0000-0000-0000-000000000001'::uuid
#   AND revoked_at IS NULL AND expires_at > now()
# ORDER BY created_at DESC, id LIMIT 100;
class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Single-use email-verification or password-reset token stored as a digest with expiry and
# consumption time; consumed rows remain until a retention policy is approved.
# SELECT id, user_id, purpose, created_at, expires_at, consumed_at
# FROM public.auth_tokens
# WHERE user_id = '00000000-0000-0000-0000-000000000001'::uuid AND purpose = 'verify'
# ORDER BY created_at DESC, id LIMIT 100;
class AuthToken(Base):
    __tablename__ = "auth_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('verify', 'reset')", name="valid_purpose"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Shared fixed-window attempt counter. bucket_key is an HMAC of scope and subject, so raw
# emails and IP addresses are not stored. Inspect counts and expiry; the key column is omitted.
# SELECT attempts, expires_at
# FROM public.auth_rate_limits
# WHERE expires_at > now()
# ORDER BY attempts DESC, expires_at LIMIT 100;
# SELECT count(*) AS active_buckets, max(attempts) AS highest_attempts
# FROM public.auth_rate_limits
# WHERE expires_at > now();
class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (CheckConstraint("attempts >= 0", name="nonnegative_attempts"),)
    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Append-only authentication event; user_id may be null (for example a failed login). It stores
# no submitted password, token, raw email, or IP address. The runtime may only insert.
# SELECT id, user_id, action, occurred_at
# FROM public.security_events
# WHERE user_id = '00000000-0000-0000-0000-000000000001'::uuid
# ORDER BY occurred_at DESC, id DESC LIMIT 100;
# SELECT id, user_id, action, occurred_at
# FROM public.security_events
# WHERE action = 'login_failed' AND occurred_at >= now() - interval '1 day'
# ORDER BY occurred_at DESC, id DESC LIMIT 100;
class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('registered', 'email_verified', 'login_succeeded', 'login_failed', "
            "'logout', 'logout_all', 'password_changed', 'reset_requested', 'reset_completed', "
            "'google_login_succeeded', 'google_registered', 'google_identity_linked', "
            "'verification_code_failed')",
            name="valid_action",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Durable transactional mail queue. The payload is Fernet-encrypted with a key outside
# PostgreSQL and cleared after delivery or expiry; a row is not proof that a mailbox received
# mail. expires_at, when set, stops delivery of a verification code that is no longer valid.
# SELECT id, purpose, attempts, next_attempt_at, expires_at, failure_code, created_at
# FROM public.mail_outbox
# WHERE delivered_at IS NULL
# ORDER BY next_attempt_at, id LIMIT 100;
# SELECT id, purpose, attempts, delivered_at, failure_code
# FROM public.mail_outbox
# WHERE id = '00000000-0000-0000-0000-000000000006'::uuid;
class MailOutbox(Base):
    __tablename__ = "mail_outbox"
    __table_args__ = (
        CheckConstraint("purpose IN ('verify', 'reset', 'invitation')", name="valid_purpose"),
        CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    encrypted_payload: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Numeric email-verification challenge (D-022). Only a keyed HMAC verifier bound to the
# challenge, user, and purpose is stored, never the code. Failed checks are counted in an
# independent transaction; a reissue invalidates the previous open challenge.
# SELECT id, user_id, purpose, failed_attempts, created_at, expires_at, consumed_at,
#        invalidated_at
# FROM public.verification_challenges
# WHERE user_id = '00000000-0000-0000-0000-000000000001'::uuid
# ORDER BY created_at DESC, id LIMIT 100;
class VerificationChallenge(Base):
    __tablename__ = "verification_challenges"
    __table_args__ = (
        CheckConstraint("purpose IN ('email_verification')", name="valid_purpose"),
        CheckConstraint("failed_attempts >= 0", name="nonnegative_attempts"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    verifier: Mapped[str] = mapped_column(String(64))
    failed_attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Single-use Google authorization transaction (D-022). It stores digests of the state and of
# the browser-binding cookie; link bindings also incorporate the initiating session digest.
# The PKCE verifier and nonce are derived from the raw state with the application HMAC key,
# so neither is stored. Link transactions name the requesting user.
# SELECT id, purpose, user_id, created_at, expires_at, consumed_at
# FROM public.oauth_transactions
# WHERE created_at >= now() - interval '1 day'
# ORDER BY created_at DESC, id LIMIT 100;
class OAuthTransaction(Base):
    __tablename__ = "oauth_transactions"
    __table_args__ = (
        CheckConstraint("purpose IN ('login', 'link')", name="valid_purpose"),
        CheckConstraint(
            "(purpose = 'login' AND user_id IS NULL) OR (purpose = 'link' AND user_id IS NOT NULL)",
            name="link_has_user",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    purpose: Mapped[str] = mapped_column(String(8))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    state_digest: Mapped[str] = mapped_column(String(64), unique=True)
    binding_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# External sign-in identity linked to one local user (D-022). Identified by the validated
# issuer/subject pair, never by email; one Google identity per user. No tokens or profile copy.
# SELECT id, user_id, provider, issuer, subject, created_at, last_login_at
# FROM public.external_identities
# WHERE user_id = '00000000-0000-0000-0000-000000000001'::uuid;
# SELECT id, user_id, created_at, last_login_at
# FROM public.external_identities
# WHERE provider = 'google' AND subject = 'synthetic-google-subject-000000000001';
class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_external_identities_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_external_identities_user_provider"),
        CheckConstraint("provider IN ('google')", name="valid_provider"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(16))
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
