"""016-B ROAS and cost per lead from stored credit on disposable PostgreSQL (D-089 D7).

Cases BV11-BV13 and, for the ROAS family, BV01, BV02, BV05, BV06 and BV16-BV18. Synthetic
journeys tagged with a campaign ID and an ad ID go through the 008-B worker; the report joins
the stored credit to the ads of one synthetic Meta-shaped spend connection and is compared
with the in-memory 014-C contract over the same runs. No provider is called; synthetic values
only.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta
from fractions import Fraction
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from attribution_support import LINEAR, make_attribution_world
from credit_support import (
    ad_objects,
    at,
    campaign,
    content,
    fraction,
    get,
    managed_link,
    parse_csv,
    sale_day,
    set_grant,
    span,
    tagged,
    today,
    visit,
)
from identity_support import make_identity_world
from report_support import (
    ad_account,
    checkpoint,
    connection,
    grant,
    key_client,
    service_key,
    spend_facts,
)
from report_support import run as sync_run
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.advertising.roas import Period, facts_from_rows, roas_report
from app.models import AdObject, AdSpendFact
from app.security import now_utc
from app.services import attribution_records as records
from app.services import attribution_store as store
from app.services import reporting

pytestmark = pytest.mark.integration
CAMPAIGN, OTHER_CAMPAIGN = "111", "112"
ADSET, OTHER_ADSET = "211", "212"
AD, SECOND_AD, THIRD_AD, LONELY_AD = "311", "312", "321", "331"
ZONE = "Africa/Cairo"


@pytest.fixture
def aw(authenticated_world, api):
    return make_attribution_world(make_identity_world(authenticated_world, api))


def spend_world(aw, day, *, zone=ZONE, client=None, ads=None, fresh=True):
    w = aw.w
    cid = connection(w, client or w.a1, "synthetic_meta_ads")
    ad_account(w, cid, "EGP", zone)
    checkpoint(w, cid, "ad_daily", at(day - timedelta(days=20), 0), at(day + timedelta(20), 0))
    sync_run(w, cid, "ad_daily", finished=now_utc() - timedelta(hours=1) if fresh else None)
    ad_objects(
        w,
        cid,
        ads
        or [
            (AD, ADSET, CAMPAIGN),
            (SECOND_AD, ADSET, CAMPAIGN),
            (THIRD_AD, OTHER_ADSET, OTHER_CAMPAIGN),
            (LONELY_AD, OTHER_ADSET, OTHER_CAMPAIGN),
        ],
    )
    return cid


def fact(ad, day, minor=None, *, campaign_id=CAMPAIGN, adset=ADSET, currency="EGP", **extra):
    return {
        "ad": ad,
        "adset": adset,
        "campaign": campaign_id,
        "day": day,
        "currency": currency,
        "minor": minor,
        "zone": extra.pop("zone", ZONE),
        **extra,
    }


def buy(aw, email, operation, minor, when, *tags):
    person = aw.person(email)
    for campaign_id, ad in tags:
        tagged(aw, person.token, campaign=campaign_id, content=ad)
    aw.sale(operation, minor, when=when)
    aw.associate(person.assertion, operation)
    return person


def meta(run):
    """The same run with Meta as the touches' source, for the in-memory 014-C contract."""
    return replace(
        run,
        allocations=tuple(
            replace(item, touch=None if item.touch is None else replace(item.touch, source="meta"))
            for item in run.allocations
        ),
    )


