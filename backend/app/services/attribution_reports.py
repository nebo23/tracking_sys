"""Snapshot reads of stored attribution for the 016-B reports (specification 016-B, D-089).

Every function runs inside the caller's report_snapshot (READ ONLY, REPEATABLE READ), so the
consumer state, the status read, the model versions, the aggregated credit, the ledger totals
and the group metadata of one report come from one moment. Every query is scoped by agency
and client. Credit is read only up to the published generation, so a rebuild in progress is
never half-visible. Nothing here writes, locks, calls a provider or starts a worker pass.

Stored credit at a published generation changes only through a write that also changes the
consumer state's version (the worker's compare-and-swap, the scrub and the lifecycle), so the
release check compares the tokens and the group metadata instead of aggregating again.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Any
from uuid import UUID

from sqlalchemy import case, distinct, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models import (
    AdObject,
    AttributionAllocation,
    AttributionConsumerState,
    AttributionConversion,
    AttributionCreditChange,
    AttributionModelVersion,
    AttributionRun,
    ConnectorConnection,
    ConnectorRecord,
    LedgerTransaction,
    LinkCampaign,
    LinkContentReference,
    ManagedLink,
)
from app.reporting.catalog import FAMILIES
from app.reporting.common import MAX_SOURCE_ROWS, ReportError
from app.reporting.credit import (
    MAX_GROUPS,
    AttributionContext,
    CountRow,
    CreditRow,
    GroupMeta,
    LedgerTotal,
    group_refs,
)
from app.reporting.digest import Digest
from app.services import attribution_reads
from app.services.access import ScopedAccess
from app.services.attribution_models import versions as model_versions
from app.services.attribution_models import view
from app.services.tenancy import AccessDenied

BATCH = 1_000
REPORTABLE = ("active", "reconnect_required")
CREDIT_REFS = {
    "campaign": AttributionCreditChange.campaign_ref,
    "content": AttributionCreditChange.content_ref,
    "link": AttributionCreditChange.link_ref,
}
ALLOCATION_REFS = {
    "campaign": AttributionAllocation.campaign_ref,
    "content": AttributionAllocation.content_ref,
    "link": AttributionAllocation.link_ref,
}


@dataclass(frozen=True)
class Bounds:
    """The UTC instants of the requested period and, optionally, the previous one."""

    low: datetime  # start of the earliest period
    split: datetime  # start of the current period
    high: datetime  # end of the current period

    @classmethod
    def of(cls, current: tuple[datetime, datetime], previous: tuple[datetime, datetime] | None):
        return cls(previous[0] if previous else current[0], current[0], current[1])

    @property
    def labels(self) -> tuple[str, ...]:
        return ("current",) if self.low == self.split else ("current", "previous")


@dataclass(frozen=True)
class ContextRead:
    context: AttributionContext
    rows: tuple[AttributionModelVersion, ...]
    selected: tuple[UUID, ...]  # the versions whose credit the report aggregates
    tokens: list[Any]


def _version_token(row: AttributionModelVersion) -> list[Any]:
    return [
        row.id,
        row.version_key,
        row.model,
        row.window_seconds,
        row.rules,
        row.is_default,
        row.status,
        row.retired_at,
    ]


def read_context(
    session: Session, access: ScopedAccess, version_id: UUID | None, *, models: bool = False
) -> ContextRead:
    """The consumer state, the 008-B status read and the client's model versions."""
    state = session.get(AttributionConsumerState, access.client_id, populate_existing=True)
    if state is not None and state.agency_id != access.agency_id:
        raise AccessDenied()
    status = attribution_reads.status(session, access.agency_id, access.client_id)
    label = "failed" if state is not None and state.status == "failed" else status["state"]
    rows = tuple(model_versions(session, access.client_id))
    selected: AttributionModelVersion | None = None
    if models:
        chosen = tuple(row.id for row in rows if row.status == "active")
    else:
        if version_id is None:
            selected = next((row for row in rows if row.is_default), None)
        else:
            selected = next((row for row in rows if row.id == version_id), None)
            if selected is None:
                raise AccessDenied()  # an unknown or foreign version looks the same
        chosen = () if selected is None else (selected.id,)
    consumer = status["consumer"]
    context = AttributionContext(
        state=label,
        generation=state.generation if state is not None else 0,
        published_at=state.published_at if state is not None else None,
        failure_code=state.failure_code if state is not None else None,
        unit=state.unit_kind if state is not None else None,
        consumer={
            "ledger_generation": consumer["ledger_generation"],
            "receipt_ordinal": consumer["receipt_ordinal"],
            "identity_seq": consumer["identity_seq"],
        },
        current=dict(status["current"]),
        versions=tuple(view(row) for row in rows),
        version=None if selected is None else view(selected),
    )
    tokens = [
        "attribution",
        None
        if state is None
        else [
            state.generation,
            state.version,
            state.scrub_epoch,
            state.status,
            state.failure_code,
            state.unit_kind,
            state.ledger_generation,
            state.receipt_ordinal,
            state.identity_seq,
            state.model_set_digest,
            state.published_at,
        ],
        [label, status["state"], dict(status["current"]), consumer["model_set_current"]],
        [_version_token(row) for row in rows],
        list(chosen),
    ]
    return ContextRead(context, rows, chosen, tokens)


