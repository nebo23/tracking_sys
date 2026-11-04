"""Validated local configuration; secrets are never included in error input details."""

# Literal restricts settings such as environment and mail mode to explicit typed choices.
# urlsplit parses origin components so the boundary validator can reject paths and wildcards.
# Fernet is the authenticated symmetric scheme used here only to validate the mail key; the
# mail service performs encryption. Imports do not execute an application feature by themselves.
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

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
    mail_mode: Literal["local"] = "local"
    mail_directory: Path = PROJECT_ROOT / "local-data" / "mail"
    session_lifetime_seconds: int = Field(default=43200, ge=60, le=86400)
    session_idle_seconds: int = Field(default=1800, ge=60, le=43200)
    verification_lifetime_seconds: int = Field(default=86400, ge=60, le=172800)
    reset_lifetime_seconds: int = Field(default=1800, ge=60, le=3600)
    invitation_lifetime_seconds: int = Field(default=604800, ge=60, le=604800)
    login_attempts_per_minute: int = Field(default=5, ge=1, le=100)
    auth_requests_per_minute: int = Field(default=30, ge=1, le=1000)
    # Per-user invitation acceptance attempts per minute (review amendment T-02). The default
    # mirrors the login subject limit and is recorded as a proposed value in the auth design.
    invitation_attempts_per_minute: int = Field(default=5, ge=1, le=100)

    # Registered field validator for the HMAC/CSRF key: require at least 32 bytes encoded as
    # hexadecimal. Unlike an ordinary helper, Pydantic invokes it automatically on validation.
    @field_validator("auth_secret")
    @classmethod
    def validate_auth_secret(cls, value: SecretStr) -> SecretStr:
        try:
            valid = len(bytes.fromhex(value.get_secret_value())) >= 32
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "The authentication secret must contain at least 32 hexadecimal bytes."
            )
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
    # allowed only for loopback origins; production stays blocked until a reviewed external
    # mail adapter and production rule set exist.
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
        if self.environment == "production":
            raise ValueError("Production requires an approved external mail delivery adapter.")
        return self

    # Computed when read: secure deployments use the __Host- prefix, which browsers accept only
    # for Secure, host-only, path=/ cookies. Reading it does not issue a session cookie.
    @property
    def cookie_name(self) -> str:
        return "__Host-tracking_session" if self.cookie_secure else "tracking_session"


# Separate migrator credentials through explicit TRACKING_MIGRATION_* aliases, with a longer
# per-statement timeout for DDL. This is neither a database uptime allowance nor a grant of
# schema privileges to the runtime role.
class MigrationSettings(DatabaseSettings):
    database_user: str = Field(
        default="tracking_migrator", validation_alias="TRACKING_MIGRATION_USER"
    )
    database_password: SecretStr = Field(validation_alias="TRACKING_MIGRATION_PASSWORD")
    database_statement_timeout_ms: int = Field(default=30000, ge=100, le=60000)
