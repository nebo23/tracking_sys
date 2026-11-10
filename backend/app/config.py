"""Validated local configuration; secrets are never included in error input details."""

# Literal restricts settings such as environment and mail mode to explicit typed choices.
# urlsplit parses origin components so the boundary validator can reject paths and wildcards.
# Fernet is the authenticated symmetric scheme used here only to validate the mail key; the
# mail service performs encryption. Imports do not execute an application feature by themselves.
import binascii
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from email_validator import EmailNotValidError, validate_email
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from app.collection.keys import TombstoneKeyring
from app.links.policy import LinkRuleError, canonical_hostname, platform_authorities
from app.privacy.token_secrets import LocalKeyring

# Absolute anchors keep configuration and migration discovery independent of the working
# directory from which the API, worker, Alembic, or tests are started.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


# Read and validate database connection settings shared by the API, worker, and migrations.
# Values come from TRACKING_-prefixed environment variables or the repository-root .env file.
class DatabaseSettings(BaseSettings):
    # TRACKING_ prefix; root-relative .env read as UTF-8; unrelated dotenv keys are ignored so
    # one file can serve several tools. hide_input_in_errors omits input values from textual
    # validation errors; it does not redact every structured error serialization by itself.
    model_config = SettingsConfigDict(
        env_prefix="TRACKING_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_host: str = "127.0.0.1"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "tracking_sys"
    database_user: str = "tracking_app"
    database_password: SecretStr
    database_connect_timeout: int = Field(default=3, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=3000, ge=100, le=60000)

    # Pydantic calls this registered field validator while validating the settings object;
    # classmethod supplies the settings class, not an instance. Blank or space-only secrets
    # are rejected, and a valid password is returned unchanged rather than silently trimmed.
    @field_validator("database_password")
    @classmethod
    def require_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("A database password is required.")
        return value

    # Build a structured SQLAlchemy URL on access so password punctuation needs no manual
    # encoding. The secret is extracted only to supply credentials; this does not connect.
    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.database_user,
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )


