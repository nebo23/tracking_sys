"""Provider-independent lead and revenue attribution (specification 008-A, D-046).

One run answers how much credit each eligible content interaction receives for one conversion,
under one version of one model. Everything is in memory: the journey is a synthetic, authorized
snapshot of touchpoints (the 006 identity and journey contracts are not implemented yet), and
the revenue of a sale is the authoritative state of one 007-A ledger transaction after a known
receipt, read from a LedgerCalculation (sale_state) or from the receipt journal (ledger_feed).

Rules (D-046, the Q-007 choices for this local synthetic slice):
- First Click, Last Click and Linear are calculated independently; results of different models
  are never added together. A lead carries one unit of lead credit split into exact Fraction
  shares and has no money. A sale carries the verified net of its own ledger transaction, in
  its original currency and integer minor units. A purchase signal or a manual declaration
  never posts in the ledger, so it supplies no verified revenue.
- The lookback window is configurable per model version (30 days by default) and inclusive at
  both ends: [conversion instant - window, conversion instant]. A sale's conversion instant is
  the authoritative effective instant of its sale in the ledger. Every instant is stored and
  compared in UTC. A window reaching before the earliest representable instant starts there;
  no instant can precede it, so the inclusive window keeps its meaning.
- A touch is eligible only when it is assigned to the converting person (006 owned segment),
  its attribution consent is currently granted, it is person-level evidence (aggregate platform
  metrics never are) and it lies in the window. Retries of one touchpoint ID with identical
  content count once; records of one touchpoint ID that disagree are excluded, because a wrong
  association is worse than a missing one. Distinct touchpoint IDs with the same content count
  separately. Touches of another agency, client or person are ignored and never listed.
- Eligible campaign interactions take precedence. Without one, an eligible direct visit
  receives the credit; without either, unknown receives all of it.
- Linear revenue is split by largest remainder; equal remainders go to the earlier touch in the
  stable order, so splitting one minor unit across two touches gives it to the first.
- A revision is recorded whenever the current view changes: the revenue state, the sale
  instant, the eligible and excluded touches, the evidence of a touch, or the allocations.
  Differences are signed and keyed by recipient, touchpoint and campaign, content and link
  provenance, so a report that applies them reaches the fresh calculation. Recalculating
  identical inputs under the same version returns the existing revision.

AttributionHistory keeps every revision and enforces the registry: one conversion per scoped
sale, one identity per conversion ID, one definition per model version ID (global to the
history), one currency per sale and non-decreasing ledger positions.

IncrementalAttribution consumes the receipt journal of ledger_feed(). A ledger receipt is the
atomic unit: its movements may arrive across transport pages, and only the item that closes a
receipt (index == count) carries the authoritative sale state after it. Identical items are
coalesced, a different item at a known position is a journal mismatch, and a missing position
is a journal gap. Each completed receipt yields its own revisions, the runs of one call are
committed together, and the checkpoint advances only after the commit. Durable positions,
atomic storage and permissions belong to 007-B; identity association of sales belongs to 007-C
and 006.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from fractions import Fraction
from hashlib import sha256
from math import floor
from uuid import UUID

from app.ledger import (
    Currency,
    Evidence,
    LedgerCalculation,
    LedgerScope,
    Money,
    Movement,
    Transaction,
    calculate,
)
from app.ledger.money import MAX_MINOR, require_aware, require_text, utc_instant
from app.privacy.consent import ConsentState

RULES = "008-A.1"
DEFAULT_WINDOW = timedelta(days=30)
EARLIEST_INSTANT = datetime.min.replace(tzinfo=UTC)
_JOURNAL_START = bytes(sha256().digest_size)


class AttributionInputError(ValueError):
    """A malformed or inconsistent input; code is a closed reason, never the rejected value."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AttributionModel(StrEnum):
    FIRST_CLICK = "first_click"
    LAST_CLICK = "last_click"
    LINEAR = "linear"


class ConversionKind(StrEnum):
    LEAD = "lead"
    SALE = "sale"


class EvidenceClass(StrEnum):
    """What a touch shows about the converting person (distinct from app.ledger.EvidenceClass)."""

    CAMPAIGN_INTERACTION = "campaign_interaction"  # a managed link or campaign-tagged visit
    DIRECT_VISIT = "direct_visit"  # a visit without link, campaign or referrer evidence
    AGGREGATE_METRIC = "aggregate_metric"  # platform counts; never identifies a buyer


class Association(StrEnum):
    """How the 006 journey relates a touch to the converting person."""

    ASSIGNED = "assigned"  # within the person's owned segment
    AMBIGUOUS = "ambiguous"  # an ambiguous segment; assigned to nobody
    UNRESOLVED = "unresolved"  # outside every owned segment
    EXCLUDED = "excluded"  # owned by another person, for example after a correction


class Recipient(StrEnum):
    CAMPAIGN = "campaign"
    DIRECT = "direct"
    UNKNOWN = "unknown"


class CreditBasis(StrEnum):
    CAMPAIGN = "campaign"  # eligible campaign interactions exist
    DIRECT_FALLBACK = "direct_fallback"  # no campaign interaction; an eligible direct visit
    UNKNOWN_FALLBACK = "unknown_fallback"  # no eligible evidence


class ExclusionReason(StrEnum):
    CONFLICTING_RECORDS = "conflicting_records"
    AGGREGATE_EVIDENCE = "aggregate_evidence"
    NOT_ASSIGNED = "association_not_assigned"
    CONSENT_NOT_GRANTED = "consent_not_granted"
    AFTER_CONVERSION = "after_conversion"
    BEFORE_WINDOW = "before_window"
    DIRECT_SUPERSEDED = "direct_superseded_by_campaign"


class RunStatus(StrEnum):
    COMPLETE = "complete"
    NO_VERIFIED_REVENUE = "no_verified_revenue"  # a sale without a posted ledger transaction
    NET_OUT_OF_RANGE = "net_out_of_range"  # the receipt's exact net exceeds the Money bound


class RevisionCause(StrEnum):
    INITIAL = "initial"
    REVENUE_CHANGED = "revenue_changed"  # the status or the net of the sale
    SALE_TIME_CHANGED = "sale_time_changed"  # the authoritative sale instant, hence the window
    TOUCHES_CHANGED = "touches_changed"  # the basis, or which touches are eligible or excluded
    EVIDENCE_CHANGED = "evidence_changed"  # the content or provenance of an eligible touch


