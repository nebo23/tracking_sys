"""Connector coverage and provenance reads (specification 009-C, D-049 decisions D16 and D17).

Readers with client:read see, for a connection of their client, where its data comes from, how
far the stored history is complete, whether each metric the adapter declares is available, the
state of the latest synchronization, and how much of the connection's own daily allocation is
spent. Every metric value is paired with an explicit state, so an observed zero is never
confused with a metric the provider omitted (missing), one it does not offer for the account
kind (unsupported), or a value older than the adapter's freshness window (stale). Responses
never include another tenant's usage, the provider-wide total, raw provider errors, cursors,
leases, or token state.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.contracts import Capability, ConnectorProvider, MetricSpec
from app.models import (
    ConnectorCheckpoint,
    ConnectorConnection,
    ConnectorRecord,
    ConnectorSyncRun,
    ConnectorUsageRecord,
)
from app.services.access import ScopedAccess
from app.services.connectors import get_connection, provider_for

RECORD_PAGE = 100


# A metric is unsupported only when the adapter restricts it to account kinds that exclude the
# connection's known kind; an unknown kind (for example after the purge) is not assumed.
def _supported(spec: MetricSpec, account_kind: str | None) -> bool:
    return spec.account_kinds is None or account_kind is None or account_kind in spec.account_kinds


def _freshness(connection: ConnectorConnection, capability: Capability, now: datetime) -> str:
    if connection.last_successful_sync_at is None:
        return "never_synced"
    window = timedelta(hours=capability.freshness_hours)
    return "stale" if now - connection.last_successful_sync_at > window else "fresh"


# The state of the latest run in reader terms. A queued run waiting for its not-before time is
# "delayed" after a rate limit or retryable failure and "budget_stopped" after a usage limit.
def _sync_state(run: ConnectorSyncRun | None, now: datetime) -> dict[str, object]:
    state: dict[str, object] = {
        "state": "idle",
        "kind": None if run is None else run.kind,
        "reason": None,
        "next_attempt_at": None,
    }
    if run is None:
        return state
    if run.status == "queued":
        waiting = run.not_before is not None and run.not_before > now
        if waiting and run.error_kind == "budget_exhausted":
            state["state"] = "budget_stopped"
        elif waiting:
            state["state"] = "delayed"
        else:
            state["state"] = "queued"
        state["reason"] = run.error_kind
        state["next_attempt_at"] = run.not_before if waiting else None
    elif run.status == "running":
        state["state"] = "running"
    elif run.status == "failed":
        state["state"], state["reason"] = "failed", run.error_kind
    elif run.status == "canceled":
        state["reason"] = run.error_kind
    return state


def _period_start(now: datetime) -> datetime:
    day = now.astimezone(UTC).date()
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


@dataclass(frozen=True)
class _Context:
    connection: ConnectorConnection
    capability: Capability


def _context(
    session: Session,
    registry: Mapping[str, ConnectorProvider],
    access: ScopedAccess,
    connection_id: UUID,
) -> _Context:
    connection = get_connection(session, access, connection_id)
    return _Context(connection, provider_for(registry, connection.provider).capability)


# Coverage of one connection of the reader's client (D16). The metric availability is
# "unsupported" for the account kind, "not_synced" before any record exists, "missing" when no
# stored record has a value, "stale" when values exist but the last successful synchronization
# is older than the freshness window, and "available" otherwise.
def coverage(
    session: Session,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    access: ScopedAccess,
    connection_id: UUID,
    now: datetime,
) -> dict[str, object]:
    context = _context(session, registry, access, connection_id)
    connection, capability = context.connection, context.capability
    run = session.scalar(
        select(ConnectorSyncRun)
        .where(ConnectorSyncRun.connection_id == connection.id)
        .order_by(ConnectorSyncRun.created_at.desc(), ConnectorSyncRun.id.desc())
        .limit(1)
    )
    checkpoints = {
        row.stream: row
        for row in session.scalars(
            select(ConnectorCheckpoint).where(ConnectorCheckpoint.connection_id == connection.id)
        )
    }
    point = checkpoints.get(capability.stream)
    if point is None or point.complete_through is None:
        stream_state = "partial" if point is not None and point.cursor else "not_synced"
    else:
        stream_state = "partial" if point.cursor else "complete"
    freshness = _freshness(connection, capability, now)
    stored = session.scalar(
        select(func.count())
        .select_from(ConnectorRecord)
        .where(ConnectorRecord.connection_id == connection.id)
    )
    metrics = []
    for spec in capability.metrics:
        valued = (ConnectorRecord.metrics.has_key(spec.name)) & (
            func.jsonb_typeof(ConnectorRecord.metrics[spec.name]) != "null"
        )
        latest = session.scalar(
            select(func.max(ConnectorRecord.observed_at)).where(
                ConnectorRecord.connection_id == connection.id, valued
            )
        )
        if not _supported(spec, connection.account_kind):
            availability = "unsupported"
        elif not stored:
            availability = "not_synced"
        elif latest is None:
            availability = "missing"
        elif freshness == "stale":
            availability = "stale"
        else:
            availability = "available"
        metrics.append(
            {
                "name": spec.name,
                "unit": spec.unit,
                "availability": availability,
                "latest_observed_at": latest if _supported(spec, connection.account_kind) else None,
            }
        )
    period = _period_start(now)
    consumed = session.scalar(
        select(func.coalesce(func.sum(ConnectorUsageRecord.quantity), 0)).where(
            ConnectorUsageRecord.connection_id == connection.id,
            ConnectorUsageRecord.period == period.date(),
        )
    )
    allocation = settings.connector_connection_daily_units
    sync = _sync_state(run, now)
    reason = None
    if consumed >= allocation:
        reason = "connection_allocation"
    elif sync["state"] == "budget_stopped":
        reason = "provider_quota"
    return {
        "connection_id": connection.id,
        "source": {
            "provider": connection.provider,
            "adapter_version": capability.version,
            "account_kind": connection.account_kind,
        },
        "status": connection.status,
        "last_successful_sync_at": connection.last_successful_sync_at,
        "freshness": freshness,
        "freshness_hours": capability.freshness_hours,
        "sync": sync,
        "streams": [
            {
                "stream": capability.stream,
                "state": stream_state,
                "covered_from": None if point is None else point.covered_from,
                "complete_through": None if point is None else point.complete_through,
                "history_limit_days": capability.history_days,
            }
        ],
        "metrics": metrics,
        "cost": {
            "unit": capability.cost_unit,
            "period_start": period,
            "consumed": consumed,
            "allocation": allocation,
            "remaining": max(allocation - consumed, 0),
            "state": "exhausted" if reason else "available",
            "reason": reason,
        },
    }


# One page of a connection's stored records with provenance and per-metric states (D17),
# ordered by provider object ID; `after` continues after the last ID of the previous page.
# Only metrics declared in the adapter's catalog are returned.
def records(
    session: Session,
    registry: Mapping[str, ConnectorProvider],
    access: ScopedAccess,
    connection_id: UUID,
    now: datetime,
    *,
    after: str | None = None,
    limit: int = RECORD_PAGE,
) -> tuple[list[dict[str, object]], str | None]:
    context = _context(session, registry, access, connection_id)
    connection, capability = context.connection, context.capability
    query = select(ConnectorRecord).where(ConnectorRecord.connection_id == connection.id)
    if after is not None:
        query = query.where(ConnectorRecord.provider_object_id > after)
    rows = list(
        session.scalars(query.order_by(ConnectorRecord.provider_object_id).limit(limit + 1))
    )
    window = timedelta(hours=capability.freshness_hours)
    items = []
    for row in rows[:limit]:
        stale = now - row.fetched_at > window
        values: dict[str, dict[str, object]] = {}
        for spec in capability.metrics:
            value = row.metrics.get(spec.name)
            if not _supported(spec, connection.account_kind):
                values[spec.name] = {"state": "unsupported", "value": None}
            elif value is None:
                values[spec.name] = {"state": "missing", "value": None}
            else:
                values[spec.name] = {"state": "stale" if stale else "observed", "value": value}
        items.append(
            {
                "provider_object_id": row.provider_object_id,
                "observed_at": row.observed_at,
                "fetched_at": row.fetched_at,
                "source": {
                    "provider": connection.provider,
                    "adapter_version": row.adapter_version,
                    "run_id": row.source_run_id,
                },
                "metrics": values,
            }
        )
    following = rows[limit - 1].provider_object_id if len(rows) > limit else None
    return items, following


__all__ = ["coverage", "records"]
