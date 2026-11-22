"""016-A reports through the real routes on disposable PostgreSQL (D-072, verification matrix).

Each case names the verification-matrix scenarios it covers. Synthetic rows are seeded with
report_support; the route clock is fixed at report_support.NOW. No provider is called.
"""

import csv
import io
import logging
from datetime import date, timedelta

import pytest
from report_support import (
    NOW,
    USD,
    ad_account,
    append,
    checkpoint,
    connection,
    evidence,
    grant,
    instagram_days,
    key_client,
    midnight,
    records,
    report_url,
    run,
    service_key,
    spend_facts,
)
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.connectors.synthetic_instagram import SyntheticInstagramProvider
from app.connectors.synthetic_youtube import pacific_start
from app.ledger import Currency, EvidenceClass, OperationKind
from app.models import (
    AgencyMembership,
    ConnectorConnection,
    ConnectorRecord,
    ServiceCredential,
)
from app.security import digest
from app.services import reporting
from app.services.access import AccessService
from app.services.tenancy import tenancy_transaction

pytestmark = pytest.mark.integration
NOV1, NOV2, NOV3 = date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)
SPAN = {"start": "2026-11-01", "end": "2026-11-03"}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr("app.api.reports.now_utc", lambda: NOW)


def _instagram(w, client=None, agency=None, **days):
    cid = connection(w, client or w.a1, "synthetic_instagram", agency)
    checkpoint(w, cid, "account", midnight(date(2026, 10, 1)), midnight(date(2026, 11, 15)))
    run(w, cid, "account")
    if days:
        instagram_days(w, cid, [NOV1, NOV2], **days)
    return cid


def _spend(w, client=None, agency=None, currency="EGP"):
    cid = connection(w, client or w.a1, "synthetic_meta_ads", agency, day_zone="Africa/Cairo")
    ad_account(w, cid, currency)
    checkpoint(w, cid, "ad_daily", midnight(date(2026, 9, 30)), midnight(date(2026, 11, 15)))
    run(w, cid, "ad_daily")
    return cid


def _social(client, w, cid, view="daily", **extra):
    query = {"connection_id": cid, "view": view, **SPAN, **extra}
    return client.get(report_url(w, "social", **query))


def _parse(response):
    assert response.headers["content-type"].startswith("text/csv")
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8"), newline="")))


# --- V01, V02: tenant scope and permissions -------------------------------------------------------


def test_v01_foreign_scopes_reveal_nothing(authenticated_world, api):
    w = authenticated_world
    mine = _instagram(w, views=[10, 12], reach=[10, 12])
    theirs = _instagram(w, client=w.a2, views=[777, 888])
    foreign = _instagram(w, client=w.b1, agency=w.b, views=[555, 666])
    spend_a2 = _spend(w, client=w.a2)
    spend_facts(w, spend_a2, [{"ad": "31", "day": NOV1, "currency": "USD", "minor": 4321}])
    append(w, [evidence(w, "9701", minor=9_999, when=midnight(NOV1), client=w.a2)])
    owner = w.signed_in("owner_a")
    good = _social(owner, w, mine)
    assert good.status_code == 200, good.text
    body = good.json()
    assert body["client_id"] == str(w.a1) and body["connection_id"] == str(mine)
    assert "777" not in good.text and "555" not in good.text
    denials = [
        _social(owner, w, theirs),
        _social(owner, w, foreign),
        owner.get(
            report_url(w, "social", client=w.b1, connection_id=foreign, view="daily", **SPAN)
        ),
        _social(owner, w, "00000000-0000-4000-8000-000000000999"),
        owner.get(report_url(w, "spend", connection_id=spend_a2, **SPAN)),
    ]
    for response in denials:
        assert (response.status_code, response.json()) == (403, {"error": "access_denied"})
    revenue = owner.get(report_url(w, "revenue", **SPAN)).json()
    assert revenue["totals"] == [] and revenue["unresolved"]["evidence_rows"] == 0
    a2 = owner.get(report_url(w, "revenue", client=w.a2, **SPAN)).json()
    assert a2["totals"][0]["net"] == {"minor": 9999, "decimal": "99.99"}
    outsider = w.signed_in("owner_b").get(report_url(w, "revenue", client=w.a2, **SPAN))
    assert outsider.status_code == 403


