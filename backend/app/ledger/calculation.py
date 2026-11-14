"""Provider-independent revenue calculation contract (specification 007-A, D-043).

The ledger is derived from evidence. calculate() takes every Evidence record received for any
number of tenants and returns postings, adjustments, reconciliation items and totals. The same
set of records gives the same result whatever order the records are supplied in or arrived in,
with one documented exception: when two records disagree about one business operation, or
reuse one delivery ID with different content, the record received first keeps its effect and
the disagreement is routed to reconciliation. A later conflicting record never rewrites a
posting.

Rules (entry review decisions A1-A3):
- Qualifying sale evidence is synthetic confirmed capture or settlement evidence. Both stages of
  one economic capture carry the same business operation ID and post one sale.
- Manual declarations and purchase_signal records are kept as unverified records and never enter
  verified totals. Agency subscription receipts (specification 017) are excluded from client
  revenue.
- Operations are matched within agency, client and source account by business operation ID. A
  delivery ID identifies a notification, never an operation: an exact redelivery is a no-op, and
  a new delivery that agrees with a known operation is attached to the same posting as evidence.
- Each operation posts once as a signed RevenueEntry in integer minor units. Net is captured value
  less refunds and chargebacks, plus chargeback reversals and audited corrections.
- An adjustment stays pending until its parent operation is posted. Ready adjustments are applied
  in canonical order (effective time, then operation ID), so delivery order cannot decide which
  adjustment exceeds the outstanding balance. An excess goes to reconciliation.
- A chargeback reversal restores at most the outstanding amount of the chargeback it references.
- An audited correction adds its own posting with actor, reason and source reference; the
  corrected posting is never changed.

The contract has no person reference, so a sale with an unknown purchaser is complete. Storage,
write permissions, live providers and identity association belong to slices 007-B and 007-C.
"""

import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.ledger.money import (
    MAX_REASON,
    Currency,
    LedgerInputError,
    Money,
    register_currency,
    require_aware,
    require_text,
)


class OperationKind(StrEnum):
    SALE = "sale"
    REFUND = "refund"
    CHARGEBACK = "chargeback"
    CHARGEBACK_REVERSAL = "chargeback_reversal"
    CORRECTION = "correction"


class EvidenceClass(StrEnum):
    CONFIRMED_CAPTURE = "confirmed_capture"  # qualifying sale evidence (A1)
    CONFIRMED_SETTLEMENT = "confirmed_settlement"  # the same economic capture, settled (A1)
    CONFIRMED_ADJUSTMENT = "confirmed_adjustment"  # a confirmed refund, chargeback or reversal
    AUDITED_CORRECTION = "audited_correction"  # a signed correction with actor and source
    MANUAL_DECLARATION = "manual_declaration"  # declared without independent verification
    PURCHASE_SIGNAL = "purchase_signal"  # a specification 004 reported purchase


class Stream(StrEnum):
    CLIENT_REVENUE = "client_revenue"
    AGENCY_SUBSCRIPTION = "agency_subscription"  # SaaS billing of the agency (specification 017)


class Disposition(StrEnum):
    POSTED = "posted"
    DUPLICATE = "duplicate"
    PENDING = "pending"
    RECONCILIATION = "reconciliation"
    UNVERIFIED = "unverified"
    EXCLUDED = "excluded"


class AdjustmentStatus(StrEnum):
    POSTED = "posted"
    PENDING = "pending"
    RECONCILIATION = "reconciliation"


class PendingReason(StrEnum):
    PARENT_MISSING = "parent_missing"  # no verified operation with the parent ID in the scope
    PARENT_UNRESOLVED = "parent_unresolved"  # the parent is itself pending or in reconciliation


class ReconciliationReason(StrEnum):
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    DELIVERY_ID_REUSED = "delivery_id_reused"
    EXCEEDS_OUTSTANDING = "exceeds_outstanding"
    REVERSAL_EXCEEDS_DEBIT = "reversal_exceeds_debit"
    CURRENCY_MISMATCH = "currency_mismatch"
    INVALID_PARENT = "invalid_parent"
    CORRECTION_BELOW_ZERO = "correction_below_zero"


