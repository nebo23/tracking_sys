"""016-A development bounds and measurements on disposable PostgreSQL (D-072 D8; V14, V15, V18).

Each accepted bound and the first value beyond it run through the real route. Every request
records its elapsed time, its response size and the number of SQL statements the application
engine executed; with REPORT_MEASUREMENTS set to a file path, the observations are appended
there as JSON lines for the implementation evidence. The time assertion is a generous agreed
test timeout, not a service objective; the statement count shows that queries do not grow with
the number of rows.
"""

import csv
import io
import json
import os
import time
from datetime import date, timedelta
from uuid import uuid4

import pytest
from report_support import (
    NOW,
    ad_account,
    append,
    checkpoint,
    connection,
    evidence,
    midnight,
    report_url,
    run,
)
from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from app.models import AdSpendFact, ConnectorConnection, ConnectorRecord

pytestmark = pytest.mark.integration
TIMEOUT_SECONDS = 120
MAX_STATEMENTS = 60
NOVEMBER = {"start": "2026-11-01", "end": "2026-12-02"}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr("app.api.reports.now_utc", lambda: NOW)


def _measure(client, url, label):
    statements = []

    def count(*_args, **_kwargs):
        statements.append(1)

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        started = time.perf_counter()
        response = client.get(url)
        elapsed = time.perf_counter() - started
    finally:
        event.remove(engine, "before_cursor_execute", count)
    observation = {
        "case": label,
        "status": response.status_code,
        "seconds": round(elapsed, 3),
        "bytes": len(response.content),
        "statements": len(statements),
    }
    target = os.environ.get("REPORT_MEASUREMENTS")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(observation) + "\n")
    print(json.dumps(observation))
    assert elapsed < TIMEOUT_SECONDS
    assert len(statements) <= MAX_STATEMENTS
    return response


def _scope(w, connection_id):
    with Session(w.db.migration) as session:
        row = session.get(ConnectorConnection, connection_id)
        return row.agency_id, row.client_id, row.generation


def _media_rows(w, connection_id, count, start=0):
    agency, client, generation = _scope(w, connection_id)
    base = midnight(date(2026, 11, 1))
    return [
        {
            "id": uuid4(),
            "agency_id": agency,
            "client_id": client,
            "connection_id": connection_id,
            "connection_generation": generation,
            "stream": "media",
            "provider_object_id": f"{index:08d}",
            "observed_at": base + timedelta(minutes=index * 4),
            "fetched_at": NOW - timedelta(hours=1),
            "metrics": {"views": index % 97, "likes": 1},
            "unavailable": {},
            "product_type": "FEED" if index % 2 else "REELS",
            "attributes": {},
        }
        for index in range(start, start + count)
    ]


def _bulk(w, model, rows):
    with Session(w.db.migration) as session, session.begin():
        for offset in range(0, len(rows), 2000):
            session.execute(insert(model), rows[offset : offset + 2000])


