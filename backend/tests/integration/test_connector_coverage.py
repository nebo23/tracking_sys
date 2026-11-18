"""Connector coverage and provenance on disposable PostgreSQL (specification 009-C, D-049).

Uses the synthetic lab of connector_support. The synthetic adapter reports impressions and
engagements for every account kind and saves for business accounts only; behaviors report a
metric as zero or omit it. Stored values older than the 24-hour freshness window are stale.
"""

from dataclasses import replace
from datetime import timedelta

import pytest
from connector_support import ACCOUNT, make_lab
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.synthetic import CAPABILITY, OBSERVED_AT, SyntheticProvider
from app.models import ConnectorSyncRun
from app.security import now_utc
from app.services.connectors import _next_period

pytestmark = pytest.mark.integration
DAY = timedelta(days=1)
NEWEST = OBSERVED_AT + DAY
CREATOR = "syn-creator-1"


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


def _base(lab, agency, client_id, connection_id):
    return f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}"


def _coverage(lab, name, agency, client_id, connection_id, client=None):
    browser = client or lab.browser(name)
    response = browser.get(_base(lab, agency, client_id, connection_id) + "/coverage")
    assert response.status_code == 200, response.text
    return response.json()


def _records(lab, name, agency, client_id, connection_id, **query):
    response = lab.browser(name).get(
        _base(lab, agency, client_id, connection_id) + "/records", params=query
    )
    assert response.status_code == 200, response.text
    return response.json()


def _metrics(coverage):
    return {item["name"]: item["availability"] for item in coverage["metrics"]}


def _without_sync(stream):
    return {key: value for key, value in stream.items() if key != "sync"}


def _values(record):
    return {name: (item["state"], item["value"]) for name, item in record["metrics"].items()}


