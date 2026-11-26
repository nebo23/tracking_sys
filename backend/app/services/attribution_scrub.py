"""Scrubbing stored attribution when a person or its evidence is removed (008-B, D-079 D9, D12).

The identity removal paths call these functions in their own transactions, under the client
privacy lock they already hold, after the F1 unlinking: remove_person, drop_subject_evidence,
the person erasure and the identity lifecycle expiry steps. A scrubbed conversion loses its
person reference, its lead event reference, its person-derived keys and every touchpoint ID and
touch instant of all its runs, allocations and credit changes. Shares, amounts, currencies,
reporting dates and the campaign, content, link and source provenance are never changed. The
next pass supersedes a scrubbed conversion and opens its successor from the current inputs, so
a replay never restores a scrubbed pointer.

Ordering against the attribution worker. Every scrub first makes sure the client's consumer
state row exists and increments its version and scrub epoch, and only then updates attribution
rows. A worker's first write is its compare-and-swap on the same row: a worker whose snapshot
predates the removal therefore loses its swap and writes nothing, and a worker that already
holds the row finishes its short write phase before the scrub statements run and see its rows.
Nothing here takes an advisory lock or touches a ledger, evidence or association row.
"""

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, cast, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    AttributionAllocation,
    AttributionConsumerState,
    AttributionConversion,
    AttributionCreditChange,
    AttributionRun,
    CollectedEvent,
    IdentityLink,
)
from app.services.attribution_records import scrubbed_slot_key

SCRUB_KINDS = ("erased", "expired")
BATCH = 1_000


def bump(session: Session, agency_id: UUID, client_id: UUID) -> None:
    """Order this removal against the worker: the consumer state row changes first."""
    session.execute(
        insert(AttributionConsumerState)
        .values(client_id=client_id, agency_id=agency_id)
        .on_conflict_do_nothing(index_elements=["client_id"])
    )
    session.execute(
        update(AttributionConsumerState)
        .where(AttributionConsumerState.client_id == client_id)
        .values(
            version=AttributionConsumerState.version + 1,
            scrub_epoch=AttributionConsumerState.scrub_epoch + 1,
            updated_at=func.clock_timestamp(),
        )
        .execution_options(synchronize_session=False)
    )


def _chunks(values: Iterable[UUID]) -> Iterable[list[UUID]]:
    items = sorted(set(values), key=str)
    for start in range(0, len(items), BATCH):
        yield items[start : start + BATCH]


def referencing(session: Session, client_id: UUID, event_ids: Iterable[UUID]) -> set[UUID]:
    """The conversions that hold any of these events as a touch or as their lead event."""
    found: set[UUID] = set()
    for ids in _chunks(event_ids):
        found.update(
            session.scalars(
                select(AttributionConversion.id).where(
                    AttributionConversion.client_id == client_id,
                    AttributionConversion.lead_event_id.in_(ids),
                )
            )
        )
        runs = set(
            session.scalars(
                select(AttributionAllocation.run_id).where(
                    AttributionAllocation.client_id == client_id,
                    AttributionAllocation.touchpoint_id.in_(ids),
                )
            )
        )
        runs.update(
            session.scalars(
                select(AttributionCreditChange.run_id).where(
                    AttributionCreditChange.client_id == client_id,
                    AttributionCreditChange.touchpoint_id.in_(ids),
                )
            )
        )
        found.update(
            session.scalars(
                select(AttributionRun.conversion_id).where(
                    AttributionRun.client_id == client_id,
                    AttributionRun.excluded_touchpoint_ids.overlap(ids),
                )
            )
        )
        if runs:
            found.update(
                session.scalars(
                    select(AttributionRun.conversion_id).where(
                        AttributionRun.client_id == client_id, AttributionRun.id.in_(runs)
                    )
                )
            )
    return found


