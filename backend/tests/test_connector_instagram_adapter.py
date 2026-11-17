"""Instagram API with Instagram Login adapter (specification 010-C, D-055).

Offline: every answer comes from the in-memory FakeGraph, which reproduces the shapes the 010-B
feasibility check recorded with the owner's development app. No case contacts Meta.
"""

import base64
import hashlib
import hmac
import json
import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from instagram_graph import (
    APP_ID,
    APP_SCOPED_ID,
    APP_SECRET,
    LONG_LIVED,
    PERMISSIONS,
    PRODUCT_METRICS,
    USERNAME,
    FakeGraph,
    graph_error,
)
from pydantic import SecretStr, ValidationError

import app.services.connectors as connectors
from app.config import Settings
from app.connectors.contracts import ErrorKind, ProviderError, WebhookRejected
from app.connectors.instagram import (
    CAPABILITY,
    MEDIA_PAGE,
    SCOPES,
    InstagramProvider,
    Reply,
    app_usage,
)
from app.logging_config import AllowlistFormatter
from app.privacy.providers import RuleStatus
from app.services.connectors import build_providers

NOW = datetime(2026, 11, 17, 15, 30, tzinfo=UTC)
REDIRECT = "https://tracking.example.test/connectors/oauth/callback"


@pytest.fixture
def graph():
    return FakeGraph(lambda: NOW)


@pytest.fixture
def provider(graph):
    return InstagramProvider(APP_ID, APP_SECRET, transport=graph, clock=lambda: NOW)


def _token(provider, graph):
    return provider.exchange(
        code=graph.issue_code(), code_verifier=None, redirect_uri=REDIRECT
    ).access_token


def _pages(provider, token, **window):
    pages, cursor = [], None
    while True:
        page = provider.fetch_page(token, cursor=cursor, **window)
        pages.append(page)
        cursor = page.next_cursor
        if cursor is None:
            return pages


def _signed(payload: dict, secret: str = APP_SECRET) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature).decode().rstrip("=") + "." + encoded


def test_capability_matches_the_approved_decisions():
    assert CAPABILITY.provider == "instagram" and CAPABILITY.pkce is None
    assert CAPABILITY.refresh_mode == "self" and CAPABILITY.revocation_scope == "unsupported"
    assert (
        CAPABILITY.scopes
        == SCOPES
        == (
            "instagram_business_basic",
            "instagram_business_manage_insights",
        )
    )
    assert CAPABILITY.daily_quota is None and CAPABILITY.data_delay_hours == 48
    assert {spec.name: spec.history_days for spec in CAPABILITY.stream_specs()} == {
        "account": 729,
        "media": 730,
        "stories": 1,
    }
    # The D2/D-054 catalog by product type is exactly what the live answers offered.
    for product, offered in PRODUCT_METRICS.items():
        stream = "stories" if product == "STORY" else "media"
        declared = {
            spec.name
            for spec in CAPABILITY.stream_metrics(stream)
            if spec.product_types is not None and product in spec.product_types
        }
        assert declared == offered
    assert "link_clicks" not in {spec.name for spec in CAPABILITY.metrics}
    assert "impressions" not in {spec.name for spec in CAPABILITY.metrics}


def test_authorization_url_requests_read_only_scopes_without_pkce(provider):
    url = provider.authorization_url(
        state="synthetic-state", code_challenge=None, redirect_uri=REDIRECT, scopes=SCOPES
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://www.instagram.com/oauth/authorize"
    )
    assert {key: values[0] for key, values in parse_qs(parts.query).items()} == {
        "client_id": APP_ID,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": "instagram_business_basic,instagram_business_manage_insights",
        "state": "synthetic-state",
    }
    assert APP_SECRET not in url