def test_v02_permission_matrix_for_people_and_keys(authenticated_world, api):
    w = authenticated_world
    social = _instagram(w, views=[1, 2])
    spend = _spend(w)
    spend_facts(w, spend, [{"ad": "31", "day": NOV1, "currency": "EGP", "minor": 100}])
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.grant_client(w.a, w.a2, w.viewer, can_view_financials=True)
    a2_spend = _spend(w, client=w.a2)

    def urls(client=None):
        if client == w.a2:
            return {
                "spend": report_url(w, "spend", client=w.a2, connection_id=a2_spend, **SPAN),
                "revenue": report_url(w, "revenue", client=w.a2, **SPAN),
            }
        return {
            "social": report_url(w, "social", connection_id=social, view="daily", **SPAN),
            "spend": report_url(w, "spend", connection_id=spend, **SPAN),
            "revenue": report_url(w, "revenue", **SPAN),
        }

    expected = {
        "owner_a": {"social": 200, "spend": 200, "revenue": 200},
        "admin": {"social": 200, "spend": 200, "revenue": 200},
        "analyst": {"social": 200, "spend": 403, "revenue": 403},
        "viewer": {"social": 200, "spend": 403, "revenue": 403},
        "owner_b": {"social": 403, "spend": 403, "revenue": 403},
        "outsider": {"social": 403, "spend": 403, "revenue": 403},
    }
    for name, codes in expected.items():
        client = w.signed_in(name)
        for family, url in urls().items():
            assert client.get(url).status_code == codes[family], (name, family)
    viewer = w.signed_in("viewer")
    for url in urls(w.a2).values():
        assert viewer.get(url).status_code == 200
    financial = key_client(api, service_key(w, api, [grant(w.a1, True)]))
    plain = key_client(api, service_key(w, api, [grant(w.a1)]))
    ingest = key_client(api, service_key(w, api, [grant(w.a1)], kind="ingest"))
    for family, url in urls().items():
        assert financial.get(url).status_code == 200, family
        assert plain.get(url).status_code == (200 if family == "social" else 403), family
        assert ingest.get(url).status_code == 401, family
    social_text = plain.get(urls()["social"]).text
    for word in ("spend", "currency", "revenue", "captured", "net", "exponent"):
        assert f'"{word}"' not in social_text
    expired_raw = service_key(w, api, [grant(w.a1, True)])
    revoked_raw = service_key(w, api, [grant(w.a1, True)])
    demoted_raw = service_key(w, api, [grant(w.a1, True)], actor=w.users.admin)
    clients = [key_client(api, raw) for raw in (expired_raw, revoked_raw, demoted_raw)]
    for client in clients:
        assert client.get(urls()["social"]).status_code == 200
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            update(ServiceCredential)
            .where(ServiceCredential.token_digest == digest(expired_raw))
            .values(expires_at=NOW - timedelta(days=1))
        )
        revoked_id = session.scalar(
            select(ServiceCredential.id).where(
                ServiceCredential.token_digest == digest(revoked_raw)
            )
        )
    with Session(w.db.runtime) as session, session.begin():
        AccessService(session, w.users.owner_a, api.config).revoke_service_key(w.a, revoked_id)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_member(w.a, w.admin, status="disabled")
    for client in clients:
        for url in urls().values():
            response = client.get(url)
            assert (response.status_code, response.json()) == (
                401,
                {"error": "authentication_required"},
            )


# --- V03: final authorization and source checks ---------------------------------------------------


def _race(monkeypatch, action):
    calls = []

    def hook(family):
        calls.append(family)
        action()

    monkeypatch.setattr(reporting, "before_release", hook)
    return calls


@pytest.mark.parametrize("output", ["json", "csv"])
def test_v03_revocation_before_release_sends_no_report(
    authenticated_world, api, monkeypatch, output
):
    w = authenticated_world
    cid = _instagram(w, views=[41_234, 42_345])
    spend = _spend(w)
    spend_facts(w, spend, [{"ad": "31", "day": NOV1, "currency": "EGP", "minor": 98_765}])
    append(w, [evidence(w, "9801", minor=87_654, when=midnight(NOV1))])
    analyst = w.signed_in("analyst")
    url = report_url(w, "social", connection_id=cid, view="daily", format=output, **SPAN)
    calls = _race(
        monkeypatch,
        lambda: _with_owner(w, lambda s: s.revoke_client(w.a, w.a1, w.analyst)),
    )
    response = analyst.get(url)
    assert calls == ["social"]
    assert (response.status_code, response.json()) == (403, {"error": "access_denied"})
    assert "41234" not in response.text and "41,234" not in response.text
    # A read key revoked between calculation and release, for each financial family.
    for family, query in (("spend", {"connection_id": spend}), ("revenue", {})):
        raw = service_key(w, api, [grant(w.a1, True)])
        calls = _race(monkeypatch, lambda raw=raw: _revoke_key(w, api, raw))
        response = key_client(api, raw).get(report_url(w, family, format=output, **query, **SPAN))
        assert calls == [family]
        assert (response.status_code, response.json()) == (
            401,
            {"error": "authentication_required"},
        )
        assert "987.65" not in response.text and "876.54" not in response.text
    # The client archived between calculation and release.
    owner = w.signed_in("owner_a")
    _race(
        monkeypatch, lambda: _with_owner(w, lambda s: s.update_client(w.a, w.a1, status="archived"))
    )
    response = owner.get(report_url(w, "revenue", format=output, **SPAN))
    assert (response.status_code, response.json()) == (403, {"error": "access_denied"})