def _latest_run(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        return session.scalars(
            select(ConnectorSyncRun)
            .where(ConnectorSyncRun.connection_id == connection_id)
            .order_by(ConnectorSyncRun.created_at.desc(), ConnectorSyncRun.id.desc())
        ).first()


def _iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


class _Quota(SyntheticProvider):
    capability = replace(CAPABILITY, daily_quota=4)


def test_009c_coverage_and_metric_states(lab, api):
    w = lab.w
    lab.provider.set_behavior("objects", "6")
    lab.provider.set_behavior("zero_metric", "engagements")
    k1 = lab.connect("owner_a", w.a, w.a1)
    k2 = lab.connect("owner_a", w.a, w.a2, account=CREATOR, kind="creator")

    # Before the first synchronization nothing is claimed about coverage or metrics.
    body = _coverage(lab, "owner_a", w.a, w.a1, k1)
    assert body["source"] == {
        "provider": "synthetic",
        "adapter_version": "synthetic-3",
        "account_kind": "business",
    }
    assert (body["status"], body["freshness"], body["last_successful_sync_at"]) == (
        "active",
        "never_synced",
        None,
    )
    assert body["sync"] == {
        "state": "queued",
        "kind": "incremental",
        "reason": None,
        "next_attempt_at": None,
    }
    # 010-A adds each stream's latest run; with one stream it is the connection's latest run.
    assert body["streams"][0]["sync"] == body["sync"]
    assert [_without_sync(stream) for stream in body["streams"]] == [
        {
            "stream": "objects",
            "state": "not_synced",
            "covered_from": None,
            "complete_through": None,
            "history_limit_days": 30,
        }
    ]
    assert _metrics(body) == {
        "impressions": "not_synced",
        "engagements": "not_synced",
        "saves": "not_synced",
    }
    assert body["cost"]["consumed"] == 0 and body["cost"]["state"] == "available"
    creator = _coverage(lab, "owner_a", w.a, w.a2, k2)
    assert creator["source"]["account_kind"] == "creator"
    assert _metrics(creator)["saves"] == "unsupported"

    # After a complete synchronization: an observed zero is available, not missing.
    t0 = now_utc()
    assert lab.worker(now=t0)["sync"] == {"succeeded": 2}
    body = _coverage(lab, "owner_a", w.a, w.a1, k1)
    assert (body["freshness"], body["sync"]["state"]) == ("fresh", "idle")
    assert _without_sync(body["streams"][0]) | {"history_limit_days": 30} == {
        "stream": "objects",
        "state": "complete",
        "covered_from": _iso(NEWEST - 3 * DAY),
        "complete_through": _iso(NEWEST),
        "history_limit_days": 30,
    }
    assert _metrics(body) == {
        "impressions": "available",
        "engagements": "available",
        "saves": "available",
    }
    assert {item["latest_observed_at"] for item in body["metrics"]} == {_iso(OBSERVED_AT)}
    assert body["cost"] | {"period_start": None} == {
        "unit": "synthetic_unit",
        "period_start": None,
        "consumed": 1,
        "allocation": 100,
        "remaining": 99,
        "state": "available",
        "reason": None,
        "buckets": [],
    }
    run = _latest_run(lab, k1)
    page = _records(lab, "owner_a", w.a, w.a1, k1)
    assert page["next_after"] is None
    assert [item["provider_object_id"] for item in page["records"]] == [
        f"{ACCOUNT}-post-{index}" for index in (1, 2, 3)
    ]
    first = page["records"][0]
    assert first["source"] == {
        "provider": "synthetic",
        "adapter_version": "synthetic-3",
        "run_id": str(run.id),
    }
    assert (first["observed_at"], first["fetched_at"]) == (_iso(OBSERVED_AT), _iso(t0))
    assert _values(first) == {
        "impressions": ("observed", 100),
        "engagements": ("observed", 0),
        "saves": ("observed", 1),
    }
    # A metric the account kind does not offer is unsupported, never zero.
    creator = _records(lab, "owner_a", w.a, w.a2, k2)["records"]
    assert {_values(item)["saves"] for item in creator} == {("unsupported", None)}
    assert _metrics(_coverage(lab, "owner_a", w.a, w.a2, k2))["saves"] == "unsupported"
    # Record pages continue after the last provider object ID.
    page = _records(lab, "owner_a", w.a, w.a1, k1, limit=2)
    assert len(page["records"]) == 2 and page["next_after"] == f"{ACCOUNT}-post-2"
    rest = _records(lab, "owner_a", w.a, w.a1, k1, limit=2, after=page["next_after"])
    assert [item["provider_object_id"] for item in rest["records"]] == [f"{ACCOUNT}-post-3"]
    assert rest["next_after"] is None

    # A metric the provider omits is missing; values older than the window are stale.
    lab.provider.set_behavior("zero_metric", "")
    lab.provider.set_behavior("omit_metric", "impressions")
    k3 = lab.connect("owner_b", w.b, w.b1)
    assert lab.worker(now=t0 - 2 * DAY)["sync"] == {"succeeded": 1}
    body = _coverage(lab, "owner_b", w.b, w.b1, k3)
    assert body["freshness"] == "stale"
    assert _metrics(body) == {"impressions": "missing", "engagements": "stale", "saves": "stale"}
    assert body["cost"]["consumed"] == 0
    stale = _records(lab, "owner_b", w.b, w.b1, k3)["records"][0]
    assert _values(stale) == {
        "impressions": ("missing", None),
        "engagements": ("stale", 10),
        "saves": ("stale", 1),
    }
    lab.provider.set_behavior("omit_metric", "")

    # A delayed page: the backfill keeps its first page and waits for Retry-After; coverage
    # is partial and the watermarks have not moved.
    lab.provider.set_behavior("page_size", "2")
    assert lab.sync("owner_a", w.a, w.a1, k1, {"kind": "backfill", "days": 3}).status_code == 202
    lab.provider.set_behavior("fetch_script", "ok,rate_limited:300")
    t1 = now_utc()
    assert lab.worker(now=t1)["sync"] == {"deferred": 1}
    body = _coverage(lab, "owner_a", w.a, w.a1, k1)
    assert body["sync"] == {
        "state": "delayed",
        "kind": "backfill",
        "reason": "rate_limited",
        "next_attempt_at": _iso(t1 + timedelta(seconds=300)),
    }
    stream = body["streams"][0]
    assert (stream["state"], stream["covered_from"], stream["complete_through"]) == (
        "partial",
        _iso(NEWEST - 3 * DAY),
        _iso(NEWEST),
    )
    assert body["freshness"] == "fresh" and _metrics(body)["impressions"] == "available"
    stored = _records(lab, "owner_a", w.a, w.a1, k1)["records"]
    assert len(stored) == 5
    assert body["cost"]["consumed"] == 3

    # A budget stop: the provider quota, shared by all tenants, ends the day for this run. The
    # connection's own allocation is not exhausted, and no other tenant's usage is shown.
    resumed = lab.worker(now=t1 + timedelta(seconds=300), registry={"synthetic": _Quota(lab.state)})
    assert resumed["sync"] == {"deferred": 1}
    body = _coverage(lab, "owner_a", w.a, w.a1, k1)
    assert body["sync"] == {
        "state": "budget_stopped",
        "kind": "backfill",
        "reason": "budget_exhausted",
        "next_attempt_at": _iso(_next_period(t1 + timedelta(seconds=300))),
    }
    assert body["streams"][0]["state"] == "partial"
    cost = body["cost"]
    assert (cost["consumed"], cost["remaining"], cost["state"], cost["reason"]) == (
        3,
        97,
        "exhausted",
        "provider_quota",
    )
    assert set(cost) == {
        "unit",
        "period_start",
        "consumed",
        "allocation",
        "remaining",
        "state",
        "reason",
        "buckets",
    }
    # With a smaller allocation, the connection's own spending exhausts it.
    small = api.new_client(lab.config.model_copy(update={"connector_connection_daily_units": 3}))
    api.login(small, "owner_a@example.test")
    cost = _coverage(lab, "owner_a", w.a, w.a1, k1, client=small)["cost"]
    assert (cost["allocation"], cost["remaining"], cost["state"], cost["reason"]) == (
        3,
        0,
        "exhausted",
        "connection_allocation",
    )

    # Readers with client visibility see coverage and records; nobody else does.
    path = _base(lab, w.a, w.a1, k1)
    for name, status in (("analyst", 200), ("viewer", 200), ("owner_b", 403)):
        for suffix in ("/coverage", "/records"):
            assert lab.browser(name).get(path + suffix).status_code == status, (name, suffix)
    assert lab.browser("analyst").get(_base(lab, w.a, w.a2, k2) + "/coverage").status_code == 403
    assert lab.browser("owner_a").get(_base(lab, w.a, w.a1, k3) + "/coverage").status_code == 403
    response = lab.browser("owner_a").get(path + "/records", params={"limit": 101})
    assert response.status_code == 422

    # After a disconnect the purge leaves nothing to report as available.
    lab.disconnect("owner_a", w.a, w.a2, k2)
    assert lab.worker()["teardown"] == {"disconnected": 1}
    body = _coverage(lab, "owner_a", w.a, w.a2, k2)
    assert (body["status"], body["source"]["account_kind"]) == ("disconnected", None)
    assert set(_metrics(body).values()) == {"not_synced"}
    assert body["streams"][0]["state"] == "not_synced"
    assert _records(lab, "owner_a", w.a, w.a2, k2) == {"records": [], "next_after": None}
