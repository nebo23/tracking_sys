"""Advertising spend ingestion on disposable PostgreSQL (specification 014-A, D-064).

Uses the synthetic lab of connector_support with the Meta-shaped synthetic spend provider that
the API builds next to the other synthetic providers. No case contacts Meta: the provider
reproduces the documented shapes of entry review section 2.4 only. The worker's clock and the
provider's data clock are set together. Cases T-01 to T-10 of the entry review section 7.1.
"""

from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from connector_support import make_lab
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.synthetic_meta_ads import CLOCK, SyntheticMetaAdsProvider
from app.models import (
    AdAccount,
    AdObject,
    AdSpendFact,
    ConnectorCheckpoint,
    ConnectorConnection,
    ConnectorRecord,
    ConnectorSyncRun,
)
from app.services.access import AccessService, ClientPermission

pytestmark = pytest.mark.integration
PROVIDER = "synthetic_meta_ads"
ACCOUNT, OTHER, SOUTH = "act_1001", "act_1002", "act_1003"
NEW_YORK, SYDNEY = "America/New_York", "Australia/Sydney"
START = date(2026, 10, 1)
TODAY = CLOCK.astimezone(ZoneInfo(NEW_YORK)).date()


# The spend route reads the provisional marking at the synthetic data clock.
@pytest.fixture(autouse=True)
def route_clock(monkeypatch):
    monkeypatch.setattr("app.api.advertising.now_utc", lambda: CLOCK)


# The connector lab with the Meta-shaped spend provider and two defined ad accounts; shared with
# the ROAS tests (014-C).
def make_ads_lab(authenticated_world, api, tmp_path):
    lab = make_lab(authenticated_world, api, tmp_path)
    state = lab.state.with_name(lab.state.stem + "-meta-ads" + lab.state.suffix)
    lab.meta = SyntheticMetaAdsProvider(state)
    lab.registry = {PROVIDER: lab.meta}
    for account, zone, currency in ((ACCOUNT, NEW_YORK, "USD"), (OTHER, "Europe/Berlin", "EUR")):
        lab.meta.define_account(account, currency=currency, zone=zone, name=f"Ads {account}")
        _inventory(lab, account)
    return lab


@pytest.fixture
def ads(authenticated_world, api, tmp_path):
    return make_ads_lab(authenticated_world, api, tmp_path)


def _inventory(lab, account, first=START, spend="10.00"):
    suffix = account.removeprefix("act_")
    campaign, adset = f"11{suffix}", f"21{suffix}"
    lab.meta.define_object(account, campaign, "campaign", name="Synthetic campaign")
    lab.meta.define_object(account, adset, "adset", campaign=campaign, name="Synthetic ad set")
    for ad in (f"31{suffix}", f"32{suffix}"):
        lab.meta.define_object(
            account,
            ad,
            "ad",
            campaign=campaign,
            adset=adset,
            name=f"Synthetic ad {ad}",
            first=first,
            spend=spend,
        )
    return campaign, adset, (f"31{suffix}", f"32{suffix}")


def _begin(lab, name, agency, client_id, account=ACCOUNT, provider=PROVIDER):
    body = {"provider": provider}
    if account is not None:
        body["account"] = account
    return lab.browser(name).post(f"/agencies/{agency}/clients/{client_id}/connections", json=body)


def _callback(lab, name, url, accounts, scopes=("ads_read",)):
    code = lab.meta.approve(url, accounts, scopes=scopes)
    state = parse_qs(urlsplit(url).query)["state"][0]
    response = lab.browser(name).get(
        "/connectors/oauth/callback", params={"code": code, "state": state}, follow_redirects=False
    )
    assert response.status_code == 303
    return {
        key: values[0]
        for key, values in parse_qs(urlsplit(response.headers["location"]).query).items()
    }


