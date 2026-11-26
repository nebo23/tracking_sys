"""Persisted attribution consumer (specification 008-B, D-079 decisions D4, D5, D7 and D11).

One pass keeps a client's stored attribution current with its three inputs: the published
ledger journal, the identity change feed and the sale association registry. The calculation is
app.attribution.attribute(), unchanged; this module decides what to recalculate, stores what
changed and publishes it.

Conversions. Every verified sale of the published ledger and every trusted lead_signal
(trust rank 2) assigned to a person is one slot, and a conversion is one slot with one owner:
the owner's visible root, or none for an unassociated sale, which credits unknown so that
attributed revenue reconciles with ledger revenue. A changed owner, a scrubbed conversion or a
vanished candidate supersedes the conversion with a closing revision that reverses its credit,
and opens a successor; nothing but the publication and scrub columns of a conversion changes.

Units and chunks. Work is done in units with a target fixed at their start (ledger generation
and receipt ordinal, identity feed sequence, model-set digest) and a cursor over slot keys.
Each chunk is one REPEATABLE READ transaction of at most CHUNK_LIMIT slots: it reads the
consumer state and its inputs in one snapshot, calculates in memory, and then writes. Its first
write is the compare-and-swap on the consumer state, so a worker never holds an attribution row
lock while it waits for that row; a failed swap, a serialization failure or a lock timeout
rolls the whole chunk back. The last chunk publishes the unit. An incremental unit covers the
receipts and feed records up to its target plus the state-based changes (association revisions,
scrubbed conversions, consent expiry); a rebuild unit covers every slot in a staging generation
that stays invisible until it is published atomically, and it recalculates against the stored
history, so unchanged outcomes store nothing.

The worker takes no advisory lock (privacy, agency or revenue) and no row lock on an identity,
ledger or association row. Counts only are returned: never an ID or a value.
"""

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any
from uuid import UUID, uuid4

from psycopg.errors import LockNotAvailable, SerializationFailure
from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.attribution import AttributionInputError, ConversionKind, SaleState, Touchpoint, attribute
from app.identity.segments import owner_of
from app.ledger import Currency, LedgerScope
from app.models import (
    Agency,
    AttributionAllocation,
    AttributionConsumerState,
    AttributionConversion,
    AttributionCreditChange,
    AttributionModelVersion,
    AttributionRun,
    ClientWorkspace,
    CollectedEvent,
    IdentityChange,
    IdentityLink,
    IdentitySubject,
    LedgerReceipt,
    LedgerTransaction,
    RevenueIdentityBinding,
    StoredConsentRecord,
)
from app.privacy.consent import Purpose
from app.services import attribution_records as records
from app.services.attribution_inputs import touchpoints
from app.services.attribution_models import active_digest, ensure_defaults, versions
from app.services.identity import event_times, person_group, root_of, subject_segments
from app.services.identity_feed import begin_snapshot, read_batch, snapshot_watermark, verify
from app.services.ledger_store import LedgerUnavailable, published_state
from app.services.revenue_identity import _qualifying, association_id

PASS_LIMIT = 2_000  # slots per client and pass (D11)
CHUNK_LIMIT = 200  # slots per transaction (D11)
TOUCH_LIMIT = 5_000  # events read for one person's journey (D11)
FEED_UNIT_LIMIT = 500  # feed records one incremental unit consumes
RECEIPT_UNIT_LIMIT = 1_000  # ledger receipts one incremental unit consumes
SWEEP_LIMIT = 200  # open conversions one caught-up pass verifies again
OPEN_BINDING_STATES = ("active", "pending")
CONSENT_PURPOSES = (Purpose.ATTRIBUTION.value, Purpose.IDENTITY_LINK.value)

Hook = Callable[[str], None]


class _Conflict(Exception):
    """The compare-and-swap lost: another worker or a scrub changed the consumer state."""


@dataclass(frozen=True)
class Slot:
    """One verified sale or one trusted lead event of a client."""

    key: str
    kind: str
    source_account_id: str | None = None
    sale_operation_id: str | None = None
    event_id: UUID | None = None


@dataclass(frozen=True)
class Candidate:
    """What a slot currently is: its owner root (or none), anchor and sale state."""

    owner: UUID | None
    effective_at: datetime
    sale: SaleState | None = None
    association_id: UUID | None = None
    binding_id: UUID | None = None
    binding_subject: UUID | None = None


@dataclass(frozen=True)
class StoredRun:
    id: UUID
    values: records.RunValues
    ledger_generation: int | None
    receipt_ordinal: int | None


@dataclass(frozen=True)
class _Captured:
    """The consumer state as read in the chunk's snapshot."""

    client_id: UUID
    version: int
    generation: int
    status: str
    ledger_generation: int
    receipt_ordinal: int
    identity_seq: int
    model_set_digest: str | None
    unit_kind: str | None
    staging_generation: int | None
    target_ledger_generation: int | None
    target_receipt_ordinal: int | None
    target_identity_seq: int | None
    target_model_set_digest: str | None
    progress_key: str | None
    sweep_after_key: str | None


@dataclass
class _RunPlan:
    conversion_id: UUID
    kind: ConversionKind
    version_id: UUID
    values: records.RunValues
    changes: tuple[records.CreditValues, ...]
    exceeded: bool = False


