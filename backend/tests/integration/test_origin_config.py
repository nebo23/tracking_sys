"""Configured alternate origins for a non-default published API port (review F-01)."""

import pytest

from app.config import Settings

pytestmark = pytest.mark.integration

ALTERNATE = "http://127.0.0.1:18002"


def test_alternate_origin_mutation_is_allowed_and_foreign_origins_fail(api, monkeypatch):
    monkeypatch.setenv("TRACKING_ALLOWED_ORIGINS", f'["{ALTERNATE}","http://localhost:18002"]')
    resolved = Settings(_env_file=None, cookie_secure=False)
    assert resolved.allowed_origins == [ALTERNATE, "http://localhost:18002"]
    settings = resolved.model_copy(update={"mail_directory": api.config.mail_directory})
    body = {
        "email": "alternate.origin@example.test",
        "display_name": "Alternate origin",
        "password": api.password,
    }
    client = api.new_client(settings)
    client.headers["Origin"] = ALTERNATE
    assert client.post("/auth/register", json=body).status_code == 202
    for origin in ("http://127.0.0.1:8000", "https://foreign.example.test"):
        client.headers["Origin"] = origin
        response = client.post("/auth/register", json=body)
        assert response.status_code == 403
        assert response.json() == {"error": "origin_not_allowed"}
    preflight = client.options(
        "/auth/register",
        headers={"Origin": "https://foreign.example.test", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers
