"""Persisted revenue evidence and the ledger read (specification 015-A, D-067 D2 and D11).

Every intake path (the Paymob callback of 015-B, the CSV commit and the manual declaration of
015-C) appends 007-A Evidence records through append_evidence while holding the client's revenue
lock, whose clock read is the receipt time. Receipts of one client are therefore increasing in
commit order, which keeps the 007-A journal-prefix property: a journal returned earlier is a
prefix of the journal returned with more evidence. Nothing updates or deletes evidence.

Since 007-B (D-075 J8) every stored record also receives a persisted receipt in the same
transaction (app.services.ledger_store). client_ledger loads a client's records in receipt order
once, derives the current 007-A view in one pass and returns the stored movements and the
stored receipt journal, which 008-A attribution and 014-B conversion delivery consume through
the same contracts; no receipt prefix is recalculated on a read, and a read fails closed with
ledger_projection_unavailable while the published projection is behind the stored evidence.
revenue_view shapes the finance:read answer: verified totals and transactions,
declared (unverified) items and totals kept apart, pending adjustments and reconciliation items.
Amounts in different currencies are never added together.

A Paymob refund names its parent sale in an unsigned field (D-070, review finding R001). Intake
refuses one whose stored parent carries another signed order ID, but a refund can arrive before
its sale. client_ledger therefore holds back, before calculating, every Paymob refund whose
stored parent sales all carry another order ID: it never enters the calculation or any
movement, and revenue_view lists it as pending with the reason parent_order_mismatch. The
persisted journal evaluates this rule at each receipt: a held refund keeps its own receipt
position (without a movement), and a later sale record carrying its order ID makes it take
effect at that later receipt; no earlier receipt or movement is rewritten.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.advertising.currencies import decimal_text
from app.attribution import JournalItem
from app.ledger import (
    Currency,
    Evidence,
    EvidenceClass,
    LedgerCalculation,
    LedgerInputError,
    Money,
    OperationKind,
    Stream,
    current_calculation,
)
from app.models import RevenueEvidence
from app.payments.paymob import same_order
from app.services.collection import client_lock_key

# Advisory namespace of the client revenue lock (004 uses 4004, 003 uses 3003, 005 uses 5005,
# 009 uses 9009); the second key is the 004 client key derivation.
REVENUE_LOCK_NAMESPACE = 7007
LOCK_TIMEOUT = "2s"
INTAKES = ("paymob", "csv_import", "manual_entry")
VIEW_LIMIT = 1000

Intake = Literal["paymob", "csv_import", "manual_entry"]


# Take the client's revenue lock (waiting at most LOCK_TIMEOUT; a timeout surfaces as a retryable
# database error) and return the database clock read after it is held: the receipt time of the
# evidence appended in this transaction.
def lock_revenue(session: Session, client_id: UUID) -> datetime:
    session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    session.execute(
        select(func.pg_advisory_xact_lock(REVENUE_LOCK_NAMESPACE, client_lock_key(client_id)))
    )
    return session.scalar(select(func.clock_timestamp()))


# The 007-A payload of one record (every field except the receipt time) as canonical JSON. An
# exact redelivery repeats all of it; the effective time is compared as a UTC instant.
def _canonical(item: Evidence) -> str:
    return json.dumps(
        {
            "agency_id": str(item.agency_id),
            "client_id": str(item.client_id),
            "source_account_id": item.source_account_id,
            "delivery_id": item.delivery_id,
            "operation_id": item.operation_id,
            "kind": item.kind.value,
            "classification": item.classification.value,
            "currency": item.amount.currency.code,
            "exponent": item.amount.currency.exponent,
            "minor": item.amount.minor,
            "effective_at": item.effective_at.astimezone(UTC).isoformat(timespec="microseconds"),
            "parent_operation_id": item.parent_operation_id,
            "stream": item.stream.value,
            "reason": item.reason,
            "actor": item.actor,
            "source_reference": item.source_reference,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def content_digest(item: Evidence) -> str:
    return hashlib.sha256(_canonical(item).encode()).hexdigest()


# Append one record of a client's revenue stream. With project (the default) its receipt is
# applied in the same transaction; a large bounded import passes project=False and leaves the
# projection behind until the operator backfill catches up (007-B, D-075 J11, A3). The caller
# holds the client's revenue lock and passes its clock read as received_at. Returns "stored",
# or "duplicate" for an exact redelivery (same source account, delivery ID and content), which
# inserts nothing. A reused delivery ID
# with other content is stored, so the 007-A calculation reports it as delivery_id_reused.
def append_evidence(
    session: Session,
    item: Evidence,
    intake: Intake,
    intake_id: UUID | None,
    *,
    project: bool = True,
) -> Literal["stored", "duplicate"]:
    if item.stream is not Stream.CLIENT_REVENUE or item.client_id is None:
        raise LedgerInputError("invalid_stream")
    if intake not in INTAKES or (intake == "manual_entry") != (intake_id is None):
        raise LedgerInputError("invalid_intake")
    statement = (
        insert(RevenueEvidence)
        .values(
            id=uuid4(),
            agency_id=item.agency_id,
            client_id=item.client_id,
            delivery_id=item.delivery_id,
            source_account_id=item.source_account_id,
            operation_id=item.operation_id,
            kind=item.kind.value,
            classification=item.classification.value,
            currency=item.amount.currency.code,
            currency_exponent=item.amount.currency.exponent,
            amount_minor=item.amount.minor,
            effective_at=item.effective_at,
            received_at=item.received_at,
            parent_operation_id=item.parent_operation_id,
            reason=item.reason,
            actor=item.actor,
            source_reference=item.source_reference,
            intake=intake,
            intake_id=intake_id,
            content_digest=content_digest(item),
        )
        .on_conflict_do_nothing(constraint="uq_revenue_evidence_delivery")
        .returning(RevenueEvidence.id)
    )
    stored = session.scalar(statement)
    if stored is None:
        return "duplicate"
    # 007-B (D-075): the receipt, its movements and projections commit with the evidence.
    from app.services.ledger_store import on_evidence_stored

    if project:
        on_evidence_stored(session, item.agency_id, item.client_id, stored)
    return "stored"


def _evidence(row: RevenueEvidence) -> Evidence:
    return Evidence(
        delivery_id=row.delivery_id,
        agency_id=row.agency_id,
        client_id=row.client_id,
        source_account_id=row.source_account_id,
        operation_id=row.operation_id,
        kind=OperationKind(row.kind),
        classification=EvidenceClass(row.classification),
        amount=Money(row.amount_minor, Currency(row.currency, row.currency_exponent)),
        effective_at=row.effective_at,
        received_at=row.received_at,
        parent_operation_id=row.parent_operation_id,
        reason=row.reason,
        actor=row.actor,
        source_reference=row.source_reference,
    )


@dataclass(frozen=True)
class ClientLedger:
    """A client's stored evidence in receipt order, its calculation and its journal."""

    records: tuple[Evidence, ...]
    intakes: tuple[str, ...]  # the intake of each record, in the same order
    calculation: LedgerCalculation
    # Paymob refunds held back because no stored parent sale carries their signed order ID
    # (D-070); they are not part of records or the calculation.
    held: tuple[Evidence, ...] = ()
    # The stored receipt journal of the published generation (one receipt per stored record,
    # held ones included) and the evidence row IDs of records and held, in the same order.
    journal: tuple[JournalItem, ...] = ()
    record_ids: tuple[UUID, ...] = ()
    held_ids: tuple[UUID, ...] = ()
    generation: int | None = None
    financial_revision: int = 0

    def evidence_ids_by_object(self) -> dict[int, UUID]:
        mapping = {id(item): key for item, key in zip(self.records, self.record_ids, strict=False)}
        mapping.update({id(item): key for item, key in zip(self.held, self.held_ids, strict=False)})
        return mapping

    def intake_of(self, item: Evidence) -> str | None:
        for record, intake in zip(self.records, self.intakes, strict=True):
            if record is item:
                return intake
        return None


