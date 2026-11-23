"""Specification 006 identity assertions, proof, consent and segments on disposable PostgreSQL.

Covers P1 of the joint verification matrix (D-075): the worked journey of design section 2.1,
the six issuance/proof cells, retry receipts (R006-26), the provisional prefix and shared
devices (R006-27), W1 withdrawal, cross-client isolation, the scoped hold foreign key
(R006-23), the write-once exclusion marker (R006-24), concurrency and migration privileges.
Every case asserts stored rows, not only HTTP statuses. Synthetic values only.
"""

import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from identity_support import (
    ALL,
    ANALYTICS,
    ATTRIBUTION,
    IDENTITY,
    count,
    make_identity_world,
    receipt_for,
    rows,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CollectedEvent,
    CollectionSubject,
    EventDiagnostic,
    IdentityAssertion,
    IdentityAssertionReceipt,
    IdentityChange,
    IdentityErasureHold,
    IdentityFeedState,
    IdentityHandoff,
    IdentityKey,
    IdentityKeySecret,
    IdentityLink,
    IdentitySubject,
    SubjectDeletionRequest,
)
from app.privacy.consent import ConsentSource, ConsentState, Purpose
from app.security import digest, now_utc
from app.services.collection import record_consent

pytestmark = pytest.mark.integration


@pytest.fixture
def idw(authenticated_world, api):
    return make_identity_world(authenticated_world, api)


def person_ids(db, client_id):
    return rows(
        db,
        select(IdentitySubject.id)
        .where(IdentitySubject.client_id == client_id)
        .order_by(IdentitySubject.created_at),
    )


def accepted(response):
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "accepted"
    return response


def test_worked_journey_links_three_devices_to_one_person(idw):
    """Design section 2.1, Outcome A: phone P, server subject Q and laptop L."""
    db, a1 = idw.w.db, idw.w.a1
    phone = idw.browser_subject()["subject_token"]
    e1 = idw.event(phone)
    e2 = idw.event(
        phone,
        event_type="form_submit",
        payload={"url": "https://shop.example.test/offer", "form_key": "offer"},
    )
    email = idw.identifier("email", "mona@example.test", "email_code")
    accepted(idw.via_browser(phone, [email]))
    (s1,) = person_ids(db, a1)
    server = idw.server_subject({ATTRIBUTION: "granted", IDENTITY: "granted"})
    e3 = idw.event(server["subject_token"], event_type="lead_signal", trusted=True)
    accepted(idw.via_server(server, {ATTRIBUTION: "granted", IDENTITY: "granted"}, [email]))
    laptop = idw.browser_subject()["subject_token"]
    e4 = idw.event(laptop)
    accepted(
        idw.via_browser(
            laptop,
            [
                idw.identifier("customer_ref", "cust-1042", "account_login"),
                idw.identifier("email", "mona@example.test", "account_verified_email"),
            ],
        )
    )
    e5 = idw.event(laptop)
    e6 = idw.event(
        server["subject_token"],
        event_type="purchase_signal",
        trusted=True,
        payload={"external_ref": "order-1", "amount_minor": 12000, "currency": "EGP"},
    )
    assert person_ids(db, a1) == [s1]
    keys = rows(db, select(IdentityKey).where(IdentityKey.client_id == a1))
    assert sorted(key.kind for key in keys) == ["customer_ref", "email"]
    assert {key.subject_id for key in keys} == {s1}
    assert all(len(key.key_bytes) == 32 for key in keys)
    assert (
        count(db, IdentityLink, IdentityLink.client_id == a1, IdentityLink.status == "active") == 3
    )
    journey = idw.journey(s1)
    assert set(journey) >= {e1, e3, e4, e5, e6}
    # e2 is a form submit of an unregistered form: stored with the dropped fields only.
    person = rows(db, select(IdentitySubject).where(IdentitySubject.id == s1))[0]
    assert person.journey_revision == 5  # A1, A2, A3, then e5 and e6 on linked subjects
    changes = rows(
        db,
        select(IdentityChange).where(IdentityChange.client_id == a1).order_by(IdentityChange.seq),
    )
    assert [change.seq for change in changes] == list(range(1, len(changes) + 1))
    state = rows(db, select(IdentityFeedState).where(IdentityFeedState.client_id == a1))[0]
    assert state.last_seq == len(changes)
    # No raw value, token, code or challenge is stored anywhere in the identity tables.
    with Session(db.migration) as session:
        dump = " ".join(
            str(value)
            for table in (
                "identity_keys",
                "identity_assertions",
                "identity_links",
                "identity_handoffs",
            )
            for value in session.execute(text(f"SELECT * FROM {table}")).all()
        )
    for secret in ("mona@example.test", "cust-1042", phone, laptop):
        assert secret not in dump
    assert e2 is not None


