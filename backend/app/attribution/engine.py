"""Provider-independent lead and revenue attribution (specification 008-A, D-046).

One run answers how much credit each eligible content interaction receives for one conversion,
under one version of one model. Everything is in memory: the journey is a synthetic, authorized
snapshot of touchpoints (the 006 identity and journey contracts are not implemented yet), and
the revenue of a sale is the verified net of one 007-A ledger transaction, read from a
LedgerCalculation or accumulated from its movement journal.

Rules (D-046, the Q-007 choices for this local synthetic slice):
- First Click, Last Click and Linear are calculated independently; results of different models
  are never added together. A lead carries one unit of lead credit split into exact Fraction
  shares and has no money. A sale carries the verified net of its own ledger transaction, in
  its original currency and integer minor units. A purchase signal or a manual declaration
  never posts in the ledger, so it supplies no verified revenue.
- The lookback window is configurable per model version (30 days by default) and inclusive at
  both ends: [conversion instant - window, conversion instant]. Instants are compared in UTC.
  Eligible touches are ordered by occurrence instant, then by touchpoint ID.
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
- A revision is recorded when the outcome changes: a refund, chargeback, correction or release
  changes the transaction net (the conversion stays anchored to the original sale instant), or
  the journey changes (a late eligible touch, a consent withdrawal or an ownership correction).
  Each revision keeps its model version and lists the signed difference from the previous one.
  Recalculating identical inputs under the same version returns the existing revision.

IncrementalAttribution consumes the ledger movement journal: each movement is applied once,
in sequence order, and the checkpoint advances only after the resulting runs are committed.
Durable positions, atomic storage and permissions belong to 007-B; identity association of
sales belongs to 007-C and 006.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from fractions import Fraction
from math import floor
from uuid import UUID

from app.ledger import LedgerCalculation, LedgerScope, Money, Movement, Transaction
from app.ledger.money import require_aware, require_text, utc_instant
from app.privacy.consent import ConsentState

RULES = "008-A.1"
DEFAULT_WINDOW = timedelta(days=30)


class AttributionInputError(ValueError):
    """A malformed attribution input; code is a closed reason, never the rejected value."""

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


class RevisionCause(StrEnum):
    INITIAL = "initial"
    REVENUE_CHANGED = "revenue_changed"
    TOUCHES_CHANGED = "touches_changed"


_RECIPIENT = {
    CreditBasis.CAMPAIGN: Recipient.CAMPAIGN,
    CreditBasis.DIRECT_FALLBACK: Recipient.DIRECT,
    CreditBasis.UNKNOWN_FALLBACK: Recipient.UNKNOWN,
}


def _require_uuid(value: object, code: str) -> None:
    if not isinstance(value, UUID):
        raise AttributionInputError(code)


def _optional_text(value: object, code: str) -> None:
    if value is not None:
        _text(value, code)


def _text(value: object, code: str) -> None:
    try:
        require_text(value, code)
    except ValueError as error:
        raise AttributionInputError(code) from error


def _aware(value: object, code: str) -> None:
    try:
        require_aware(value, code)
    except ValueError as error:
        raise AttributionInputError(code) from error


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


@dataclass(frozen=True, slots=True)
class Touchpoint:
    """One interaction in a synthetic, authorized journey, with its current eligibility state.

    consent is the current state of the attribution purpose for the touch's collection subject
    (003-B); association is the current 006 ownership decision. Both are re-read for every
    revision, so a withdrawal or a corrected ownership decision removes the touch.
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
        _aware(self.occurred_at, "invalid_occurred_at")
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
        return utc_instant(self.occurred_at)

    def _facts(self) -> tuple:
        """Content compared between retries; the occurrence time is compared as an instant."""
        return (
            self.agency_id,
            self.client_id,
            self.person_id,
            self.evidence_class,
            self.instant,
            self.association,
            self.consent,
            self.source,
            self.campaign_ref,
            self.content_ref,
            self.link_ref,
        )