# The rows of one client in receipt order: received_at, then the insertion sequence.
def load_rows(session: Session, agency_id: UUID, client_id: UUID) -> list[RevenueEvidence]:
    return list(
        session.scalars(
            select(RevenueEvidence)
            .where(RevenueEvidence.agency_id == agency_id, RevenueEvidence.client_id == client_id)
            .order_by(RevenueEvidence.received_at, RevenueEvidence.sequence)
        )
    )


def load_evidence(session: Session, agency_id: UUID, client_id: UUID) -> list[Evidence]:
    return [_evidence(row) for row in load_rows(session, agency_id, client_id)]


# The IDs of the Paymob refunds whose named parent is a stored Paymob sale (of the same source
# account) that never carries the refund's signed order ID (D-070). A refund whose parent is not
# stored yet is not held: 007-A keeps it pending as parent_missing until the sale arrives.
def unbound_refunds(rows: Sequence[RevenueEvidence]) -> set[UUID]:
    sales: dict[tuple[str, str], list[str | None]] = {}
    for row in rows:
        if row.intake == "paymob" and row.kind == OperationKind.SALE.value:
            sales.setdefault((row.source_account_id, row.operation_id), []).append(
                row.source_reference
            )
    held: set[UUID] = set()
    for row in rows:
        if row.intake != "paymob" or row.kind != OperationKind.REFUND.value:
            continue
        parents = sales.get((row.source_account_id, row.parent_operation_id or ""))
        if parents and not any(same_order(row.source_reference, item) for item in parents):
            held.add(row.id)
    return held