# Extend database settings with application authentication, mail, and browser policy.
# This is process configuration only; it neither implements registration nor stores users.
class Settings(DatabaseSettings):
    environment: Literal["development", "production"] = "development"
    auth_secret: SecretStr
    mail_encryption_key: SecretStr
    cookie_secure: bool = True
    allowed_origins: list[str] = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    frontend_origin: str = "http://127.0.0.1:5173"
    # Mail transport selection: local .eml capture (default) or the D-022 Gmail adapter.
    mail_mode: Literal["local", "gmail"] = "local"
    mail_directory: Path = PROJECT_ROOT / "local-data" / "mail"
    session_lifetime_seconds: int = Field(default=43200, ge=60, le=86400)
    session_idle_seconds: int = Field(default=1800, ge=60, le=43200)
    # Approved numeric verification policy (D-022): ten-minute codes, five failed checks per
    # challenge, a 60-second resend cooldown, and ten failed checks per email per 24 hours.
    otp_secret: SecretStr
    verification_code_lifetime_seconds: int = Field(default=600, ge=60, le=3600)
    verification_code_attempts: int = Field(default=5, ge=1, le=10)
    verification_resend_cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    verification_daily_failures: int = Field(default=10, ge=1, le=100)
    reset_lifetime_seconds: int = Field(default=1800, ge=60, le=3600)
    invitation_lifetime_seconds: int = Field(default=604800, ge=60, le=604800)
    login_attempts_per_minute: int = Field(default=5, ge=1, le=100)
    auth_requests_per_minute: int = Field(default=30, ge=1, le=1000)
    # Per-user invitation acceptance attempts per minute (review amendment T-02). The default
    # mirrors the login subject limit and is recorded as a proposed value in the auth design.
    invitation_attempts_per_minute: int = Field(default=5, ge=1, le=100)
    # Account closure (D-024): an account without a password must present a session created
    # within this window, which means a fresh Google sign-in. Ten minutes is the approved maximum.
    closure_reauthentication_seconds: int = Field(default=600, ge=60, le=600)
    # Google sign-in (D-022) is off unless explicitly enabled with a Web client. The completion
    # URL receives the browser after the callback; it defaults to the frontend completion page.
    google_sign_in_enabled: bool = False
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = "http://127.0.0.1:8000/auth/google/callback"
    google_complete_url: str = ""
    # Gmail sender (D-022): a separate Desktop OAuth client authorized by the owner for the
    # send-only scope. Used only when mail_mode is "gmail".
    gmail_client_id: str = ""
    gmail_client_secret: SecretStr = SecretStr("")
    gmail_refresh_token: SecretStr = SecretStr("")
    gmail_sender: str = ""
    # Event collection (D-027). Development-only local keyrings in ignored .env, refused with
    # every production configuration below: TRACKING_TOKEN_KEYRING ("id:base64url,...", the
    # D-025 token keyring) seals webhook signing secrets; TRACKING_TOMBSTONE_KEYRING
    # ("id:hex,...") keys deletion tombstones independently of every other secret. Collection
    # routes that need a missing keyring fail closed.
    token_keyring: SecretStr = SecretStr("")
    token_keyring_active: str = ""
    tombstone_keyring: SecretStr = SecretStr("")
    tombstone_keyring_active: str = ""
    # Approved development rates per minute (D-027 decision 6); a deployment may lower them.
    ingest_public_per_minute: int = Field(default=60, ge=1, le=60)
    ingest_trusted_per_minute: int = Field(default=600, ge=1, le=600)
    # Public consent-state reads (D-033) use their own bucket per source and peer.
    consent_state_per_minute: int = Field(default=60, ge=1, le=60)
    # Managed links (D-033). Platform short-link authorities ("host" or "host:port", never a
    # wildcard) resolve links without a custom domain; a custom domain resolves only while its
    # verification is current, on link_custom_domain_port (443 outside local tests). Loopback
    # HTTP destinations are a development aid that must stay off elsewhere. Live DNS/TLS domain
    # verification runs only when explicitly enabled with an operator-configured CNAME service
    # target; synthetic adapters are injected by test code, never selected by configuration.
    link_platform_hosts: list[str] = ["127.0.0.1:8000", "localhost:8000"]
    link_allow_loopback_destinations: bool = False
    link_custom_domain_port: int = Field(default=443, ge=1, le=65535)
    link_service_target: str = ""
    link_domain_verification: Literal["disabled", "live"] = "disabled"

    # Registered field validator for the HMAC/CSRF key: require at least 32 bytes encoded as
    # hexadecimal. Unlike an ordinary helper, Pydantic invokes it automatically on validation.
    # The same rule applies to the independent numeric-verification verifier key.
    @field_validator("auth_secret", "otp_secret")
    @classmethod
    def validate_auth_secret(cls, value: SecretStr) -> SecretStr:
        try:
            valid = len(bytes.fromhex(value.get_secret_value())) >= 32
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Application secrets must contain at least 32 hexadecimal bytes.")
        return value

    # Registered field validator: constructing Fernet proves the key has the expected format.
    # SecretStr only masks the value in displays; it is not encryption.
    @field_validator("mail_encryption_key")
    @classmethod
    def validate_mail_key(cls, value: SecretStr) -> SecretStr:
        try:
            Fernet(value.get_secret_value().encode())
        except (ValueError, TypeError) as error:
            raise ValueError("A valid mail encryption key is required.") from error
        return value

    # After-model validator: checks relationships across already parsed fields. Origins must be
    # exact HTTP(S) origins without credentials, paths, or wildcards; insecure cookies are
    # allowed only for loopback origins; the verification key must differ from the auth secret;
    # enabled Google sign-in and Gmail mode must be fully configured; production stays blocked
    # until a reviewed production rule set exists.
    @model_validator(mode="after")
    def validate_development_boundary(self) -> "Settings":
        for origin in [*self.allowed_origins, self.frontend_origin]:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise ValueError("Origins must be explicit HTTP(S) origins without paths.")
            if not self.cookie_secure and parsed.hostname not in {
                "127.0.0.1",
                "localhost",
                "[::1]",
                "::1",
            }:
                raise ValueError("Insecure development cookies require loopback origins.")
        if self.otp_secret.get_secret_value() == self.auth_secret.get_secret_value():
            raise ValueError("The verification key must be independent of the auth secret.")
        self.token_keys()
        self._validate_links()
        tombstones = self.tombstone_keys()
        if tombstones is not None:
            others = {
                bytes.fromhex(self.auth_secret.get_secret_value()),
                bytes.fromhex(self.otp_secret.get_secret_value()),
            }
            if tombstones.key_material() & others:
                raise ValueError("Tombstone keys must be independent of other secrets.")
        if self.google_sign_in_enabled:
            self._validate_google()
        if self.mail_mode == "gmail":
            self._validate_gmail()
        if self.environment == "production":
            raise ValueError("Production requires an approved external mail delivery adapter.")
        return self

    # Platform short-link hosts must be exact authorities; live verification needs a valid
    # service target hostname.
    def _validate_links(self) -> None:
        try:
            if not self.link_platform_hosts or any("*" in h for h in self.link_platform_hosts):
                raise LinkRuleError("invalid_platform_host")
            platform_authorities(self.link_platform_hosts)
            if self.link_service_target:
                canonical_hostname(self.link_service_target)
        except LinkRuleError as error:
            raise ValueError("The managed-link host configuration is invalid.") from error
        if self.link_domain_verification == "live" and not self.link_service_target:
            raise ValueError("Live domain verification requires the CNAME service target.")

    # Google sign-in needs a Web client, an exact callback on this API, and a completion URL
    # whose origin is explicitly allowed. HTTP is accepted only on loopback hosts.
    def _validate_google(self) -> None:
        if not self.google_client_id or not self.google_client_secret.get_secret_value():
            raise ValueError("Google sign-in requires its client ID and secret.")
        callback = urlsplit(self.google_redirect_uri)
        loopback = callback.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            callback.scheme not in {"http", "https"}
            or (callback.scheme == "http" and not loopback)
            or callback.path != "/auth/google/callback"
            or callback.query
            or callback.fragment
            or callback.username
            or callback.password
        ):
            raise ValueError("The Google redirect URI must be this API's exact callback route.")
        target = urlsplit(self.google_completion_url)
        if (
            f"{target.scheme}://{target.netloc}" not in self.allowed_origins
            or target.fragment
            or target.username
            or target.password
        ):
            raise ValueError("The Google completion URL must use an allowed origin.")

    # Gmail mode needs the separate sender client, its refresh token, and a valid sender. The
    # sender client must not be the sign-in client (D-022 decision 6).
    def _validate_gmail(self) -> None:
        if not (
            self.gmail_client_id
            and self.gmail_client_secret.get_secret_value()
            and self.gmail_refresh_token.get_secret_value()
            and self.gmail_sender
        ):
            raise ValueError("Gmail delivery requires sender client, refresh token, and sender.")
        if self.gmail_client_id == self.google_client_id:
            raise ValueError("Gmail delivery requires a client separate from Google sign-in.")
        try:
            validate_email(self.gmail_sender, check_deliverability=False, test_environment=True)
        except EmailNotValidError as error:
            raise ValueError("The Gmail sender must be a valid email address.") from error

    # The D-025 local token keyring, or None while unset. Parsing validates every key.
    def token_keys(self) -> "LocalKeyring | None":
        text = self.token_keyring.get_secret_value().strip()
        if not text:
            return None
        try:
            return LocalKeyring.from_text(text, self.token_keyring_active)
        except (ValueError, binascii.Error) as error:
            raise ValueError("The token keyring is invalid.") from error

    # The independent tombstone keyring, or None while unset.
    def tombstone_keys(self) -> "TombstoneKeyring | None":
        text = self.tombstone_keyring.get_secret_value().strip()
        if not text:
            return None
        try:
            return TombstoneKeyring.from_text(text, self.tombstone_keyring_active)
        except ValueError as error:
            raise ValueError("The tombstone keyring is invalid.") from error

    # Computed when read: secure deployments use the __Host- prefix, which browsers accept only
    # for Secure, host-only, path=/ cookies. Reading it does not issue a session cookie.
    @property
    def cookie_name(self) -> str:
        return "__Host-tracking_session" if self.cookie_secure else "tracking_session"

    # Short-lived cookie that binds a Google authorization transaction to the browser that
    # started it. The __Secure- prefix permits the narrower /auth/google path.
    @property
    def oauth_cookie_name(self) -> str:
        return "__Secure-tracking_oauth" if self.cookie_secure else "tracking_oauth"

    # Where the browser goes after the Google callback; at most a fixed error code is appended.
    @property
    def google_completion_url(self) -> str:
        return self.google_complete_url or f"{self.frontend_origin}/auth/google/complete"


