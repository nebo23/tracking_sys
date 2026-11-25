"""Independent review of the combined 006 and 007-B/C branch at 8b03b1c (2026-11-25).

Each case asserts the approved behavior and fails on the reviewed implementation; they are
review regressions, not fixes. Synthetic values on the disposable database only. Finding IDs
refer to reports/specs-006-007-joint-review-2026-11-25.md.
"""

import os
import time
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from identity_support import IDENTITY, count, make_identity_world, rows
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from test_identity_admin import email, erase, merge, ok, people, resolve, reverse, shared_tablet
from test_ledger_persistence import _csv, ledger, put, record, stored
from test_revenue_identity import associate, bindings, only_person, person, profile, sale

import app.services.identity_admin as identity_admin
from app.ledger_backfill import backfill
from app.models import (
    CollectedEvent,
    CollectionSubject,
    IdentityAssertion,
    IdentityKey,
    IdentityLink,
    IdentitySubject,
    LedgerMovement,
    LedgerProjectionState,
    LedgerReceipt,
    LedgerTransaction,
    RevenueIdentityBinding,
)
from app.security import digest
from app.services import declarations, ledger_store
from app.services.lifecycle import run_lifecycle
from app.services.revenue import append_evidence, lock_revenue

pytestmark = pytest.mark.integration


@pytest.fixture
def idw(authenticated_world, api):
    return make_identity_world(authenticated_world, api)


def version(idw, person_id):
    path = f"{idw.base}/clients/{idw.w.a1}/identity/subjects/{person_id}"
    return idw.owner.get(path).json()["version"]


def unprojected(w, operation, received_at=None):
    """Store one capture the way a CSV commit above 200 rows does (project=False)."""
    with Session(w.db.runtime) as session, session.begin():
        clock = lock_revenue(session, w.a1)
        item = replace(record(w, operation, minor=5_000), received_at=received_at or clock)
        append_evidence(session, item, "csv_import", uuid4(), project=False)


def age_identity_evidence(db, person_id, days=400):
    with db.migration.connect() as connection:
        old = connection.execute(select(func.now())).scalar_one() - timedelta(days=days)
    subject = rows(
        db, select(IdentityLink.collection_subject_id).where(IdentityLink.subject_id == person_id)
    )[0]
    with db.migration.begin() as connection:
        connection.execute(
            update(IdentityLink)
            .where(IdentityLink.collection_subject_id == subject)
            .values(asserted_at=old, eligible_from=old, provisional_from=None, grant_started_at=old)
        )
        connection.execute(
            update(IdentityAssertion)
            .where(IdentityAssertion.collection_subject_id == subject)
            .values(received_at=old)
        )


# --- P1 ------------------------------------------------------------------------------------


def test_review_r0607_01_withdrawal_of_the_last_ambiguous_candidate(idw, db):
    family = lambda: idw.identifier("email", "family@example.test", "email_code")  # noqa: E731
    a, b, c = (idw.browser_subject()["subject_token"] for _ in range(3))
    ok(idw.via_browser(a, [family(), idw.identifier("customer_ref", "c-2001", "account_login")]))
    ok(idw.via_browser(b, [family(), idw.identifier("customer_ref", "c-2002", "account_login")]))
    ok(idw.via_browser(c, [family()]))  # R5: an ambiguous segment with candidates A and B
    withdraw = {"choices": {IDENTITY: "withdrawn"}}
    assert idw.public_post("consent", {**withdraw, "subject_token": a}).status_code == 200
    last = idw.public_post("consent", {**withdraw, "subject_token": b})
    assert last.status_code == 200, last.text  # observed: 409 state_conflict, nothing recorded
    # A later assertion of the contested email names nobody: a neutral segment, accepted.
    d = idw.browser_subject()["subject_token"]
    later = idw.via_browser(d, [family()])
    assert later.status_code == 201, later.text
    subject = rows(db, select(CollectionSubject).where(CollectionSubject.token_digest == digest(d)))
    statuses = rows(
        db, select(IdentityLink.status).where(IdentityLink.collection_subject_id == subject[0].id)
    )
    assert statuses == ["neutral"]


def test_review_r0607_01_erasure_of_the_last_ambiguous_candidate(idw, db):
    _, _, omar, ali, _, _, _ = shared_tablet(idw, db)
    assert erase(idw, subject_id=str(omar)).status_code == 201
    second = erase(idw, subject_id=str(ali))
    assert second.status_code == 201, second.text  # observed: 409 state_conflict
    assert ali not in people(db, idw.w.a1) or second.json()["status"] == "on_hold"


