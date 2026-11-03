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