def test_six_issuance_and_proof_cells(idw, db):
    a1 = idw.w.a1
    email = [idw.identifier("email", "cell@example.test", "email_code")]
    browser = idw.browser_subject()
    server = idw.server_subject()
    # browser + direct token: proof_invalid, nothing consumed.
    direct = idw.assertion(
        email,
        proof={
            "subject_token": browser["subject_token"],
            "identity_consent_receipt_id": receipt_for(browser, ALL),
        },
    )
    assert direct.status_code == 422 and direct.json()["reason"] == "proof_invalid"
    # server + public handoff: the same unavailable answer as an unknown token.
    refused = idw.handoff(server["subject_token"])
    unknown = idw.handoff("sbj_" + "x" * 43)
    assert refused.status_code == unknown.status_code == 200
    assert refused.json() == unknown.json() == {"status": "unavailable"}
    # unknown (legacy) issuance: neither route.
    with Session(db.runtime) as session, session.begin():
        legacy = record_consent(
            session,
            idw.w.a,
            a1,
            source=ConsentSource.API,
            notice_sha256="b" * 64,
            choices={Purpose.IDENTITY_LINK: ConsentState.GRANTED},
            subject_token=None,
            captured_at=None,
            recheck=lambda: None,
        )
    assert idw.handoff(legacy.subject_token).json() == {"status": "unavailable"}
    legacy_direct = idw.assertion(
        email,
        proof={
            "subject_token": legacy.subject_token,
            "identity_consent_receipt_id": str(legacy.receipts[0]),
        },
    )
    assert legacy_direct.json()["reason"] == "proof_invalid"
    channels = rows(
        db, select(CollectionSubject.issuance_channel).where(CollectionSubject.client_id == a1)
    )
    assert sorted(channels) == ["browser", "server", "unknown"]
    # The two permitted cells.
    accepted(idw.via_browser(browser["subject_token"], email))
    accepted(
        idw.via_server(server, ALL, [idw.identifier("email", "cell2@example.test", "email_code")])
    )
    assert count(db, IdentityAssertion, IdentityAssertion.client_id == a1) == 2


def test_handoff_is_single_use_bound_to_its_challenge_and_consent(idw, db):
    token = idw.browser_subject()["subject_token"]
    email = [idw.identifier("email", "once@example.test", "email_code")]
    code, value = idw.issued_handoff(token)
    reused = idw.handoff(token, value)
    assert reused.status_code == 200 and reused.json()["status"] == "unavailable"
    wrong = idw.assertion(email, proof={"handoff": code, "challenge": value[::-1]})
    assert wrong.json()["reason"] == "proof_invalid"
    accepted(idw.assertion(email, proof={"handoff": code, "challenge": value}))
    replay = idw.assertion(email, proof={"handoff": code, "challenge": value})
    assert replay.json()["reason"] == "proof_invalid"
    # A renewed grant does not reactivate a handoff issued under the earlier receipt.
    code2, value2 = idw.issued_handoff(token)
    idw.browser_subject({IDENTITY: "granted"}, token=token)
    stale = idw.assertion(
        [idw.identifier("email", "twice@example.test", "email_code")],
        proof={"handoff": code2, "challenge": value2},
    )
    assert stale.json()["reason"] == "proof_invalid"
    # Expired handoff.
    code3, value3 = idw.issued_handoff(token)
    with db.migration.begin() as connection:
        connection.execute(
            update(IdentityHandoff)
            .where(IdentityHandoff.code_digest == digest(code3))
            .values(
                expires_at=func.now() - timedelta(seconds=1),
                created_at=func.now() - timedelta(minutes=11),
            )
        )
    expired = idw.assertion(
        [idw.identifier("email", "late@example.test", "email_code")],
        proof={"handoff": code3, "challenge": value3},
    )
    assert expired.json()["reason"] == "proof_invalid"
    # Without identity_link the public route issues nothing.
    other = idw.browser_subject({ANALYTICS: "granted"})["subject_token"]
    assert idw.handoff(other).json() == {"status": "unavailable"}