def test_review_r0607_02_erasure_keeps_another_persons_reassigned_device(idw, db):
    w = idw.w
    d1 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d1, [email(idw, "ali@example.test")]))
    d2 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d2, [idw.identifier("phone", "+20 10 0000 0202", "phone_code")]))
    s7, s8 = people(db, w.a1)
    edge = ok(merge(idw, s7, s8, versions=(version(idw, s7), version(idw, s8))))
    d4 = idw.browser_subject()["subject_token"]
    ok(
        idw.via_browser(
            d4,
            [
                email(idw, "ali@example.test", "account_verified_email"),
                idw.identifier("phone", "+20 10 0000 0202", "account_verified_phone"),
                idw.identifier("customer_ref", "cust-3001", "account_login"),
            ],
        )
    )
    ok(
        idw.via_browser(
            d1,
            [
                idw.identifier("phone", "+20 10 0000 0202", "account_verified_phone"),
                idw.identifier("customer_ref", "cust-3001", "account_login"),
            ],
        )
    )
    ok(reverse(idw, edge["merge_id"], (version(idw, s7), version(idw, s8))))
    hers = idw.event(d1)
    assert hers in idw.journey(s8)
    ok(erase(idw, subject_id=str(s7)))
    # Observed: S8's event and the whole device subject are deleted with S7.
    assert count(db, CollectedEvent, CollectedEvent.event_id == hers) == 1
    assert hers in idw.journey(s8)


def test_review_r0607_02_unmerge_marks_the_device_shared(idw, db):
    w = idw.w
    mine = lambda m="email_code": idw.identifier("email", "s7@example.test", m)  # noqa: E731
    theirs = lambda m="phone_code": idw.identifier("phone", "+20 10 0000 0808", m)  # noqa: E731
    ok(idw.via_browser(idw.browser_subject()["subject_token"], [mine()]))
    ok(idw.via_browser(idw.browser_subject()["subject_token"], [theirs()]))
    s7, s8 = people(db, w.a1)
    tablet = idw.browser_subject()["subject_token"]
    early = idw.event(tablet)
    ok(idw.via_browser(tablet, [mine()]))
    edge = ok(merge(idw, s7, s8, versions=(version(idw, s7), version(idw, s8))))
    ok(idw.via_browser(tablet, [mine("account_verified_email"), theirs("account_verified_phone")]))
    later = idw.event(tablet)
    ok(reverse(idw, edge["merge_id"], (version(idw, s7), version(idw, s8))))
    subject = rows(
        db, select(CollectionSubject).where(CollectionSubject.token_digest == digest(tablet))
    )[0]
    assert subject.identity_shared_at is not None  # observed: None with an ambiguous segment
    assert early not in idw.journey(s7)
    request = ok(erase(idw, subject_id=str(s7)))
    assert request["status"] == "on_hold"  # observed: completed, deleting the ambiguous event
    assert count(db, CollectedEvent, CollectedEvent.event_id == later) == 1


def test_review_r0607_03_expiry_of_an_associated_assertion(
    idw, db, lifecycle_engine, lifecycle_settings
):
    w = idw.w
    _, assertion = person(idw, "old-buyer@example.test")
    (buyer,) = only_person(w)
    sale(w, "S1")
    assert associate(idw, assertion, "S1").status_code == 201
    age_identity_evidence(db, buyer)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)  # observed: ForeignKeyViolation
    assert result["status"] == "completed", result
    (binding,) = rows(db, select(RevenueIdentityBinding))
    assert binding.assertion_ref is None and binding.owner_subject_id is None
    assert binding.state == "unlinked"


# --- P2 ------------------------------------------------------------------------------------


def test_review_r0607_04_a_conflicting_owner_never_takes_over(idw):
    w = idw.w
    _, first = person(idw, "one@example.test")
    _, second = person(idw, "two@example.test")
    one, two = rows(w.db, select(IdentitySubject.id).order_by(IdentitySubject.created_at))
    sale(w, "S1")
    assert associate(idw, first, "S1").status_code == 201
    assert associate(idw, second, "S1", expected=1).status_code == 201
    associate(idw, second, "S1", expected=2)
    last = bindings(w)[-1]
    assert not (last.state == "active" and last.owner_subject_id == two)
    assert profile(idw, two)["customer_qualification"] != "customer"


