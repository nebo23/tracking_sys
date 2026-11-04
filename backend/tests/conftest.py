import pytest
from pydantic import SecretStr

from app.config import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    # Keep unit tests independent of workstation credentials and dotenv files.
    import os

    for name in list(os.environ):
        if name.startswith("TRACKING_"):
            monkeypatch.delenv(name)
    import base64

    monkeypatch.setenv("TRACKING_AUTH_SECRET", "ab" * 32)
    monkeypatch.setenv("TRACKING_OTP_SECRET", "cd" * 32)
    monkeypatch.setenv("TRACKING_MAIL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    return Settings(
        _env_file=None,
        database_password=SecretStr("synthetic-unit-test-password"),
    )
