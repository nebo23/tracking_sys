"""016-B attribution report over stored credit on disposable PostgreSQL (D-089).

Cases BV01-BV10 and BV16-BV18 of the 016-B verification matrix for the attribution family.
Synthetic journeys, leads and verified sales go through the 008-B worker; the report reads the
stored credit of the published generation and is compared with the stored allocations, the
persisted ledger and its own CSV. Synthetic values only.
"""

from datetime import timedelta
from fractions import Fraction
from uuid import uuid4

import pytest
from attribution_support import FIRST, LAST, LINEAR, USD, make_attribution_world
from credit_support import (
    at,
    campaign,
    content,
    credit_map,
    fraction,
    get,
    lead_total,
    managed_link,
    parse_csv,
    sale_day,
    set_grant,
    span,
    today,
    total,
    versions,
    visit,
)
from identity_support import make_identity_world
from report_support import NOW, connection, grant, key_client, records, service_key
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind
from app.models import AttributionConsumerState
from app.security import now_utc
from app.services import attribution_store as store
from app.services import reporting
from app.services.attribution_scrub import scrub_person

pytestmark = pytest.mark.integration
ONE, HALF, THIRD = Fraction(1), Fraction(1, 2), Fraction(1, 3)


@pytest.fixture
def aw(authenticated_world, api):
    return make_attribution_world(make_identity_world(authenticated_world, api))


def journeys(aw, day):
    """Campaign, direct, unknown and lead credit (the AV01 journey and more): touches and the
    lead now, the sales on the given future UTC date."""
    buyer = aw.person("buyer@example.test")
    aw.touch(buyer.token, "spring")
    aw.touch(buyer.token, "autumn")
    aw.touch(buyer.token, None)  # direct, superseded by the campaigns
    aw.sale("S1", 10_000, when=at(day, 10))
    aw.associate(buyer.assertion, "S1")
    walker = aw.person("walker@example.test")
    aw.touch(walker.token, None)
    aw.sale("S2", 4_000, when=at(day, 11))
    aw.associate(walker.assertion, "S2")
    aw.sale("S3", 2_500, when=at(day, 12))  # never associated: unknown
    asker = aw.person("asker@example.test")
    aw.touch(asker.token, "spring")
    aw.lead(asker.token)
    aw.settle()
    return buyer, walker, asker


def window(day, days=1):
    return {"start": today().isoformat(), "end": (day + timedelta(days=days)).isoformat()}


def _race(monkeypatch, action):
    calls = []

    def hook(family):
        calls.append(family)
        action()

    monkeypatch.setattr(reporting, "before_release", hook)
    return calls


def _migrate(w, statement, values=None):
    with w.db.migration.begin() as connection_:
        connection_.execute(text(statement) if isinstance(statement, str) else statement, values)


def test_bv03_credit_equals_stored_allocations_and_reconciles(aw):
    day = sale_day()
    journeys(aw, day)
    owner = aw.idw.owner
    ids = versions(owner, aw.w)
    for key in (FIRST, LAST, LINEAR):
        response = get(owner, aw.w, "attribution", model_version=ids[key], **window(day))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["model_version"]["version_key"] == key
        assert body["attribution"]["state"] == "caught_up"
        assert body["values"] == {"state": "available", "reason": None}
        assert credit_map(body) == aw.ledger(key)
        # Direct and unknown credit are rows of their own.
        kinds = [(row["recipient"], row["group_ref"]) for row in body["rows"]]
        assert ("direct", None) in kinds and ("unknown", None) in kinds
        assert total(body)["credited_revenue"] == {"minor": 16_500, "decimal": "165.00"}
        assert total(body, recipient="unknown")["credited_revenue"]["minor"] == 2_500
        assert total(body, recipient="direct")["credited_revenue"]["minor"] == 4_000
        assert total(body)["conversions"] == 3
        assert fraction(lead_total(body)["credited_leads"]) == ONE
        (item,) = body["reconciliation"]["items"]
        assert (item["state"], item["credited_revenue"]["minor"], item["ledger_net"]["minor"]) == (
            "reconciled",
            16_500,
            16_500,
        )
    # The default is Linear, and a report without a version uses it.
    default = get(owner, aw.w, "attribution", **window(day)).json()
    assert default["model_version"]["version_key"] == LINEAR
    rows = {row["group_ref"] or row["recipient"]: row for row in default["rows"]}
    assert fraction(rows["spring"]["sales"]["items"][0]["credited_sales"]) == HALF
    assert rows["spring"]["sales"]["items"][0]["conversions"] == 1
    assert rows["spring"]["leads"]["conversions"] == 1
    assert rows["unknown"]["sales"]["items"][0]["credited_revenue"]["minor"] == 2_500
    # The recipient view has exactly the three classes.
    by_class = get(owner, aw.w, "attribution", group_by="recipient", **window(day)).json()
    assert [row["recipient"] for row in by_class["rows"]] == ["campaign", "direct", "unknown"]
    assert {row["group_ref"] for row in by_class["rows"]} == {None}


