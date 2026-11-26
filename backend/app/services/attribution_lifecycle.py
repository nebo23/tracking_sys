"""Lifecycle of derived attribution rows (specification 008-B, D-079 decision D12).

Run by the lifecycle runner as tracking_lifecycle, bounded by its batch size:

- attribution_staging: a consumer in the failed state loses the rows of its staging generation
  (credit changes, allocations, runs, then conversions), its staged supersessions are undone
  and its state is reset, so the next worker pass starts again from the published state.
  Published rows are never deleted.
- attribution_scrubbed: a safety net. A stored conversion whose owner no longer exists is
  scrubbed like any removal (the removal paths already do this in their own transactions).

Nothing here updates a share, an amount, a currency, a reporting date or provenance. Person
pointers otherwise follow identity retention through the identity lifecycle steps, which call
the scrub when a person or its evidence expires.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, delete, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    AttributionAllocation,
    AttributionConsumerState,
    AttributionConversion,
    AttributionCreditChange,
    AttributionRun,
    IdentitySubject,
)
from app.services import attribution_scrub

CLEARED = {
    "unit_kind": None,
    "staging_generation": None,
    "target_ledger_generation": None,
    "target_receipt_ordinal": None,
    "target_identity_seq": None,
    "target_model_set_digest": None,
    "unit_started_at": None,
    "progress_key": None,
    "failure_code": None,
}


def _discard(session: Session, client_id: UUID, staging: int, size: int) -> tuple[int, bool]:
    """Delete one bounded batch of a staging generation; returns (rows, whether more remain)."""
    runs = list(
        session.scalars(
            select(AttributionRun.id)
            .where(AttributionRun.client_id == client_id, AttributionRun.generation == staging)
            .order_by(AttributionRun.id)
            .limit(size)
        )
    )
    if runs:
        for model in (AttributionCreditChange, AttributionAllocation):
            session.execute(delete(model).where(model.run_id.in_(runs)))
        session.execute(delete(AttributionRun).where(AttributionRun.id.in_(runs)))
        if len(runs) == size:
            return len(runs), True
    conversions = list(
        session.scalars(
            select(AttributionConversion.id)
            .where(
                AttributionConversion.client_id == client_id,
                AttributionConversion.generation == staging,
            )
            .order_by(AttributionConversion.id)
            .limit(size)
        )
    )
    if conversions:
        session.execute(
            delete(AttributionConversion).where(AttributionConversion.id.in_(conversions))
        )
    return len(runs) + len(conversions), len(conversions) == size


def run(connection: Connection, cutoff: datetime, size: int) -> dict[str, int]:
    """One bounded attribution step; returns only non-zero counts."""
    counts = {"attribution_staging": 0, "attribution_scrubbed": 0}
    # A savepoint inside the runner's transaction: commit() releases it; the runner commits.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        failed = list(
            session.scalars(
                select(AttributionConsumerState)
                .where(AttributionConsumerState.status == "failed")
                .order_by(AttributionConsumerState.client_id)
                .limit(size)
                .with_for_update(skip_locked=True)
            )
        )
        for state in failed:
            staging, more = state.staging_generation, False
            if staging is not None:
                removed, more = _discard(session, state.client_id, staging, size)
                counts["attribution_staging"] += removed
                if not more:
                    # The staged supersessions never became visible: undo them.
                    session.execute(
                        update(AttributionConversion)
                        .where(
                            AttributionConversion.client_id == state.client_id,
                            AttributionConversion.superseded_generation == staging,
                            AttributionConversion.status == "active",
                        )
                        .values(
                            superseded_generation=None,
                            superseded_at=None,
                            superseded_reason=None,
                        )
                        .execution_options(synchronize_session=False)
                    )
            if more:
                continue
            session.execute(
                update(AttributionConsumerState)
                .where(AttributionConsumerState.client_id == state.client_id)
                .values(
                    status="ready" if state.generation >= 1 else "building",
                    version=AttributionConsumerState.version + 1,
                    updated_at=func.clock_timestamp(),
                    **CLEARED,
                )
                .execution_options(synchronize_session=False)
            )
        dangling = session.execute(
            select(
                AttributionConversion.id,
                AttributionConversion.agency_id,
                AttributionConversion.client_id,
            )
            .where(
                AttributionConversion.owner_person_id.is_not(None),
                AttributionConversion.scrubbed_at.is_(None),
                ~select(IdentitySubject.id)
                .where(IdentitySubject.id == AttributionConversion.owner_person_id)
                .exists(),
            )
            .order_by(AttributionConversion.id)
            .limit(size)
        ).all()
        clients: dict[tuple[UUID, UUID], list[UUID]] = {}
        for conversion_id, agency_id, client_id in dangling:
            clients.setdefault((agency_id, client_id), []).append(conversion_id)
        for (agency_id, client_id), conversions in sorted(clients.items(), key=str):
            attribution_scrub.bump(session, agency_id, client_id)
            counts["attribution_scrubbed"] += attribution_scrub.scrub_conversions(
                session, client_id, conversions, cutoff
            )
        session.commit()
    finally:
        session.close()
    return {name: value for name, value in counts.items() if value}