@pytest.mark.parametrize("shape", ["flat", "data"])
def test_exchange_records_the_app_scoped_account_and_every_granted_permission(
    provider, graph, shape
):
    graph.exchange_shape = shape
    code = graph.issue_code()
    grant = provider.exchange(code=code, code_verifier=None, redirect_uri=REDIRECT)
    assert grant.external_account_id == APP_SCOPED_ID
    assert (grant.account_label, grant.account_kind) == (USERNAME, "business")
    assert grant.refresh_token is None
    assert grant.access_expires_at == NOW + timedelta(seconds=LONG_LIVED)
    # Instagram grants every permission configured on the app, not only the requested ones.
    assert grant.scopes == tuple(sorted(PERMISSIONS))
    assert set(grant.scopes) - set(SCOPES)
    assert grant.access_token not in repr(grant) and APP_SECRET not in repr(provider)
    # A code is single use, and the "#_" suffix Instagram appends is removed.
    with pytest.raises(ProviderError) as reused:
        provider.exchange(code=code, code_verifier=None, redirect_uri=REDIRECT)
    assert (reused.value.kind, reused.value.provider_code) == (
        ErrorKind.PERMANENT,
        "invalid_grant",
    )
    wrong = InstagramProvider(APP_ID, "f" * 32, transport=graph, clock=lambda: NOW)
    with pytest.raises(ProviderError) as refused:
        wrong.exchange(code=graph.issue_code(), code_verifier=None, redirect_uri=REDIRECT)
    assert refused.value.kind is ErrorKind.PERMANENT


def test_exchange_fails_closed_without_the_app_scoped_id(provider, graph):
    graph.fail_next("me", Reply(200, {"user_id": "17841400000000001", "username": USERNAME}))
    with pytest.raises(ProviderError) as missing:
        provider.exchange(code=graph.issue_code(), code_verifier=None, redirect_uri=REDIRECT)
    assert (missing.value.kind, missing.value.provider_code) == (ErrorKind.PERMANENT, "no_account")
    graph.fail_next("oauth/access_token", graph_error(1, 500))
    with pytest.raises(ProviderError) as unavailable:
        provider.exchange(code=graph.issue_code(), code_verifier=None, redirect_uri=REDIRECT)
    assert unavailable.value.kind is ErrorKind.RETRYABLE


def test_self_refresh_replaces_the_long_lived_token(provider, graph):
    token = _token(provider, graph)
    # Meta refreshes only a token that is at least 24 hours old.
    with pytest.raises(ProviderError) as early:
        provider.refresh(token)
    assert early.value.kind is ErrorKind.UNAUTHORIZED
    graph.age(token, 25)
    grant = provider.refresh(token)
    assert grant.access_token != token and grant.refresh_token is None
    assert grant.access_expires_at == NOW + timedelta(seconds=LONG_LIVED)
    assert (grant.external_account_id, grant.scopes) == ("", ())
    graph.expire(grant.access_token)
    with pytest.raises(ProviderError) as expired:
        provider.refresh(grant.access_token)
    assert expired.value.kind is ErrorKind.UNAUTHORIZED
    graph.fail_next("refresh_access_token", graph_error(2, 503))
    with pytest.raises(ProviderError) as busy:
        provider.refresh(token)
    assert busy.value.kind is ErrorKind.RETRYABLE
    assert provider.revoke(token, "access_token") == "unsupported"