SAME_DELIVERY = "same_delivery"
SAME_OPERATION = "same_operation"
UNVERIFIED_CLASSES = frozenset({EvidenceClass.MANUAL_DECLARATION, EvidenceClass.PURCHASE_SIGNAL})
_ALLOWED_CLASSES: dict[OperationKind, frozenset[EvidenceClass]] = {
    OperationKind.SALE: frozenset(
        {
            EvidenceClass.CONFIRMED_CAPTURE,
            EvidenceClass.CONFIRMED_SETTLEMENT,
            EvidenceClass.MANUAL_DECLARATION,
            EvidenceClass.PURCHASE_SIGNAL,
        }
    ),
    OperationKind.REFUND: frozenset(
        {EvidenceClass.CONFIRMED_ADJUSTMENT, EvidenceClass.MANUAL_DECLARATION}
    ),
    OperationKind.CHARGEBACK: frozenset(
        {EvidenceClass.CONFIRMED_ADJUSTMENT, EvidenceClass.MANUAL_DECLARATION}
    ),
    OperationKind.CHARGEBACK_REVERSAL: frozenset(
        {EvidenceClass.CONFIRMED_ADJUSTMENT, EvidenceClass.MANUAL_DECLARATION}
    ),
    OperationKind.CORRECTION: frozenset({EvidenceClass.AUDITED_CORRECTION}),
}
# The operation kinds each adjustment may reference as its parent.
_PARENT_KINDS: dict[OperationKind, frozenset[OperationKind]] = {
    OperationKind.REFUND: frozenset({OperationKind.SALE}),
    OperationKind.CHARGEBACK: frozenset({OperationKind.SALE}),
    OperationKind.CHARGEBACK_REVERSAL: frozenset({OperationKind.CHARGEBACK}),
    OperationKind.CORRECTION: frozenset(OperationKind),
}
_DEBIT_KINDS = frozenset({OperationKind.REFUND, OperationKind.CHARGEBACK})


@dataclass(frozen=True, slots=True, order=True)
class LedgerScope:
    """The tenant boundary of an operation: agency, client and the client's source account."""

    agency_id: UUID
    client_id: UUID
    source_account_id: str


@dataclass(frozen=True, slots=True)
class Evidence:
    """One received record about one business operation.

    delivery_id identifies the notification or manual submission; operation_id identifies the
    immutable business operation it describes. effective_at is when the operation took effect
    at its source and received_at is when this record arrived. amount is positive, except for a
    correction, whose signed non-zero amount is added to its transaction. client_id may be None
    only for an agency subscription receipt, which belongs to the agency rather than a client.
    """

    delivery_id: str
    agency_id: UUID
    client_id: UUID | None
    source_account_id: str
    operation_id: str
    kind: OperationKind
    classification: EvidenceClass
    amount: Money
    effective_at: datetime
    received_at: datetime
    parent_operation_id: str | None = None
    stream: Stream = Stream.CLIENT_REVENUE
    reason: str | None = None
    actor: str | None = None
    source_reference: str | None = None

    def __post_init__(self) -> None:
        require_text(self.delivery_id, "invalid_delivery_id")
        if not isinstance(self.agency_id, UUID):
            raise LedgerInputError("invalid_agency")
        if not isinstance(self.stream, Stream):
            raise LedgerInputError("invalid_stream")
        if self.client_id is None:
            if self.stream is not Stream.AGENCY_SUBSCRIPTION:
                raise LedgerInputError("invalid_client")
        elif not isinstance(self.client_id, UUID):
            raise LedgerInputError("invalid_client")
        require_text(self.source_account_id, "invalid_source_account")
        require_text(self.operation_id, "invalid_operation_id")
        if not isinstance(self.kind, OperationKind):
            raise LedgerInputError("invalid_kind")
        if (
            not isinstance(self.classification, EvidenceClass)
            or self.classification not in _ALLOWED_CLASSES[self.kind]
        ):
            raise LedgerInputError("invalid_classification")
        if not isinstance(self.amount, Money):
            raise LedgerInputError("invalid_amount")
        if self.kind is OperationKind.CORRECTION:
            if self.amount.minor == 0:
                raise LedgerInputError("invalid_amount")
        elif self.amount.minor <= 0:
            raise LedgerInputError("invalid_amount")
        require_aware(self.effective_at, "invalid_effective_at")
        require_aware(self.received_at, "invalid_received_at")
        if self.kind is OperationKind.SALE:
            if self.parent_operation_id is not None:
                raise LedgerInputError("invalid_parent")
        else:
            require_text(self.parent_operation_id, "invalid_parent")
            if self.parent_operation_id == self.operation_id:
                raise LedgerInputError("invalid_parent")
        if self.reason is not None:
            require_text(self.reason, "invalid_reason", MAX_REASON)
        if self.actor is not None:
            require_text(self.actor, "invalid_actor")
        if self.source_reference is not None:
            require_text(self.source_reference, "invalid_source_reference")
        if self.kind is OperationKind.CORRECTION and (
            self.actor is None or self.reason is None or self.source_reference is None
        ):
            raise LedgerInputError("incomplete_correction")

    @property
    def scope(self) -> LedgerScope:
        if self.client_id is None:
            raise LedgerInputError("invalid_client")
        return LedgerScope(self.agency_id, self.client_id, self.source_account_id)