# Lifecycle runner configuration (specification 003-A3, D-024). It connects as the dedicated
# tracking_lifecycle role through explicit TRACKING_LIFECYCLE_* aliases and needs no auth, mail,
# or provider secret. Each retention period defaults to the owner-approved value, which is also
# its upper bound: a deployment may shorten a period but cannot extend it without a new
# recorded decision. Periods count from the row's end (revocation, expiry, consumption,
# invalidation, or delivery), never from creation alone.
class LifecycleSettings(DatabaseSettings):
    database_user: str = Field(
        default="tracking_lifecycle", validation_alias="TRACKING_LIFECYCLE_USER"
    )
    database_password: SecretStr = Field(validation_alias="TRACKING_LIFECYCLE_PASSWORD")
    environment: Literal["development", "production"] = "development"
    mail_mode: Literal["local", "gmail"] = "local"
    mail_directory: Path = PROJECT_ROOT / "local-data" / "mail"
    session_idle_seconds: int = Field(default=1800, ge=60, le=43200)
    session_retention_days: int = Field(default=30, ge=0, le=30)
    token_retention_days: int = Field(default=7, ge=0, le=7)
    challenge_retention_days: int = Field(default=7, ge=0, le=7)
    oauth_transaction_retention_days: int = Field(default=1, ge=0, le=1)
    outbox_retention_days: int = Field(default=30, ge=0, le=30)
    local_mail_retention_days: int = Field(default=7, ge=0, le=7)
    # Provisional development retention for collected data (D-027 decision 7): event rows 13
    # months (395 days) after first receipt, diagnostic counters 30 days after their day, and
    # subjects with their consent records 13 months after last activity.
    event_retention_days: int = Field(default=395, ge=0, le=395)
    diagnostic_retention_days: int = Field(default=30, ge=0, le=30)
    subject_retention_days: int = Field(default=395, ge=0, le=395)
    lifecycle_batch_size: int = Field(default=500, ge=1, le=5000)


# Separate migrator credentials through explicit TRACKING_MIGRATION_* aliases, with a longer
# per-statement timeout for DDL. This is neither a database uptime allowance nor a grant of
# schema privileges to the runtime role.
class MigrationSettings(DatabaseSettings):
    database_user: str = Field(
        default="tracking_migrator", validation_alias="TRACKING_MIGRATION_USER"
    )
    database_password: SecretStr = Field(validation_alias="TRACKING_MIGRATION_PASSWORD")
    database_statement_timeout_ms: int = Field(default=30000, ge=100, le=60000)