def test_account_stream_reads_one_complete_utc_day_per_page(provider, graph):
    token = _token(provider, graph)
    pages = _pages(provider, token, stream="account")
    records = [record for page in pages for record in page.records]
    # The default recent window is the 7 complete days before the current UTC day.
    assert [record.provider_object_id for record in records] == [
        f"day-2026-11-{day:02d}" for day in range(10, 17)
    ]
    assert all(record.observed_at.hour == 0 for record in records)
    assert {(page.covered_from, page.complete_through) for page in pages} == {
        (datetime(2026, 11, 10, tzinfo=UTC), datetime(2026, 11, 17, tzinfo=UTC))
    }
    first = records[0]
    assert set(first.metrics) == {spec.name for spec in CAPABILITY.stream_metrics("account")} - {
        "follows_and_unfollows"
    }
    # Under 100 followers the provider answers empty data, which is a threshold, not zero.
    assert first.unavailable == {"follows_and_unfollows": "below_threshold"}
    assert graph.paths().count("17841400000000001/insights") == 7
    graph.followers = 150
    page = provider.fetch_page(token, stream="account", since=NOW - timedelta(days=1))
    assert "follows_and_unfollows" in page.records[0].metrics
    assert page.records[0].unavailable == {}
    # The history limit is 729 days back.
    page = provider.fetch_page(token, stream="account", since=NOW - timedelta(days=1000))
    assert page.covered_from == datetime(2024, 11, 18, tzinfo=UTC)
    with pytest.raises(ProviderError) as cursor:
        provider.fetch_page(token, stream="account", cursor="sig_cursor_1")
    assert (cursor.value.kind, cursor.value.provider_code) == (
        ErrorKind.PERMANENT,
        "invalid_cursor",
    )


def test_account_stream_marks_an_empty_metric_not_returned(provider, graph):
    token = _token(provider, graph)
    graph.followers = 150
    graph.fail_next(
        "insights",
        Reply(200, {"data": [{"name": "reach", "period": "day", "total_value": {"value": 7}}]}),
    )
    record = provider.fetch_page(token, stream="account", since=NOW - timedelta(days=1)).records[0]
    assert record.metrics == {"reach": 7}
    assert set(record.unavailable.values()) == {"not_returned"}
    assert "reach" not in record.unavailable


def test_media_stream_reads_product_type_metrics_with_cursor_paging(provider, graph):
    token = _token(provider, graph)
    feed = [graph.post("FEED", timedelta(hours=hours)) for hours in range(1, 12)]
    reel = graph.post("REELS", timedelta(days=2), "VIDEO")
    graph.post("FEED", timedelta(days=10))
    pages = _pages(provider, token, stream="media")
    assert len(pages) == 2 and pages[0].next_cursor is not None
    records = {record.provider_object_id: record for page in pages for record in page.records}
    assert set(records) == {item.id for item in feed} | {reel.id}
    for record in records.values():
        assert set(record.metrics) == PRODUCT_METRICS[record.product_type]
        assert record.unavailable == {}
    assert records[reel.id].product_type == "REELS"
    # Only the metrics a product type offers are requested, so nothing is refused.
    requested = {
        metric
        for _, path, metric in graph.calls
        if path == f"{reel.id}/insights"
        for metric in metric.split(",")
    }
    assert requested == PRODUCT_METRICS["REELS"]
    assert len(pages[0].records) == MEDIA_PAGE
    assert pages[0].complete_through == NOW


def test_media_stream_falls_back_metric_by_metric_and_skips_unreadable_items(provider, graph):
    token = _token(provider, graph)
    changed = graph.post("FEED", timedelta(hours=1))
    gone = graph.post("FEED", timedelta(hours=2))
    later = graph.post("REELS", timedelta(hours=3), "VIDEO")
    graph.unsupported[changed.id] = {"follows"}
    graph.deleted.add(gone.id)
    page = provider.fetch_page(token, stream="media", until=NOW - timedelta(minutes=90))
    # The window ends before the newest item, and the deleted item has no insights at all.
    assert [record.provider_object_id for record in page.records] == [later.id]
    page = provider.fetch_page(token, stream="media")
    records = {record.provider_object_id: record for record in page.records}
    assert set(records) == {changed.id, later.id}
    assert records[changed.id].unavailable == {"follows": "not_returned"}
    assert "follows" not in records[changed.id].metrics


def test_stories_stream_rereads_every_live_story(provider, graph):
    token = _token(provider, graph)
    story = graph.post("STORY", timedelta(hours=5))
    graph.post("STORY", timedelta(hours=30))
    # An incremental window that starts after the story still refreshes its values.
    page = provider.fetch_page(token, stream="stories", since=NOW - timedelta(hours=1))
    assert [record.provider_object_id for record in page.records] == [story.id]
    record = page.records[0]
    assert record.product_type == "STORY"
    assert set(record.metrics) == PRODUCT_METRICS["STORY"] and record.unavailable == {}
    assert (page.covered_from, page.complete_through) == (NOW - timedelta(days=1), NOW)
    assert page.next_cursor is None


