"""Persisted revenue evidence and the ledger read (specification 015-A, D-067 D2 and D11).

Every intake path (the Paymob callback of 015-B, the CSV commit and the manual declaration of
015-C) appends 007-A Evidence records through append_evidence while holding the client's revenue
lock, whose clock read is the receipt time. Receipts of one client are therefore increasing in
commit order, which keeps the 007-A journal-prefix property: a journal returned earlier is a
prefix of the journal returned with more evidence. Nothing updates or deletes evidence.

client_ledger loads a client's records in receipt order and returns the 007-A LedgerCalculation
and the ledger_feed journal, which 008-A attribution and 014-B conversion delivery consume
unchanged. revenue_view shapes the finance:read answer: verified totals and transactions,
declared (unverified) items and totals kept apart, pending adjustments and reconciliation items.
Amounts in different currencies are never added together.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.advertising.currencies import decimal_text
from app.attribution import JournalItem, ledger_feed
from app.ledger import (
    Currency,
    Evidence,
    EvidenceClass,
    LedgerCalculation,
    LedgerInputError,
    Money,
    OperationKind,
    Stream,
    calculate,
)
from app.models import RevenueEvidence
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


# Append one record of a client's revenue stream. The caller holds the client's revenue lock and
# passes its clock read as received_at. Returns "stored", or "duplicate" for an exact redelivery
# (same source account, delivery ID and content), which inserts nothing. A reused delivery ID
# with other content is stored, so the 007-A calculation reports it as delivery_id_reused.
def append_evidence(
    session: Session, item: Evidence, intake: Intake, intake_id: UUID | None
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
    return "stored" if session.scalar(statement) is not None else "duplicate"


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

    # The ledger_feed journal, computed on first use: it recalculates every receipt prefix.
    @cached_property
    def journal(self) -> tuple[JournalItem, ...]:
        return ledger_feed(self.records)

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


# The 007-A calculation and the ledger_feed journal of one client's stored evidence. The caller
# has authorized the read (finance:read for people and keys; internal jobs check their own
# scope); the result never contains another client's records.
def client_ledger(session: Session, agency_id: UUID, client_id: UUID) -> ClientLedger:
    rows = load_rows(session, agency_id, client_id)
    records = tuple(_evidence(row) for row in rows)
    return ClientLedger(records, tuple(row.intake for row in rows), calculate(records))


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
                "reason": item.status_reason,
            }
            for item in calculation.pending[:VIEW_LIMIT]
        ],
        "reconciliation": [
            {"operation_id": item.operation_id, "reason": item.reason.value}
            for item in calculation.reconciliation[:VIEW_LIMIT]
        ],
        "truncated": max(
            len(transactions),
            len(declared),
            len(calculation.pending),
            len(calculation.reconciliation),
        )
        > VIEW_LIMIT,
    }
