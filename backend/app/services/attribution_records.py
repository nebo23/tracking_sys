"""Pure mapping between the 008-A engine and the persisted 008-B rows (D-079 D6).

Nothing here reads or writes the database. It derives the slot and conversion keys, the
model-set digest, the engine contracts of a stored model version and conversion, the row values
of one engine run, the exact reconstruction of the latest stored run (so that attribute() with
that run as previous returns it unchanged for identical inputs), and the credit changes each
revision books in the reporting ledger:

- an initial revision books its credited allocations;
- a later revision with an unchanged anchor books the engine's signed differences;
- a later revision whose anchor moved reverses the previous credited allocations at the old
  anchor and books the new ones at the new anchor, so the ledger stays exact per reporting date;
- a closing revision of a superseded conversion reverses its latest credited allocations.

The calculation itself is attribute(); this module never allocates credit.
"""

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from uuid import UUID

from app.attribution import (
    Association,
    AttributionModel,
    AttributionRun,
    Conversion,
    ConversionKind,
    CreditAllocation,
    CreditBasis,
    EvidenceClass,
    ExcludedTouch,
    ExclusionReason,
    ModelVersion,
    Recipient,
    RevisionCause,
    RunStatus,
    SaleState,
    Touchpoint,
)
from app.ledger import Currency, LedgerScope, Money
from app.privacy.consent import ConsentState

UNASSOCIATED = "unassociated"  # the engine person of a sale without a qualifying owner
SUPERSEDED = "superseded"  # the persisted status and cause of a closing revision
DAY = 86_400
MIN_WINDOW_DAYS, MAX_WINDOW_DAYS = 1, 90


def _digest(parts: Sequence[object]) -> str:
    return hashlib.sha256(json.dumps(list(parts), separators=(",", ":")).encode()).hexdigest()


def sale_slot_key(client_id: UUID, source_account_id: str, sale_operation_id: str) -> str:
    return _digest(
        ["attribution-slot:v1", str(client_id), "sale", source_account_id, sale_operation_id]
    )


def lead_slot_key(client_id: UUID, event_id: UUID) -> str:
    return _digest(["attribution-slot:v1", str(client_id), "lead", str(event_id)])


def scrubbed_slot_key(conversion_id: UUID) -> str:
    return _digest(["attribution-scrubbed:v1", str(conversion_id)])


def conversion_key(slot_key: str, ordinal: int) -> str:
    return f"{slot_key}.{ordinal}"


def scrubbed_conversion_key(conversion_id: UUID) -> str:
    return f"scrubbed.{conversion_id}"


def version_key(model: str, window_days: int, ordinal: int) -> str:
    return f"{model}_{window_days}d_v{ordinal}"


def valid_window_days(value: object) -> bool:
    return type(value) is int and MIN_WINDOW_DAYS <= value <= MAX_WINDOW_DAYS


def model_set_digest(versions: Iterable[tuple[str, str, int, str]]) -> str:
    """The digest of an active version set: (version_key, model, window_seconds, rules)."""
    return _digest(["attribution-model-set:v1", *sorted(list(item) for item in versions)])


def engine_version(version_key_: str, model: str, window_seconds: int, rules: str) -> ModelVersion:
    return ModelVersion(
        version_key_, AttributionModel(model), timedelta(seconds=window_seconds), rules
    )


def engine_conversion(
    conversion_id: UUID,
    agency_id: UUID,
    client_id: UUID,
    kind: str,
    owner: UUID | None,
    effective_at: datetime,
    source_account_id: str | None,
    sale_operation_id: str | None,
) -> Conversion:
    return Conversion(
        str(conversion_id),
        agency_id,
        client_id,
        str(owner) if owner is not None else UNASSOCIATED,
        ConversionKind(kind),
        effective_at,
        source_account_id,
        sale_operation_id,
    )


# ---------------------------------------------------------------------------------------------
# Row values of one run.


@dataclass(frozen=True)
class AllocationValues:
    ordinal: int
    credited: bool
    recipient: str
    basis: str
    position: int
    share: Fraction
    amount_minor: int | None
    touchpoint_id: UUID | None
    evidence_class: str | None
    occurred_at: datetime | None
    source: str | None
    campaign_ref: str | None
    content_ref: str | None
    link_ref: UUID | None


