"""Validated local configuration; secrets are never included in error input details."""

# Literal restricts settings such as environment and mail mode to explicit typed choices.
# urlsplit parses origin components so the boundary validator can reject paths and wildcards.
# Fernet is the authenticated symmetric scheme used here only to validate the mail key; the
# mail service performs encryption. Imports do not execute an application feature by themselves.
import binascii
import re
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
# Paddle's documented credential forms (specification 017-C, design-017c.md section 2, V-4 and
# V-12): the API key carries its environment, the client-side token is test_ or live_, and the
# webhook secret is the notification destination's pdl_ntfset_ key.
PADDLE_API_KEY = re.compile(r"pdl_(live|sdbx)_apikey_[a-z0-9]{26}_[A-Za-z0-9]{22}_[A-Za-z0-9]{3}")
PADDLE_CLIENT_TOKEN = re.compile(r"(test|live)_[A-Za-z0-9]{27}")
PADDLE_WEBHOOK_SECRET = re.compile(r"pdl_ntfset_[!-~]{5,245}")


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
    # Agreement record (017-A, D10; 018 D15): registration and every sign-in must send these
    # current Terms of Service and Privacy Policy versions. The owner supplies the texts; until
    # then the development labels are draft-1 and the texts are reported as not published.
    terms_version: str = Field(default="draft-1", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    privacy_version: str = Field(default="draft-1", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    agreement_texts_published: bool = False
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
    # Connector runtime (specification 009-A, D-048). The provider redirects to the fixed
    # callback on this API; the browser then goes to the completion URL with at most a fixed
    # result code and the connection ID. The synthetic provider is selected only by an explicit
    # development state file shared by the API and the connector worker. The 72-hour teardown
    # target applies to that local synthetic slice only; live provider deadlines are 010-013.
    connector_redirect_uri: str = "http://127.0.0.1:8000/connectors/oauth/callback"
    connector_complete_url: str = ""
    connector_synthetic_state: Path | None = None
    connector_teardown_hours: int = Field(default=72, ge=1, le=72)
    # Synchronization (009-B, D-049 decisions D11 and D15). The worker queues an incremental run
    # for an active connection whose last run is older than the interval. Each connection may
    # spend at most the daily allocation of its provider's cost unit per UTC day, in addition to
    # the provider's own daily quota. Both are synthetic development values, not commercial
    # budgets (Q-004).
    connector_sync_interval_hours: int = Field(default=24, ge=1, le=168)
    connector_connection_daily_units: int = Field(default=100, ge=1, le=100000)
    # Instagram API with Instagram Login (specification 010-C, D-055). The live adapter stays
    # off unless explicitly enabled with the Meta app's ID and secret from ignored .env, and it
    # is registered only while the Meta and Instagram provider rules are current. Until App
    # Review (010-D), Meta lets only people with a role on the development app authorize it.
    connector_instagram_enabled: bool = False
    instagram_app_id: str = ""
    instagram_app_secret: SecretStr = SecretStr("")
    # YouTube Data API and YouTube Analytics API (specification 011-C, D-058, D-060). The live
    # adapter stays off unless explicitly enabled with its own Web client from ignored .env
    # (TRACKING_YOUTUBE_CLIENT_ID and TRACKING_YOUTUBE_CLIENT_SECRET), never the Google sign-in
    # or Gmail sender client, and it is registered only while the YouTube provider rules are
    # current. Turning it off is the kill switch; app.connector_purge disconnects and purges.
    connector_youtube_enabled: bool = False
    youtube_client_id: str = ""
    youtube_client_secret: SecretStr = SecretStr("")
    # Meta Marketing API and Conversions API (specification 014-D, D-064 decision D12). The
    # live meta_ads and meta_capi adapters stay off unless explicitly enabled with their own
    # Meta app ID, app secret and Facebook Login for Business configuration ID from ignored
    # .env, kept apart from the Instagram settings, and each is registered only while its
    # provider rules are current. Spec 014 makes no live call (D-063).
    connector_meta_ads_enabled: bool = False
    meta_ads_app_id: str = ""
    meta_ads_app_secret: SecretStr = SecretStr("")
    meta_ads_config_id: str = ""
    # Paymob payments (specification 015-B, D-067 decision D12). The Paymob source type stays
    # off unless explicitly enabled, and it is usable only while the payments.processor_records
    # and paymob.accept provider rules are current. Merchant HMAC secrets are entered through
    # the API and sealed under the token keyring; none belongs in .env. Spec 015 makes no call
    # to Paymob.
    payments_paymob_enabled: bool = False
    # Bookings and CRM (specification 015-D, D-068 E2, E5 and E11). The Cal.com source kind
    # stays off unless enabled and usable only while the calcom.webhooks rule is current; the
    # provider-neutral signed webhook kind stays off unless enabled. Signing secrets are
    # entered or issued through the API and sealed under the token keyring.
    integrations_calcom_enabled: bool = False
    integrations_webhook_enabled: bool = False
    # WhatsApp Cloud API referrals (specification 015-E, D-068 E7 and E11). The intake stays off
    # unless enabled with the Meta app secret (signatures) and a verify token (the handshake)
    # from ignored .env, and it is usable only while the whatsapp.cloud_api rule is current.
    # Spec 015 makes no call to Meta.
    whatsapp_enabled: bool = False
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_verify_token: SecretStr = SecretStr("")
    # Retained report exports (specification 016-C, D-095 D5): an export, sealed under the token
    # keyring, is downloadable for this many days after creation; 7 is the approved maximum.
    report_export_lifetime_days: int = Field(default=7, ge=1, le=7)
    # Platform billing (specification 017-C, D-103 D4 and D14). Off by default: while it is off
    # every new agency is complimentary on the default plan, exactly as before, and the billing
    # routes, webhook, worker and command answer that billing is unavailable. Enabling it
    # requires the Paddle API key and webhook secret of the configured environment from ignored
    # .env, and the paddle.billing provider rule must be current. The client-side token is
    # public (Paddle.js) and optional. Spec 017-C makes no live Paddle call.
    billing_enabled: bool = False
    billing_trial_days: int = Field(default=14, ge=1, le=30)
    billing_paddle_environment: Literal["sandbox", "live"] = "sandbox"
    billing_paddle_api_key: SecretStr = SecretStr("")
    billing_paddle_webhook_secret: SecretStr = SecretStr("")
    billing_paddle_client_token: str = ""

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
        self._validate_connectors()
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
        if self.billing_enabled:
            self._validate_billing()
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
                # Stored canonically, so CNAME answers compare consistently (R005-11).
                self.link_service_target = canonical_hostname(self.link_service_target)
        except LinkRuleError as error:
            raise ValueError("The managed-link host configuration is invalid.") from error
        if self.link_domain_verification == "live" and not self.link_service_target:
            raise ValueError("Live domain verification requires the CNAME service target.")

    # The connector callback must be the fixed route on this API (HTTP only on loopback), and
    # the synthetic provider exists only in development.
    def _validate_connectors(self) -> None:
        callback = urlsplit(self.connector_redirect_uri)
        loopback = callback.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            callback.scheme not in {"http", "https"}
            or (callback.scheme == "http" and not loopback)
            or callback.path != "/connectors/oauth/callback"
            or callback.query
            or callback.fragment
            or callback.username
            or callback.password
        ):
            raise ValueError("The connector callback must be this API's fixed callback route.")
        if self.connector_complete_url:
            target = urlsplit(self.connector_complete_url)
            origin = f"{target.scheme}://{target.netloc}"
            if origin not in self.allowed_origins or target.fragment:
                raise ValueError("The connector completion URL must use an allowed origin.")
        if self.connector_synthetic_state is not None and self.environment != "development":
            raise ValueError("The synthetic connector provider is for development only.")
        if self.connector_instagram_enabled:
            app_id = self.instagram_app_id
            secret = self.instagram_app_secret.get_secret_value()
            if not (
                app_id.isascii()
                and app_id.isdigit()
                and len(app_id) <= 32
                and secret.isascii()
                and secret.isalnum()
                and 16 <= len(secret) <= 128
            ):
                raise ValueError("The Instagram connector requires the Meta app ID and secret.")
        if self.connector_youtube_enabled:
            client = self.youtube_client_id
            secret = self.youtube_client_secret.get_secret_value()
            if not (
                client.isascii()
                and client.endswith(".apps.googleusercontent.com")
                and len(client) <= 128
                and secret.isascii()
                and secret.strip() == secret
                and 8 <= len(secret) <= 128
            ):
                raise ValueError("The YouTube connector requires its Web client ID and secret.")
            if client in {self.google_client_id, self.gmail_client_id}:
                raise ValueError("The YouTube connector needs a client of its own.")
        if self.connector_meta_ads_enabled:
            app_id, config_id = self.meta_ads_app_id, self.meta_ads_config_id
            secret = self.meta_ads_app_secret.get_secret_value()
            if not (
                app_id.isascii()
                and app_id.isdigit()
                and len(app_id) <= 32
                and config_id.isascii()
                and config_id.isdigit()
                and len(config_id) <= 32
                and secret.isascii()
                and secret.isprintable()
                and secret.strip() == secret
                and 1 <= len(secret) <= 128
            ):
                raise ValueError(
                    "The Meta advertising connectors require the app ID, secret and login "
                    "configuration ID."
                )
        if self.whatsapp_enabled:
            secrets = (
                self.whatsapp_app_secret.get_secret_value(),
                self.whatsapp_verify_token.get_secret_value(),
            )
            if not all(
                value.isascii()
                and value.isprintable()
                and value.strip() == value
                and 16 <= len(value) <= 256
                for value in secrets
            ):
                raise ValueError("WhatsApp intake requires the app secret and a verify token.")

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

    # Enabled billing needs Paddle's API key of the configured environment, whose documented
    # form carries sdbx or live (V-12), and the notification destination's secret (V-4). An
    # optional client-side token must be of the same environment (test_ or live_). Errors name
    # the setting, never its value.
    def _validate_billing(self) -> None:
        sandbox = self.billing_paddle_environment == "sandbox"
        key = PADDLE_API_KEY.fullmatch(self.billing_paddle_api_key.get_secret_value())
        if key is None or (key.group(1) == "sdbx") != sandbox:
            raise ValueError("Billing requires the Paddle API key of the configured environment.")
        secret = self.billing_paddle_webhook_secret.get_secret_value()
        if not PADDLE_WEBHOOK_SECRET.fullmatch(secret):
            raise ValueError("Billing requires the Paddle webhook secret.")
        if self.billing_paddle_client_token:
            token = PADDLE_CLIENT_TOKEN.fullmatch(self.billing_paddle_client_token)
            if token is None or (token.group(1) == "test") != sandbox:
                raise ValueError("The Paddle client token must match the configured environment.")

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

    # Short-lived cookie binding a connector authorization to the browser session that started
    # it, limited to the /connectors/oauth path and separate from the Google sign-in cookie.
    @property
    def connector_cookie_name(self) -> str:
        return (
            "__Secure-tracking_connector_oauth"
            if self.cookie_secure
            else "tracking_connector_oauth"
        )

    # Where the browser goes after a connector callback.
    @property
    def connector_completion_url(self) -> str:
        return self.connector_complete_url or f"{self.frontend_origin}/connections/complete"

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
    # Connector webhook delivery records (D-049 decision D19): 7 days after receipt.
    webhook_delivery_retention_days: int = Field(default=7, ge=0, le=7)
    # Connector records (D-053 decision D9): at most 2 years after observation; the
    # disconnect, deauthorize and data deletion purges remove them earlier.
    connector_record_retention_days: int = Field(default=730, ge=0, le=730)
    # 011-A (D11): record attributes and account labels not refreshed for 30 days are cleared,
    # and a provider may keep its records for a shorter period (730 days for YouTube).
    connector_attribute_refresh_days: int = Field(default=30, ge=0, le=30)
    connector_provider_retention_days: dict[str, int] = Field(
        default_factory=lambda: {"synthetic_youtube": 730, "youtube": 730}
    )
    # 014 (D-064 decision D13, provisional development values): spend facts at most 730 days
    # after their spend date.
    ad_spend_retention_days: int = Field(default=730, ge=0, le=730)
    # Ended conversion deliveries and their acknowledgements 30 days after they end (D13).
    delivery_retention_days: int = Field(default=30, ge=0, le=30)
    # 015 (D-067 decision D14, provisional development values): Paymob callback diagnostics
    # 30 days after receipt; replaced payment source secrets are deleted once retired.
    payment_diagnostic_retention_days: int = Field(default=30, ge=0, le=30)
    # Revenue import records (D-067 D14): 13 months (395 days) after the commit; the declared
    # evidence stays.
    revenue_import_retention_days: int = Field(default=395, ge=0, le=395)
    # 015-D (D-068 E9, provisional development values): integration deliveries 30 days after
    # receipt; bookings and CRM deals 13 months (395 days) after their last update.
    integration_delivery_retention_days: int = Field(default=30, ge=0, le=30)
    booking_retention_days: int = Field(default=395, ge=0, le=395)
    deal_retention_days: int = Field(default=395, ge=0, le=395)
    # 015-E (D-068 E9): WhatsApp referral messages 395 days after receipt.
    whatsapp_message_retention_days: int = Field(default=395, ge=0, le=395)
    # 017-C (D-103 D7, provisional under Q-012): Paddle events 395 days after receipt, and open
    # or expired checkouts 30 days after their expiry.
    billing_event_retention_days: int = Field(default=395, ge=0, le=395)
    billing_checkout_retention_days: int = Field(default=30, ge=0, le=30)
    outbox_retention_days: int = Field(default=30, ge=0, le=30)
    local_mail_retention_days: int = Field(default=7, ge=0, le=7)
    # Provisional development retention for collected data (D-027 decision 7): event rows 13
    # months (395 days) after first receipt, diagnostic counters 30 days after their day, and
    # subjects with their consent records 13 months after last activity.
    event_retention_days: int = Field(default=395, ge=0, le=395)
    diagnostic_retention_days: int = Field(default=30, ge=0, le=30)
    subject_retention_days: int = Field(default=395, ge=0, le=395)
    lifecycle_batch_size: int = Field(default=500, ge=1, le=5000)

    @field_validator("connector_provider_retention_days")
    @classmethod
    def _bounded_provider_retention(cls, value: dict[str, int]) -> dict[str, int]:
        for provider, days in value.items():
            if not provider.replace("_", "").isalnum() or not 0 <= days <= 730:
                raise ValueError("Provider retention needs a provider name and 0 to 730 days.")
        return value


# Separate migrator credentials through explicit TRACKING_MIGRATION_* aliases, with a longer
# per-statement timeout for DDL. This is neither a database uptime allowance nor a grant of
# schema privileges to the runtime role.
class MigrationSettings(DatabaseSettings):
    database_user: str = Field(
        default="tracking_migrator", validation_alias="TRACKING_MIGRATION_USER"
    )
    database_password: SecretStr = Field(validation_alias="TRACKING_MIGRATION_PASSWORD")
    database_statement_timeout_ms: int = Field(default=30000, ge=100, le=60000)
