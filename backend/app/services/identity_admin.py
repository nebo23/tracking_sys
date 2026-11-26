"""Identity administration and person-level reads (specification 006, D-075; design 7, 9, 10).

Administration (merge, reversal, person erasure and its resolution, the review queue) is
Owner/Admin only. Audited writes take the agency row lock first, then the 004 client privacy
lock; under the privacy lock they read the database clock and lock persons in ID order. Reads
need identity:read (Owner/Admin, or Analyst/ClientViewer with can_view_identities); service
keys have no identity access in v1. Responses never contain an identifier value, a mask, a
token or key bytes. Purchase claims (004 purchase_signal) appear only for readers who also hold
finance:read, and financial customer qualification follows the same double permission.
"""

import base64
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.config import Settings
from app.identity.normalize import IdentifierRejected, canonical
from app.identity.segments import classify
from app.models import (
    CollectedEvent,
    CollectionSubject,
    IdentityAssertion,
    IdentityChange,
    IdentityErasureHold,
    IdentityKey,
    IdentityLink,
    IdentityMerge,
    IdentitySubject,
    LinkCampaign,
    LinkContentReference,
    ManagedLink,
    RevenueIdentityBinding,
    StoredTombstone,
    SubjectDeletionRequest,
)
from app.privacy import deletion
from app.privacy.deletion import RequesterKind, RequestStatus, TargetStatus
from app.services.collection import (
    erase_subject_row,
    lock_client,
    require_token_keys,
    require_tombstone_keys,
)
from app.services.identity import (
    REMOVAL_KINDS,
    IdentityError,
    Journey,
    _raise_floor,
    active_edge,
    complete_if_settled,
    event_times,
    identity_key,
    journey_events,
    matching_key,
    person_group,
    reevaluate_dependents,
    remove_orphan_keys,
    remove_person,
    root_of,
    settle_holds,
    subject_segments,
)
from app.services.tenancy import AccessDenied, TenancyService

