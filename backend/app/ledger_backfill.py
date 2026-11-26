"""Operator backfill of a client's persisted revenue journal (specification 007-B, D-075 J7, J8).

Usage (operator, migration role, disposable or authorized databases only):

    python -m app.ledger_backfill --agency <uuid> --client <uuid> [--batch 200] [--restart]

The journal is rebuilt from revenue_evidence in its original receipt order, reconstructing the
state as known after each receipt (the D-070 hold rule is evaluated per receipt, never with the
final filter applied to every prefix). Receipts and movements are written to a staging
generation in bounded batches, outside the revenue lock, so intake keeps working; an interrupted
run resumes from its last staging receipt. Publication takes the client revenue lock, catches
up with evidence stored meanwhile, writes the transaction projections and switches the
published generation only if the generation captured at registration and the staging
generation are both unchanged (compare-and-swap). A failed swap discards the staging rows and
changes nothing current. Readers see only the published generation; earlier generations are
retired, never updated. This is administrative tooling, not a runtime permission.
"""

import argparse
import sys
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.attribution.engine import JOURNAL_START, sale_states
from app.ledger import (
    Currency,
    Evidence,
    LedgerScope,
    Money,
    OperationKind,
    RevenueEntry,
    current_calculation,
)
from app.models import (
    ClientWorkspace,
    LedgerMovement,
    LedgerProjectionState,
    LedgerReceipt,
)
from app.services.ledger_store import (
    ALGORITHM,
    Cursor,
    apply_one,
    discard_generation,
    evidence_of,
    held_ids,
    write_transactions,
)
from app.services.revenue import load_rows, lock_revenue


def _register(session: Session, agency_id: UUID, client_id: UUID, restart: bool):
    state = session.scalar(
        select(LedgerProjectionState)
        .where(LedgerProjectionState.client_id == client_id)
        .with_for_update()
    )
    if state is None:
        state = LedgerProjectionState(
            client_id=client_id,
            agency_id=agency_id,
            generation=0,
            algorithm=ALGORITHM,
            status="building",
            receipt_digest=JOURNAL_START,
        )
        session.add(state)
        session.flush()
    previous = state.staging_generation
    if previous is not None and restart:
        discard_generation(session, client_id, previous)
        state.staging_generation = None
    if state.staging_generation is None:
        # A staging number is never reused: above the published, the abandoned and every
        # generation that still has rows.
        highest = session.scalar(
            select(func.max(LedgerReceipt.generation)).where(LedgerReceipt.client_id == client_id)
        )
        state.staging_generation = max(state.generation, previous or 0, highest or 0) + 1
    session.flush()
    return state.generation, state.staging_generation


def _cursor(session: Session, agency_id: UUID, client_id: UUID, staging: int, rows, cache):
    last = session.scalar(
        select(LedgerReceipt)
        .where(LedgerReceipt.client_id == client_id, LedgerReceipt.generation == staging)
        .order_by(LedgerReceipt.receipt_ordinal.desc())
        .limit(1)
    )
    if last is None:
        return 0, Cursor(staging, 0, 0, JOURNAL_START, {}, {})
    position = next(index for index, row in enumerate(rows) if row.id == last.evidence_id) + 1
    committed: dict[tuple[LedgerScope, str], RevenueEntry] = {}
    for item in session.scalars(
        select(LedgerMovement)
        .where(LedgerMovement.client_id == client_id, LedgerMovement.generation == staging)
        .order_by(LedgerMovement.movement_sequence)
    ):
        scope = LedgerScope(agency_id, client_id, item.source_account_id)
        key = (scope, item.operation_id)
        if item.direction == "release":
            committed.pop(key, None)
            continue
        committed[key] = RevenueEntry(
            scope,
            item.transaction_id,
            item.operation_id,
            OperationKind(item.kind),
            Money(item.amount_minor, Currency(item.currency, item.currency_exponent)),
            item.effective_at,
            None,
            (),
        )
    movement = session.scalar(
        select(func.max(LedgerMovement.movement_sequence)).where(
            LedgerMovement.client_id == client_id, LedgerMovement.generation == staging
        )
    )
    prefix = rows[:position]
    held = held_ids(prefix)
    for row in prefix:
        cache.setdefault(row.id, evidence_of(row))
    states = sale_states(current_calculation([cache[r.id] for r in prefix if r.id not in held]))
    return position, Cursor(
        staging, last.receipt_ordinal, movement or 0, last.receipt_digest, committed, states
    )