def contract_rows(aw, cid, day, zone=ZONE):
    """roas_report over the stored runs (reconstructed) and the stored spend of the connection."""
    w = aw.w
    row = aw.versions()[LINEAR]
    version = records.engine_version(row.version_key, row.model, row.window_seconds, row.rules)
    runs = []
    for conversion in aw.conversions():
        values = aw.latest(conversion.id)[LINEAR]
        engine_conversion = records.engine_conversion(
            conversion.id,
            w.a,
            w.a1,
            conversion.kind,
            conversion.owner_person_id,
            conversion.effective_at,
            conversion.source_account_id,
            conversion.sale_operation_id,
        )
        runs.append(
            meta(records.reconstruct(engine_conversion, version, values, ledger_position=None))
        )
    with Session(w.db.migration) as session:
        facts = facts_from_rows(
            session.scalars(select(AdSpendFact).where(AdSpendFact.connection_id == cid))
        )
        objects = {
            item.object_id: (item.campaign_id, item.adset_id)
            for item in session.scalars(
                select(AdObject).where(AdObject.connection_id == cid, AdObject.level == "ad")
            )
        }
    report = roas_report(
        facts,
        runs,
        agency_id=w.a,
        client_id=w.a1,
        connection_id=cid,
        period=Period(day, day),
        zone=zone,
        model_version=version,
        as_of=now_utc(),
        covered=(day - timedelta(days=20), day + timedelta(days=19)),
        objects=objects,
    )
    found = {}
    for item in report.rows:
        found.setdefault(item.level, []).append(
            (
                item.object_id,
                item.currency,
                None if item.spend is None else item.spend.minor,
                None if item.credited is None else item.credited.minor,
                None if item.roas is None else (item.roas.numerator, item.roas.denominator),
                item.reason,
                item.spend_state,
            )
        )
    return found, report


def view(row):
    return (
        row["object_id"],
        row["currency"],
        None if row["spend"] is None else row["spend"]["minor"],
        None if row["credited_revenue"] is None else row["credited_revenue"]["minor"],
        None if row["roas"] is None else (row["roas"]["numerator"], row["roas"]["denominator"]),
        row["roas_reason"],
        row["spend_state"],
    )


def test_bv11_roas_from_stored_credit_equals_the_contract(aw):
    w, day = aw.w, sale_day()
    cid = spend_world(aw, day)
    spend_facts(
        w,
        cid,
        [
            fact(AD, day, 5_000),
            fact(SECOND_AD, day, 0),
            fact(
                THIRD_AD,
                day,
                campaign_id=OTHER_CAMPAIGN,
                adset=OTHER_ADSET,
                refusal="unparseable_amount",
            ),
            fact(LONELY_AD, day, 700, campaign_id=OTHER_CAMPAIGN, adset=OTHER_ADSET),
            fact(AD, day - timedelta(days=1), 900),  # outside the period
        ],
    )
    buy(aw, "buyer@example.test", "S1", 10_000, at(day, 10), (CAMPAIGN, AD))
    buy(
        aw,
        "split@example.test",
        "S2",
        6_000,
        at(day, 11),
        (CAMPAIGN, SECOND_AD),
        (OTHER_CAMPAIGN, THIRD_AD),
    )
    buy(aw, "stray@example.test", "S3", 2_000, at(day, 12), ("999", AD))
    aw.sale("S4", 1_000, when=at(day, 13))  # never associated: unknown
    aw.settle()
    expected, contract = contract_rows(aw, cid, day)
    owner = aw.idw.owner
    for level in ("ad", "adset", "campaign"):
        response = get(owner, w, "roas", connection_id=cid, level=level, **span(day))
        assert response.status_code == 200, response.text
        body = response.json()
        assert [view(row) for row in body["rows"]] == expected[level], level
        assert body["model_version"]["version_key"] == LINEAR
        assert body["basis"] == "conversion_date" and body["day_zone"] == ZONE
    ad_rows = {
        row["object_id"]: row
        for row in get(owner, w, "roas", connection_id=cid, **span(day)).json()["rows"]
    }
    assert ad_rows[AD]["roas"] == {"numerator": 2, "denominator": 1, "decimal": "2.0000"}
    assert ad_rows[SECOND_AD]["roas_reason"] == "zero_spend"
    assert ad_rows[THIRD_AD]["spend_state"] == "incomplete"
    assert ad_rows[LONELY_AD]["credited_revenue"] == {"minor": 0, "decimal": "0.00"}
    body = get(owner, w, "roas", connection_id=cid, **span(day)).json()
    assert body["unmatched"] == [
        {
            "period": "current",
            "currency": "EGP",
            "exponent": 2,
            "credited_revenue": {"minor": 3_000, "decimal": "30.00"},
        }
    ]
    assert [money.minor for money in contract.unmatched] == [3_000]
    (account,) = body["totals"]
    assert (account["level"], account["spend"]["minor"], account["credited_revenue"]["minor"]) == (
        "account",
        5_700,
        16_000,
    )
    assert body["spend_source"]["stream"]["stream"] == "ad_daily"


