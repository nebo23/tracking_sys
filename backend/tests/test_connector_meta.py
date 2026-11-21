"""Meta live adapters against an in-memory Graph (specification 014-D, D-064 decision D12).

Cases T-50 to T-53 of the entry review section 7.4: registration only when enabled, configured
and allowed by current provider rules; Insights parsing, Conversions API request building,
answers and error classes; the Login for Business authorization URL, the exchange and the
recorded permissions; the delivery permission; and no network call anywhere in the suite.
"""

import json
import socket
import urllib.request
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from meta_graph import APP_ID, APP_SECRET, CODE, CONFIG_ID, TOKEN, MetaGraph
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.connectors import meta_ads
from app.connectors.contracts import ErrorKind, ProviderError
from app.connectors.meta_ads import (
    ADS_CAPABILITY,
    CAPI_CAPABILITY,
    MetaAdsProvider,
    MetaCapiProvider,
    regain_seconds,
)
from app.privacy import providers
from app.services import connectors as runtime
from app.services.connectors import LIVE_RULES, build_providers, rules_allow

REDIRECT = "http://127.0.0.1:8000/connectors/oauth/callback"
ACCOUNT, DATASET = "act_5550001", "7770001"
CLOCK = datetime(2026, 11, 10, 17, 0, tzinfo=UTC)
ZONE = "America/New_York"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    # T-53: any attempt to open a connection fails the test.
    def refuse(*args, **kwargs):
        raise AssertionError("The Meta fixture tests must not open a network connection.")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def graph():
    graph = MetaGraph()
    graph.accounts[ACCOUNT] = {
        "name": "Synthetic ad account",
        "currency": "USD",
        "timezone_name": ZONE,
        "account_status": 1,
    }
    graph.datasets[DATASET] = "Synthetic dataset"
    graph.objects = {
        "campaigns": [{"id": "111", "name": "Campaign", "effective_status": "ACTIVE"}],
        "adsets": [
            {"id": "211", "name": "Ad set", "effective_status": "PAUSED", "campaign_id": "111"}
        ],
        "ads": [
            {
                "id": ad,
                "name": f"Ad {ad}",
                "effective_status": status,
                "campaign_id": "111",
                "adset_id": "211",
            }
            for ad, status in (("311", "ACTIVE"), ("321", "ARCHIVED"), ("331", "DELETED"))
        ],
    }
    for offset in range(10):
        day = (date(2026, 11, 9) - timedelta(days=offset)).isoformat()
        graph.insights.append(
            {
                "ad_id": "311",
                "adset_id": "211",
                "campaign_id": "111",
                "spend": "5339.5" if offset == 0 else "12.34",
                "impressions": "361324",
                "clicks": "17",
                "account_currency": "USD",
                "date_start": day,
                "date_stop": day,
            }
        )
    return graph


def _ads(graph):
    return MetaAdsProvider(APP_ID, APP_SECRET, CONFIG_ID, transport=graph, clock=lambda: CLOCK)


def _capi(graph):
    return MetaCapiProvider(APP_ID, APP_SECRET, CONFIG_ID, transport=graph, clock=lambda: CLOCK)


def _settings(settings, **updates):
    return settings.model_copy(
        update={
            "connector_meta_ads_enabled": True,
            "meta_ads_app_id": APP_ID,
            "meta_ads_app_secret": SecretStr(APP_SECRET),
            "meta_ads_config_id": CONFIG_ID,
            **updates,
        }
    )


def test_registration_needs_settings_and_current_rules(settings, monkeypatch):
    # T-50: neither adapter is registered unless enabled and configured with current rules; a
    # stale or overdue rule removes it.
    assert LIVE_RULES["meta_ads"] == ("meta.platform_data", "meta.marketing_api")
    assert LIVE_RULES["meta_capi"] == ("meta.platform_data", "meta.conversions_api")
    today = date(2026, 11, 21)
    assert set(build_providers(settings, today)) == set()
    enabled = _settings(settings)
    registry = build_providers(enabled, today)
    assert isinstance(registry["meta_ads"], MetaAdsProvider)
    assert isinstance(registry["meta_capi"], MetaCapiProvider)
    assert set(build_providers(enabled, date(2027, 11, 21))) == set()
    for name in ("meta.marketing_api", "meta.conversions_api"):
        stale = tuple(
            replace(item, status=providers.RuleStatus.STALE) if item.rule_id == name else item
            for item in providers.RULES
        )
        with monkeypatch.context() as patched:
            patched.setattr(providers, "RULES", stale)
            kept = set(build_providers(enabled, today))
        assert kept == ({"meta_capi"} if name == "meta.marketing_api" else {"meta_ads"})
    assert rules_allow("meta_ads", today) and rules_allow("meta_capi", today)
    assert not rules_allow("meta_ads", date(2027, 11, 21))