_RECIPIENT = {
    CreditBasis.CAMPAIGN: Recipient.CAMPAIGN,
    CreditBasis.DIRECT_FALLBACK: Recipient.DIRECT,
    CreditBasis.UNKNOWN_FALLBACK: Recipient.UNKNOWN,
}


def _require_uuid(value: object, code: str) -> None:
    if not isinstance(value, UUID):
        raise AttributionInputError(code)


def _require_int(value: object, code: str, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise AttributionInputError(code)


def _optional_text(value: object, code: str) -> None:
    if value is not None:
        _text(value, code)


def _text(value: object, code: str) -> None:
    try:
        require_text(value, code)
    except ValueError as error:
        raise AttributionInputError(code) from error


def _utc(value: object, code: str) -> datetime:
    """The UTC instant of an aware datetime; one that cannot be expressed in UTC is refused."""
    try:
        require_aware(value, code)
        return utc_instant(value)
    except (ValueError, OverflowError) as error:
        raise AttributionInputError(code) from error


def _normalize(instance: object, name: str, code: str) -> None:
    object.__setattr__(instance, name, _utc(getattr(instance, name), code))


@dataclass(frozen=True, slots=True)
class ModelVersion:
    """One immutable version of one model: its ID, model, lookback window and rule set."""

    version_id: str
    model: AttributionModel
    window: timedelta = DEFAULT_WINDOW
    rules: str = RULES

    def __post_init__(self) -> None:
        _text(self.version_id, "invalid_model_version")
        if not isinstance(self.model, AttributionModel):
            raise AttributionInputError("invalid_model")
        if not isinstance(self.window, timedelta) or self.window <= timedelta(0):
            raise AttributionInputError("invalid_window")
        if self.rules != RULES:
            raise AttributionInputError("unsupported_rules")

    def window_start(self, end: datetime) -> datetime:
        """The inclusive start of the window ending at end, clamped to the earliest instant."""
        try:
            return end - self.window
        except OverflowError:
            return EARLIEST_INSTANT


@dataclass(frozen=True, slots=True)
class Touchpoint:
    """One interaction in a synthetic, authorized journey, with its current eligibility state.

    occurred_at is stored as its UTC instant. consent is the current state of the attribution
    purpose for the touch's collection subject (003-B); association is the current 006
    ownership decision. Both are re-read for every revision, so a withdrawal or a corrected
    ownership decision removes the touch.
    """

    touchpoint_id: str
    agency_id: UUID
    client_id: UUID
    person_id: str
    evidence_class: EvidenceClass
    occurred_at: datetime
    association: Association
    consent: ConsentState
    source: str | None = None
    campaign_ref: str | None = None
    content_ref: str | None = None
    link_ref: str | None = None

    def __post_init__(self) -> None:
        _text(self.touchpoint_id, "invalid_touchpoint_id")
        _require_uuid(self.agency_id, "invalid_agency")
        _require_uuid(self.client_id, "invalid_client")
        _text(self.person_id, "invalid_person")
        if not isinstance(self.evidence_class, EvidenceClass):
            raise AttributionInputError("invalid_evidence_class")
        _normalize(self, "occurred_at", "invalid_occurred_at")
        if not isinstance(self.association, Association):
            raise AttributionInputError("invalid_association")
        if not isinstance(self.consent, ConsentState):
            raise AttributionInputError("invalid_consent")
        for value, code in (
            (self.source, "invalid_source"),
            (self.campaign_ref, "invalid_campaign_ref"),
            (self.content_ref, "invalid_content_ref"),
            (self.link_ref, "invalid_link_ref"),
        ):
            _optional_text(value, code)
        tagged = self.campaign_ref is not None or self.link_ref is not None
        if self.evidence_class is EvidenceClass.CAMPAIGN_INTERACTION and not tagged:
            raise AttributionInputError("campaign_reference_required")
        if self.evidence_class is EvidenceClass.DIRECT_VISIT and tagged:
            raise AttributionInputError("direct_visit_has_campaign")

    @property
    def instant(self) -> datetime:
        return self.occurred_at

    @property
    def provenance(self) -> tuple[str | None, str | None, str | None, str | None]:
        return self.source, self.campaign_ref, self.content_ref, self.link_ref


@dataclass(frozen=True, slots=True)
class Conversion:
    """A lead or a verified sale of one person in one agency and client.

    A sale references one ledger transaction by its source account and the business operation
    ID of the sale. Its effective_at is the anchor used until the ledger supplies the
    authoritative sale instant; a run with a SaleState is anchored to that state instead.
    effective_at is stored as its UTC instant.
    """

    conversion_id: str
    agency_id: UUID
    client_id: UUID
    person_id: str
    kind: ConversionKind
    effective_at: datetime
    source_account_id: str | None = None
    transaction_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.conversion_id, "invalid_conversion_id")
        _require_uuid(self.agency_id, "invalid_agency")
        _require_uuid(self.client_id, "invalid_client")
        _text(self.person_id, "invalid_person")
        if not isinstance(self.kind, ConversionKind):
            raise AttributionInputError("invalid_conversion_kind")
        _normalize(self, "effective_at", "invalid_effective_at")
        if self.kind is ConversionKind.SALE:
            _text(self.source_account_id, "invalid_source_account")
            _text(self.transaction_id, "invalid_transaction")
        elif self.source_account_id is not None or self.transaction_id is not None:
            raise AttributionInputError("lead_has_transaction")

    @property
    def instant(self) -> datetime:
        return self.effective_at

    @property
    def key(self) -> tuple[UUID, UUID, str]:
        return self.agency_id, self.client_id, self.conversion_id

    @property
    def ledger_key(self) -> tuple[LedgerScope, str]:
        if self.kind is not ConversionKind.SALE:
            raise AttributionInputError("lead_has_transaction")
        scope = LedgerScope(self.agency_id, self.client_id, self.source_account_id)
        return scope, self.transaction_id

    @property
    def identity(self) -> tuple:
        """What a conversion ID always means; a sale's anchor may later be corrected."""
        anchor = self.effective_at if self.kind is ConversionKind.LEAD else None
        return (
            self.key,
            self.person_id,
            self.kind,
            self.source_account_id,
            self.transaction_id,
            anchor,
        )