def scrub_conversions(
    session: Session, client_id: UUID, conversion_ids: Iterable[UUID], now: datetime
) -> int:
    """Scrub every identifying pointer of the listed conversions; returns how many changed."""
    changed = 0
    for ids in _chunks(conversion_ids):
        rows = session.execute(
            select(AttributionConversion.id, AttributionConversion.kind).where(
                AttributionConversion.client_id == client_id,
                AttributionConversion.id.in_(ids),
            )
        ).all()
        for conversion_id, kind in rows:
            values = {
                "owner_person_id": None,
                "lead_event_id": None,
                "conversion_key": func.concat("scrubbed.", cast(AttributionConversion.id, String)),
                "scrubbed_at": func.coalesce(AttributionConversion.scrubbed_at, now),
            }
            if kind == "lead":
                # The lead slot is derived from its event; a sale slot names no person.
                values["slot_key"] = scrubbed_slot_key(conversion_id)
            changed += session.execute(
                update(AttributionConversion)
                .where(
                    AttributionConversion.id == conversion_id,
                    AttributionConversion.scrubbed_at.is_(None),
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            ).rowcount
        if not rows:
            continue
        found = [conversion_id for conversion_id, _ in rows]
        runs = select(AttributionRun.id).where(
            AttributionRun.client_id == client_id, AttributionRun.conversion_id.in_(found)
        )
        # Every excluded touchpoint ID becomes null; the reasons and their order stay.
        session.execute(
            text(
                "UPDATE attribution_runs SET excluded_touchpoint_ids = "
                "array_fill(NULL::uuid, ARRAY[cardinality(excluded_touchpoint_ids)]) "
                "WHERE client_id = :client AND conversion_id = ANY(:conversions) "
                "AND cardinality(excluded_touchpoint_ids) > 0"
            ),
            {"client": client_id, "conversions": found},
        )
        session.execute(
            update(AttributionAllocation)
            .where(
                AttributionAllocation.client_id == client_id,
                AttributionAllocation.run_id.in_(runs),
                AttributionAllocation.touchpoint_id.is_not(None)
                | AttributionAllocation.occurred_at.is_not(None),
            )
            .values(touchpoint_id=None, occurred_at=None)
            .execution_options(synchronize_session=False)
        )
        session.execute(
            update(AttributionCreditChange)
            .where(
                AttributionCreditChange.client_id == client_id,
                AttributionCreditChange.run_id.in_(runs),
                AttributionCreditChange.touchpoint_id.is_not(None),
            )
            .values(touchpoint_id=None)
            .execution_options(synchronize_session=False)
        )
    return changed


def scrub_events(
    session: Session, agency_id: UUID, client_id: UUID, event_ids: Iterable[UUID], now: datetime
) -> int:
    """Scrub every conversion that references one of these events (erasure or expiry)."""
    bump(session, agency_id, client_id)
    return scrub_conversions(session, client_id, referencing(session, client_id, event_ids), now)


def scrub_person(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    person_id: UUID,
    kind: str,
    now: datetime,
    event_ids: Iterable[UUID] = (),
) -> int:
    """Scrub the conversions a removed person owns and, for erasure and expiry, every
    conversion that references one of its events."""
    bump(session, agency_id, client_id)
    affected = set(
        session.scalars(
            select(AttributionConversion.id).where(
                AttributionConversion.client_id == client_id,
                AttributionConversion.owner_person_id == person_id,
            )
        )
    )
    if kind in SCRUB_KINDS:
        affected |= referencing(session, client_id, event_ids)
    return scrub_conversions(session, client_id, affected, now)


def subject_event_ids(session: Session, client_id: UUID, subject_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            select(CollectedEvent.event_id).where(
                CollectedEvent.client_id == client_id, CollectedEvent.subject_id == subject_id
            )
        )
    )


def link_event_ids(session: Session, link: IdentityLink, now: datetime) -> list[UUID]:
    """The events one link's segment assigns: those of its subject it covers."""
    from app.services.identity import identity_consent, link_segment

    periods = identity_consent(session, link.collection_subject_id, now).periods
    segment = link_segment(link, periods)
    return [
        event_id
        for event_id, received_at in session.execute(
            select(CollectedEvent.event_id, CollectedEvent.first_received_at).where(
                CollectedEvent.client_id == link.client_id,
                CollectedEvent.subject_id == link.collection_subject_id,
            )
        )
        if segment.covers(received_at)
    ]


def person_event_ids(
    session: Session, client_id: UUID, person_id: UUID, now: datetime
) -> list[UUID]:
    """The events currently assigned to a person through its own active segments."""
    found: list[UUID] = []
    for link in session.scalars(
        select(IdentityLink).where(
            IdentityLink.client_id == client_id,
            IdentityLink.status == "active",
            IdentityLink.subject_id == person_id,
        )
    ):
        found.extend(link_event_ids(session, link, now))
    return found


def scrubbed_at(session: Session, client_id: UUID, now: datetime) -> int:
    """How many conversions this transaction scrubbed (its scrubs share the instant now)."""
    return session.scalar(
        select(func.count())
        .select_from(AttributionConversion)
        .where(
            AttributionConversion.client_id == client_id,
            AttributionConversion.scrubbed_at == now,
        )
    )
