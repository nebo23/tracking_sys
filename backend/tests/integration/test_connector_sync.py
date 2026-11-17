"""Connector synchronization on disposable PostgreSQL (specification 009-B, D-049).

Uses the 009-A synthetic lab of connector_support: agency A connects syn-acct-777 in clients
A1 (K1) and A2 (K2), and agency B connects it in client B1 (K3). The synthetic data set is
anchored at a fixed date, so windows, pages, and coverage never depend on the wall clock. Time
passes only through the `now` given to each worker pass.
"""

from dataclasses import replace
from datetime import timedelta

import pytest
from connector_support import ACCOUNT, WorkerStopped, make_lab
from connector_support import archive as _archive
from connector_support import fail_connection as _fail_k
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.connectors.synthetic import CAPABILITY, OBSERVED_AT, SyntheticProvider
from app.models import ConnectorCheckpoint, ConnectorRecord, ConnectorSyncRun, ConnectorUsageRecord
from app.security import now_utc
from app.services.connectors import _next_period

pytestmark = pytest.mark.integration
DAY = timedelta(days=1)
# End of the newest synthetic day: what a completed recent read reports as complete-through.
NEWEST = OBSERVED_AT + DAY


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


def _runs(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        return list(
            session.scalars(
                select(ConnectorSyncRun)
                .where(ConnectorSyncRun.connection_id == connection_id)
                .order_by(ConnectorSyncRun.created_at, ConnectorSyncRun.id)
            )
        )


def _checkpoint(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        return session.scalars(
            select(ConnectorCheckpoint).where(ConnectorCheckpoint.connection_id == connection_id)
        ).one_or_none()


def _objects(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        ids = session.scalars(
            select(ConnectorRecord.provider_object_id).where(
                ConnectorRecord.connection_id == connection_id
            )
        ).all()
    assert len(ids) == len(set(ids))
    return set(ids)


def _usage(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        rows = session.scalars(
            select(ConnectorUsageRecord).where(ConnectorUsageRecord.connection_id == connection_id)
        ).all()
    return sorted((row.period, row.operation, row.outcome, row.quantity) for row in rows)


def _posts(*indexes):
    return {f"{ACCOUNT}-post-{index}" for index in indexes}


def test_009b_pages_checkpoints_backfill_and_overlapping_requests(lab):
    w = lab.w
    lab.provider.set_behavior("objects", "10")
    lab.provider.set_behavior("page_size", "2")
    k1 = lab.connect("owner_a", w.a, w.a1)
    reads = len(lab.provider.reads())
    assert lab.worker()["sync"] == {"succeeded": 1}
    # The recent window holds three objects, read in two pages.
    assert lab.provider.reads()[reads:] == [(0, "ok"), (2, "ok")]
    assert _objects(lab, k1) == _posts(1, 2, 3)
    run = _runs(lab, k1)[-1]
    assert (run.kind, run.status, run.pages, run.window_since) == (
        "incremental",
        "succeeded",
        2,
        None,
    )
    point = _checkpoint(lab, k1)
    assert (point.stream, point.cursor, point.run_id) == ("objects", None, run.id)
    assert (point.covered_from, point.complete_through) == (NEWEST - 3 * DAY, NEWEST)

    # An incremental run starts one day before the watermark, the provider's overlap.
    assert lab.sync("owner_a", w.a, w.a1, k1).json()["kind"] == "incremental"
    reads = len(lab.provider.reads())
    assert lab.worker()["sync"] == {"succeeded": 1}
    run = _runs(lab, k1)[-1]
    assert (run.window_since, run.pages) == (NEWEST - DAY, 1)
    assert lab.provider.reads()[reads:] == [(0, "ok")]
    assert _objects(lab, k1) == _posts(1, 2, 3)

    # A backfill extends the history five days back without moving the incremental watermark.
    response = lab.sync("owner_a", w.a, w.a1, k1, {"kind": "backfill", "days": 5})
    assert response.status_code == 202 and response.json()["kind"] == "backfill"
    assert lab.worker()["sync"] == {"succeeded": 1}
    run = _runs(lab, k1)[-1]
    assert (run.kind, run.window_since, run.window_until, run.pages) == (
        "backfill",
        NEWEST - 8 * DAY,
        NEWEST - 3 * DAY,
        3,
    )
    assert _objects(lab, k1) == _posts(*range(1, 9))
    point = _checkpoint(lab, k1)
    assert (point.covered_from, point.complete_through) == (NEWEST - 8 * DAY, NEWEST)

    # The provider's history limit bounds a longer backfill; coverage records what it served.
    lab.sync("owner_a", w.a, w.a1, k1, {"kind": "backfill", "days": 30})
    assert lab.worker()["sync"] == {"succeeded": 1}
    assert _runs(lab, k1)[-1].window_since == NEWEST - 38 * DAY
    assert _checkpoint(lab, k1).covered_from == NEWEST - CAPABILITY.history_days * DAY
    assert _objects(lab, k1) == _posts(*range(1, 11))

    # Backfill requests are bounded by the provider's history limit.
    for body, status, error in (
        ({"kind": "backfill", "days": 31}, 422, {"error": "invalid_backfill"}),
        ({"kind": "backfill"}, 422, {"error": "invalid_backfill"}),
        ({"kind": "backfill", "days": 0}, 422, None),
        ({"kind": "weekly"}, 422, None),
    ):
        response = lab.sync("owner_a", w.a, w.a1, k1, body)
        assert response.status_code == status, body
        assert error is None or response.json() == error
    # Overlapping requests: the same kind returns the open run, the other kind is refused.
    first = lab.sync("owner_a", w.a, w.a1, k1).json()
    assert lab.sync("owner_a", w.a, w.a1, k1, {"kind": "incremental"}).json() == first
    response = lab.sync("owner_a", w.a, w.a1, k1, {"kind": "backfill", "days": 1})
    assert (response.status_code, response.json()) == (409, {"error": "sync_in_progress"})
    assert lab.sync("analyst", w.a, w.a1, k1, {"kind": "backfill", "days": 1}).status_code == 403
    # A backfill needs a completed synchronization first.
    k2 = lab.connect("owner_a", w.a, w.a2)
    lab.provider.set_behavior("fetch_script", "ok,forbidden")
    assert lab.worker()["sync"] == {"succeeded": 1, "failed": 1}
    response = lab.sync("owner_a", w.a, w.a2, k2, {"kind": "backfill", "days": 1})
    assert (response.status_code, response.json()) == (409, {"error": "sync_required"})


class _Stopping(SyntheticProvider):
    """Stops the worker once, before or after the read of one page."""

    def __init__(self, path, *, before=None, after=None):
        super().__init__(path)
        self.before, self.after = before, after

    def fetch_page(self, access_token, **window):
        if self.before is not None and window.get("cursor") == self.before:
            self.before = None
            raise WorkerStopped
        page = super().fetch_page(access_token, **window)
        if self.after is not None and window.get("cursor") == self.after:
            self.after = None
            raise WorkerStopped
        return page


@pytest.mark.parametrize("stop", ["after_read", "inside_write", "after_commit"])
def test_009b_restart_at_the_page_boundary_skips_and_duplicates_nothing(lab, stop):
    w = lab.w
    lab.provider.set_behavior("objects", "6")
    lab.provider.set_behavior("recent_days", "6")
    lab.provider.set_behavior("page_size", "2")
    k1 = lab.connect("owner_a", w.a, w.a1)
    k3 = lab.connect("owner_b", w.b, w.b1)
    start = now_utc()
    provider = {
        "after_read": _Stopping(lab.state, after="syn_cursor_2"),
        "inside_write": lab.provider,
        "after_commit": _Stopping(lab.state, before="syn_cursor_4"),
    }[stop]
    page_writes = []

    # Stop inside the transaction of the second page, after its records were written and
    # before the run's page count and the checkpoint advance.
    def stop_inside_write(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE connector_sync_runs SET") and (
            "pages=(connector_sync_runs.pages +" in statement
        ):
            page_writes.append(statement)
            if len(page_writes) == 2:
                raise WorkerStopped

    reads = len(lab.provider.reads())
    if stop == "inside_write":
        event.listen(w.db.runtime, "after_cursor_execute", stop_inside_write)
    try:
        with pytest.raises(WorkerStopped):
            lab.worker(now=start, registry={"synthetic": provider}, limit=1)
    finally:
        if stop == "inside_write":
            event.remove(w.db.runtime, "after_cursor_execute", stop_inside_write)
    first_pass = lab.provider.reads()[reads:]
    committed = 2 if stop == "after_commit" else 1
    run = _runs(lab, k1)[-1]
    assert (run.status, run.attempt, run.pages) == ("running", 1, committed)
    point = _checkpoint(lab, k1)
    assert (point.cursor, point.run_id) == (f"syn_cursor_{2 * committed}", run.id)
    assert point.complete_through is None
    assert _objects(lab, k1) == _posts(*range(1, 2 * committed + 1))

    # Within the lease another pass leaves the stopped run alone; the other agency syncs.
    assert lab.worker(now=start + timedelta(minutes=1))["sync"] == {"succeeded": 1}
    assert _objects(lab, k3) == _posts(*range(1, 7))
    # After the lease the run resumes at the stored cursor.
    reads = len(lab.provider.reads())
    assert lab.worker(now=start + timedelta(minutes=6))["sync"] == {"succeeded": 1}
    resumed = lab.provider.reads()[reads:]
    expected = {
        "after_read": ([(0, "ok"), (2, "ok")], [(2, "ok"), (4, "ok")]),
        "inside_write": ([(0, "ok"), (2, "ok")], [(2, "ok"), (4, "ok")]),
        "after_commit": ([(0, "ok"), (2, "ok")], [(4, "ok")]),
    }[stop]
    assert (first_pass, resumed) == expected
    run = _runs(lab, k1)[-1]
    assert (run.status, run.attempt, run.pages) == ("succeeded", 2, 3)
    assert _objects(lab, k1) == _posts(*range(1, 7))
    point = _checkpoint(lab, k1)
    assert (point.cursor, point.covered_from, point.complete_through) == (
        None,
        NEWEST - 6 * DAY,
        NEWEST,
    )
    # Every reserved call is counted, including the one interrupted by the stop.
    outcomes = sorted(item[2] for item in _usage(lab, k1))
    assert (
        outcomes
        == {
            "after_read": ["ok", "ok", "ok", "reserved"],
            "inside_write": ["ok", "ok", "ok", "ok"],
            "after_commit": ["ok", "ok", "ok", "reserved"],
        }[stop]
    )


def test_009b_rate_limits_retries_forbidden_and_permanent_failures(lab):
    w = lab.w
    lab.provider.set_behavior("page_size", "2")
    k1 = lab.connect("owner_a", w.a, w.a1)
    k2 = lab.connect("owner_a", w.a, w.a2)
    # 429 with Retry-After on the second page: the first page is kept and the run waits.
    lab.provider.set_behavior("fetch_script", "ok,rate_limited:120")
    t0 = now_utc()
    assert lab.worker(now=t0)["sync"] == {"deferred": 1, "succeeded": 1}
    run = _runs(lab, k1)[-1]
    assert (run.status, run.error_kind, run.retries, run.attempt, run.pages) == (
        "queued",
        "rate_limited",
        1,
        1,
        1,
    )
    assert run.not_before == t0 + timedelta(seconds=120)
    assert _objects(lab, k1) == _posts(1, 2)
    point = _checkpoint(lab, k1)
    assert (point.cursor, point.complete_through) == ("syn_cursor_2", None)
    assert _objects(lab, k2) == _posts(1, 2, 3)
    assert lab.view("owner_a", w.a, w.a1, k1).json()["status"] == "active"
    assert lab.worker(now=t0 + timedelta(seconds=119))["sync"] == {}
    reads = len(lab.provider.reads())
    assert lab.worker(now=t0 + timedelta(seconds=120))["sync"] == {"succeeded": 1}
    assert lab.provider.reads()[reads:] == [(2, "ok")]
    run = _runs(lab, k1)[-1]
    assert (run.status, run.attempt, run.pages, run.retries, run.error_kind) == (
        "succeeded",
        2,
        2,
        1,
        None,
    )
    assert _checkpoint(lab, k1).complete_through == NEWEST

    # Retry-After is honored up to one hour.
    t1 = t0 + timedelta(minutes=10)
    lab.sync("owner_a", w.a, w.a1, k1)
    lab.provider.set_behavior("fetch_script", "rate_limited:7200")
    assert lab.worker(now=t1)["sync"] == {"deferred": 1}
    assert _runs(lab, k1)[-1].not_before == t1 + timedelta(hours=1)

    # Retryable failures back off from 30 s, doubling, and fail the run after five deferrals.
    lab.sync("owner_a", w.a, w.a2, k2)
    lab.provider.set_behavior("fetch_script", ",".join(["retryable"] * 6))
    moment, delays = t1, []
    for _ in range(5):
        assert lab.worker(now=moment)["sync"] == {"deferred": 1}
        run = _runs(lab, k2)[-1]
        delays.append(run.not_before - moment)
        assert lab.worker(now=run.not_before - timedelta(seconds=1))["sync"] == {}
        moment = run.not_before
    assert delays == [timedelta(seconds=30 * 2**n) for n in range(5)]
    assert lab.worker(now=moment)["sync"] == {"failed": 1}
    run = _runs(lab, k2)[-1]
    assert (run.status, run.error_kind, run.retries) == ("failed", "retryable", 5)
    assert lab.row(k2).status == "active"

    # 403 and permanent failures fail only their run, without retry; the connection stays
    # active and synchronizes again later.
    for outcome, kind in (("forbidden", "forbidden"), ("permanent", "permanent")):
        lab.sync("owner_a", w.a, w.a2, k2)
        lab.provider.set_behavior("fetch_script", outcome)
        moment += timedelta(minutes=1)
        assert lab.worker(now=moment)["sync"] == {"failed": 1}
        run = _runs(lab, k2)[-1]
        assert (run.status, run.error_kind, run.retries) == ("failed", kind, 0)
        assert lab.view("owner_a", w.a, w.a2, k2).json()["status"] == "active"
    lab.sync("owner_a", w.a, w.a2, k2)
    assert lab.worker(now=moment + timedelta(minutes=1))["sync"] == {"succeeded": 1}
    # Usage counts every call, failed and retried calls included.
    outcomes = [item[2] for item in _usage(lab, k2)]
    assert sorted(outcomes) == sorted(
        ["ok", "ok"] + ["retryable"] * 6 + ["forbidden", "permanent", "ok"]
    )
    # The deferred run of K1 is still waiting for its Retry-After.
    assert _runs(lab, k1)[-1].status == "queued"


class _SmallQuota(SyntheticProvider):
    capability = replace(CAPABILITY, daily_quota=7)


def test_009b_usage_accounting_and_budget_stops(lab):
    w = lab.w
    settings = lab.config.model_copy(update={"connector_connection_daily_units": 3})
    provider = _SmallQuota(lab.state)
    registry = {"synthetic": provider}
    lab.provider.set_behavior("page_size", "1")
    lab.provider.set_behavior("access_ttl", str(3 * 86400))
    k1 = lab.connect("owner_a", w.a, w.a1)
    k3 = lab.connect("owner_b", w.b, w.b1)
    k2 = lab.connect("owner_a", w.a, w.a2)
    t0 = now_utc()
    period, following = t0.date(), _next_period(t0)
    # K1 and K3 each spend three units; K2's second read would exceed the provider quota of
    # seven units, although K2's own allocation is not reached.
    assert lab.worker(now=t0, registry=registry, settings=settings)["sync"] == {
        "succeeded": 2,
        "deferred": 1,
    }
    for k in (k1, k3):
        assert _usage(lab, k) == [(period, "fetch", "ok", 1)] * 3
        assert _objects(lab, k) == _posts(1, 2, 3)
    assert _usage(lab, k2) == [(period, "fetch", "ok", 1)]
    run = _runs(lab, k2)[-1]
    assert (run.status, run.error_kind, run.retries, run.pages, run.not_before) == (
        "queued",
        "budget_exhausted",
        0,
        1,
        following,
    )
    assert _objects(lab, k2) == _posts(1)
    assert _checkpoint(lab, k2).cursor == "syn_cursor_1"
    # K1's next run stops at its own allocation before calling the provider.
    lab.sync("owner_a", w.a, w.a1, k1)
    reads = len(lab.provider.reads())
    assert lab.worker(now=t0, registry=registry, settings=settings)["sync"] == {"deferred": 1}
    assert lab.provider.reads()[reads:] == []
    run = _runs(lab, k1)[-1]
    assert (run.status, run.error_kind, run.not_before) == ("queued", "budget_exhausted", following)
    assert len(_usage(lab, k1)) == 3
    # Both resume on the next UTC day; K2 continues at its stored cursor.
    assert (
        lab.worker(now=following - timedelta(seconds=1), registry=registry, settings=settings)[
            "sync"
        ]
        == {}
    )
    reads = len(lab.provider.reads())
    assert lab.worker(now=following, registry=registry, settings=settings)["sync"] == {
        "succeeded": 2
    }
    assert sorted(lab.provider.reads()[reads:]) == [(0, "ok"), (1, "ok"), (2, "ok")]
    assert _objects(lab, k2) == _posts(1, 2, 3)
    assert (
        _usage(lab, k2) == [(period, "fetch", "ok", 1)] + [(following.date(), "fetch", "ok", 1)] * 2
    )
    assert _usage(lab, k1)[-1] == (following.date(), "fetch", "ok", 1)
    assert _checkpoint(lab, k2).complete_through == NEWEST


def test_009b_scheduling_queues_due_connections_once(lab):
    w = lab.w
    k1, k2, k3 = lab.fixtures()
    t0 = now_utc()
    assert lab.worker(now=t0)["sync"] == {"succeeded": 3}
    assert lab.worker(now=t0 + timedelta(hours=1), schedule=True)["schedule"] == {}
    # An archived client and a connection that requires reconnection are not scheduled.
    _archive(w, w.a2)
    _fail_k(lab, w.b, w.b1, k3, owner="owner_b")
    later = t0 + timedelta(hours=25)
    result = lab.worker(now=later, schedule=True)
    assert (result["schedule"], result["sync"]) == ({"queued": 1}, {"succeeded": 1})
    run = _runs(lab, k1)[-1]
    assert (run.kind, run.status, run.created_at) == ("incremental", "succeeded", later)
    assert [r.kind for r in _runs(lab, k2)] == ["incremental"]
    # A connection synchronized within the interval is not queued again.
    assert lab.worker(now=later, schedule=True)["schedule"] == {}
    # An open run is never duplicated: the requested run is processed instead.
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    result = lab.worker(now=later + timedelta(hours=25), schedule=True)
    assert (result["schedule"], result["sync"]) == ({}, {"succeeded": 1})
    assert len(_runs(lab, k1)) == 3


def test_009b_privileges_scoped_references_and_disconnect_purge(lab):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    k2 = lab.connect("owner_a", w.a, w.a2)
    assert lab.worker()["sync"] == {"succeeded": 2}
    denied = [
        "DELETE FROM connector_usage_records",
        "UPDATE connector_usage_records SET quantity = quantity",
        "UPDATE connector_usage_records SET connection_id = connection_id",
        "UPDATE connector_checkpoints SET connection_id = connection_id",
        "UPDATE connector_checkpoints SET stream = stream",
        "UPDATE connector_sync_runs SET kind = kind",
    ]
    for statement in denied:
        with pytest.raises(DBAPIError, match="permission denied"):
            with w.db.runtime.begin() as connection:
                connection.execute(text(statement))
    # A checkpoint cannot reference another client's connection.
    with pytest.raises(IntegrityError):
        with Session(w.db.runtime) as session, session.begin():
            session.add(
                ConnectorCheckpoint(
                    agency_id=w.a, client_id=w.a2, connection_id=k1, stream="cross-client"
                )
            )
    # The disconnect purge deletes the checkpoint with the provider records; usage counts,
    # which hold no provider data, stay with the run history.
    usage = _usage(lab, k1)
    assert _checkpoint(lab, k1) is not None and usage
    lab.disconnect("owner_a", w.a, w.a1, k1)
    assert lab.worker()["teardown"] == {"disconnected": 1}
    assert _checkpoint(lab, k1) is None and _objects(lab, k1) == set()
    assert _usage(lab, k1) == usage
    assert _checkpoint(lab, k2) is not None and _objects(lab, k2) == _posts(1, 2, 3)


# R009-11: a worker pass without a fixed time reads the clock at each step, not once per claim.
# Each read of a slow provider takes two minutes on a controlled clock. A 429 on the third
# read waits its full Retry-After from the answer, each stored page renews the lease from its
# own write, and fetch and usage times are those of the calls. The other connections of the
# fixture keep synchronizing.
def test_r009_11_each_sync_step_reads_the_clock_when_it_happens(lab, monkeypatch):
    import app.services.connectors as service

    w = lab.w
    lab.provider.set_behavior("page_size", "1")
    k2 = lab.connect("owner_a", w.a, w.a2)
    k3 = lab.connect("owner_b", w.b, w.b1)
    assert lab.worker()["sync"] == {"succeeded": 2}
    # K1's first run reads the three-day recent window in three single-object pages.
    k1 = lab.connect("owner_a", w.a, w.a1)
    start = now_utc()
    clock = [start]
    step = timedelta(minutes=2)
    leases = []

    class SlowProvider:
        capability = lab.provider.capability

        def __getattr__(self, name):
            return getattr(lab.provider, name)

        def fetch_page(self, access_token, **kwargs):
            leases.append(_runs(lab, k1)[-1].lease_expires_at)
            try:
                return lab.provider.fetch_page(access_token, **kwargs)
            finally:
                clock[0] += step

    lab.provider.set_behavior("fetch_script", "ok,ok,rate_limited:300")
    reads = len(lab.provider.reads())
    monkeypatch.setattr(service, "now_utc", lambda: clock[0])
    try:
        # The run is deferred and not claimed again in the same pass.
        assert lab.worker(registry={"synthetic": SlowProvider()})["sync"] == {"deferred": 1}
    finally:
        monkeypatch.undo()
    assert lab.provider.reads()[reads:] == [(0, "ok"), (1, "ok"), (2, "rate_limited")]
    minutes = [timedelta(minutes=n) for n in range(12)]
    # The claim set the first lease; each stored page renewed it from its own write.
    assert leases == [start + minutes[5], start + minutes[7], start + minutes[9]]
    run = _runs(lab, k1)[-1]
    assert (run.status, run.error_kind, run.pages, run.retries) == (
        "queued",
        "rate_limited",
        2,
        1,
    )
    assert run.not_before == start + minutes[6] + timedelta(seconds=300)
    with Session(lab.w.db.migration) as session:
        fetched = dict(
            session.execute(
                select(ConnectorRecord.provider_object_id, ConnectorRecord.fetched_at).where(
                    ConnectorRecord.source_run_id == run.id
                )
            ).all()
        )
        usage = session.execute(
            select(ConnectorUsageRecord.occurred_at, ConnectorUsageRecord.settled_at)
            .where(ConnectorUsageRecord.run_id == run.id)
            .order_by(ConnectorUsageRecord.occurred_at)
        ).all()
    assert fetched == {
        f"{ACCOUNT}-post-1": start + minutes[2],
        f"{ACCOUNT}-post-2": start + minutes[4],
    }
    assert [tuple(row) for row in usage] == [
        (start, start + minutes[2]),
        (start + minutes[2], start + minutes[4]),
        (start + minutes[4], start + minutes[6]),
    ]
    # Retry-After counts from the 429, so the run waits until then and resumes at its cursor.
    assert lab.worker(now=run.not_before - timedelta(seconds=1))["sync"] == {}
    assert lab.worker(now=run.not_before)["sync"] == {"succeeded": 1}
    assert lab.provider.reads()[-1] == (2, "ok")
    assert _objects(lab, k1) == _posts(1, 2, 3)
    for other, agency, client_id, owner in ((k2, w.a, w.a2, "owner_a"), (k3, w.b, w.b1, "owner_b")):
        assert lab.sync(owner, agency, client_id, other).status_code == 202
    assert lab.worker()["sync"] == {"succeeded": 2}
    assert _objects(lab, k2) == _objects(lab, k3) == _posts(1, 2, 3)
