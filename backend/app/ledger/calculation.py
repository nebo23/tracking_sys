"""Provider-independent revenue calculation contract (specification 007-A, D-043).

calculate() takes every Evidence record received for any number of tenants and returns two
views of the same ledger:

- The provisional calculation (transactions, entries, adjustments, reconciliation items and
  totals) is derived from all evidence received so far. Which adjustments fit a balance is
  decided in effective order, so the economic result depends only on the set of records, with
  one documented exception: when two records disagree about one business operation, or reuse
  one delivery ID with different content, the record received first keeps its effect and the
  disagreement is routed to reconciliation. Later evidence can change the provisional
  calculation; for example, a late-arriving refund with an earlier effective time can leave a
  later refund without balance.
- The movement journal (movements) is append-only. Records are taken in receipt order and every
  change in the provisional postings becomes a movement: a posting when an operation takes
  effect, a release when an operation that took effect no longer does. A movement is never
  rewritten or removed, so a committed effect can change only through an explicit later
  movement. The movements of every transaction sum to its provisional net. Callers that persist
  effects should commit movements, not the provisional entries.

Receipt order is the receipt instant (received_at as an absolute instant); records received at
the same instant keep the order in which they are supplied. Neither delivery IDs nor content
decide a tie, because they do not show which record arrived first. The supplied sequence is
therefore the receipt log: to replay a journal, store the records in the order they were
received and pass that same sequence, appending each new record at its end. While each new
record is received at or after the instants already received, every journal returned earlier
is an exact prefix, with the same sequence numbers and content, of the journal returned with
more evidence, and a consumer that applies only the movements after its last sequence reaches
the recalculated balance.

Rules (entry review decisions A1-A3):
- Qualifying sale evidence is synthetic confirmed capture or settlement evidence. Both stages of
  one economic capture carry the same business operation ID and post one sale; each stage keeps
  its own effective time and source reference.
- Manual declarations and purchase_signal records are unverified and never enter verified
  totals. Their delivery IDs form a namespace separate from verified evidence; a shared ID is
  reported for review without affecting either record. Agency subscription receipts
  (specification 017) are excluded from client revenue before any validation that could affect
  another tenant.
- Operations are matched within agency, client and source account by business operation ID. A
  delivery ID identifies a notification, never an operation: an exact redelivery is a no-op, and
  a new delivery whose economic terms and effective time agree with a known operation is
  attached to the same posting as evidence. Per-delivery provenance (source reference, actor and
  reason) may differ, except on an audited correction, where it is part of the audit terms.
- Each operation posts at most once as a signed RevenueEntry in integer minor units. Net is
  captured value less refunds and chargebacks, plus chargeback reversals and audited
  corrections.
- An adjustment whose parent is absent stays pending (parent_missing); one whose parent is
  pending or rejected waits as parent_unresolved. A parent of a disallowed kind or a cycle of
  parents can never be resolved by further evidence and goes to reconciliation.
- Each chargeback is normalized with its reversals first: reversals are accepted in canonical
  order up to the chargeback amount, and the chargeback consumes only its unreversed remainder.
  Refunds, chargebacks and corrections are then applied in canonical order (effective instant,
  then operation ID), so delivery order cannot decide which of them exceeds the balance.
- An audited correction adds its own posting with actor, reason and source reference; the
  corrected posting is never changed.

The contract has no person reference, so a sale with an unknown purchaser is complete. Storage,
write permissions, live providers and identity association belong to slices 007-B and 007-C.
"""