def test_bv01_isolation_across_agencies_clients_and_versions(aw):
    w, day = aw.w, sale_day()
    for client, minor in ((w.a1, 10_000), (w.a2, 3_000)):
        buyer = aw.person("same@example.test", client=client)
        aw.touch(buyer.token, "spring", client=client)
        aw.sale("S1", minor, when=at(day, 10), client=client)
        aw.associate(buyer.assertion, "S1", client=client)
        aw.settle(client)
    owner = aw.idw.owner
    mine = get(owner, w, "attribution", **span(day)).json()
    theirs = get(owner, w, "attribution", client=w.a2, **span(day)).json()
    assert credit_map(mine) == {("spring", "EGP"): (ONE, 10_000)}
    assert credit_map(theirs) == {("spring", "EGP"): (ONE, 3_000)}
    assert mine["reconciliation"]["items"][0]["ledger_net"]["minor"] == 10_000
    foreign = versions(owner, w, client=w.a2)[LINEAR]
    denied = {"error": "access_denied"}
    for response in (
        get(owner, w, "attribution", model_version=foreign, **span(day)),
        get(owner, w, "attribution", model_version=str(uuid4()), **span(day)),
        get(w.signed_in("owner_b"), w, "attribution", **span(day)),
        get(owner, w, "attribution", client=uuid4(), **span(day)),
        get(w.signed_in("outsider"), w, "attribution", **span(day)),
    ):
        assert (response.status_code, response.json()) == (403, denied)
    other = get(w.signed_in("owner_b"), w, "attribution", client=w.b1, agency=w.b, **span(day))
    assert other.status_code == 200, other.text
    assert other.json()["values"] == {"state": "not_ready", "reason": "attribution_not_ready"}
    assert "spring" not in other.text and "10000" not in other.text


def test_bv02_lead_credit_without_finance_and_key_rules(aw, api):
    w, day = aw.w, sale_day()
    journeys(aw, day)
    full = get(aw.idw.owner, w, "attribution", compare="previous", **window(day)).json()
    assert full["finance"] == "available"
    for name in ("analyst", "viewer"):
        response = get(w.signed_in(name), w, "attribution", compare="previous", **window(day))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["finance"] == "permission_unavailable"
        assert body["totals"]["sales"] == {
            "state": "permission_unavailable",
            "reason": None,
            "items": None,
        }
        assert body["reconciliation"]["state"] == "permission_unavailable"
        assert body["reconciliation"]["items"] is None
        assert {row["sales"]["state"] for row in body["rows"]} == {"permission_unavailable"}
        assert {item["kind"] for item in body["comparison"]} == {"lead"}
        # Lead credit stays; no currency, amount or sale count appears anywhere.
        assert fraction(lead_total(body)["credited_leads"]) == ONE
        for secret in ("EGP", "credited_revenue", "16500", "165.00", "sale_conversions"):
            assert secret not in response.text, secret
        csv_text = get(w.signed_in(name), w, "attribution", format="csv", **window(day)).text
        assert "EGP" not in csv_text and "16500" not in csv_text
    set_grant(aw, can_view_financials=True)
    analyst = get(w.signed_in("analyst"), w, "attribution", **window(day)).json()
    assert (
        analyst["finance"] == "available" and total(analyst)["credited_revenue"]["minor"] == 16_500
    )
    # Read keys follow the same rules; an ingest key is not a reader.
    leads_only = key_client(api, service_key(w, api, [grant(w.a1)]))
    body = get(leads_only, w, "attribution", **window(day)).json()
    assert body["finance"] == "permission_unavailable" and "EGP" not in str(body)
    finance_key = key_client(api, service_key(w, api, [grant(w.a1, financial=True)]))
    assert total(get(finance_key, w, "attribution", **window(day)).json())["conversions"] == 3
    assert get(finance_key, w, "attribution", client=w.a2, **window(day)).status_code == 403
    assert get(aw.idw.ingest, w, "attribution", **window(day)).status_code in {401, 403}