# The 007-A view and the stored journal of one client's evidence (007-B). The caller
# has authorized the read (finance:read for people and keys; internal jobs check their own
# scope); the result never contains another client's records.
def client_ledger(session: Session, agency_id: UUID, client_id: UUID) -> ClientLedger:
    from app.services import ledger_store

    rows = load_rows(session, agency_id, client_id)
    state = ledger_store.require_current(session, agency_id, client_id, rows)
    held = unbound_refunds(rows)
    evidence = {row.id: _evidence(row) for row in rows}
    kept = [row for row in rows if row.id not in held]
    records = tuple(evidence[row.id] for row in kept)
    movements = ledger_store.stored_movements(session, state, evidence) if state else ()
    return ClientLedger(
        records,
        tuple(row.intake for row in kept),
        current_calculation(records, movements),
        tuple(evidence[row.id] for row in rows if row.id in held),
        journal=ledger_store.stored_journal(session, state, movements) if state else (),
        record_ids=tuple(row.id for row in kept),
        held_ids=tuple(row.id for row in rows if row.id in held),
        generation=state.generation if state else None,
        financial_revision=state.financial_revision if state else 0,
    )


def _amount(minor: int, currency: Currency) -> str:
    return decimal_text(minor, currency.exponent)


def _instant(value: datetime) -> datetime:
    return value.astimezone(UTC)


# The finance:read answer over one client's ledger (design section 3.3). Lists are bounded to
# VIEW_LIMIT items, newest first; totals always cover every record.
def revenue_view(ledger: ClientLedger, agency_id: UUID, client_id: UUID) -> dict[str, Any]:
    calculation = ledger.calculation
    totals = calculation.totals(agency_id, client_id)
    transactions = sorted(
        calculation.transactions,
        key=lambda item: (_instant(item.sale.effective_at), item.operation_id),
        reverse=True,
    )
    declared: Sequence[Evidence] = sorted(
        calculation.unverified,
        key=lambda item: (_instant(item.effective_at), item.operation_id),
        reverse=True,
    )
    declared_totals: dict[str, dict[str, Any]] = {}
    for item in declared:
        bucket = declared_totals.setdefault(
            item.amount.currency.code,
            {"currency": item.amount.currency, "sales": 0, "refunds": 0},
        )
        if bucket["currency"] != item.amount.currency:
            raise LedgerInputError("currency_exponent_conflict")
        bucket["sales" if item.kind is OperationKind.SALE else "refunds"] += item.amount.minor
    # Adjustments 007-A keeps pending, then the Paymob refunds held back by D-070.
    pending: list[tuple[Any, str | None]] = [
        (item, item.status_reason) for item in calculation.pending
    ] + [(item, "parent_order_mismatch") for item in ledger.held]
    return {
        "verified": {
            "totals": [
                {
                    "currency": code,
                    "captured": _amount(value.captured, value.currency),
                    "refunded": _amount(value.refunded, value.currency),
                    "charged_back": _amount(value.charged_back, value.currency),
                    "reversed": _amount(value.reversed, value.currency),
                    "corrected": _amount(value.corrected, value.currency),
                    "net": _amount(value.net, value.currency),
                }
                for code, value in totals.items()
            ],
            "transactions": [
                {
                    "operation_id": item.operation_id,
                    "source_account_id": item.scope.source_account_id,
                    "currency": item.currency.code,
                    "effective_at": item.sale.effective_at,
                    "net": _amount(item.totals.net, item.currency),
                    "entries": [
                        {
                            "operation_id": entry.operation_id,
                            "kind": entry.kind.value,
                            "amount": _amount(entry.amount.minor, item.currency),
                            "effective_at": entry.effective_at,
                        }
                        for entry in item.entries
                    ],
                }
                for item in transactions[:VIEW_LIMIT]
            ],
        },
        "declared": {
            "totals": [
                {
                    "currency": code,
                    "sales": _amount(bucket["sales"], bucket["currency"]),
                    "refunds": _amount(bucket["refunds"], bucket["currency"]),
                }
                for code, bucket in sorted(declared_totals.items())
            ],
            "items": [
                {
                    "operation_id": item.operation_id,
                    "kind": item.kind.value,
                    "amount": _amount(item.amount.minor, item.amount.currency),
                    "currency": item.amount.currency.code,
                    "effective_at": item.effective_at,
                    "parent_operation_id": item.parent_operation_id,
                    "intake": ledger.intake_of(item),
                    "reason": item.reason,
                    "source_reference": item.source_reference,
                }
                for item in declared[:VIEW_LIMIT]
            ],
        },
        "pending": [
            {
                "operation_id": item.operation_id,
                "kind": item.kind.value,
                "parent_operation_id": item.parent_operation_id,
                "amount": _amount(item.amount.minor, item.amount.currency),
                "currency": item.amount.currency.code,
                "effective_at": item.effective_at,
                "reason": reason,
            }
            for item, reason in pending[:VIEW_LIMIT]
        ],
        "reconciliation": [
            {"operation_id": item.operation_id, "reason": item.reason.value}
            for item in calculation.reconciliation[:VIEW_LIMIT]
        ],
        "truncated": max(
            len(transactions),
            len(declared),
            len(pending),
            len(calculation.reconciliation),
        )
        > VIEW_LIMIT,
    }
