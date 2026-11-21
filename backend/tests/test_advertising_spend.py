"""Pure parts of 014-A spend ingestion (specification 014-A, D-064 decision D4).

Exact spend parsing per currency exponent (T-04), the allow-listed currency table, the
Meta-shaped synthetic provider's local-day windows across daylight-saving changes (T-03), its
cursor, Login for Business request and capability, and the provisional marking. No database
and no network.
"""

from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from app.advertising.currencies import EXPONENTS, decimal_text, parse_spend
from app.advertising.spend import fact_values, provisional_until
from app.connectors.contracts import ErrorKind, ProviderError
from app.connectors.synthetic_meta_ads import (
    CAPABILITY,
    CLOCK,
    SyntheticMetaAdsProvider,
    day_cursor,
    parse_day_cursor,
)

REDIRECT = "http://127.0.0.1:8000/connectors/oauth/callback"


@pytest.mark.parametrize(
    ("value", "code", "minor"),
    [
        ("1234", "JPY", 1234),
        ("0", "KRW", 0),
        ("10.50", "USD", 1050),
        ("5339.5", "USD", 533950),
        ("10", "EUR", 1000),
        ("1.234", "BHD", 1234),
        ("1.2", "JOD", 1200),
        ("1234.56", "HUF", 123456),
    ],
)
def test_exponents_parse_exactly(value, code, minor):
    amount = parse_spend(value, code)
    assert amount.minor == minor and amount.currency.code == code


@pytest.mark.parametrize(
    ("value", "code", "reason"),
    [
        ("1234.5", "JPY", "unparseable_amount"),
        ("10.505", "USD", "unparseable_amount"),
        ("1.2345", "BHD", "unparseable_amount"),
        ("-1.00", "USD", "unparseable_amount"),
        ("1e3", "USD", "unparseable_amount"),
        ("01.00", "USD", "unparseable_amount"),
        (" 1.00", "USD", "unparseable_amount"),
        (12.5, "USD", "unparseable_amount"),
        ("1.00", "XTS", "unsupported_currency"),
        ("1.00", "FBZ", "unsupported_currency"),
        ("1.00", "HRK", "unsupported_currency"),
        ("1.00", "usd", "unsupported_currency"),
        ("1.00", None, "unsupported_currency"),
    ],
)
def test_exponents_and_refusals(value, code, reason):
    # T-04: extra decimal places and unlisted currencies are refused, never rounded.
    assert parse_spend(value, code) == reason


def test_currency_table_follows_meta_and_iso():
    assert {code for code, exponent in EXPONENTS.items() if exponent == 0} == {
        "CLP",
        "ISK",
        "JPY",
        "KRW",
        "PYG",
        "VND",
    }
    assert {code for code, exponent in EXPONENTS.items() if exponent == 3} == {"BHD", "JOD"}
    assert len(EXPONENTS) == 60
    assert not {"FBZ", "HRK", "LTL", "LVL", "SKK", "VEF"} & set(EXPONENTS)
    assert decimal_text(1230, 2) == "12.30" and decimal_text(7, 0) == "7"
    assert decimal_text(1234, 3) == "1.234"


def test_fact_values_store_amount_or_refusal():
    assert fact_values({"spend": "1.50", "currency": "USD"}, {"impressions": 3, "clicks": 1}) == {
        "currency": "USD",
        "spend_minor": 150,
        "refusal": None,
        "impressions": 3,
        "clicks": 1,
    }
    refused = fact_values({"spend": "1.505", "currency": "USD"}, {"impressions": -1})
    assert (refused["spend_minor"], refused["refusal"], refused["impressions"]) == (
        None,
        "unparseable_amount",
        0,
    )
    unknown = fact_values({"spend": "1", "currency": "X1"}, {})
    assert (unknown["currency"], unknown["refusal"]) == (None, "unsupported_currency")


def test_provisional_until_counts_local_days():
    zone = "America/New_York"
    day = date(2026, 10, 31)
    assert provisional_until(day, zone) == datetime(2026, 11, 29, tzinfo=ZoneInfo(zone))
    assert provisional_until(day, zone).astimezone(UTC).hour == 5


def test_capability_declares_named_accounts_and_advertising_streams():
    assert CAPABILITY.named_account == "ad_account" and CAPABILITY.connection_day_zone
    assert CAPABILITY.scopes == ("ads_read",) and CAPABILITY.require_all_scopes
    assert CAPABILITY.pkce is None and CAPABILITY.revocation_scope == "unsupported"
    assert [spec.name for spec in CAPABILITY.stream_specs()] == [
        "account",
        "ad_objects",
        "ad_daily",
    ]
    assert {spec.storage for spec in CAPABILITY.stream_specs()} == {"advertising"}
    daily = CAPABILITY.stream_spec("ad_daily")
    assert (daily.history_days, daily.overlap_days) == (730, 28)


