"""Persisted revenue journal over revenue_evidence (specification 007-B, D-075 J8, J9, J11).

Every stored evidence row of a client receives one immutable receipt position in the published
generation, in receipt order (received_at from the revenue lock's clock, then the insertion
sequence), including held, conflicting and unverified evidence; an exact redelivery stores no
evidence and therefore no receipt. A receipt is applied under the client revenue lock in the
transaction that stores its evidence:

1. The eligible log is every row up to and including this receipt, minus the Paymob refunds held
   at this receipt by the D-070 signed-order rule; a later sale that proves a matching order
   makes a held refund take effect at that later receipt, and no earlier receipt changes.
2. The 007-A calculation over that log is compared with the persisted current postings, and the
   necessary releases and postings are appended (app.ledger.next_movements), exactly as
   calculate() would derive them for the same log.
3. The receipt (input, previous and receipt digests of the ledger_feed chain, the outcome and
   the closing states of the transactions it moved or changed), its movements, the replaced
   transaction projections and the advanced cursors commit together; if anything fails,
   nothing advances.

Readers never rebuild receipt prefixes: they load the evidence once, derive the current view in
one pass and use the stored movements. They fail closed with ledger_projection_unavailable
while no ready generation exists or the published cursor is behind the stored evidence. A new
client's projection starts with its first evidence row; a client whose evidence predates the
projection needs the operator backfill (app.ledger_backfill). Amounts stay in their original
currency and minor units.
"""

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.attribution.engine import (
    JOURNAL_START,
    JournalItem,
    SaleState,
    receipt_digest,
    receipt_payload,
    sale_states,
)
from app.ledger import (
    Currency,
    Evidence,
    LedgerCalculation,
    LedgerInputError,
    LedgerScope,
    Money,
    Movement,
    MovementType,
    OperationKind,
    RevenueEntry,
    next_movements,
)
from app.models import (
    LedgerMovement,
    LedgerProjectionState,
    LedgerReceipt,
    LedgerTransaction,
    RevenueEvidence,
)

ALGORITHM = "007-A.1/D-070"


class LedgerUnavailable(Exception):
    """The persisted projection is not ready or is behind the stored evidence (retryable)."""

    code = "ledger_projection_unavailable"
    status = 503


Key = tuple[LedgerScope, str]


def evidence_of(row: RevenueEvidence) -> Evidence:
    from app.services.revenue import _evidence

    return _evidence(row)


def held_ids(rows: Sequence[RevenueEvidence]) -> set[UUID]:
    from app.services.revenue import unbound_refunds

    return unbound_refunds(rows)


def _currency(code: str, exponent: int) -> Currency:
    return Currency(code, exponent)


def _entry_json(entry: RevenueEntry) -> dict[str, Any]:
    return {
        "operation_id": entry.operation_id,
        "kind": entry.kind.value,
        "amount_minor": entry.amount.minor,
        "effective_at": entry.effective_at.isoformat(),
        "parent_operation_id": entry.parent_operation_id,
    }


def committed_from(rows: Iterable[LedgerTransaction], agency_id: UUID) -> dict[Key, RevenueEntry]:
    committed: dict[Key, RevenueEntry] = {}
    for row in rows:
        scope = LedgerScope(agency_id, row.client_id, row.source_account_id)
        currency = _currency(row.currency, row.currency_exponent)
        for item in row.entries:
            committed[(scope, item["operation_id"])] = RevenueEntry(
                scope,
                row.operation_id,
                item["operation_id"],
                OperationKind(item["kind"]),
                Money(item["amount_minor"], currency),
                datetime.fromisoformat(item["effective_at"]),
                item["parent_operation_id"],
                (),
            )
    return committed


def states_from(rows: Iterable[LedgerTransaction], agency_id: UUID) -> dict[Key, SaleState]:
    return {
        (LedgerScope(agency_id, row.client_id, row.source_account_id), row.operation_id): SaleState(
            LedgerScope(agency_id, row.client_id, row.source_account_id),
            row.operation_id,
            _currency(row.currency, row.currency_exponent),
            row.sale_effective_at,
            row.net,
        )
        for row in rows
    }