import heapq
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.ledger.money import (
    MAX_REASON,
    Currency,
    LedgerInputError,
    Money,
    require_aware,
    require_text,
    utc_instant,
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
    PARENT_UNRESOLVED = "parent_unresolved"  # the parent is itself pending or not posted


class ReconciliationReason(StrEnum):
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    DELIVERY_ID_REUSED = "delivery_id_reused"
    DELIVERY_ID_SHARED = "delivery_id_shared"  # one ID on verified and unverified evidence
    EXCEEDS_OUTSTANDING = "exceeds_outstanding"
    REVERSAL_EXCEEDS_DEBIT = "reversal_exceeds_debit"
    CURRENCY_MISMATCH = "currency_mismatch"
    INVALID_PARENT = "invalid_parent"
    PARENT_CYCLE = "parent_cycle"
    CORRECTION_BELOW_ZERO = "correction_below_zero"


class MovementType(StrEnum):
    POSTING = "posting"  # the operation takes effect
    RELEASE = "release"  # an operation that took effect no longer does; reverses its posting


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
    at its source and received_at is when this record arrived; both are compared as absolute
    instants. amount is positive, except for a correction, whose signed non-zero amount is added
    to its transaction. client_id may be None only for an agency subscription receipt, which
    belongs to the agency rather than a client.
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
    """One signed provisional posting in minor units, with every agreeing record as evidence."""

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
    transaction_id: str | None  # the sale, once the parent chain reaches a posted sale
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
    """One disagreement or limit breach for review; retained is the record whose effect stands.

    Repeated identical deliveries of one discrepancy join the same item as further evidence.
    """

    scope: LedgerScope
    operation_id: str
    reason: ReconciliationReason
    evidence: tuple[Evidence, ...]
    retained: Evidence | None = None


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """What one received record did under the provisional calculation, in arrival order."""

    evidence: Evidence
    disposition: Disposition
    reason: str


@dataclass(frozen=True, slots=True)
class Movement:
    """One append-only journal line: a signed change to a transaction's committed balance."""

    sequence: int  # 1-based position in the journal
    scope: LedgerScope
    transaction_id: str
    operation_id: str
    kind: OperationKind
    movement: MovementType
    amount: Money  # signed effect; a release is the negation of the posting it reverses
    trigger: Evidence  # the received record whose arrival caused the change
    reason: str | None  # for a release, the operation's new status reason


@dataclass(frozen=True, slots=True)
class LedgerCalculation:
    """The provisional calculation over all evidence, and the append-only movement journal."""

    transactions: tuple[Transaction, ...]
    adjustments: tuple[Adjustment, ...]
    reconciliation: tuple[ReconciliationItem, ...]
    unverified: tuple[Evidence, ...]
    excluded: tuple[Evidence, ...]
    outcomes: tuple[DeliveryOutcome, ...]
    movements: tuple[Movement, ...] = ()

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
        amounts in different currencies are never added. If the selected transactions use one
        currency code with two exponents, the totals are refused with
        currency_exponent_conflict; the conflict never affects another client.
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
            if prior is not None and prior.currency != transaction.currency:
                raise LedgerInputError("currency_exponent_conflict")
            totals[code] = transaction.totals if prior is None else prior + transaction.totals
        return dict(sorted(totals.items()))


_Key = tuple[LedgerScope, str]


@dataclass(slots=True)
class _Operation:
    scope: LedgerScope
    reference: Evidence  # the first-received record; it fixes the operation's terms
    evidence: list[Evidence]
    stages: dict[EvidenceClass, Evidence]  # the first agreeing record of each evidence class

    @property
    def timing(self) -> Evidence:
        """The record whose effective time the operation carries: a capture before a settlement."""
        if self.reference.kind is OperationKind.SALE:
            return (
                self.stages.get(EvidenceClass.CONFIRMED_CAPTURE)
                or self.stages[EvidenceClass.CONFIRMED_SETTLEMENT]
            )
        return self.reference


@dataclass(slots=True)
class _State:
    """The provisional calculation over one prefix of the arrival order."""

    transactions: list[Transaction] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    reconciliation: list[ReconciliationItem] = field(default_factory=list)
    unverified: list[Evidence] = field(default_factory=list)
    excluded: list[Evidence] = field(default_factory=list)
    outcomes: list[DeliveryOutcome] = field(default_factory=list)
    posted: dict[_Key, RevenueEntry] = field(default_factory=dict)  # in application order
    status: dict[_Key, tuple[AdjustmentStatus, str | None, str | None]] = field(
        default_factory=dict
    )


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
        utc_instant(item.effective_at),
        item.parent_operation_id,
        item.stream,
        item.reason,
        item.actor,
        item.source_reference,
    )