def _connect(lab, name, agency, client_id, account=ACCOUNT, accounts=None):
    response = _begin(lab, name, agency, client_id, account)
    assert response.status_code == 200, response.text
    result = _callback(lab, name, response.json()["authorization_url"], accounts or (account,))
    assert result["result"] == "connected", result
    return UUID(result["connection_id"])


def _work(lab, now=CLOCK, limit=20):
    return lab.worker(now=now, registry=lab.registry, limit=limit)


def _sync(lab, name, agency, client_id, connection_id, stream, **extra):
    response = lab.sync(name, agency, client_id, connection_id, {"stream": stream, **extra})
    assert response.status_code == 202, response.text


def _spend(lab, name, agency, client_id, connection_id, since, until, level="ad", client=None):
    query = urlencode(
        {
            "connection_id": str(connection_id),
            "since": since.isoformat(),
            "until": until.isoformat(),
            "level": level,
        }
    )
    return (client or lab.browser(name)).get(
        f"/agencies/{agency}/clients/{client_id}/ad-spend?{query}"
    )


def _facts(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        return {
            (row.ad_id, row.spend_date): row
            for row in session.scalars(
                select(AdSpendFact).where(AdSpendFact.connection_id == connection_id)
            )
        }


def _account(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        return session.scalar(select(AdAccount).where(AdAccount.connection_id == connection_id))


def _connected(lab, name="owner_a", agency=None, client_id=None, account=ACCOUNT):
    w = lab.w
    connection = _connect(lab, name, agency or w.a, client_id or w.a1, account)
    assert _work(lab)["sync"] == {"succeeded": 3}
    return connection


def _usd_total(body):
    return {item["currency"]: item["spend_minor"] for item in body["totals"]}


def test_connect_names_the_account_and_keeps_its_zone(ads):
    w = ads.w
    k = _connected(ads)
    row = ads.row(k)
    assert (row.provider, row.external_account_id, row.day_zone) == (PROVIDER, ACCOUNT, NEW_YORK)
    assert row.granted_scopes == ["ads_read"]
    account = _account(ads, k)
    assert (account.account_id, account.currency, account.time_zone) == (ACCOUNT, "USD", NEW_YORK)
    # Ninety account-local days at connect, ending before today; two ads from October 1.
    days = (TODAY - START).days
    assert len(_facts(ads, k)) == 2 * days
    with Session(ads.w.db.migration) as session:
        checkpoint = session.scalar(
            select(ConnectorCheckpoint).where(
                ConnectorCheckpoint.connection_id == k, ConnectorCheckpoint.stream == "ad_daily"
            )
        )
        objects = session.scalar(
            select(func.count()).select_from(AdObject).where(AdObject.connection_id == k)
        )
    zone = ZoneInfo(NEW_YORK)
    assert checkpoint.complete_through == datetime.combine(TODAY, datetime.min.time(), zone)
    assert checkpoint.covered_from == datetime.combine(
        TODAY - timedelta(days=90), datetime.min.time(), zone
    )
    assert objects == 4
    # Every daily window covers at most 7 days.
    windows = [d for d, outcome in ads.meta.stream_reads() if d.startswith("ad_daily")]
    assert len(windows) == 13
    body = _spend(ads, "owner_a", w.a, w.a1, k, START, TODAY - timedelta(days=1)).json()
    assert body["totals"] == [
        {
            "currency": "USD",
            "spend": f"{20 * days}.00",
            "spend_minor": 2000 * days,
            "impressions": 200 * days,
            "clicks": 10 * days,
            "days": days,
        }
    ]
    assert body["coverage"]["state"] == "complete"


def test_rereading_a_window_keeps_facts_and_totals(ads):
    # T-01: reading the same window twice gives the same facts and totals.
    w = ads.w
    k = _connected(ads)
    before = {key: (row.spend_minor, row.revisions) for key, row in _facts(ads, k).items()}
    period = (START, TODAY - timedelta(days=1))
    first = _spend(ads, "owner_a", w.a, w.a1, k, *period).json()
    for _ in range(2):
        _sync(ads, "owner_a", w.a, w.a1, k, "ad_daily")
        assert _work(ads)["sync"] == {"succeeded": 1}
    after = {key: (row.spend_minor, row.revisions) for key, row in _facts(ads, k).items()}
    assert after == before
    assert _spend(ads, "owner_a", w.a, w.a1, k, *period).json()["totals"] == first["totals"]
    # The incremental re-read starts 28 account-local days before the last complete day.
    with Session(ads.w.db.migration) as session:
        run = session.scalars(
            select(ConnectorSyncRun)
            .where(ConnectorSyncRun.connection_id == k, ConnectorSyncRun.stream == "ad_daily")
            .order_by(ConnectorSyncRun.created_at.desc())
        ).first()
    assert run.window_since == datetime.combine(
        TODAY - timedelta(days=28), datetime.min.time(), ZoneInfo(NEW_YORK)
    )


def test_restated_value_replaces_the_old_one(ads):
    # T-02: a changed value inside the re-read window replaces the old one.
    w = ads.w
    k = _connected(ads)
    ad, day = "311001", TODAY - timedelta(days=5)
    ads.meta.override(ACCOUNT, ad, day, spend="12.50", clicks=7)
    _sync(ads, "owner_a", w.a, w.a1, k, "ad_daily")
    assert _work(ads)["sync"] == {"succeeded": 1}
    fact = _facts(ads, k)[ad, day]
    assert (fact.spend_minor, fact.clicks, fact.revisions) == (1250, 7, 1)
    days = (TODAY - START).days
    body = _spend(ads, "owner_a", w.a, w.a1, k, START, TODAY - timedelta(days=1)).json()
    assert _usd_total(body) == {"USD": 2000 * days + 250}
    # Reading the same value again does not count a further revision.
    _sync(ads, "owner_a", w.a, w.a1, k, "ad_daily")
    _work(ads)
    assert _facts(ads, k)[ad, day].revisions == 1
    # Days inside the 28-day window are provisional; older days are not.
    assert day in {date.fromisoformat(item) for item in body["provisional_dates"]}
    assert START not in {date.fromisoformat(item) for item in body["provisional_dates"]}


def test_daylight_saving_days(ads):
    # T-03: account-local days across a 25-hour day (New York, 2026-11-01) and a 23-hour day
    # (Sydney, 2026-10-04).
    w = ads.w
    ads.meta.define_account(SOUTH, currency="AUD", zone=SYDNEY, name="Southern ads")
    _inventory(ads, SOUTH)
    north = _connected(ads)
    south = _connected(ads, client_id=w.a2, account=SOUTH)
    for connection, zone, day in (
        (north, NEW_YORK, date(2026, 11, 1)),
        (south, SYDNEY, date(2026, 10, 4)),
    ):
        facts = _facts(ads, connection)
        days = sorted({spend_date for _, spend_date in facts})
        assert days == [START + timedelta(days=n) for n in range(len(days))]
        assert all(len([key for key in facts if key[1] == d]) == 2 for d in days)
        fact = next(row for key, row in facts.items() if key[1] == day)
        local = ZoneInfo(zone)
        assert fact.time_zone == zone
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), local)
        start = datetime.combine(day, datetime.min.time(), local)
        length = end.astimezone(UTC) - start.astimezone(UTC)
        assert length == timedelta(hours=25 if zone == NEW_YORK else 23)
        assert fact.provisional_until == datetime.combine(
            day + timedelta(days=29), datetime.min.time(), local
        )
    # The incremental window starts at a local midnight on the far side of the change.
    _sync(ads, "owner_a", w.a, w.a1, north, "ad_daily")
    _work(ads)
    with Session(ads.w.db.migration) as session:
        run = session.scalars(
            select(ConnectorSyncRun)
            .where(ConnectorSyncRun.connection_id == north, ConnectorSyncRun.stream == "ad_daily")
            .order_by(ConnectorSyncRun.created_at.desc())
        ).first()
    assert run.window_since == datetime.combine(
        TODAY - timedelta(days=28), datetime.min.time(), ZoneInfo(NEW_YORK)
    )
    assert run.window_since.astimezone(UTC).hour == 4  # EDT, before the 2026-11-01 change