@dataclass(frozen=True, slots=True)
class SaleState:
    """The authoritative 007-A state of one sale transaction after a known receipt.

    net_minor is exact and may transiently exceed the Money bound; such a state yields a
    net_out_of_range run instead of an allocation. effective_at is the sale's authoritative
    effective instant, stored in UTC.
    """

    scope: LedgerScope
    transaction_id: str
    currency: Currency
    effective_at: datetime
    net_minor: int

    def __post_init__(self) -> None:
        if not isinstance(self.scope, LedgerScope):
            raise AttributionInputError("invalid_sale_state")
        _text(self.transaction_id, "invalid_transaction")
        if not isinstance(self.currency, Currency):
            raise AttributionInputError("invalid_currency")
        _normalize(self, "effective_at", "invalid_effective_at")
        _require_int(self.net_minor, "invalid_net", 0)

    @property
    def key(self) -> tuple[LedgerScope, str]:
        return self.scope, self.transaction_id

    @property
    def net(self) -> Money | None:
        return Money(self.net_minor, self.currency) if self.net_minor < MAX_MINOR else None


def sale_conversion(transaction: Transaction, *, conversion_id: str, person_id: str) -> Conversion:
    """The sale conversion of a posted ledger transaction, anchored to its sale instant."""
    if not isinstance(transaction, Transaction):
        raise AttributionInputError("invalid_transaction")
    scope = transaction.scope
    return Conversion(
        conversion_id,
        scope.agency_id,
        scope.client_id,
        person_id,
        ConversionKind.SALE,
        transaction.sale.effective_at,
        scope.source_account_id,
        transaction.operation_id,
    )


def _state(transaction: Transaction) -> SaleState:
    return SaleState(
        transaction.scope,
        transaction.operation_id,
        transaction.currency,
        transaction.sale.effective_at,
        transaction.totals.net,
    )


def sale_states(ledger: LedgerCalculation) -> dict[tuple[LedgerScope, str], SaleState]:
    """The authoritative state of every posted sale transaction, keyed by scope and sale."""
    return {(t.scope, t.operation_id): _state(t) for t in ledger.transactions}


def receipt_payload(record: Evidence) -> str:
    """The canonical JSON a receipt digest binds: the full record with UTC instants."""
    normalized = replace(
        record,
        effective_at=_utc(record.effective_at, "invalid_effective_at"),
        received_at=_utc(record.received_at, "invalid_received_at"),
    )
    return json.dumps(asdict(normalized), sort_keys=True, separators=(",", ":"), default=str)


def receipt_digest(previous: bytes, record: Evidence) -> bytes:
    """The digest binding one receipt to its ordered prefix (the ledger_feed chain)."""
    return sha256(previous + receipt_payload(record).encode("utf-8")).digest()


JOURNAL_START = _JOURNAL_START


def sale_state(ledger: LedgerCalculation, conversion: Conversion) -> SaleState | None:
    """The authoritative state of the conversion's own transaction, or None if nothing posted."""
    if not isinstance(ledger, LedgerCalculation):
        raise AttributionInputError("invalid_ledger")
    if not isinstance(conversion, Conversion):
        raise AttributionInputError("invalid_conversion")
    scope, transaction_id = conversion.ledger_key
    for transaction in ledger.transactions:
        if transaction.scope == scope and transaction.operation_id == transaction_id:
            return _state(transaction)
    return None


@dataclass(frozen=True, slots=True)
class JournalItem:
    """One transport unit of the receipt journal.

    receipt is the 1-based position of the received record in the 007-A receipt log; index and
    count place the item within that receipt, which has one item per movement, or a single item
    without a movement. The closing item (index == count) carries the authoritative state,
    after the receipt, of every sale transaction the receipt moved or changed.
    All parts share the same two digests, binding the receipt to its original log prefix.
    """

    receipt: int
    index: int
    count: int
    movement: Movement | None
    sales: tuple[SaleState, ...] = ()
    previous_digest: bytes = field(kw_only=True)
    receipt_digest: bytes = field(kw_only=True)

    def __post_init__(self) -> None:
        _require_int(self.receipt, "invalid_journal_item", 1)
        _require_int(self.index, "invalid_journal_item", 1)
        _require_int(self.count, "invalid_journal_item", 1)
        for digest in (self.previous_digest, self.receipt_digest):
            if not isinstance(digest, bytes) or len(digest) != len(_JOURNAL_START):
                raise AttributionInputError("invalid_journal_item")
        if self.index > self.count:
            raise AttributionInputError("invalid_journal_item")
        if self.movement is None:
            if self.count != 1:
                raise AttributionInputError("invalid_journal_item")
        elif not isinstance(self.movement, Movement):
            raise AttributionInputError("invalid_journal_item")
        if not isinstance(self.sales, tuple) or not all(
            isinstance(state, SaleState) for state in self.sales
        ):
            raise AttributionInputError("invalid_journal_item")
        if self.sales and self.index != self.count:
            raise AttributionInputError("invalid_journal_item")
        if len({state.key for state in self.sales}) != len(self.sales):
            raise AttributionInputError("invalid_journal_item")

    @property
    def position(self) -> tuple[int, int]:
        return self.receipt, self.index

    @property
    def closes_receipt(self) -> bool:
        return self.index == self.count