@dataclass(frozen=True, slots=True)
class Conversion:
    """A lead or a verified sale of one person in one agency and client.

    A sale references one ledger transaction by its source account and the business operation
    ID of the sale; effective_at is the sale's original effective instant, which stays the anchor
    of the window when refunds or releases change the net later.
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
        _aware(self.effective_at, "invalid_effective_at")
        if self.kind is ConversionKind.SALE:
            _text(self.source_account_id, "invalid_source_account")
            _text(self.transaction_id, "invalid_transaction")
        elif self.source_account_id is not None or self.transaction_id is not None:
            raise AttributionInputError("lead_has_transaction")

    @property
    def instant(self) -> datetime:
        return utc_instant(self.effective_at)

    @property
    def ledger_key(self) -> tuple[LedgerScope, str]:
        if self.kind is not ConversionKind.SALE:
            raise AttributionInputError("lead_has_transaction")
        scope = LedgerScope(self.agency_id, self.client_id, self.source_account_id)
        return scope, self.transaction_id


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


def verified_net(ledger: LedgerCalculation, conversion: Conversion) -> Money | None:
    """The verified net of the conversion's own transaction, or None when nothing posted."""
    if not isinstance(ledger, LedgerCalculation):
        raise AttributionInputError("invalid_ledger")
    scope, transaction_id = conversion.ledger_key
    for transaction in ledger.transactions:
        if transaction.scope == scope and transaction.operation_id == transaction_id:
            return transaction.net
    return None


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
    def key(self) -> tuple[Recipient, str | None]:
        return self.recipient, self.touch.touchpoint_id if self.touch else None

    @property
    def rule(self) -> str:
        return f"{self.model.value}/{self.basis.value}"


@dataclass(frozen=True, slots=True)
class ExcludedTouch:
    touchpoint_id: str
    reason: ExclusionReason


@dataclass(frozen=True, slots=True)
class CreditDifference:
    """The signed change of one recipient's credit from the previous revision."""

    recipient: Recipient
    touchpoint_id: str | None
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

    conversion: Conversion
    model_version: ModelVersion
    revision: int
    status: RunStatus
    basis: CreditBasis
    eligible: tuple[str, ...]  # touchpoint IDs of the basis, in the stable order
    verified_net: Money | None  # None for a lead and for a sale without verified revenue
    allocations: tuple[CreditAllocation, ...]
    excluded: tuple[ExcludedTouch, ...]
    window_start: datetime
    window_end: datetime
    ledger_position: int | None  # the last movement sequence reflected, when known
    causes: tuple[RevisionCause, ...]
    differences: tuple[CreditDifference, ...]

    @property
    def outcome(self) -> tuple:
        """What a revision decides; a change in it, and only that, records a new revision."""
        return self.status, self.basis, self.verified_net, self.allocations

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
    verified_net: Money | None = None,
    ledger_position: int | None = None,
    previous: AttributionRun | None = None,
) -> AttributionRun:
    """Calculate one conversion under one model version.

    previous is the latest revision for the same conversion and version, if any. When the new
    outcome equals it, previous is returned unchanged; otherwise the next revision is returned
    with the signed differences.
    """
    if not isinstance(conversion, Conversion):
        raise AttributionInputError("invalid_conversion")
    if not isinstance(model_version, ModelVersion):
        raise AttributionInputError("invalid_model_version")
    touches = list(touchpoints)
    if not all(isinstance(touch, Touchpoint) for touch in touches):
        raise AttributionInputError("invalid_touchpoint")
    if conversion.kind is ConversionKind.LEAD and verified_net is not None:
        raise AttributionInputError("lead_has_revenue")
    if verified_net is not None and (not isinstance(verified_net, Money) or verified_net.minor < 0):
        raise AttributionInputError("invalid_net")
    if previous is not None and (
        not isinstance(previous, AttributionRun)
        or previous.conversion != conversion
        or previous.model_version != model_version
    ):
        raise AttributionInputError("revision_mismatch")

    end = conversion.instant
    start = end - model_version.window
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

    status = RunStatus.COMPLETE
    if conversion.kind is ConversionKind.SALE and verified_net is None:
        status = RunStatus.NO_VERIFIED_REVENUE
        allocations: tuple[CreditAllocation, ...] = ()
    else:
        allocations = _allocate(model_version.model, basis, ordered, verified_net)

    run = AttributionRun(
        conversion=conversion,
        model_version=model_version,
        revision=1,
        status=status,
        basis=basis,
        eligible=tuple(t.touchpoint_id for t in ordered),
        verified_net=verified_net,
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
        return previous
    causes = []
    if previous.verified_net != run.verified_net:
        causes.append(RevisionCause.REVENUE_CHANGED)
    if (previous.basis, previous.eligible) != (run.basis, run.eligible):
        causes.append(RevisionCause.TOUCHES_CHANGED)
    return replace(
        run,
        revision=previous.revision + 1,
        causes=tuple(causes),
        differences=_differences(previous, run),
    )


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
        facts = {record._facts() for record in records}
        touch = records[0]
        if len(facts) > 1:
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
            key[0],
            key[1],
            old.share if old else Fraction(0),
            new.share if new else Fraction(0),
            old.amount if old else None,
            new.amount if new else None,
        )
        if difference.delta_share or difference.delta_minor or (old is None) != (new is None):
            differences.append(difference)
    return tuple(differences)