def _with_owner(w, action):
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        action(service)


def _revoke_key(w, api, raw):
    with Session(w.db.runtime) as session, session.begin():
        identifier = session.scalar(
            select(ServiceCredential.id).where(ServiceCredential.token_digest == digest(raw))
        )
        AccessService(session, w.users.owner_a, api.config).revoke_service_key(w.a, identifier)


@pytest.mark.parametrize("output", ["json", "csv"])
def test_v03_source_changes_before_release_refuse_the_report(
    authenticated_world, monkeypatch, output
):
    w = authenticated_world
    cid = _instagram(w, views=[10, 12])
    owner = w.signed_in("owner_a")
    url = report_url(w, "social", connection_id=cid, view="daily", format=output, **SPAN)

    def migrate(statement):
        with Session(w.db.migration) as session, session.begin():
            session.execute(statement)

    for statement, code in (
        (
            update(ConnectorConnection)
            .where(ConnectorConnection.id == cid)
            .values(generation=ConnectorConnection.generation + 1),
            "report_changed",
        ),
        (
            update(ConnectorRecord)
            .where(ConnectorRecord.connection_id == cid)
            .values(metrics={"views": 99}),
            "report_changed",
        ),
        (delete(ConnectorRecord).where(ConnectorRecord.connection_id == cid), "report_changed"),
        (
            update(ConnectorConnection)
            .where(ConnectorConnection.id == cid)
            .values(
                status="disconnecting",
                disconnect_requested_at=NOW,
                purge_due_at=NOW + timedelta(days=1),
                revocation_status="pending",
                destruction_status="pending",
                purge_status="pending",
            ),
            "source_unavailable",
        ),
    ):
        _race(monkeypatch, lambda statement=statement: migrate(statement))
        response = owner.get(url)
        assert (response.status_code, response.json()) == (409, {"error": code})
    monkeypatch.setattr(reporting, "before_release", reporting._no_hook)
    assert owner.get(url).json() == {"error": "source_unavailable"}
    append(w, [evidence(w, "9901", when=midnight(NOV1))])
    _race(monkeypatch, lambda: append(w, [evidence(w, "9902", when=midnight(NOV2))]))
    response = owner.get(report_url(w, "revenue", format=output, **SPAN))
    assert (response.status_code, response.json()) == (409, {"error": "report_changed"})


# --- V04, V05, V08: metric semantics and source states --------------------------------------------


def test_v04_v08_daily_semantics_and_independent_stream_states(authenticated_world, tmp_path):
    w = authenticated_world
    cid = _instagram(w, views=[10, 12], reach=[10, 12], likes=[1, 2])
    records(
        w,
        cid,
        [
            {
                "stream": "media",
                "object_id": "9001",
                "observed_at": midnight(NOV1) + timedelta(hours=9),
                "product_type": "FEED",
                "metrics": {"views": 50},
            }
        ],
    )
    owner = w.signed_in("owner_a")
    body = _social(owner, w, cid).json()
    totals = {item["metric"]: item for item in body["totals"]}
    assert (totals["views"]["value"], totals["views"]["status"]) == (22, "complete")
    assert totals["reach"]["value"] is None and totals["reach"]["reason"] == "non_additive"
    assert [row["value"] for row in body["rows"] if row["metric"] == "reach"] == [10, 12]
    assert totals["comments"]["value"] is None and totals["comments"]["reason"] == "missing"
    stream = body["source_status"]["streams"][0]
    assert stream["coverage"]["current"] == "complete" and stream["freshness"]["state"] == "fresh"
    assert body["source_status"]["adapter_state"] == "unavailable"
    assert body["source_status"]["connection_last_successful_sync_at"] is not None
    # The account stream's success says nothing about the media stream.
    cohort = _social(owner, w, cid, view="content_cohort").json()
    media = next(item for item in cohort["source_status"]["streams"] if item["stream"] == "media")
    assert media["coverage"]["current"] == "not_synced"
    assert media["freshness"]["state"] == "never_synced"
    views = next(i for i in cohort["totals"] if i["stream"] == "media" and i["metric"] == "views")
    assert (views["value"], views["status"], views["reason"]) == (
        50,
        "partial",
        "inventory_unproven",
    )
    assert cohort["basis"] == "published_cohort_lifetime"
    # A registered adapter, a stale stream and a read between pages are labeled separately.
    owner.app.state.connector_providers = {
        "synthetic_instagram": SyntheticInstagramProvider(tmp_path / "ig.sqlite3")
    }
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            text("UPDATE connector_sync_runs SET finished_at = :old WHERE connection_id = :id"),
            {"old": NOW - timedelta(days=3), "id": cid},
        )
        session.execute(
            text("UPDATE connector_checkpoints SET cursor = 'next' WHERE connection_id = :id"),
            {"id": cid},
        )
    body = _social(owner, w, cid, compare="previous").json()
    assert body["source_status"]["adapter_state"] == "available"
    stream = body["source_status"]["streams"][0]
    assert stream["freshness"]["state"] == "stale" and stream["sync"]["in_progress"] is True
    views = next(item for item in body["comparison"] if item["metric"] == "views")
    assert views["comparable"] is False and views["reason"] == "unavailable"