def ledger_feed(records: Iterable[Evidence]) -> tuple[JournalItem, ...]:
    """The receipt journal of a 007-A receipt log, one receipt per supplied record.

    records is the receipt log in receipt order (non-decreasing receipt instants, as 007-A
    requires for replay). Each receipt's movements and closing sale states are taken from
    app.ledger.calculate() over the log up to and including that receipt.
    """
    log = list(records)
    if not all(isinstance(record, Evidence) for record in log):
        raise AttributionInputError("invalid_evidence")
    log = [
        replace(
            record,
            effective_at=_utc(record.effective_at, "invalid_effective_at"),
            received_at=_utc(record.received_at, "invalid_received_at"),
        )
        for record in log
    ]
    instants = [record.received_at for record in log]
    if any(later < earlier for earlier, later in zip(instants, instants[1:], strict=False)):
        raise AttributionInputError("receipt_log_out_of_order")
    items: list[JournalItem] = []
    movements: tuple[Movement, ...] = ()
    states: dict[tuple[LedgerScope, str], SaleState] = {}
    previous_digest = _JOURNAL_START
    for receipt, record in enumerate(log, start=1):
        # Bind the full input, including a pending receipt, to its ordered prefix.
        digest = receipt_digest(previous_digest, record)
        ledger = calculate(log[:receipt])
        if ledger.movements[: len(movements)] != movements:
            raise AttributionInputError("journal_not_append_only")
        new = ledger.movements[len(movements) :]
        current = {(t.scope, t.operation_id): _state(t) for t in ledger.transactions}
        if not states.keys() <= current.keys():
            raise AttributionInputError("journal_not_append_only")
        moved = {(m.scope, m.transaction_id) for m in new}
        closing = tuple(
            current[key]
            for key in sorted(current)
            if key in moved or states.get(key) != current[key]
        )
        parts = new or (None,)
        for index, movement in enumerate(parts, start=1):
            sales = closing if index == len(parts) else ()
            items.append(
                JournalItem(
                    receipt,
                    index,
                    len(parts),
                    movement,
                    sales,
                    previous_digest=previous_digest,
                    receipt_digest=digest,
                )
            )
        previous_digest = digest
        movements, states = ledger.movements, current
    return tuple(items)


@dataclass(frozen=True, slots=True)
class CreditAllocation:
    """The credit one recipient receives: an exact share and, for a sale, an amount.

    touch is the credited touchpoint with its source, campaign, content and link references; it
    is None only for unknown. amount is None for a lead, whose credit is the share alone.
    """

    recipient: Recipient
    basis: CreditBasis
    model: AttributionModel
    position: int  # 1-based position of the touch in the stable eligible order; 0 for unknown
    share: Fraction
    amount: Money | None
    touch: Touchpoint | None

    @property
    def key(self) -> tuple:
        """Recipient, touchpoint and provenance: a reassigned touch is a different key."""
        if self.touch is None:
            return self.recipient, None, None, None, None, None
        return self.recipient, self.touch.touchpoint_id, *self.touch.provenance

    @property
    def rule(self) -> str:
        return f"{self.model.value}/{self.basis.value}"


@dataclass(frozen=True, slots=True)
class ExcludedTouch:
    touchpoint_id: str
    reason: ExclusionReason


@dataclass(frozen=True, slots=True)
class CreditDifference:
    """The signed change of one recipient's credit, with the provenance it is booked under.

    A report that adds delta_share and delta_minor to the key (recipient, touchpoint and
    source, campaign, content and link references) reaches the allocations of the revision.
    """

    recipient: Recipient
    touchpoint_id: str | None
    source: str | None
    campaign_ref: str | None
    content_ref: str | None
    link_ref: str | None
    previous_share: Fraction
    share: Fraction
    previous_amount: Money | None
    amount: Money | None

    @property
    def delta_share(self) -> Fraction:
        return self.share - self.previous_share

    @property
    def delta_minor(self) -> int:
        before = self.previous_amount.minor if self.previous_amount else 0
        return (self.amount.minor if self.amount else 0) - before


@dataclass(frozen=True, slots=True)
class AttributionRun:
    """One revision of one conversion under one model version."""

    conversion: Conversion  # for a sale with a state, anchored to the authoritative sale instant
    model_version: ModelVersion
    revision: int
    status: RunStatus
    basis: CreditBasis
    eligible: tuple[Touchpoint, ...]  # the touches of the basis, in the stable order
    sale: SaleState | None
    verified_net: Money | None  # None for a lead and for a sale without allocatable revenue
    allocations: tuple[CreditAllocation, ...]
    excluded: tuple[ExcludedTouch, ...]
    window_start: datetime
    window_end: datetime
    ledger_position: int | None  # the last receipt reflected, when known
    causes: tuple[RevisionCause, ...]
    differences: tuple[CreditDifference, ...]

    @property
    def eligible_ids(self) -> tuple[str, ...]:
        return tuple(touch.touchpoint_id for touch in self.eligible)

    @property
    def outcome(self) -> tuple:
        """The current view; a change in it, and only that, records a new revision."""
        return (
            self.status,
            self.basis,
            self.sale,
            self.verified_net,
            self.window_end,
            self.eligible,
            self.allocations,
            self.excluded,
        )

    @property
    def credited_minor(self) -> int:
        return sum(a.amount.minor for a in self.allocations if a.amount is not None)

    @property
    def credited_share(self) -> Fraction:
        return sum((a.share for a in self.allocations), Fraction(0))