def test_settings_fail_closed(settings):
    base = {"database_password": "synthetic", "_env_file": None}
    for values in (
        {"meta_ads_app_id": "", "meta_ads_app_secret": "s" * 32, "meta_ads_config_id": "1"},
        {"meta_ads_app_id": "abc", "meta_ads_app_secret": "s" * 32, "meta_ads_config_id": "1"},
        {"meta_ads_app_id": "1", "meta_ads_app_secret": "", "meta_ads_config_id": "1"},
        {"meta_ads_app_id": "1", "meta_ads_app_secret": "s" * 32, "meta_ads_config_id": ""},
        {"meta_ads_app_id": "1", "meta_ads_app_secret": "s" * 32, "meta_ads_config_id": "x1"},
    ):
        with pytest.raises(ValidationError):
            Settings(**base, connector_meta_ads_enabled=True, **values)
    configured = Settings(
        **base,
        connector_meta_ads_enabled=True,
        meta_ads_app_id=APP_ID,
        meta_ads_app_secret=APP_SECRET,
        meta_ads_config_id=CONFIG_ID,
    )
    assert configured.connector_meta_ads_enabled and APP_SECRET not in repr(configured)
    assert Settings(**base).connector_meta_ads_enabled is False


def test_authorization_url_and_exchange_record_permissions(graph):
    # T-51: Login for Business with the configuration ID; the exchange, then debug_token.
    provider = _ads(graph)
    url = provider.authorization_url(
        state="st", code_challenge=None, redirect_uri=REDIRECT, scopes=ADS_CAPABILITY.scopes
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://www.facebook.com/v27.0/dialog/oauth"
    )
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert query == {
        "client_id": APP_ID,
        "redirect_uri": REDIRECT,
        "state": "st",
        "config_id": CONFIG_ID,
        "response_type": "code",
        "override_default_response_type": "true",
    }
    graph.scopes = ["ads_read", "ads_management"]
    grant = provider.exchange(code=CODE, code_verifier=None, redirect_uri=REDIRECT)
    assert (grant.access_token, grant.refresh_token, grant.access_expires_at) == (TOKEN, None, None)
    assert grant.scopes == ("ads_read", "ads_management")
    exchange, inspected = graph.requests
    assert exchange.path == "oauth/access_token" and exchange.query["redirect_uri"] == REDIRECT
    assert inspected.path == "debug_token" and inspected.query["input_token"] == TOKEN
    with pytest.raises(ProviderError) as raised:
        provider.exchange(code="wrong", code_verifier=None, redirect_uri=REDIRECT)
    assert raised.value.kind is ErrorKind.PERMANENT
    graph.expires_at = 1800000000
    assert provider.exchange(code=CODE, code_verifier=None, redirect_uri=REDIRECT).access_expires_at
    assert provider.revoke(TOKEN, "access_token") == "unsupported"
    with pytest.raises(ProviderError):
        provider.refresh(TOKEN)


def test_delivery_scope_required(graph):
    # T-52: a delivery connection needs ads_read (V-14); neither adapter asks for more.
    assert CAPI_CAPABILITY.scopes == ADS_CAPABILITY.scopes == ("ads_read",)
    assert CAPI_CAPABILITY.require_all_scopes and ADS_CAPABILITY.require_all_scopes
    assert "ads_management" not in CAPI_CAPABILITY.scopes + ADS_CAPABILITY.scopes
    graph.scopes = []
    grant = _capi(graph).exchange(code=CODE, code_verifier=None, redirect_uri=REDIRECT)
    assert not set(CAPI_CAPABILITY.scopes) <= set(grant.scopes)


