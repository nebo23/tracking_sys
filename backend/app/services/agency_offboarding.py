"""Offboarding of closed agencies (specification 017-B, D-098 D6; design-017b.md section 4).

The first worker pass after a closure completes runs, as tracking_app, the offboarding of the
closed agency, in two transactions:

1. record: the agency row is locked (SKIP LOCKED, so a second worker passes it by) and the
   purge record is inserted in state offboarding with the copied closure times;
2. effects: the agency row and the purge record are locked again and, unless the state moved
   on, every live connection is disconnected with reason agency_closed (the 009 teardown then
   revokes its tokens and purges its provider data), service keys and pending invitations are
   revoked, report exports are revoked, a pending offboarding export fails with
   closure_completed, and sources, destinations and WhatsApp numbers are disabled. The export
   summary is written and the record moves to waiting.

Every effect selects only rows still in the state it changes, so a second pass changes nothing.
No audit row is written: the actor is the platform, and the agency's audit log is purged; the
purge record carries the times. Nothing here logs or returns a name, a figure or a token.
"""

import logging
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Agency,
    AgencyClosure,
    AgencyExport,
    AgencyInvitation,
    AgencyPurge,
    ClientWorkspace,
    ConnectorConnection,
    ConversionDestination,
    IngestionSource,
    IntegrationSource,
    PaymentSource,
    ServiceCredential,
    WhatsappNumber,
)
from app.security import now_utc
from app.services.connectors import LIVE, start_disconnect
from app.services.report_exports import revoke_exports

logger = logging.getLogger("tracking")
EFFECTS = (
    "connections_disconnected",
    "service_keys_revoked",
    "invitations_revoked",
    "report_exports_revoked",
    "agency_exports_failed",
    "sources_disabled",
    "destinations_disabled",
    "whatsapp_numbers_disabled",
)


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def export_view_status(item: AgencyExport, now: datetime) -> str:
    """The export's status as answered: a ready export past its expiry is expired."""
    if item.status == "ready" and item.expires_at <= now:
        return "expired"
    return item.status