def test_bv04_refund_late_touch_owner_change_and_moved_sale(aw):
    w, day = aw.w, sale_day()
    buyer = aw.person("buyer@example.test")
    aw.touch(buyer.token, "spring")
    aw.sale("S1", 10_000, when=at(day, 10))
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    owner = aw.idw.owner
    # A refund dated the next day lowers the credited revenue of the sale's own date.
    aw.sale("R1", 3_000, kind=OperationKind.REFUND, parent="S1", when=at(day + timedelta(1), 9))
    aw.settle()
    first = get(owner, w, "attribution", **span(day)).json()
    assert credit_map(first) == {("spring", "EGP"): (ONE, 7_000)}
    assert get(owner, w, "attribution", **span(day + timedelta(1))).json()["rows"] == []
    # A late touch: the sale stays credited exactly once.
    aw.touch(buyer.token, "autumn")
    aw.settle()
    late = get(owner, w, "attribution", **span(day)).json()
    assert credit_map(late) == {("spring", "EGP"): (HALF, 3_500), ("autumn", "EGP"): (HALF, 3_500)}
    assert total(late)["conversions"] == 1
    # An owner change (detach) supersedes the conversion: the successor credits unknown.
    aw.detach("S1")
    aw.settle()
    detached = get(owner, w, "attribution", **span(day)).json()
    assert credit_map(detached) == {("unknown", "EGP"): (ONE, 7_000)}
    assert total(detached)["conversions"] == 1

    # A moved sale time: a settlement first, then the capture with an earlier instant.
    def evidence(classification, when, delivery):
        return Evidence(
            delivery,
            w.a,
            w.a1,
            "shop",
            "S9",
            OperationKind.SALE,
            classification,
            Money(5_000, Currency("EGP", 2)),
            when,
            when,
        )

    from report_support import append

    later, earlier = day + timedelta(2), day + timedelta(1)
    append(
        w, [evidence(EvidenceClass.CONFIRMED_SETTLEMENT, at(later, 9), "d:S9:settle")], "csv_import"
    )
    aw.settle()
    assert total(get(owner, w, "attribution", **span(later)).json())["conversions"] == 1
    append(
        w, [evidence(EvidenceClass.CONFIRMED_CAPTURE, at(earlier, 9), "d:S9:capture")], "csv_import"
    )
    aw.settle()
    assert get(owner, w, "attribution", **span(later)).json()["rows"] == []
    moved = get(owner, w, "attribution", **span(earlier)).json()
    assert credit_map(moved) == {("unknown", "EGP"): (ONE, 5_000)}
    whole = get(owner, w, "attribution", **span(day, 3)).json()
    assert total(whole)["conversions"] == 2 and total(whole)["credited_revenue"]["minor"] == 12_000
    assert whole["reconciliation"]["items"][0]["state"] == "reconciled"
    aw.assert_fresh()


def test_bv05_utc_bounds_to_the_microsecond_and_refusals(aw):
    w, day = aw.w, sale_day()
    midnight = at(day, 0)
    aw.sale("S1", 1_000, when=midnight)
    aw.sale("S2", 2_000, when=midnight + timedelta(days=1) - timedelta(microseconds=1))
    aw.sale("S3", 4_000, when=midnight + timedelta(days=1))
    aw.sale("S4", 8_000, when=midnight - timedelta(microseconds=1))
    aw.settle()
    owner = aw.idw.owner
    body = get(owner, w, "attribution", **span(day)).json()
    assert total(body)["credited_revenue"]["minor"] == 3_000
    assert body["day_zone"] == "UTC" and body["basis"] == "conversion_date"
    assert body["period"] == {
        "start": day.isoformat(),
        "end": (day + timedelta(1)).isoformat(),
        "days": 1,
    }
    base = report = f"/agencies/{w.a}/clients/{w.a1}/reports/attribution"
    for params, code in (
        ({"start": "2026-12-02", "end": "2026-12-01"}, "invalid_period"),
        ({"start": "2026-12-01", "end": "2026-12-01"}, "invalid_period"),
        ({"start": "2026-11-01", "end": "2026-12-03"}, "invalid_period"),
        ({**span(day), "metrics": "views"}, "unknown_parameter"),
        ({**span(day), "format": "csv", "page": "1"}, "csv_pagination_unsupported"),
        ({**span(day), "view": "models", "compare": "previous"}, "comparison_unsupported"),
        (
            {**span(day), "view": "models", "model_version": str(uuid4())},
            "model_version_not_applicable",
        ),
        ({**span(day), "group_by": "channel"}, "validation_failed"),
    ):
        response = owner.get(base, params=params)
        assert (response.status_code, response.json()) == (422, {"error": code}), params
    repeated = owner.get(
        f"{report}?start={day}&end={day + timedelta(1)}&group_by=link&group_by=content"
    )
    assert (repeated.status_code, repeated.json()["error"]) == (422, "unknown_parameter")
    assert get(owner, w, "attribution", start="2026-11-01", end="2026-12-02").status_code == 200