@pytest.mark.parametrize(
    ("reply", "kind", "retry_after"),
    [
        (graph_error(190, 400, "OAuthException"), ErrorKind.UNAUTHORIZED, None),
        (Reply(401, {}), ErrorKind.UNAUTHORIZED, None),
        (graph_error(10, 400), ErrorKind.FORBIDDEN, None),
        (graph_error(200, 403), ErrorKind.FORBIDDEN, None),
        (graph_error(4), ErrorKind.RATE_LIMITED, 900),
        (graph_error(17), ErrorKind.RATE_LIMITED, 900),
        (graph_error(32), ErrorKind.RATE_LIMITED, 900),
        (graph_error(613), ErrorKind.RATE_LIMITED, 900),
        (graph_error(80002), ErrorKind.RATE_LIMITED, 900),
        (Reply(429, {}), ErrorKind.RATE_LIMITED, 900),
        (graph_error(2, 503), ErrorKind.RETRYABLE, None),
        (Reply(502, "not json"), ErrorKind.RETRYABLE, None),
        (graph_error(100), ErrorKind.PERMANENT, None),
    ],
)
def test_graph_errors_map_to_runtime_kinds(provider, graph, reply, kind, retry_after):
    token = _token(provider, graph)
    graph.fail_next("me", reply)
    with pytest.raises(ProviderError) as raised:
        provider.fetch_page(token, stream="account")
    assert raised.value.kind is kind and raised.value.retry_after == retry_after
    assert token not in repr(raised.value) and "synthetic" not in raised.value.provider_code


def test_app_usage_defers_before_meta_throttles(provider, graph):
    token = _token(provider, graph)
    graph.usage = 50
    assert provider.fetch_page(token, stream="stories").next_cursor is None
    graph.usage = 95
    with pytest.raises(ProviderError) as raised:
        provider.fetch_page(token, stream="stories")
    assert (raised.value.kind, raised.value.provider_code, raised.value.retry_after) == (
        ErrorKind.RATE_LIMITED,
        "app_usage",
        900,
    )
    assert app_usage({"x-app-usage": '{"call_count": 12, "total_cputime": 3}'}) == 12
    assert app_usage({"x-app-usage": "unreadable"}) is None
    assert app_usage({}) is None


def test_network_failures_are_retryable_without_details(monkeypatch):
    import urllib.request

    import app.connectors.instagram as instagram

    def unreachable(*args, **kwargs):
        raise OSError("synthetic network failure with access_token=secret")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    provider = InstagramProvider(APP_ID, APP_SECRET, clock=lambda: NOW)
    with pytest.raises(ProviderError) as raised:
        provider.fetch_page("token-value", stream="account")
    assert (raised.value.kind, raised.value.provider_code) == (ErrorKind.RETRYABLE, "network")
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert instagram.http_send.__name__ == "http_send"