def test_review_r0607_05_no_restore_after_attribution_returns(idw):
    w = idw.w
    subject, assertion = person(idw, "attr@example.test")
    sale(w, "S2")
    assert associate(idw, assertion, "S2").status_code == 201
    early = uuid4()
    associate(idw, assertion, "S2", request_id=early, expected=1)
    idw.server_subject({"attribution": "withdrawn"}, token=subject["subject_token"])
    withdrawn = bindings(w)[-1]
    assert withdrawn.state == "unlinked"
    idw.server_subject({"attribution": "granted"}, token=subject["subject_token"])
    associate(idw, assertion, "S2", request_id=early, expected=withdrawn.revision)
    assert bindings(w)[-1].state != "active"  # observed: revision 2 active from the old proof


def test_review_r0607_06_the_association_answer_hides_an_objection(idw):
    w = idw.w
    person(idw, "objector@example.test")
    (objector,) = only_person(w)
    ok(erase(idw, subject_id=str(objector), objected=True))
    _, again = person(idw, "objector@example.test")
    _, fresh = person(idw, "fresh@example.test")
    objected = associate(idw, again, "S-unknown-1")
    control = associate(idw, fresh, "S-unknown-2")
    assert objected.status_code == control.status_code  # observed: 422 against 201


def test_review_r0607_07_withdrawn_keys_and_people_do_not_link_again(idw, db):
    a1 = idw.w.a1
    x, y = (idw.browser_subject()["subject_token"] for _ in range(2))
    mona = lambda: email(idw, "mona@example.test")  # noqa: E731
    phone = lambda: idw.identifier("phone", "+20 10 0000 0101", "phone_code")  # noqa: E731
    ok(idw.via_browser(x, [mona(), phone()]))
    ok(idw.via_browser(y, [mona()]))
    idw.browser_subject({IDENTITY: "withdrawn"}, token=x)
    assert count(db, IdentityKey, IdentityKey.client_id == a1, IdentityKey.kind == "phone") == 0


def test_review_r0607_07_a_person_kept_only_by_a_withdrawn_device_is_removed(idw, db):
    a1 = idw.w.a1
    d1, d2, d3 = (idw.browser_subject()["subject_token"] for _ in range(3))
    ok(idw.via_browser(d1, [email(idw, "x@example.test")]))
    ok(idw.via_browser(d2, [idw.identifier("phone", "+20 10 0000 0303", "phone_code")]))
    _, y = people(db, a1)
    both = [
        email(idw, "x@example.test", "account_verified_email"),
        idw.identifier("phone", "+20 10 0000 0303", "account_verified_phone"),
    ]
    ok(idw.via_browser(d3, both))  # R4: ambiguous
    idw.browser_subject({IDENTITY: "withdrawn"}, token=d2)
    idw.browser_subject({IDENTITY: "withdrawn"}, token=d3)
    assert y not in people(db, a1)


def test_review_r0607_08_a_paused_objection_survives_withdrawal(idw, db):
    w = idw.w
    d1, d2 = (idw.browser_subject()["subject_token"] for _ in range(2))
    ok(idw.via_browser(d1, [email(idw, "p1@example.test")]))
    ok(idw.via_browser(d2, [email(idw, "p2@example.test")]))
    a, b = people(db, w.a1)
    ok(merge(idw, a, b))
    paused = ok(erase(idw, subject_id=str(b), objected=True))
    idw.browser_subject({IDENTITY: "withdrawn"}, token=d2)
    resolution = resolve(idw, paused["id"], subject_id=str(b))
    assert resolution.status_code != 403, resolution.text
    before = len(people(db, w.a1))
    ok(idw.via_browser(idw.browser_subject()["subject_token"], [email(idw, "p2@example.test")]))
    assert len(people(db, w.a1)) == before  # observed: a new person despite the objection


def test_review_r0607_09_customer_status_while_the_projection_is_behind(idw):
    w = idw.w
    _, assertion = person(idw, "buyer@example.test")
    (buyer,) = only_person(w)
    sale(w, "S1")
    assert associate(idw, assertion, "S1").status_code == 201
    unprojected(w, "S2")
    assert idw.owner.get(f"{idw.base}/clients/{w.a1}/revenue").status_code == 503
    response = idw.owner.get(f"{idw.base}/clients/{w.a1}/identity/subjects/{buyer}")
    # Fail closed or an explicit unavailable state; observed: 200 with "not_customer".
    assert response.status_code == 503 or response.json()["customer_qualification"] not in (
        "not_customer",
    )