REASON_CODES = ("same_person_confirmed_by_client", "duplicate_account", "data_correction")
LATE_AFTER = timedelta(minutes=5)
PAGE = 100


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _cursor(values: Iterable[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps([str(item) for item in values]).encode()).decode()


def _parse_cursor(value: str | None, size: int) -> list[str] | None:
    if value is None:
        return None
    try:
        items = json.loads(base64.urlsafe_b64decode(value.encode()))
    except (ValueError, TypeError) as error:
        raise IdentityError("invalid_cursor", 422) from error
    if (
        not isinstance(items, list)
        or len(items) != size
        or not all(isinstance(i, str) for i in items)
    ):
        raise IdentityError("invalid_cursor", 422)
    return items


@dataclass(frozen=True)
class Reader:
    """The live permissions of one identity read (resolved by the route for this request)."""

    agency_id: UUID
    client_id: UUID
    finance: bool
    manager: bool


class IdentityAdmin(TenancyService):
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    def _begin(self, agency_id: UUID, client_id: UUID):
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        now = lock_client(self.session, client_id)
        return actor, now

    def _person(self, client_id: UUID, person_id: UUID) -> IdentitySubject:
        person = self.session.scalar(
            select(IdentitySubject)
            .where(IdentitySubject.client_id == client_id, IdentitySubject.id == person_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if person is None:
            raise AccessDenied()
        return person

    def _recorded(self, client_id: UUID, operation_id: UUID, fingerprint: str):
        row = self.session.scalar(
            select(IdentityMerge).where(
                IdentityMerge.client_id == client_id, IdentityMerge.operation_id == operation_id
            )
        )
        if row is None:
            return None
        if row.fingerprint != fingerprint:
            raise IdentityError("operation_conflict", 409)
        return row.result

    # Merge two active, distinct persons outside any active edge (D10, disjoint pairs).
    def merge(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        operation_id: UUID,
        survivor_id: UUID,
        merged_id: UUID,
        survivor_version: int,
        merged_version: int,
        reason_code: str,
    ) -> tuple[dict[str, Any], int]:
        if reason_code not in REASON_CODES:
            raise ValueError("Unknown reason code.")
        actor, now = self._begin(agency_id, client_id)
        fingerprint = _fingerprint(
            {
                "action": "merge",
                "client": client_id,
                "survivor": survivor_id,
                "merged": merged_id,
                "versions": [survivor_version, merged_version],
                "reason": reason_code,
                "actor": actor.id,
            }
        )
        recorded = self._recorded(client_id, operation_id, fingerprint)
        if recorded is not None:
            return recorded, 200
        if survivor_id == merged_id:
            raise IdentityError("merge_invalid", 409)
        first, second = sorted([survivor_id, merged_id], key=str)
        people = {first: self._person(client_id, first), second: self._person(client_id, second)}
        survivor, merged = people[survivor_id], people[merged_id]
        if (survivor.version, merged.version) != (survivor_version, merged_version):
            raise IdentityError("version_conflict", 409)
        if (
            survivor.status != "active"
            or merged.status != "active"
            or active_edge(self.session, survivor_id) is not None
            or active_edge(self.session, merged_id) is not None
            or self.session.scalar(
                select(IdentitySubject.id).where(
                    IdentitySubject.merged_into_id.in_([survivor_id, merged_id])
                )
            )
        ):
            raise IdentityError("merge_invalid", 409)
        edge_id = uuid4()
        result = {
            "merge_id": str(edge_id),
            "survivor": {"id": str(survivor_id), "version": survivor.version + 1},
            "merged": {"id": str(merged_id), "version": merged.version + 1},
        }
        edge = IdentityMerge(
            id=edge_id,
            agency_id=agency_id,
            client_id=client_id,
            operation_id=operation_id,
            kind="merge",
            survivor_id=survivor_id,
            merged_id=merged_id,
            status="active",
            survivor_version_before=survivor.version,
            merged_version_before=merged.version,
            survivor_version_after=survivor.version + 1,
            merged_version_after=merged.version + 1,
            fingerprint=fingerprint,
            result=result,
            actor_membership_id=actor.id,
            reason_code=reason_code,
            created_at=now,
        )
        self.session.add(edge)
        self.session.flush()
        merged.status, merged.merged_into_id = "merged", survivor_id
        survivor.version += 1
        merged.version += 1
        journey = Journey(self.session, agency_id, client_id, now)
        journey.touch(survivor_id, "merged")
        journey.touch(merged_id, "merged")
        journey.flush()
        self._audit(agency_id, "identity.merged", "identity_subject", survivor_id, client_id)
        return result, 201

    # Reverse the named active edge (design section 10.1) and re-evaluate its dependents.
    def reverse(
        self,
        agency_id: UUID,
        client_id: UUID,
        merge_id: UUID,
        *,
        operation_id: UUID,
        survivor_version: int,
        merged_version: int,
        reason_code: str,
    ) -> tuple[dict[str, Any], int]:
        if reason_code not in REASON_CODES:
            raise ValueError("Unknown reason code.")
        actor, now = self._begin(agency_id, client_id)
        fingerprint = _fingerprint(
            {
                "action": "unmerge",
                "client": client_id,
                "merge": merge_id,
                "versions": [survivor_version, merged_version],
                "reason": reason_code,
                "actor": actor.id,
            }
        )
        recorded = self._recorded(client_id, operation_id, fingerprint)
        if recorded is not None:
            return recorded, 200
        edge = self.session.scalar(
            select(IdentityMerge)
            .where(
                IdentityMerge.client_id == client_id,
                IdentityMerge.id == merge_id,
                IdentityMerge.kind == "merge",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if edge is None:
            raise AccessDenied()
        if edge.status != "active":
            raise IdentityError("merge_not_active", 409)
        first, second = sorted([edge.survivor_id, edge.merged_id], key=str)
        people = {first: self._person(client_id, first), second: self._person(client_id, second)}
        survivor, merged = people[edge.survivor_id], people[edge.merged_id]
        if (survivor.version, merged.version) != (survivor_version, merged_version):
            raise IdentityError("version_conflict", 409)
        edge.status, edge.ended_at = "reversed", now
        merged.status, merged.merged_into_id = "active", None
        self.session.flush()
        journey = Journey(self.session, agency_id, client_id, now)
        moved = reevaluate_dependents(self.session, client_id, edge, journey)
        survivor.version += 1
        merged.version += 1
        journey.touch(edge.survivor_id, "unmerged")
        journey.touch(edge.merged_id, "unmerged")
        journey.flush()
        result = {
            "merge_id": str(edge.id),
            "survivor": {"id": str(edge.survivor_id), "version": survivor.version},
            "merged": {"id": str(edge.merged_id), "version": merged.version},
            "moved_to_review": moved,
        }
        self.session.add(
            IdentityMerge(
                id=uuid4(),
                agency_id=agency_id,
                client_id=client_id,
                operation_id=operation_id,
                kind="unmerge",
                survivor_id=edge.survivor_id,
                merged_id=edge.merged_id,
                reverses_id=edge.id,
                status="recorded",
                survivor_version_before=survivor_version,
                merged_version_before=merged_version,
                survivor_version_after=survivor.version,
                merged_version_after=merged.version,
                fingerprint=fingerprint,
                result=result,
                actor_membership_id=actor.id,
                reason_code=reason_code,
                created_at=now,
            )
        )
        self._audit(agency_id, "identity.unmerged", "identity_subject", edge.survivor_id, client_id)
        return result, 201

    # Person erasure (design section 7.2): resolve, classify, hold, then delete.
    def erase(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        subject_id: UUID | None = None,
        identifier: tuple[str, str] | None = None,
        objected: bool = False,
    ) -> SubjectDeletionRequest:
        if (subject_id is None) == (identifier is None):
            raise ValueError("Identify the person by exactly one of subject_id or identifier.")
        _, now = self._begin(agency_id, client_id)
        paused = False
        person_id = subject_id
        key: IdentityKey | None = None
        if identifier is not None:
            try:
                value = canonical(*identifier)
            except IdentifierRejected as rejection:
                raise IdentityError(rejection.reason, 422) from rejection
            secret = matching_key(
                self.session, require_token_keys(self.settings), agency_id, client_id, create=False
            )
            key = None
            if secret is not None:
                key = self.session.scalar(
                    select(IdentityKey)
                    .where(
                        IdentityKey.client_id == client_id,
                        IdentityKey.kind == value.kind,
                        IdentityKey.key_bytes == identity_key(secret, client_id, value),
                    )
                    .with_for_update()
                )
            if key is None:
                raise AccessDenied()
            if key.status == "contested":
                paused = True
                person_id = None
            else:
                person_id = key.subject_id
        else:
            self._person(client_id, subject_id)
        if person_id is not None and self._needs_clarification(person_id):
            paused = True
        request = SubjectDeletionRequest(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            requester_kind=RequesterKind.AGENCY_ADMIN.value,
            requested_by_user_id=self.actor_user_id,
            status=RequestStatus.RECEIVED.value,
            objected=objected,
            received_at=now,
            target_outcomes={},
        )
        self.session.add(request)
        self.session.flush()
        status = deletion.transition(RequestStatus.RECEIVED, RequestStatus.VERIFYING)
        if paused:
            status = deletion.transition(status, RequestStatus.PAUSED_FOR_CLARIFICATION)
            request.status = status.value
            request.target_outcomes = {"identity_records": TargetStatus.PENDING.value}
            if objected:
                # The objection takes effect when it is received: its identifier tombstones do
                # not wait for the clarification, so a withdrawal or another erasure of the
                # person before the resolution cannot lose it (R0607-08).
                named = [] if key is None else [key]
                if person_id is not None:
                    named += list(
                        self.session.scalars(
                            select(IdentityKey).where(
                                IdentityKey.client_id == client_id,
                                IdentityKey.status == "owned",
                                IdentityKey.subject_id == person_id,
                            )
                        )
                    )
                self._objection_tombstones(request, named, now)
        else:
            self._run_erasure(request, status, person_id, now)
        self._audit(agency_id, "identity.erased", "deletion_request", request.id, client_id)
        return request

    def _objection_tombstones(
        self, request: SubjectDeletionRequest, named: list[IdentityKey], now: datetime
    ) -> None:
        keys = require_tombstone_keys(self.settings)
        for value in sorted({item.key_bytes.hex() for item in named}):
            match_key, key_id = keys.seal(request.client_id, "identity_key", value)
            self.session.add(
                StoredTombstone(
                    id=uuid4(),
                    agency_id=request.agency_id,
                    client_id=request.client_id,
                    deletion_request_id=request.id,
                    match_type="identity_key",
                    match_key=match_key,
                    match_key_id=key_id,
                    effective_at=now,
                    objected=True,
                )
            )
        self.session.flush()

    def _removed_elsewhere(self, client_id: UUID, person_id: UUID) -> bool:
        """Whether the person no longer exists because W1, an erasure or the lifecycle removed
        it: its final change record is kept for the change-feed period (30 days)."""
        if self.session.get(IdentitySubject, person_id) is not None:
            return False
        return (
            self.session.scalar(
                select(IdentityChange.seq)
                .where(
                    IdentityChange.client_id == client_id,
                    IdentityChange.person_id == person_id,
                    IdentityChange.kind.in_(REMOVAL_KINDS),
                )
                .limit(1)
            )
            is not None
        )

    def _complete_removed(self, request: SubjectDeletionRequest, now: datetime) -> None:
        """Complete a paused request whose person was removed by another path (R0607-08)."""
        status = deletion.transition(
            RequestStatus.PAUSED_FOR_CLARIFICATION, RequestStatus.VERIFYING
        )
        for step in (RequestStatus.ACCEPTED, RequestStatus.IN_PROGRESS):
            status = deletion.transition(status, step)
        targets = {
            "identity_records": TargetStatus.DONE.value,
            "collected_events": TargetStatus.NOT_APPLICABLE.value,
            "collection_subjects": TargetStatus.NOT_APPLICABLE.value,
            "booking_links": TargetStatus.NOT_APPLICABLE.value,
            "unresolved_events": TargetStatus.NOT_APPLICABLE.value,
            "financial_associations": TargetStatus.NOT_APPLICABLE.value,
        }
        request.target_outcomes = targets
        final = deletion.outcome({key: TargetStatus(value) for key, value in targets.items()})
        request.status = deletion.transition(status, final).value
        request.completed_at = now
        self.session.flush()

    def _needs_clarification(self, person_id: UUID) -> bool:
        person = self.session.get(IdentitySubject, person_id)
        return (
            person is None
            or person.status != "active"
            or active_edge(self.session, person_id) is not None
        )

    def _run_erasure(
        self,
        request: SubjectDeletionRequest,
        status: RequestStatus,
        person_id: UUID,
        now: datetime,
    ) -> None:
        session = self.session
        agency_id, client_id = request.agency_id, request.client_id
        keys = require_tombstone_keys(self.settings)
        for step in (RequestStatus.ACCEPTED, RequestStatus.IN_PROGRESS):
            status = deletion.transition(status, step)
        person = self._person(client_id, person_id)
        owned = list(
            session.scalars(
                select(IdentityLink).where(
                    IdentityLink.client_id == client_id,
                    IdentityLink.status == "active",
                    IdentityLink.subject_id == person.id,
                )
            )
        )
        candidate = list(
            session.scalars(
                select(IdentityLink).where(
                    IdentityLink.client_id == client_id,
                    IdentityLink.status == "ambiguous",
                    func.array_position(IdentityLink.candidate_ids, person.id).is_not(None),
                )
            )
        )
        owned_subjects = {link.collection_subject_id for link in owned}
        exclusive: list[CollectionSubject] = []
        confirmed: list[CollectedEvent] = []
        unresolved: list[CollectedEvent] = []
        for subject_id in sorted(
            owned_subjects | {link.collection_subject_id for link in candidate}, key=str
        ):
            subject = session.scalar(
                select(CollectionSubject)
                .where(CollectionSubject.id == subject_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if subject.identity_shared_at is None and subject_id in owned_subjects:
                exclusive.append(subject)
                continue
            _, segments = subject_segments(session, subject_id, now)
            for event in session.scalars(
                select(CollectedEvent)
                .where(CollectedEvent.subject_id == subject_id)
                .order_by(CollectedEvent.first_received_at, CollectedEvent.id)
                .with_for_update()
            ):
                kind = classify(event_times(event), segments, person.id)
                if kind == "confirmed":
                    confirmed.append(event)
                elif kind == "unresolved":
                    unresolved.append(event)
            _raise_floor(subject, now)
        # Stage 3: record the exact held set before anything is deleted (R006-24 marker too).
        for event in unresolved:
            session.add(
                IdentityErasureHold(
                    id=uuid4(),
                    agency_id=agency_id,
                    client_id=client_id,
                    deletion_request_id=request.id,
                    collected_event_id=event.id,
                    state="held",
                    held_at=now,
                )
            )
            if event.identity_excluded_at is None:
                event.identity_excluded_at = now
        session.flush()
        # 008-B (D-079 D9): the person's confirmed and held events leave every stored
        # attribution row before the confirmed ones are deleted.
        from app.services import attribution_scrub

        attribution_scrub.scrub_events(
            session,
            agency_id,
            client_id,
            [event.event_id for event in (*confirmed, *unresolved)],
            now,
        )
        confirmed_ids = [event.id for event in confirmed]
        settle_holds(session, client_id, confirmed_ids, "erased_elsewhere", now)
        tombstones: list[tuple[str, str, bool]] = [
            ("event_id", str(event.event_id), False) for event in confirmed
        ]
        for key in session.scalars(
            select(IdentityKey).where(
                IdentityKey.client_id == client_id,
                IdentityKey.status == "owned",
                IdentityKey.subject_id == person.id,
            )
        ):
            tombstones.append(("identity_key", key.key_bytes.hex(), request.objected))
        assertions = list(
            session.scalars(
                select(IdentityAssertion).where(
                    IdentityAssertion.client_id == client_id,
                    IdentityAssertion.subject_id == person.id,
                )
            )
        )
        presented: set[UUID] = set()
        for assertion in assertions:
            tombstones.append(("assertion_id", str(assertion.assertion_id), False))
            tombstones.append(("assertion_fp", assertion.fingerprint.hex(), False))
            presented.update(UUID(item["key_id"]) for item in assertion.evidence or [])
        for match_type, value, objected in tombstones:
            match_key, key_id = keys.seal(client_id, match_type, value)
            session.add(
                StoredTombstone(
                    id=uuid4(),
                    agency_id=agency_id,
                    client_id=client_id,
                    deletion_request_id=request.id,
                    match_type=match_type,
                    match_key=match_key,
                    match_key_id=key_id,
                    effective_at=now,
                    objected=objected,
                )
            )
        session.flush()
        if confirmed_ids:
            session.execute(
                CollectedEvent.__table__.delete().where(CollectedEvent.id.in_(confirmed_ids))
            )
        associations = session.scalar(
            select(func.count())
            .select_from(RevenueIdentityBinding)
            .where(
                RevenueIdentityBinding.client_id == client_id,
                RevenueIdentityBinding.owner_subject_id == person.id,
            )
        )
        journey = Journey(session, agency_id, client_id, now)
        remove_person(session, client_id, person.id, "erased", journey, now)
        remove_orphan_keys(session, client_id, presented)
        detached = 0
        for subject in exclusive:
            detached += erase_subject_row(session, keys, request, subject, now)[0]
        journey.flush()
        targets = {
            "identity_records": TargetStatus.DONE.value,
            "collected_events": (
                TargetStatus.DONE if confirmed or exclusive else TargetStatus.NOT_APPLICABLE
            ).value,
            "collection_subjects": (
                TargetStatus.DONE if exclusive else TargetStatus.NOT_APPLICABLE
            ).value,
            "booking_links": (TargetStatus.DONE if detached else TargetStatus.NOT_APPLICABLE).value,
            "unresolved_events": (
                TargetStatus.PENDING if unresolved else TargetStatus.NOT_APPLICABLE
            ).value,
            # F1: completion requires the person's sale associations to be unlinked (done in
            # this transaction by remove_person); amounts and evidence are untouched.
            "financial_associations": (
                TargetStatus.DONE if associations else TargetStatus.NOT_APPLICABLE
            ).value,
            # 008-B (D-079 D9): done only after the scrub, which ran in this transaction
            # (the person's events above, then remove_person and each exclusive subject).
            "attribution": (
                TargetStatus.DONE
                if attribution_scrub.scrubbed_at(session, client_id, now)
                else TargetStatus.NOT_APPLICABLE
            ).value,
        }
        request.target_outcomes = targets
        if unresolved:
            request.status = deletion.transition(status, RequestStatus.ON_HOLD).value
        else:
            final = deletion.outcome({key: TargetStatus(value) for key, value in targets.items()})
            request.status = deletion.transition(status, final).value
            request.completed_at = now
        session.flush()

    # Resolve a paused request with the original person, or decide an on-hold request's held
    # events (erase or retain exactly the recorded set).
    def resolve(
        self,
        agency_id: UUID,
        client_id: UUID,
        request_id: UUID,
        *,
        subject_id: UUID | None = None,
        unresolved_events: Literal["erase", "retain"] | None = None,
    ) -> SubjectDeletionRequest:
        if (subject_id is None) == (unresolved_events is None):
            raise ValueError("Provide exactly one resolution.")
        _, now = self._begin(agency_id, client_id)
        request = self.session.scalar(
            select(SubjectDeletionRequest)
            .where(
                SubjectDeletionRequest.client_id == client_id,
                SubjectDeletionRequest.id == request_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if request is None:
            raise AccessDenied()
        if subject_id is not None:
            if request.status != RequestStatus.PAUSED_FOR_CLARIFICATION.value:
                raise IdentityError("request_state", 409)
            if self._removed_elsewhere(client_id, subject_id):
                self._complete_removed(request, now)
            else:
                self._person(client_id, subject_id)
                if self._needs_clarification(subject_id):
                    raise IdentityError("clarification_required", 409)
                status = deletion.transition(
                    RequestStatus.PAUSED_FOR_CLARIFICATION, RequestStatus.VERIFYING
                )
                self._run_erasure(request, status, subject_id, now)
        else:
            if request.status != RequestStatus.ON_HOLD.value:
                raise IdentityError("request_state", 409)
            self._decide_holds(request, unresolved_events, now)
        self._audit(
            agency_id, "identity.erasure_resolved", "deletion_request", request.id, client_id
        )
        return request

    def _decide_holds(self, request: SubjectDeletionRequest, decision: str, now: datetime) -> None:
        session, client_id = self.session, request.client_id
        holds = list(
            session.scalars(
                select(IdentityErasureHold)
                .where(
                    IdentityErasureHold.client_id == client_id,
                    IdentityErasureHold.deletion_request_id == request.id,
                    IdentityErasureHold.state == "held",
                )
                .order_by(IdentityErasureHold.id)
                .with_for_update()
            )
        )
        event_ids = [hold.collected_event_id for hold in holds]
        if decision == "erase":
            keys = require_tombstone_keys(self.settings)
            events = list(
                session.scalars(
                    select(CollectedEvent).where(CollectedEvent.id.in_(event_ids)).with_for_update()
                )
            )
            for hold in holds:
                hold.state, hold.collected_event_id, hold.settled_at = "erased", None, now
            session.flush()
            journey = Journey(session, request.agency_id, client_id, now)
            for event in events:
                match_key, key_id = keys.seal(client_id, "event_id", str(event.event_id))
                session.add(
                    StoredTombstone(
                        id=uuid4(),
                        agency_id=request.agency_id,
                        client_id=client_id,
                        deletion_request_id=request.id,
                        match_type="event_id",
                        match_key=match_key,
                        match_key_id=key_id,
                        effective_at=now,
                    )
                )
            settle_holds(session, client_id, event_ids, "erased_elsewhere", now)
            if event_ids:
                session.execute(
                    CollectedEvent.__table__.delete().where(CollectedEvent.id.in_(event_ids))
                )
            journey.flush()
        else:
            for hold in holds:
                hold.state, hold.collected_event_id, hold.settled_at = "retained", None, now
        session.flush()
        complete_if_settled(session, client_id, request.id, now)
        session.refresh(request)

    def review(self, agency_id: UUID, client_id: UUID) -> dict[str, Any]:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        session = self.session
        links = session.scalars(
            select(IdentityLink)
            .where(IdentityLink.client_id == client_id, IdentityLink.status == "ambiguous")
            .order_by(IdentityLink.asserted_at, IdentityLink.id)
            .limit(PAGE)
        )
        keys = session.scalars(
            select(IdentityKey)
            .where(IdentityKey.client_id == client_id, IdentityKey.status == "contested")
            .order_by(IdentityKey.created_at, IdentityKey.id)
            .limit(PAGE)
        )
        requests = session.scalars(
            select(SubjectDeletionRequest)
            .where(
                SubjectDeletionRequest.client_id == client_id,
                SubjectDeletionRequest.status.in_(["paused_for_clarification", "on_hold"]),
            )
            .order_by(SubjectDeletionRequest.received_at, SubjectDeletionRequest.id)
            .limit(PAGE)
        )
        segments = []
        for link in links:
            outcome = (
                session.scalar(
                    select(IdentityAssertion.outcome).where(
                        IdentityAssertion.id == link.assertion_ref
                    )
                )
                if link.assertion_ref is not None
                else None
            )
            segments.append(
                {
                    "link_id": str(link.id),
                    "candidates": [str(item) for item in link.candidate_ids],
                    # A link left ambiguous by a reversal or an edge closure was created owned.
                    "reason": "ambiguous" if outcome in (None, "ambiguous") else "unmerged",
                    "asserted_at": link.asserted_at,
                }
            )
        return {
            "ambiguous_segments": segments,
            "contested_keys": [
                {
                    "key_id": str(key.id),
                    "kind": key.kind,
                    "reason": key.contested_reason,
                    "candidates": [str(item) for item in key.candidate_ids],
                }
                for key in keys
            ],
            "erasure_requests": [
                {"id": str(item.id), "status": item.status, "targets": item.target_outcomes}
                for item in requests
            ],
            # Conflicting sale associations wait for a review action (R0607-04): detach names
            # the association ID and the revision shown here.
            "ambiguous_associations": [
                {
                    "association_id": str(row.association_id),
                    "revision": row.revision,
                    "reason": row.reason,
                    "source_account_id": row.source_account_id,
                    "sale_operation_id": row.sale_operation_id,
                    "received_at": row.received_at,
                }
                for row in session.scalars(
                    select(RevenueIdentityBinding)
                    .where(
                        RevenueIdentityBinding.client_id == client_id,
                        RevenueIdentityBinding.state == "ambiguous",
                        RevenueIdentityBinding.closed_at.is_(None),
                    )
                    .order_by(RevenueIdentityBinding.received_at, RevenueIdentityBinding.id)
                    .limit(PAGE)
                )
            ],
        }


# ---------------------------------------------------------------------------------------------
# Reads (identity:read).


def customer_status(session: Session, client_id: UUID, group: list[UUID], reader: Reader) -> str:
    """Financial customer qualification (D13, J5): 007-C supplies verified associations. While
    the published ledger cannot be read the answer is the explicit ledger_unavailable, never a
    manufactured not_customer (joint design 2 and 4.6, R0607-09)."""
    if not reader.finance:
        return "permission_unavailable"
    from app.services.ledger_store import LedgerUnavailable
    from app.services.revenue_identity import has_verified_purchase

    try:
        return "customer" if has_verified_purchase(session, client_id, group) else "not_customer"
    except LedgerUnavailable:
        return "ledger_unavailable"


def _provenance(session: Session, event: CollectedEvent, cache: dict) -> dict[str, Any]:
    path = None
    url = (event.payload or {}).get("url")
    if isinstance(url, str):
        path = urlsplit(url).path or None
    if event.link_id is None:
        return {"link_id": None, "campaign": None, "content": None, "path": path}
    if event.link_id not in cache:
        row = session.execute(
            select(LinkCampaign.public_code, LinkContentReference.external_code)
            .select_from(ManagedLink)
            .outerjoin(LinkCampaign, LinkCampaign.id == ManagedLink.campaign_id)
            .outerjoin(
                LinkContentReference, LinkContentReference.id == ManagedLink.content_reference_id
            )
            .where(ManagedLink.id == event.link_id)
        ).one_or_none()
        cache[event.link_id] = row or (None, None)
    campaign, content = cache[event.link_id]
    return {"link_id": str(event.link_id), "campaign": campaign, "content": content, "path": path}


def _visible(event: CollectedEvent, reader: Reader) -> bool:
    return event.event_type != "purchase_signal" or reader.finance


def _stage(entries, has_link: bool, customer: str) -> tuple[str, list[str]]:
    flags = []
    lead = any(e.event_type == "lead_signal" and e.trust_rank == 2 for e, _ in entries)
    if any(e.event_type == "lead_signal" and e.trust_rank == 1 for e, _ in entries):
        flags.append("lead_reported_unverified")
    if any(e.event_type == "purchase_signal" and e.trust_rank == 2 for e, _ in entries):
        flags.append("purchase_reported")
    if customer == "ledger_unavailable":
        flags.append("customer_status_unavailable")
    if not has_link:
        return "unlinked", flags
    if customer == "customer":
        return "customer", flags
    return ("lead" if lead else "known"), flags


def _summary(session: Session, reader: Reader, person_id: UUID, now: datetime) -> dict[str, Any]:
    client_id = reader.client_id
    group = person_group(session, client_id, person_id)
    entries = [
        item
        for item in journey_events(session, client_id, person_id, now)
        if _visible(item[0], reader)
    ]
    has_link = (
        session.scalar(
            select(IdentityLink.id)
            .where(
                IdentityLink.client_id == client_id,
                IdentityLink.status == "active",
                IdentityLink.subject_id.in_(group),
            )
            .limit(1)
        )
        is not None
    )
    customer = customer_status(session, client_id, group, reader)
    stage, flags = _stage(entries, has_link, customer)
    if not reader.finance:
        flags = [flag for flag in flags if flag != "purchase_reported"]
    return {
        "group": group,
        "entries": entries,
        "stage": stage,
        "flags": flags,
        "customer": customer,
    }


def profile(session: Session, reader: Reader, person_id: UUID, now: datetime) -> dict[str, Any]:
    client_id = reader.client_id
    requested = session.scalar(
        select(IdentitySubject).where(
            IdentitySubject.client_id == client_id, IdentitySubject.id == person_id
        )
    )
    if requested is None:
        raise AccessDenied()
    root = session.get(IdentitySubject, root_of(session, person_id))
    summary = _summary(session, reader, person_id, now)
    group, entries = summary["group"], summary["entries"]
    keys = list(
        session.scalars(
            select(IdentityKey)
            .where(
                IdentityKey.client_id == client_id,
                or_(
                    IdentityKey.subject_id.in_(group),
                    *[
                        func.array_position(IdentityKey.candidate_ids, item).is_not(None)
                        for item in group
                    ],
                ),
            )
            .order_by(IdentityKey.kind, IdentityKey.created_at)
        )
    )
    devices = set(
        session.scalars(
            select(IdentityLink.collection_subject_id).where(
                IdentityLink.client_id == client_id,
                IdentityLink.status == "active",
                IdentityLink.subject_id.in_(group),
            )
        )
    )
    cache: dict = {}
    by_receipt = sorted(
        entries, key=lambda item: (item[0].first_received_at, str(item[0].event_id))
    )
    review_items = session.scalar(
        select(func.count())
        .select_from(IdentityLink)
        .where(
            IdentityLink.client_id == client_id,
            IdentityLink.status == "ambiguous",
            or_(
                *[
                    func.array_position(IdentityLink.candidate_ids, item).is_not(None)
                    for item in group
                ]
            ),
        )
    )
    body = {
        "id": str(root.id),
        "requested_id": str(person_id),
        "status": root.status,
        "version": root.version,
        "stage": summary["stage"],
        "flags": summary["flags"],
        "customer_qualification": summary["customer"],
        "first_seen_at": by_receipt[0][0].first_received_at if by_receipt else None,
        "last_seen_at": by_receipt[-1][0].first_received_at if by_receipt else None,
        "keys": [
            {
                "kind": key.kind,
                "normalizer": key.normalizer,
                "method": key.method,
                "verified_at": key.last_verified_at,
                "contested": key.status == "contested",
            }
            for key in keys
        ],
        "device_subjects": len(devices),
        "touchpoints": len(entries),
        "first_touch": _provenance(session, entries[0][0], cache) if entries else None,
        "last_touch": _provenance(session, entries[-1][0], cache) if entries else None,
        "journey_revision": root.journey_revision,
        "review_items": review_items,
    }
    if reader.manager:
        body["members"] = [
            {"id": str(item), "version": session.get(IdentitySubject, item).version}
            for item in group
        ]
        edge = active_edge(session, root.id) if root.status == "active" else None
        body["active_merge_id"] = str(edge.id) if edge is not None else None
    return body


def timeline(
    session: Session,
    reader: Reader,
    person_id: UUID,
    now: datetime,
    *,
    after: str | None = None,
    limit: int = PAGE,
) -> dict[str, Any]:
    if not 1 <= limit <= PAGE:
        raise ValueError("invalid_limit")
    client_id = reader.client_id
    if (
        session.scalar(
            select(IdentitySubject.id).where(
                IdentitySubject.client_id == client_id, IdentitySubject.id == person_id
            )
        )
        is None
    ):
        raise AccessDenied()
    root = session.get(IdentitySubject, root_of(session, person_id))
    entries = [
        item
        for item in journey_events(session, client_id, person_id, now)
        if _visible(item[0], reader)
    ]
    aliases: dict[UUID, str] = {}
    for _, link in sorted(entries, key=lambda item: (item[1].asserted_at, str(item[1].id))):
        aliases.setdefault(link.collection_subject_id, f"device-{len(aliases) + 1}")
    position = _parse_cursor(after, 3)
    if position is not None:
        entries = [
            item
            for item in entries
            if (
                item[0].occurred_at.isoformat(),
                item[0].first_received_at.isoformat(),
                str(item[0].event_id),
            )
            > tuple(position)
        ]
    page = entries[:limit]
    cache: dict = {}
    assertions: dict[UUID, IdentityAssertion] = {}
    result = []
    for event, link in page:
        if link.assertion_ref not in assertions and link.assertion_ref is not None:
            assertions[link.assertion_ref] = session.get(IdentityAssertion, link.assertion_ref)
        evidence = assertions.get(link.assertion_ref)
        items = (evidence.evidence if evidence is not None else []) or []
        entry = {
            "event_id": str(event.event_id),
            "type": event.event_type,
            "occurred_at": event.occurred_at,
            "received_at": event.first_received_at,
            "late": event.first_received_at - event.occurred_at > LATE_AFTER,
            "trust": "trusted_sender" if event.trust_rank == 2 else "browser",
            "revision": event.revision,
            "provenance": _provenance(session, event, cache),
            "evidence": {
                "device_subject": aliases[link.collection_subject_id],
                "assertion_id": str(evidence.assertion_id) if evidence is not None else None,
                "keys": sorted({item["kind"] for item in items}),
                "methods": sorted({item["method"] for item in items}),
            },
        }
        if event.event_type == "purchase_signal":
            entry["note"] = "Reported purchase; not verified sale evidence."
        result.append(entry)
    following = None
    if len(entries) > limit:
        last = page[-1][0]
        following = _cursor(
            [last.occurred_at.isoformat(), last.first_received_at.isoformat(), last.event_id]
        )
    return {
        "subject_id": str(root.id),
        "journey_revision": root.journey_revision,
        "entries": result,
        "next_cursor": following,
    }


def list_people(
    session: Session,
    reader: Reader,
    now: datetime,
    *,
    stage: str | None = None,
    updated_since: datetime | None = None,
    after: str | None = None,
    limit: int = PAGE,
) -> dict[str, Any]:
    if not 1 <= limit <= PAGE:
        raise ValueError("invalid_limit")
    query = select(IdentitySubject).where(
        IdentitySubject.client_id == reader.client_id, IdentitySubject.status == "active"
    )
    if updated_since is not None:
        query = query.where(IdentitySubject.updated_at >= updated_since)
    position = _parse_cursor(after, 1)
    if position is not None:
        query = query.where(IdentitySubject.id > UUID(position[0]))
    items = []
    for person in session.scalars(query.order_by(IdentitySubject.id)):
        summary = _summary(session, reader, person.id, now)
        if stage is not None and summary["customer"] == "ledger_unavailable":
            # A stage filter needs the financial qualification: fail closed and retry, never
            # leave a customer out of the list (R0607-09).
            from app.services.ledger_store import LedgerUnavailable

            raise LedgerUnavailable()
        if stage is not None and summary["stage"] != stage:
            continue
        items.append(
            {
                "id": str(person.id),
                "version": person.version,
                "stage": summary["stage"],
                "flags": summary["flags"],
                "journey_revision": person.journey_revision,
                "updated_at": person.updated_at,
            }
        )
        if len(items) > limit:
            break
    following = _cursor([items[limit - 1]["id"]]) if len(items) > limit else None
    return {"items": items[:limit], "next_cursor": following}


def leads(
    session: Session,
    reader: Reader,
    now: datetime,
    *,
    identified: bool | None = None,
    trust: Literal["browser", "trusted_sender"] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    after: str | None = None,
    limit: int = PAGE,
) -> dict[str, Any]:
    if not 1 <= limit <= PAGE:
        raise ValueError("invalid_limit")
    query = select(CollectedEvent).where(
        CollectedEvent.client_id == reader.client_id, CollectedEvent.event_type == "lead_signal"
    )
    if trust is not None:
        query = query.where(CollectedEvent.trust_rank == (2 if trust == "trusted_sender" else 1))
    if start is not None:
        query = query.where(CollectedEvent.first_received_at >= start)
    if end is not None:
        query = query.where(CollectedEvent.first_received_at < end)
    position = _parse_cursor(after, 2)
    if position is not None:
        try:
            bound = (datetime.fromisoformat(position[0]), UUID(position[1]))
        except ValueError as error:
            raise IdentityError("invalid_cursor", 422) from error
        query = query.where(tuple_(CollectedEvent.first_received_at, CollectedEvent.id) < bound)
    segments: dict[UUID, list] = {}
    stages: dict[UUID, str] = {}
    qualifications: dict[UUID, str] = {}
    cache: dict = {}
    items = []
    from app.identity.segments import owner_of

    for event in session.scalars(
        query.order_by(CollectedEvent.first_received_at.desc(), CollectedEvent.id.desc())
    ):
        if event.subject_id not in segments:
            segments[event.subject_id] = subject_segments(session, event.subject_id, now)[1]
        owner = owner_of(event_times(event), segments[event.subject_id])
        person = root_of(session, owner) if owner is not None else None
        if identified is not None and (person is not None) != identified:
            continue
        if person is not None and person not in stages:
            summary = _summary(session, reader, person, now)
            stages[person] = summary["stage"]
            qualifications[person] = summary["customer"]
        items.append(
            {
                "event_id": str(event.event_id),
                "action": (event.payload or {}).get("action"),
                "trust": "trusted_sender" if event.trust_rank == 2 else "browser",
                "occurred_at": event.occurred_at,
                "received_at": event.first_received_at,
                "person": (
                    {
                        "id": str(person),
                        "stage": stages[person],
                        "customer_qualification": qualifications[person],
                    }
                    if person is not None
                    else None
                ),
                "identified": person is not None,
                "provenance": _provenance(session, event, cache),
                "_key": (event.first_received_at.isoformat(), str(event.id)),
            }
        )
        if len(items) > limit:
            break
    following = _cursor(items[limit - 1]["_key"]) if len(items) > limit else None
    for item in items:
        item.pop("_key")
    return {"items": items[:limit], "next_cursor": following}