def test_validation_and_freshness_rejections(idw):
    token = idw.browser_subject()["subject_token"]
    code, value = idw.issued_handoff(token)
    proof = {"handoff": code, "challenge": value}
    stale = idw.identifier(
        "email", "old@example.test", "email_code", now_utc() - timedelta(days=31)
    )
    ahead = idw.identifier(
        "email", "old@example.test", "email_code", now_utc() + timedelta(minutes=6)
    )
    for item in (stale, ahead):
        response = idw.assertion([item], proof=proof)
        assert response.status_code == 422 and response.json()["reason"] == "verification_stale"
    cases = [
        ([idw.identifier("phone", "010 0000 0101", "phone_code")], "phone_country_required"),
        ([idw.identifier("phone", "+20 10 0000 0101 ext 9", "phone_code")], "identifier_invalid"),
        ([idw.identifier("email", "x@example.test", "phone_code")], "method_invalid"),
        (
            [
                idw.identifier("email", "x@example.test", "email_code"),
                idw.identifier("email", "y@example.test", "email_code"),
            ],
            "request_invalid",
        ),
    ]
    for identifiers, reason in cases:
        response = idw.assertion(identifiers, proof=proof)
        assert response.status_code == 422 and response.json() == {
            "status": "rejected",
            "reason": reason,
        }
    both = idw.assertion(
        [idw.identifier("email", "x@example.test", "email_code")],
        proof={**proof, "subject_token": token, "identity_consent_receipt_id": str(uuid4())},
    )
    assert both.json()["reason"] == "request_invalid"
    # The handoff was never consumed by the rejected requests.
    accepted(idw.assertion([idw.identifier("email", "ok@example.test", "email_code")], proof=proof))


def test_retry_receipts_answer_inside_the_window_only(idw, db):
    """R006-26: retries inside 24 hours; an expired receipt is replaced, never duplicated."""
    a1 = idw.w.a1
    server = idw.server_subject()
    assertion_id = uuid4()
    email = [idw.identifier("email", "retry@example.test", "email_code")]
    first = idw.via_server(server, ALL, email, assertion_id=assertion_id)
    accepted(first)
    again = idw.via_server(server, ALL, email, assertion_id=assertion_id)
    assert again.status_code == 200 and again.json()["status"] == "duplicate"
    changed = idw.via_server(
        server,
        ALL,
        [idw.identifier("email", "other@example.test", "email_code")],
        assertion_id=assertion_id,
    )
    assert changed.status_code == 409 and changed.json()["status"] == "conflict"
    assert count(db, IdentityAssertion, IdentityAssertion.client_id == a1) == 1
    receipt = rows(
        db,
        select(IdentityAssertionReceipt).where(
            IdentityAssertionReceipt.assertion_id == assertion_id
        ),
    )[0]
    # Expire the receipt exactly now: a failed proof leaves it unchanged.
    with db.migration.begin() as connection:
        connection.execute(
            update(IdentityAssertionReceipt)
            .where(IdentityAssertionReceipt.id == receipt.id)
            .values(received_at=func.now() - timedelta(hours=25), expires_at=func.now())
        )
    before = rows(
        db, select(IdentityAssertionReceipt).where(IdentityAssertionReceipt.id == receipt.id)
    )[0]
    failed = idw.assertion(
        email,
        proof={
            "subject_token": server["subject_token"],
            "identity_consent_receipt_id": str(uuid4()),
        },
        assertion_id=assertion_id,
    )
    assert failed.json()["reason"] == "proof_invalid"
    unchanged = rows(
        db, select(IdentityAssertionReceipt).where(IdentityAssertionReceipt.id == receipt.id)
    )[0]
    assert (unchanged.fingerprint, unchanged.expires_at) == (before.fingerprint, before.expires_at)
    # Valid new proof after the window: accepted without a uniqueness error; not applied twice.
    renewed = idw.via_server(server, ALL, email, assertion_id=assertion_id)
    accepted(renewed)
    replaced = rows(
        db,
        select(IdentityAssertionReceipt).where(
            IdentityAssertionReceipt.assertion_id == assertion_id
        ),
    )
    assert len(replaced) == 1 and replaced[0].expires_at > before.expires_at
    assert count(db, IdentityAssertion, IdentityAssertion.client_id == a1) == 1
    reasons = rows(
        db,
        select(EventDiagnostic.reason).where(
            EventDiagnostic.client_id == a1,
            EventDiagnostic.channel == "identity",
            EventDiagnostic.outcome == "suppressed",
        ),
    )
    assert reasons == ["assertion_id_reused"]