def test_review_r0607_09_customer_status_during_a_concurrent_receipt(idw, monkeypatch):
    w = idw.w
    _, assertion = person(idw, "buyer@example.test")
    (buyer,) = only_person(w)
    sale(w, "S1")
    assert associate(idw, assertion, "S1").status_code == 201
    original = ledger_store.require_current
    fired = []

    def racing(session, agency_id, client_id, evidence_rows):
        if not fired:
            fired.append(True)
            sale(w, "S2")
        return original(session, agency_id, client_id, evidence_rows)

    monkeypatch.setattr(ledger_store, "require_current", racing)
    body = profile(idw, buyer)
    assert fired and body["customer_qualification"] == "customer"  # observed: not_customer


def test_review_r0607_10_an_account_switch_keeps_the_first_buyer(idw):
    """Pending the owner's reading of "presently valid ownership segment" (J10)."""
    w = idw.w
    tablet = idw.browser_subject()["subject_token"]
    first = uuid4()
    ok(idw.via_browser(tablet, [email(idw, "a@example.test")], assertion_id=first))
    (buyer,) = only_person(w)
    sale(w, "S1")
    assert associate(idw, first, "S1").status_code == 201
    ok(idw.via_browser(tablet, [email(idw, "b@example.test")]))
    assert profile(idw, buyer)["customer_qualification"] == "customer"  # observed: not_customer


@pytest.mark.skipif(
    os.environ.get("TRACKING_REVIEW_MEASURE") != "1", reason="Set TRACKING_REVIEW_MEASURE=1."
)
def test_review_r0607_11_a_200_row_commit_on_a_client_with_history(world):
    """Measurement (no SLO): 1,000 stored rows, then a 200-row CSV commit."""
    w = world
    with Session(w.db.runtime) as session, session.begin():
        clock = lock_revenue(session, w.a1)
        for index in range(1000):
            item = replace(record(w, f"B{index}", minor=100 + index), received_at=clock)
            append_evidence(session, item, "csv_import", uuid4(), project=False)
    with Session(w.db.migration) as session, session.begin():
        for model in (LedgerMovement, LedgerReceipt, LedgerTransaction, LedgerProjectionState):
            session.query(model).filter(model.client_id == w.a1).delete()
    assert backfill(w.db.migration, w.a, w.a1, batch_size=200) == "published"
    body = _csv(
        *(f"NEW-{index},sale,1.00,EGP,2026-11-01T00:00:00Z,,,declared" for index in range(200))
    )
    started = time.perf_counter()
    with Session(w.db.runtime) as session, session.begin():
        declarations.DeclarationService(session, w.users.owner_a).commit(
            w.a, w.a1, declarations.file_digest(body), body
        )
    elapsed = time.perf_counter() - started
    print("R0607-11 commit seconds", round(elapsed, 1))  # observed 43.3 s on the review host
    assert elapsed < 3


# --- P3 ------------------------------------------------------------------------------------


def test_review_r0607_12_a_receipt_committed_between_ledger_reads(idw, monkeypatch):
    w = idw.w
    sale(w, "S1")
    original = ledger_store.stored_movements
    fired = []

    def racing(session, state, evidence):
        if not fired:
            fired.append(True)
            sale(w, "S2")
        return original(session, state, evidence)

    monkeypatch.setattr(ledger_store, "stored_movements", racing)
    response = idw.owner.get(f"{idw.base}/clients/{w.a1}/revenue")  # observed: KeyError
    assert response.status_code in (200, 503)


def test_review_r0607_13_a_clock_behind_the_log_is_retryable(authenticated_world, monkeypatch):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    url = f"/agencies/{w.a}/clients/{w.a1}/revenue-declarations"
    body = {
        "operation_id": "M-1",
        "kind": "sale",
        "amount": "75.00",
        "currency": "EGP",
        "effective_at": "2026-11-20T09:00:00+02:00",
        "reason": "Paid in cash at the office",
    }
    assert owner.post(url, json=body).status_code == 201
    original = declarations.lock_revenue
    monkeypatch.setattr(
        declarations, "lock_revenue", lambda s, c: original(s, c) - timedelta(hours=1)
    )
    second = owner.post(url, json={**body, "operation_id": "M-2"})
    assert second.status_code == 503, second.text  # observed: 422 validation_failed


def test_review_r0607_13_an_out_of_order_row_is_never_served_without_a_receipt(world):
    w = world
    put(w, [record(w, "S1"), record(w, "S2"), record(w, "S3")])
    earliest = stored(w)[0].received_at
    unprojected(w, "X", received_at=earliest + timedelta(microseconds=1))
    put(w, [record(w, "S4")])
    with Session(w.db.migration) as session:
        receipts = session.scalar(
            select(func.count()).select_from(LedgerReceipt).where(LedgerReceipt.client_id == w.a1)
        )
    try:
        ledger(w)
        served = True
    except ledger_store.LedgerUnavailable:
        served = False
    assert not served or receipts == len(stored(w))  # observed: served with 4 of 5 receipts