def _period(column: Any, bounds: Bounds) -> Any:
    return case((column >= bounds.split, "current"), else_="previous").label("period")


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def count_groups(
    session: Session,
    access: ScopedAccess,
    versions: Sequence[UUID],
    generation: int,
    bounds: Bounds,
    group_by: str,
) -> int:
    """The bounded number of groups of the current period (cap + 1 at most)."""
    if group_by == "recipient" or not versions:
        return 0
    change = AttributionCreditChange
    inner = (
        select(change.recipient, CREDIT_REFS[group_by])
        .where(
            change.agency_id == access.agency_id,
            change.client_id == access.client_id,
            change.model_version_id.in_(list(versions)),
            change.generation <= generation,
            change.effective_at >= bounds.split,
            change.effective_at < bounds.high,
        )
        .distinct()
        .limit(MAX_GROUPS + 1)
        .subquery()
    )
    return int(session.scalar(select(func.count()).select_from(inner)) or 0)


def read_credit(
    session: Session,
    access: ScopedAccess,
    versions: Sequence[UUID],
    generation: int,
    bounds: Bounds,
    group_by: str | None,
) -> list[CreditRow]:
    """Stored credit of the published generation, aggregated in SQL (design section 2).

    group_by campaign, content or link groups by that reference; recipient or None groups by
    recipient class only."""
    if not versions or generation <= 0:
        return []
    change = AttributionCreditChange
    period = _period(change.effective_at, bounds)
    ref = CREDIT_REFS[group_by] if group_by in CREDIT_REFS else None
    keys = [change.model_version_id, period, change.recipient]
    if ref is not None:
        keys.append(ref)
    keys += [
        change.conversion_kind,
        change.currency,
        change.currency_exponent,
        change.delta_share_denominator,
    ]
    query = (
        select(
            *keys,
            func.sum(change.delta_share_numerator),
            func.sum(change.delta_minor),
        )
        .where(
            change.agency_id == access.agency_id,
            change.client_id == access.client_id,
            change.model_version_id.in_(list(versions)),
            change.generation <= generation,
            change.effective_at >= bounds.low,
            change.effective_at < bounds.high,
        )
        .group_by(*keys)
    )
    found = []
    for row in session.execute(query):
        values = list(row)
        version_id, label, recipient = values[:3]
        reference = _text(values[3]) if ref is not None else None
        kind, currency, exponent, denominator, numerator, minor = values[-6:]
        found.append(
            CreditRow(
                version_id=version_id,
                period=label,
                recipient=recipient,
                ref=reference,
                kind=kind,
                currency=currency,
                exponent=exponent,
                share=Fraction(int(numerator), int(denominator)),
                minor=None if minor is None else int(minor),
            )
        )
    return found


def read_counts(
    session: Session,
    access: ScopedAccess,
    versions: Sequence[UUID],
    generation: int,
    bounds: Bounds,
    group_by: str | None,
) -> list[CountRow]:
    """Conversions whose latest revision credits a group (group_by) or a recipient class (None).

    A conversion's reporting ledger nets to its latest revision's credited allocations at that
    revision's anchor, so counting the latest revisions is exact (design section 2)."""
    if not versions or generation <= 0:
        return []
    run = AttributionRun
    latest = (
        select(
            run.id,
            run.conversion_id,
            run.model_version_id,
            run.status,
            run.window_end,
            run.currency,
            run.currency_exponent,
        )
        .where(
            run.agency_id == access.agency_id,
            run.client_id == access.client_id,
            run.model_version_id.in_(list(versions)),
            run.generation <= generation,
        )
        .ext(distinct_on(run.conversion_id, run.model_version_id))
        .order_by(run.conversion_id, run.model_version_id, run.revision.desc())
        .subquery()
    )
    allocation, conversion = AttributionAllocation, AttributionConversion
    period = _period(latest.c.window_end, bounds)
    ref = ALLOCATION_REFS[group_by] if group_by in ALLOCATION_REFS else None
    keys = [latest.c.model_version_id, period, allocation.recipient]
    if ref is not None:
        keys.append(ref)
    keys += [conversion.kind, latest.c.currency, latest.c.currency_exponent]
    counted = func.count(distinct(latest.c.conversion_id))
    query = (
        select(
            *keys,
            counted,
            func.count(distinct(latest.c.conversion_id)).filter(
                conversion.owner_person_id.is_(None)
            ),
        )
        .select_from(latest)
        .join(
            allocation,
            (allocation.run_id == latest.c.id)
            & (allocation.client_id == access.client_id)
            & allocation.credited,
        )
        .join(
            conversion,
            (conversion.id == latest.c.conversion_id) & (conversion.client_id == access.client_id),
        )
        .where(
            latest.c.status == "complete",
            latest.c.window_end >= bounds.low,
            latest.c.window_end < bounds.high,
        )
        .group_by(*keys)
    )
    found = []
    for row in session.execute(query):
        values = list(row)
        version_id, label, recipient = values[:3]
        reference = _text(values[3]) if ref is not None else None
        kind, currency, exponent, conversions, unassociated = values[-5:]
        found.append(
            CountRow(
                version_id=version_id,
                period=label,
                recipient=recipient,
                ref=reference,
                kind=kind,
                currency=currency,
                exponent=exponent,
                conversions=int(conversions),
                unassociated=int(unassociated),
            )
        )
    return found


def read_ledger(
    session: Session, access: ScopedAccess, context: AttributionContext, bounds: Bounds
) -> tuple[str, list[LedgerTotal]]:
    """The verified net of the period's sales in the published ledger, per currency, with a
    negative net counted as zero, as the worker credits it."""
    current = context.current
    state = current["ledger"]
    if state != "available":
        return state, []
    transaction = LedgerTransaction
    period = _period(transaction.sale_effective_at, bounds)
    query = (
        select(
            period,
            transaction.currency,
            transaction.currency_exponent,
            func.sum(func.greatest(transaction.net, 0)),
        )
        .where(
            transaction.agency_id == access.agency_id,
            transaction.client_id == access.client_id,
            transaction.generation == current["ledger_generation"],
            transaction.sale_effective_at >= bounds.low,
            transaction.sale_effective_at < bounds.high,
        )
        .group_by(period, transaction.currency, transaction.currency_exponent)
    )
    return state, [
        LedgerTotal(label, code, exponent, int(net))
        for label, code, exponent, net in session.execute(query)
    ]


def _batches(values: Sequence[str]) -> Iterable[list[str]]:
    for start in range(0, len(values), BATCH):
        yield list(values[start : start + BATCH])


def _uuids(values: Iterable[str]) -> list[UUID]:
    found = []
    for value in values:
        try:
            found.append(UUID(value))
        except ValueError:
            continue
    return found