@dataclass
class _SlotPlan:
    supersede: tuple[UUID, str] | None = None
    opened: dict[str, Any] | None = None
    runs: list[_RunPlan] = field(default_factory=list)
    update: tuple[UUID, dict[str, Any]] | None = None

    @property
    def writes(self) -> bool:
        return bool(self.supersede or self.opened or self.runs or self.update)


@dataclass
class Step:
    outcome: str | None = None  # set when the client's pass ends
    processed: int = 0
    counts: Counter = field(default_factory=Counter)

    @property
    def done(self) -> bool:
        return self.outcome is not None


def sale_slot(client_id: UUID, source_account_id: str, sale_operation_id: str) -> Slot:
    key = records.sale_slot_key(client_id, source_account_id, sale_operation_id)
    return Slot(key, "sale", source_account_id, sale_operation_id)


def lead_slot(client_id: UUID, event_id: UUID) -> Slot:
    return Slot(records.lead_slot_key(client_id, event_id), "lead", event_id=event_id)


def _row_slot(row: Any) -> Slot:
    return Slot(
        row.slot_key, row.kind, row.source_account_id, row.sale_operation_id, row.lead_event_id
    )


def stored_values(run: AttributionRun, allocations: Iterable[AttributionAllocation]):
    """The RunValues of a stored run and its allocation rows."""
    currency = Currency(run.currency, run.currency_exponent) if run.currency is not None else None
    return records.RunValues(
        revision=run.revision,
        status=run.status,
        basis=run.basis,
        causes=tuple(run.causes),
        currency=currency,
        verified_net_minor=run.verified_net_minor,
        window_start=run.window_start,
        window_end=run.window_end,
        excluded=tuple(zip(run.excluded_touchpoint_ids, run.excluded_reasons, strict=True)),
        allocations=tuple(
            records.AllocationValues(
                ordinal=row.ordinal,
                credited=row.credited,
                recipient=row.recipient,
                basis=row.basis,
                position=row.position,
                share=Fraction(row.share_numerator, row.share_denominator),
                amount_minor=row.amount_minor,
                touchpoint_id=row.touchpoint_id,
                evidence_class=row.evidence_class,
                occurred_at=row.occurred_at,
                source=row.source,
                campaign_ref=row.campaign_ref,
                content_ref=row.content_ref,
                link_ref=row.link_ref,
            )
            for row in sorted(allocations, key=lambda item: item.ordinal)
        ),
    )


class _Context:
    """One chunk's snapshot: its inputs, caches and the generation it writes."""

    def __init__(
        self, session: Session, agency_id: UUID, client_id: UUID, state: _Captured
    ) -> None:
        self.session, self.agency_id, self.client_id, self.state = (
            session,
            agency_id,
            client_id,
            state,
        )
        self.now: datetime = session.scalar(select(func.clock_timestamp()))
        ledger = published_state(session, agency_id, client_id)  # may raise LedgerUnavailable
        self.ledger_generation = ledger.generation if ledger is not None else 0
        self.ledger_ordinal = ledger.receipt_ordinal if ledger is not None else 0
        self.feed_last = snapshot_watermark(session.connection(), client_id)
        self.version_rows = [row for row in versions(session, client_id) if row.status == "active"]
        self.digest = active_digest(self.version_rows)
        self.engine_versions = {
            row.id: records.engine_version(
                row.version_key, row.model, row.window_seconds, row.rules
            )
            for row in self.version_rows
        }
        self._journeys: dict[UUID, tuple[list[Touchpoint], bool, frozenset[UUID]]] = {}
        self._qualifying: dict[UUID, set[UUID]] = {}

    # --- inputs --------------------------------------------------------------------------

    def subjects(self, group: list[UUID]) -> set[UUID]:
        return set(
            self.session.scalars(
                select(IdentityLink.collection_subject_id).where(
                    IdentityLink.client_id == self.client_id,
                    IdentityLink.status == "active",
                    IdentityLink.subject_id.in_(group),
                )
            )
        )

    def journey(self, root: UUID) -> tuple[list[Touchpoint], bool, frozenset[UUID]]:
        """The owner root's touches, whether the touch bound was exceeded, and its subjects."""
        if root not in self._journeys:
            group = person_group(self.session, self.client_id, root)
            subjects = self.subjects(group)
            events = 0
            if subjects:
                bounded = (
                    select(CollectedEvent.id)
                    .where(
                        CollectedEvent.client_id == self.client_id,
                        CollectedEvent.subject_id.in_(subjects),
                        CollectedEvent.identity_excluded_at.is_(None),
                    )
                    .limit(TOUCH_LIMIT + 1)
                    .subquery()
                )
                events = self.session.scalar(select(func.count()).select_from(bounded))
            exceeded = events > TOUCH_LIMIT
            touches = (
                []
                if exceeded
                else touchpoints(self.session, self.agency_id, self.client_id, root, self.now)
            )
            self._journeys[root] = (touches, exceeded, frozenset(subjects))
        return self._journeys[root]

    def qualifies(self, binding: RevenueIdentityBinding) -> bool:
        owner = binding.owner_subject_id
        if owner is None:
            return False
        if owner not in self._qualifying:
            rows = _qualifying(self.session, self.agency_id, self.client_id, [owner], self.now)
            self._qualifying[owner] = {row.id for row in rows}
        return binding.id in self._qualifying[owner]

    def open_binding(self, slot: Slot) -> RevenueIdentityBinding | None:
        return self.session.scalar(
            select(RevenueIdentityBinding)
            .where(
                RevenueIdentityBinding.client_id == self.client_id,
                RevenueIdentityBinding.association_id
                == association_id(self.client_id, slot.source_account_id, slot.sale_operation_id),
                RevenueIdentityBinding.closed_at.is_(None),
                RevenueIdentityBinding.state.in_(OPEN_BINDING_STATES),
            )
            .order_by(RevenueIdentityBinding.revision.desc())
            .limit(1)
        )

    def candidate(self, slot: Slot) -> Candidate | None:
        if slot.kind == "sale":
            return self._sale_candidate(slot)
        return self._lead_candidate(slot)

    def _sale_candidate(self, slot: Slot) -> Candidate | None:
        if self.ledger_generation == 0:
            return None
        transaction = self.session.scalar(
            select(LedgerTransaction).where(
                LedgerTransaction.client_id == self.client_id,
                LedgerTransaction.generation == self.ledger_generation,
                LedgerTransaction.source_account_id == slot.source_account_id,
                LedgerTransaction.operation_id == slot.sale_operation_id,
            )
        )
        if transaction is None:
            return None
        sale = SaleState(
            LedgerScope(self.agency_id, self.client_id, slot.source_account_id),
            slot.sale_operation_id,
            Currency(transaction.currency, transaction.currency_exponent),
            transaction.sale_effective_at,
            max(transaction.net, 0),
        )
        binding = self.open_binding(slot)
        if binding is None:
            return Candidate(None, transaction.sale_effective_at, sale)
        if not self.qualifies(binding):
            return Candidate(None, transaction.sale_effective_at, sale, binding_id=binding.id)
        return Candidate(
            root_of(self.session, binding.owner_subject_id),
            transaction.sale_effective_at,
            sale,
            association_id=binding.association_id,
            binding_id=binding.id,
            binding_subject=binding.collection_subject_id,
        )

    def _lead_candidate(self, slot: Slot) -> Candidate | None:
        if slot.event_id is None:
            return None
        event = self.session.scalar(
            select(CollectedEvent).where(
                CollectedEvent.client_id == self.client_id,
                CollectedEvent.event_id == slot.event_id,
            )
        )
        if (
            event is None
            or event.event_type != "lead_signal"
            or event.trust_rank != 2
            or event.identity_excluded_at is not None
        ):
            return None
        _, segments = subject_segments(self.session, event.subject_id, self.now)
        owner = owner_of(event_times(event), segments)
        if owner is None:
            return None
        return Candidate(root_of(self.session, owner), event.occurred_at)

    def recheck_at(self, subjects: Iterable[UUID]) -> datetime | None:
        """The earliest expiry of the current consent grants the result depends on."""
        ids = list(subjects)
        if not ids:
            return None
        rows = self.session.execute(
            select(StoredConsentRecord.state, StoredConsentRecord.expires_at)
            .where(
                StoredConsentRecord.subject_id.in_(ids),
                StoredConsentRecord.purpose.in_(CONSENT_PURPOSES),
            )
            .ext(distinct_on(StoredConsentRecord.subject_id, StoredConsentRecord.purpose))
            .order_by(
                StoredConsentRecord.subject_id,
                StoredConsentRecord.purpose,
                StoredConsentRecord.received_at.desc(),
                StoredConsentRecord.id.desc(),
            )
        )
        expiries = [
            expires_at
            for state, expires_at in rows
            if state == "granted" and expires_at is not None and expires_at > self.now
        ]
        return min(expiries) if expiries else None

    # --- slot enumeration ----------------------------------------------------------------

    def open_conversions(self, *conditions: Any, limit: int | None = None) -> list[Any]:
        query = (
            select(
                AttributionConversion.id,
                AttributionConversion.slot_key,
                AttributionConversion.kind,
                AttributionConversion.source_account_id,
                AttributionConversion.sale_operation_id,
                AttributionConversion.lead_event_id,
                AttributionConversion.binding_id,
            )
            .where(
                AttributionConversion.client_id == self.client_id,
                AttributionConversion.superseded_generation.is_(None),
                *conditions,
            )
            .order_by(AttributionConversion.slot_key)
        )
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.execute(query))

    def lead_events(self, subjects: Iterable[UUID] | None = None) -> list[UUID]:
        query = select(CollectedEvent.event_id).where(
            CollectedEvent.client_id == self.client_id,
            CollectedEvent.event_type == "lead_signal",
            CollectedEvent.trust_rank == 2,
            CollectedEvent.identity_excluded_at.is_(None),
        )
        if subjects is not None:
            ids = list(subjects)
            if not ids:
                return []
            query = query.where(CollectedEvent.subject_id.in_(ids))
        return list(self.session.scalars(query))

    def state_slots(self) -> dict[str, Slot]:
        """Slots whose stored conversion no longer matches a state the feed does not report."""
        slots: dict[str, Slot] = {}
        for row in self.open_conversions(
            (AttributionConversion.scrubbed_at.is_not(None))
            | (AttributionConversion.recheck_at <= self.now)
        ):
            slots[row.slot_key] = _row_slot(row)
        bindings = dict(
            self.session.execute(
                select(RevenueIdentityBinding.association_id, RevenueIdentityBinding.id)
                .where(
                    RevenueIdentityBinding.client_id == self.client_id,
                    RevenueIdentityBinding.closed_at.is_(None),
                    RevenueIdentityBinding.state.in_(OPEN_BINDING_STATES),
                )
                # The highest open revision wins, as in open_binding().
                .order_by(RevenueIdentityBinding.revision)
            ).all()
        )
        for row in self.open_conversions(AttributionConversion.kind == "sale"):
            expected = bindings.get(
                association_id(self.client_id, row.source_account_id, row.sale_operation_id)
            )
            if expected != row.binding_id:
                slots[row.slot_key] = _row_slot(row)
        return slots

    def person_slots(self, person_id: UUID) -> dict[str, Slot]:
        slots: dict[str, Slot] = {}
        owners = {person_id}
        exists = self.session.scalar(
            select(IdentitySubject.id).where(
                IdentitySubject.client_id == self.client_id, IdentitySubject.id == person_id
            )
        )
        if exists is not None:
            root = root_of(self.session, person_id)
            owners.add(root)
            group = person_group(self.session, self.client_id, root)
            for account, operation in self.session.execute(
                select(
                    RevenueIdentityBinding.source_account_id,
                    RevenueIdentityBinding.sale_operation_id,
                ).where(
                    RevenueIdentityBinding.client_id == self.client_id,
                    RevenueIdentityBinding.closed_at.is_(None),
                    RevenueIdentityBinding.state.in_(OPEN_BINDING_STATES),
                    RevenueIdentityBinding.owner_subject_id.in_(group),
                )
            ):
                slot = sale_slot(self.client_id, account, operation)
                slots[slot.key] = slot
            for event_id in self.lead_events(self.subjects(group)):
                slot = lead_slot(self.client_id, event_id)
                slots[slot.key] = slot
        for row in self.open_conversions(AttributionConversion.owner_person_id.in_(owners)):
            slots[row.slot_key] = _row_slot(row)
        return slots

    def incremental_slots(self) -> dict[str, Slot]:
        state = self.state
        slots: dict[str, Slot] = {}
        base = (
            state.receipt_ordinal
            if state.ledger_generation == state.target_ledger_generation
            else 0
        )
        if state.target_ledger_generation and state.target_receipt_ordinal > base:
            for closing in self.session.scalars(
                select(LedgerReceipt.closing_states).where(
                    LedgerReceipt.client_id == self.client_id,
                    LedgerReceipt.generation == state.target_ledger_generation,
                    LedgerReceipt.receipt_ordinal > base,
                    LedgerReceipt.receipt_ordinal <= state.target_receipt_ordinal,
                )
            ):
                for item in closing or []:
                    slot = sale_slot(
                        self.client_id, item["source_account_id"], item["transaction_id"]
                    )
                    slots[slot.key] = slot
        if state.target_identity_seq > state.identity_seq:
            people = set(
                self.session.scalars(
                    select(IdentityChange.person_id).where(
                        IdentityChange.client_id == self.client_id,
                        IdentityChange.seq > state.identity_seq,
                        IdentityChange.seq <= state.target_identity_seq,
                    )
                )
            )
            for person_id in sorted(people, key=str):
                slots.update(self.person_slots(person_id))
        slots.update(self.state_slots())
        return slots

    def all_slots(self) -> dict[str, Slot]:
        slots: dict[str, Slot] = {}
        if self.ledger_generation:
            for account, operation in self.session.execute(
                select(LedgerTransaction.source_account_id, LedgerTransaction.operation_id).where(
                    LedgerTransaction.client_id == self.client_id,
                    LedgerTransaction.generation == self.ledger_generation,
                )
            ):
                slot = sale_slot(self.client_id, account, operation)
                slots[slot.key] = slot
        for event_id in self.lead_events():
            slot = lead_slot(self.client_id, event_id)
            slots[slot.key] = slot
        for row in self.open_conversions():
            slots.setdefault(row.slot_key, _row_slot(row))
        return slots

    # --- stored state --------------------------------------------------------------------

    def stored(self, keys: list[str]) -> tuple[dict, dict, dict]:
        """The open conversion, latest runs and conversion count of each slot key."""
        if not keys:
            return {}, {}, {}
        conversions = {
            row.slot_key: row
            for row in self.session.scalars(
                select(AttributionConversion)
                .where(
                    AttributionConversion.client_id == self.client_id,
                    AttributionConversion.slot_key.in_(keys),
                    AttributionConversion.superseded_generation.is_(None),
                )
                .execution_options(populate_existing=True)
            )
        }
        counts = dict(
            self.session.execute(
                select(AttributionConversion.slot_key, func.count())
                .where(
                    AttributionConversion.client_id == self.client_id,
                    AttributionConversion.slot_key.in_(keys),
                )
                .group_by(AttributionConversion.slot_key)
            ).all()
        )
        latest = latest_runs(self.session, [row.id for row in conversions.values()])
        return conversions, latest, counts


def latest_runs(
    session: Session, conversion_ids: list[UUID], *, through: int | None = None
) -> dict[UUID, dict[UUID, StoredRun]]:
    """The latest stored revision of each conversion under each model version."""
    if not conversion_ids:
        return {}
    query = (
        select(AttributionRun)
        .where(AttributionRun.conversion_id.in_(conversion_ids))
        .ext(distinct_on(AttributionRun.conversion_id, AttributionRun.model_version_id))
        .order_by(
            AttributionRun.conversion_id,
            AttributionRun.model_version_id,
            AttributionRun.revision.desc(),
        )
        .execution_options(populate_existing=True)
    )
    if through is not None:
        query = query.where(AttributionRun.generation <= through)
    runs = list(session.scalars(query))
    allocations: dict[UUID, list[AttributionAllocation]] = {}
    if runs:
        for row in session.scalars(
            select(AttributionAllocation)
            .where(AttributionAllocation.run_id.in_([run.id for run in runs]))
            .execution_options(populate_existing=True)
        ):
            allocations.setdefault(row.run_id, []).append(row)
    found: dict[UUID, dict[UUID, StoredRun]] = {}
    for run in runs:
        found.setdefault(run.conversion_id, {})[run.model_version_id] = StoredRun(
            run.id,
            stored_values(run, allocations.get(run.id, [])),
            run.ledger_generation,
            run.receipt_ordinal,
        )
    return found


# ---------------------------------------------------------------------------------------------
# Planning: everything a chunk will write, calculated in memory.


def _closing(stored: StoredRun) -> records.RunValues:
    return records.RunValues(
        revision=stored.values.revision + 1,
        status=records.SUPERSEDED,
        basis=None,
        causes=(records.SUPERSEDED,),
        currency=stored.values.currency,
        verified_net_minor=None,
        window_start=None,
        window_end=None,
        excluded=(),
        allocations=(),
    )


def _supersession(current: AttributionConversion, candidate: Candidate | None, latest: dict):
    if current.scrubbed_at is not None:
        return "scrubbed"  # its pointers are gone: it can never be recalculated
    if candidate is None:
        return "sale_removed" if current.kind == "sale" else "lead_removed"
    if current.owner_person_id != candidate.owner:
        return "owner_changed"
    if current.kind == "lead" and current.effective_at != candidate.effective_at:
        return "lead_changed"
    if current.kind == "sale" and any(
        stored.values.currency is not None and stored.values.currency != candidate.sale.currency
        for stored in latest.values()
    ):
        return "sale_changed"
    return None


def plan_slot(
    ctx: _Context,
    slot: Slot,
    current: AttributionConversion | None,
    latest: dict[UUID, StoredRun],
    opened_before: int,
    generation: int,
) -> _SlotPlan:
    plan = _SlotPlan()
    candidate = ctx.candidate(slot)
    kind = ConversionKind(slot.kind)
    if current is not None:
        reason = _supersession(current, candidate, latest)
        if reason is not None:
            plan.supersede = (current.id, reason)
            for version in ctx.version_rows:
                stored = latest.get(version.id)
                if stored is None or stored.values.status == records.SUPERSEDED:
                    continue
                plan.runs.append(
                    _RunPlan(
                        current.id,
                        kind,
                        version.id,
                        _closing(stored),
                        records.closing_changes(kind, stored.values),
                    )
                )
            current, latest = None, {}
    if candidate is None:
        return plan
    touches: list[Touchpoint] = []
    exceeded = False
    subjects: set[UUID] = set()
    if candidate.owner is not None:
        touches, exceeded, journey_subjects = ctx.journey(candidate.owner)
        subjects |= journey_subjects
    if candidate.binding_subject is not None:
        subjects.add(candidate.binding_subject)
    recheck = ctx.recheck_at(subjects)
    if current is None:
        conversion_id = uuid4()
        plan.opened = {
            "id": conversion_id,
            "agency_id": ctx.agency_id,
            "client_id": ctx.client_id,
            "generation": generation,
            "slot_key": slot.key,
            "conversion_key": records.conversion_key(slot.key, opened_before + 1),
            "kind": slot.kind,
            "owner_person_id": candidate.owner,
            "association_id": candidate.association_id,
            "binding_id": candidate.binding_id,
            "source_account_id": slot.source_account_id,
            "sale_operation_id": slot.sale_operation_id,
            "lead_event_id": slot.event_id,
            "effective_at": candidate.effective_at,
            "status": "active",
            "recheck_at": recheck,
        }
        anchor = candidate.effective_at
    else:
        conversion_id, anchor = current.id, current.effective_at
        changes = {}
        if current.recheck_at != recheck:
            changes["recheck_at"] = recheck
        if current.binding_id != candidate.binding_id:
            changes["binding_id"] = candidate.binding_id
        if changes:
            plan.update = (current.id, changes)
    conversion = records.engine_conversion(
        conversion_id,
        ctx.agency_id,
        ctx.client_id,
        slot.kind,
        candidate.owner,
        anchor,
        slot.source_account_id,
        slot.sale_operation_id,
    )
    position = ctx.ledger_ordinal if candidate.sale is not None else None
    for version in ctx.version_rows:
        engine_version = ctx.engine_versions[version.id]
        stored = latest.get(version.id)
        previous = None
        if stored is not None:
            known = (
                stored.receipt_ordinal
                if stored.ledger_generation == ctx.ledger_generation
                else None
            )
            previous = records.reconstruct(
                conversion, engine_version, stored.values, ledger_position=known
            )
        run = attribute(
            conversion,
            touches,
            engine_version,
            sale=candidate.sale,
            ledger_position=position,
            previous=previous,
        )
        if previous is not None and run.revision == previous.revision:
            continue
        values = records.run_values(run)
        plan.runs.append(
            _RunPlan(
                conversion_id,
                kind,
                version.id,
                values,
                records.credit_changes(kind, stored.values if stored else None, values, run),
                exceeded,
            )
        )
    return plan