def test_bv06_comparison_of_equal_periods(aw):
    w, day = aw.w, sale_day()
    buyer = aw.person("buyer@example.test")
    aw.touch(buyer.token, "spring")
    aw.sale("S1", 10_000, when=at(day, 10))
    aw.sale("S2", 15_000, when=at(day + timedelta(1), 10))
    aw.associate(buyer.assertion, "S1")
    aw.associate(buyer.assertion, "S2")
    aw.settle()
    owner = aw.idw.owner
    body = get(owner, w, "attribution", compare="previous", **span(day + timedelta(1))).json()
    assert body["comparison_period"] == {
        "start": day.isoformat(),
        "end": (day + timedelta(1)).isoformat(),
        "days": 1,
    }
    rows = {item["metric"]: item for item in body["comparison"]}
    revenue = rows["credited_revenue"]
    assert (revenue["percent_change"], revenue["comparable"], revenue["reason"]) == (
        "50.00",
        True,
        None,
    )
    assert revenue["difference"] == {"minor": 5_000, "decimal": "50.00"}
    assert rows["credited_sales"]["percent_change"] == "0.00"
    leads = rows["credited_leads"]
    assert (leads["percent_change"], leads["comparable"], leads["reason"]) == (
        None,
        True,
        "zero_baseline",
    )
    assert total(body, period="previous")["credited_revenue"]["minor"] == 10_000
    # While attribution is behind, values are served and labeled, but no percentage holds.
    aw.touch(buyer.token, "autumn")
    behind = get(owner, w, "attribution", compare="previous", **span(day + timedelta(1))).json()
    assert behind["attribution"]["state"] == "behind"
    assert total(behind)["credited_revenue"]["minor"] == 15_000
    assert {item["reason"] for item in behind["comparison"]} == {"attribution_behind"}
    assert {item["percent_change"] for item in behind["comparison"]} == {None}
    assert {item["comparable"] for item in behind["comparison"]} == {False}
    (difference,) = [
        item for item in behind["reconciliation"]["items"] if item["period"] == "current"
    ]
    assert difference["state"] == "reconciled"


def test_bv07_models_view_side_by_side(aw):
    w, day = aw.w, sale_day()
    journeys(aw, day)
    owner = aw.idw.owner
    ids = versions(owner, w)
    body = get(owner, w, "attribution", view="models", **window(day)).json()
    assert [item["version_key"] for item in body["model_versions"]] == [FIRST, LAST, LINEAR]
    assert body["totals"] is None and body["model_version"] is None
    for row in body["rows"]:
        assert [item["model_version_id"] for item in row["models"]] == [
            ids[FIRST],
            ids[LAST],
            ids[LINEAR],
        ]
    spring = next(row for row in body["rows"] if row["group_ref"] == "spring")
    shares = [
        sum((fraction(entry["credited_sales"]) for entry in item["sales"]["items"]), Fraction(0))
        for item in spring["models"]
    ]
    assert shares == [ONE, Fraction(0), HALF]  # First Click, Last Click (autumn), Linear
    # Each version's total reconciles on its own; versions are never added up.
    for item in body["model_reconciliation"]:
        assert [entry["state"] for entry in item["items"]] == ["reconciled"]
    sums = [
        next(entry for entry in item["sales"]["items"] if entry["recipient"] == "all")
        for item in body["model_totals"]
    ]
    assert [entry["credited_revenue"]["minor"] for entry in sums] == [16_500] * 3
    assert "50000" not in str(body["model_totals"])
    # A retired version can still be read and is labeled retired; an unknown one is refused.
    retired = owner.post(
        f"/agencies/{w.a}/clients/{w.a1}/attribution/models/{ids[FIRST]}/retire",
        json={"operation_id": str(uuid4())},
    )
    assert retired.status_code == 201, retired.text
    aw.settle()
    old = get(owner, w, "attribution", model_version=ids[FIRST], **window(day)).json()
    assert old["model_version"]["status"] == "retired"
    assert credit_map(old) == aw.ledger(FIRST)
    active = get(owner, w, "attribution", view="models", **window(day)).json()
    assert [item["version_key"] for item in active["model_versions"]] == [LAST, LINEAR]
    assert (
        get(owner, w, "attribution", model_version=str(uuid4()), **window(day)).status_code == 403
    )