def _economic_terms(item: Evidence) -> tuple:
    """The terms every record of one operation must share, apart from stage timing.

    Source reference, actor and reason are per-delivery provenance, except on an audited
    correction, where they are the audit record of the correction itself.
    """
    terms: tuple = (item.kind, item.amount, item.parent_operation_id)
    if item.kind is OperationKind.CORRECTION:
        terms += (item.actor, item.reason, item.source_reference)
    return terms


def _receipt_instant(item: Evidence) -> datetime:
    return utc_instant(item.received_at)


def _arrival_key(item: Evidence) -> tuple:
    """A total, content-based order for presenting evidence; it never decides receipt order."""
    return (
        utc_instant(item.received_at),
        item.delivery_id,
        str(item.agency_id),
        str(item.client_id),
        item.source_account_id,
        item.operation_id,
        item.kind.value,
        item.classification.value,
        item.amount.currency.code,
        item.amount.currency.exponent,
        item.amount.minor,
        utc_instant(item.effective_at),
        item.parent_operation_id or "",
        item.stream.value,
        item.reason or "",
        item.actor or "",
        item.source_reference or "",
    )


def _by_delivery(records: Iterable[Evidence]) -> tuple[Evidence, ...]:
    return tuple(sorted(records, key=_arrival_key_by_delivery))


def _arrival_key_by_delivery(record: Evidence) -> tuple:
    return (record.delivery_id, _arrival_key(record))


def calculate(records: Iterable[Evidence]) -> LedgerCalculation:
    """Derive the provisional calculation and the movement journal from received evidence.

    records is the receipt log: records are ordered by receipt instant, and records received at
    the same instant keep the order in which they are supplied (see the module documentation
    for replaying a journal). Malformed records are refused when an Evidence is constructed.
    calculate() itself refuses only objects that are not Evidence; disagreements between valid
    records never abort the calculation and are confined to the affected scope.
    """
    items = list(records)
    for item in items:
        if not isinstance(item, Evidence):
            raise LedgerInputError("invalid_evidence")
    arrival = sorted(items, key=_receipt_instant)  # stable: ties keep the supplied order

    movements: list[Movement] = []
    committed: dict[_Key, RevenueEntry] = {}
    state = _derive([])
    for count in range(1, len(arrival) + 1):
        state = _derive(arrival[:count])
        _record_movements(state, committed, movements, arrival[count - 1])
    return LedgerCalculation(
        transactions=tuple(state.transactions),
        adjustments=tuple(sorted(state.adjustments, key=lambda a: (a.scope, a.operation_id))),
        reconciliation=tuple(sorted(state.reconciliation, key=_reconciliation_key)),
        unverified=tuple(state.unverified),
        excluded=tuple(state.excluded),
        outcomes=tuple(state.outcomes),
        movements=tuple(movements),
    )


def _record_movements(
    state: _State,
    committed: dict[_Key, RevenueEntry],
    movements: list[Movement],
    trigger: Evidence,
) -> None:
    """Append the movements that bring the committed effects in line with the new state."""
    changes: list[tuple[RevenueEntry, MovementType, str | None]] = []
    for key in sorted(committed, key=lambda k: (k[0], committed[k].transaction_id, k[1])):
        entry = committed[key]
        current = state.posted.get(key)
        if current is None or _effect(current) != _effect(entry):
            reason = state.status[key][1] if key in state.status else None
            changes.append((entry, MovementType.RELEASE, reason))
    for key, entry in state.posted.items():
        prior = committed.get(key)
        if prior is None or _effect(prior) != _effect(entry):
            changes.append((entry, MovementType.POSTING, None))
    for entry, movement, reason in changes:
        key = (entry.scope, entry.operation_id)
        if movement is MovementType.RELEASE:
            del committed[key]
            amount = -entry.amount
        else:
            committed[key] = entry
            amount = entry.amount
        movements.append(
            Movement(
                len(movements) + 1,
                entry.scope,
                entry.transaction_id,
                entry.operation_id,
                entry.kind,
                movement,
                amount,
                trigger,
                reason,
            )
        )