def test_bv12_join_needs_campaign_and_ad_of_the_connection(aw):
    w, day = aw.w, sale_day()
    cid = spend_world(aw, day)
    other = spend_world(aw, day, ads=[("999", ADSET, CAMPAIGN)])
    spend_facts(w, cid, [fact(AD, day, 1_000), fact(SECOND_AD, day, 1_000)])
    owner = aw.idw.owner
    buy(aw, "match@example.test", "S1", 1_000, at(day, 10), (CAMPAIGN, AD))
    buy(aw, "wrong-campaign@example.test", "S2", 2_000, at(day, 10), (OTHER_CAMPAIGN, AD))
    buy(aw, "other-account@example.test", "S3", 4_000, at(day, 10), (CAMPAIGN, "999"))
    # A managed link's content reference wins over the URL's utm_content value.
    linked = managed_link(
        owner,
        w,
        "meta-link",
        campaign_id=campaign(owner, w, CAMPAIGN),
        content_id=content(owner, w, SECOND_AD),
    )
    person = aw.person("linked@example.test")
    visit(aw, person.token, linked, query=f"?utm_content={AD}")
    aw.sale("S4", 8_000, when=at(day, 10))
    aw.associate(person.assertion, "S4")
    # A padded utm_content value is not a usable reference and is ignored.
    buy(aw, "padded@example.test", "S5", 16_000, at(day, 10), (CAMPAIGN, "%20311"))
    aw.settle()
    assert [row.content_ref for row in aw.latest(aw.conversion("S4").id)[LINEAR].allocations] == [
        SECOND_AD
    ]
    assert [row.content_ref for row in aw.latest(aw.conversion("S5").id)[LINEAR].allocations] == [
        None
    ]
    body = get(owner, w, "roas", connection_id=cid, **span(day)).json()
    rows = {row["object_id"]: row["credited_revenue"]["minor"] for row in body["rows"]}
    assert rows[AD] == 1_000 and rows[SECOND_AD] == 8_000
    assert body["unmatched"][0]["credited_revenue"]["minor"] == 2_000 + 4_000 + 16_000
    # The ad of another account matches only under its own connection.
    there = get(owner, w, "roas", connection_id=other, **span(day)).json()
    assert {row["object_id"]: row["credited_revenue"]["minor"] for row in there["rows"]} == {
        "999": 4_000
    }


def test_bv12_adapter_change_rebuilds_once_and_keeps_history(aw, monkeypatch):
    w, day = aw.w, sale_day()
    cid = spend_world(aw, day)
    spend_facts(w, cid, [fact(AD, day, 2_000)])
    original = store.touchpoints

    def before_016b(session, agency_id, client_id, person_id, now):
        touches = original(session, agency_id, client_id, person_id, now)
        return [touch if touch.link_ref else replace(touch, content_ref=None) for touch in touches]

    monkeypatch.setattr(store, "touchpoints", before_016b)
    monkeypatch.setattr(records, "INPUT_ADAPTER_REVISION", 1)
    buy(aw, "buyer@example.test", "S1", 10_000, at(day, 10), (CAMPAIGN, AD), (CAMPAIGN, SECOND_AD))
    buy(aw, "plain@example.test", "S2", 3_000, at(day, 11), ("plain", None))
    aw.settle()
    owner = aw.idw.owner
    before = get(owner, w, "roas", connection_id=cid, **span(day)).json()
    assert before["unmatched"][0]["credited_revenue"]["minor"] == 13_000
    history = aw.snapshot()
    totals = aw.ledger(LINEAR)
    old_digest = aw.state().model_set_digest
    monkeypatch.undo()
    counts = aw.settle()
    assert counts["rebuilds"] == 1
    assert aw.state().model_set_digest != old_digest
    after = aw.snapshot()
    for table, stored in history.items():
        assert set(stored) <= set(after[table]), table  # every earlier row is byte-identical
    assert aw.ledger(LINEAR) == totals  # totals by campaign, recipient and currency
    conversion = aw.conversion("S1")
    revisions = aw.revisions(conversion.id, LINEAR)
    assert [item.revision for item in revisions] == [1, 2]
    assert revisions[-1].causes == ("evidence_changed",)
    assert [row.content_ref for row in revisions[-1].allocations] == [AD, SECOND_AD]
    assert len(aw.revisions(aw.conversion("S2").id, LINEAR)) == 1  # nothing to move
    report = get(owner, w, "roas", connection_id=cid, **span(day)).json()
    rows = {row["object_id"]: row["credited_revenue"]["minor"] for row in report["rows"]}
    assert rows == {AD: 5_000, SECOND_AD: 5_000}
    assert report["unmatched"][0]["credited_revenue"]["minor"] == 3_000
    assert aw.settle().get("rebuilds", 0) == 0  # once only
    aw.assert_fresh()


