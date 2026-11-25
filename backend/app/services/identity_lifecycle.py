"""Development retention of identity data (specification 006 section 12.5, D-075 decision J6).

Runs as tracking_lifecycle, one client at a time, inside the lifecycle batch transaction that
already holds that client's privacy lock (app.services.lifecycle.delete_client_batch), so an
assertion, consent change or erasure either commits first and is observed, or waits. Each call
does a bounded amount of work and returns counts; the lifecycle loop repeats until nothing is
left. It never reads the matching secret or tombstones, never lowers an identity floor and never
touches financial rows.

Before the batch deletes expiring events, their erasure holds settle as expired (completing a
request whose last hold this settles) and the journeys they leave change; before it deletes an
expiring collection subject, the subject's identity evidence goes first. Links and assertions
expire 395 days after receipt, persons 395 days after their last evidence, contested keys 395
days after their last verification, handoffs 1 day after expiry or use, retry receipts at
expires_at, change records after 30 days (advancing pruned_through_seq), settled holds 30 days
after their request completed, and reversed or closed merge entries 2 years after they ended.
An expiry that removes a merge participant's last evidence closes the edge first (10.4).
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, delete, func, select, update
from sqlalchemy.orm import Session, aliased

from app.identity.segments import owner_of
from app.models import (
    CollectedEvent,
    CollectionSubject,
    IdentityAssertion,
    IdentityAssertionReceipt,
    IdentityChange,
    IdentityErasureHold,
    IdentityFeedState,
    IdentityHandoff,
    IdentityKey,
    IdentityLink,
    IdentityMerge,
    IdentitySubject,
    SubjectDeletionRequest,
)
from app.services.identity import (
    Journey,
    cleanup_people,
    drop_subject_evidence,
    event_times,
    owners_of_keys,
    remove_orphan_keys,
    remove_person,
    settle_holds,
    subject_segments,
)

IDENTITY_RETENTION = timedelta(days=395)
HANDOFF_GRACE = timedelta(days=1)
CHANGE_RETENTION = timedelta(days=30)
HOLD_RETENTION = timedelta(days=30)
MERGE_RETENTION = timedelta(days=730)


def candidates(connection: Connection, cutoff: datetime) -> set[UUID]:
    """Clients that may have identity work; eligibility is decided again under each lock."""
    old = cutoff - IDENTITY_RETENTION
    queries = (
        select(IdentityAssertionReceipt.client_id).where(
            IdentityAssertionReceipt.expires_at < cutoff
        ),
        select(IdentityHandoff.client_id).where(
            func.coalesce(IdentityHandoff.consumed_at, IdentityHandoff.expires_at)
            < cutoff - HANDOFF_GRACE
        ),
        select(IdentityChange.client_id).where(
            IdentityChange.occurred_at < cutoff - CHANGE_RETENTION
        ),
        select(IdentityLink.client_id).where(IdentityLink.asserted_at < old),
        select(IdentityAssertion.client_id).where(IdentityAssertion.received_at < old),
        select(IdentitySubject.client_id).where(IdentitySubject.last_evidence_at < old),
        select(IdentityKey.client_id).where(
            IdentityKey.status == "contested", IdentityKey.last_verified_at < old
        ),
        select(IdentityErasureHold.client_id).where(IdentityErasureHold.state != "held"),
        select(IdentityMerge.client_id).where(IdentityMerge.ended_at < cutoff - MERGE_RETENTION),
    )
    found: set[UUID] = set()
    for query in queries:
        found.update(connection.execute(query.distinct()).scalars())
    return found


def _agency(session: Session, client_id: UUID) -> UUID | None:
    for model in (IdentitySubject, IdentityFeedState, CollectionSubject):
        agency = session.scalar(
            select(model.agency_id).where(model.client_id == client_id).limit(1)
        )
        if agency is not None:
            return agency
    return None


def run(
    connection: Connection,
    client_id: UUID,
    cutoff: datetime,
    size: int,
    *,
    expiring_events: Sequence[UUID],
    expiring_subjects: Sequence[UUID],
) -> dict[str, int]:
    counts = dict.fromkeys(
        (
            "identity_holds_expired",
            "identity_subject_evidence",
            "identity_links",
            "identity_persons",
            "identity_keys",
            "identity_handoffs",
            "identity_receipts",
            "identity_changes",
            "identity_settled_holds",
            "identity_merges",
        ),
        0,
    )
    # A savepoint inside the batch transaction: commit() releases it and leaves the batch open.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        # Without a person, feed or collection subject there is no journey to record; the
        # purges below still run (a client may hold only receipts or handoffs).
        agency_id = _agency(session, client_id)
        journey = Journey(session, agency_id or client_id, client_id, cutoff)
        old = cutoff - IDENTITY_RETENTION
        # Events leaving retention: their owners' journeys change, then holds settle.
        if expiring_events:
            events = list(
                session.scalars(
                    select(CollectedEvent).where(CollectedEvent.id.in_(expiring_events))
                )
            )
            segments: dict[UUID, list] = {}
            for event in events:
                if event.subject_id not in segments:
                    segments[event.subject_id] = subject_segments(
                        session, event.subject_id, cutoff
                    )[1]
                owner = owner_of(event_times(event), segments[event.subject_id])
                if owner is not None:
                    journey.touch(owner, "events_changed")
            held = session.scalar(
                select(func.count())
                .select_from(IdentityErasureHold)
                .where(
                    IdentityErasureHold.client_id == client_id,
                    IdentityErasureHold.state == "held",
                    IdentityErasureHold.collected_event_id.in_(list(expiring_events)),
                )
            )
            settle_holds(session, client_id, list(expiring_events), "expired", cutoff)
            counts["identity_holds_expired"] = held or 0
        # Subjects leaving retention lose their identity evidence first.
        for subject_id in expiring_subjects:
            subject = session.scalar(
                select(CollectionSubject)
                .where(CollectionSubject.id == subject_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if subject is None:
                continue
            drop_subject_evidence(
                session, agency_id, client_id, subject, "expired", journey, cutoff
            )
            counts["identity_subject_evidence"] += 1
        # Links and assertions 395 days after receipt.
        links = list(
            session.scalars(
                select(IdentityLink)
                .where(IdentityLink.client_id == client_id, IdentityLink.asserted_at < old)
                .order_by(IdentityLink.asserted_at, IdentityLink.id)
                .limit(size)
                .with_for_update()
            )
        )
        assertions = list(
            session.scalars(
                select(IdentityAssertion)
                .where(
                    IdentityAssertion.client_id == client_id, IdentityAssertion.received_at < old
                )
                .order_by(IdentityAssertion.received_at, IdentityAssertion.id)
                .limit(size)
            )
        )
        people = {link.subject_id for link in links if link.subject_id is not None}
        people |= {item.subject_id for item in assertions if item.subject_id is not None}
        keys = {UUID(entry["key_id"]) for item in assertions for entry in item.evidence or []}
        # The owners of keys presented by expiring assertions are checked again (R0607-07).
        people |= owners_of_keys(session, keys)
        # F1 (J6): a sale association loses every identifying pointer before its assertion or
        # segment expires, so no binding still references a deleted assertion (R0607-03).
        from app.services.revenue_identity import unlink

        unlink(
            session,
            client_id,
            "expired",
            cutoff,
            assertion_refs={item.id for item in assertions}
            | {link.assertion_ref for link in links if link.assertion_ref is not None},
        )
        for link in links:
            session.delete(link)
        session.flush()
        for item in assertions:
            if (
                session.scalar(
                    select(IdentityLink.id).where(IdentityLink.assertion_ref == item.id).limit(1)
                )
                is None
            ):
                session.delete(item)
        session.flush()
        counts["identity_links"] = len(links) + len(assertions)
        cleanup_people(session, client_id, people, "expired", journey, cutoff)
        remove_orphan_keys(session, client_id, keys)
        # Persons 395 days after their last evidence.
        for person_id in session.scalars(
            select(IdentitySubject.id)
            .where(IdentitySubject.client_id == client_id, IdentitySubject.last_evidence_at < old)
            .order_by(IdentitySubject.id)
            .limit(size)
        ).all():
            if session.get(IdentitySubject, person_id) is not None:
                remove_person(session, client_id, person_id, "expired", journey, cutoff)
                counts["identity_persons"] += 1
        counts["identity_keys"] = session.execute(
            delete(IdentityKey).where(
                IdentityKey.id.in_(
                    select(IdentityKey.id)
                    .where(
                        IdentityKey.client_id == client_id,
                        IdentityKey.status == "contested",
                        IdentityKey.last_verified_at < old,
                    )
                    .limit(size)
                )
            )
        ).rowcount
        journey.flush()
        counts["identity_handoffs"] = session.execute(
            delete(IdentityHandoff).where(
                IdentityHandoff.id.in_(
                    select(IdentityHandoff.id)
                    .where(
                        IdentityHandoff.client_id == client_id,
                        func.coalesce(IdentityHandoff.consumed_at, IdentityHandoff.expires_at)
                        < cutoff - HANDOFF_GRACE,
                    )
                    .limit(size)
                )
            )
        ).rowcount
        counts["identity_receipts"] = session.execute(
            delete(IdentityAssertionReceipt).where(
                IdentityAssertionReceipt.id.in_(
                    select(IdentityAssertionReceipt.id)
                    .where(
                        IdentityAssertionReceipt.client_id == client_id,
                        IdentityAssertionReceipt.expires_at < cutoff,
                    )
                    .limit(size)
                )
            )
        ).rowcount
        # Change records after 30 days; the watermark records what was removed (11.1).
        pruned = list(
            session.scalars(
                delete(IdentityChange)
                .where(
                    IdentityChange.id.in_(
                        select(IdentityChange.id)
                        .where(
                            IdentityChange.client_id == client_id,
                            IdentityChange.occurred_at < cutoff - CHANGE_RETENTION,
                        )
                        .order_by(IdentityChange.seq)
                        .limit(size)
                    )
                )
                .returning(IdentityChange.seq)
            )
        )
        if pruned:
            state = session.scalar(
                select(IdentityFeedState)
                .where(IdentityFeedState.client_id == client_id)
                .with_for_update()
            )
            state.pruned_through_seq = max(state.pruned_through_seq, max(pruned))
            state.updated_at = cutoff
        counts["identity_changes"] = len(pruned)
        completed = select(SubjectDeletionRequest.id).where(
            SubjectDeletionRequest.client_id == client_id,
            SubjectDeletionRequest.completed_at < cutoff - HOLD_RETENTION,
        )
        counts["identity_settled_holds"] = session.execute(
            delete(IdentityErasureHold).where(
                IdentityErasureHold.client_id == client_id,
                IdentityErasureHold.state != "held",
                IdentityErasureHold.deletion_request_id.in_(completed),
            )
        ).rowcount
        edge = aliased(IdentityMerge)
        ended = select(edge.id).where(
            edge.client_id == client_id,
            edge.kind == "merge",
            edge.ended_at < cutoff - MERGE_RETENTION,
            ~select(IdentityKey.id).where(IdentityKey.merge_id == edge.id).exists(),
            ~select(IdentityLink.id).where(IdentityLink.merge_id == edge.id).exists(),
        )
        session.execute(
            update(IdentityAssertion)
            .where(IdentityAssertion.client_id == client_id, IdentityAssertion.merge_id.in_(ended))
            .values(merge_id=None)
        )
        session.execute(
            delete(IdentityMerge).where(
                IdentityMerge.client_id == client_id,
                IdentityMerge.kind == "unmerge",
                IdentityMerge.reverses_id.in_(ended),
            )
        )
        counts["identity_merges"] = session.execute(
            delete(IdentityMerge).where(IdentityMerge.id.in_(ended))
        ).rowcount
        session.flush()
        session.commit()
        # Only work done is reported, so a run without identity data keeps its result shape.
        return {name: value for name, value in counts.items() if value}
    finally:
        session.close()