def _state_json(state: SaleState) -> dict[str, Any]:
    return {
        "source_account_id": state.scope.source_account_id,
        "transaction_id": state.transaction_id,
        "currency": state.currency.code,
        "exponent": state.currency.exponent,
        "effective_at": state.effective_at.isoformat(),
        "net_minor": state.net_minor,
    }


def _state_from_json(item: dict[str, Any], agency_id: UUID, client_id: UUID) -> SaleState:
    return SaleState(
        LedgerScope(agency_id, client_id, item["source_account_id"]),
        item["transaction_id"],
        _currency(item["currency"], item["exponent"]),
        datetime.fromisoformat(item["effective_at"]),
        item["net_minor"],
    )


@dataclass
class Cursor:
    """The progress of one generation while receipts are applied."""

    generation: int
    ordinal: int
    movement: int
    digest: bytes
    committed: dict[Key, RevenueEntry]
    states: dict[Key, SaleState]


@dataclass
class Applied:
    receipt: LedgerReceipt
    movements: list[LedgerMovement]
    calculation: LedgerCalculation
    changed: set[Key]


def apply_one(
    agency_id: UUID,
    client_id: UUID,
    rows: Sequence[RevenueEvidence],
    cursor: Cursor,
    evidence: dict[UUID, Evidence] | None = None,
) -> Applied:
    """Compute the receipt of rows[-1] given the log rows (its whole prefix) and the cursor,
    and advance the cursor in memory. Nothing is written here."""
    current = rows[-1]
    held = held_ids(rows)
    cache = evidence if evidence is not None else {}
    for row in rows:
        if row.id not in cache:
            cache[row.id] = evidence_of(row)
    log = [cache[row.id] for row in rows if row.id not in held]
    trigger = cache[current.id]
    before = dict(cursor.committed)
    movements, calculation = next_movements(cursor.committed, log, trigger, cursor.movement + 1)
    current_states = sale_states(calculation)
    moved = {(item.scope, item.transaction_id) for item in movements}
    changed = {
        key
        for key in current_states
        if key in moved or cursor.states.get(key) != current_states[key]
    }
    closing = [current_states[key] for key in sorted(current_states) if key in changed]
    if current.id in held:
        outcome = "held"
    else:
        outcome = next(
            item.disposition.value for item in calculation.outcomes if item.evidence is trigger
        )
    posted = {
        (entry.scope, entry.operation_id): entry
        for transaction in calculation.transactions
        for entry in transaction.entries
    }
    payload = receipt_payload(trigger).encode("utf-8")
    digest = receipt_digest(cursor.digest, trigger)
    receipt = LedgerReceipt(
        id=uuid4(),
        agency_id=agency_id,
        client_id=client_id,
        generation=cursor.generation,
        receipt_ordinal=cursor.ordinal + 1,
        evidence_id=current.id,
        evidence_sequence=current.sequence,
        input_digest=hashlib.sha256(payload).digest(),
        previous_digest=cursor.digest,
        receipt_digest=digest,
        outcome=outcome,
        closing_states=[_state_json(item) for item in closing],
    )
    rows_out = []
    for movement in movements:
        key = (movement.scope, movement.operation_id)
        source = posted.get(key) if movement.movement is MovementType.POSTING else before.get(key)
        rows_out.append(
            LedgerMovement(
                id=uuid4(),
                agency_id=agency_id,
                client_id=client_id,
                generation=cursor.generation,
                movement_sequence=movement.sequence,
                receipt_id=receipt.id,
                source_account_id=movement.scope.source_account_id,
                transaction_id=movement.transaction_id,
                operation_id=movement.operation_id,
                kind=movement.kind.value,
                direction=movement.movement.value,
                amount_minor=movement.amount.minor,
                currency=movement.amount.currency.code,
                currency_exponent=movement.amount.currency.exponent,
                effective_at=source.effective_at,
                trigger_evidence_id=current.id,
                reason=movement.reason,
            )
        )
    cursor.ordinal += 1
    cursor.movement += len(movements)
    cursor.digest = digest
    cursor.states = current_states
    return Applied(receipt, rows_out, calculation, changed)