@dataclass(frozen=True, slots=True)
class RevenueEntry:
    """One signed posting in minor units; its evidence is every agreeing record received."""

    scope: LedgerScope
    transaction_id: str  # the business operation ID of the sale
    operation_id: str
    kind: OperationKind
    amount: Money  # signed: sales and reversals positive, refunds and chargebacks negative
    effective_at: datetime
    parent_operation_id: str | None
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class Adjustment:
    """A refund, chargeback, chargeback reversal or audited correction and its current state."""

    scope: LedgerScope
    operation_id: str
    kind: OperationKind
    parent_operation_id: str
    amount: Money  # as claimed: a positive magnitude, or the signed correction amount
    effective_at: datetime
    status: AdjustmentStatus
    status_reason: str | None  # a PendingReason or ReconciliationReason; None once posted
    transaction_id: str | None  # the sale, once the parent is posted
    reason: str | None
    actor: str | None
    source_reference: str | None
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class CurrencyTotals:
    """Verified totals in one original currency, in minor units."""

    currency: Currency
    captured: int = 0
    refunded: int = 0
    charged_back: int = 0
    reversed: int = 0
    corrected: int = 0  # signed

    @property
    def net(self) -> int:
        return self.captured - self.refunded - self.charged_back + self.reversed + self.corrected

    @property
    def net_amount(self) -> Money:
        return Money(self.net, self.currency)

    def __add__(self, other: object) -> "CurrencyTotals":
        if not isinstance(other, CurrencyTotals):
            return NotImplemented
        if other.currency != self.currency:
            raise LedgerInputError("currency_mismatch")
        return CurrencyTotals(
            self.currency,
            self.captured + other.captured,
            self.refunded + other.refunded,
            self.charged_back + other.charged_back,
            self.reversed + other.reversed,
            self.corrected + other.corrected,
        )


@dataclass(frozen=True, slots=True)
class Transaction:
    """One sale and the posted adjustments linked to it, in one original currency."""

    scope: LedgerScope
    operation_id: str
    currency: Currency
    entries: tuple[RevenueEntry, ...]  # in application order; the sale is first
    totals: CurrencyTotals

    @property
    def sale(self) -> RevenueEntry:
        return self.entries[0]

    @property
    def net(self) -> Money:
        return self.totals.net_amount


@dataclass(frozen=True, slots=True)
class ReconciliationItem:
    """A disagreement or limit breach for review; retained is the record whose effect stands."""

    scope: LedgerScope
    operation_id: str
    reason: ReconciliationReason
    evidence: tuple[Evidence, ...]
    retained: Evidence | None = None


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """What one received record did, in arrival order."""

    evidence: Evidence
    disposition: Disposition
    reason: str


