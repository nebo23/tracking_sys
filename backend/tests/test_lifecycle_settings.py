"""Lifecycle settings bounds and development mail cleanup (specification 003-A3, D-024)."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.config import LifecycleSettings
from app.services.lifecycle import clean_local_mail

CUTOFF = datetime(2030, 1, 1, tzinfo=UTC)


def lifecycle(**values) -> LifecycleSettings:
    return LifecycleSettings(_env_file=None, TRACKING_LIFECYCLE_PASSWORD="synthetic", **values)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("TRACKING_"):
            monkeypatch.delenv(name)


def test_defaults_are_the_approved_periods_and_cannot_be_extended():
    settings = lifecycle()
    assert settings.database_user == "tracking_lifecycle"
    assert (
        settings.session_retention_days,
        settings.token_retention_days,
        settings.challenge_retention_days,
        settings.oauth_transaction_retention_days,
        settings.outbox_retention_days,
        settings.local_mail_retention_days,
    ) == (30, 7, 7, 1, 30, 7)
    for field, longer in (
        ("session_retention_days", 31),
        ("token_retention_days", 8),
        ("challenge_retention_days", 8),
        ("oauth_transaction_retention_days", 2),
        ("outbox_retention_days", 31),
        ("local_mail_retention_days", 8),
    ):
        with pytest.raises(ValidationError):
            lifecycle(**{field: longer})
    assert lifecycle(session_retention_days=7).session_retention_days == 7


def test_lifecycle_settings_do_not_require_application_secrets():
    settings = lifecycle()
    assert not hasattr(settings, "auth_secret") and not hasattr(settings, "otp_secret")


def write(path, age: timedelta) -> None:
    path.write_text("synthetic message")
    stamp = (CUTOFF - age).timestamp()
    os.utime(path, (stamp, stamp))


def test_local_mail_cleanup_removes_only_old_captures(tmp_path):
    old, edge = timedelta(days=7, seconds=1), timedelta(days=7)
    write(tmp_path / "old.eml", old)
    write(tmp_path / "old.pending", old)
    write(tmp_path / "boundary.eml", edge)
    write(tmp_path / "new.eml", timedelta(days=1))
    write(tmp_path / "notes.txt", old)
    (tmp_path / "nested").mkdir()
    write(tmp_path / "nested" / "old.eml", old)
    counts = clean_local_mail(lifecycle(mail_directory=tmp_path), CUTOFF)
    assert counts == {"deleted": 2, "failed": 0}
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "boundary.eml",
        "nested",
        "new.eml",
        "notes.txt",
    ]
    assert (tmp_path / "nested" / "old.eml").exists()


@pytest.mark.parametrize(
    "values", [{"environment": "production"}, {"mail_mode": "gmail"}], ids=["production", "gmail"]
)
def test_local_mail_cleanup_runs_only_in_development_local_mode(tmp_path, values):
    write(tmp_path / "old.eml", timedelta(days=30))
    counts = clean_local_mail(lifecycle(mail_directory=tmp_path, **values), CUTOFF)
    assert counts == {"deleted": 0, "failed": 0}
    assert (tmp_path / "old.eml").exists()


def test_missing_mail_directory_is_not_an_error(tmp_path):
    counts = clean_local_mail(lifecycle(mail_directory=tmp_path / "absent"), CUTOFF)
    assert counts == {"deleted": 0, "failed": 0}