def write_transactions(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    generation: int,
    calculation: LedgerCalculation,
    evidence_ids: dict[int, UUID],
    revision: dict[Key, int],
) -> None:
    """Replace the transaction projections whose content changed (revision maps each changed
    key to the receipt ordinal that changed it)."""
    existing = {
        (row.source_account_id, row.operation_id): row
        for row in session.scalars(
            select(LedgerTransaction).where(
                LedgerTransaction.client_id == client_id, LedgerTransaction.generation == generation
            )
        )
    }
    seen = set()
    for transaction in calculation.transactions:
        key = (transaction.scope, transaction.operation_id)
        short = (transaction.scope.source_account_id, transaction.operation_id)
        seen.add(short)
        if key not in revision and short in existing:
            continue
        totals = transaction.totals
        values = {
            "currency": transaction.currency.code,
            "currency_exponent": transaction.currency.exponent,
            "sale_effective_at": transaction.sale.effective_at,
            "captured": totals.captured,
            "refunded": totals.refunded,
            "charged_back": totals.charged_back,
            "reversed": totals.reversed,
            "corrected": totals.corrected,
            "net": totals.net,
            "entries": [_entry_json(entry) for entry in transaction.entries],
            "evidence_ids": sorted(
                {
                    evidence_ids[id(item)]
                    for entry in transaction.entries
                    for item in entry.evidence
                    if id(item) in evidence_ids
                },
                key=str,
            ),
            "financial_revision": revision.get(key, 0),
        }
        row = existing.get(short)
        if row is None:
            session.add(
                LedgerTransaction(
                    id=uuid4(),
                    agency_id=agency_id,
                    client_id=client_id,
                    generation=generation,
                    source_account_id=transaction.scope.source_account_id,
                    operation_id=transaction.operation_id,
                    **values,
                )
            )
        else:
            for name, value in values.items():
                setattr(row, name, value)
    for short, row in existing.items():
        if short not in seen:
            session.delete(row)
    session.flush()


def _new_state(agency_id: UUID, client_id: UUID) -> LedgerProjectionState:
    return LedgerProjectionState(
        client_id=client_id,
        agency_id=agency_id,
        generation=1,
        algorithm=ALGORITHM,
        status="ready",
        last_evidence_sequence=0,
        receipt_ordinal=0,
        movement_sequence=0,
        receipt_digest=JOURNAL_START,
        financial_revision=0,
    )