def test_bv08_groups_flags_and_social_content_pointer(aw):
    w, day = aw.w, sale_day()
    owner = aw.idw.owner
    spring = campaign(owner, w, "spring")
    post = content(owner, w, "post-1")
    tagged_link = managed_link(owner, w, "spring-post", campaign_id=spring, content_id=post)
    bare_link = managed_link(owner, w, "bare-link")
    instagram = connection(w, w.a1, "synthetic_instagram")
    records(
        w,
        instagram,
        [
            {"stream": "media", "object_id": "post-1", "observed_at": NOW, "metrics": {"likes": 3}},
            {"stream": "media", "object_id": "POST-1", "observed_at": NOW},
            {"stream": "account", "object_id": "post-1", "observed_at": NOW},
        ],
    )
    foreign = connection(w, w.a2, "synthetic_instagram")
    records(w, foreign, [{"stream": "media", "object_id": "post-1", "observed_at": NOW}])
    buyer = aw.person("buyer@example.test")
    visit(aw, buyer.token, tagged_link)
    visit(aw, buyer.token, bare_link)
    aw.touch(buyer.token, "autumn")  # a retained utm_campaign value, not registered
    aw.sale("S1", 9_000, when=at(day, 10))
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    by_campaign = get(owner, w, "attribution", **span(day)).json()
    keys = [(row["recipient"], row["group_ref"], row["registered"]) for row in by_campaign["rows"]]
    assert keys == [
        ("campaign", "autumn", False),
        ("campaign", "spring", True),
        ("campaign", None, None),
    ]
    assert {row["content_items"] for row in by_campaign["rows"]} == {None}
    by_content = get(owner, w, "attribution", group_by="content", **span(day)).json()
    rows = {row["group_ref"]: row for row in by_content["rows"]}
    assert set(rows) == {"post-1", None}  # a missing content reference is a group of its own
    assert rows["post-1"]["registered"] is True and rows[None]["registered"] is None
    assert rows["post-1"]["content_items"] == [
        {
            "connection_id": str(instagram),
            "provider": "synthetic_instagram",
            "stream": "media",
            "content_id": "post-1",
        }
    ]
    assert rows[None]["content_items"] == []
    by_link = get(owner, w, "attribution", group_by="link", **span(day)).json()
    links = {row["group_ref"]: row["registered"] for row in by_link["rows"]}
    assert links == {str(tagged_link): True, str(bare_link): True, None: None}
    assert fraction(by_link["rows"][0]["sales"]["items"][0]["credited_sales"]) == THIRD
    for body in (by_campaign, by_content, by_link):
        assert "Synthetic" not in str(body) and "label" not in str(body)


def test_bv09_currencies_stay_apart_and_thirds_sum_to_one(aw):
    w, day = aw.w, sale_day()
    buyer = aw.person("buyer@example.test")
    for code in ("one", "two", "three"):
        aw.touch(buyer.token, code)
    aw.sale("E1", 1_000, when=at(day, 10))
    aw.sale("U1", 1_000, when=at(day, 11), currency=USD)
    aw.associate(buyer.assertion, "E1")
    aw.associate(buyer.assertion, "U1")
    asker = aw.person("asker@example.test")
    for code in ("one", "two", "three"):
        aw.touch(asker.token, code)
    aw.lead(asker.token)
    aw.settle()
    body = get(aw.idw.owner, w, "attribution", **window(day)).json()
    for currency in ("EGP", "USD"):
        assert total(body, currency=currency)["credited_revenue"]["minor"] == 1_000
        shares = [
            fraction(item["credited_sales"])
            for row in body["rows"]
            for item in row["sales"]["items"]
            if item["currency"] == currency
        ]
        assert shares == [THIRD] * 3 and sum(shares) == ONE
        amounts = sorted(
            item["credited_revenue"]["minor"]
            for row in body["rows"]
            for item in row["sales"]["items"]
            if item["currency"] == currency
        )
        assert amounts == [333, 333, 334]
    assert {
        item["credited_sales"]["decimal"] for row in body["rows"] for item in row["sales"]["items"]
    } == {"0.3333"}
    assert sum(fraction(row["leads"]["credited_leads"]) for row in body["rows"]) == ONE
    assert "currency" not in body["totals"]["leads"]["items"][0]
    assert [item["currency"] for item in body["reconciliation"]["items"]] == ["EGP", "USD"]


