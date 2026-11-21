"""Connector contracts, the synthetic provider, and settings (specification 009-A, D-048)."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.connectors.contracts import ErrorKind, ProviderError, TokenGrant
from app.connectors.synthetic import SyntheticProvider, s256
from app.models import ConnectorConnection
from app.services.connectors import (
    build_providers,
    connection_view,
    pkce_challenge,
    pkce_verifier,
)

REDIRECT = "http://127.0.0.1:8000/connectors/oauth/callback"


def _authorize(provider, verifier="v" * 64, redirect=REDIRECT):
    url = provider.authorization_url(
        state="synthetic-state",
        code_challenge=s256(verifier),
        redirect_uri=redirect,
        scopes=("synthetic.metrics.read",),
    )
    return url, verifier


def test_exchange_requires_pkce_redirect_and_single_use(tmp_path):
    provider = SyntheticProvider(tmp_path / "state.sqlite3")
    url, verifier = _authorize(provider)
    assert parse_qs(urlsplit(url).query)["code_challenge_method"] == ["S256"]
    code = provider.approve(url, "syn-acct-1")
    with pytest.raises(ProviderError) as wrong:
        provider.exchange(code=code, code_verifier="w" * 64, redirect_uri=REDIRECT)
    assert wrong.value.kind is ErrorKind.PERMANENT
    # A presented code is spent even when the exchange fails.
    with pytest.raises(ProviderError):
        provider.exchange(code=code, code_verifier=verifier, redirect_uri=REDIRECT)
    code = provider.approve(url, "syn-acct-1")
    with pytest.raises(ProviderError):
        provider.exchange(code=code, code_verifier=verifier, redirect_uri=REDIRECT + "x")
    code = provider.approve(url, "syn-acct-1", "Label")
    grant = provider.exchange(code=code, code_verifier=verifier, redirect_uri=REDIRECT)
    assert (grant.external_account_id, grant.account_label) == ("syn-acct-1", "Label")
    with pytest.raises(ProviderError):
        provider.exchange(code=code, code_verifier=verifier, redirect_uri=REDIRECT)
    assert provider.calls()[-1] == ("exchange", "invalid_grant")
    with pytest.raises(ValueError):
        provider.approve(url.replace("S256", "plain"), "syn-acct-1")


def test_revocation_is_per_grant_and_visible_to_another_instance(tmp_path):
    path = tmp_path / "state.sqlite3"
    provider = SyntheticProvider(path)
    url, verifier = _authorize(provider)
    first = provider.exchange(
        code=provider.approve(url, "shared"), code_verifier=verifier, redirect_uri=REDIRECT
    )
    second = provider.exchange(
        code=provider.approve(url, "shared"), code_verifier=verifier, redirect_uri=REDIRECT
    )
    other_process_view = SyntheticProvider(path)
    assert other_process_view.revoke(first.refresh_token, "refresh_token") == "done"
    assert not provider.token_usable(first.access_token)
    assert not provider.token_usable(first.refresh_token)
    assert provider.token_usable(second.access_token)
    assert provider.fetch_page(second.access_token).records
    with pytest.raises(ProviderError) as revoked:
        provider.fetch_page(first.access_token)
    assert revoked.value.kind is ErrorKind.UNAUTHORIZED
    # Revoking an already revoked token is confirmed again; an unknown token is an error.
    assert provider.revoke(first.access_token, "access_token") == "done"
    with pytest.raises(ProviderError):
        provider.revoke("syn_at_unknown", "access_token")
    with pytest.raises(ProviderError):
        provider.refresh(first.refresh_token)
    assert provider.grants() == [("shared", True), ("shared", False)]


def test_injected_behaviors_and_expiry(tmp_path):
    provider = SyntheticProvider(tmp_path / "state.sqlite3")
    provider.set_behavior("access_ttl", "0")
    url, verifier = _authorize(provider)
    grant = provider.exchange(
        code=provider.approve(url, "acct"), code_verifier=verifier, redirect_uri=REDIRECT
    )
    with pytest.raises(ProviderError):
        provider.fetch_page(grant.access_token)
    provider.set_behavior("access_ttl", "60")
    refreshed = provider.refresh(grant.refresh_token)
    assert refreshed.refresh_token == grant.refresh_token
    assert len(provider.fetch_page(refreshed.access_token).records) == 3
    provider.set_behavior("revoke", "unsupported")
    assert provider.revoke(grant.refresh_token, "refresh_token") == "unsupported"
    assert provider.token_usable(refreshed.access_token)
    provider.set_behavior("revoke", "retryable")
    with pytest.raises(ProviderError) as retry:
        provider.revoke(grant.refresh_token, "refresh_token")
    assert retry.value.kind is ErrorKind.RETRYABLE
    with pytest.raises(ValueError):
        provider.set_behavior("revoke", "sometimes")


def test_representations_omit_tokens():
    grant = TokenGrant("syn_at_secret", "syn_rt_secret", None, ("scope",), "acct")
    assert "secret" not in repr(grant)
    assert repr(ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")) == (
        "ProviderError('unauthorized')"
    )


def test_pkce_values_are_derived_and_not_stored(settings):
    verifier = pkce_verifier(settings, "raw-state")
    assert len(verifier) == 64 and verifier == pkce_verifier(settings, "raw-state")
    assert verifier != pkce_verifier(settings, "other-state")
    assert pkce_challenge(verifier) == s256(verifier)


def test_settings_fail_closed(settings, tmp_path):
    assert build_providers(settings) == {}
    configured = settings.model_copy(update={"connector_synthetic_state": tmp_path / "s.sqlite3"})
    assert set(build_providers(configured)) == {
        "synthetic",
        "synthetic_instagram",
        "synthetic_youtube",
        "synthetic_meta_ads",
    }
    base = {"database_password": "synthetic", "_env_file": None}
    with pytest.raises(ValidationError):
        Settings(**base, connector_redirect_uri="http://example.test/connectors/oauth/callback")
    with pytest.raises(ValidationError):
        Settings(**base, connector_redirect_uri="http://127.0.0.1:8000/other")
    with pytest.raises(ValidationError):
        Settings(**base, connector_complete_url="https://elsewhere.test/done")
    with pytest.raises(ValidationError):
        Settings(**base, connector_teardown_hours=73)
    with pytest.raises(ValidationError):
        Settings(**base, environment="production", connector_synthetic_state=tmp_path / "s")
    assert settings.connector_cookie_name == "__Secure-tracking_connector_oauth"
    assert settings.connector_completion_url.endswith("/connections/complete")


def test_connection_view_hides_worker_state():
    now = datetime(2026, 11, 15, tzinfo=UTC)
    row = ConnectorConnection(
        provider="synthetic",
        external_account_id=None,
        account_label=None,
        status="disconnected",
        status_reason="user_requested",
        generation=4,
        granted_scopes=["synthetic.metrics.read"],
        connected_at=now,
        disconnect_requested_at=now,
        purge_due_at=now,
        disconnected_at=now,
        revocation_status="failed",
        destruction_status="done",
        purge_status="done",
        teardown_attempts=3,
    )
    view = connection_view(row, manage=True)
    assert view.account is None
    assert view.disconnect["revocation"] == "failed" and view.disconnect["deadline_met"] is True
    assert view.actions == {"reconnect": False, "disconnect": False}
    assert "generation" not in vars(view) and "teardown_attempts" not in vars(view)