def on_evidence_stored(session: Session, agency_id: UUID, client_id: UUID, row_id: UUID) -> None:
    """Apply the receipt of one newly stored evidence row (the caller holds the revenue lock)."""
    state = session.scalar(
        select(LedgerProjectionState)
        .where(LedgerProjectionState.client_id == client_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if state is None:
        earlier = session.scalar(
            select(RevenueEvidence.id)
            .where(RevenueEvidence.client_id == client_id, RevenueEvidence.id != row_id)
            .limit(1)
        )
        if earlier is not None:
            return  # existing history: the operator backfill builds and publishes the journal
        state = _new_state(agency_id, client_id)
        session.add(state)
        session.flush()
    if state.status != "ready":
        return
    from app.services.revenue import load_rows

    rows = load_rows(session, agency_id, client_id)
    if not rows or rows[-1].id != row_id:
        # A receipt position never moves: a clock behind the published log refuses the write.
        raise LedgerInputError("clock_moved_backwards")
    preceding = rows[-2].sequence if len(rows) > 1 else 0
    if state.last_evidence_sequence != preceding:
        # The projection is behind (a large import or legacy evidence): it stays behind, and
        # reads fail closed until the operator backfill catches up. Intake is never blocked.
        return
    previous = list(
        session.scalars(
            select(LedgerTransaction).where(
                LedgerTransaction.client_id == client_id,
                LedgerTransaction.generation == state.generation,
            )
        )
    )
    cursor = Cursor(
        state.generation,
        state.receipt_ordinal,
        state.movement_sequence,
        state.receipt_digest,
        committed_from(previous, agency_id),
        states_from(previous, agency_id),
    )
    evidence: dict[UUID, Evidence] = {}
    applied = apply_one(agency_id, client_id, rows, cursor, evidence)
    session.add(applied.receipt)
    session.flush()
    session.add_all(applied.movements)
    ids = {id(item): row_id_ for row_id_, item in evidence.items()}
    write_transactions(
        session,
        agency_id,
        client_id,
        state.generation,
        applied.calculation,
        ids,
        dict.fromkeys(applied.changed, cursor.ordinal),
    )
    state.receipt_ordinal = cursor.ordinal
    state.movement_sequence = cursor.movement
    state.receipt_digest = cursor.digest
    state.last_evidence_sequence = rows[-1].sequence
    state.last_received_at = rows[-1].received_at
    state.financial_revision = cursor.ordinal
    state.updated_at = func.now()
    session.flush()


def require_current(
    session: Session, agency_id: UUID, client_id: UUID, rows: Sequence[RevenueEvidence]
) -> LedgerProjectionState | None:
    """The published state when it covers every stored row; None for a client without
    evidence; LedgerUnavailable otherwise (never an older generation served as current)."""
    if not rows:
        return None
    state = session.scalar(
        select(LedgerProjectionState).where(
            LedgerProjectionState.agency_id == agency_id,
            LedgerProjectionState.client_id == client_id,
        )
    )
    latest = max(row.sequence for row in rows)
    if state is None or state.status != "ready" or state.last_evidence_sequence != latest:
        raise LedgerUnavailable()
    return state


def stored_movements(
    session: Session, state: LedgerProjectionState, evidence: dict[UUID, Evidence]
) -> tuple[Movement, ...]:
    result = []
    for row in session.scalars(
        select(LedgerMovement)
        .where(
            LedgerMovement.client_id == state.client_id,
            LedgerMovement.generation == state.generation,
        )
        .order_by(LedgerMovement.movement_sequence)
    ):
        result.append(
            Movement(
                row.movement_sequence,
                LedgerScope(state.agency_id, state.client_id, row.source_account_id),
                row.transaction_id,
                row.operation_id,
                OperationKind(row.kind),
                MovementType(row.direction),
                Money(row.amount_minor, _currency(row.currency, row.currency_exponent)),
                evidence[row.trigger_evidence_id],
                row.reason,
            )
        )
    return tuple(result)


def stored_journal(
    session: Session,
    state: LedgerProjectionState,
    movements: Sequence[Movement],
) -> tuple[JournalItem, ...]:
    """The transport journal of the published generation: one receipt per stored evidence row,
    its movements, and the closing states on its last item (JournalItem contract of 008-A)."""
    by_receipt: dict[UUID, list[Movement]] = {}
    sequences = {
        row.movement_sequence: row.receipt_id
        for row in session.execute(
            select(LedgerMovement.movement_sequence, LedgerMovement.receipt_id).where(
                LedgerMovement.client_id == state.client_id,
                LedgerMovement.generation == state.generation,
            )
        )
    }
    for movement in movements:
        by_receipt.setdefault(sequences[movement.sequence], []).append(movement)
    items: list[JournalItem] = []
    for receipt in session.scalars(
        select(LedgerReceipt)
        .where(
            LedgerReceipt.client_id == state.client_id,
            LedgerReceipt.generation == state.generation,
        )
        .order_by(LedgerReceipt.receipt_ordinal)
    ):
        parts: list[Movement | None] = list(by_receipt.get(receipt.id, [])) or [None]
        closing = tuple(
            _state_from_json(item, state.agency_id, state.client_id)
            for item in receipt.closing_states
        )
        for index, movement in enumerate(parts, start=1):
            items.append(
                JournalItem(
                    receipt.receipt_ordinal,
                    index,
                    len(parts),
                    movement,
                    closing if index == len(parts) else (),
                    previous_digest=receipt.previous_digest,
                    receipt_digest=receipt.receipt_digest,
                )
            )
    return tuple(items)


# ---------------------------------------------------------------------------------------------
# Movements read and reconciliation (J9).


def movements_page(
    session: Session,
    state: LedgerProjectionState | None,
    *,
    after: int = 0,
    generation: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Generation-bound keyset pages of the movement journal, with receipt provenance."""
    if state is None:
        return {"generation": None, "financial_revision": 0, "movements": [], "next_after": None}
    if generation is not None and generation != state.generation:
        raise LedgerConflict("ledger_generation_changed")
    rows = list(
        session.execute(
            select(LedgerMovement, LedgerReceipt.receipt_ordinal)
            .join(LedgerReceipt, LedgerReceipt.id == LedgerMovement.receipt_id)
            .where(
                LedgerMovement.client_id == state.client_id,
                LedgerMovement.generation == state.generation,
                LedgerMovement.movement_sequence > after,
            )
            .order_by(LedgerMovement.movement_sequence)
            .limit(limit + 1)
        )
    )
    page = rows[:limit]
    return {
        "generation": state.generation,
        "financial_revision": state.financial_revision,
        "movements": [
            {
                "sequence": row.movement_sequence,
                "receipt": ordinal,
                "source_account_id": row.source_account_id,
                "transaction_id": row.transaction_id,
                "operation_id": row.operation_id,
                "kind": row.kind,
                "direction": row.direction,
                "amount_minor": row.amount_minor,
                "currency": row.currency,
                "currency_exponent": row.currency_exponent,
                "effective_at": row.effective_at,
                "trigger_evidence_id": str(row.trigger_evidence_id),
                "reason": row.reason,
            }
            for row, ordinal in page
        ],
        "next_after": page[-1][0].movement_sequence if len(rows) > limit else None,
    }


class LedgerConflict(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Issue:
    issue_id: UUID
    kind: str  # reconciliation, pending or held
    reason: str
    source_account_id: str
    operation_id: str
    evidence_ids: tuple[UUID, ...]
    fingerprint: str


def _issue_id(client_id: UUID, kind: str, scope: LedgerScope, operation_id: str, reason: str):
    raw = json.dumps([str(client_id), kind, scope.source_account_id, operation_id, reason])
    return UUID(hashlib.sha256(raw.encode()).hexdigest()[:32])


def issues(ledger, client_id: UUID) -> list[Issue]:
    """Open reconciliation, pending and held items of the current calculation, with a stable
    ID and a fingerprint of the evidence they rest on."""
    ids = ledger.evidence_ids_by_object()
    found = []

    def add(kind, scope, operation_id, reason, evidence):
        evidence_ids = tuple(
            sorted({ids[id(item)] for item in evidence if id(item) in ids}, key=str)
        )
        fingerprint = hashlib.sha256(
            json.dumps([kind, reason, [str(item) for item in evidence_ids]]).encode()
        ).hexdigest()
        found.append(
            Issue(
                _issue_id(client_id, kind, scope, operation_id, reason),
                kind,
                reason,
                scope.source_account_id,
                operation_id,
                evidence_ids,
                fingerprint,
            )
        )

    for item in ledger.calculation.reconciliation:
        add("reconciliation", item.scope, item.operation_id, item.reason.value, item.evidence)
    for item in ledger.calculation.pending:
        add("pending", item.scope, item.operation_id, item.status_reason or "", item.evidence)
    for item in ledger.held:
        add("held", item.scope, item.operation_id, "parent_order_mismatch", (item,))
    return found


def discard_generation(session: Session, client_id: UUID, generation: int) -> None:
    """Operator-only: remove an unpublished staging generation (migration role)."""
    session.execute(
        delete(LedgerMovement).where(
            LedgerMovement.client_id == client_id, LedgerMovement.generation == generation
        )
    )
    session.execute(
        delete(LedgerReceipt).where(
            LedgerReceipt.client_id == client_id, LedgerReceipt.generation == generation
        )
    )
    session.execute(
        delete(LedgerTransaction).where(
            LedgerTransaction.client_id == client_id, LedgerTransaction.generation == generation
        )
    )