@dataclass(frozen=True, slots=True)
class LedgerCalculation:
    transactions: tuple[Transaction, ...]
    adjustments: tuple[Adjustment, ...]
    reconciliation: tuple[ReconciliationItem, ...]
    unverified: tuple[Evidence, ...]
    excluded: tuple[Evidence, ...]
    outcomes: tuple[DeliveryOutcome, ...]

    @property
    def entries(self) -> tuple[RevenueEntry, ...]:
        return tuple(entry for transaction in self.transactions for entry in transaction.entries)

    @property
    def pending(self) -> tuple[Adjustment, ...]:
        return tuple(a for a in self.adjustments if a.status is AdjustmentStatus.PENDING)

    def totals(
        self, agency_id: UUID, client_id: UUID, source_account_id: str | None = None
    ) -> dict[str, CurrencyTotals]:
        """Verified totals of one client, optionally one source account, per original currency.

        The tenant keys are mandatory: no method aggregates across agencies or clients, and
        amounts in different currencies are never added.
        """
        totals: dict[str, CurrencyTotals] = {}
        for transaction in self.transactions:
            scope = transaction.scope
            if scope.agency_id != agency_id or scope.client_id != client_id:
                continue
            if source_account_id is not None and scope.source_account_id != source_account_id:
                continue
            code = transaction.currency.code
            prior = totals.get(code)
            totals[code] = transaction.totals if prior is None else prior + transaction.totals
        return dict(sorted(totals.items()))


@dataclass(slots=True)
class _Operation:
    scope: LedgerScope
    reference: Evidence  # the first-received record; it fixes the operation's terms
    evidence: list[Evidence]
    effective_at: datetime


@dataclass(slots=True)
class _Ledger:
    currency: Currency
    entries: list[RevenueEntry]
    net: int


def _payload(item: Evidence) -> tuple:
    """Everything except the receipt time: an exact redelivery repeats all of it."""
    return (
        item.agency_id,
        item.client_id,
        item.source_account_id,
        item.operation_id,
        item.kind,
        item.classification,
        item.amount,
        item.effective_at,
        item.parent_operation_id,
        item.stream,
        item.reason,
        item.actor,
        item.source_reference,
    )


def _terms(item: Evidence) -> tuple:
    """The terms two records of one operation must share; capture and settlement may differ."""
    return (
        item.kind,
        item.amount,
        item.parent_operation_id,
        item.reason,
        item.actor,
        item.source_reference,
    )


def _arrival_key(item: Evidence) -> tuple:
    """Receipt order with a total, content-based tie-break."""
    return (
        item.received_at,
        item.delivery_id,
        str(item.agency_id),
        str(item.client_id),
        item.source_account_id,
        item.operation_id,
        item.kind.value,
        item.classification.value,
        item.amount.currency.code,
        item.amount.minor,
        item.effective_at,
        item.parent_operation_id or "",
        item.stream.value,
        item.reason or "",
        item.actor or "",
        item.source_reference or "",
    )


def _by_delivery(records: Iterable[Evidence]) -> tuple[Evidence, ...]:
    return tuple(sorted(records, key=lambda record: record.delivery_id))


