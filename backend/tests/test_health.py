from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError

import app.main as main
from app.config import Settings
from app.database import expected_revision, readiness_failure


def fake_engine() -> MagicMock:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalars.return_value = [expected_revision()]
    return engine


def test_ready_after_connection_and_schema_check(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = fake_engine()
    monkeypatch.setattr(main, "create_database_engine", lambda _, **kwargs: engine)
    with TestClient(main.create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        assert response.headers["cache-control"] == "no-store"
    assert engine.dispose.call_count == 2


def test_database_failure_keeps_liveness_and_redacts_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = fake_engine()
    secret = "sensitive-database-password"
    engine.connect.side_effect = OperationalError("SELECT 1", {}, RuntimeError(secret))
    monkeypatch.setattr(main, "create_database_engine", lambda _, **kwargs: engine)
    with TestClient(main.create_app(settings)) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}
    assert secret not in ready.text
    assert secret not in capsys.readouterr().err


@pytest.mark.parametrize("revisions", [[], ["old_revision"], ["0001_foundation", "unexpected"]])
def test_schema_drift_blocks_readiness(revisions: list[str]) -> None:
    engine = fake_engine()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalars.return_value = revisions
    assert readiness_failure(engine, "0001_foundation") == "schema_mismatch"


def test_unmigrated_database_is_not_ready() -> None:
    engine = fake_engine()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.side_effect = [
        MagicMock(),
        ProgrammingError("SELECT version_num", {}, RuntimeError("missing version table")),
    ]
    assert readiness_failure(engine, "0001_foundation") == "schema_unavailable"