def test_v05_v08_youtube_cohort_and_unknown_combinations(authenticated_world):
    w = authenticated_world
    cid = connection(w, w.a1, "synthetic_youtube")
    for stream in ("videos", "video_totals", "channel_daily"):
        checkpoint(w, cid, stream, NOW - timedelta(days=40), NOW - timedelta(days=3))
        run(w, cid, stream)
    published = pacific_start(NOV1) + timedelta(hours=3)
    records(
        w,
        cid,
        [
            {
                "stream": "videos",
                "object_id": "-vid=1",
                "observed_at": NOW,
                "metrics": {"viewCount": 5},
                "attributes": {"published_at": published.isoformat(), "title": "Leak title"},
            },
            {
                "stream": "videos",
                "object_id": "vid2",
                "observed_at": NOW,
                "attributes": {"privacy_status": "public"},
            },
            {
                "stream": "video_totals",
                "object_id": "-vid=1",
                "observed_at": pacific_start(date(2026, 11, 14)),
                "product_type": "SHORTS",
                "metrics": {"views": 1000, "averageViewDuration": 61},
            },
            {
                "stream": "channel",
                "object_id": "snapshot",
                "observed_at": NOW,
                "metrics": {"subscriberCount": 12300},
            },
        ],
    )
    owner = w.signed_in("owner_a")
    response = _social(owner, w, cid, view="content_cohort")
    body = response.json()
    assert body["day_zone"] == "America/Los_Angeles"
    assert body["source_status"]["publication_unknown"] == 1
    views = next(item for item in body["totals"] if item["metric"] == "views")
    assert (views["value"], views["status"], views["reason"]) == (
        1000,
        "partial",
        "inventory_unproven",
    )
    duration = next(item for item in body["totals"] if item["metric"] == "averageViewDuration")
    assert duration["value"] is None and duration["reason"] == "non_additive"
    assert "Leak title" not in response.text and "12300" not in response.text
    excluded = {
        (item["stream"], item["metric"]) for item in body["source_status"]["excluded_metrics"]
    }
    assert ("videos", "viewCount") in excluded
    daily = _social(owner, w, cid, metrics="subscriberCount")
    assert (daily.status_code, daily.json()) == (422, {"error": "unsupported_metric"})
    generic = connection(w, w.a1, "synthetic")
    response = _social(owner, w, generic)
    assert (response.status_code, response.json()) == (422, {"error": "not_a_social_connection"})
    compare = _social(owner, w, cid, view="content_cohort", compare="previous")
    assert (compare.status_code, compare.json()) == (422, {"error": "comparison_unsupported"})


# --- V06, V07: dates, zones and comparisons -------------------------------------------------------