def plan_chunk(ctx: _Context, chunk: list[Slot], generation: int) -> list[_SlotPlan]:
    conversions, latest, counts = ctx.stored([slot.key for slot in chunk])
    plans = []
    for slot in chunk:
        current = conversions.get(slot.key)
        runs = latest.get(current.id, {}) if current is not None else {}
        plans.append(plan_slot(ctx, slot, current, runs, counts.get(slot.key, 0), generation))
    return plans


# ---------------------------------------------------------------------------------------------
# Writing: the compare-and-swap first, then the planned rows.


def _capture(row: AttributionConsumerState) -> _Captured:
    return _Captured(
        **{name: getattr(row, name) for name in _Captured.__dataclass_fields__}  # type: ignore[attr-defined]
    )


def _swap(session: Session, state: _Captured, **values: Any) -> None:
    """Compare-and-swap on the consumer state; the first write of every chunk."""
    result = session.execute(
        update(AttributionConsumerState)
        .where(
            AttributionConsumerState.client_id == state.client_id,
            AttributionConsumerState.version == state.version,
            AttributionConsumerState.generation == state.generation,
            AttributionConsumerState.ledger_generation == state.ledger_generation,
            AttributionConsumerState.receipt_ordinal == state.receipt_ordinal,
            AttributionConsumerState.identity_seq == state.identity_seq,
        )
        .values(version=state.version + 1, updated_at=func.clock_timestamp(), **values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise _Conflict()


UNIT_CLEARED = {
    "unit_kind": None,
    "staging_generation": None,
    "target_ledger_generation": None,
    "target_receipt_ordinal": None,
    "target_identity_seq": None,
    "target_model_set_digest": None,
    "unit_started_at": None,
    "progress_key": None,
}


def _write(ctx: _Context, plans: list[_SlotPlan], generation: int, *, staged: bool) -> Counter:
    session, counts = ctx.session, Counter()
    for plan in plans:
        if plan.supersede is None:
            continue
        conversion_id, reason = plan.supersede
        values: dict[str, Any] = {
            "superseded_generation": generation,
            "superseded_at": ctx.now,
            "superseded_reason": reason,
        }
        if not staged:
            values["status"] = "superseded"
        result = session.execute(
            update(AttributionConversion)
            .where(
                AttributionConversion.id == conversion_id,
                AttributionConversion.superseded_generation.is_(None),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise _Conflict()
        counts["superseded"] += 1
    opened = [AttributionConversion(**plan.opened) for plan in plans if plan.opened is not None]
    if opened:
        session.add_all(opened)
        session.flush()
        counts["opened"] += len(opened)
    runs, children = [], []
    for plan in plans:
        for item in plan.runs:
            values = item.values
            run_id = uuid4()
            sale = item.kind is ConversionKind.SALE and ctx.ledger_generation > 0
            runs.append(
                AttributionRun(
                    id=run_id,
                    agency_id=ctx.agency_id,
                    client_id=ctx.client_id,
                    generation=generation,
                    conversion_id=item.conversion_id,
                    model_version_id=item.version_id,
                    revision=values.revision,
                    status=values.status,
                    basis=values.basis,
                    causes=list(values.causes),
                    currency=values.currency.code if values.currency else None,
                    currency_exponent=values.currency.exponent if values.currency else None,
                    verified_net_minor=values.verified_net_minor,
                    window_start=values.window_start,
                    window_end=values.window_end,
                    ledger_generation=ctx.ledger_generation if sale else None,
                    receipt_ordinal=ctx.ledger_ordinal if sale else None,
                    identity_seq=ctx.feed_last,
                    excluded_touchpoint_ids=[touch for touch, _ in values.excluded],
                    excluded_reasons=[reason for _, reason in values.excluded],
                    touch_bound_exceeded=item.exceeded,
                    recorded_at=ctx.now,
                )
            )
            for row in values.allocations:
                children.append(
                    AttributionAllocation(
                        id=uuid4(),
                        agency_id=ctx.agency_id,
                        client_id=ctx.client_id,
                        run_id=run_id,
                        ordinal=row.ordinal,
                        credited=row.credited,
                        recipient=row.recipient,
                        basis=row.basis,
                        position=row.position,
                        share_numerator=row.share.numerator,
                        share_denominator=row.share.denominator,
                        amount_minor=row.amount_minor,
                        touchpoint_id=row.touchpoint_id,
                        evidence_class=row.evidence_class,
                        occurred_at=row.occurred_at,
                        source=row.source,
                        campaign_ref=row.campaign_ref,
                        content_ref=row.content_ref,
                        link_ref=row.link_ref,
                    )
                )
            for change in item.changes:
                children.append(
                    AttributionCreditChange(
                        id=uuid4(),
                        agency_id=ctx.agency_id,
                        client_id=ctx.client_id,
                        run_id=run_id,
                        model_version_id=item.version_id,
                        generation=generation,
                        ordinal=change.ordinal,
                        conversion_kind=item.kind.value,
                        effective_at=change.effective_at,
                        recipient=change.recipient,
                        touchpoint_id=change.touchpoint_id,
                        source=change.source,
                        campaign_ref=change.campaign_ref,
                        content_ref=change.content_ref,
                        link_ref=change.link_ref,
                        delta_share_numerator=change.delta_share.numerator,
                        delta_share_denominator=change.delta_share.denominator,
                        delta_minor=change.delta_minor,
                        currency=change.currency.code if change.currency else None,
                        currency_exponent=change.currency.exponent if change.currency else None,
                        recorded_at=ctx.now,
                    )
                )
    if runs:
        session.add_all(runs)
        session.flush()
        counts["revisions"] += len(runs)
    if children:
        session.add_all(children)
        session.flush()
    for plan in plans:
        if plan.update is not None:
            conversion_id, changes = plan.update
            session.execute(
                update(AttributionConversion)
                .where(AttributionConversion.id == conversion_id)
                .values(**changes)
                .execution_options(synchronize_session=False)
            )
    return counts


# ---------------------------------------------------------------------------------------------
# Units of work.


def _decide(ctx: _Context) -> dict[str, Any] | None:
    """The unit to start, or None when the client is caught up."""
    state = ctx.state
    target = {
        "target_ledger_generation": ctx.ledger_generation,
        "target_receipt_ordinal": ctx.ledger_ordinal,
        "target_identity_seq": ctx.feed_last,
        "target_model_set_digest": ctx.digest,
        "unit_started_at": ctx.now,
        "progress_key": None,
    }
    rebuild = {
        **target,
        "unit_kind": "rebuild",
        "staging_generation": state.generation + 1,
        "status": "building",
    }
    if state.generation == 0 or state.model_set_digest != ctx.digest:
        return rebuild
    if state.ledger_generation not in (0, ctx.ledger_generation):
        return rebuild
    batch = read_batch(ctx.session.connection(), ctx.client_id, state.identity_seq, FEED_UNIT_LIMIT)
    verdict = verify(batch, state.identity_seq)
    if verdict == "rebuild":
        return rebuild
    seq = batch.records[-1].seq if verdict == "apply" else state.identity_seq
    base = state.receipt_ordinal if state.ledger_generation == ctx.ledger_generation else 0
    ordinal = min(ctx.ledger_ordinal, base + RECEIPT_UNIT_LIMIT)
    moved = (
        seq > state.identity_seq
        or ordinal > base
        or state.ledger_generation != ctx.ledger_generation
    )
    if not moved and not ctx.state_slots():
        return None
    return {
        **target,
        "target_receipt_ordinal": ordinal,
        "target_identity_seq": seq,
        "unit_kind": "incremental",
        "staging_generation": None,
    }


def _advance(ctx: _Context, budget: int, hook: Hook | None) -> Step:
    state = ctx.state
    rebuild = state.unit_kind == "rebuild"
    obsolete = (
        ctx.ledger_generation != state.target_ledger_generation
        or ctx.digest != state.target_model_set_digest
    )
    if obsolete and not rebuild:
        # The model set or the ledger generation changed: this unit ends; a rebuild follows.
        _swap(ctx.session, state, **UNIT_CLEARED)
        return Step()
    if obsolete:
        # Restart in place: the same staging generation, a new target and cursor.
        _swap(
            ctx.session,
            state,
            target_ledger_generation=ctx.ledger_generation,
            target_receipt_ordinal=ctx.ledger_ordinal,
            target_identity_seq=ctx.feed_last,
            target_model_set_digest=ctx.digest,
            unit_started_at=ctx.now,
            progress_key=None,
        )
        return Step()
    slots = ctx.all_slots() if rebuild else ctx.incremental_slots()
    pending = sorted(
        (
            slot
            for slot in slots.values()
            if state.progress_key is None or slot.key > state.progress_key
        ),
        key=lambda slot: slot.key,
    )
    chunk = pending[: min(CHUNK_LIMIT, budget)]
    last = len(chunk) == len(pending)
    generation = state.staging_generation if rebuild else state.generation
    plans = plan_chunk(ctx, chunk, generation)
    if hook is not None:
        hook("computed")
    counts: Counter = Counter()
    if not last:
        _swap(ctx.session, state, progress_key=chunk[-1].key)
    elif rebuild:
        _swap(
            ctx.session,
            state,
            generation=state.staging_generation,
            status="ready",
            ledger_generation=state.target_ledger_generation,
            receipt_ordinal=state.target_receipt_ordinal,
            identity_seq=state.target_identity_seq,
            model_set_digest=state.target_model_set_digest,
            published_at=ctx.now,
            **UNIT_CLEARED,
        )
        counts["rebuilds"] += 1
    else:
        _swap(
            ctx.session,
            state,
            ledger_generation=state.target_ledger_generation,
            receipt_ordinal=state.target_receipt_ordinal,
            identity_seq=state.target_identity_seq,
            published_at=ctx.now,
            **UNIT_CLEARED,
        )
    counts += _write(ctx, plans, generation, staged=rebuild)
    if last and rebuild:
        # The staged supersessions become the published status with the generation switch.
        ctx.session.execute(
            update(AttributionConversion)
            .where(
                AttributionConversion.client_id == ctx.client_id,
                AttributionConversion.superseded_generation == state.staging_generation,
                AttributionConversion.status == "active",
            )
            .values(status="superseded")
            .execution_options(synchronize_session=False)
        )
    counts["slots"] += len(chunk)
    return Step(processed=len(chunk), counts=counts)


def _sweep(ctx: _Context, budget: int, hook: Hook | None) -> Step:
    """Verify a bounded slice of open conversions again; store only what changed."""
    state = ctx.state
    limit = min(SWEEP_LIMIT, budget)
    if limit <= 0:
        return Step("caught_up")
    rows = []
    if state.sweep_after_key is not None:
        rows = ctx.open_conversions(
            AttributionConversion.slot_key > state.sweep_after_key, limit=limit
        )
    if not rows:
        rows = ctx.open_conversions(limit=limit)  # from the start, or wrapped around
    if not rows:
        return Step("caught_up")
    chunk = [_row_slot(row) for row in rows]
    plans = plan_chunk(ctx, chunk, state.generation)
    if hook is not None:
        hook("computed")
    counts: Counter = Counter()
    _swap(ctx.session, state, sweep_after_key=chunk[-1].key)
    counts += _write(ctx, plans, state.generation, staged=False)
    counts["swept"] += len(chunk)
    return Step("caught_up", processed=len(chunk), counts=counts)


def _step(engine: Engine, agency_id: UUID, client_id: UUID, budget: int, hook: Hook | None) -> Step:
    """One chunk transaction for one client."""
    captured: _Captured | None = None
    try:
        with Session(engine) as session, session.begin():
            begin_snapshot(session.connection())
            row = session.get(AttributionConsumerState, client_id)
            captured = _capture(row)
            if captured.status == "failed":
                return Step("failed")
            try:
                ctx = _Context(session, agency_id, client_id, captured)
            except LedgerUnavailable:
                return Step("ledger_unavailable")
            if captured.unit_kind is not None:
                return _advance(ctx, budget, hook)
            unit = _decide(ctx)
            if unit is None:
                return _sweep(ctx, budget, hook)
            _swap(session, captured, **unit)
            return Step()
    except _Conflict:
        return Step("conflict")
    except OperationalError as error:
        if isinstance(error.orig, SerializationFailure | LockNotAvailable):
            return Step("conflict")
        raise
    except AttributionInputError as error:
        if error.code == "stale_ledger_position":
            return Step("conflict")
        _fail(engine, captured, error.code)
        return Step("failed")


def _fail(engine: Engine, state: _Captured | None, code: str) -> None:
    """Record an engine refusal as the explicit failed state (retried after the lifecycle)."""
    if state is None:
        return
    with Session(engine) as session, session.begin():
        session.execute(
            update(AttributionConsumerState)
            .where(
                AttributionConsumerState.client_id == state.client_id,
                AttributionConsumerState.version == state.version,
            )
            .values(
                version=state.version + 1,
                status="failed",
                failure_code=code[:40],
                updated_at=func.clock_timestamp(),
            )
        )


# ---------------------------------------------------------------------------------------------
# Passes.


def prepare(engine: Engine, agency_id: UUID, client_id: UUID) -> None:
    """Make sure the consumer state row and the default model versions exist."""
    with Session(engine) as session, session.begin():
        ensure_state(session, agency_id, client_id)
        ensure_defaults(session, agency_id, client_id)


def ensure_state(session: Session, agency_id: UUID, client_id: UUID) -> None:
    session.execute(
        insert(AttributionConsumerState)
        .values(client_id=client_id, agency_id=agency_id)
        .on_conflict_do_nothing(index_elements=["client_id"])
    )


def process_client(
    engine: Engine,
    agency_id: UUID,
    client_id: UUID,
    *,
    budget: int = PASS_LIMIT,
    hook: Hook | None = None,
) -> dict[str, Any]:
    """One bounded pass for one client. Returns its outcome and counts."""
    prepare(engine, agency_id, client_id)
    counts: Counter = Counter()
    processed = 0
    while True:
        step = _step(engine, agency_id, client_id, budget - processed, hook)
        processed += step.processed
        counts += step.counts
        if step.done:
            return {"outcome": step.outcome, **counts}
        if processed >= budget:
            return {"outcome": "bounded", **counts}


def run_pass(engine: Engine, *, budget: int = PASS_LIMIT) -> dict[str, int]:
    """One bounded pass over every active client; counts only."""
    with Session(engine) as session:
        clients = list(
            session.execute(
                select(ClientWorkspace.agency_id, ClientWorkspace.id)
                .join(Agency, Agency.id == ClientWorkspace.agency_id)
                .where(Agency.status == "active", ClientWorkspace.status == "active")
                .order_by(ClientWorkspace.id)
            )
        )
    totals: Counter = Counter({"clients": len(clients)})
    for agency_id, client_id in clients:
        result = process_client(engine, agency_id, client_id, budget=budget)
        totals[result.pop("outcome")] += 1
        totals.update(result)
    return dict(totals)


def model_versions(session: Session, client_id: UUID) -> list[AttributionModelVersion]:
    return versions(session, client_id)


def pending_changes(engine: Engine, agency_id: UUID, client_id: UUID) -> int:
    """How many slots a full recalculation would change now; nothing is written.

    Zero means the stored state equals what a rebuild from the current inputs would publish.
    """
    changed = 0
    with Session(engine) as session, session.begin():
        begin_snapshot(session.connection())
        row = session.get(AttributionConsumerState, client_id)
        if row is None:
            return 0
        ctx = _Context(session, agency_id, client_id, _capture(row))
        slots = sorted(ctx.all_slots().values(), key=lambda slot: slot.key)
        for start in range(0, len(slots), CHUNK_LIMIT):
            plans = plan_chunk(ctx, slots[start : start + CHUNK_LIMIT], max(row.generation, 1))
            changed += sum(1 for plan in plans if plan.writes)
    return changed