def test_refused_amounts_are_not_stored(ads):
    # T-04: extra decimal places and an unlisted currency are refused, not rounded or stored.
    w = ads.w
    k = _connected(ads)
    first, second = TODAY - timedelta(days=3), TODAY - timedelta(days=2)
    ads.meta.override(ACCOUNT, "311001", first, spend="10.005")
    ads.meta.override(ACCOUNT, "321001", second, spend="9.00", currency="XTS")
    _sync(ads, "owner_a", w.a, w.a1, k, "ad_daily")
    assert _work(ads)["sync"] == {"succeeded": 1}
    facts = _facts(ads, k)
    assert (facts["311001", first].spend_minor, facts["311001", first].refusal) == (
        None,
        "unparseable_amount",
    )
    assert (facts["321001", second].spend_minor, facts["321001", second].refusal) == (
        None,
        "unsupported_currency",
    )
    days = (TODAY - START).days
    body = _spend(ads, "owner_a", w.a, w.a1, k, START, TODAY - timedelta(days=1)).json()
    assert body["refused"] == {"unparseable_amount": 1, "unsupported_currency": 1}
    assert _usd_total(body) == {"USD": 2000 * days - 2000}
    # A later exact value replaces the refusal.
    ads.meta.override(ACCOUNT, "311001", first, spend="10.25")
    _sync(ads, "owner_a", w.a, w.a1, k, "ad_daily")
    _work(ads)
    fixed = _facts(ads, k)["311001", first]
    assert (fixed.spend_minor, fixed.refusal, fixed.revisions) == (1025, None, 2)