def test_accounts_objects_and_insights(graph):
    # T-51: account, inventory pages and daily insights with decimal strings and local days.
    provider = _ads(graph)
    snapshot = provider.describe_account(TOKEN, ACCOUNT)
    assert (snapshot.account_id, snapshot.day_zone, snapshot.attributes["currency"]) == (
        ACCOUNT,
        ZONE,
        "USD",
    )
    with pytest.raises(ProviderError) as raised:
        provider.describe_account(TOKEN, "act_999")
    assert raised.value.provider_code == "dataset_unavailable"
    page = provider.fetch_page(TOKEN, stream="account", account=ACCOUNT, day_zone=ZONE)
    assert page.records[0].attributes["timezone_name"] == ZONE and page.account_label
    objects, cursor = [], None
    while True:
        page = provider.fetch_page(TOKEN, stream="ad_objects", cursor=cursor, account=ACCOUNT)
        objects += page.records
        cursor = page.next_cursor
        if cursor is None:
            break
    assert [(item.provider_object_id, item.attributes["level"]) for item in objects] == [
        ("111", "campaign"),
        ("211", "adset"),
        ("311", "ad"),
        ("321", "ad"),
        ("331", "ad"),
    ]
    assert objects[-1].attributes["effective_status"] == "DELETED"
    rows, cursor = [], None
    since = datetime(2026, 11, 1, tzinfo=ZoneInfo(ZONE))
    while True:
        page = provider.fetch_page(
            TOKEN, stream="ad_daily", cursor=cursor, since=since, account=ACCOUNT, day_zone=ZONE
        )
        rows += page.records
        cursor = page.next_cursor
        if cursor is None:
            break
    days = [record.attributes["date"] for record in rows]
    # Every day of the period, each once; Meta answers in its own order.
    assert sorted(days) == [f"2026-11-0{n}" for n in range(1, 10)]
    latest = next(record for record in rows if record.attributes["date"] == "2026-11-09")
    assert latest.attributes["spend"] == "5339.5" and latest.metrics == {
        "impressions": 361324,
        "clicks": 17,
    }
    windows = [
        json.loads(item.query["time_range"])
        for item in graph.requests
        if item.path.endswith("insights")
    ]
    assert {(w["since"], w["until"]) for w in windows} == {
        ("2026-11-01", "2026-11-07"),
        ("2026-11-08", "2026-11-09"),
    }
    assert all(
        item.query["fields"] == meta_ads.INSIGHT_FIELDS
        for item in graph.requests
        if item.path.endswith("insights")
    )
    assert page.complete_through == datetime(2026, 11, 10, 5, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "body", "headers", "kind", "code", "wait"),
    [
        (400, {"error": {"code": 190}}, {}, ErrorKind.UNAUTHORIZED, "invalid_token", None),
        (401, {}, {}, ErrorKind.UNAUTHORIZED, "invalid_token", None),
        (400, {"error": {"code": 80000}}, {}, ErrorKind.RATE_LIMITED, "rate_limited", 900),
        (
            400,
            {"error": {"code": 17, "error_subcode": 2446079}},
            {
                "x-business-use-case-usage": json.dumps(
                    {"1": [{"type": "ads_insights", "estimated_time_to_regain_access": 7}]}
                )
            },
            ErrorKind.RATE_LIMITED,
            "rate_limited",
            420,
        ),
        (429, {}, {}, ErrorKind.RATE_LIMITED, "rate_limited", 900),
        (400, {"error": {"code": 200}}, {}, ErrorKind.FORBIDDEN, "permission", None),
        (403, {}, {}, ErrorKind.FORBIDDEN, "permission", None),
        (500, {}, {}, ErrorKind.RETRYABLE, "unavailable", None),
        (400, {"error": {"code": 2}}, {}, ErrorKind.RETRYABLE, "unavailable", None),
        (
            400,
            {"error": {"code": 100, "error_subcode": 33}},
            {},
            ErrorKind.PERMANENT,
            "dataset_unavailable",
            None,
        ),
        (400, {"error": {"code": 100}}, {}, ErrorKind.PERMANENT, "graph_100", None),
    ],
)
def test_error_classes(graph, status, body, headers, kind, code, wait):
    # T-51: Graph errors map to runtime kinds (V-6, V-13).
    graph.fail_next(status, body, headers)
    with pytest.raises(ProviderError) as raised:
        _ads(graph).fetch_page(TOKEN, stream="account", account=ACCOUNT)
    assert (raised.value.kind, raised.value.provider_code, raised.value.retry_after) == (
        kind,
        code,
        wait,
    )