# The summary of the agency's latest offboarding export kept in the purge record (D8): totals,
# times and the manifest digest only, never a client ID, a path or a name.
def export_summary(session: Session, agency_id: UUID, now: datetime) -> dict[str, Any]:
    item = session.scalar(
        select(AgencyExport)
        .where(AgencyExport.agency_id == agency_id)
        .order_by(AgencyExport.requested_at.desc(), AgencyExport.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if item is None:
        return {"status": "none"}
    return {
        "status": export_view_status(item, now),
        "error_code": item.error_code,
        "requested_at": _time(item.requested_at),
        "ready_at": _time(item.ready_at),
        "expires_at": _time(item.expires_at),
        "revoked_at": _time(item.revoked_at),
        "part_count": item.part_count,
        "byte_size": item.byte_size,
        "row_count": item.row_count,
        "manifest_sha256": item.manifest_sha256,
        "download_count": item.download_count,
        "last_downloaded_at": _time(item.last_downloaded_at),
    }


def _locked_closed(session: Session, agency_id: UUID) -> Agency | None:
    return session.scalar(
        select(Agency)
        .where(Agency.id == agency_id, Agency.status == "closed")
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


# Transaction 1: insert the purge record in state offboarding. Returns whether the agency is
# (now) in state offboarding; False when it is locked by another worker, not closed, already
# further along, or without a completed closure (which 017-A always records).
def _record(engine: Engine, agency_id: UUID) -> bool:
    with Session(engine) as session, session.begin():
        if _locked_closed(session, agency_id) is None:
            return False
        purge = session.get(AgencyPurge, agency_id, with_for_update=True, populate_existing=True)
        if purge is not None:
            return purge.state == "offboarding"
        closure = session.scalar(
            select(AgencyClosure)
            .where(AgencyClosure.agency_id == agency_id, AgencyClosure.completed_at.is_not(None))
            .order_by(AgencyClosure.completed_at.desc(), AgencyClosure.id.desc())
            .limit(1)
        )
        if closure is None or closure.completed_at is None:
            return False
        session.add(
            AgencyPurge(
                agency_id=agency_id,
                state="offboarding",
                closure_requested_at=closure.requested_at,
                closes_at=closure.closes_at,
                closure_completed_at=closure.completed_at,
            )
        )
        return True


def _changed(session: Session, statement: Any) -> int:
    return session.execute(statement.execution_options(synchronize_session=False)).rowcount


# The effects of D6 on one locked agency, each limited to rows still in the state it changes.
def _effects(session: Session, settings: Settings, agency_id: UUID, now: datetime) -> Counter:
    counts: Counter = Counter()
    connections = session.scalars(
        select(ConnectorConnection)
        .where(ConnectorConnection.agency_id == agency_id, ConnectorConnection.status.in_(LIVE))
        .order_by(ConnectorConnection.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    for connection in connections:
        start_disconnect(session, settings, connection, "agency_closed", now)
        counts["connections_disconnected"] += 1
    session.flush()
    counts["service_keys_revoked"] = _changed(
        session,
        update(ServiceCredential)
        .where(ServiceCredential.agency_id == agency_id, ServiceCredential.status == "active")
        .values(status="revoked", updated_at=func.now()),
    )
    counts["invitations_revoked"] = _changed(
        session,
        update(AgencyInvitation)
        .where(AgencyInvitation.agency_id == agency_id, AgencyInvitation.status == "pending")
        .values(status="revoked", updated_at=func.now()),
    )
    clients = session.scalars(
        select(ClientWorkspace.id)
        .where(ClientWorkspace.agency_id == agency_id)
        .order_by(ClientWorkspace.id)
    ).all()
    for client_id in clients:
        counts["report_exports_revoked"] += revoke_exports(
            session, agency_id, client_id, "agency_closed"
        )
    counts["agency_exports_failed"] = _changed(
        session,
        update(AgencyExport)
        .where(AgencyExport.agency_id == agency_id, AgencyExport.status == "pending")
        .values(status="failed", error_code="closure_completed"),
    )
    for model in (IngestionSource, PaymentSource, IntegrationSource):
        counts["sources_disabled"] += _changed(
            session,
            update(model)
            .where(model.agency_id == agency_id, model.status == "active")
            .values(status="disabled", updated_at=func.now()),
        )
    counts["destinations_disabled"] = _changed(
        session,
        update(ConversionDestination)
        .where(ConversionDestination.agency_id == agency_id, ConversionDestination.enabled)
        .values(enabled=False, updated_at=func.now()),
    )
    # A pending claim is revoked, so the operator can no longer verify it (design section 12).
    counts["whatsapp_numbers_disabled"] = _changed(
        session,
        update(WhatsappNumber)
        .where(WhatsappNumber.agency_id == agency_id, WhatsappNumber.status == "active")
        .values(status="disabled", updated_at=func.now()),
    ) + _changed(
        session,
        update(WhatsappNumber)
        .where(WhatsappNumber.agency_id == agency_id, WhatsappNumber.status == "pending")
        .values(status="revoked", updated_at=func.now()),
    )
    return counts


# Transaction 2: apply the effects and move the record to waiting. Returns the effect counts,
# or None when the agency is locked by another worker or no longer in state offboarding.
def _complete(engine: Engine, settings: Settings, agency_id: UUID, now: datetime) -> Counter | None:
    with Session(engine) as session, session.begin():
        if _locked_closed(session, agency_id) is None:
            return None
        purge = session.get(AgencyPurge, agency_id, with_for_update=True, populate_existing=True)
        if purge is None or purge.state != "offboarding":
            return None
        counts = _effects(session, settings, agency_id, now)
        clock = session.scalar(select(func.now()))
        assert clock is not None
        purge.export_summary = export_summary(session, agency_id, clock)
        purge.state, purge.offboarding_completed_at = "waiting", func.now()
        return counts


def offboard_agency(
    engine: Engine, settings: Settings, agency_id: UUID, now: datetime | None = None
) -> Counter | None:
    """Offboard one closed agency; None when there was nothing to do or it was busy."""
    if not _record(engine, agency_id):
        return None
    return _complete(engine, settings, agency_id, now or now_utc())


# The closed agencies whose offboarding is due: no purge record yet, or one still offboarding.
def due_agencies(session: Session, limit: int) -> list[UUID]:
    return list(
        session.scalars(
            select(Agency.id)
            .outerjoin(AgencyPurge, AgencyPurge.agency_id == Agency.id)
            .where(
                Agency.status == "closed",
                (AgencyPurge.agency_id.is_(None)) | (AgencyPurge.state == "offboarding"),
            )
            .order_by(Agency.id)
            .limit(limit)
        )
    )


def run_offboarding(
    engine: Engine, settings: Settings, *, limit: int = 10, now: datetime | None = None
) -> dict[str, int]:
    """One bounded pass: offboard at most `limit` due agencies; counts only."""
    with Session(engine) as session:
        agencies = due_agencies(session, limit)
    totals: Counter = Counter({"offboarded": 0, "skipped": 0, "failed": 0})
    for agency_id in agencies:
        try:
            counts = offboard_agency(engine, settings, agency_id, now)
        except SQLAlchemyError:
            logger.warning("agency_offboarding_failed")
            totals["failed"] += 1
            continue
        if counts is None:
            totals["skipped"] += 1
            continue
        totals["offboarded"] += 1
        totals.update(counts)
    return {name: totals[name] for name in ("offboarded", "skipped", "failed", *EFFECTS)}


def _counts(rows: Mapping[str, Any]) -> dict[str, int]:
    return {str(name): int(value) for name, value in sorted(rows.items())}


# The operator's view of one agency (D11): states, times and counts, never a name.
def status(session: Session, agency_id: UUID) -> dict[str, Any] | None:
    agency = session.get(Agency, agency_id, populate_existing=True)
    if agency is None:
        return None
    now = session.scalar(select(func.now()))
    assert now is not None
    purge = session.get(AgencyPurge, agency_id, populate_existing=True)
    closure = session.scalar(
        select(AgencyClosure)
        .where(AgencyClosure.agency_id == agency_id)
        .order_by(AgencyClosure.requested_at.desc(), AgencyClosure.id.desc())
        .limit(1)
    )
    if closure is not None:
        closure_view: dict[str, Any] | None = {
            "requested_at": _time(closure.requested_at),
            "closes_at": _time(closure.closes_at),
            "cancelled_at": _time(closure.cancelled_at),
            "completed_at": _time(closure.completed_at),
        }
    elif purge is not None:
        closure_view = {
            "requested_at": _time(purge.closure_requested_at),
            "closes_at": _time(purge.closes_at),
            "cancelled_at": None,
            "completed_at": _time(purge.closure_completed_at),
        }
    else:
        closure_view = None
    if purge is not None and purge.state != "offboarding":
        export: dict[str, Any] = dict(purge.export_summary)
    else:
        export = export_summary(session, agency_id, now)
    offboarding = None
    if purge is not None:
        deleted = _counts(purge.deleted_counts)
        offboarding = {
            "state": purge.state,
            "offboarding_started_at": _time(purge.offboarding_started_at),
            "offboarding_completed_at": _time(purge.offboarding_completed_at),
            "teardown_settled_at": _time(purge.teardown_settled_at),
            "purge_started_at": _time(purge.purge_started_at),
            "purge_completed_at": _time(purge.purge_completed_at),
            "deleted_rows": sum(deleted.values()),
            "deleted": deleted,
        }
    connections = Counter({"live": 0, "disconnecting": 0, "past_deadline": 0, "disconnected": 0})
    for state, due in session.execute(
        select(ConnectorConnection.status, ConnectorConnection.purge_due_at).where(
            ConnectorConnection.agency_id == agency_id
        )
    ):
        if state in LIVE:
            connections["live"] += 1
        elif state == "disconnecting":
            connections["past_deadline" if due is not None and due <= now else "disconnecting"] += 1
        else:
            connections["disconnected"] += 1
    return {
        "agency_id": str(agency_id),
        "status": agency.status,
        "purged_at": _time(agency.purged_at),
        "closure": closure_view,
        "export": export,
        "offboarding": offboarding,
        "connections": dict(connections),
    }