def test_currency_change_keeps_earlier_facts(ads):
    # T-05: after a change of account currency, earlier facts keep their currency and no read
    # sums the two.
    w = ads.w
    k = _connected(ads)
    ads.meta.define_account(ACCOUNT, currency="EUR", zone=NEW_YORK, name="Ads act_1001")
    _sync(ads, "owner_a", w.a, w.a1, k, "account")
    _sync(ads, "owner_a", w.a, w.a1, k, "ad_daily")
    assert _work(ads)["sync"] == {"succeeded": 2}
    account = _account(ads, k)
    assert (account.currency, account.previous_currency) == ("EUR", "USD")
    assert account.currency_changed_at is not None
    facts = _facts(ads, k)
    reread = TODAY - timedelta(days=28)
    assert {row.currency for key, row in facts.items() if key[1] < reread} == {"USD"}
    assert {row.currency for key, row in facts.items() if key[1] >= reread} == {"EUR"}
    days = (TODAY - START).days
    body = _spend(ads, "owner_a", w.a, w.a1, k, START, TODAY - timedelta(days=1)).json()
    assert _usd_total(body) == {"USD": 2000 * (days - 28), "EUR": 2000 * 28}
    for level in ("ad", "adset", "campaign"):
        rows = _spend(ads, "owner_a", w.a, w.a1, k, START, TODAY, level).json()["rows"]
        assert sorted(row["currency"] for row in rows) == (
            ["EUR", "EUR", "USD", "USD"] if level == "ad" else ["EUR", "USD"]
        )