def calculate(records: Iterable[Evidence]) -> LedgerCalculation:
    """Derive postings, adjustments, reconciliation items and totals from received evidence."""
    items = list(records)
    known: dict[str, int] = {}
    for item in items:
        if not isinstance(item, Evidence):
            raise LedgerInputError("invalid_evidence")
        register_currency(known, item.amount.currency)
    arrival = sorted(items, key=_arrival_key)

    outcomes: list[DeliveryOutcome | None] = [None] * len(arrival)
    reconciliation: list[ReconciliationItem] = []
    excluded: list[Evidence] = []
    unverified: list[Evidence] = []
    deliveries: dict[tuple[LedgerScope, str], Evidence] = {}
    claims: dict[tuple[LedgerScope, str], list[int]] = {}

    # 1. Separate excluded and unverified records and remove redeliveries.
    for index, item in enumerate(arrival):
        if item.stream is Stream.AGENCY_SUBSCRIPTION:
            excluded.append(item)
            outcomes[index] = DeliveryOutcome(item, Disposition.EXCLUDED, item.stream.value)
            continue
        scope = item.scope
        delivery = (scope, item.delivery_id)
        first = deliveries.get(delivery)
        if first is not None:
            if _payload(first) == _payload(item):
                outcomes[index] = DeliveryOutcome(item, Disposition.DUPLICATE, SAME_DELIVERY)
            else:
                reason = ReconciliationReason.DELIVERY_ID_REUSED
                reconciliation.append(
                    ReconciliationItem(scope, item.operation_id, reason, (item,), first)
                )
                outcomes[index] = DeliveryOutcome(item, Disposition.RECONCILIATION, reason)
            continue
        deliveries[delivery] = item
        if item.classification in UNVERIFIED_CLASSES:
            unverified.append(item)
            outcomes[index] = DeliveryOutcome(
                item, Disposition.UNVERIFIED, item.classification.value
            )
            continue
        claims.setdefault((scope, item.operation_id), []).append(index)

    # 2. Resolve each scoped operation from its first-received record.
    operations: dict[tuple[LedgerScope, str], _Operation] = {}
    references: dict[tuple[LedgerScope, str], int] = {}
    for key, indexes in claims.items():
        reference = arrival[indexes[0]]
        operation = _Operation(key[0], reference, [reference], reference.effective_at)
        for index in indexes[1:]:
            item = arrival[index]
            if _terms(item) == _terms(reference):
                operation.evidence.append(item)
                operation.effective_at = min(operation.effective_at, item.effective_at)
                outcomes[index] = DeliveryOutcome(item, Disposition.DUPLICATE, SAME_OPERATION)
            else:
                reason = ReconciliationReason.CONFLICTING_EVIDENCE
                reconciliation.append(
                    ReconciliationItem(key[0], key[1], reason, (item,), reference)
                )
                outcomes[index] = DeliveryOutcome(item, Disposition.RECONCILIATION, reason)
        operations[key] = operation
        references[key] = indexes[0]

    # 3. Post sales, then apply each adjustment once its parent is posted, in canonical order.
    children: dict[tuple[LedgerScope, str], list[tuple[LedgerScope, str]]] = {}
    ready: list[tuple[datetime, str, LedgerScope]] = []
    for key, operation in operations.items():
        parent_id = operation.reference.parent_operation_id
        if parent_id is None:
            heapq.heappush(ready, (operation.effective_at, key[1], key[0]))
        else:
            children.setdefault((key[0], parent_id), []).append(key)

    ledgers: dict[tuple[LedgerScope, str], _Ledger] = {}
    posted: dict[tuple[LedgerScope, str], RevenueEntry] = {}
    reversed_by_chargeback: dict[tuple[LedgerScope, str], int] = {}
    states: dict[tuple[LedgerScope, str], tuple[AdjustmentStatus, str | None, str | None]] = {}
    while ready:
        _, operation_id, scope = heapq.heappop(ready)
        key = (scope, operation_id)
        operation = operations[key]
        item = operation.reference
        if item.kind is OperationKind.SALE:
            transaction_id = operation_id
            ledger = ledgers[key] = _Ledger(item.amount.currency, [], 0)
            signed = item.amount.minor
        else:
            parent_key = (scope, item.parent_operation_id)
            parent = posted[parent_key]
            transaction_id = parent.transaction_id
            ledger = ledgers[(scope, transaction_id)]
            failure = _limit_failure(item, parent, ledger, reversed_by_chargeback)
            if failure is not None:
                states[key] = (AdjustmentStatus.RECONCILIATION, failure, transaction_id)
                reconciliation.append(
                    ReconciliationItem(
                        scope, operation_id, failure, _by_delivery(operation.evidence)
                    )
                )
                continue
            signed = item.amount.minor
            if item.kind in _DEBIT_KINDS:
                signed = -signed
            if item.kind is OperationKind.CHARGEBACK_REVERSAL:
                reversed_by_chargeback[parent_key] = (
                    reversed_by_chargeback.get(parent_key, 0) + item.amount.minor
                )
            states[key] = (AdjustmentStatus.POSTED, None, transaction_id)
        entry = RevenueEntry(
            scope,
            transaction_id,
            operation_id,
            item.kind,
            Money(signed, item.amount.currency),
            operation.effective_at,
            item.parent_operation_id,
            _by_delivery(operation.evidence),
        )
        ledger.entries.append(entry)
        ledger.net += signed
        posted[key] = entry
        for child in children.get(key, ()):
            heapq.heappush(ready, (operations[child].effective_at, child[1], child[0]))

    # 4. Everything not reached stays pending; record each first-received record's outcome.
    adjustments = []
    for key, operation in operations.items():
        item = operation.reference
        if item.kind is OperationKind.SALE:
            outcomes[references[key]] = DeliveryOutcome(item, Disposition.POSTED, "posted")
            continue
        if key not in states:
            parent_known = (key[0], item.parent_operation_id) in operations
            reason = (
                PendingReason.PARENT_UNRESOLVED if parent_known else PendingReason.PARENT_MISSING
            )
            states[key] = (AdjustmentStatus.PENDING, reason, None)
        status, status_reason, transaction_id = states[key]
        disposition = Disposition(status.value)
        outcomes[references[key]] = DeliveryOutcome(item, disposition, status_reason or "posted")
        adjustments.append(
            Adjustment(
                key[0],
                key[1],
                item.kind,
                item.parent_operation_id,
                item.amount,
                operation.effective_at,
                status,
                status_reason,
                transaction_id,
                item.reason,
                item.actor,
                item.source_reference,
                _by_delivery(operation.evidence),
            )
        )

    transactions = tuple(
        Transaction(key[0], key[1], ledger.currency, tuple(ledger.entries), _totals(ledger))
        for key, ledger in sorted(ledgers.items(), key=lambda pair: pair[0])
    )
    return LedgerCalculation(
        transactions=transactions,
        adjustments=tuple(sorted(adjustments, key=lambda a: (a.scope, a.operation_id))),
        reconciliation=tuple(sorted(reconciliation, key=_reconciliation_key)),
        unverified=tuple(unverified),
        excluded=tuple(excluded),
        outcomes=tuple(outcome for outcome in outcomes if outcome is not None),
    )