def _effect(entry: RevenueEntry) -> tuple:
    """What a posting does to a balance; added evidence for the same posting changes nothing."""
    return (entry.transaction_id, entry.kind, entry.amount)


def _derive(arrival: list[Evidence]) -> _State:
    """The provisional calculation over records already sorted in arrival order."""
    state = _State()
    outcomes: list[DeliveryOutcome | None] = [None] * len(arrival)
    deliveries: dict[tuple[LedgerScope, bool, str], Evidence] = {}
    reused: dict[tuple, list[Evidence]] = {}
    namespaces: dict[tuple[LedgerScope, str], dict[bool, Evidence]] = {}
    claims: dict[_Key, list[int]] = {}

    # 1. Exclude non-client records, separate unverified records and remove redeliveries.
    for index, item in enumerate(arrival):
        if item.stream is Stream.AGENCY_SUBSCRIPTION:
            state.excluded.append(item)
            outcomes[index] = DeliveryOutcome(item, Disposition.EXCLUDED, item.stream.value)
            continue
        scope = item.scope
        verified = item.classification not in UNVERIFIED_CLASSES
        delivery = (scope, verified, item.delivery_id)
        first = deliveries.get(delivery)
        if first is not None:
            if _payload(first) == _payload(item):
                outcomes[index] = DeliveryOutcome(item, Disposition.DUPLICATE, SAME_DELIVERY)
            else:
                reused.setdefault((delivery, _payload(item)), []).append(item)
                outcomes[index] = DeliveryOutcome(
                    item, Disposition.RECONCILIATION, ReconciliationReason.DELIVERY_ID_REUSED
                )
            continue
        deliveries[delivery] = item
        namespaces.setdefault((scope, item.delivery_id), {})[verified] = item
        if not verified:
            state.unverified.append(item)
            outcomes[index] = DeliveryOutcome(
                item, Disposition.UNVERIFIED, item.classification.value
            )
            continue
        claims.setdefault((scope, item.operation_id), []).append(index)
    for (delivery, _), records in reused.items():
        first = deliveries[delivery]
        state.reconciliation.append(
            ReconciliationItem(
                delivery[0],
                records[0].operation_id,
                ReconciliationReason.DELIVERY_ID_REUSED,
                tuple(records),
                first,
            )
        )
    for (scope, _), firsts in namespaces.items():
        if len(firsts) == 2:
            state.reconciliation.append(
                ReconciliationItem(
                    scope,
                    firsts[True].operation_id,
                    ReconciliationReason.DELIVERY_ID_SHARED,
                    (firsts[True], firsts[False]),
                    firsts[True],
                )
            )

    # 2. Resolve each scoped operation from its first-received record.
    operations: dict[_Key, _Operation] = {}
    references: dict[_Key, int] = {}
    conflicts: dict[tuple, list[Evidence]] = {}
    for key, indexes in claims.items():
        reference = arrival[indexes[0]]
        operation = _Operation(
            key[0], reference, [reference], {reference.classification: reference}
        )
        terms = _economic_terms(reference)
        for index in indexes[1:]:
            item = arrival[index]
            stage = operation.stages.get(item.classification)
            in_time = stage is None or utc_instant(stage.effective_at) == utc_instant(
                item.effective_at
            )
            if _economic_terms(item) == terms and in_time:
                operation.evidence.append(item)
                operation.stages.setdefault(item.classification, item)
                outcomes[index] = DeliveryOutcome(item, Disposition.DUPLICATE, SAME_OPERATION)
            else:
                signature = (
                    _economic_terms(item),
                    item.classification,
                    utc_instant(item.effective_at),
                )
                conflicts.setdefault((key, signature), []).append(item)
                outcomes[index] = DeliveryOutcome(
                    item, Disposition.RECONCILIATION, ReconciliationReason.CONFLICTING_EVIDENCE
                )
        operations[key] = operation
        references[key] = indexes[0]
    for (key, _), records in conflicts.items():
        state.reconciliation.append(
            ReconciliationItem(
                key[0],
                key[1],
                ReconciliationReason.CONFLICTING_EVIDENCE,
                tuple(records),
                operations[key].reference,
            )
        )

    # 3. Refuse parent links that no further evidence can repair.
    children: dict[_Key, list[_Key]] = {}
    for key, operation in operations.items():
        parent_id = operation.reference.parent_operation_id
        if parent_id is None:
            continue
        children.setdefault((key[0], parent_id), []).append(key)
        parent = operations.get((key[0], parent_id))
        if (
            parent is not None
            and parent.reference.kind not in _PARENT_KINDS[operation.reference.kind]
        ):
            _reject(state, operations, key, ReconciliationReason.INVALID_PARENT, None)
    _reject_cycles(state, operations)

    # 4. Apply each sale's adjustments.
    for key in sorted(k for k, op in operations.items() if op.reference.kind is OperationKind.SALE):
        _apply_transaction(state, operations, children, key)

    # 5. Everything not reached waits; record the outcome of each first-received record.
    for key, operation in operations.items():
        item = operation.reference
        if item.kind is OperationKind.SALE:
            outcomes[references[key]] = DeliveryOutcome(item, Disposition.POSTED, "posted")
            continue
        if key not in state.status:
            known = (key[0], item.parent_operation_id) in operations
            reason = PendingReason.PARENT_UNRESOLVED if known else PendingReason.PARENT_MISSING
            state.status[key] = (AdjustmentStatus.PENDING, reason, None)
        status, status_reason, transaction_id = state.status[key]
        outcomes[references[key]] = DeliveryOutcome(
            item, Disposition(status.value), status_reason or "posted"
        )
        state.adjustments.append(
            Adjustment(
                key[0],
                key[1],
                item.kind,
                item.parent_operation_id,
                item.amount,
                operation.timing.effective_at,
                status,
                status_reason,
                transaction_id,
                item.reason,
                item.actor,
                item.source_reference,
                _by_delivery(operation.evidence),
            )
        )
    state.outcomes = [outcome for outcome in outcomes if outcome is not None]
    return state