def read_meta(
    session: Session, access: ScopedAccess, group_by: str, refs: Sequence[str]
) -> GroupMeta:
    """Registered flags and, for content, the social content items with the same ID."""
    registered: dict[str, bool] = {}
    pointers: dict[str, list[dict[str, Any]]] = {}
    if group_by == "recipient" or not refs:
        return GroupMeta(registered, pointers)
    scope = {
        "campaign": (LinkCampaign, LinkCampaign.public_code),
        "content": (LinkContentReference, LinkContentReference.external_code),
    }
    for chunk in _batches(list(refs)):
        if group_by in scope:
            model, column = scope[group_by]
            known = set(
                session.scalars(
                    select(column).where(
                        model.agency_id == access.agency_id,
                        model.client_id == access.client_id,
                        column.in_(chunk),
                    )
                )
            )
        else:
            ids = _uuids(chunk)
            known = (
                {
                    str(item)
                    for item in session.scalars(
                        select(ManagedLink.id).where(
                            ManagedLink.agency_id == access.agency_id,
                            ManagedLink.client_id == access.client_id,
                            ManagedLink.id.in_(ids),
                        )
                    )
                }
                if ids
                else set()
            )
        for ref in chunk:
            registered[ref] = ref in known
    if group_by == "content":
        record, connection = ConnectorRecord, ConnectorConnection
        streams = []
        for family in FAMILIES.values():
            names = list(family.content_streams)
            if family.publication_stream is not None:
                names.append(family.publication_stream)
            streams.append(
                connection.provider.in_(list(family.providers)) & record.stream.in_(names)
            )
        condition = streams[0]
        for item in streams[1:]:
            condition = condition | item
        for chunk in _batches(list(refs)):
            for object_id, connection_id, provider, stream in session.execute(
                select(
                    record.provider_object_id,
                    record.connection_id,
                    connection.provider,
                    record.stream,
                )
                .join(
                    connection,
                    (connection.id == record.connection_id)
                    & (connection.agency_id == record.agency_id)
                    & (connection.client_id == record.client_id),
                )
                .where(
                    record.agency_id == access.agency_id,
                    record.client_id == access.client_id,
                    connection.status.in_(REPORTABLE),
                    record.connection_generation == connection.generation,
                    condition,
                    record.provider_object_id.in_(chunk),
                )
                .order_by(record.provider_object_id, record.connection_id, record.stream)
            ):
                pointers.setdefault(object_id, []).append(
                    {
                        "connection_id": connection_id,
                        "provider": provider,
                        "stream": stream,
                        "content_id": object_id,
                    }
                )
    return GroupMeta(registered, pointers)


def meta_token(meta: GroupMeta) -> list[Any]:
    return [
        "meta",
        sorted(meta.registered.items()),
        [
            [ref, [[item["connection_id"], item["provider"], item["stream"]] for item in items]]
            for ref, items in sorted(meta.pointers.items())
        ],
    ]


@dataclass(frozen=True)
class AttributionInputs:
    """Everything one attribution report reads, with the digest its release check rereads."""

    context: AttributionContext
    selected: tuple[UUID, ...]
    credit: tuple[CreditRow, ...]
    counts: tuple[CountRow, ...]
    recipient_counts: tuple[CountRow, ...]
    ledger_state: str
    ledger: tuple[LedgerTotal, ...]
    meta: GroupMeta
    refs: tuple[str, ...]
    digest: str


def inputs_digest(tokens: list[Any], meta: GroupMeta, extra: Iterable[Any] = ()) -> str:
    target = Digest("attribution-inputs")
    target.add(tokens)
    target.add(meta_token(meta))
    for item in extra:
        target.add(item)
    return target.hexdigest()