def attribute(
    conversion: Conversion,
    touchpoints: Iterable[Touchpoint],
    model_version: ModelVersion,
    *,
    sale: SaleState | None = None,
    ledger_position: int | None = None,
    previous: AttributionRun | None = None,
) -> AttributionRun:
    """Calculate one conversion under one model version.

    sale is the authoritative state of a sale's transaction after receipt ledger_position, or
    None while nothing has posted. previous is the latest revision for the same conversion and
    version, if any. A changed outcome returns the next revision with its causes and signed
    differences. For an unchanged outcome, a later receipt advances the position on the returned
    view while preserving the revision number and the original historical record. An older ledger
    position than previous, a different state at the same position, or a change of currency is
    refused.
    """
    if not isinstance(conversion, Conversion):
        raise AttributionInputError("invalid_conversion")
    if not isinstance(model_version, ModelVersion):
        raise AttributionInputError("invalid_model_version")
    touches = list(touchpoints)
    if not all(isinstance(touch, Touchpoint) for touch in touches):
        raise AttributionInputError("invalid_touchpoint")
    if ledger_position is not None:
        _require_int(ledger_position, "invalid_ledger_position", 0)
    if conversion.kind is ConversionKind.LEAD:
        if sale is not None:
            raise AttributionInputError("lead_has_revenue")
    elif sale is not None:
        if not isinstance(sale, SaleState):
            raise AttributionInputError("invalid_sale_state")
        if sale.key != conversion.ledger_key:
            raise AttributionInputError("sale_mismatch")
        if sale.effective_at != conversion.effective_at:
            conversion = replace(conversion, effective_at=sale.effective_at)
    if previous is not None:
        _check_previous(previous, conversion, model_version, sale, ledger_position)

    end = conversion.effective_at
    start = model_version.window_start(end)
    eligible, excluded = _eligible(conversion, touches, start, end)
    campaign = [t for t in eligible if t.evidence_class is EvidenceClass.CAMPAIGN_INTERACTION]
    direct = [t for t in eligible if t.evidence_class is EvidenceClass.DIRECT_VISIT]
    if campaign:
        basis, ordered = CreditBasis.CAMPAIGN, campaign
        excluded += [
            ExcludedTouch(t.touchpoint_id, ExclusionReason.DIRECT_SUPERSEDED) for t in direct
        ]
    elif direct:
        basis, ordered = CreditBasis.DIRECT_FALLBACK, direct
    else:
        basis, ordered = CreditBasis.UNKNOWN_FALLBACK, []

    net = sale.net if sale is not None else None
    allocations: tuple[CreditAllocation, ...] = ()
    if conversion.kind is ConversionKind.LEAD:
        status = RunStatus.COMPLETE
        allocations = _allocate(model_version.model, basis, ordered, None)
    elif sale is None:
        status = RunStatus.NO_VERIFIED_REVENUE
    elif net is None:
        status = RunStatus.NET_OUT_OF_RANGE
    else:
        status = RunStatus.COMPLETE
        allocations = _allocate(model_version.model, basis, ordered, net)

    run = AttributionRun(
        conversion=conversion,
        model_version=model_version,
        revision=1,
        status=status,
        basis=basis,
        eligible=tuple(ordered),
        sale=sale,
        verified_net=net,
        allocations=allocations,
        excluded=tuple(sorted(excluded, key=lambda e: (e.touchpoint_id, e.reason.value))),
        window_start=start,
        window_end=end,
        ledger_position=ledger_position,
        causes=(RevisionCause.INITIAL,),
        differences=(),
    )
    if previous is None:
        return run
    if previous.outcome == run.outcome:
        if conversion.kind is ConversionKind.SALE and ledger_position != previous.ledger_position:
            return replace(previous, ledger_position=ledger_position)
        return previous
    return replace(
        run,
        revision=previous.revision + 1,
        causes=_causes(previous, run),
        differences=_differences(previous, run),
    )


def _check_previous(
    previous: AttributionRun,
    conversion: Conversion,
    model_version: ModelVersion,
    sale: SaleState | None,
    ledger_position: int | None,
) -> None:
    if (
        not isinstance(previous, AttributionRun)
        or previous.conversion.identity != conversion.identity
        or previous.model_version != model_version
    ):
        raise AttributionInputError("revision_mismatch")
    if conversion.kind is ConversionKind.SALE:
        _check_sale_observation(previous.sale, previous.ledger_position, sale, ledger_position)


def _check_sale_observation(
    prior: SaleState | None,
    prior_position: int | None,
    sale: SaleState | None,
    ledger_position: int | None,
) -> None:
    if prior is not None and sale is not None and prior.currency != sale.currency:
        raise AttributionInputError("currency_changed")
    if prior_position is not None:
        if ledger_position is None:
            raise AttributionInputError("ledger_position_required")
        if ledger_position < prior_position:
            raise AttributionInputError("stale_ledger_position")
        if ledger_position == prior_position and sale != prior:
            raise AttributionInputError("ledger_position_conflict")
    if prior is not None and sale is None:
        raise AttributionInputError("sale_state_missing")


def _causes(previous: AttributionRun, run: AttributionRun) -> tuple[RevisionCause, ...]:
    causes = []
    before_net = previous.sale.net_minor if previous.sale else None
    after_net = run.sale.net_minor if run.sale else None
    if (previous.status, before_net) != (run.status, after_net):
        causes.append(RevisionCause.REVENUE_CHANGED)
    if previous.window_end != run.window_end:
        causes.append(RevisionCause.SALE_TIME_CHANGED)
    if (previous.basis, previous.eligible_ids, previous.excluded) != (
        run.basis,
        run.eligible_ids,
        run.excluded,
    ):
        causes.append(RevisionCause.TOUCHES_CHANGED)
    before = {touch.touchpoint_id: touch for touch in previous.eligible}
    if any(
        touch != before[touch.touchpoint_id]
        for touch in run.eligible
        if touch.touchpoint_id in before
    ):
        causes.append(RevisionCause.EVIDENCE_CHANGED)
    return tuple(causes)


def _eligible(
    conversion: Conversion, touches: list[Touchpoint], start: datetime, end: datetime
) -> tuple[list[Touchpoint], list[ExcludedTouch]]:
    scope = (conversion.agency_id, conversion.client_id, conversion.person_id)
    groups: dict[str, list[Touchpoint]] = {}
    for touch in touches:
        if (touch.agency_id, touch.client_id, touch.person_id) == scope:
            groups.setdefault(touch.touchpoint_id, []).append(touch)
    eligible: list[Touchpoint] = []
    excluded: list[ExcludedTouch] = []
    for touchpoint_id, records in groups.items():
        touch = records[0]
        if any(record != touch for record in records):
            reason = ExclusionReason.CONFLICTING_RECORDS
        elif touch.evidence_class is EvidenceClass.AGGREGATE_METRIC:
            reason = ExclusionReason.AGGREGATE_EVIDENCE
        elif touch.association is not Association.ASSIGNED:
            reason = ExclusionReason.NOT_ASSIGNED
        elif touch.consent is not ConsentState.GRANTED:
            reason = ExclusionReason.CONSENT_NOT_GRANTED
        elif touch.instant > end:
            reason = ExclusionReason.AFTER_CONVERSION
        elif touch.instant < start:
            reason = ExclusionReason.BEFORE_WINDOW
        else:
            eligible.append(touch)
            continue
        excluded.append(ExcludedTouch(touchpoint_id, reason))
    eligible.sort(key=lambda t: (t.instant, t.touchpoint_id))
    return eligible, excluded