def _apply_range(session, agency_id, client_id, rows, start, stop, cursor, cache) -> None:
    for index in range(start, stop):
        applied = apply_one(agency_id, client_id, rows[: index + 1], cursor, cache)
        session.add(applied.receipt)
        session.flush()
        session.add_all(applied.movements)
        session.flush()


def backfill(
    engine: Engine,
    agency_id: UUID,
    client_id: UUID,
    *,
    batch_size: int = 200,
    restart: bool = False,
    stop_after_batches: int | None = None,
    before_publish: Callable[[], None] | None = None,
) -> str:
    """Build, resume and publish a client's journal; returns published, interrupted, conflict
    or refused (the agency does not own the client, R0607-18: nothing is changed)."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    with Session(engine) as session:
        owned = session.scalar(
            select(ClientWorkspace.id).where(
                ClientWorkspace.id == client_id, ClientWorkspace.agency_id == agency_id
            )
        )
    if owned is None:
        return "refused"
    with Session(engine) as session, session.begin():
        captured, staging = _register(session, agency_id, client_id, restart)
    batches = 0
    while True:
        with Session(engine) as session, session.begin():
            rows = load_rows(session, agency_id, client_id)
            cache: dict[UUID, Evidence] = {}
            start, cursor = _cursor(session, agency_id, client_id, staging, rows, cache)
            if start >= len(rows):
                break
            _apply_range(
                session,
                agency_id,
                client_id,
                rows,
                start,
                min(len(rows), start + batch_size),
                cursor,
                cache,
            )
        batches += 1
        if stop_after_batches is not None and batches >= stop_after_batches:
            return "interrupted"
    if before_publish is not None:
        before_publish()
    with Session(engine) as session, session.begin():
        lock_revenue(session, client_id)
        state = session.scalar(
            select(LedgerProjectionState)
            .where(LedgerProjectionState.client_id == client_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if state is None or state.generation != captured or state.staging_generation != staging:
            # Only this run's own unpublished rows are discarded, never a published generation.
            if state is None or staging not in (state.generation, state.staging_generation):
                discard_generation(session, client_id, staging)
            return "conflict"
        rows = load_rows(session, agency_id, client_id)
        cache = {}
        start, cursor = _cursor(session, agency_id, client_id, staging, rows, cache)
        _apply_range(session, agency_id, client_id, rows, start, len(rows), cursor, cache)
        for row in rows:
            cache.setdefault(row.id, evidence_of(row))
        held = held_ids(rows)
        final = current_calculation([cache[row.id] for row in rows if row.id not in held])
        revision: dict[tuple[LedgerScope, str], int] = {}
        for receipt in session.scalars(
            select(LedgerReceipt)
            .where(LedgerReceipt.client_id == client_id, LedgerReceipt.generation == staging)
            .order_by(LedgerReceipt.receipt_ordinal)
        ):
            for item in receipt.closing_states:
                scope = LedgerScope(agency_id, client_id, item["source_account_id"])
                revision[(scope, item["transaction_id"])] = receipt.receipt_ordinal
        ids = {id(item): key for key, item in cache.items()}
        write_transactions(session, agency_id, client_id, staging, final, ids, revision)
        state.generation, state.staging_generation, state.status = staging, None, "ready"
        state.receipt_ordinal, state.movement_sequence = cursor.ordinal, cursor.movement
        state.receipt_digest = cursor.digest
        state.last_evidence_sequence = rows[-1].sequence if rows else 0
        state.last_received_at = rows[-1].received_at if rows else None
        state.financial_revision = cursor.ordinal
        state.updated_at = func.now()
        session.flush()
    return "published"


def main(argv: list[str] | None = None) -> int:
    from app.config import MigrationSettings
    from app.database import create_database_engine

    parser = argparse.ArgumentParser(description="Backfill one client's revenue journal.")
    parser.add_argument("--agency", type=UUID, required=True)
    parser.add_argument("--client", type=UUID, required=True)
    parser.add_argument("--batch", type=int, default=200)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args(argv)
    engine = create_database_engine(MigrationSettings())
    try:
        result = backfill(
            engine, args.agency, args.client, batch_size=args.batch, restart=args.restart
        )
    finally:
        engine.dispose()
    print(result)
    return 0 if result == "published" else 1


if __name__ == "__main__":
    sys.exit(main())