def test_bv10_not_ready_behind_rebuild_failed_and_ledger_unavailable(aw):
    w, day = aw.w, sale_day()
    owner = aw.idw.owner
    # Before the first publication every value is null with attribution_not_ready, never 0.
    buyer = aw.person("buyer@example.test")
    aw.touch(buyer.token, "spring")
    aw.sale("S1", 10_000, when=at(day, 10))
    aw.associate(buyer.assertion, "S1")
    aw.sale("S2", 500, when=at(day, 11))  # a second slot, so a rebuild can stop half-way
    fresh = get(owner, w, "attribution", **window(day)).json()
    assert fresh["values"] == {"state": "not_ready", "reason": "attribution_not_ready"}
    assert fresh["totals"]["sales"] == {
        "state": "not_ready",
        "reason": "attribution_not_ready",
        "items": None,
    }
    assert fresh["totals"]["leads"]["items"] is None and fresh["rows"] == []
    assert fresh["reconciliation"]["state"] == "not_ready"
    assert fresh["attribution"]["published_generation"] == 0
    aw.settle()
    ready = get(owner, w, "attribution", **window(day)).json()
    assert ready["attribution"]["state"] == "caught_up"
    # Behind: served from the published generation and labeled.
    aw.touch(buyer.token, "autumn")
    behind = get(owner, w, "attribution", **window(day)).json()
    assert behind["attribution"]["state"] == "behind"
    assert credit_map(behind) == {("spring", "EGP"): (ONE, 10_000), ("unknown", "EGP"): (ONE, 500)}
    aw.settle()
    # A rebuild is invisible until it is published, then the report changes at once.
    created = owner.post(
        f"/agencies/{w.a}/clients/{w.a1}/attribution/models",
        json={"operation_id": str(uuid4()), "model": "linear", "window_days": 7},
    )
    assert created.status_code == 201, created.text
    seven = created.json()["id"]
    result = store.process_client(w.db.runtime, w.a, w.a1, budget=1)
    assert result["outcome"] == "bounded"
    staged = get(owner, w, "attribution", model_version=seven, **window(day)).json()
    assert staged["attribution"]["state"] == "rebuilding"
    assert staged["rows"] == [] and staged["totals"]["sales"]["items"] == []
    aw.settle()
    published = get(owner, w, "attribution", model_version=seven, **window(day)).json()
    assert credit_map(published) == {
        ("spring", "EGP"): (HALF, 5_000),
        ("autumn", "EGP"): (HALF, 5_000),
        ("unknown", "EGP"): (ONE, 500),
    }
    # A failed consumer is reported as failed and served from its published generation.
    _migrate(
        w,
        update(AttributionConsumerState)
        .where(AttributionConsumerState.client_id == w.a1)
        .values(
            status="failed",
            failure_code="synthetic_refusal",
            version=AttributionConsumerState.version + 1,
        ),
    )
    failed = get(owner, w, "attribution", compare="previous", **window(day)).json()
    assert failed["attribution"]["state"] == "failed"
    assert failed["attribution"]["failure_code"] == "synthetic_refusal"
    assert {item["reason"] for item in failed["comparison"]} == {"attribution_failed"}
    _migrate(
        w,
        update(AttributionConsumerState)
        .where(AttributionConsumerState.client_id == w.a1)
        .values(status="ready", failure_code=None),
    )
    # A ledger behind its evidence is reported as unavailable, never as an amount.
    _migrate(
        w,
        "INSERT INTO revenue_evidence (id, agency_id, client_id, delivery_id, source_account_id, "
        "operation_id, kind, classification, currency, currency_exponent, amount_minor, "
        "effective_at, received_at, intake, intake_id, content_digest) VALUES (:id, :agency, "
        ":client, 'unprojected:1', 'shop', 'U1', 'sale', 'confirmed_capture', 'EGP', 2, 1000, "
        "now(), now(), 'csv_import', :intake, :digest)",
        {"id": uuid4(), "agency": w.a, "client": w.a1, "intake": uuid4(), "digest": "c" * 64},
    )
    unavailable = get(owner, w, "attribution", **window(day)).json()
    assert unavailable["reconciliation"] == {
        "state": "unavailable",
        "reason": "ledger_unavailable",
        "ledger": "unavailable",
        "items": None,
    }
    assert unavailable["attribution"]["current"]["ledger"] == "unavailable"
    assert unavailable["attribution"]["state"] == "behind"