def test_deleted_and_archived_ads_keep_facts(ads):
    # T-06: deleted and archived ads keep their facts; the inventory refreshes names and
    # statuses.
    w = ads.w
    k = _connected(ads)
    before = len(_facts(ads, k))
    ads.meta.define_object(
        ACCOUNT, "311001", "ad", campaign="111001", adset="211001", name="Renamed", status="DELETED"
    )
    ads.meta.define_object(
        ACCOUNT,
        "321001",
        "ad",
        campaign="111001",
        adset="211001",
        name="Archived ad",
        status="ARCHIVED",
    )
    for offset in range(1, 29):
        ads.meta.override(ACCOUNT, "311001", TODAY - timedelta(days=offset), omit=True)
    _sync(ads, "owner_a", w.a, w.a1, k, "ad_objects")
    _sync(ads, "owner_a", w.a, w.a1, k, "ad_daily")
    assert _work(ads)["sync"] == {"succeeded": 2}
    assert len(_facts(ads, k)) == before
    with Session(ads.w.db.migration) as session:
        objects = {
            row.object_id: (row.name, row.effective_status)
            for row in session.scalars(select(AdObject).where(AdObject.connection_id == k))
        }
    assert objects["311001"] == ("Renamed", "DELETED")
    assert objects["321001"] == ("Archived ad", "ARCHIVED")
    rows = _spend(ads, "owner_a", w.a, w.a1, k, START, TODAY).json()["rows"]
    assert {row["object_id"]: row["name"] for row in rows} == {
        "311001": "Renamed",
        "321001": "Archived ad",
    }


def test_throttling_permission_and_token_errors(ads):
    # T-07: throttling defers the run by the provider's wait; a permission error is forbidden;
    # an invalid token makes the connection reconnect_required (no refresh exists, V-7).
    w = ads.w
    k = _connected(ads)
    ads.meta.set_behavior("fetch_script", "rate_limited:600")
    _sync(ads, "owner_a", w.a, w.a1, k, "ad_daily")
    assert _work(ads)["sync"] == {"deferred": 1}
    with Session(ads.w.db.migration) as session:
        run = session.scalars(
            select(ConnectorSyncRun)
            .where(ConnectorSyncRun.connection_id == k, ConnectorSyncRun.stream == "ad_daily")
            .order_by(ConnectorSyncRun.created_at.desc())
        ).first()
    assert (run.status, run.error_kind, run.not_before) == (
        "queued",
        "rate_limited",
        CLOCK + timedelta(seconds=600),
    )
    assert _work(ads, now=CLOCK + timedelta(seconds=601))["sync"] == {"succeeded": 1}
    ads.meta.set_behavior("fetch_script", "forbidden")
    _sync(ads, "owner_a", w.a, w.a1, k, "account")
    assert _work(ads)["sync"] == {"failed": 1}
    assert ads.row(k).status == "active"
    ads.meta.set_behavior("fetch_script", "unauthorized")
    _sync(ads, "owner_a", w.a, w.a1, k, "account")
    assert _work(ads)["sync"] == {"stopped": 1}
    row = ads.row(k)
    assert (row.status, row.status_reason) == ("reconnect_required", "provider_revoked")
    assert "refresh" not in {operation for operation, _ in ads.meta.calls()}


def test_unavailable_account_and_reconnect(ads):
    # T-08: a connect naming an account the grant cannot read ends with account_unavailable; a
    # reconnect keeps the connection's own account and cannot move to another one.
    w = ads.w
    missing = _begin(ads, "owner_a", w.a, w.a1, account=None)
    assert (missing.status_code, missing.json()) == (422, {"error": "invalid_account"})
    malformed = _begin(ads, "owner_a", w.a, w.a1, account="1001")
    assert (malformed.status_code, malformed.json()) == (422, {"error": "invalid_account"})
    response = _begin(ads, "owner_a", w.a, w.a1, OTHER)
    result = _callback(ads, "owner_a", response.json()["authorization_url"], (ACCOUNT,))
    assert result == {"error": "account_unavailable"}
    with Session(ads.w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(ConnectorConnection)) == 0
    k = _connected(ads)
    ads.meta.set_behavior("fetch_script", "unauthorized")
    _sync(ads, "owner_a", w.a, w.a1, k, "account")
    _work(ads)
    assert ads.row(k).status == "reconnect_required"
    base = f"/agencies/{w.a}/clients/{w.a1}/connections/{k}/reconnect"
    moved = ads.browser("owner_a").post(base, json={"account": OTHER})
    assert moved.status_code == 422
    url = ads.browser("owner_a").post(base).json()["authorization_url"]
    assert _callback(ads, "owner_a", url, (OTHER,)) == {"error": "account_unavailable"}
    assert ads.row(k).status == "reconnect_required"
    url = ads.browser("owner_a").post(base).json()["authorization_url"]
    assert _callback(ads, "owner_a", url, (ACCOUNT, OTHER))["result"] == "reconnected"
    row = ads.row(k)
    assert (row.status, row.external_account_id) == ("active", ACCOUNT)