def test_bv13_cost_per_lead(aw):
    w, day = aw.w, today()
    cid = spend_world(aw, day)
    spend_facts(
        w,
        cid,
        [
            fact(AD, day, 3_000),
            fact(SECOND_AD, day, 0),
            fact(THIRD_AD, day, 1_000, campaign_id=OTHER_CAMPAIGN, adset=OTHER_ADSET),
            # One ad reported in two currencies over the period: no ROAS, no cost per lead.
            fact(
                LONELY_AD,
                day - timedelta(days=1),
                100,
                campaign_id=OTHER_CAMPAIGN,
                adset=OTHER_ADSET,
            ),
            fact(
                LONELY_AD, day, 100, campaign_id=OTHER_CAMPAIGN, adset=OTHER_ADSET, currency="USD"
            ),
        ],
    )
    # Three account-local dates around today, so the leads made now fall inside in Cairo.
    window = span(day - timedelta(days=1), 3)
    one = aw.person("one@example.test")
    tagged(aw, one.token, campaign=CAMPAIGN, content=AD)
    aw.lead(one.token)
    two = aw.person("two@example.test")
    tagged(aw, two.token, campaign=CAMPAIGN, content=AD)
    tagged(aw, two.token, campaign=CAMPAIGN, content=SECOND_AD)
    aw.lead(two.token)
    three = aw.person("three@example.test")
    tagged(aw, three.token, campaign=OTHER_CAMPAIGN, content=LONELY_AD)
    aw.lead(three.token)
    aw.settle()
    body = get(aw.idw.owner, w, "roas", connection_id=cid, **window).json()
    rows = {row["object_id"]: row for row in body["rows"]}
    assert fraction(rows[AD]["credited_leads"]) == Fraction(3, 2)
    assert rows[AD]["cost_per_lead"] == {"numerator": 2_000, "denominator": 1, "decimal": "20.00"}
    assert rows[AD]["cost_per_lead_reason"] is None
    assert (rows[SECOND_AD]["cost_per_lead"], rows[SECOND_AD]["cost_per_lead_reason"]) == (
        None,
        "zero_spend",
    )
    assert (rows[THIRD_AD]["cost_per_lead"], rows[THIRD_AD]["cost_per_lead_reason"]) == (
        None,
        "zero_leads",
    )
    assert rows[LONELY_AD]["cost_per_lead_reason"] == "currency_mismatch"
    assert rows[LONELY_AD]["roas_reason"] == "currency_mismatch"
    (account,) = body["totals"]
    assert fraction(account["credited_leads"]) == Fraction(3)
    assert account["cost_per_lead_reason"] == "currency_mismatch"
    campaigns = {
        row["object_id"]: row
        for row in get(
            aw.idw.owner, w, "roas", connection_id=cid, level="campaign", **window
        ).json()["rows"]
    }
    assert campaigns[CAMPAIGN]["cost_per_lead"]["decimal"] == "15.00"  # 3,000 / 2 leads