def test_v06_native_day_boundaries_and_rejected_periods(authenticated_world):
    w = authenticated_world
    cid = _instagram(w)
    records(
        w,
        cid,
        [
            {
                "stream": "account",
                "object_id": "a",
                "observed_at": midnight(NOV1),
                "metrics": {"views": 1},
            },
            {
                "stream": "account",
                "object_id": "b",
                "observed_at": midnight(NOV2),
                "metrics": {"views": 2},
            },
            {
                "stream": "account",
                "object_id": "c",
                "observed_at": midnight(NOV3),
                "metrics": {"views": 400},
            },
        ],
    )
    owner = w.signed_in("owner_a")
    views = next(
        item for item in _social(owner, w, cid).json()["totals"] if item["metric"] == "views"
    )
    assert views["value"] == 3
    youtube = connection(w, w.a1, "synthetic_youtube")
    checkpoint(w, youtube, "channel_daily", pacific_start(date(2026, 10, 1)), pacific_start(NOV3))
    run(w, youtube, "channel_daily")
    records(
        w,
        youtube,
        [
            {
                "stream": "channel_daily",
                "object_id": f"day-{day}",
                "observed_at": pacific_start(day),
                "metrics": {"views": value},
            }
            for day, value in ((date(2026, 10, 31), 900), (NOV1, 10), (NOV2, 20))
        ],
    )
    body = owner.get(
        report_url(w, "social", connection_id=youtube, view="daily", metrics="views", **SPAN)
    ).json()
    assert [row["value"] for row in body["rows"]] == [10, 20]
    assert body["totals"][0]["value"] == 30 and body["totals"][0]["status"] == "complete"
    spend = _spend(w)
    spend_facts(
        w,
        spend,
        [
            {"ad": "31", "day": date(2026, 10, 31), "currency": "EGP", "minor": 5000},
            {"ad": "31", "day": NOV1, "currency": "EGP", "minor": 100},
            {"ad": "31", "day": NOV2, "currency": "EGP", "minor": 200},
            {"ad": "31", "day": NOV3, "currency": "EGP", "minor": 7000},
        ],
    )
    body = owner.get(report_url(w, "spend", connection_id=spend, **SPAN)).json()
    assert body["totals"][0]["spend"] == {"minor": 300, "decimal": "3.00"}
    assert body["day_zone"] == "Africa/Cairo"
    for query, code in (
        ({"start": "2026-11-03", "end": "2026-11-01"}, "invalid_period"),
        ({"start": "2026-11-01", "end": "2026-11-01"}, "invalid_period"),
        ({"start": "2026-11-01", "end": "2026-12-03"}, "invalid_period"),
        ({"start": "2026-11-01", "end": "2026-11-03", "tz": "Asia/Tokyo"}, "unknown_parameter"),
        ({"start": "2026-11-01", "end": "2026-11-03", "as_of": "2026-01-01"}, "unknown_parameter"),
    ):
        response = owner.get(report_url(w, "revenue", **query))
        assert (response.status_code, response.json()) == (422, {"error": code}), query
    repeated = owner.get(
        f"/agencies/{w.a}/clients/{w.a1}/reports/revenue?start=2026-11-01&end=2026-11-03&end=2026-11-04"
    )
    assert repeated.json() == {"error": "unknown_parameter"}
    zoneless = connection(w, w.a1, "synthetic_meta_ads")
    body = owner.get(report_url(w, "spend", connection_id=zoneless, **SPAN)).json()
    assert body["day_zone"] is None and body["totals"] == []
    assert body["source_status"]["periods"][0]["coverage"] == "not_synced"


def test_v07_previous_period_comparisons(authenticated_world):
    w = authenticated_world
    cid = _instagram(w)
    instagram_days(
        w,
        cid,
        [date(2026, 10, 30), date(2026, 10, 31), NOV1, NOV2],
        views=[10, 10, 15, 15],
        likes=[0, 0, 1, 1],
    )
    owner = w.signed_in("owner_a")
    body = _social(owner, w, cid, compare="previous").json()
    assert body["comparison_period"] == {"start": "2026-10-30", "end": "2026-11-01", "days": 2}
    by_metric = {item["metric"]: item for item in body["comparison"]}
    assert (by_metric["views"]["difference"], by_metric["views"]["percent_change"]) == (10, "50.00")
    assert by_metric["likes"]["reason"] == "zero_baseline"
    assert by_metric["likes"]["percent_change"] is None
    assert by_metric["reach"]["reason"] == "non_additive"


# --- V09-V11: revenue and spend money -------------------------------------------------------------


def test_v09_refund_activity_with_the_sale_outside_the_period(authenticated_world):
    w = authenticated_world
    append(
        w,
        [
            evidence(w, "1001", minor=10_000, when=midnight(date(2026, 1, 15))),
            evidence(
                w,
                "1002",
                OperationKind.REFUND,
                2_000,
                when=midnight(date(2026, 2, 10)),
                parent="1001",
            ),
        ],
    )
    owner = w.signed_in("owner_a")
    february = owner.get(report_url(w, "revenue", start="2026-02-01", end="2026-03-01")).json()
    verified = february["totals"][0]
    assert verified["net"] == {"minor": -2000, "decimal": "-20.00"}
    assert verified["captured"]["minor"] == 0 and verified["postings"] == 1
    assert [(row["kind"], row["amount"]["minor"]) for row in february["rows"]] == [
        ("refund", -2000)
    ]
    january = owner.get(report_url(w, "revenue", start="2026-01-01", end="2026-02-01")).json()
    assert january["totals"][0]["net"]["minor"] == 10_000
    assert january["basis"] == "posting_effective_time" and january["day_zone"] == "UTC"