_RunKey = tuple[UUID, UUID, str, str]


def _run_key(conversion: Conversion, version: ModelVersion) -> _RunKey:
    return conversion.agency_id, conversion.client_id, conversion.conversion_id, version.version_id


class AttributionHistory:
    """Every revision of every run, kept per conversion and model version; nothing is replaced."""

    def __init__(self) -> None:
        self._runs: dict[_RunKey, list[AttributionRun]] = {}

    def latest(self, conversion: Conversion, version: ModelVersion) -> AttributionRun | None:
        runs = self._runs.get(_run_key(conversion, version))
        return runs[-1] if runs else None

    def revisions(
        self, conversion: Conversion, version: ModelVersion
    ) -> tuple[AttributionRun, ...]:
        return tuple(self._runs.get(_run_key(conversion, version), ()))

    def record(self, run: AttributionRun) -> AttributionRun:
        """Append the next revision; recording the latest revision again changes nothing."""
        runs = self._runs.setdefault(_run_key(run.conversion, run.model_version), [])
        if runs and runs[-1] is run:
            return run
        if run.revision != len(runs) + 1 or (runs and runs[-1].conversion != run.conversion):
            raise AttributionInputError("revision_out_of_order")
        runs.append(run)
        return run

    def calculate(
        self,
        conversion: Conversion,
        touchpoints: Iterable[Touchpoint],
        model_version: ModelVersion,
        *,
        verified_net: Money | None = None,
        ledger_position: int | None = None,
    ) -> AttributionRun:
        run = attribute(
            conversion,
            touchpoints,
            model_version,
            verified_net=verified_net,
            ledger_position=ledger_position,
            previous=self.latest(conversion, model_version),
        )
        return self.record(run)


_LedgerKey = tuple[LedgerScope, str]
_JourneyKey = tuple[UUID, UUID, str]


