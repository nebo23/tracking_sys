"""Identity assertions, segments, consent effects and the change feed (specification 006, D-075).

Every write runs under the 004 client privacy lock (app.services.collection.lock_client), reads
the database clock after the lock is held, rechecks live sender scope and only then reads
consent, tombstones and identity rows. Audited administration (merge, reversal, person erasure)
takes the agency row lock first; nothing here acquires an agency, user or revenue lock while
holding the privacy lock.

Assertion processing follows design section 4.2 in order: validation before the lock; then
the per-client matching key, retry receipts (answered from the receipt alone inside its 24-hour
window), freshness, proof (a browser handoff or a server-issued subject token), current
identity_link consent, replay and identity-key tombstones, matching (R1-R5), the device rule
(segments, floor, shared marker and the provisional prefix of R006-27) and one commit of
evidence, receipt, keys, links, revisions and change records. Every well-formed, fresh and
proven assertion receives the same generic acknowledgement whatever happens internally.

The change feed allocates contiguous per-client sequence numbers under the client lock in the
transaction that changes a journey; identity_feed_state advances in the same transaction.
"""

import json
import secrets
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Uuid, any_, delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.collection.keys import TombstoneKeyring
from app.config import Settings
from app.identity import matching
from app.identity.normalize import KEY_VERSION, Canonical, IdentifierRejected
from app.identity.segments import (
    ConsentMark,
    EventTimes,
    Period,
    Segment,
    current_period,
    effective_end,
    grant_periods,
    owner_of,
)
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
    IdentityKeySecret,
    IdentityLink,
    IdentityMerge,
    IdentitySubject,
    StoredConsentRecord,
    StoredTombstone,
    SubjectDeletionRequest,
)
from app.privacy import deletion
from app.privacy.consent import Purpose
from app.privacy.deletion import RequestStatus, TargetStatus, keyed_identifier, subject_key
from app.privacy.token_secrets import (
    LocalKeyring,
    SealedSecret,
    SecretContext,
    open_secret,
    seal,
)
from app.security import digest, new_token

HANDOFF_LIFETIME = timedelta(minutes=10)
RETRY_WINDOW = timedelta(hours=24)
FRESHNESS = timedelta(days=30)
FUTURE_SKEW = timedelta(minutes=5)
SECRET_KIND = "identity_matching_key"
FINGERPRINT_DOMAIN = "assertion:v1"
REMOVAL_KINDS = ("erased", "withdrawn", "expired")


class IdentityError(Exception):
    """A public refusal with a closed reason code and HTTP status."""

    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


# ---------------------------------------------------------------------------------------------
# Per-client matching key (design section 12.1): sealed under the D-025 development keyring.


def _context(agency_id: UUID, client_id: UUID, secret_id: UUID, version: int) -> SecretContext:
    return SecretContext(agency_id, client_id, client_id, secret_id, SECRET_KIND, version)


def matching_key(
    session: Session, keyring: LocalKeyring, agency_id: UUID, client_id: UUID, *, create: bool
) -> bytes | None:
    """The client's matching secret; created on first use (the caller holds the client lock)."""
    row = session.scalar(
        select(IdentityKeySecret)
        .where(IdentityKeySecret.agency_id == agency_id, IdentityKeySecret.client_id == client_id)
        .order_by(IdentityKeySecret.version.desc())
        .limit(1)
    )
    if row is not None:
        sealed = SealedSecret(
            row.kek_id, row.wrap_nonce, row.wrapped_dek, row.nonce, row.ciphertext
        )
        return bytes.fromhex(
            open_secret(keyring, sealed, _context(agency_id, client_id, row.id, row.version))
        )
    if not create:
        return None
    raw = secrets.token_bytes(32)
    secret_id = uuid4()
    sealed = seal(keyring, raw.hex(), _context(agency_id, client_id, secret_id, 1))
    session.add(
        IdentityKeySecret(
            id=secret_id,
            agency_id=agency_id,
            client_id=client_id,
            version=1,
            kek_id=sealed.kek_id,
            wrap_nonce=sealed.wrap_nonce,
            wrapped_dek=sealed.wrapped_dek,
            nonce=sealed.nonce,
            ciphertext=sealed.ciphertext,
        )
    )
    session.flush()
    return raw


def identity_key(secret: bytes, client_id: UUID, item: Canonical) -> bytes:
    return subject_key(secret, client_id, item.normalizer, item.value)


# ---------------------------------------------------------------------------------------------
# Change feed (design sections 9.1 and 11): one revision per affected person per transaction.