def test_concurrent_identical_retries_and_new_keys_are_deterministic(idw, db):
    """JV09/JV12: concurrent attempts on one assertion ID and one new key create one row each."""
    a1 = idw.w.a1
    server = idw.server_subject()
    email = [idw.identifier("email", "race@example.test", "email_code")]
    assertion_id = uuid4()
    barrier = threading.Barrier(2)
    results = []

    def attempt():
        client = idw.ingest
        barrier.wait()
        results.append(idw.via_server(server, ALL, email, assertion_id=assertion_id, sender=client))

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(response.status_code for response in results) == [200, 201]
    assert count(db, IdentitySubject, IdentitySubject.client_id == a1) == 1
    # Two different subjects asserting the same new email at once: one person, one key.
    tokens = [idw.server_subject() for _ in range(2)]
    barrier2 = threading.Barrier(2)
    second = []

    def assert_new(subject):
        barrier2.wait()
        second.append(
            idw.via_server(
                subject, ALL, [idw.identifier("email", "same@example.test", "email_code")]
            )
        )

    threads = [threading.Thread(target=assert_new, args=(item,)) for item in tokens]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [response.status_code for response in second] == [201, 201]
    assert count(db, IdentitySubject, IdentitySubject.client_id == a1) == 2
    assert count(db, IdentityKey, IdentityKey.client_id == a1) == 2


def test_provisional_prefix_shared_device_and_two_time_rule(idw, db):
    """R006-27 and design section 4.4 (Sara and Omar on one tablet)."""
    a1 = idw.w.a1
    tablet = idw.browser_subject()["subject_token"]
    p1 = idw.event(tablet)  # pre-identification, inside the identity grant
    accepted(idw.via_browser(tablet, [idw.identifier("email", "sara@example.test", "email_code")]))
    (sara,) = person_ids(db, a1)
    p2 = idw.event(tablet)
    assert idw.journey(sara) == [p1, p2]  # the provisional prefix is adopted
    before_omar = now_utc()
    accepted(idw.via_browser(tablet, [idw.identifier("email", "omar@example.test", "email_code")]))
    sara_, omar = person_ids(db, a1)
    assert sara_ == sara
    p4 = idw.event(tablet, occurred_at=before_omar - timedelta(seconds=1))
    p5 = idw.event(tablet)
    p6 = idw.event(tablet, occurred_at=idw.event_row(p1).first_received_at)
    assert idw.journey(sara) == [p2]  # the prefix is retracted, p2 stays confirmed
    assert idw.journey(omar) == [p5]
    subject = rows(
        db, select(CollectionSubject).where(CollectionSubject.token_digest == digest(tablet))
    )[0]
    assert subject.identity_shared_at is not None and subject.identity_floor_at is not None
    links = rows(
        db,
        select(IdentityLink)
        .where(IdentityLink.collection_subject_id == subject.id)
        .order_by(IdentityLink.asserted_at),
    )
    assert [link.closed_reason for link in links] == ["switched", None]
    assert all(link.provisional_from is None for link in links)
    for event_id in (p4, p6):
        assert event_id not in idw.journey(sara) + idw.journey(omar)
    # Sara returns: a new segment starts at her own assertion; nothing in between reaches her.
    gap = idw.event(tablet)
    accepted(idw.via_browser(tablet, [idw.identifier("email", "sara@example.test", "email_code")]))
    assert gap in idw.journey(omar)
    after = idw.event(tablet)
    assert idw.journey(sara) == [p2, after]