@dataclass(frozen=True)
class CreditValues:
    ordinal: int
    effective_at: datetime
    recipient: str
    touchpoint_id: UUID | None
    source: str | None
    campaign_ref: str | None
    content_ref: str | None
    link_ref: UUID | None
    delta_share: Fraction
    delta_minor: int | None
    currency: Currency | None


@dataclass(frozen=True)
class RunValues:
    revision: int
    status: str
    basis: str | None
    causes: tuple[str, ...]
    currency: Currency | None
    verified_net_minor: int | None
    window_start: datetime | None
    window_end: datetime | None
    excluded: tuple[tuple[UUID | None, str], ...]
    allocations: tuple[AllocationValues, ...]


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value is not None else None


def run_values(run: AttributionRun) -> RunValues:
    """The persisted values of one engine run (status, allocations rows and exclusions)."""
    credited = {
        allocation.touch.touchpoint_id: allocation
        for allocation in run.allocations
        if allocation.touch is not None
    }
    rows: list[AllocationValues] = []
    if run.eligible:
        for position, touch in enumerate(run.eligible, start=1):
            allocation = credited.get(touch.touchpoint_id)
            if allocation is not None and allocation.position != position:
                raise ValueError("allocation_position_mismatch")
            rows.append(
                AllocationValues(
                    ordinal=position,
                    credited=allocation is not None,
                    recipient=(
                        Recipient.CAMPAIGN
                        if run.basis is CreditBasis.CAMPAIGN
                        else Recipient.DIRECT
                    ).value,
                    basis=run.basis.value,
                    position=position,
                    share=allocation.share if allocation is not None else Fraction(0),
                    amount_minor=(
                        allocation.amount.minor
                        if allocation is not None and allocation.amount is not None
                        else None
                    ),
                    touchpoint_id=UUID(touch.touchpoint_id),
                    evidence_class=touch.evidence_class.value,
                    occurred_at=touch.occurred_at,
                    source=touch.source,
                    campaign_ref=touch.campaign_ref,
                    content_ref=touch.content_ref,
                    link_ref=_uuid(touch.link_ref),
                )
            )
        if len(credited) != len(run.allocations):
            raise ValueError("allocation_without_touch")
    for allocation in run.allocations:
        if allocation.touch is None:
            rows.append(
                AllocationValues(
                    ordinal=len(rows) + 1,
                    credited=True,
                    recipient=allocation.recipient.value,
                    basis=allocation.basis.value,
                    position=0,
                    share=allocation.share,
                    amount_minor=allocation.amount.minor if allocation.amount else None,
                    touchpoint_id=None,
                    evidence_class=None,
                    occurred_at=None,
                    source=None,
                    campaign_ref=None,
                    content_ref=None,
                    link_ref=None,
                )
            )
    sale = run.sale
    return RunValues(
        revision=run.revision,
        status=run.status.value,
        basis=run.basis.value,
        causes=tuple(cause.value for cause in run.causes),
        currency=sale.currency if sale is not None else None,
        verified_net_minor=sale.net_minor if sale is not None else None,
        window_start=run.window_start,
        window_end=run.window_end,
        excluded=tuple((UUID(item.touchpoint_id), item.reason.value) for item in run.excluded),
        allocations=tuple(rows),
    )