def _limit_failure(
    item: Evidence,
    parent: RevenueEntry,
    ledger: _Ledger,
    reversed_by_chargeback: dict[tuple[LedgerScope, str], int],
) -> ReconciliationReason | None:
    if parent.kind not in _PARENT_KINDS[item.kind]:
        return ReconciliationReason.INVALID_PARENT
    if item.amount.currency != ledger.currency:
        return ReconciliationReason.CURRENCY_MISMATCH
    if item.kind in _DEBIT_KINDS and item.amount.minor > ledger.net:
        return ReconciliationReason.EXCEEDS_OUTSTANDING
    if item.kind is OperationKind.CHARGEBACK_REVERSAL:
        restored = reversed_by_chargeback.get((parent.scope, parent.operation_id), 0)
        if item.amount.minor > -parent.amount.minor - restored:
            return ReconciliationReason.REVERSAL_EXCEEDS_DEBIT
    if item.kind is OperationKind.CORRECTION and ledger.net + item.amount.minor < 0:
        return ReconciliationReason.CORRECTION_BELOW_ZERO
    return None


def _totals(ledger: _Ledger) -> CurrencyTotals:
    amounts = dict.fromkeys(OperationKind, 0)
    for entry in ledger.entries:
        amounts[entry.kind] += entry.amount.minor
    return CurrencyTotals(
        ledger.currency,
        captured=amounts[OperationKind.SALE],
        refunded=-amounts[OperationKind.REFUND],
        charged_back=-amounts[OperationKind.CHARGEBACK],
        reversed=amounts[OperationKind.CHARGEBACK_REVERSAL],
        corrected=amounts[OperationKind.CORRECTION],
    )


def _reconciliation_key(item: ReconciliationItem) -> tuple:
    return (
        item.scope,
        item.operation_id,
        item.reason.value,
        tuple(record.delivery_id for record in item.evidence),
    )