def test_roas_isolation_permissions_and_periods(aw, api):
    w = aw.w
    # Daylight-saving end in America/Los_Angeles (2026-11-01 has 25 hours): credit and spend on
    # account-local dates. Unassociated sales credit unknown, so no touch is needed.
    zone = "America/Los_Angeles"
    local = ZoneInfo(zone)
    nov1 = date(2026, 11, 1)
    cid = spend_world(aw, nov1, zone=zone)
    spend_facts(w, cid, [fact(AD, nov1, 2_500, zone=zone)])
    inside = [
        datetime(2026, 11, 1, 0, 0, tzinfo=local),
        datetime(2026, 11, 1, 23, 30, tzinfo=local),
    ]
    outside = [
        datetime(2026, 11, 2, 0, 0, tzinfo=local),
        datetime(2026, 10, 31, 23, 59, tzinfo=local),
    ]
    for index, moment in enumerate(inside + outside):
        aw.sale(f"D{index}", 1_000 * (index + 1), when=moment)
    aw.settle()
    owner = aw.idw.owner
    period = {"start": "2026-11-01", "end": "2026-11-02"}
    body = get(owner, w, "roas", connection_id=cid, **period).json()
    assert body["unmatched"][0]["credited_revenue"]["minor"] == 1_000 + 2_000
    assert body["totals"][0]["spend"]["minor"] == 2_500 and body["day_zone"] == zone
    # Permissions: finance:read is required; read keys follow the same rule.
    assert get(w.signed_in("analyst"), w, "roas", connection_id=cid, **period).status_code == 403
    assert get(w.signed_in("viewer"), w, "roas", connection_id=cid, **period).status_code == 403
    set_grant(aw, can_view_financials=True)
    assert get(w.signed_in("analyst"), w, "roas", connection_id=cid, **period).status_code == 200
    plain = key_client(api, service_key(w, api, [grant(w.a1)]))
    finance = key_client(api, service_key(w, api, [grant(w.a1, financial=True)]))
    assert get(plain, w, "roas", connection_id=cid, **period).status_code == 403
    assert get(finance, w, "roas", connection_id=cid, **period).status_code == 200
    assert get(aw.idw.ingest, w, "roas", connection_id=cid, **period).status_code in {401, 403}
    # Isolation: another client's connection, an unknown one and a foreign model version.
    foreign = connection(w, w.a2, "synthetic_meta_ads")
    instagram = connection(w, w.a1, "synthetic_instagram")
    for params, status, code in (
        ({"connection_id": foreign}, 403, "access_denied"),
        ({"connection_id": uuid4()}, 403, "access_denied"),
        ({"connection_id": cid, "model_version": str(uuid4())}, 403, "access_denied"),
        ({"connection_id": instagram}, 422, "not_a_spend_connection"),
        ({"connection_id": cid, "start": "2026-11-02", "end": "2026-11-01"}, 422, "invalid_period"),
        ({"connection_id": cid, "start": "2026-10-01", "end": "2026-11-02"}, 422, "invalid_period"),
        ({"connection_id": cid, "group_by": "campaign"}, 422, "unknown_parameter"),
    ):
        response = get(owner, w, "roas", **{**period, **params})
        assert (response.status_code, response.json()) == (status, {"error": code}), params
    assert get(w.signed_in("owner_b"), w, "roas", connection_id=cid, **period).status_code == 403
    # An invalid stored zone is refused; a connection without any zone answers day_zone_unknown.
    broken = connection(w, w.a1, "synthetic_meta_ads")
    ad_account(w, broken, "EGP", "Mars/Olympus")
    response = get(owner, w, "roas", connection_id=broken, **period)
    assert (response.status_code, response.json()) == (422, {"error": "invalid_zone"})
    never = connection(w, w.a1, "synthetic_meta_ads")
    response = get(owner, w, "roas", connection_id=never, **period)
    assert (response.status_code, response.json()) == (409, {"error": "day_zone_unknown"})