class IncrementalAttribution:
    """Keeps attribution current from the 007-A movement journal and journey updates.

    Each call is one atomic step: new runs are calculated first, then handed to commit (the
    in-memory stand-in for a 007-B transactional write); only when commit returns are the
    history, transaction nets, journeys and the receipt checkpoint updated. A failed commit
    leaves everything as it was, so the same movements can be applied again.
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
        self._commit = commit
        self.checkpoint = 0
        self._nets: dict[_LedgerKey, Money] = {}
        self._conversions: dict[tuple[UUID, UUID, str], Conversion] = {}
        self._journeys: dict[_JourneyKey, tuple[Touchpoint, ...]] = {}

    def net(self, conversion: Conversion) -> Money | None:
        return self._nets.get(conversion.ledger_key)

    def runs(self, conversion: Conversion) -> dict[str, AttributionRun]:
        return {
            version.version_id: run
            for version in self.versions
            if (run := self.history.latest(conversion, version)) is not None
        }

    def register(self, conversion: Conversion) -> tuple[AttributionRun, ...]:
        if not isinstance(conversion, Conversion):
            raise AttributionInputError("invalid_conversion")
        key = (conversion.agency_id, conversion.client_id, conversion.conversion_id)
        known = self._conversions.get(key)
        if known is not None and known != conversion:
            raise AttributionInputError("conversion_conflict")
        runs = self._calculate([conversion], self._nets, self._journeys)
        self._finish(runs)
        self._conversions[key] = conversion
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
        journeys = {**self._journeys, journey: touches}
        affected = [c for c in self._conversions.values() if _journey_key(c) == journey]
        runs = self._calculate(affected, self._nets, journeys)
        self._finish(runs)
        self._journeys = journeys
        return runs

    def apply(self, movements: Iterable[Movement]) -> tuple[AttributionRun, ...]:
        """Apply the journal movements after the checkpoint, in sequence, as one step.

        Movements at or before the checkpoint were already applied and are skipped, so a retry
        of the same journal or an overlapping suffix changes nothing. The remaining movements
        must continue the checkpoint without a gap.
        """
        pending = []
        for movement in movements:
            if not isinstance(movement, Movement):
                raise AttributionInputError("invalid_movement")
            if movement.sequence > self.checkpoint:
                pending.append(movement)
        pending.sort(key=lambda m: m.sequence)
        for expected, movement in enumerate(pending, start=self.checkpoint + 1):
            if movement.sequence != expected:
                raise AttributionInputError("movement_gap")
        if not pending:
            return ()
        nets = dict(self._nets)
        changed: set[_LedgerKey] = set()
        for movement in pending:
            key = (movement.scope, movement.transaction_id)
            prior = nets.get(key)
            nets[key] = movement.amount if prior is None else prior + movement.amount
            changed.add(key)
        affected = [
            c
            for c in self._conversions.values()
            if c.kind is ConversionKind.SALE and c.ledger_key in changed
        ]
        position = pending[-1].sequence
        runs = self._calculate(affected, nets, self._journeys, position)
        self._finish(runs)
        self._nets = nets
        self.checkpoint = position
        return runs

    def _calculate(
        self,
        conversions: list[Conversion],
        nets: dict[_LedgerKey, Money],
        journeys: dict[_JourneyKey, tuple[Touchpoint, ...]],
        position: int | None = None,
    ) -> tuple[AttributionRun, ...]:
        runs = []
        for conversion in sorted(conversions, key=_conversion_order):
            sale = conversion.kind is ConversionKind.SALE
            for version in self.versions:
                previous = self.history.latest(conversion, version)
                run = attribute(
                    conversion,
                    journeys.get(_journey_key(conversion), ()),
                    version,
                    verified_net=nets.get(conversion.ledger_key) if sale else None,
                    ledger_position=(position or self.checkpoint) if sale else None,
                    previous=previous,
                )
                if run is not previous:
                    runs.append(run)
        return tuple(runs)

    def _finish(self, runs: tuple[AttributionRun, ...]) -> None:
        if self._commit is not None and runs:
            self._commit(runs)  # may raise: nothing below runs, and no state has changed yet
        for run in runs:
            self.history.record(run)


def _journey_key(conversion: Conversion) -> _JourneyKey:
    return conversion.agency_id, conversion.client_id, conversion.person_id


def _conversion_order(conversion: Conversion) -> tuple:
    return str(conversion.agency_id), str(conversion.client_id), conversion.conversion_id