def reconstruct(
    conversion: Conversion,
    version: ModelVersion,
    values: RunValues,
    *,
    ledger_position: int | None,
) -> AttributionRun:
    """The engine view of a stored, unscrubbed run, exact for attribute(previous=...).

    conversion is the stored conversion's engine contract; for a sale its anchor is replaced by
    the run's window end, as attribute() re-anchors it. ledger_position is the run's receipt
    ordinal when it belongs to the published ledger generation, else None.
    """
    if values.status == SUPERSEDED:
        raise ValueError("superseded_run")
    if conversion.kind is ConversionKind.SALE:
        anchored = Conversion(
            conversion.conversion_id,
            conversion.agency_id,
            conversion.client_id,
            conversion.person_id,
            conversion.kind,
            values.window_end,
            conversion.source_account_id,
            conversion.transaction_id,
        )
        sale = SaleState(
            LedgerScope(conversion.agency_id, conversion.client_id, conversion.source_account_id),
            conversion.transaction_id,
            values.currency,
            values.window_end,
            values.verified_net_minor,
        )
        net = sale.net
    else:
        anchored, sale, net = conversion, None, None
    basis = CreditBasis(values.basis)
    model = version.model
    touches: list[Touchpoint] = []
    allocations: list[CreditAllocation] = []
    for row in sorted(values.allocations, key=lambda item: item.ordinal):
        touch = None
        if row.recipient != Recipient.UNKNOWN.value:
            if row.touchpoint_id is None or row.occurred_at is None:
                raise ValueError("scrubbed_run")
            touch = Touchpoint(
                str(row.touchpoint_id),
                conversion.agency_id,
                conversion.client_id,
                conversion.person_id,
                EvidenceClass(row.evidence_class),
                row.occurred_at,
                Association.ASSIGNED,
                ConsentState.GRANTED,
                source=row.source,
                campaign_ref=row.campaign_ref,
                content_ref=row.content_ref,
                link_ref=str(row.link_ref) if row.link_ref is not None else None,
            )
            touches.append(touch)
        if row.credited:
            amount = (
                Money(row.amount_minor, values.currency) if row.amount_minor is not None else None
            )
            allocations.append(
                CreditAllocation(
                    Recipient(row.recipient),
                    CreditBasis(row.basis),
                    model,
                    row.position,
                    row.share,
                    amount,
                    touch,
                )
            )
    excluded = []
    for touchpoint_id, reason in values.excluded:
        if touchpoint_id is None:
            raise ValueError("scrubbed_run")
        excluded.append(ExcludedTouch(str(touchpoint_id), ExclusionReason(reason)))
    return AttributionRun(
        conversion=anchored,
        model_version=version,
        revision=values.revision,
        status=RunStatus(values.status),
        basis=basis,
        eligible=tuple(touches),
        sale=sale,
        verified_net=net,
        allocations=tuple(allocations),
        excluded=tuple(excluded),
        window_start=values.window_start,
        window_end=values.window_end,
        ledger_position=ledger_position,
        causes=tuple(RevisionCause(cause) for cause in values.causes),
        differences=(),
    )


# ---------------------------------------------------------------------------------------------
# Credit changes (the reporting ledger).


def _credited(values: RunValues) -> list[AllocationValues]:
    return [row for row in values.allocations if row.credited]


def _booking(
    row: AllocationValues, effective_at: datetime, currency: Currency | None, sign: int
) -> tuple:
    return (
        effective_at,
        row.recipient,
        row.touchpoint_id,
        row.source,
        row.campaign_ref,
        row.content_ref,
        row.link_ref,
        sign * row.share,
        sign * row.amount_minor if row.amount_minor is not None else None,
        currency,
    )


def _numbered(items: list[tuple]) -> tuple[CreditValues, ...]:
    return tuple(CreditValues(index, *item) for index, item in enumerate(items, start=1))


def _money_kind(kind: ConversionKind, currency: Currency | None) -> Currency | None:
    return currency if kind is ConversionKind.SALE else None


def credit_changes(
    kind: ConversionKind,
    previous: RunValues | None,
    current: RunValues,
    run: AttributionRun,
) -> tuple[CreditValues, ...]:
    """The credit changes a new revision books, given the previous stored revision."""
    items: list[tuple] = []
    currency = _money_kind(kind, current.currency)
    if previous is None:
        for row in _credited(current):
            items.append(_booking(row, current.window_end, currency, 1))
        return _numbered([item for item in items if _nonzero(item)])
    if previous.window_end != current.window_end:
        before = _money_kind(kind, previous.currency)
        for row in _credited(previous):
            items.append(_booking(row, previous.window_end, before, -1))
        for row in _credited(current):
            items.append(_booking(row, current.window_end, currency, 1))
        return _numbered([item for item in items if _nonzero(item)])
    for difference in run.differences:
        delta_minor = difference.delta_minor if kind is ConversionKind.SALE else None
        items.append(
            (
                current.window_end,
                difference.recipient.value,
                _uuid(difference.touchpoint_id),
                difference.source,
                difference.campaign_ref,
                difference.content_ref,
                _uuid(difference.link_ref),
                difference.delta_share,
                delta_minor,
                currency,
            )
        )
    return _numbered([item for item in items if _nonzero(item)])


def closing_changes(kind: ConversionKind, latest: RunValues) -> tuple[CreditValues, ...]:
    """The reversal a closing revision books: minus the latest credited allocations."""
    currency = _money_kind(kind, latest.currency)
    items = [_booking(row, latest.window_end, currency, -1) for row in _credited(latest)]
    return _numbered([item for item in items if _nonzero(item)])


def _nonzero(item: tuple) -> bool:
    share, minor = item[7], item[8]
    return share != 0 or (minor is not None and minor != 0)