def test_day_cursor_round_trip_and_refusals():
    first, window = date(2026, 10, 1), date(2026, 10, 8)
    assert parse_day_cursor(day_cursor(first, window, 3)) == (first, window, 3)
    for bad in (
        "2026-10-01:2026-10-08",
        "2026-10-08:2026-10-01:0",
        "x:y:0",
        "2026-10-1:2026-10-08:0",
    ):
        with pytest.raises(ProviderError) as raised:
            parse_day_cursor(bad)
        assert raised.value.provider_code == "invalid_cursor"


def _provider(tmp_path, zone):
    provider = SyntheticMetaAdsProvider(tmp_path / "meta-ads.sqlite3")
    provider.define_account("act_1001", zone=zone)
    provider.define_object("act_1001", "111", "campaign")
    provider.define_object("act_1001", "211", "adset", campaign="111")
    provider.define_object(
        "act_1001", "311", "ad", campaign="111", adset="211", first=date(2026, 9, 1)
    )
    url = provider.authorization_url(
        state="s", code_challenge=None, redirect_uri=REDIRECT, scopes=()
    )
    code = provider.approve(url, ("act_1001",))
    grant = provider.exchange(code=code, code_verifier=None, redirect_uri=REDIRECT)
    return provider, grant.access_token


def _days(provider, token, zone, since, until=None):
    days, cursor = [], None
    while True:
        page = provider.fetch_page(
            token,
            stream="ad_daily",
            cursor=cursor,
            since=since,
            until=until,
            account="act_1001",
            day_zone=zone,
        )
        days.extend(date.fromisoformat(record.attributes["date"]) for record in page.records)
        if page.next_cursor is None:
            return days, page
        cursor = page.next_cursor


@pytest.mark.parametrize(
    ("zone", "change", "hours"),
    [("America/New_York", date(2026, 11, 1), 25), ("Australia/Sydney", date(2026, 10, 4), 23)],
)
def test_local_day_windows(tmp_path, zone, change, hours):
    # T-03: windows start at local midnights on both sides of a 25-hour and a 23-hour day.
    provider, token = _provider(tmp_path, zone)
    local = ZoneInfo(zone)
    since = datetime.combine(change - timedelta(days=3), datetime.min.time(), local)
    days, page = _days(provider, token, zone, since)
    today = CLOCK.astimezone(local).date()
    assert days == [change - timedelta(days=3) + timedelta(days=n) for n in range(len(days))]
    assert days[-1] == today - timedelta(days=1)
    assert page.covered_from == since
    assert page.complete_through == datetime.combine(today, datetime.min.time(), local)
    start = datetime.combine(change, datetime.min.time(), local).astimezone(UTC)
    end = datetime.combine(change + timedelta(days=1), datetime.min.time(), local).astimezone(UTC)
    assert end - start == timedelta(hours=hours)
    # An until bound at a local midnight ends the read before that day.
    bounded, _ = _days(
        provider,
        token,
        zone,
        since,
        datetime.combine(change + timedelta(days=1), datetime.min.time(), local),
    )
    assert bounded[-1] == change


def test_reads_split_into_seven_day_windows_and_keep_the_first_day(tmp_path):
    provider, token = _provider(tmp_path, "America/New_York")
    provider.set_behavior("page_rows", "3")
    days, _ = _days(provider, token, "America/New_York", None)
    # The ad runs from 2026-09-01; the read covers 90 days, of which 70 have rows.
    assert len(days) == 70 and len(set(days)) == 70
    reads = [detail for detail, _ in provider.stream_reads()]
    assert reads[0] == "ad_daily:0"
    windows = {detail.split(":")[2] for detail in reads[1:]}
    assert all(
        (date.fromisoformat(b) - date.fromisoformat(a)).days == 7
        for a, b in zip(sorted(windows), sorted(windows)[1:], strict=False)
    )


def test_login_for_business_request_and_account_checks(tmp_path):
    provider, token = _provider(tmp_path, "America/New_York")
    url = provider.authorization_url(
        state="st", code_challenge=None, redirect_uri=REDIRECT, scopes=()
    )
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    assert query["response_type"] == "code" and query["override_default_response_type"] == "true"
    assert "scope" not in query and "code_challenge" not in query and query["config_id"]
    snapshot = provider.describe_account(token, "act_1001")
    assert (snapshot.account_id, snapshot.day_zone, snapshot.attributes["currency"]) == (
        "act_1001",
        "America/New_York",
        "USD",
    )
    provider.define_account("act_2002")
    with pytest.raises(ProviderError) as raised:
        provider.describe_account(token, "act_2002")
    assert raised.value.kind is ErrorKind.FORBIDDEN
    with pytest.raises(ProviderError) as raised:
        provider.fetch_page(token, stream="ad_daily", account="act_2002", day_zone="UTC")
    assert raised.value.kind is ErrorKind.FORBIDDEN
    provider.remove_integration(token)
    with pytest.raises(ProviderError) as raised:
        provider.fetch_page(token, stream="account", account="act_1001")
    assert raised.value.kind is ErrorKind.UNAUTHORIZED
    assert provider.revoke(token, "access_token") == "unsupported"
