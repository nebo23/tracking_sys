import pytest
from pydantic import SecretStr, ValidationError

from app.config import MigrationSettings, Settings


def test_password_is_required_and_validation_hides_input(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_password="")
    secret = "never-print-this"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_password=secret, database_port="invalid")
    assert secret not in str(error.value)


def test_special_characters_in_password_are_not_parsed_as_url(settings: Settings) -> None:
    secret = "password:@/%?with-characters"
    configuration = Settings(_env_file=None, database_password=SecretStr(secret))
    assert configuration.database_url.password == secret
    assert secret not in str(configuration.database_url)
    assert secret not in repr(configuration)


def test_migrations_use_separate_credentials(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRACKING_DATABASE_PASSWORD", "runtime-secret")
    monkeypatch.setenv("TRACKING_MIGRATION_PASSWORD", "migration-secret")
    runtime = Settings(_env_file=None)
    migration = MigrationSettings(_env_file=None)
    assert runtime.database_user == "tracking_app"
    assert migration.database_user == "tracking_migrator"
    assert runtime.database_url.password == "runtime-secret"
    assert migration.database_url.password == "migration-secret"


@pytest.mark.parametrize(
    "changes",
    [
        {"auth_secret": "short"},
        {"mail_encryption_key": "invalid"},
        {"allowed_origins": ["*"]},
        {"frontend_origin": "https://example.test/path"},
        {"cookie_secure": False, "allowed_origins": ["https://example.test"]},
        {"environment": "production"},
    ],
)
def test_auth_configuration_fails_closed(settings: Settings, changes: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(settings.model_dump() | changes))


def test_migration_configuration_does_not_require_auth_secrets(settings, monkeypatch):
    monkeypatch.delenv("TRACKING_AUTH_SECRET")
    monkeypatch.delenv("TRACKING_MAIL_ENCRYPTION_KEY")
    config = MigrationSettings(_env_file=None, TRACKING_MIGRATION_PASSWORD="synthetic")
    assert config.database_user == "tracking_migrator"


def test_alternate_origins_resolve_from_forwarded_environment(settings, monkeypatch):
    # Mirrors the JSON list Compose forwards when TRACKING_API_PORT=18002 (review F-01).
    monkeypatch.setenv(
        "TRACKING_ALLOWED_ORIGINS",
        '["http://127.0.0.1:18002","http://localhost:18002","http://127.0.0.1:5173"]',
    )
    monkeypatch.setenv("TRACKING_FRONTEND_ORIGIN", "http://localhost:5173")
    resolved = Settings(_env_file=None, database_password="synthetic", cookie_secure=False)
    assert resolved.allowed_origins == [
        "http://127.0.0.1:18002",
        "http://localhost:18002",
        "http://127.0.0.1:5173",
    ]
    assert resolved.frontend_origin == "http://localhost:5173"
    monkeypatch.setenv("TRACKING_ALLOWED_ORIGINS", '["http://127.0.0.1:18002","*"]')
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_password="synthetic", cookie_secure=False)


GOOGLE = {
    "google_sign_in_enabled": True,
    "google_client_id": "synthetic-sign-in.apps.googleusercontent.com",
    "google_client_secret": "synthetic-secret",
}
GMAIL = {
    "mail_mode": "gmail",
    "gmail_client_id": "synthetic-sender.apps.googleusercontent.com",
    "gmail_client_secret": "synthetic-sender-secret",
    "gmail_refresh_token": "synthetic-refresh-token",
    "gmail_sender": "sender@example.test",
}


@pytest.mark.parametrize(
    "changes",
    [
        {"otp_secret": "ab" * 32},
        {"otp_secret": "short"},
        {"google_sign_in_enabled": True},
        GOOGLE | {"google_redirect_uri": "http://example.test/auth/google/callback"},
        GOOGLE | {"google_redirect_uri": "http://127.0.0.1:8000/other"},
        GOOGLE | {"google_complete_url": "https://foreign.example.test/done"},
        {"mail_mode": "gmail"},
        GMAIL | {"gmail_sender": "not-an-email"},
        GMAIL | GOOGLE | {"gmail_client_id": GOOGLE["google_client_id"]},
        GMAIL | {"environment": "production"},
    ],
)
def test_identity_and_mail_configuration_fails_closed(settings: Settings, changes: dict) -> None:
    base = settings.model_dump() | {"cookie_secure": False}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(base | changes))


def test_complete_google_and_gmail_configuration_is_accepted(settings: Settings) -> None:
    base = settings.model_dump() | {"cookie_secure": False}
    configured = Settings(_env_file=None, **(base | GOOGLE | GMAIL))
    assert configured.google_completion_url == "http://127.0.0.1:5173/auth/google/complete"
    assert configured.oauth_cookie_name == "tracking_oauth"
    assert configured.mail_mode == "gmail"
