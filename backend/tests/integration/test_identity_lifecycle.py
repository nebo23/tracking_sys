"""Development identity retention run by tracking_lifecycle (design 12.5, D-075 J6).

Synthetic values on disposable PostgreSQL. A lifecycle run with a controlled cutoff purges
expired handoffs and retry receipts, prunes the change feed (advancing pruned_through_seq),
settles holds on expiring events before deleting them, removes the identity evidence of an
expiring collection subject before the subject itself, and closes a merge edge first when an
expiry removes a participant's last independent evidence (R006-25). Nothing runs without the
client privacy lock, and the role never reads the matching secret or tombstones.
"""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from identity_support import make_identity_world, rows
from sqlalchemy import func, select, update

from app.models import (
    CollectedEvent,
    CollectionSubject,
    IdentityAssertion,
    IdentityAssertionReceipt,
    IdentityChange,
    IdentityErasureHold,
    IdentityFeedState,
    IdentityHandoff,
    IdentityLink,
    IdentityMerge,
    IdentitySubject,
    SubjectDeletionRequest,
)
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration


@pytest.fixture
def idw(authenticated_world, api):
    return make_identity_world(authenticated_world, api)


def now(db):
    with db.migration.connect() as connection:
        return connection.execute(select(func.now())).scalar_one()


def ok(response, status=201):
    assert response.status_code == status, response.text
    return response.json()


def test_handoffs_receipts_and_change_feed_expire(idw, db, lifecycle_engine, lifecycle_settings):
    a1 = idw.w.a1
    token = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(token, [idw.identifier("email", "life@example.test", "email_code")]))
    idw.issued_handoff(token)  # one consumed (by the assertion) and one unused handoff
    later = now(db) + timedelta(days=31)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=later)
    assert result["status"] == "completed", result
    assert rows(db, select(IdentityHandoff)) == []
    assert rows(db, select(IdentityAssertionReceipt)) == []
    assert rows(db, select(IdentityChange)) == []
    state = rows(db, select(IdentityFeedState).where(IdentityFeedState.client_id == a1))[0]
    assert state.pruned_through_seq == state.last_seq >= 1
    # The person and its evidence stay: 395 days have not passed.
    assert len(rows(db, select(IdentitySubject))) == 1
    assert result["deleted"]["identity_changes"] >= 1


def test_expiring_held_event_settles_its_hold_and_completes_the_request(
    idw, db, lifecycle_engine, lifecycle_settings
):
    tablet = idw.browser_subject()["subject_token"]
    early = idw.event(tablet)
    ok(idw.via_browser(tablet, [idw.identifier("email", "h1@example.test", "email_code")]))
    ok(idw.via_browser(tablet, [idw.identifier("email", "h2@example.test", "email_code")]))
    first = rows(db, select(IdentitySubject.id).order_by(IdentitySubject.created_at))[0]
    request = ok(
        idw.owner.post(
            f"{idw.base}/clients/{idw.w.a1}/identity/erasures", json={"subject_id": str(first)}
        )
    )
    assert request["status"] == "on_hold"
    event = idw.event_row(early)
    with db.migration.begin() as connection:
        connection.execute(
            update(CollectedEvent)
            .where(CollectedEvent.id == event.id)
            .values(expires_at=func.now() - timedelta(seconds=1))
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed", result
    assert rows(db, select(CollectedEvent).where(CollectedEvent.id == event.id)) == []
    hold = rows(db, select(IdentityErasureHold))[0]
    assert (hold.state, hold.collected_event_id) == ("expired", None)
    stored = rows(
        db, select(SubjectDeletionRequest).where(SubjectDeletionRequest.id == UUID(request["id"]))
    )[0]
    assert stored.status == "completed"
    assert stored.target_outcomes["unresolved_events"] == "done"


def test_expiring_subject_loses_identity_evidence_first(
    idw, db, lifecycle_engine, lifecycle_settings
):
    token = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(token, [idw.identifier("email", "idle@example.test", "email_code")]))
    (person,) = rows(db, select(IdentitySubject.id))
    far = now(db) + timedelta(days=800)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=far)
    assert result["status"] == "completed", result
    assert rows(db, select(CollectionSubject)) == []
    assert rows(db, select(IdentityLink)) == []
    assert rows(db, select(IdentityAssertion)) == []
    assert rows(db, select(IdentitySubject)) == []
    kinds = rows(db, select(IdentityChange.kind).where(IdentityChange.person_id == person))
    assert kinds == [] or kinds[-1] == "expired"  # change rows themselves expire after 30 days


def test_expiry_of_a_participant_closes_the_merge_edge_first(
    idw, db, lifecycle_engine, lifecycle_settings
):
    w = idw.w
    d1 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d1, [idw.identifier("email", "stay@example.test", "email_code")]))
    d2 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d2, [idw.identifier("email", "old@example.test", "email_code")]))
    survivor, lost = rows(db, select(IdentitySubject.id).order_by(IdentitySubject.created_at))
    edge = ok(
        idw.owner.post(
            f"{idw.base}/clients/{w.a1}/identity/merges",
            json={
                "operation_id": str(uuid4()),
                "survivor_id": str(survivor),
                "merged_id": str(lost),
                "survivor_version": 1,
                "merged_version": 1,
                "reason_code": "duplicate_account",
            },
        )
    )
    old = now(db) - timedelta(days=400)
    d2_subject = rows(
        db,
        select(IdentityLink.collection_subject_id).where(IdentityLink.subject_id == lost),
    )[0]
    with db.migration.begin() as connection:
        connection.execute(
            update(IdentityLink)
            .where(IdentityLink.collection_subject_id == d2_subject)
            .values(asserted_at=old, eligible_from=old, provisional_from=None, grant_started_at=old)
        )
        connection.execute(
            update(IdentityAssertion)
            .where(IdentityAssertion.collection_subject_id == d2_subject)
            .values(received_at=old)
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed", result
    assert rows(db, select(IdentitySubject.id)) == [survivor]
    row = rows(db, select(IdentityMerge).where(IdentityMerge.id == UUID(edge["merge_id"])))[0]
    assert (row.status, row.closed_reason) == ("closed", "participant_expired")
    person = rows(db, select(IdentitySubject).where(IdentitySubject.id == survivor))[0]
    assert person.version == 3 and person.status == "active"