def test_bv16_pages_and_revision(aw):
    w, day = aw.w, sale_day()
    buyer = aw.person("buyer@example.test")
    codes = [f"c{index}" for index in range(7)]
    for code in codes:
        aw.touch(buyer.token, code)
    aw.sale("S1", 7_000, when=at(day, 10))
    aw.associate(buyer.assertion, "S1")
    aw.sale("S2", 1_000, when=at(day, 11))
    aw.settle()
    owner = aw.idw.owner
    whole = get(owner, w, "attribution", page_size=500, **span(day)).json()
    assert whole["page"]["total_rows"] == 8
    seen = []
    first = get(owner, w, "attribution", page_size=3, **span(day)).json()
    assert first["page"] == {"page": 1, "page_size": 3, "total_rows": 8, "total_pages": 3}
    assert first["totals"] == whole["totals"] and first["revision"] == whole["revision"]
    seen += first["rows"]
    for page in (2, 3):
        body = get(
            owner,
            w,
            "attribution",
            page_size=3,
            page=page,
            expected_revision=first["revision"],
            **span(day),
        ).json()
        assert body["revision"] == first["revision"]
        seen += body["rows"]
    assert seen == whole["rows"]
    assert len({(row["recipient"], row["group_ref"]) for row in seen}) == 8
    # A later page needs a revision, a page after the last is refused.
    refused = get(owner, w, "attribution", page_size=3, page=2, **span(day))
    assert (refused.status_code, refused.json()) == (422, {"error": "revision_required"})
    beyond = get(
        owner,
        w,
        "attribution",
        page_size=3,
        page=4,
        expected_revision=first["revision"],
        **span(day),
    )
    assert (beyond.status_code, beyond.json()) == (422, {"error": "invalid_page"})
    # A worker pass between two pages answers report_changed.
    aw.settle()
    changed = get(
        owner,
        w,
        "attribution",
        page_size=3,
        page=2,
        expected_revision=first["revision"],
        **span(day),
    )
    assert (changed.status_code, changed.json()) == (409, {"error": "report_changed"})
    # The revision is bound to the reader's finance access.
    analyst = get(w.signed_in("analyst"), w, "attribution", page_size=500, **span(day)).json()
    assert (
        analyst["revision"]
        != get(owner, w, "attribution", page_size=500, **span(day)).json()["revision"]
    )


@pytest.mark.parametrize("output", ["json", "csv"])
def test_bv17_release_race(aw, monkeypatch, output):
    w, day = aw.w, sale_day()
    buyer, _, _ = journeys(aw, day)
    owner = aw.idw.owner
    ids = versions(owner, w)
    params = {**window(day), "format": output}

    def worker_pass():
        aw.touch(buyer.token, "winter")
        aw.settle()

    def scrub():
        with Session(w.db.runtime) as session, session.begin():
            scrub_person(session, w.a, w.a1, buyer.id, "erased", now_utc())

    def default_model():
        _migrate(
            w,
            "UPDATE attribution_model_versions SET is_default = false WHERE client_id = :c",
            {"c": w.a1},
        )
        _migrate(
            w,
            "UPDATE attribution_model_versions SET is_default = true WHERE id = :v",
            {"v": ids[FIRST]},
        )

    for action in (worker_pass, scrub, default_model):
        calls = _race(monkeypatch, action)
        response = get(owner, w, "attribution", **params)
        assert calls == ["attribution"], action
        assert (response.status_code, response.json()) == (409, {"error": "report_changed"}), action
        assert "spring" not in response.text
    # A revoked finance grant refuses a body built with sale values; a revoked client grant
    # refuses everything.
    set_grant(aw, can_view_financials=True)
    analyst = w.signed_in("analyst")
    _race(
        monkeypatch,
        lambda: _migrate(
            w,
            "UPDATE client_grants SET can_view_financials = false "
            "WHERE membership_id = :m AND client_id = :c",
            {"m": w.analyst, "c": w.a1},
        ),
    )
    response = get(analyst, w, "attribution", **params)
    assert (response.status_code, response.json()) == (403, {"error": "access_denied"})
    _race(
        monkeypatch,
        lambda: _migrate(
            w,
            "DELETE FROM client_grants WHERE membership_id = :m AND client_id = :c",
            {"m": w.analyst, "c": w.a1},
        ),
    )
    response = get(analyst, w, "attribution", **params)
    assert (response.status_code, response.json()) == (403, {"error": "access_denied"})
    monkeypatch.setattr(reporting, "before_release", reporting._no_hook)
    assert get(owner, w, "attribution", **params).status_code == 200