def test_spend_reads_need_finance_access(ads, api):
    # T-09: two agencies with two clients each; spend reads need finance:read, client:read sees
    # no amounts, and service keys follow their grants.
    w = ads.w
    a1 = _connected(ads)
    a2 = _connect(ads, "owner_a", w.a, w.a2, OTHER)
    b1 = _connect(ads, "owner_b", w.b, w.b1)
    assert _work(ads)["sync"] == {"succeeded": 6}
    period = (START, TODAY - timedelta(days=1))
    owner = _spend(ads, "owner_a", w.a, w.a1, a1, *period)
    assert owner.status_code == 200 and _usd_total(owner.json())
    for name in ("analyst", "viewer", "owner_b"):
        assert _spend(ads, name, w.a, w.a1, a1, *period).status_code == 403, name
    # A connection of another client is not readable through this client.
    assert _spend(ads, "owner_a", w.a, w.a1, a2, *period).status_code == 403
    assert _spend(ads, "owner_b", w.b, w.b1, a1, *period).status_code == 403
    # Each client sees its own facts only; agency B's copy of the account is separate.
    assert _usd_total(_spend(ads, "owner_b", w.b, w.b1, b1, *period).json()) == _usd_total(
        owner.json()
    )
    with Session(w.db.migration) as session:
        assert {row.client_id for row in session.scalars(select(AdSpendFact))} == {
            w.a1,
            w.a2,
            w.b1,
        }
    # client:read readers see the connection but no amounts: spend never enters records.
    records = ads.browser("analyst").get(
        f"/agencies/{w.a}/clients/{w.a1}/connections/{a1}/records?stream=ad_daily"
    )
    assert records.status_code == 200 and records.json()["records"] == []
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(ConnectorRecord)) == 0
    keys = {}
    for kind, financial in (("read", True), ("read", False), ("ingest", False)):
        with Session(w.db.runtime, expire_on_commit=False) as session, session.begin():
            _, raw = AccessService(session, w.users.owner_a, ads.config).issue_service_key(
                w.a, f"Synthetic {kind}", [ClientPermission(w.a1, financial)], kind=kind
            )
        client = api.new_client(ads.config)
        client.headers["Authorization"] = f"Bearer {raw}"
        keys[kind, financial] = client
    assert _spend(ads, "", w.a, w.a1, a1, *period, client=keys["read", True]).status_code == 200
    assert _spend(ads, "", w.a, w.a1, a1, *period, client=keys["read", False]).status_code == 403
    assert _spend(ads, "", w.a, w.a1, a1, *period, client=keys["ingest", False]).status_code == 401


def test_disconnect_purges_spend(ads):
    # T-10: a disconnect purges accounts, objects and facts.
    w = ads.w
    k = _connected(ads)
    other = _connect(ads, "owner_a", w.a, w.a2)
    _work(ads)
    assert ads.disconnect("owner_a", w.a, w.a1, k).status_code == 202
    assert _work(ads)["teardown"] == {"disconnected": 1}
    with Session(w.db.migration) as session:
        for model in (AdAccount, AdObject, AdSpendFact):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.connection_id == k)
                )
                == 0
            )
            assert session.scalar(
                select(func.count()).select_from(model).where(model.connection_id == other)
            )
    row = ads.row(k)
    assert (row.status, row.external_account_id, row.day_zone) == ("disconnected", None, None)
    assert row.revocation_status == "unsupported"