def test_review_r0607_14_finance_is_rechecked_before_release(idw, monkeypatch):
    w = idw.w
    grant = f"{idw.base}/members/{w.analyst}/clients/{w.a1}"
    both = {"can_view_financials": True, "can_view_identities": True}
    assert idw.owner.put(grant, json=both).status_code == 204
    analyst = w.signed_in("analyst")
    _, assertion = person(idw, "buyer@example.test")
    (buyer,) = only_person(w)
    sale(w, "S1")
    assert associate(idw, assertion, "S1").status_code == 201
    original = identity_admin.customer_status

    def revoking(session, client_id, group, reader):
        result = original(session, client_id, group, reader)
        with w.db.migration.begin() as connection:
            connection.execute(
                text(
                    "UPDATE client_grants SET can_view_financials = false "
                    "WHERE membership_id = :m AND client_id = :c"
                ),
                {"m": w.analyst, "c": w.a1},
            )
        return result

    monkeypatch.setattr(identity_admin, "customer_status", revoking)
    response = analyst.get(f"{idw.base}/clients/{w.a1}/identity/subjects/{buyer}")
    assert response.status_code == 403 or response.json()["customer_qualification"] != "customer"


def test_review_r0607_15_unmerge_keeps_the_sale_with_its_original_owner(idw):
    w = idw.w
    mine = lambda m="email_code": idw.identifier("email", "a7@example.test", m)  # noqa: E731
    theirs = lambda m="phone_code": idw.identifier("phone", "+20 10 0000 0909", m)  # noqa: E731
    ref = lambda: idw.identifier("customer_ref", "cust-9009", "account_login")  # noqa: E731
    ok(idw.via_browser(idw.browser_subject()["subject_token"], [mine()]))
    ok(idw.via_browser(idw.browser_subject()["subject_token"], [theirs()]))
    a, b = rows(w.db, select(IdentitySubject.id).order_by(IdentitySubject.created_at))
    edge = ok(merge(idw, b, a, versions=(version(idw, b), version(idw, a))))
    device = idw.browser_subject()["subject_token"]
    ok(
        idw.via_browser(
            device, [mine("account_verified_email"), theirs("account_verified_phone"), ref()]
        )
    )
    proof = uuid4()
    ok(idw.via_browser(idw.browser_subject()["subject_token"], [mine(), ref()], assertion_id=proof))
    sale(w, "S1")
    assert associate(idw, proof, "S1").status_code == 201
    ok(reverse(idw, edge["merge_id"], (version(idw, b), version(idw, a))))
    owners = (profile(idw, a)["customer_qualification"], profile(idw, b)["customer_qualification"])
    assert "customer" in owners  # observed: neither person keeps the sale


def test_review_r0607_17_conflicting_deliveries_have_distinct_issues(authenticated_world):
    w = authenticated_world
    put(
        w,
        [
            record(w, "Q1", minor=10_000),
            record(w, "Q1", minor=10_001, delivery="d:a"),
            record(w, "Q1", minor=10_002, delivery="d:b"),
        ],
    )
    body = w.signed_in("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/revenue/reconciliation")
    identifiers = [item["issue_id"] for item in body.json()["issues"]]
    assert len(identifiers) == len(set(identifiers))  # observed: two issues share one ID


def test_review_r0607_18_a_backfill_with_the_wrong_agency_changes_nothing(world):
    w = world
    put(w, [record(w, "S1")])
    result = backfill(w.db.migration, w.b, w.a1)
    try:
        ledger(w)
        available = True
    except ledger_store.LedgerUnavailable:
        available = False
    assert result != "published" and available  # observed: published, reads then 503


def test_review_r0607_19_an_erased_candidate_leaves_no_reference(idw, db):
    _, _, omar, _, _, _, _ = shared_tablet(idw, db)
    request = ok(erase(idw, subject_id=str(omar)))
    ok(resolve(idw, request["id"], unresolved_events="erase"), 200)
    with db.migration.connect() as connection:
        for table in ("identity_keys", "identity_assertions", "identity_links"):
            hits = connection.execute(
                text(f"SELECT count(*) FROM {table} t WHERE t::text LIKE :needle"),
                {"needle": f"%{omar}%"},
            ).scalar_one()
            assert hits == 0, table  # observed: one link and one assertion still name him