def test_consent_gap_and_late_grant_are_never_adopted(idw, db):
    a1 = idw.w.a1
    choices = {ANALYTICS: "granted", ATTRIBUTION: "granted"}
    token = idw.browser_subject(choices)["subject_token"]
    before_consent = idw.event(token)
    idw.browser_subject({IDENTITY: "granted"}, token=token)
    inside = idw.event(token)
    accepted(idw.via_browser(token, [idw.identifier("email", "gap@example.test", "email_code")]))
    (person,) = person_ids(db, a1)
    assert idw.journey(person) == [inside]
    assert before_consent not in idw.journey(person)


def test_w1_withdrawal_removes_identity_evidence_in_the_consent_transaction(idw, db):
    a1 = idw.w.a1
    token = idw.browser_subject()["subject_token"]
    assertion_id = uuid4()
    code, value = idw.issued_handoff(token)
    email = [idw.identifier("email", "w1@example.test", "email_code")]
    accepted(
        idw.assertion(email, proof={"handoff": code, "challenge": value}, assertion_id=assertion_id)
    )
    (person,) = person_ids(db, a1)
    pending, _ = idw.issued_handoff(token)
    idw.browser_subject({IDENTITY: "withdrawn"}, token=token)
    assert count(db, IdentityLink, IdentityLink.client_id == a1) == 0
    assert count(db, IdentityAssertion, IdentityAssertion.client_id == a1) == 0
    assert count(db, IdentityHandoff, IdentityHandoff.client_id == a1) == 0
    assert count(db, IdentityKey, IdentityKey.client_id == a1) == 0
    assert person_ids(db, a1) == []
    changes = rows(
        db,
        select(IdentityChange)
        .where(IdentityChange.person_id == person)
        .order_by(IdentityChange.seq),
    )
    assert changes[-1].kind == "withdrawn"
    subject = rows(
        db, select(CollectionSubject).where(CollectionSubject.token_digest == digest(token))
    )[0]
    assert subject.identity_floor_at is not None and subject.identity_shared_at is None
    # The retry receipt survives inside its window and answers the same way.
    retry = idw.assertion(
        email, proof={"handoff": code, "challenge": value}, assertion_id=assertion_id
    )
    assert retry.status_code == 200 and retry.json()["status"] == "duplicate"
    assert count(db, IdentityAssertionReceipt, IdentityAssertionReceipt.client_id == a1) == 1
    assert pending is not None
    # A denial through the trusted consent API acts the same way.
    server = idw.server_subject()
    accepted(
        idw.via_server(server, ALL, [idw.identifier("email", "w1b@example.test", "email_code")])
    )
    idw.server_subject({IDENTITY: "denied"}, token=server["subject_token"])
    assert person_ids(db, a1) == []


def test_identical_values_in_two_clients_never_link_or_collide(idw, db):
    """JV02: the same email, request ID and account reference in two clients."""
    a1, a2 = idw.w.a1, idw.w.a2
    assertion_id = uuid4()
    for client_id in (a1, a2):
        server = idw.server_subject(client_id=client_id)
        accepted(
            idw.via_server(
                server,
                ALL,
                [
                    idw.identifier("email", "shared@example.test", "email_code"),
                    idw.identifier("customer_ref", "cust-1", "account_login"),
                ],
                client_id=client_id,
                assertion_id=assertion_id,
            )
        )
    keys = rows(db, select(IdentityKey))
    assert len(keys) == 4
    by_client = {}
    for key in keys:
        by_client.setdefault(key.client_id, set()).add(key.key_bytes)
    assert not by_client[a1] & by_client[a2]
    assert len(person_ids(db, a1)) == len(person_ids(db, a2)) == 1
    secrets = rows(db, select(IdentityKeySecret))
    assert sorted(item.client_id for item in secrets) == sorted([a1, a2])
    # A handoff of client A1 cannot be redeemed with A2's scope.
    token = idw.browser_subject()["subject_token"]
    code, value = idw.issued_handoff(token)
    foreign = idw.assertion(
        [idw.identifier("email", "x@example.test", "email_code")],
        proof={"handoff": code, "challenge": value},
        client_id=a2,
    )
    assert foreign.json()["reason"] == "proof_invalid"