def _allocate(
    model: AttributionModel,
    basis: CreditBasis,
    ordered: list[Touchpoint],
    net: Money | None,
) -> tuple[CreditAllocation, ...]:
    recipient = _RECIPIENT[basis]
    if not ordered:
        return (CreditAllocation(recipient, basis, model, 0, Fraction(1), net, None),)
    positions = list(enumerate(ordered, start=1))
    if model is AttributionModel.FIRST_CLICK:
        credited = positions[:1]
    elif model is AttributionModel.LAST_CLICK:
        credited = positions[-1:]
    else:
        credited = positions
    shares = [Fraction(1, len(credited))] * len(credited)
    amounts = _largest_remainder(net.minor, shares) if net is not None else [None] * len(shares)
    return tuple(
        CreditAllocation(
            recipient,
            basis,
            model,
            position,
            share,
            Money(minor, net.currency) if net is not None else None,
            touch,
        )
        for (position, touch), share, minor in zip(credited, shares, amounts, strict=True)
    )


def _largest_remainder(total: int, shares: list[Fraction]) -> list[int]:
    """Integer amounts summing exactly to total; ties in remainder go to the earlier share."""
    exact = [total * share for share in shares]
    amounts = [floor(value) for value in exact]
    leftover = total - sum(amounts)
    order = sorted(range(len(shares)), key=lambda i: (-(exact[i] - amounts[i]), i))
    for index in order[:leftover]:
        amounts[index] += 1
    return amounts


def _differences(previous: AttributionRun, run: AttributionRun) -> tuple[CreditDifference, ...]:
    before = {allocation.key: allocation for allocation in previous.allocations}
    after = {allocation.key: allocation for allocation in run.allocations}
    keys = list(after) + [key for key in before if key not in after]
    differences = []
    for key in keys:
        old, new = before.get(key), after.get(key)
        difference = CreditDifference(
            *key,
            old.share if old else Fraction(0),
            new.share if new else Fraction(0),
            old.amount if old else None,
            new.amount if new else None,
        )
        if difference.delta_share or difference.delta_minor or (old is None) != (new is None):
            differences.append(difference)
    return tuple(differences)


_RunKey = tuple[UUID, UUID, str, str]
_LedgerKey = tuple[LedgerScope, str]
_ConversionKey = tuple[UUID, UUID, str]
_JourneyKey = tuple[UUID, UUID, str]


def _run_key(conversion: Conversion, version: ModelVersion) -> _RunKey:
    return *conversion.key, version.version_id


class AttributionHistory:
    """Every revision of every run, kept per conversion and model version; nothing is replaced.

    The history is also the registry the revisions are checked against. A conversion ID keeps
    one identity (person, kind, ledger transaction and, for a lead, its instant). A scoped sale
    (agency, client, source account and sale operation ID) belongs to one conversion, so it is
    credited once per model. A model version ID means one definition across the whole history.
    A sale keeps its currency, and its ledger position never moves backwards. Reads and writes
    with a conflicting conversion or model definition are refused.
    """

    def __init__(self) -> None:
        self._runs: dict[_RunKey, tuple[AttributionRun, ...]] = {}
        self._conversions: dict[_ConversionKey, Conversion] = {}
        self._sales: dict[_LedgerKey, _ConversionKey] = {}
        self._models: dict[str, ModelVersion] = {}
        self._observations: dict[_LedgerKey, tuple[SaleState | None, int | None]] = {}
        self._journeys: dict[_JourneyKey, tuple[Touchpoint, ...]] = {}

    def _stage(self) -> "AttributionHistory":
        """Isolate a consumer call until its commit succeeds. All mapping values are immutable."""
        staged = AttributionHistory()
        staged._runs = self._runs.copy()
        staged._conversions = self._conversions.copy()
        staged._sales = self._sales.copy()
        staged._models = self._models.copy()
        staged._observations = self._observations.copy()
        staged._journeys = self._journeys.copy()
        return staged

    def _publish(self, staged: "AttributionHistory") -> None:
        self._runs = staged._runs
        self._conversions = staged._conversions
        self._sales = staged._sales
        self._models = staged._models
        self._observations = staged._observations
        self._journeys = staged._journeys

    def _check_observation(
        self, conversion: Conversion, sale: SaleState | None, position: int | None
    ) -> None:
        if conversion.kind is ConversionKind.SALE and conversion.ledger_key in self._observations:
            _check_sale_observation(*self._observations[conversion.ledger_key], sale, position)

    def _caught_up(self, key: _LedgerKey, sale: SaleState | None, position: int) -> bool:
        prior, known_position = self._observations.get(key, (None, None))
        if known_position is not None:
            return position >= known_position
        # A snapshot supplied without a position can anchor replay at its matching state.
        if prior is not None and sale is not None and prior.currency != sale.currency:
            raise AttributionInputError("currency_changed")
        return prior is None or prior == sale

    def check_conversion(self, conversion: Conversion) -> None:
        if not isinstance(conversion, Conversion):
            raise AttributionInputError("invalid_conversion")
        known = self._conversions.get(conversion.key)
        if known is not None and known.identity != conversion.identity:
            raise AttributionInputError("conversion_mismatch")
        if conversion.kind is ConversionKind.SALE:
            owner = self._sales.get(conversion.ledger_key)
            if owner is not None and owner != conversion.key:
                if self._conversions[owner].person_id != conversion.person_id:
                    raise AttributionInputError("sale_association_conflict")
                raise AttributionInputError("sale_already_registered")

    def check_model(self, version: ModelVersion) -> None:
        if not isinstance(version, ModelVersion):
            raise AttributionInputError("invalid_model_version")
        known = self._models.get(version.version_id)
        if known is not None and known != version:
            raise AttributionInputError("model_version_conflict")

    def register(self, conversion: Conversion) -> None:
        """Register a conversion; an identical or re-anchored registration changes nothing else."""
        self.check_conversion(conversion)
        self._conversions[conversion.key] = conversion
        if conversion.kind is ConversionKind.SALE:
            self._sales[conversion.ledger_key] = conversion.key

    def conversion(self, key: _ConversionKey) -> Conversion | None:
        return self._conversions.get(key)

    def latest(self, conversion: Conversion, version: ModelVersion) -> AttributionRun | None:
        self.check_conversion(conversion)
        self.check_model(version)
        runs = self._runs.get(_run_key(conversion, version))
        if not runs:
            return None
        run = runs[-1]
        if conversion.kind is ConversionKind.SALE:
            sale, position = self._observations[conversion.ledger_key]
            if sale == run.sale and position != run.ledger_position:
                return replace(run, ledger_position=position)
        return run

    def revisions(
        self, conversion: Conversion, version: ModelVersion
    ) -> tuple[AttributionRun, ...]:
        self.check_conversion(conversion)
        self.check_model(version)
        return tuple(self._runs.get(_run_key(conversion, version), ()))

    def check_record(self, run: AttributionRun) -> None:
        if not isinstance(run, AttributionRun):
            raise AttributionInputError("invalid_run")
        self.check_conversion(run.conversion)
        self.check_model(run.model_version)
        self._check_observation(run.conversion, run.sale, run.ledger_position)
        runs = self._runs.get(_run_key(run.conversion, run.model_version), ())
        if runs and run.revision == runs[-1].revision:
            if run == replace(runs[-1], ledger_position=run.ledger_position):
                return
        if run.revision != len(runs) + 1:
            raise AttributionInputError("revision_out_of_order")
        if runs:
            _check_previous(
                runs[-1], run.conversion, run.model_version, run.sale, run.ledger_position
            )

    def record(self, run: AttributionRun) -> AttributionRun:
        """Append the next revision; recording the latest revision again changes nothing."""
        self.check_record(run)
        key = _run_key(run.conversion, run.model_version)
        runs = self._runs.get(key, ())
        self.register(run.conversion)
        self._models[run.model_version.version_id] = run.model_version
        if run.conversion.kind is ConversionKind.SALE:
            self._observations[run.conversion.ledger_key] = (run.sale, run.ledger_position)
        if not runs or run.revision != runs[-1].revision:
            self._runs[key] = (*runs, run)
        return run

    def calculate(
        self,
        conversion: Conversion,
        touchpoints: Iterable[Touchpoint],
        model_version: ModelVersion,
        *,
        sale: SaleState | None = None,
        ledger_position: int | None = None,
    ) -> AttributionRun:
        previous = self.latest(conversion, model_version)
        touches = tuple(touchpoints)
        run = attribute(
            conversion,
            touches,
            model_version,
            sale=sale,
            ledger_position=ledger_position,
            previous=previous,
        )
        self.record(run)
        journey = _journey_key(conversion)
        self._journeys[journey] = tuple(
            t for t in touches if (t.agency_id, t.client_id, t.person_id) == journey
        )
        return run