def test_v14_v18_social_bound_is_exact(authenticated_world):
    w = authenticated_world
    cid = connection(w, w.a1, "synthetic_instagram")
    checkpoint(w, cid, "media", midnight(date(2026, 1, 1)), midnight(date(2026, 12, 3)))
    run(w, cid, "media")
    _bulk(w, ConnectorRecord, _media_rows(w, cid, 10_000))
    owner = w.signed_in("owner_a")
    url = report_url(w, "social", connection_id=cid, view="content_cohort", **NOVEMBER)
    accepted = _measure(owner, url, "social_cohort_10000_rows")
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["source_status"]["source_rows"] == 10_000
    views = next(i for i in body["totals"] if i["stream"] == "media" and i["metric"] == "views")
    assert views["value"] == sum(index % 97 for index in range(10_000))
    assert views["status"] == "complete"
    last = _measure(
        owner,
        report_url(
            w,
            "social",
            connection_id=cid,
            view="content_cohort",
            page=-(-body["page"]["total_rows"] // 500),
            page_size=500,
            expected_revision=body["revision"],
            **NOVEMBER,
        ),
        "social_cohort_10000_rows_last_page",
    )
    assert last.status_code == 200 and last.json()["rows"]
    _bulk(w, ConnectorRecord, _media_rows(w, cid, 1, start=10_000))
    refused = _measure(owner, url, "social_cohort_10001_rows")
    assert (refused.status_code, refused.json()) == (422, {"error": "report_too_large"})


def _spend_rows(w, connection_id, days, ads, refused_every=0, start_ad=0):
    agency, client, _ = _scope(w, connection_id)
    rows = []
    for day in days:
        for index in range(start_ad, start_ad + ads):
            refused = refused_every and index % refused_every == 0
            rows.append(
                {
                    "id": uuid4(),
                    "agency_id": agency,
                    "client_id": client,
                    "connection_id": connection_id,
                    "ad_id": str(100000 + index),
                    "adset_id": str(200 + index % 7),
                    "campaign_id": "300",
                    "spend_date": day,
                    "time_zone": "Africa/Cairo",
                    "currency": None if refused else "EGP",
                    "spend_minor": None if refused else 100 + index,
                    "impressions": 10,
                    "clicks": 1,
                    "refusal": "unparseable_amount" if refused else None,
                    "provisional_until": NOW - timedelta(days=1),
                }
            )
    return rows


def _spend_connection(w):
    cid = connection(w, w.a1, "synthetic_meta_ads", day_zone="Africa/Cairo")
    ad_account(w, cid)
    checkpoint(w, cid, "ad_daily", midnight(date(2026, 9, 1)), midnight(date(2026, 12, 3)))
    run(w, cid, "ad_daily")
    return cid


def test_v14_v18_spend_bound_counts_refused_rows_and_both_periods(authenticated_world):
    w = authenticated_world
    cid = _spend_connection(w)
    days = [date(2026, 11, 1) + timedelta(days=offset) for offset in range(25)]
    _bulk(w, AdSpendFact, _spend_rows(w, cid, days, 400, refused_every=10)[:9_999])
    _bulk(w, AdSpendFact, _spend_rows(w, cid, [date(2026, 10, 15)], 1, start_ad=900))
    owner = w.signed_in("owner_a")
    current = report_url(w, "spend", connection_id=cid, **NOVEMBER)
    compared = report_url(w, "spend", connection_id=cid, compare="previous", **NOVEMBER)
    response = _measure(owner, current, "spend_9999_current_rows")
    assert response.status_code == 200
    period = response.json()["source_status"]["periods"][0]
    assert period["facts"] == 9_999 and period["refused"]["unparseable_amount"] == 1_000
    response = _measure(owner, compared, "spend_10000_rows_both_periods")
    assert response.status_code == 200
    assert response.json()["source_status"]["source_rows"] == 10_000
    _bulk(w, AdSpendFact, _spend_rows(w, cid, [date(2026, 10, 16)], 1, start_ad=901))
    refused = _measure(owner, compared, "spend_10001_rows_both_periods")
    assert (refused.status_code, refused.json()) == (422, {"error": "report_too_large"})
    assert owner.get(current).status_code == 200


def test_v14_v18_revenue_bound_counts_the_whole_client(authenticated_world, monkeypatch):
    w = authenticated_world

    def forbidden(*_args, **_kwargs):
        raise AssertionError("The prefix journal must not be evaluated for reports.")

    # 007-B: reads use the stored journal; neither the prefix journal nor the prefix
    # calculation may run for a report.
    monkeypatch.setattr("app.attribution.engine.ledger_feed", forbidden)
    monkeypatch.setattr("app.ledger.calculation.calculate", forbidden)
    monkeypatch.setattr("app.ledger.calculate", forbidden)
    october = midnight(date(2026, 10, 1))
    append(
        w,
        [evidence(w, f"5{index:03d}", minor=1000 + index, when=october) for index in range(199)]
        + [evidence(w, "6000", minor=777, when=midnight(date(2026, 11, 5)))],
    )
    owner = w.signed_in("owner_a")
    url = report_url(w, "revenue", **NOVEMBER)
    accepted = _measure(owner, url, "revenue_200_evidence_rows")
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["totals"][0]["net"]["minor"] == 777
    assert body["unresolved"]["evidence_rows"] == 200
    compared = _measure(
        owner,
        report_url(w, "revenue", compare="previous", **NOVEMBER),
        "revenue_200_evidence_rows_compared",
    )
    assert compared.status_code == 200
    append(w, [evidence(w, "7000", minor=5, when=october - timedelta(days=60))])
    refused = _measure(owner, url, "revenue_201_evidence_rows")
    assert (refused.status_code, refused.json()) == (
        409,
        {"error": "report_requires_ledger_upgrade"},
    )
    other = owner.get(report_url(w, "revenue", client=w.a2, **NOVEMBER))
    assert other.status_code == 200


def test_v15_v18_csv_row_bound_is_exact(authenticated_world):
    w = authenticated_world
    cid = _spend_connection(w)
    day = [date(2026, 11, 1)]
    _bulk(w, AdSpendFact, _spend_rows(w, cid, day, 1))
    owner = w.signed_in("owner_a")
    url = report_url(w, "spend", connection_id=cid, format="csv", **NOVEMBER)
    one = list(csv.DictReader(io.StringIO(owner.get(url).content.decode("utf-8"), newline="")))
    fixed = len(one) - 3
    groups, extra = divmod(5_000 - fixed, 3)
    _bulk(w, AdSpendFact, _spend_rows(w, cid, day, groups - 1, start_ad=1))
    # Each provisional date adds one status record; use them to land exactly on the bound.
    for offset in range(extra):
        _bulk(
            w,
            AdSpendFact,
            [
                {
                    **_spend_rows(w, cid, [date(2026, 11, 10 + offset)], 1)[0],
                    "provisional_until": NOW + timedelta(days=2),
                }
            ],
        )
    accepted = _measure(owner, url, "spend_csv_5000_rows")
    assert accepted.status_code == 200
    rows = list(csv.DictReader(io.StringIO(accepted.content.decode("utf-8"), newline="")))
    assert len(rows) == 5_000
    assert len(accepted.content) <= 2 * 1024 * 1024
    # One more provisional date adds exactly one status record: 5,001 records.
    _bulk(
        w,
        AdSpendFact,
        [
            {
                **_spend_rows(w, cid, [date(2026, 11, 25)], 1)[0],
                "provisional_until": NOW + timedelta(days=2),
            }
        ],
    )
    refused = _measure(owner, url, "spend_csv_5001_rows")
    assert (refused.status_code, refused.json()) == (422, {"error": "export_too_large"})
    assert refused.headers["content-type"].startswith("application/json")