def test_signed_requests_are_verified_before_they_are_read(provider, graph):
    issued = NOW - timedelta(minutes=1)
    request = graph.sign(APP_SCOPED_ID, issued)
    assert provider.verify_signed_request(request, NOW).external_account_id == APP_SCOPED_ID
    numeric = _signed(
        {"algorithm": "HMAC-SHA256", "issued_at": int(issued.timestamp()), "user_id": 91}
    )
    assert provider.verify_signed_request(numeric, NOW).external_account_id == "91"
    signature, _, payload = request.partition(".")
    tampered = _signed({"algorithm": "HMAC-SHA256", "issued_at": 1, "user_id": "x"})
    cases = {
        graph.sign(APP_SCOPED_ID, issued, "f" * 32): "signature_invalid",
        signature + "." + tampered.partition(".")[2]: "signature_invalid",
        "not-base64!." + payload: "signature_invalid",
        signature + ".": "signature_invalid",
        graph.sign(APP_SCOPED_ID, NOW - timedelta(hours=25)): "signature_expired",
        graph.sign(APP_SCOPED_ID, NOW + timedelta(minutes=10)): "signature_expired",
        _signed({"algorithm": "HMAC-SHA1", "issued_at": 1, "user_id": "x"}): "invalid_delivery",
        _signed({"algorithm": "HMAC-SHA256", "issued_at": "1", "user_id": "x"}): "invalid_delivery",
        _signed({"algorithm": "HMAC-SHA256", "issued_at": 1}): "invalid_delivery",
        _signed({"algorithm": "HMAC-SHA256", "issued_at": 1, "user_id": ""}): "invalid_delivery",
        _signed({"algorithm": "HMAC-SHA256", "issued_at": 1, "user_id": True}): "invalid_delivery",
    }
    for value, reason in cases.items():
        with pytest.raises(WebhookRejected) as rejected:
            provider.verify_signed_request(value, NOW)
        assert rejected.value.reason == reason, value
    unsigned = InstagramProvider(APP_ID, "", transport=graph, clock=lambda: NOW)
    with pytest.raises(WebhookRejected):
        unsigned.verify_signed_request(_signed({"user_id": "x"}, ""), NOW)
    with pytest.raises(WebhookRejected):
        provider.verify_webhook({}, b"{}", NOW)


def test_registry_needs_enablement_configuration_and_current_rules(settings, monkeypatch):
    assert "instagram" not in build_providers(settings)
    enabled = settings.model_copy(
        update={
            "connector_instagram_enabled": True,
            "instagram_app_id": APP_ID,
            "instagram_app_secret": SecretStr(APP_SECRET),
        }
    )
    registry = build_providers(enabled, date(2026, 11, 17))
    assert set(registry) == {"instagram"}
    assert isinstance(registry["instagram"], InstagramProvider)
    assert repr(registry) == "{'instagram': InstagramProvider()}"
    # A rule past its review date, or a stale rule, keeps the adapter out of the registry.
    assert build_providers(enabled, date(2027, 11, 18)) == {}
    original = connectors.rule
    monkeypatch.setattr(
        connectors,
        "rule",
        lambda name: (
            replace(original(name), status=RuleStatus.STALE)
            if name == "instagram.login_api"
            else original(name)
        ),
    )
    assert build_providers(enabled, date(2026, 11, 17)) == {}
    base = {"database_password": "synthetic", "_env_file": None}
    for values in (
        {"instagram_app_id": "", "instagram_app_secret": APP_SECRET},
        {"instagram_app_id": "12ab", "instagram_app_secret": APP_SECRET},
        {"instagram_app_id": APP_ID, "instagram_app_secret": ""},
        {"instagram_app_id": APP_ID, "instagram_app_secret": "short"},
        {"instagram_app_id": APP_ID, "instagram_app_secret": "a" * 31 + "-"},
    ):
        with pytest.raises(ValidationError) as invalid:
            Settings(**base, connector_instagram_enabled=True, **values)
        assert APP_SECRET not in str(invalid.value)
    disabled = Settings(**base, instagram_app_id="", instagram_app_secret="")
    assert disabled.connector_instagram_enabled is False


def test_extra_scope_event_is_registered_without_fields():
    formatter = AllowlistFormatter()
    record = logging.makeLogRecord(
        {"name": "tracking", "msg": "connector_extra_scopes", "levelname": "WARNING"}
    )
    assert json.loads(formatter.format(record))["event"] == "connector_extra_scopes"
    record = logging.makeLogRecord(
        {
            "name": "tracking",
            "msg": "connector_extra_scopes",
            "levelname": "WARNING",
            "scopes": "instagram_business_content_publish",
        }
    )
    assert json.loads(formatter.format(record)) | {"timestamp": None} == {
        "timestamp": None,
        "level": "WARNING",
        "event": "log_event_rejected",
        "rejection": "unregistered_field",
    }