_Position = tuple[int, int]


class IncrementalAttribution:
    """Keeps attribution current from the receipt journal and journey updates.

    Each call is one atomic step: new runs are calculated first, then handed to commit (the
    in-memory stand-in for a 007-B transactional write); only when commit returns are the
    history, sale states, journeys, buffered items and the receipt checkpoint updated. A failed
    commit leaves everything as it was, so the same items can be applied again.

    A consumer attached to a populated history restores its scoped journeys and waits until
    replay reaches each sale's recorded position. An unchanged outcome preserves its revision.
    """

    def __init__(
        self,
        versions: Iterable[ModelVersion],
        *,
        commit: Callable[[tuple[AttributionRun, ...]], None] | None = None,
        history: AttributionHistory | None = None,
    ) -> None:
        self.versions = tuple(versions)
        if not self.versions or not all(isinstance(v, ModelVersion) for v in self.versions):
            raise AttributionInputError("invalid_model_version")
        if len({v.version_id for v in self.versions}) != len(self.versions):
            raise AttributionInputError("duplicate_model_version")
        self.history = history if history is not None else AttributionHistory()
        for version in self.versions:
            self.history.check_model(version)
        self._commit = commit
        self.checkpoint = 0  # the last completed receipt
        self._applied: dict[_Position, JournalItem] = {}
        self._buffer: dict[_Position, JournalItem] = {}
        self._nets: dict[_LedgerKey, int] = {}
        self._sales: dict[_LedgerKey, SaleState] = {}
        self._conversions: dict[_ConversionKey, Conversion] = {}

    @property
    def buffered(self) -> int:
        """Items of the incomplete receipt received so far; they are not yet applied."""
        return len(self._buffer)

    def sale(self, conversion: Conversion) -> SaleState | None:
        self.history.check_conversion(conversion)
        state = self._sales.get(conversion.ledger_key)
        if state is not None and self.history.conversion(conversion.key) is None:
            raise AttributionInputError("conversion_not_registered")
        return state

    def net(self, conversion: Conversion) -> Money | None:
        state = self.sale(conversion)
        return state.net if state is not None else None

    def runs(self, conversion: Conversion) -> dict[str, AttributionRun]:
        return {
            version.version_id: run
            for version in self.versions
            if (run := self.history.latest(conversion, version)) is not None
        }

    def register(self, conversion: Conversion) -> tuple[AttributionRun, ...]:
        """Register a conversion; a retry is idempotent and a sale may be re-anchored."""
        staged = self.history._stage()
        staged.check_conversion(conversion)
        if staged.conversion(conversion.key) is None:
            staged._journeys.setdefault(_journey_key(conversion), ())
        staged.register(conversion)
        runs = tuple(self._calculate([conversion], self._sales, self.checkpoint, staged))
        self._finish(runs, staged)
        self._conversions[conversion.key] = conversion
        return runs

    def set_journey(
        self, agency_id: UUID, client_id: UUID, person_id: str, touchpoints: Iterable[Touchpoint]
    ) -> tuple[AttributionRun, ...]:
        """Replace one person's journey snapshot with the current touches and decisions."""
        touches = tuple(touchpoints)
        if not all(isinstance(touch, Touchpoint) for touch in touches):
            raise AttributionInputError("invalid_touchpoint")
        journey = (agency_id, client_id, person_id)
        if any((t.agency_id, t.client_id, t.person_id) != journey for t in touches):
            raise AttributionInputError("journey_scope_mismatch")
        staged = self.history._stage()
        staged._journeys[journey] = touches
        affected = [c for c in self._conversions.values() if _journey_key(c) == journey]
        runs = tuple(self._calculate(affected, self._sales, self.checkpoint, staged))
        self._finish(runs, staged)
        return runs

    def apply(self, items: Iterable[JournalItem]) -> tuple[AttributionRun, ...]:
        """Apply one page of the receipt journal.

        Items already applied or buffered are skipped when identical and refused as
        journal_mismatch otherwise; identical copies within the page are coalesced. The new
        items must continue the journal without a hole (journal_gap). Every receipt the page
        completes is applied in order and yields its own revisions; the items of an incomplete
        receipt are buffered. Nothing changes when the page is refused or commit fails.
        """
        page = list(items)
        if not all(isinstance(item, JournalItem) for item in page):
            raise AttributionInputError("invalid_journal_item")
        new: dict[_Position, JournalItem] = {}
        for item in page:
            known = (
                self._applied.get(item.position)
                or self._buffer.get(item.position)
                or new.get(item.position)
            )
            if known is None:
                new[item.position] = item
            elif known != item:
                raise AttributionInputError("journal_mismatch")
        buffer = dict(self._buffer)
        position, sequence, last = self._cursor()
        for key in sorted(new):
            item = new[key]
            if key < position:
                raise AttributionInputError("journal_mismatch")
            if key != position:
                raise AttributionInputError("journal_gap")
            if item.index == 1:
                expected = last.receipt_digest if last else _JOURNAL_START
                if item.previous_digest != expected:
                    raise AttributionInputError("journal_mismatch")
            elif (item.count, item.previous_digest, item.receipt_digest) != (
                last.count,
                last.previous_digest,
                last.receipt_digest,
            ):
                raise AttributionInputError("journal_mismatch")
            if item.movement is not None:
                if item.movement.sequence != sequence + 1:
                    raise AttributionInputError("journal_mismatch")
                sequence += 1
            last = item
            position = (
                (item.receipt, item.index + 1) if item.index < item.count else (item.receipt + 1, 1)
            )
            buffer[key] = item

        nets, sales, staged = dict(self._nets), dict(self._sales), self.history._stage()
        applied: dict[_Position, JournalItem] = {}
        checkpoint, runs = self.checkpoint, []
        while (first := buffer.get((checkpoint + 1, 1))) is not None:
            receipt = checkpoint + 1
            parts = [buffer.get((receipt, index)) for index in range(1, first.count + 1)]
            if None in parts:
                break
            changed = self._apply_receipt(parts, nets, sales)
            affected = [
                c
                for c in self._conversions.values()
                if c.kind is ConversionKind.SALE
                and (
                    c.ledger_key in changed
                    or staged._observations.get(c.ledger_key, (None, None))[1] == receipt
                )
            ]
            runs += self._calculate(affected, sales, receipt, staged)
            for part in parts:
                applied[part.position] = buffer.pop(part.position)
            checkpoint = receipt
        result = tuple(runs)
        if checkpoint > self.checkpoint:
            for conversion in self._conversions.values():
                if conversion.kind is ConversionKind.SALE:
                    key = conversion.ledger_key
                    if staged._caught_up(key, sales.get(key), checkpoint):
                        staged._check_observation(conversion, sales.get(key), checkpoint)
                        staged._observations[key] = (sales.get(key), checkpoint)
        self._finish(result, staged)
        self._applied.update(applied)
        self._buffer, self._nets, self._sales = buffer, nets, sales
        self.checkpoint = checkpoint
        return result

    def _cursor(self) -> tuple[_Position, int, JournalItem | None]:
        """The next expected position, last movement sequence and preceding item."""
        items = list(self._applied.values()) + list(self._buffer.values())
        if not items:
            return (1, 1), 0, None
        last = max(items, key=lambda item: item.position)
        sequence = max((i.movement.sequence for i in items if i.movement is not None), default=0)
        if last.index < last.count:
            return (last.receipt, last.index + 1), sequence, last
        return (last.receipt + 1, 1), sequence, last

    @staticmethod
    def _apply_receipt(
        parts: list[JournalItem],
        nets: dict[_LedgerKey, int],
        sales: dict[_LedgerKey, SaleState],
    ) -> set[_LedgerKey]:
        """Accumulate one receipt exactly and check it against its closing sale states."""
        closing = {state.key: state for state in parts[-1].sales}
        for part in parts:
            if part.movement is None:
                continue
            key = (part.movement.scope, part.movement.transaction_id)
            state = closing.get(key)
            if state is None or part.movement.amount.currency != state.currency:
                raise AttributionInputError("journal_mismatch")
            nets[key] = nets.get(key, 0) + part.movement.amount.minor
        for key, state in closing.items():
            prior = sales.get(key)
            if prior is not None and prior.currency != state.currency:
                raise AttributionInputError("currency_changed")
            if nets.get(key, 0) != state.net_minor:
                raise AttributionInputError("journal_mismatch")
            sales[key] = state
        return set(closing)

    def _calculate(
        self,
        conversions: list[Conversion],
        sales: dict[_LedgerKey, SaleState],
        position: int,
        staged: AttributionHistory,
    ) -> list[AttributionRun]:
        runs = []
        for conversion in sorted(conversions, key=_conversion_order):
            is_sale = conversion.kind is ConversionKind.SALE
            sale = sales.get(conversion.ledger_key) if is_sale else None
            if is_sale:
                if not staged._caught_up(conversion.ledger_key, sale, position):
                    continue
                staged._check_observation(conversion, sale, position)
            journey = _journey_key(conversion)
            if journey not in staged._journeys:
                # A standalone recorded run does not contain the original journey.
                # Refuse a changed sale until the caller supplies the journey and retries.
                if (
                    is_sale
                    and sale != staged._observations.get(conversion.ledger_key, (None, None))[0]
                ):
                    raise AttributionInputError("journey_required")
                continue
            for version in self.versions:
                previous = staged.latest(conversion, version)
                run = attribute(
                    conversion,
                    staged._journeys[journey],
                    version,
                    sale=sale,
                    ledger_position=position if is_sale else None,
                    previous=previous,
                )
                staged.record(run)
                if previous is None or run.revision != previous.revision:
                    runs.append(run)
        return runs

    def _finish(self, runs: tuple[AttributionRun, ...], staged: AttributionHistory) -> None:
        if self._commit is not None and runs:
            self._commit(runs)  # may raise: nothing below runs, no state has changed
        self.history._publish(staged)


def _journey_key(conversion: Conversion) -> _JourneyKey:
    return conversion.agency_id, conversion.client_id, conversion.person_id


def _conversion_order(conversion: Conversion) -> tuple:
    return str(conversion.agency_id), str(conversion.client_id), conversion.conversion_id