def test_spend_pages_follow_object_and_currency(ads):
    # R010: facts keep their reported currency (D-064 D4), so one object can have rows in two
    # currencies, and an ad set or campaign ID can be missing. At every level, limit-1 pages
    # reach each (object, currency) group exactly once in order; the totals stay the same on
    # every page; the last page has no cursor and a page after it is empty.
    w = ads.w
    connection = _connect(ads, "owner_a", w.a, w.a1)
    now = datetime(2026, 11, 22, tzinfo=UTC)
    facts = [
        ("111", "222", "333", 1, "EGP", 100),
        ("111", "222", "333", 2, "USD", 200),
        ("112", "222", "333", 1, "USD", 300),
        ("113", None, None, 1, "EGP", 50),
        ("113", None, None, 2, "USD", 70),
        ("114", "223", None, 1, "EGP", 10),
    ]
    with Session(w.db.migration) as session, session.begin():
        for ad, adset, campaign, day, currency, minor in facts:
            session.add(
                AdSpendFact(
                    agency_id=w.a,
                    client_id=w.a1,
                    connection_id=connection,
                    ad_id=ad,
                    adset_id=adset,
                    campaign_id=campaign,
                    spend_date=date(2026, 11, day),
                    time_zone="UTC",
                    currency=currency,
                    spend_minor=minor,
                    provisional_until=now,
                )
            )
    expected = {
        "ad": [
            ("111", "EGP", 100),
            ("111", "USD", 200),
            ("112", "USD", 300),
            ("113", "EGP", 50),
            ("113", "USD", 70),
            ("114", "EGP", 10),
        ],
        "adset": [
            (None, "EGP", 50),
            (None, "USD", 70),
            ("222", "EGP", 100),
            ("222", "USD", 500),
            ("223", "EGP", 10),
        ],
        "campaign": [
            (None, "EGP", 60),
            (None, "USD", 70),
            ("333", "EGP", 100),
            ("333", "USD", 500),
        ],
    }
    totals = [("EGP", 160), ("USD", 570)]
    path = f"/agencies/{w.a}/clients/{w.a1}/ad-spend"
    client = ads.browser("owner_a")
    base = {"connection_id": str(connection), "since": "2026-11-01", "until": "2026-11-02"}
    for level, groups in expected.items():
        seen, after = [], None
        while True:
            params = {**base, "level": level, "limit": 1} | ({"after": after} if after else {})
            page = client.get(path, params=params).json()
            assert [(t["currency"], t["spend_minor"]) for t in page["totals"]] == totals
            seen.extend((r["object_id"], r["currency"], r["spend_minor"]) for r in page["rows"])
            after = page["next_after"]
            if after is None:
                break
        assert seen == groups, level
        last = groups[-1]
        tail = client.get(
            path, params={**base, "level": level, "after": f"{last[0] or ''}:{last[1]}"}
        ).json()
        assert (tail["rows"], tail["next_after"]) == ([], None)
        whole = client.get(path, params={**base, "level": level, "limit": 500}).json()
        assert [(r["object_id"], r["currency"]) for r in whole["rows"]] == [
            (item[0], item[1]) for item in groups
        ]
        assert whole["next_after"] is None
    for cursor in ("111", "111:egp", "x:EGP", ":", "0:EGP", "111:EGPX", "111:EGP:USD"):
        response = client.get(path, params={**base, "after": cursor})
        assert response.status_code == 422, cursor
    assert ads.browser("analyst").get(path, params=base).status_code == 403