class Journey:
    """Collects the persons whose visible journey a transaction changes, then records them."""

    def __init__(self, session: Session, agency_id: UUID, client_id: UUID, now: datetime) -> None:
        self.session, self.agency_id, self.client_id, self.now = session, agency_id, client_id, now
        self.touched: dict[UUID, str] = {}
        self.recorded: set[UUID] = set()

    def touch(self, person_id: UUID | None, kind: str) -> None:
        if person_id is None or person_id in self.recorded:
            return
        if person_id not in self.touched or kind in REMOVAL_KINDS:
            self.touched[person_id] = kind
        root = self.session.scalar(
            select(IdentitySubject.merged_into_id).where(IdentitySubject.id == person_id)
        )
        if root is not None and root not in self.touched and root not in self.recorded:
            self.touched[root] = kind if kind not in REMOVAL_KINDS else "events_changed"

    def _sequence(self, count: int) -> int:
        statement = insert(IdentityFeedState).values(
            client_id=self.client_id, agency_id=self.agency_id, last_seq=0, pruned_through_seq=0
        )
        self.session.execute(statement.on_conflict_do_nothing(index_elements=["client_id"]))
        state = self.session.scalar(
            select(IdentityFeedState)
            .where(IdentityFeedState.client_id == self.client_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        first = state.last_seq + 1
        state.last_seq += count
        state.updated_at = self.now
        return first

    def _record(self, people: list[tuple[UUID, str]]) -> None:
        if not people:
            return
        first = self._sequence(len(people))
        for offset, (person_id, kind) in enumerate(people):
            person = self.session.scalar(
                select(IdentitySubject)
                .where(IdentitySubject.id == person_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if person is None:
                continue
            person.journey_revision += 1
            person.updated_at = self.now
            self.session.add(
                IdentityChange(
                    id=uuid4(),
                    agency_id=self.agency_id,
                    client_id=self.client_id,
                    seq=first + offset,
                    person_id=person_id,
                    kind=kind,
                    journey_revision=person.journey_revision,
                    occurred_at=self.now,
                )
            )
            self.recorded.add(person_id)
        self.session.flush()

    def final(self, person_id: UUID, kind: str) -> None:
        """Record a person's last revision now, before its row is deleted."""
        self.touched.pop(person_id, None)
        if person_id not in self.recorded:
            self._record([(person_id, kind)])

    def flush(self) -> None:
        pending = sorted(
            (item for item in self.touched.items() if item[0] not in self.recorded),
            key=lambda item: str(item[0]),
        )
        self.touched.clear()
        existing = set(
            self.session.scalars(
                select(IdentitySubject.id).where(
                    IdentitySubject.id.in_([person for person, _ in pending])
                )
            )
        )
        self._record([(person, kind) for person, kind in pending if person in existing])


# ---------------------------------------------------------------------------------------------
# Consent and segments of one collection subject.


@dataclass(frozen=True)
class IdentityConsent:
    periods: list[Period]
    current: Period | None
    grant_record_id: UUID | None  # the latest identity_link record, while it grants


def identity_consent(session: Session, subject_id: UUID, now: datetime) -> IdentityConsent:
    rows = list(
        session.scalars(
            select(StoredConsentRecord)
            .where(
                StoredConsentRecord.subject_id == subject_id,
                StoredConsentRecord.purpose == Purpose.IDENTITY_LINK.value,
            )
            .order_by(StoredConsentRecord.received_at, StoredConsentRecord.id)
        )
    )
    periods = grant_periods(
        (ConsentMark(row.received_at, row.state == "granted", row.expires_at) for row in rows),
        now,
    )
    current = current_period(periods, now)
    latest = rows[-1] if rows else None
    granted = (
        latest is not None
        and latest.state == "granted"
        and (latest.expires_at is None or latest.expires_at > now)
    )
    return IdentityConsent(periods, current, latest.id if granted and latest else None)


def link_segment(link: IdentityLink, periods: Sequence[Period]) -> Segment:
    return Segment(
        link.status,  # type: ignore[arg-type]
        link.subject_id,
        frozenset(link.candidate_ids or ()),
        link.provisional_from or link.eligible_from,
        effective_end(link.eligible_until, periods, link.asserted_at),
    )


def subject_links(session: Session, subject_id: UUID, *, lock: bool = False) -> list[IdentityLink]:
    query = (
        select(IdentityLink)
        .where(IdentityLink.collection_subject_id == subject_id)
        .order_by(IdentityLink.asserted_at, IdentityLink.id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return list(session.scalars(query))


def subject_segments(
    session: Session, subject_id: UUID, now: datetime
) -> tuple[list[IdentityLink], list[Segment]]:
    consent = identity_consent(session, subject_id, now)
    links = subject_links(session, subject_id)
    return links, [link_segment(link, consent.periods) for link in links]


def event_times(event: CollectedEvent) -> EventTimes:
    excluded = event.identity_excluded_at is not None
    return EventTimes(event.first_received_at, event.occurred_at, excluded)


# Persist the closure of segments whose identity grant period ended (design section 6): the
# next write under the client lock records eligible_until and raises the floor before it
# computes any new link.
def close_ended_segments(
    session: Session, subject: CollectionSubject, links: Iterable[IdentityLink], periods
) -> None:
    for link in links:
        if link.eligible_until is not None:
            continue
        ended = effective_end(None, periods, link.asserted_at)
        if ended is not None:
            link.eligible_until, link.closed_reason = ended, "consent_ended"
            _raise_floor(subject, ended)


def _raise_floor(subject: CollectionSubject, moment: datetime) -> None:
    if subject.identity_floor_at is None or subject.identity_floor_at < moment:
        subject.identity_floor_at = moment


# ---------------------------------------------------------------------------------------------
# Person evidence, removal and the single merge-loss rule (design section 10.4, R006-25).


def root_of(session: Session, person_id: UUID) -> UUID:
    merged = session.scalar(
        select(IdentitySubject.merged_into_id).where(IdentitySubject.id == person_id)
    )
    return merged or person_id


def active_edge(session: Session, person_id: UUID) -> IdentityMerge | None:
    return session.scalar(
        select(IdentityMerge)
        .where(
            IdentityMerge.status == "active",
            or_(IdentityMerge.survivor_id == person_id, IdentityMerge.merged_id == person_id),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _assertions_presenting(session: Session, client_id: UUID, key_id: UUID):
    return (
        select(IdentityAssertion.id)
        .where(
            IdentityAssertion.client_id == client_id,
            IdentityAssertion.evidence.contains([{"key_id": str(key_id)}]),
        )
        .exists()
    )


def has_evidence(
    session: Session, client_id: UUID, person_id: UUID, *, excluding_merge: UUID | None = None
) -> bool:
    """Whether a person keeps independent evidence (R006-25).

    Only active links and owned keys of the person count, and with excluding_merge every key or
    link that records that merge is ignored. A key counts only while a surviving assertion
    presents it. Candidate references and financial associations never count.
    """

    def independent(column):
        return (
            column.is_(None)
            if excluding_merge is None
            else or_(column.is_(None), column != excluding_merge)
        )

    if session.scalar(
        select(IdentityLink.id)
        .where(
            IdentityLink.client_id == client_id,
            IdentityLink.status == "active",
            IdentityLink.subject_id == person_id,
            independent(IdentityLink.merge_id) if excluding_merge is not None else True,
        )
        .limit(1)
    ):
        return True
    keys = session.scalars(
        select(IdentityKey.id).where(
            IdentityKey.client_id == client_id,
            IdentityKey.status == "owned",
            IdentityKey.subject_id == person_id,
            independent(IdentityKey.merge_id) if excluding_merge is not None else True,
        )
    )
    return any(
        session.scalar(select(_assertions_presenting(session, client_id, key))) for key in keys
    )


def reevaluate_dependents(
    session: Session,
    client_id: UUID,
    edge: IdentityMerge,
    journey: Journey,
    *,
    lost: UUID | None = None,
) -> dict[str, list[str]]:
    """Re-evaluate the keys and links that record a merge (design sections 10.1 and 10.3).

    Each item is decided with R5 over its anchoring evidence with every key of this merge
    unavailable: an item whose remaining owned anchors name exactly one original owner stays
    with that owner; otherwise a key becomes contested (unmerged) and a link ambiguous. A lost
    participant still counts as an owner, and is then omitted from the listed candidates.
    """
    moved: dict[str, list[str]] = {"keys": [], "links": []}
    dependent_keys = list(
        session.scalars(
            select(IdentityKey)
            .where(IdentityKey.client_id == client_id, IdentityKey.merge_id == edge.id)
            .order_by(IdentityKey.id)
            .with_for_update()
        )
    )
    dependent_ids = {key.id for key in dependent_keys}

    def anchors(identifiers: Iterable[UUID]) -> set[UUID]:
        ids = [item for item in identifiers if item not in dependent_ids]
        if not ids:
            return set()
        return set(
            session.scalars(
                select(IdentityKey.subject_id).where(
                    IdentityKey.id.in_(ids),
                    IdentityKey.status == "owned",
                    or_(IdentityKey.merge_id.is_(None), IdentityKey.merge_id != edge.id),
                )
            )
        )

    def listed(owners: Iterable[UUID]) -> list[UUID]:
        return sorted({item for item in owners if item != lost}, key=str)

    for key in dependent_keys:
        owners = anchors(key.anchor_key_ids or ())
        if len(owners) == 1:
            (owner,) = owners
            key.subject_id, key.merge_id, key.original_owner_ids = owner, None, [owner]
        else:
            candidates = listed(key.original_owner_ids or [edge.survivor_id, edge.merged_id])
            key.status, key.contested_reason, key.subject_id = "contested", "unmerged", None
            key.candidate_ids, key.merge_id = candidates, None
            moved["keys"].append(str(key.id))
    session.flush()
    for link in session.scalars(
        select(IdentityLink)
        .where(IdentityLink.client_id == client_id, IdentityLink.merge_id == edge.id)
        .order_by(IdentityLink.id)
        .with_for_update()
    ):
        owners = anchors(link.key_ids or ())
        previous = link.subject_id
        if len(owners) == 1:
            (owner,) = owners
            link.subject_id, link.merge_id, link.original_owner_ids = owner, None, [owner]
        else:
            candidates = listed(link.original_owner_ids or [edge.survivor_id, edge.merged_id])
            link.status, link.subject_id, link.provisional_from = "ambiguous", None, None
            link.candidate_ids, link.merge_id = candidates or [edge.survivor_id], None
            moved["links"].append(str(link.id))
        if link.assertion_ref is not None:
            session.execute(
                update(IdentityAssertion)
                .where(IdentityAssertion.id == link.assertion_ref)
                .values(subject_id=link.subject_id)
            )
        for person in (previous, link.subject_id):
            journey.touch(person, "unmerged")
    session.execute(
        update(IdentityAssertion)
        .where(IdentityAssertion.client_id == client_id, IdentityAssertion.merge_id == edge.id)
        .values(merge_id=None)
    )
    session.flush()
    return moved


def _closed_edges(client_id: UUID, person_id: UUID):
    return select(IdentityMerge.id).where(
        IdentityMerge.client_id == client_id,
        IdentityMerge.kind == "merge",
        IdentityMerge.status != "active",
        or_(IdentityMerge.survivor_id == person_id, IdentityMerge.merged_id == person_id),
    )


def _member(person_id: UUID, column):
    return literal(person_id, Uuid) == any_(column)


CLOSURE_REASONS = {
    "expired": "participant_expired",
    "withdrawn": "participant_withdrew",
    "erased": "participant_erased",
}


def remove_person(
    session: Session, client_id: UUID, person_id: UUID, kind: str, journey: Journey, now: datetime
) -> None:
    """Remove a person that lost its last evidence, closing an active merge edge first."""
    edge = active_edge(session, person_id)
    if edge is not None:
        other = edge.merged_id if edge.survivor_id == person_id else edge.survivor_id
        edge.status, edge.closed_reason, edge.ended_at = "closed", CLOSURE_REASONS[kind], now
        session.flush()
        merged = session.get(IdentitySubject, edge.merged_id)
        if merged is not None and merged.merged_into_id is not None:
            merged.status, merged.merged_into_id = "active", None
            session.flush()
        reevaluate_dependents(session, client_id, edge, journey, lost=person_id)
        remaining = session.get(IdentitySubject, other)
        if remaining is not None:
            remaining.version += 1
            journey.touched.pop(other, None)
            journey._record([(other, "merge_closed")])
    journey.final(person_id, kind)
    session.execute(
        update(IdentityLink)
        .where(IdentityLink.client_id == client_id, _member(person_id, IdentityLink.candidate_ids))
        .values(candidate_ids=func.array_remove(IdentityLink.candidate_ids, person_id))
    )
    session.execute(
        update(IdentityAssertion)
        .where(
            IdentityAssertion.client_id == client_id,
            _member(person_id, IdentityAssertion.candidate_ids),
        )
        .values(candidate_ids=func.array_remove(IdentityAssertion.candidate_ids, person_id))
    )
    session.execute(
        update(IdentityKey)
        .where(IdentityKey.client_id == client_id, _member(person_id, IdentityKey.candidate_ids))
        .values(candidate_ids=func.array_remove(IdentityKey.candidate_ids, person_id))
    )
    # An ambiguous segment left without any candidate names nobody: it becomes neutral.
    session.execute(
        update(IdentityLink)
        .where(
            IdentityLink.client_id == client_id,
            IdentityLink.status == "ambiguous",
            func.cardinality(IdentityLink.candidate_ids) == 0,
        )
        .values(
            status="neutral", original_owner_ids=[], key_ids=[], merge_id=None, assertion_ref=None
        )
    )
    session.execute(
        delete(IdentityLink).where(
            IdentityLink.client_id == client_id, IdentityLink.subject_id == person_id
        )
    )
    # An assertion's subject_id always equals its link's owner (reevaluate_dependents keeps
    # them in step), so no surviving link references these rows.
    session.execute(
        delete(IdentityAssertion).where(
            IdentityAssertion.client_id == client_id,
            IdentityAssertion.subject_id == person_id,
            ~select(IdentityLink.id)
            .where(IdentityLink.assertion_ref == IdentityAssertion.id)
            .exists(),
        )
    )
    session.execute(
        delete(IdentityKey).where(
            IdentityKey.client_id == client_id, IdentityKey.subject_id == person_id
        )
    )
    if kind == "erased":
        # Erasure deletes the closed ledger rows naming the person (design section 7.2).
        session.execute(
            update(IdentityAssertion)
            .where(
                IdentityAssertion.client_id == client_id,
                IdentityAssertion.merge_id.in_(_closed_edges(client_id, person_id)),
            )
            .values(merge_id=None)
        )
        session.execute(
            delete(IdentityMerge).where(
                IdentityMerge.client_id == client_id,
                IdentityMerge.kind == "unmerge",
                IdentityMerge.reverses_id.in_(_closed_edges(client_id, person_id)),
            )
        )
        session.execute(
            delete(IdentityMerge).where(
                IdentityMerge.id.in_(_closed_edges(client_id, person_id)),
                ~select(IdentityKey.id).where(IdentityKey.merge_id == IdentityMerge.id).exists(),
                ~select(IdentityLink.id).where(IdentityLink.merge_id == IdentityMerge.id).exists(),
            )
        )
    session.execute(
        update(IdentitySubject)
        .where(IdentitySubject.client_id == client_id, IdentitySubject.merged_into_id == person_id)
        .values(status="active", merged_into_id=None)
    )
    session.execute(
        delete(IdentitySubject).where(
            IdentitySubject.client_id == client_id, IdentitySubject.id == person_id
        )
    )
    session.flush()


def remove_orphan_keys(session: Session, client_id: UUID, key_ids: Iterable[UUID]) -> None:
    """Delete contested keys that no surviving assertion presents any longer."""
    for key_id in sorted(set(key_ids), key=str):
        key = session.get(IdentityKey, key_id)
        if key is None or key.status != "contested":
            continue
        if not session.scalar(select(_assertions_presenting(session, client_id, key_id))):
            session.delete(key)
    session.flush()


def cleanup_people(
    session: Session,
    client_id: UUID,
    people: Iterable[UUID],
    kind: str,
    journey: Journey,
    now: datetime,
) -> list[UUID]:
    """Remove persons left without independent evidence; touch the others. Returns removed."""
    removed: list[UUID] = []
    for person_id in sorted(set(people), key=str):
        if session.get(IdentitySubject, person_id) is None:
            continue
        edge = active_edge(session, person_id)
        survives = (
            has_evidence(
                session, client_id, person_id, excluding_merge=edge.id if edge is not None else None
            )
            if edge is not None
            else has_evidence(session, client_id, person_id)
        )
        if survives:
            journey.touch(person_id, "unlinked")
            continue
        remove_person(session, client_id, person_id, kind, journey, now)
        removed.append(person_id)
    return removed


def _people_of_links(links: Iterable[IdentityLink]) -> set[UUID]:
    people: set[UUID] = set()
    for link in links:
        if link.status == "active":
            people.add(link.subject_id)
            people.update(link.original_owner_ids or ())
    return people


def _keys_of_assertions(assertions: Iterable[IdentityAssertion]) -> set[UUID]:
    return {
        UUID(item["key_id"])
        for assertion in assertions
        for item in (assertion.evidence or [])
        if item.get("key_id")
    }


def subject_has_identity(session: Session, subject_id: UUID) -> bool:
    return any(
        session.scalar(select(model.id).where(column == subject_id).limit(1)) is not None
        for model, column in (
            (IdentityLink, IdentityLink.collection_subject_id),
            (IdentityAssertion, IdentityAssertion.collection_subject_id),
            (IdentityHandoff, IdentityHandoff.collection_subject_id),
        )
    )


def drop_subject_evidence(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    subject: CollectionSubject,
    kind: Literal["withdrawn", "erased", "expired"],
    journey: Journey,
    now: datetime,
) -> list[UUID]:
    """Delete a collection subject's segments, assertion evidence and handoffs (W1, token-holder
    erasure and lifecycle expiry), raise its floor, then remove keys and persons left without
    evidence. Retry receipts are untouched. Returns the removed persons."""
    links = subject_links(session, subject.id, lock=True)
    assertions = list(
        session.scalars(
            select(IdentityAssertion).where(IdentityAssertion.collection_subject_id == subject.id)
        )
    )
    people = _people_of_links(links) | {
        assertion.subject_id for assertion in assertions if assertion.subject_id is not None
    }
    keys = _keys_of_assertions(assertions)
    for person in people:
        journey.touch(person, "unlinked")
    session.execute(delete(IdentityLink).where(IdentityLink.collection_subject_id == subject.id))
    session.execute(
        delete(IdentityAssertion).where(IdentityAssertion.collection_subject_id == subject.id)
    )
    session.execute(
        delete(IdentityHandoff).where(IdentityHandoff.collection_subject_id == subject.id)
    )
    if links or assertions:
        _raise_floor(subject, now)
    session.flush()
    removed = cleanup_people(session, client_id, people, kind, journey, now)
    remove_orphan_keys(session, client_id, keys)
    return removed


# W1 (design section 6): withdrawing or explicitly denying identity_link on a collection subject
# removes its identity evidence in the consent transaction. Called by record_consent.
def withdraw_identity(
    session: Session, agency_id: UUID, client_id: UUID, subject: CollectionSubject, now: datetime
) -> None:
    journey = Journey(session, agency_id, client_id, now)
    drop_subject_evidence(session, agency_id, client_id, subject, "withdrawn", journey, now)
    journey.flush()


# ---------------------------------------------------------------------------------------------
# Erasure holds settled by deletions outside a person erasure (design section 7.2).


def settle_holds(
    session: Session,
    client_id: UUID,
    event_ids: Sequence[UUID],
    state: Literal["erased_elsewhere", "expired"],
    now: datetime,
) -> None:
    """Settle every hold on these events and complete each request whose last hold settled."""
    if not event_ids:
        return
    requests = set(
        session.scalars(
            update(IdentityErasureHold)
            .where(
                IdentityErasureHold.client_id == client_id,
                IdentityErasureHold.state == "held",
                IdentityErasureHold.collected_event_id.in_(list(event_ids)),
            )
            .values(state=state, collected_event_id=None, settled_at=now)
            .returning(IdentityErasureHold.deletion_request_id)
        )
    )
    for request_id in sorted(requests, key=str):
        complete_if_settled(session, client_id, request_id, now)


def complete_if_settled(session: Session, client_id: UUID, request_id: UUID, now: datetime) -> bool:
    remaining = session.scalar(
        select(IdentityErasureHold.id)
        .where(
            IdentityErasureHold.client_id == client_id,
            IdentityErasureHold.deletion_request_id == request_id,
            IdentityErasureHold.state == "held",
        )
        .limit(1)
    )
    if remaining is not None:
        return False
    row = session.execute(
        select(SubjectDeletionRequest.status, SubjectDeletionRequest.target_outcomes)
        .where(SubjectDeletionRequest.id == request_id)
        .with_for_update()
    ).one_or_none()
    if row is None or row.status != RequestStatus.ON_HOLD.value:
        return False
    targets = dict(row.target_outcomes or {})
    targets["unresolved_events"] = TargetStatus.DONE.value
    status = deletion.transition(RequestStatus.ON_HOLD, RequestStatus.IN_PROGRESS)
    final = deletion.outcome({name: TargetStatus(value) for name, value in targets.items()})
    if final is None:
        return False
    status = deletion.transition(status, final)
    session.execute(
        update(SubjectDeletionRequest)
        .where(SubjectDeletionRequest.id == request_id)
        .values(status=status.value, completed_at=now, target_outcomes=targets)
    )
    return True


# ---------------------------------------------------------------------------------------------
# 004 hooks: an assigned event added, upgraded or removed changes its owner's journey.


def on_event_changed(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    subject_id: UUID,
    received_at: datetime,
    occurred_at: datetime,
    now: datetime,
) -> None:
    if (
        session.scalar(
            select(IdentityLink.id).where(IdentityLink.collection_subject_id == subject_id).limit(1)
        )
        is None
    ):
        return
    _, segments = subject_segments(session, subject_id, now)
    owner = owner_of(EventTimes(received_at, occurred_at), segments)
    if owner is not None:
        journey = Journey(session, agency_id, client_id, now)
        journey.touch(owner, "events_changed")
        journey.flush()


# ---------------------------------------------------------------------------------------------
# Browser handoff (design section 8, D3).


def issue_handoff(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    *,
    subject_token: str,
    challenge: str,
    lock: Callable[[], datetime],
) -> tuple[str, datetime] | None:
    """Issue a one-time code for a browser-issued subject with effective identity_link, bound
    to one unused backend challenge; None for every refusal (the same public answer)."""
    now = lock()
    subject = session.scalar(
        select(CollectionSubject)
        .where(
            CollectionSubject.client_id == client_id,
            CollectionSubject.token_digest == digest(subject_token),
        )
        .with_for_update(key_share=True)
    )
    if subject is None or subject.issuance_channel != "browser":
        return None
    consent = identity_consent(session, subject.id, now)
    if consent.grant_record_id is None:
        return None
    challenge_digest = digest(challenge)
    if session.scalar(
        select(IdentityHandoff.id).where(
            IdentityHandoff.client_id == client_id,
            IdentityHandoff.challenge_digest == challenge_digest,
        )
    ):
        return None
    code = "ihc_" + new_token()
    expires_at = now + HANDOFF_LIFETIME
    session.add(
        IdentityHandoff(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            collection_subject_id=subject.id,
            code_digest=digest(code),
            challenge_digest=challenge_digest,
            identity_consent_receipt_id=consent.grant_record_id,
            expires_at=expires_at,
            created_at=now,
        )
    )
    session.flush()
    return code, expires_at


# ---------------------------------------------------------------------------------------------
# Assertions (design sections 4.2 and 12.2).


@dataclass(frozen=True)
class AssertedIdentifier:
    canonical: Canonical
    method: str
    verified_at: datetime


@dataclass(frozen=True)
class AssertionRequest:
    assertion_id: UUID
    identifiers: tuple[AssertedIdentifier, ...]
    handoff: str | None = None
    challenge: str | None = None
    subject_token: str | None = None
    identity_consent_receipt_id: UUID | None = None

    def proof_parts(self) -> list[str]:
        if self.handoff is not None and self.challenge is not None:
            return ["handoff", digest(self.handoff), digest(self.challenge)]
        if self.subject_token is not None and self.identity_consent_receipt_id is not None:
            return ["token", digest(self.subject_token), str(self.identity_consent_receipt_id)]
        raise IdentifierRejected("request_invalid")


@dataclass(frozen=True)
class AssertionResult:
    status: Literal["accepted", "duplicate", "conflict", "rejected"]
    http: int
    reason: str | None = None
    # Internal only (tests and diagnostics); never part of a response.
    outcome: str | None = None
    internal_reason: str | None = None


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="microseconds")


def fingerprint(
    secret: bytes,
    client_id: UUID,
    request: AssertionRequest,
    credential_id: UUID,
    keys: Sequence[bytes],
) -> bytes:
    evidence = [
        [
            item.canonical.kind,
            item.canonical.normalizer,
            key.hex(),
            item.method,
            _iso(item.verified_at),
        ]
        for item, key in zip(request.identifiers, keys, strict=True)
    ]
    message = json.dumps(
        [str(request.assertion_id), str(credential_id), evidence, request.proof_parts()],
        separators=(",", ":"),
    )
    return keyed_identifier(secret, FINGERPRINT_DOMAIN, client_id, "fingerprint", message)


def _tombstones(
    session: Session, keys: TombstoneKeyring, client_id: UUID, match_type: str, value: str
) -> list[deletion.Tombstone]:
    rows = session.scalars(
        select(StoredTombstone).where(
            StoredTombstone.client_id == client_id,
            StoredTombstone.match_type == match_type,
            StoredTombstone.match_key.in_(keys.candidates(client_id, match_type, value)),
        )
    )
    return [
        deletion.Tombstone(
            row.id,
            row.agency_id,
            row.client_id,
            deletion.ScopeKind(row.scope_kind),
            row.match_type,
            row.match_key,
            row.match_key_id,
            row.deletion_request_id,
            row.effective_at,
            row.objected,
        )
        for row in rows
    ]


@dataclass
class _Proof:
    subject: CollectionSubject
    handoff: IdentityHandoff | None
    grant_record_id: UUID
    grant_received_at: datetime
    consent: IdentityConsent


def _resolve_proof(
    session: Session, client_id: UUID, request: AssertionRequest, now: datetime
) -> _Proof | None:
    handoff = None
    if request.handoff is not None:
        handoff = session.scalar(
            select(IdentityHandoff)
            .where(
                IdentityHandoff.client_id == client_id,
                IdentityHandoff.code_digest == digest(request.handoff),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            handoff is None
            or handoff.consumed_at is not None
            or handoff.expires_at <= now
            or handoff.challenge_digest != digest(request.challenge or "")
        ):
            return None
        subject = session.scalar(
            select(CollectionSubject)
            .where(CollectionSubject.id == handoff.collection_subject_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if subject is None or subject.issuance_channel != "browser":
            return None
        expected = handoff.identity_consent_receipt_id
    else:
        subject = session.scalar(
            select(CollectionSubject)
            .where(
                CollectionSubject.client_id == client_id,
                CollectionSubject.token_digest == digest(request.subject_token or ""),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if subject is None or subject.issuance_channel != "server":
            return None
        expected = request.identity_consent_receipt_id
    consent = identity_consent(session, subject.id, now)
    if consent.grant_record_id is None or consent.grant_record_id != expected:
        return None
    grant = session.get(StoredConsentRecord, consent.grant_record_id)
    return _Proof(subject, handoff, consent.grant_record_id, grant.received_at, consent)


def _store_receipt(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    request: AssertionRequest,
    print_: bytes,
    receipt: IdentityAssertionReceipt | None,
    now: datetime,
) -> None:
    # R006-26: an expired receipt is replaced in place (fingerprint and window); a live one is
    # never extended, and nothing is inserted against the existing unique key.
    if receipt is not None:
        receipt.fingerprint, receipt.received_at = print_, now
        receipt.expires_at = now + RETRY_WINDOW
    else:
        session.add(
            IdentityAssertionReceipt(
                id=uuid4(),
                agency_id=agency_id,
                client_id=client_id,
                assertion_id=request.assertion_id,
                fingerprint=print_,
                received_at=now,
                expires_at=now + RETRY_WINDOW,
            )
        )
    session.flush()


def _count(session: Session, agency_id: UUID, client_id: UUID, now: datetime, outcome, reason):
    from app.services.collection import count

    count(session, agency_id, client_id, now.date(), "identity", outcome, reason)


def process_assertion(
    session: Session,
    settings: Settings,
    agency_id: UUID,
    client_id: UUID,
    credential_id: UUID,
    request: AssertionRequest,
    *,
    lock: Callable[[], datetime],
) -> AssertionResult:
    """Apply one trusted assertion (design section 4.2); validation already ran (step 1)."""
    tombstone_keys = settings.tombstone_keys()
    token_keys = settings.token_keys()
    if tombstone_keys is None or token_keys is None:
        raise IdentityError("identity_not_configured", 503)
    request.proof_parts()  # request_invalid before the lock
    now = lock()  # step 2: client lock, database clock, live sender scope
    secret = matching_key(session, token_keys, agency_id, client_id, create=True)
    keys = [identity_key(secret, client_id, item.canonical) for item in request.identifiers]
    print_ = fingerprint(secret, client_id, request, credential_id, keys)
    receipt = session.scalar(
        select(IdentityAssertionReceipt)
        .where(
            IdentityAssertionReceipt.client_id == client_id,
            IdentityAssertionReceipt.assertion_id == request.assertion_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if receipt is not None and receipt.expires_at > now:  # step 3: live receipt only
        if receipt.fingerprint == print_:
            _count(session, agency_id, client_id, now, "duplicate", "retry_receipt")
            return AssertionResult("duplicate", 200)
        _count(session, agency_id, client_id, now, "conflict", "retry_receipt")
        return AssertionResult("conflict", 409)
    for item in request.identifiers:  # step 4
        if not now - FRESHNESS <= item.verified_at <= now + FUTURE_SKEW:
            _count(session, agency_id, client_id, now, "rejected", "verification_stale")
            return AssertionResult("rejected", 422, "verification_stale")
    proof = _resolve_proof(session, client_id, request, now)  # steps 5-6
    if proof is None:
        _count(session, agency_id, client_id, now, "rejected", "proof_invalid")
        return AssertionResult("rejected", 422, "proof_invalid")
    subject = proof.subject
    journey = Journey(session, agency_id, client_id, now)
    # Step 7: from here on, the request is acknowledged as accepted.
    if proof.handoff is not None:
        proof.handoff.consumed_at = now
    _store_receipt(session, agency_id, client_id, request, print_, receipt, now)
    existing = session.scalar(
        select(IdentityAssertion.id).where(
            IdentityAssertion.client_id == client_id,
            IdentityAssertion.assertion_id == request.assertion_id,
        )
    )
    replay = _tombstones(
        session, tombstone_keys, client_id, "assertion_id", str(request.assertion_id)
    )
    suppressed: str | None = None
    neutral = False
    if existing is not None:
        suppressed = "assertion_id_reused"
    elif replay:
        same = _tombstones(session, tombstone_keys, client_id, "assertion_fp", print_.hex())
        suppressed = "replay_before_deletion" if same else "assertion_id_reused"
    else:
        for key in keys:
            gate = deletion.admission(
                subject_tombstones=_tombstones(
                    session, tombstone_keys, client_id, "identity_key", key.hex()
                ),
                replay_tombstones=[],
                consent_received_at=proof.grant_received_at,
            )
            if not gate.allowed:
                suppressed, neutral = gate.reason, True
                break
    if suppressed is not None:
        if existing is None:
            session.add(
                IdentityAssertion(
                    id=uuid4(),
                    agency_id=agency_id,
                    client_id=client_id,
                    assertion_id=request.assertion_id,
                    credential_id=credential_id,
                    collection_subject_id=subject.id,
                    fingerprint=print_,
                    proof="handoff" if proof.handoff is not None else "token",
                    received_at=now,
                    outcome="suppressed",
                    reason=suppressed,
                )
            )
        if neutral:
            _neutral_boundary(session, agency_id, client_id, subject, proof, journey, now)
        journey.flush()
        _count(session, agency_id, client_id, now, "suppressed", suppressed)
        return AssertionResult("accepted", 201, outcome="suppressed", internal_reason=suppressed)
    outcome = _apply(
        session, agency_id, client_id, credential_id, request, keys, print_, proof, journey, now
    )
    journey.flush()
    _count(session, agency_id, client_id, now, "accepted", outcome)
    return AssertionResult("accepted", 201, outcome=outcome)


def _neutral_boundary(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    subject: CollectionSubject,
    proof: _Proof,
    journey: Journey,
    now: datetime,
) -> None:
    links = subject_links(session, subject.id, lock=True)
    close_ended_segments(session, subject, links, proof.consent.periods)
    _close_open(session, subject, links, None, "neutral_boundary", journey, now)
    _mark_shared(session, subject, links, journey, now)
    session.add(
        IdentityLink(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            collection_subject_id=subject.id,
            status="neutral",
            asserted_at=now,
            eligible_from=now,
            grant_started_at=proof.consent.current.start if proof.consent.current else now,
        )
    )
    session.flush()


def _owner_set(link: IdentityLink) -> frozenset[UUID]:
    if link.status != "active":
        return frozenset()
    return frozenset(link.original_owner_ids or ([link.subject_id] if link.subject_id else []))


def _close_open(
    session: Session,
    subject: CollectionSubject,
    links: Iterable[IdentityLink],
    keep: frozenset[UUID] | None,
    reason: str,
    journey: Journey,
    now: datetime,
) -> None:
    """Close every open segment except an owned one of the same original owners (continuation)."""
    for link in links:
        if link.eligible_until is not None:
            continue
        if keep is not None and link.status == "active" and _owner_set(link) == keep:
            continue
        link.eligible_until, link.closed_reason = now, reason
        _raise_floor(subject, now)
        journey.touch(link.subject_id, "events_changed")
    session.flush()


def _mark_shared(
    session: Session,
    subject: CollectionSubject,
    links: Iterable[IdentityLink],
    journey: Journey,
    now: datetime,
) -> None:
    """Record the write-once shared marker and retract every provisional prefix (R006-27)."""
    if subject.identity_shared_at is None:
        subject.identity_shared_at = now
    for link in links:
        if link.provisional_from is not None:
            link.provisional_from = None
            journey.touch(link.subject_id, "unlinked")
    session.flush()


def _evidence_item(key: IdentityKey, item: AssertedIdentifier, owner: UUID | None, state: str):
    return {
        "key_id": str(key.id),
        "kind": item.canonical.kind,
        "method": item.method,
        "verified_at": _iso(item.verified_at),
        "owner_id": str(owner) if owner else None,
        "state": state,
    }


def _apply(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    credential_id: UUID,
    request: AssertionRequest,
    keys: list[bytes],
    print_: bytes,
    proof: _Proof,
    journey: Journey,
    now: datetime,
) -> str:
    subject = proof.subject
    # Step 8: classify every asserted key by its current owner, locked in key order.
    order = sorted(
        range(len(keys)),
        key=lambda index: (request.identifiers[index].canonical.kind, keys[index]),
    )
    rows: dict[int, IdentityKey | None] = {}
    for index in order:
        rows[index] = session.scalar(
            select(IdentityKey)
            .where(
                IdentityKey.client_id == client_id,
                IdentityKey.kind == request.identifiers[index].canonical.kind,
                IdentityKey.key_bytes == keys[index],
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    asserted: list[matching.AssertedKey] = []
    roots: set[UUID] = set()
    for index, item in enumerate(request.identifiers):
        row = rows[index]
        if row is None:
            asserted.append(matching.AssertedKey(index, item.canonical.kind, "new"))
        elif row.status == "contested":
            asserted.append(
                matching.AssertedKey(
                    index, item.canonical.kind, "contested", candidates=frozenset(row.candidate_ids)
                )
            )
        else:
            root = root_of(session, row.subject_id)
            roots.add(root)
            owners = frozenset(row.original_owner_ids or [row.subject_id])
            asserted.append(
                matching.AssertedKey(
                    index,
                    item.canonical.kind,
                    "owned",
                    owner=row.subject_id,
                    root=root,
                    owners=owners if row.merge_id else frozenset([row.subject_id]),
                    merge_id=row.merge_id,
                )
            )
    holds: dict[UUID, bool] = {}
    edges: dict[UUID, UUID] = {}
    for root in roots:
        group = [
            root,
            *session.scalars(
                select(IdentitySubject.id).where(IdentitySubject.merged_into_id == root)
            ),
        ]
        holds[root] = (
            session.scalar(
                select(IdentityKey.id)
                .where(
                    IdentityKey.client_id == client_id,
                    IdentityKey.kind == "customer_ref",
                    IdentityKey.status == "owned",
                    IdentityKey.subject_id.in_(group),
                )
                .limit(1)
            )
            is not None
        )
        edge = session.scalar(
            select(IdentityMerge.id).where(
                IdentityMerge.client_id == client_id,
                IdentityMerge.status == "active",
                IdentityMerge.survivor_id == root,
            )
        )
        if edge is not None:
            edges[root] = edge
    decision = matching.decide(asserted, root_holds_reference=holds, edge_of=edges)
    # Step 9: the device rule.
    links = subject_links(session, subject.id, lock=True)
    close_ended_segments(session, subject, links, proof.consent.periods)
    person_id: UUID | None = decision.person
    if decision.create_new:
        person = IdentitySubject(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            status="active",
            version=1,
            journey_revision=0,
            created_at=now,
            updated_at=now,
            last_evidence_at=now,
        )
        session.add(person)
        session.flush()
        person_id = person.id
    owners = (
        frozenset([person_id])
        if decision.create_new
        else (decision.original_owners if decision.outcome != "ambiguous" else frozenset())
    )
    if decision.outcome == "ambiguous":
        _close_open(session, subject, links, None, "ambiguous", journey, now)
        _mark_shared(session, subject, links, journey, now)
    else:
        keep = owners if decision.merge_id is not None else frozenset([person_id])
        previous = set().union(*(_owner_set(link) for link in links)) if links else set()
        _close_open(session, subject, links, keep, "switched", journey, now)
        if any(link.status != "active" for link in links) or (previous - keep):
            _mark_shared(session, subject, links, journey, now)
    # Step 10: commit evidence, keys and the link.
    evidence: list[dict[str, Any]] = []
    key_rows: list[IdentityKey] = []
    anchor_ids = [
        rows[key.index].id
        for key in asserted
        if key.state == "owned" and key.index not in decision.contest
    ]
    for key in asserted:
        item = request.identifiers[key.index]
        row = rows[key.index]
        if key.state == "new":
            if decision.outcome == "ambiguous":
                continue
            row = IdentityKey(
                id=uuid4(),
                agency_id=agency_id,
                client_id=client_id,
                kind=item.canonical.kind,
                key_bytes=keys[key.index],
                key_version=KEY_VERSION,
                normalizer=item.canonical.normalizer,
                subject_id=person_id,
                status="owned",
                candidate_ids=[],
                merge_id=decision.merge_id,
                original_owner_ids=sorted(owners, key=str) if decision.merge_id else [person_id],
                anchor_key_ids=anchor_ids,
                method=item.method,
                first_verified_at=item.verified_at,
                last_verified_at=item.verified_at,
                created_at=now,
            )
            session.add(row)
            session.flush()
            evidence.append(_evidence_item(row, item, None, "new"))
        elif key.state == "owned" and key.index in decision.contest:
            previous_owner = row.subject_id
            journey.touch(previous_owner, "contested")
            row.status, row.contested_reason, row.subject_id = "contested", "shared", None
            row.candidate_ids = sorted({previous_owner, person_id} - {None}, key=str)
            row.merge_id, row.last_verified_at = None, max(row.last_verified_at, item.verified_at)
            evidence.append(_evidence_item(row, item, previous_owner, "contested"))
        elif key.state == "owned":
            row.last_verified_at = max(row.last_verified_at, item.verified_at)
            row.method = item.method
            evidence.append(_evidence_item(row, item, row.subject_id, "owned"))
        else:
            if person_id is not None and decision.outcome != "ambiguous":
                row.candidate_ids = sorted(set(row.candidate_ids) | {person_id}, key=str)
            row.last_verified_at = max(row.last_verified_at, item.verified_at)
            evidence.append(_evidence_item(row, item, None, "contested"))
        key_rows.append(row)
    session.flush()
    candidates = list(decision.candidates)
    assertion = IdentityAssertion(
        id=uuid4(),
        agency_id=agency_id,
        client_id=client_id,
        assertion_id=request.assertion_id,
        credential_id=credential_id,
        collection_subject_id=subject.id,
        fingerprint=print_,
        proof="handoff" if proof.handoff is not None else "token",
        received_at=now,
        outcome=decision.outcome,
        evidence=evidence,
        candidate_ids=candidates,
        subject_id=person_id if decision.outcome != "ambiguous" else None,
        merge_id=decision.merge_id,
    )
    session.add(assertion)
    session.flush()
    period = proof.consent.current
    grant_start = period.start if period is not None else now
    if decision.outcome == "ambiguous":
        session.add(
            IdentityLink(
                id=uuid4(),
                agency_id=agency_id,
                client_id=client_id,
                collection_subject_id=subject.id,
                status="ambiguous",
                candidate_ids=candidates,
                assertion_ref=assertion.id,
                asserted_at=now,
                eligible_from=now,
                original_owner_ids=candidates,
                key_ids=[row.id for row in key_rows],
                grant_started_at=grant_start,
            )
        )
        session.flush()
        return "ambiguous"
    provisional = None
    first_in_period = not any(
        link.status == "active" and link.asserted_at >= grant_start for link in links
    )
    if (
        subject.identity_shared_at is None
        and (subject.identity_floor_at is None or subject.identity_floor_at <= grant_start)
        and first_in_period
        and period is not None
    ):
        provisional = grant_start
    session.add(
        IdentityLink(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            collection_subject_id=subject.id,
            status="active",
            subject_id=person_id,
            assertion_ref=assertion.id,
            asserted_at=now,
            eligible_from=now,
            provisional_from=provisional,
            merge_id=decision.merge_id,
            original_owner_ids=sorted(owners, key=str),
            key_ids=[row.id for row in key_rows if row.status == "owned"],
            grant_started_at=grant_start,
        )
    )
    person = session.get(IdentitySubject, person_id)
    person.last_evidence_at = now
    journey.touch(person_id, "linked")
    session.flush()
    return decision.outcome


# ---------------------------------------------------------------------------------------------
# Journeys (design section 9.2): the assigned events of one person and its merge group.


def person_group(session: Session, client_id: UUID, person_id: UUID) -> list[UUID]:
    """The visible root of a person and every member merged into it."""
    root = root_of(session, person_id)
    members = session.scalars(
        select(IdentitySubject.id).where(
            IdentitySubject.client_id == client_id, IdentitySubject.merged_into_id == root
        )
    )
    return [root, *sorted(members, key=str)]


def journey_events(
    session: Session, client_id: UUID, person_id: UUID, now: datetime
) -> list[tuple[CollectedEvent, IdentityLink]]:
    """Each event assigned to the person's group once, with the segment that assigns it, in
    timeline order (occurred_at, first_received_at, event_id). Marked events never appear."""
    group = set(person_group(session, client_id, person_id))
    subjects = sorted(
        set(
            session.scalars(
                select(IdentityLink.collection_subject_id).where(
                    IdentityLink.client_id == client_id,
                    IdentityLink.status == "active",
                    IdentityLink.subject_id.in_(group),
                )
            )
        ),
        key=str,
    )
    entries: list[tuple[CollectedEvent, IdentityLink]] = []
    for subject_id in subjects:
        links, segments = subject_segments(session, subject_id, now)
        events = session.scalars(
            select(CollectedEvent).where(
                CollectedEvent.client_id == client_id,
                CollectedEvent.subject_id == subject_id,
                CollectedEvent.identity_excluded_at.is_(None),
            )
        )
        for event in events:
            owner = owner_of(event_times(event), segments)
            if owner not in group:
                continue
            link = next(
                link
                for link, segment in zip(links, segments, strict=True)
                if segment.status == "active"
                and segment.owner == owner
                and segment.covers(event.first_received_at)
            )
            entries.append((event, link))
    entries.sort(
        key=lambda item: (item[0].occurred_at, item[0].first_received_at, str(item[0].event_id))
    )
    return entries