def test_usage_headers_defer_before_throttling(graph):
    graph.fail_next(
        200,
        {"id": ACCOUNT, **graph.accounts[ACCOUNT]},
        {
            "x-fb-ads-insights-throttle": json.dumps(
                {"app_id_util_pct": 12.0, "acc_id_util_pct": 95.0}
            )
        },
    )
    with pytest.raises(ProviderError) as raised:
        _ads(graph).fetch_page(TOKEN, stream="account", account=ACCOUNT)
    assert (raised.value.kind, raised.value.retry_after) == (ErrorKind.RATE_LIMITED, 900)
    assert regain_seconds({"x-business-use-case-usage": "not json"}) is None


def test_conversions_api_request_building(graph):
    # T-51: one event per request; fbc never hashed; no field outside D8.
    provider = _capi(graph)
    assert provider.describe_account(TOKEN, DATASET).label == "Synthetic dataset"
    fbc = "fb.1.1795163415123.IwAR0AbC_dEf-9"
    event = {
        "event_name": "Purchase",
        "event_time": 1795160000,
        "event_id": "e" * 64,
        "action_source": "system_generated",
        "event_source_url": "https://shop.example.test/thanks",
        "user_data": {"fbc": fbc, "em": "x" * 64, "client_ip_address": "192.0.2.1"},
        "custom_data": {"value": 69.5, "currency": "USD", "order_id": "o-1"},
        "opt_out": False,
    }
    answer = provider.send_event(TOKEN, dataset=DATASET, event=event, test_event_code="TEST1")
    assert (answer.events_received, answer.trace_id) == (1, "AsyntheticTrace1")
    request = graph.requests[-1]
    assert (request.method, request.path) == ("POST", f"{DATASET}/events")
    assert request.form["test_event_code"] == "TEST1"
    (sent,) = json.loads(request.form["data"])
    assert sent == {
        "event_name": "Purchase",
        "event_time": 1795160000,
        "event_id": "e" * 64,
        "action_source": "system_generated",
        "user_data": {"fbc": fbc},
        "custom_data": {"value": 69.5, "currency": "USD"},
    }
    website = provider.request_event({**event, "action_source": "website"})
    assert website["event_source_url"] == "https://shop.example.test/thanks"
    provider.send_event(TOKEN, dataset=DATASET, event=event, test_event_code=None)
    assert "test_event_code" not in graph.requests[-1].form
    with pytest.raises(ProviderError) as raised:
        provider.send_event(TOKEN, dataset="7770009", event=event, test_event_code=None)
    assert raised.value.provider_code == "dataset_unavailable"
    graph.fail_next(400, {"error": {"code": 100, "message": "Invalid parameter"}})
    with pytest.raises(ProviderError) as raised:
        provider.send_event(TOKEN, dataset=DATASET, event=event, test_event_code=None)
    assert (raised.value.kind, raised.value.provider_code) == (ErrorKind.PERMANENT, "graph_100")
    assert "Invalid parameter" not in repr(raised.value)


def test_capabilities_follow_the_verified_sources():
    assert (ADS_CAPABILITY.revocation_scope, CAPI_CAPABILITY.revocation_scope) == (
        "unsupported",
        "unsupported",
    )
    assert not ADS_CAPABILITY.signed_requests and not CAPI_CAPABILITY.signed_requests
    assert ADS_CAPABILITY.named_account == "ad_account" and ADS_CAPABILITY.connection_day_zone
    assert CAPI_CAPABILITY.delivery and CAPI_CAPABILITY.stream_specs() == ()
    assert meta_ads.GRAPH_VERSION == "v27.0"
    assert ADS_CAPABILITY.stream_spec("ad_daily").overlap_days == 28


def test_suite_makes_no_network_call(graph):
    # T-53: the default transport is the only network path, and it is unreachable here.
    provider = MetaAdsProvider(APP_ID, APP_SECRET, CONFIG_ID)
    with pytest.raises(AssertionError, match="must not open a network connection"):
        provider.fetch_page(TOKEN, stream="account", account=ACCOUNT)
    assert runtime.MetaAdsProvider is MetaAdsProvider


def test_marketing_api_rule_uses_a_registered_data_class():
    from app.data_policy import CLASSES

    rule = providers.rule("meta.marketing_api")
    assert rule.data_class in CLASSES and rule.review_due_at == date(2027, 11, 20)
    assert providers.rule("meta.conversions_api").status is providers.RuleStatus.CURRENT