def test_roas_comparison_pages_release_and_csv(aw, monkeypatch):
    w, day = aw.w, sale_day(3)
    cid = spend_world(aw, day)
    previous = day - timedelta(days=1)
    spend_facts(
        w,
        cid,
        [fact(AD, day, 4_000), fact(AD, previous, 2_000), fact(SECOND_AD, day, 1_000)],
    )
    buyer = buy(aw, "buyer@example.test", "S1", 6_000, at(day, 10), (CAMPAIGN, AD))
    aw.sale("S0", 3_000, when=at(previous, 10))
    aw.associate(buyer.assertion, "S0")
    aw.settle()
    owner = aw.idw.owner
    body = get(owner, w, "roas", connection_id=cid, compare="previous", **span(day)).json()
    rows = {item["metric"]: item for item in body["comparison"]}
    assert (rows["spend"]["percent_change"], rows["spend"]["comparable"]) == ("150.00", True)
    assert rows["credited_revenue"]["percent_change"] == "100.00"
    assert [item["period"] for item in body["totals"]] == ["current", "previous"]
    # Behind attribution blocks the percentages.
    tagged(aw, buyer.token, campaign=CAMPAIGN, content=SECOND_AD)
    behind = get(owner, w, "roas", connection_id=cid, compare="previous", **span(day)).json()
    assert {item["reason"] for item in behind["comparison"]} == {"attribution_behind"}
    aw.settle()
    # Pages: one ad per page, bound to the revision; a worker pass changes it.
    first = get(owner, w, "roas", connection_id=cid, page_size=1, **span(day)).json()
    assert first["page"]["total_rows"] == 2
    second = get(
        owner,
        w,
        "roas",
        connection_id=cid,
        page_size=1,
        page=2,
        expected_revision=first["revision"],
        **span(day),
    ).json()
    assert [row["object_id"] for row in first["rows"] + second["rows"]] == [AD, SECOND_AD]
    aw.settle()
    changed = get(
        owner,
        w,
        "roas",
        connection_id=cid,
        page_size=1,
        page=2,
        expected_revision=first["revision"],
        **span(day),
    )
    assert (changed.status_code, changed.json()) == (409, {"error": "report_changed"})

    # A changed spend fact between building and release refuses JSON and CSV.
    def change_spend():
        with Session(w.db.migration) as session, session.begin():
            session.execute(
                update(AdSpendFact)
                .where(AdSpendFact.connection_id == cid)
                .values(spend_minor=AdSpendFact.spend_minor + 1)
            )

    for output in ("json", "csv"):
        calls: list[str] = []

        def hook(family, calls=calls):
            calls.append(family)
            change_spend()

        monkeypatch.setattr(reporting, "before_release", hook)
        response = get(owner, w, "roas", connection_id=cid, format=output, **span(day))
        assert (calls, response.status_code, response.json()) == (
            ["roas"],
            409,
            {"error": "report_changed"},
        )
    monkeypatch.setattr(reporting, "before_release", reporting._no_hook)
    # CSV equals JSON under one revision, with the id: prefix on every ad ID.
    body = get(owner, w, "roas", connection_id=cid, **span(day)).json()
    response = get(owner, w, "roas", connection_id=cid, format="csv", **span(day))
    assert response.headers["content-disposition"] == 'attachment; filename="report-roas.csv"'
    cells = parse_csv(response)
    assert [row for row in cells if row["metric"] == "revision"][0][
        "object_id"
    ] == f"id:{body['revision']}"
    from_csv = {
        row["object_id"]: int(row["value_minor"])
        for row in cells
        if row["row_type"] == "value" and row["metric"] == "credited_revenue" and row["value_minor"]
    }
    assert from_csv == {
        f"id:{row['object_id']}": row["credited_revenue"]["minor"] for row in body["rows"]
    }
    assert all(row["object_id"].startswith("id:") for row in cells if row["object_id"])
    assert "Synthetic" not in response.text and "example.test" not in response.text
    with w.db.migration.connect() as connection_:
        assert connection_.execute(text("SELECT count(*) FROM ad_spend_facts")).scalar_one() == 3