def test_v10_duplicates_declarations_pending_and_held_refunds(authenticated_world, api):
    w = authenticated_world
    sale = evidence(w, "2001", minor=10_000, when=midnight(NOV1))
    append(w, [sale, sale])
    append(
        w,
        [
            evidence(
                w,
                "2002",
                minor=5_000,
                when=midnight(NOV1),
                classification=EvidenceClass.MANUAL_DECLARATION,
                reason="Synthetic private reason",
            )
        ],
        intake="manual_entry",
    )
    append(
        w,
        [
            evidence(w, "2003", OperationKind.REFUND, 100, when=midnight(NOV2), parent="missing"),
            evidence(
                w,
                "2004",
                OperationKind.REFUND,
                300,
                when=midnight(NOV2),
                parent="2001",
                order="999",
            ),
        ],
    )
    owner = w.signed_in("owner_a")
    response = owner.get(report_url(w, "revenue", **SPAN))
    body = response.json()
    verified = next(item for item in body["totals"] if item["block"] == "verified")
    assert verified["captured"]["minor"] == 10_000 and verified["refunded"]["minor"] == 0
    declared = next(item for item in body["totals"] if item["block"] == "declared")
    assert declared["sales"]["minor"] == 5_000
    unresolved = body["unresolved"]
    assert unresolved["pending_reasons"] == {"parent_missing": 1, "parent_order_mismatch": 1}
    assert unresolved["held"] == 1 and unresolved["evidence_rows"] == 4
    assert unresolved["scope"] == "all_evidence"
    for secret in ("Synthetic private reason", "2001", "paymob", "synthetic:"):
        assert secret not in response.text
    csv_response = owner.get(report_url(w, "revenue", format="csv", **SPAN))
    assert "Synthetic private reason" not in csv_response.text and "paymob" not in csv_response.text


def test_v11_currencies_stay_apart_and_exponent_conflicts_fail(authenticated_world):
    w = authenticated_world
    spend = _spend(w)
    spend_facts(
        w,
        spend,
        [
            {"ad": "31", "adset": "21", "day": NOV1, "currency": "EGP", "minor": 1000},
            {"ad": "31", "adset": "21", "day": NOV2, "currency": "USD", "minor": 250},
            {"ad": "32", "day": NOV1, "currency": "EGP", "minor": 500},
        ],
    )
    owner = w.signed_in("owner_a")
    seen, revision = [], None
    for page in (1, 2, 3):
        body = owner.get(
            report_url(
                w,
                "spend",
                connection_id=spend,
                level="adset",
                page=page,
                page_size=1,
                expected_revision=revision,
                **SPAN,
            )
        ).json()
        revision = body["revision"]
        seen += [(row["object_id"], row["currency"]) for row in body["rows"]]
        assert body["page"]["total_rows"] == 3
    assert seen == [(None, "EGP"), ("21", "EGP"), ("21", "USD")]
    assert {item["currency"] for item in body["totals"]} == {"EGP", "USD"}
    append(
        w,
        [
            evidence(w, "3001", minor=100, when=midnight(NOV1)),
            evidence(w, "3002", minor=200, when=midnight(NOV1), currency=USD),
        ],
    )
    revenue = owner.get(report_url(w, "revenue", **SPAN)).json()
    assert [item["currency"] for item in revenue["totals"]] == ["EGP", "USD"]
    assert revenue["unresolved"]["external_completeness"] == "unknown"
    append(w, [evidence(w, "3003", minor=100, when=midnight(NOV1), currency=Currency("EGP", 3))])
    conflict = owner.get(report_url(w, "revenue", **SPAN))
    assert (conflict.status_code, conflict.json()) == (409, {"error": "currency_exponent_conflict"})


# --- V12, V13: pagination and revisions -----------------------------------------------------------


def _media_items(count, day=NOV1, prefix="m"):
    return [
        {
            "stream": "media",
            "object_id": f"{prefix}{index:05d}",
            "observed_at": midnight(day) + timedelta(minutes=index % 1000),
            "product_type": "FEED" if index % 2 else "REELS",
            "metrics": {"views": index, "likes": 1},
        }
        for index in range(count)
    ]


