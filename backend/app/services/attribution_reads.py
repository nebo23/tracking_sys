"""Reads of stored attribution and their release barrier (008-B, D-079 decisions D8 and D10).

status() reports the consumer's checkpoint beside the current watermarks: caught_up, behind
or rebuilding. Nothing in it names a person, an event or a sale.

runs() returns the stored revisions of one conversion under one model version, and it is a
person-level read: it answers the retryable attribution_stale (503) unless the consumer is
caught up, and, for an open unscrubbed conversion, unless the conversion is still what its
slot currently is and recalculating it from the current inputs with attribute() changes
nothing. That check covers consent, tombstones, associations and consent expiry at read time,
so an older person association is never released. A superseded or scrubbed conversion is
stored history and is returned as such. The caller runs runs() in a REPEATABLE READ snapshot
and resolves the reader's scope again before it responds.

Money needs finance:read: without it a sale's amounts and transaction references answer the
explicit permission_unavailable, while shares, provenance and touches stay.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AttributionAllocation,
    AttributionConsumerState,
    AttributionConversion,
    AttributionCreditChange,
    AttributionRun,
)
from app.services import attribution_store as store
from app.services.attribution_models import AttributionError, active_digest, versions, view
from app.services.identity_feed import current_watermark
from app.services.ledger_store import LedgerUnavailable, published_state
from app.services.tenancy import AccessDenied

STALE = ("attribution_stale", 503)


def _iso(moment) -> str | None:
    return moment.isoformat() if moment is not None else None


def status(session: Session, agency_id: UUID, client_id: UUID) -> dict[str, Any]:
    state = session.get(AttributionConsumerState, client_id, populate_existing=True)
    digest = active_digest(versions(session, client_id))
    try:
        ledger = published_state(session, agency_id, client_id)
        ledger_state = "available" if ledger is not None else "none"
        generation = ledger.generation if ledger is not None else 0
        ordinal = ledger.receipt_ordinal if ledger is not None else 0
    except LedgerUnavailable:
        ledger_state, generation, ordinal = "unavailable", None, None
    feed_last = current_watermark(session.connection(), client_id)[0]
    current = {
        "ledger": ledger_state,
        "ledger_generation": generation,
        "receipt_ordinal": ordinal,
        "identity_seq": feed_last,
    }
    if state is None:
        consumer = {
            "generation": 0,
            "status": "building",
            "failure_code": None,
            "unit": None,
            "ledger_generation": 0,
            "receipt_ordinal": 0,
            "identity_seq": 0,
            "model_set_current": False,
            "published_at": None,
        }
        return {"state": "rebuilding", "consumer": consumer, "current": current}
    consumer = {
        "generation": state.generation,
        "status": state.status,
        "failure_code": state.failure_code,
        "unit": state.unit_kind,
        "ledger_generation": state.ledger_generation,
        "receipt_ordinal": state.receipt_ordinal,
        "identity_seq": state.identity_seq,
        "model_set_current": state.model_set_digest == digest,
        "published_at": _iso(state.published_at),
    }
    if state.generation == 0 or state.unit_kind == "rebuild" or state.status == "building":
        name = "rebuilding"
    else:
        covered = (
            state.status == "ready"
            and state.unit_kind is None
            and ledger_state != "unavailable"
            and state.ledger_generation == generation
            and state.receipt_ordinal == ordinal
            and state.identity_seq >= feed_last
            and state.model_set_digest == digest
        )
        # Association revisions, scrubs and consent expiry move no watermark: they count too.
        if covered:
            context = store._Context(session, agency_id, client_id, store._capture(state))
            covered = not context.state_slots()
        name = "caught_up" if covered else "behind"
    return {"state": name, "consumer": consumer, "current": current}


def runs(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    conversion_id: UUID,
    version_id: UUID | None,
    *,
    finance: bool,
) -> dict[str, Any]:
    state = session.get(AttributionConsumerState, client_id, populate_existing=True)
    conversion = session.scalar(
        select(AttributionConversion)
        .where(
            AttributionConversion.agency_id == agency_id,
            AttributionConversion.client_id == client_id,
            AttributionConversion.id == conversion_id,
        )
        .execution_options(populate_existing=True)
    )
    rows = versions(session, client_id)
    if version_id is None:
        version = next((row for row in rows if row.is_default), None)
    else:
        version = next((row for row in rows if row.id == version_id), None)
    if (
        state is None
        or conversion is None
        or version is None
        or conversion.generation > state.generation
    ):
        # An unknown, foreign or still staged conversion and an unknown version look the same.
        raise AccessDenied()
    if status(session, agency_id, client_id)["state"] != "caught_up":
        raise AttributionError(*STALE)
    if conversion.status == "active" and conversion.scrubbed_at is None:
        context = store._Context(session, agency_id, client_id, store._capture(state))
        latest = store.latest_runs(session, [conversion.id], through=state.generation)
        plan = store.plan_slot(
            context,
            store._row_slot(conversion),
            conversion,
            latest.get(conversion.id, {}),
            0,
            state.generation,
        )
        if plan.supersede is not None or plan.runs:
            raise AttributionError(*STALE)
    stored = list(
        session.scalars(
            select(AttributionRun)
            .where(
                AttributionRun.conversion_id == conversion.id,
                AttributionRun.model_version_id == version.id,
                AttributionRun.generation <= state.generation,
            )
            .order_by(AttributionRun.revision)
            .execution_options(populate_existing=True)
        )
    )
    run_ids = [run.id for run in stored]
    allocations: dict[UUID, list] = {}
    changes: dict[UUID, list] = {}
    if run_ids:
        for row in session.scalars(
            select(AttributionAllocation)
            .where(AttributionAllocation.run_id.in_(run_ids))
            .order_by(AttributionAllocation.run_id, AttributionAllocation.ordinal)
            .execution_options(populate_existing=True)
        ):
            allocations.setdefault(row.run_id, []).append(row)
        for row in session.scalars(
            select(AttributionCreditChange)
            .where(AttributionCreditChange.run_id.in_(run_ids))
            .order_by(AttributionCreditChange.run_id, AttributionCreditChange.ordinal)
            .execution_options(populate_existing=True)
        ):
            changes.setdefault(row.run_id, []).append(row)
    sale = conversion.kind == "sale"
    money = sale and finance
    amounts = "not_applicable" if not sale else "available" if finance else "permission_unavailable"
    return {
        "generation": state.generation,
        "conversion": {
            "id": str(conversion.id),
            "kind": conversion.kind,
            "status": conversion.status,
            "effective_at": _iso(conversion.effective_at),
            "superseded_at": _iso(conversion.superseded_at),
            "superseded_reason": conversion.superseded_reason,
            "scrubbed": conversion.scrubbed_at is not None,
            "person_id": str(conversion.owner_person_id) if conversion.owner_person_id else None,
            "lead_event_id": str(conversion.lead_event_id) if conversion.lead_event_id else None,
            "transaction": {
                "state": amounts,
                "source_account_id": conversion.source_account_id if money else None,
                "sale_operation_id": conversion.sale_operation_id if money else None,
            },
        },
        "model_version": view(version),
        "runs": [
            _run(run, allocations.get(run.id, []), changes.get(run.id, []), amounts, money)
            for run in stored
        ],
    }


def _share(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def _text(value) -> str | None:
    return str(value) if value is not None else None


def _run(run: AttributionRun, allocations, changes, amounts: str, money: bool) -> dict[str, Any]:
    return {
        "revision": run.revision,
        "status": run.status,
        "basis": run.basis,
        "causes": list(run.causes),
        "recorded_at": _iso(run.recorded_at),
        "window_start": _iso(run.window_start),
        "window_end": _iso(run.window_end),
        "amounts": amounts,
        "currency": run.currency if money else None,
        "currency_exponent": run.currency_exponent if money else None,
        "verified_net_minor": run.verified_net_minor if money else None,
        "ledger_generation": run.ledger_generation,
        "receipt_ordinal": run.receipt_ordinal,
        "identity_seq": run.identity_seq,
        "touch_bound_exceeded": run.touch_bound_exceeded,
        "allocations": [
            {
                "ordinal": row.ordinal,
                "credited": row.credited,
                "recipient": row.recipient,
                "basis": row.basis,
                "position": row.position,
                "share": _share(row.share_numerator, row.share_denominator),
                "amount_minor": row.amount_minor if money else None,
                "touchpoint_id": _text(row.touchpoint_id),
                "evidence_class": row.evidence_class,
                "occurred_at": _iso(row.occurred_at),
                "source": row.source,
                "campaign_ref": row.campaign_ref,
                "content_ref": row.content_ref,
                "link_ref": _text(row.link_ref),
            }
            for row in allocations
        ],
        "differences": [
            {
                "ordinal": row.ordinal,
                "effective_at": _iso(row.effective_at),
                "recipient": row.recipient,
                "touchpoint_id": _text(row.touchpoint_id),
                "source": row.source,
                "campaign_ref": row.campaign_ref,
                "content_ref": row.content_ref,
                "link_ref": _text(row.link_ref),
                "delta_share": _share(row.delta_share_numerator, row.delta_share_denominator),
                "delta_minor": row.delta_minor if money else None,
            }
            for row in changes
        ],
        "excluded": [
            {"touchpoint_id": _text(touch), "reason": reason}
            for touch, reason in zip(run.excluded_touchpoint_ids, run.excluded_reasons, strict=True)
        ],
    }