def test_bv18_csv_equals_json_and_bounds(aw):
    w, day = aw.w, sale_day()
    buyer = aw.person("buyer@example.test")
    for code in ("%3DSUM(1)", "%2B1", "-1", "%401", "spring"):
        aw.touch(buyer.token, code)
    aw.sale("S1", 10_000, when=at(day, 10))
    aw.associate(buyer.assertion, "S1")
    aw.sale("S2", 1_000, when=at(day, 11))
    asker = aw.person("asker@example.test")
    aw.touch(asker.token, "spring")
    aw.lead(asker.token)
    aw.settle()
    owner = aw.idw.owner
    body = get(owner, w, "attribution", page_size=500, **window(day)).json()
    response = get(owner, w, "attribution", format="csv", **window(day))
    assert response.status_code == 200, response.text
    assert (
        response.headers["content-disposition"] == 'attachment; filename="report-attribution.csv"'
    )
    assert response.headers["cache-control"] == "no-store"
    cells = parse_csv(response)
    assert set(cells[0]) >= {
        "row_type",
        "group_ref",
        "model_version_id",
        "value_minor",
        "numerator",
    }
    revision = [row for row in cells if row["metric"] == "revision"][0]["object_id"]
    assert revision == f"id:{body['revision']}"
    from_csv = {}
    for row in cells:
        if row["row_type"] == "value" and row["metric"] == "credited_revenue":
            from_csv[(row["group_ref"], row["currency"])] = int(row["value_minor"])
    from_json = {
        (f"id:{row['group_ref']}" if row["group_ref"] else "", item["currency"]): item[
            "credited_revenue"
        ]["minor"]
        for row in body["rows"]
        for item in row["sales"]["items"]
    }
    assert from_csv == from_json
    refs = {row["group_ref"] for row in cells if row["group_ref"]}
    assert {"id:=SUM(1)", "id:+1", "id:-1", "id:@1", "id:spring"} <= refs
    for row in cells:
        for value in row.values():
            assert not value.startswith(("=", "+", "@")), row
            assert not (value.startswith("-") and not value[1:2].isdigit()), row
    text_ = response.text
    for forbidden in (str(buyer.id), str(asker.id), "example.test", "Synthetic", "touchpoint"):
        assert forbidden not in text_
    leads = [
        row for row in cells if row["metric"] == "credited_leads" and row["row_type"] == "value"
    ]
    assert sum(Fraction(int(row["numerator"]), int(row["denominator"])) for row in leads) == ONE
    dependencies = {
        row["metric"]: (row["status"], row["detail"])
        for row in cells
        if row["source"] == "dependencies"
    }
    assert dependencies["roas"] == ("available", "roas")


def test_reconciliation_counts_a_negative_net_as_zero(aw):
    # The worker credits a sale with max(net, 0), so the reconciliation counts a negative
    # ledger net as zero. The ledger keeps nets from falling below zero, so the stored
    # projection is set directly here to exercise the rule.
    w, day = aw.w, sale_day()
    buyer = aw.person("buyer@example.test")
    aw.touch(buyer.token, "spring")
    aw.sale("S1", 10_000, when=at(day, 10))
    aw.associate(buyer.assertion, "S1")
    aw.sale("S2", 3_000, when=at(day, 11))
    aw.settle()
    _migrate(
        w,
        "UPDATE ledger_transactions SET refunded = 12000, net = -2000 "
        "WHERE client_id = :c AND operation_id = 'S1'",
        {"c": w.a1},
    )
    body = get(aw.idw.owner, w, "attribution", **span(day)).json()
    (item,) = body["reconciliation"]["items"]
    assert (item["credited_revenue"]["minor"], item["ledger_net"]["minor"]) == (13_000, 3_000)
    assert (item["state"], item["reason"]) == ("difference", "unexplained_difference")


def test_review_r016b_02_sale_only_groups_stay_hidden_without_finance(aw):
    """A group that holds only sale credit is not listed, counted or exported for a reader
    without finance:read; its lead credit groups stay (review R016B-02)."""
    w, day = aw.w, sale_day()
    journeys(aw, day)  # autumn holds sale credit only; spring holds sale and lead credit
    full = get(aw.idw.owner, w, "attribution", **window(day)).json()
    assert ("campaign", "autumn") in {(row["recipient"], row["group_ref"]) for row in full["rows"]}
    analyst = w.signed_in("analyst")
    for view in ("groups", "models"):
        response = get(analyst, w, "attribution", view=view, **window(day))
        assert response.status_code == 200, response.text
        listed = {(row["recipient"], row["group_ref"]) for row in response.json()["rows"]}
        assert ("campaign", "spring") in listed
        assert "autumn" not in response.text
    funnel = get(analyst, w, "funnel", **window(day))
    assert funnel.status_code == 200, funnel.text
    assert "autumn" not in funnel.text
    csv_text = get(analyst, w, "attribution", format="csv", **window(day)).text
    assert "autumn" not in csv_text