def test_v12_complete_totals_deterministic_pages_and_revisions(authenticated_world):
    w = authenticated_world
    cid = _instagram(w)
    checkpoint(w, cid, "media", midnight(date(2026, 1, 1)), midnight(date(2026, 11, 19)))
    records(w, cid, _media_items(60))
    owner = w.signed_in("owner_a")
    first = _social(owner, w, cid, view="content_cohort", page_size=500).json()
    total = first["page"]["total_rows"]
    assert total > 500 and first["page"]["total_pages"] == 2
    keys, revision = [], first["revision"]
    for size in (500, 7):
        pages = -(-total // size)
        seen = []
        for page in range(1, pages + 1):
            body = _social(
                owner,
                w,
                cid,
                view="content_cohort",
                page=page,
                page_size=size,
                expected_revision=revision,
            ).json()
            assert body["revision"] == revision and body["totals"] == first["totals"]
            seen += [(row["stream"], row["content_id"], row["metric"]) for row in body["rows"]]
        assert len(seen) == total == len(set(seen)) and seen == sorted(seen)
        keys.append(seen)
    assert keys[0] == keys[1]
    views = next(i for i in first["totals"] if i["stream"] == "media" and i["metric"] == "views")
    assert views["value"] == sum(range(60))
    missing = _social(owner, w, cid, view="content_cohort", page=2)
    assert (missing.status_code, missing.json()) == (422, {"error": "revision_required"})
    wrong = _social(owner, w, cid, view="content_cohort", page=2, expected_revision="0" * 64)
    assert (wrong.status_code, wrong.json()) == (409, {"error": "report_changed"})
    beyond = _social(
        owner, w, cid, view="content_cohort", page=3, page_size=500, expected_revision=revision
    )
    assert (beyond.status_code, beyond.json()) == (422, {"error": "invalid_page"})
    admin = _social(w.signed_in("admin"), w, cid, view="content_cohort").json()
    assert admin["revision"] != revision and admin["totals"] == first["totals"]
    filtered = _social(owner, w, cid, view="content_cohort", metrics="views").json()
    assert filtered["revision"] != revision
    csv_body = _social(
        owner, w, cid, view="content_cohort", format="csv", expected_revision=revision
    )
    assert csv_body.status_code == 200


def test_v13_changed_inputs_never_mix_revisions(authenticated_world):
    w = authenticated_world
    cid = _instagram(w)
    checkpoint(w, cid, "media", midnight(date(2026, 1, 1)), midnight(date(2026, 11, 19)))
    records(w, cid, _media_items(30))
    owner = w.signed_in("owner_a")
    first = _social(owner, w, cid, view="content_cohort", page_size=50).json()
    revision = first["revision"]

    def changed():
        response = _social(
            owner, w, cid, view="content_cohort", page=2, page_size=50, expected_revision=revision
        )
        return response.status_code, response.json()

    with Session(w.db.migration) as session, session.begin():
        session.execute(
            update(ConnectorRecord)
            .where(ConnectorRecord.provider_object_id == "m00003")
            .values(metrics={"views": 3000, "likes": 1})
        )
    assert changed() == (409, {"error": "report_changed"})
    current = _social(owner, w, cid, view="content_cohort", page_size=50).json()
    views = next(i for i in current["totals"] if i["stream"] == "media" and i["metric"] == "views")
    assert views["value"] == sum(range(30)) - 3 + 3000
    revision = current["revision"]
    records(w, cid, _media_items(1, prefix="new"))
    assert changed() == (409, {"error": "report_changed"})
    revision = _social(owner, w, cid, view="content_cohort").json()["revision"]
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            delete(ConnectorRecord).where(ConnectorRecord.provider_object_id == "new00000")
        )
    assert changed() == (409, {"error": "report_changed"})
    # A previous-period fact is part of the revision of a compared report.
    daily = _instagram(w, client=w.a1)
    instagram_days(w, daily, [date(2026, 10, 30), NOV1], views=[5, 6])
    before = _social(owner, w, daily, compare="previous").json()["revision"]
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            update(ConnectorRecord)
            .where(ConnectorRecord.provider_object_id == "day-2026-10-30")
            .values(metrics={"views": 50})
        )
    after = _social(owner, w, daily, compare="previous").json()
    assert after["revision"] != before
    assert (
        next(i for i in after["totals"] if i["metric"] == "views" and i["period"] == "previous")[
            "value"
        ]
        == 50
    )


# --- V15, V16: CSV --------------------------------------------------------------------------------