def read_attribution_inputs(
    session: Session,
    access: ScopedAccess,
    *,
    version_id: UUID | None,
    view_name: str,
    group_by: str,
    bounds: Bounds,
    finance: bool,
) -> AttributionInputs:
    models = view_name == "models"
    read = read_context(session, access, version_id, models=models)
    context = read.context
    generation = context.generation if context.ready(models) else 0
    if count_groups(session, access, read.selected, generation, bounds, group_by) > MAX_GROUPS:
        raise ReportError("report_too_large", 422)
    credit = read_credit(session, access, read.selected, generation, bounds, group_by)
    counts = read_counts(session, access, read.selected, generation, bounds, group_by)
    recipient_counts = read_counts(session, access, read.selected, generation, bounds, None)
    ledger_state, ledger = (
        read_ledger(session, access, context, bounds)
        if finance
        else (context.current["ledger"], [])
    )
    refs = group_refs(credit, group_by)
    meta = read_meta(session, access, group_by, refs)
    return AttributionInputs(
        context=context,
        selected=read.selected,
        credit=tuple(credit),
        counts=tuple(counts),
        recipient_counts=tuple(recipient_counts),
        ledger_state=ledger_state,
        ledger=tuple(ledger),
        meta=meta,
        refs=refs,
        digest=inputs_digest(read.tokens, meta),
    )


def attribution_release_digest(
    session: Session,
    access: ScopedAccess,
    *,
    version_id: UUID | None,
    view_name: str,
    group_by: str,
    refs: Sequence[str],
) -> str:
    read = read_context(session, access, version_id, models=view_name == "models")
    return inputs_digest(read.tokens, read_meta(session, access, group_by, refs))


# --- ROAS (016-B P2) ---------------------------------------------------------------------------


def read_ad_objects(
    session: Session, access: ScopedAccess, connection_id: UUID
) -> tuple[dict[str, tuple[str, str | None]], list[Any]]:
    """The ads stored under the spend connection: ad ID to (campaign ID, ad set ID), bounded."""
    scope = (
        AdObject.agency_id == access.agency_id,
        AdObject.client_id == access.client_id,
        AdObject.connection_id == connection_id,
        AdObject.level == "ad",
    )
    inner = select(AdObject.id).where(*scope).limit(MAX_SOURCE_ROWS + 1).subquery()
    if int(session.scalar(select(func.count()).select_from(inner)) or 0) > MAX_SOURCE_ROWS:
        raise ReportError("report_too_large", 422)
    found: dict[str, tuple[str, str | None]] = {}
    for object_id, campaign_id, adset_id in session.execute(
        select(AdObject.object_id, AdObject.campaign_id, AdObject.adset_id)
        .where(*scope)
        .order_by(AdObject.object_id)
    ):
        found[object_id] = (campaign_id, adset_id)
    return found, ["ad_objects", sorted([key, *value] for key, value in found.items())]


def read_roas_credit(
    session: Session,
    access: ScopedAccess,
    versions: Sequence[UUID],
    generation: int,
    bounds: Bounds,
) -> list[tuple]:
    """Stored credit of the published generation by campaign and content reference, kind,
    currency and share denominator, over the account-local bounds of each period."""
    if not versions or generation <= 0:
        return []
    change = AttributionCreditChange
    scope = (
        change.agency_id == access.agency_id,
        change.client_id == access.client_id,
        change.model_version_id.in_(list(versions)),
        change.generation <= generation,
        change.effective_at >= bounds.low,
        change.effective_at < bounds.high,
    )
    inner = (
        select(change.campaign_ref, change.content_ref)
        .where(*scope)
        .distinct()
        .limit(MAX_GROUPS + 1)
        .subquery()
    )
    if int(session.scalar(select(func.count()).select_from(inner)) or 0) > MAX_GROUPS:
        raise ReportError("report_too_large", 422)
    period = _period(change.effective_at, bounds)
    keys = [
        period,
        change.campaign_ref,
        change.content_ref,
        change.conversion_kind,
        change.currency,
        change.delta_share_denominator,
    ]
    return [
        tuple(row)
        for row in session.execute(
            select(*keys, func.sum(change.delta_share_numerator), func.sum(change.delta_minor))
            .where(*scope)
            .group_by(*keys)
        )
    ]