def _reject(
    state: _State,
    operations: dict[_Key, _Operation],
    key: _Key,
    reason: ReconciliationReason,
    transaction_id: str | None,
) -> None:
    state.status[key] = (AdjustmentStatus.RECONCILIATION, reason, transaction_id)
    state.reconciliation.append(
        ReconciliationItem(key[0], key[1], reason, _by_delivery(operations[key].evidence))
    )


def _reject_cycles(state: _State, operations: dict[_Key, _Operation]) -> None:
    """Route every operation on a cycle of parent references to reconciliation."""
    finished: set[_Key] = set()
    for start in sorted(operations):
        path: list[_Key] = []
        on_path: set[_Key] = set()
        node: _Key | None = start
        while node is not None and node in operations and node not in finished:
            item = operations[node].reference
            if item.kind is OperationKind.SALE or node in state.status:
                break
            if node in on_path:
                for member in path[path.index(node) :]:
                    _reject(state, operations, member, ReconciliationReason.PARENT_CYCLE, None)
                break
            on_path.add(node)
            path.append(node)
            node = (node[0], item.parent_operation_id)
        finished.update(path)


def _canonical(operations: dict[_Key, _Operation], key: _Key) -> tuple:
    return (utc_instant(operations[key].timing.effective_at), key[1], key)