def test_v15_csv_matches_json_under_one_revision(authenticated_world):
    w = authenticated_world
    cid = _instagram(w, views=[10, 12], reach=[3, 4])
    owner = w.signed_in("owner_a")
    body = _social(owner, w, cid, compare="previous").json()
    response = _social(
        owner, w, cid, compare="previous", format="csv", expected_revision=body["revision"]
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="report-social.csv"'
    assert response.headers["cache-control"] == "no-store"
    rows = _parse(response)
    assert (
        next(row for row in rows if row["metric"] == "revision")["object_id"]
        == "id:" + body["revision"]
    )
    totals = [row for row in rows if row["row_type"] == "total"]
    assert len(totals) == len(body["totals"])
    views = next(row for row in totals if row["metric"] == "views" and row["period"] == "current")
    assert (views["value"], views["status"], views["available_count"]) == ("22", "complete", "2")
    values = [row for row in rows if row["row_type"] == "value"]
    assert len(values) == body["page"]["total_rows"]
    comparisons = [row for row in rows if row["row_type"] == "comparison"]
    assert len(comparisons) == len(body["comparison"])
    assert {row["family"] for row in rows} == {"social"}
    paged = _social(owner, w, cid, format="csv", page=1)
    assert (paged.status_code, paged.json()) == (422, {"error": "csv_pagination_unsupported"})
    sized = _social(owner, w, cid, format="csv", page_size=10)
    assert sized.json() == {"error": "csv_pagination_unsupported"}
    stale = _social(owner, w, cid, format="csv", expected_revision="1" * 64)
    assert (stale.status_code, stale.json()) == (409, {"error": "report_changed"})


HOSTILE = ["=1+2", "+SUM(A1)", "-2+3", "@cmd", "a,b;c", "line\r\nbreak", "\uff1dwide"]


def test_v16_csv_cells_are_typed_and_carry_no_private_text(authenticated_world, caplog):
    w = authenticated_world
    cid = _instagram(w)
    checkpoint(w, cid, "media", midnight(date(2026, 1, 1)), midnight(date(2026, 11, 19)))
    records(
        w,
        cid,
        [
            {
                "stream": "media",
                "object_id": identifier,
                "observed_at": midnight(NOV1) + timedelta(hours=index),
                "product_type": "FEED",
                "metrics": {"views": index + 1},
            }
            for index, identifier in enumerate(HOSTILE)
        ],
    )
    owner = w.signed_in("owner_a")
    with caplog.at_level(logging.DEBUG):
        response = _social(owner, w, cid, view="content_cohort", format="csv")
    assert response.status_code == 200
    rows = _parse(response)
    identifiers = {row["object_id"] for row in rows if row["row_type"] == "value"}
    assert identifiers == {f"id:{item}" for item in HOSTILE}
    for row in rows:
        for column, value in row.items():
            if column not in {
                "value",
                "value_minor",
                "current_value",
                "previous_value",
                "percent_change",
            }:
                assert value[:1] not in {"=", "+", "-", "@", "\t", "\r"}, (column, value)
    for text_value in ("Synthetic label", "syn-", "Synthetic Client"):
        assert text_value not in response.text
    for record in caplog.records:
        message = record.getMessage()
        assert "=1+2" not in message and "Synthetic label" not in message
    append(
        w,
        [
            evidence(w, "4001", OperationKind.SALE, 1000, when=midnight(NOV1)),
            evidence(w, "4002", OperationKind.REFUND, 2500, when=midnight(NOV2), parent="4001"),
        ],
    )
    revenue = _parse(owner.get(report_url(w, "revenue", format="csv", **SPAN)))
    refunds = [row for row in revenue if row["row_type"] == "value" and row["metric"] == "refund"]
    assert refunds == []
    totals = {row["metric"]: row for row in revenue if row["row_type"] == "total"}
    assert totals["net"]["value"] == "10.00"


# --- V17, V19: no storage, no attribution substitutes ---------------------------------------------


def test_v17_v19_no_storage_and_dependency_states(authenticated_world):
    w = authenticated_world
    with Session(w.db.migration) as session:
        before = set(
            session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
    cid = _instagram(w, views=[1, 2])
    spend = _spend(w)
    owner = w.signed_in("owner_a")
    responses = [
        _social(owner, w, cid),
        owner.get(report_url(w, "spend", connection_id=spend, **SPAN)),
        owner.get(report_url(w, "revenue", **SPAN)),
        owner.get(report_url(w, "revenue", format="csv", **SPAN)),
    ]
    for response in responses:
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    for response in responses[:3]:
        dependencies = {
            item["capability"]: item["state"] for item in response.json()["dependencies"]
        }
        assert dependencies == {
            "attribution": "dependency_unavailable",
            "content_revenue": "dependency_unavailable",
            "funnels": "dependency_unavailable",
            "roas": "dependency_unavailable",
        }
        assert '"roas":' not in response.text.replace('"capability":"roas"', "")
    status = [row for row in _parse(responses[3]) if row["source"] == "dependencies"]
    assert {row["status"] for row in status} == {"dependency_unavailable"}
    with Session(w.db.migration) as session:
        after = set(
            session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
        memberships = session.scalar(select(AgencyMembership.id).limit(1))
    assert before == after and memberships is not None


def test_v19_current_crm_and_booking_state_never_becomes_revenue(authenticated_world):
    w = authenticated_world
    with Session(w.db.migration) as session:
        tables = set(
            session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
    assert {"crm_deals", "bookings"} <= tables
    owner = w.signed_in("owner_a")
    body = owner.get(report_url(w, "revenue", **SPAN)).json()
    assert body["totals"] == [] and body["rows"] == []
    assert "funnel" not in str({key: value for key, value in body.items() if key != "dependencies"})