def test_scoped_hold_foreign_key_and_write_once_markers(idw, db):
    """R006-23 and R006-24 at the database level."""
    a1, a2 = idw.w.a1, idw.w.a2
    token = idw.browser_subject()["subject_token"]
    event_id = idw.event(token)
    event = idw.event_row(event_id)
    foreign_id = uuid4()
    with Session(db.migration) as session, session.begin():
        request = SubjectDeletionRequest(
            id=uuid4(),
            agency_id=idw.w.a,
            client_id=a1,
            requester_kind="agency_admin",
            requested_by_user_id=idw.w.users.owner_a,
            status="on_hold",
        )
        foreign = SubjectDeletionRequest(
            id=foreign_id,
            agency_id=idw.w.a,
            client_id=a2,
            requester_kind="agency_admin",
            requested_by_user_id=idw.w.users.owner_a,
            status="on_hold",
        )
        session.add_all([request, foreign])
        session.flush()
        session.add(
            IdentityErasureHold(
                id=uuid4(),
                agency_id=idw.w.a,
                client_id=a1,
                deletion_request_id=request.id,
                collected_event_id=event.id,
                state="held",
                held_at=now_utc(),
            )
        )
    with pytest.raises(IntegrityError):
        with Session(db.migration) as session, session.begin():
            session.add(
                IdentityErasureHold(
                    id=uuid4(),
                    agency_id=idw.w.a,
                    client_id=a2,
                    deletion_request_id=foreign_id,
                    collected_event_id=event.id,
                    state="held",
                    held_at=now_utc(),
                )
            )
    with pytest.raises(IntegrityError):
        with db.runtime.begin() as connection:
            connection.execute(
                text("DELETE FROM collected_events WHERE id = :id"), {"id": event.id}
            )
    assert count(db, CollectedEvent, CollectedEvent.id == event.id) == 1
    with db.runtime.begin() as connection:
        connection.execute(
            update(CollectedEvent)
            .where(CollectedEvent.id == event.id)
            .values(identity_excluded_at=func.now())
        )
    for values in ({"identity_excluded_at": None}, {"first_received_at": func.now()}):
        with pytest.raises(DBAPIError):
            with db.migration.begin() as connection:
                connection.execute(
                    update(CollectedEvent).where(CollectedEvent.id == event.id).values(**values)
                )
    subject = event.subject_id
    with db.runtime.begin() as connection:
        connection.execute(
            update(CollectionSubject)
            .where(CollectionSubject.id == subject)
            .values(identity_floor_at=func.now(), identity_shared_at=func.now())
        )
    for values in (
        {"identity_floor_at": func.now() - timedelta(days=1)},
        {"identity_shared_at": func.now()},
        {"issuance_channel": "server"},
    ):
        with pytest.raises(DBAPIError):
            with db.migration.begin() as connection:
                connection.execute(
                    update(CollectionSubject)
                    .where(CollectionSubject.id == subject)
                    .values(**values)
                )


def test_runtime_and_lifecycle_privileges(idw, db, lifecycle_engine):
    token = idw.browser_subject()["subject_token"]
    accepted(idw.via_browser(token, [idw.identifier("email", "priv@example.test", "email_code")]))
    denied = [
        (db.runtime, "UPDATE collection_subjects SET issuance_channel = 'server'"),
        (db.runtime, "DELETE FROM identity_assertion_receipts"),
        (db.runtime, "UPDATE identity_changes SET kind = 'linked'"),
        (db.runtime, "UPDATE identity_keys SET key_bytes = key_bytes"),
        (lifecycle_engine, "SELECT ciphertext FROM identity_key_secrets"),
        (lifecycle_engine, "SELECT match_key FROM deletion_tombstones"),
        (lifecycle_engine, "UPDATE identity_keys SET key_bytes = key_bytes"),
    ]
    for engine, statement in denied:
        with pytest.raises(DBAPIError) as caught:
            with engine.begin() as connection:
                connection.execute(text(statement))
        assert "permission denied" in str(caught.value.orig).lower()