def _apply_transaction(
    state: _State,
    operations: dict[_Key, _Operation],
    children: dict[_Key, list[_Key]],
    sale_key: _Key,
) -> None:
    sale = operations[sale_key]
    currency = sale.reference.amount.currency
    transaction_id = sale_key[1]
    entries: list[RevenueEntry] = []

    def post(key: _Key, signed: int) -> None:
        operation = operations[key]
        item = operation.reference
        entry = RevenueEntry(
            key[0],
            transaction_id,
            key[1],
            item.kind,
            Money(signed, item.amount.currency),
            operation.timing.effective_at,
            item.parent_operation_id,
            _by_delivery(operation.evidence),
        )
        entries.append(entry)
        state.posted[key] = entry
        if item.kind is not OperationKind.SALE:
            state.status[key] = (AdjustmentStatus.POSTED, None, transaction_id)

    ready: list[tuple] = []

    def release_children(parent: _Key) -> None:
        for child in children.get(parent, ()):
            kind = operations[child].reference.kind
            if child not in state.status and kind is not OperationKind.CHARGEBACK_REVERSAL:
                heapq.heappush(ready, _canonical(operations, child))

    post(sale_key, sale.reference.amount.minor)
    balance = sale.reference.amount.minor
    release_children(sale_key)
    while ready:
        key = heapq.heappop(ready)[2]
        item = operations[key].reference
        amount = item.amount.minor
        if item.amount.currency != currency:
            _reject(state, operations, key, ReconciliationReason.CURRENCY_MISMATCH, transaction_id)
            continue
        if item.kind is OperationKind.REFUND:
            if amount > balance:
                _reject(
                    state, operations, key, ReconciliationReason.EXCEEDS_OUTSTANDING, transaction_id
                )
                continue
            post(key, -amount)
            balance -= amount
            release_children(key)
        elif item.kind is OperationKind.CHARGEBACK:
            accepted = _accepted_reversals(state, operations, children, key, transaction_id)
            remainder = amount - sum(operations[r].reference.amount.minor for r in accepted)
            if remainder > balance:
                _reject(
                    state, operations, key, ReconciliationReason.EXCEEDS_OUTSTANDING, transaction_id
                )
                continue
            post(key, -amount)
            for reversal in accepted:
                post(reversal, operations[reversal].reference.amount.minor)
            balance -= remainder
            release_children(key)
            for reversal in accepted:
                release_children(reversal)
        else:  # an audited correction
            if balance + amount < 0:
                _reject(
                    state,
                    operations,
                    key,
                    ReconciliationReason.CORRECTION_BELOW_ZERO,
                    transaction_id,
                )
                continue
            post(key, amount)
            balance += amount
            release_children(key)

    state.transactions.append(
        Transaction(
            sale_key[0], transaction_id, currency, tuple(entries), _totals(currency, entries)
        )
    )


def _accepted_reversals(
    state: _State,
    operations: dict[_Key, _Operation],
    children: dict[_Key, list[_Key]],
    chargeback: _Key,
    transaction_id: str,
) -> list[_Key]:
    """Accept a chargeback's reversals in canonical order, up to the chargeback amount."""
    limit = operations[chargeback].reference.amount.minor
    currency = operations[chargeback].reference.amount.currency
    candidates = sorted(
        (
            child
            for child in children.get(chargeback, ())
            if child not in state.status
            and operations[child].reference.kind is OperationKind.CHARGEBACK_REVERSAL
        ),
        key=lambda child: _canonical(operations, child),
    )
    accepted: list[_Key] = []
    restored = 0
    for child in candidates:
        item = operations[child].reference
        if item.amount.currency != currency:
            _reject(
                state, operations, child, ReconciliationReason.CURRENCY_MISMATCH, transaction_id
            )
        elif restored + item.amount.minor > limit:
            _reject(
                state,
                operations,
                child,
                ReconciliationReason.REVERSAL_EXCEEDS_DEBIT,
                transaction_id,
            )
        else:
            accepted.append(child)
            restored += item.amount.minor
    return accepted


def _totals(currency: Currency, entries: list[RevenueEntry]) -> CurrencyTotals:
    amounts = dict.fromkeys(OperationKind, 0)
    for entry in entries:
        amounts[entry.kind] += entry.amount.minor
    return CurrencyTotals(
        currency,
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
        tuple(_arrival_key(record) for record in item.evidence),
    )
