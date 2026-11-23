"""Specification 007-C sale-to-person association on disposable PostgreSQL (D-075 J10, J5, J6).

JV18: a verified sale and qualified trusted proof link exactly once; unknown sales stay
pending; another credential, client or source account never links; a conflicting owner stays
ambiguous; financial rows stay byte-identical. JV19: erasure and withdrawal clear every
identifying pointer of current and closed revisions (F1) and old requests cannot reattach.
JV20: customer qualification follows verified associated captures, survives a full refund and
needs both permissions. JV21: actual persisted journeys and sales drive the existing 008-A
engine through refunds, merges and erasure. Synthetic values only.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from identity_support import ALL, IDENTITY, make_identity_world, rows
from report_support import append
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.attribution import AttributionModel, ModelVersion, RevisionCause, attribute
from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind
from app.models import (
    AuditEvent,
    IdentitySubject,
    LedgerMovement,
    LedgerReceipt,
    RevenueEvidence,
    RevenueIdentityBinding,
    SubjectDeletionRequest,
)
from app.services.attribution_inputs import sale_conversions, touchpoints

pytestmark = pytest.mark.integration

EGP = Currency("EGP", 2)


@pytest.fixture
def idw(authenticated_world, api):
    return make_identity_world(authenticated_world, api)


def sale(
    w,
    operation,
    minor=10_000,
    *,
    kind=OperationKind.SALE,
    parent=None,
    account="shop",
    when=None,
    client=None,
):
    moment = when or datetime(2026, 11, 20, tzinfo=UTC)
    classes = {
        OperationKind.SALE: EvidenceClass.CONFIRMED_CAPTURE,
        OperationKind.REFUND: EvidenceClass.CONFIRMED_ADJUSTMENT,
    }
    item = Evidence(
        f"d:{operation}:{kind.value}:{minor}",
        w.a,
        client or w.a1,
        account,
        operation,
        kind,
        classes[kind],
        Money(minor, EGP),
        moment,
        moment,
        parent_operation_id=parent,
    )
    append(w, [item], intake="csv_import")


def person(idw, value, choices=None):
    choices = choices or ALL
    subject = idw.server_subject(choices)
    assertion_id = uuid4()
    response = idw.via_server(
        subject, choices, [idw.identifier("email", value, "email_code")], assertion_id=assertion_id
    )
    assert response.status_code == 201, response.text
    return subject, assertion_id


def associate(
    idw,
    assertion_id,
    operation,
    *,
    request_id=None,
    account="shop",
    expected=None,
    sender=None,
    client=None,
):
    return (sender or idw.ingest).post(
        f"{idw.base}/clients/{client or idw.w.a1}/revenue/identity-associations",
        json={
            "request_id": str(request_id or uuid4()),
            "source_account_id": account,
            "sale_operation_id": operation,
            "assertion_id": str(assertion_id),
            "expected_revision": expected,
        },
    )


def bindings(w):
    return rows(
        w.db,
        select(RevenueIdentityBinding).order_by(
            RevenueIdentityBinding.received_at, RevenueIdentityBinding.revision
        ),
    )


def financial_snapshot(w):
    with Session(w.db.migration) as session:
        return (
            [
                tuple(row)
                for row in session.execute(
                    select(
                        RevenueEvidence.id,
                        RevenueEvidence.content_digest,
                        RevenueEvidence.amount_minor,
                    ).order_by(RevenueEvidence.sequence)
                )
            ],
            [
                tuple(row)
                for row in session.execute(
                    select(LedgerReceipt.id, LedgerReceipt.receipt_digest).order_by(
                        LedgerReceipt.id
                    )
                )
            ],
            [
                tuple(row)
                for row in session.execute(
                    select(LedgerMovement.id, LedgerMovement.amount_minor).order_by(
                        LedgerMovement.id
                    )
                )
            ],
        )


def profile(idw, person_id, client=None):
    response = (client or idw.owner).get(
        f"{idw.base}/clients/{idw.w.a1}/identity/subjects/{person_id}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def only_person(w):
    return rows(w.db, select(IdentitySubject.id))


def test_verified_sale_links_once_and_never_changes_money(idw):
    w = idw.w
    _, assertion = person(idw, "buyer@example.test")
    (buyer,) = only_person(w)
    sale(w, "S1")
    before = financial_snapshot(w)
    request_id = uuid4()
    first = associate(idw, assertion, "S1", request_id=request_id)
    assert (first.status_code, first.json()) == (
        201,
        {"status": "accepted", "request_id": str(request_id)},
    )
    assert associate(idw, assertion, "S1", request_id=request_id).status_code == 200
    changed = associate(idw, assertion, "S1", request_id=request_id, account="other")
    assert changed.status_code == 409
    (binding,) = bindings(w)
    assert (binding.state, binding.owner_subject_id, binding.revision) == ("active", buyer, 1)
    assert financial_snapshot(w) == before
    body = profile(idw, buyer)
    assert body["stage"] == "customer" and body["customer_qualification"] == "customer"
    revenue = idw.owner.get(f"{idw.base}/clients/{w.a1}/identity/subjects/{buyer}/revenue").json()
    assert [(item["sale_operation_id"], item["net_minor"]) for item in revenue["sales"]] == [
        ("S1", 10_000)
    ]
    # Unknown sale: pending, no stage; the later verified sale qualifies on the next read.
    assert associate(idw, assertion, "S-later").status_code == 201
    pending = [b for b in bindings(w) if b.sale_operation_id == "S-later"][0]
    assert pending.state == "pending"
    # A sale of another source account with the same operation ID never links to "shop".
    sale(w, "S2", account="other-account")
    associate(idw, assertion, "S2")
    s2 = [b for b in bindings(w) if b.sale_operation_id == "S2"][0]
    assert s2.state == "pending"


def test_wrong_credential_client_or_proof_never_links(idw, api):
    w = idw.w
    _, assertion = person(idw, "proof@example.test")
    sale(w, "S1")
    issued = idw.owner.post(
        idw.base + "/service-credentials",
        json={
            "name": "Other ingest",
            "kind": "ingest",
            "clients": [{"client_id": str(w.a1)}, {"client_id": str(w.a2)}],
        },
    )
    other = api.new_client()
    other.headers["Authorization"] = "Bearer " + issued.json()["key"]
    refused = associate(idw, assertion, "S1", sender=other)
    assert (refused.status_code, refused.json()["reason"]) == (422, "proof_invalid")
    foreign = associate(idw, assertion, "S1", client=w.a2)
    assert foreign.status_code == 422
    assert associate(idw, uuid4(), "S1").status_code == 422
    assert bindings(w) == []
    # A read key cannot associate.
    read = idw.owner.post(
        idw.base + "/service-credentials",
        json={"name": "Reader", "clients": [{"client_id": str(w.a1)}]},
    )
    reader = api.new_client()
    reader.headers["Authorization"] = "Bearer " + read.json()["key"]
    assert associate(idw, assertion, "S1", sender=reader).status_code in {401, 403}


def test_conflicting_owner_stays_ambiguous_and_manager_detaches(idw):
    w = idw.w
    _, first = person(idw, "one@example.test")
    _, second = person(idw, "two@example.test")
    one, two = rows(w.db, select(IdentitySubject.id).order_by(IdentitySubject.created_at))
    sale(w, "S1")
    assert associate(idw, first, "S1").status_code == 201
    stale = associate(idw, second, "S1")
    assert (stale.status_code, stale.json()["reason"]) == (409, "revision_conflict")
    assert associate(idw, second, "S1", expected=1).status_code == 201
    current = bindings(w)[-1]
    assert (current.state, current.reason, current.revision) == (
        "ambiguous",
        "conflicting_owner",
        2,
    )
    assert profile(idw, one)["customer_qualification"] == "not_customer"
    assert profile(idw, two)["customer_qualification"] == "not_customer"
    association = current.association_id
    url = f"{idw.base}/clients/{w.a1}/revenue/identity-associations/{association}/detach"
    body = {
        "operation_id": str(uuid4()),
        "expected_revision": 2,
        "reason_code": "mistaken_association",
    }
    assert w.signed_in("analyst").post(url, json=body).status_code == 403
    detached = idw.owner.post(url, json=body)
    assert detached.status_code == 201, detached.text
    assert idw.owner.post(url, json=body).status_code == 200
    assert idw.owner.post(url, json={**body, "operation_id": str(uuid4())}).status_code == 409
    assert bindings(w)[-1].state == "detached"
    assert rows(
        w.db, select(AuditEvent.action).where(AuditEvent.action == "revenue.association_detached")
    ) == ["revenue.association_detached"]


def test_withdrawal_and_erasure_unlink_every_revision(idw):
    w = idw.w
    subject, assertion = person(idw, "gone@example.test")
    (gone,) = only_person(w)
    sale(w, "S1")
    sale(w, "S2")
    old_request = uuid4()
    associate(idw, assertion, "S1", request_id=old_request)
    association = bindings(w)[0].association_id
    idw.owner.post(
        f"{idw.base}/clients/{w.a1}/revenue/identity-associations/{association}/detach",
        json={
            "operation_id": str(uuid4()),
            "expected_revision": 1,
            "reason_code": "data_correction",
        },
    )
    associate(idw, assertion, "S1", expected=2)  # a later revision, the first one is closed
    associate(idw, assertion, "S-pending")
    before = financial_snapshot(w)
    request = idw.owner.post(
        f"{idw.base}/clients/{w.a1}/identity/erasures", json={"subject_id": str(gone)}
    )
    assert request.status_code == 201, request.text
    assert request.json()["target_outcomes"]["financial_associations"] == "done"
    for row in bindings(w):
        assert row.owner_subject_id is None and row.assertion_ref is None
        assert row.collection_subject_id is None and row.key_ids == []
        if row.state != "detached":
            assert (
                row.state == "unlinked"
                and row.request_id is None
                and row.request_fingerprint is None
            )
    assert financial_snapshot(w) == before
    replay = associate(idw, assertion, "S1", request_id=old_request, expected=3)
    assert replay.status_code == 422  # the erased proof cannot restore a binding
    # Attribution withdrawal alone also unlinks (the second permission of J10).
    subject2, assertion2 = person(idw, "attr@example.test")
    associate(idw, assertion2, "S2")
    idw.server_subject({"attribution": "withdrawn"}, token=subject2["subject_token"])
    latest = [b for b in bindings(w) if b.sale_operation_id == "S2"][-1]
    assert (latest.state, latest.reason) == ("unlinked", "attribution_withdrawn")
    assert (
        associate(idw, assertion2, "S2", expected=latest.revision).json()["reason"]
        == "proof_invalid"
    )


def test_customer_qualification_survives_a_full_refund_and_needs_both_permissions(idw):
    w = idw.w
    subject, assertion = person(idw, "lead@example.test")
    idw.event(subject["subject_token"], event_type="lead_signal", trusted=True)
    (lead,) = only_person(w)
    assert profile(idw, lead)["stage"] == "lead"
    sale(w, "S1", 5_000)
    associate(idw, assertion, "S1")
    assert profile(idw, lead)["stage"] == "customer"
    sale(w, "R1", 5_000, kind=OperationKind.REFUND, parent="S1")
    revenue = idw.owner.get(f"{idw.base}/clients/{w.a1}/identity/subjects/{lead}/revenue").json()
    assert revenue["sales"][0]["net_minor"] == 0 and revenue["customer_qualification"] == "customer"
    assert profile(idw, lead)["stage"] == "customer"  # the purchase fact stays historical
    grant = f"{idw.base}/members/{w.analyst}/clients/{w.a1}"
    analyst = w.signed_in("analyst")
    assert idw.owner.put(grant, json={"can_view_identities": True}).status_code == 204
    limited = profile(idw, lead, client=analyst)
    assert (
        limited["customer_qualification"] == "permission_unavailable" and limited["stage"] == "lead"
    )
    route = f"{idw.base}/clients/{w.a1}/identity/subjects/{lead}/revenue"
    assert analyst.get(route).status_code == 403  # identity without finance
    assert (
        idw.owner.put(
            grant, json={"can_view_financials": True, "can_view_identities": False}
        ).status_code
        == 204
    )
    assert analyst.get(route).status_code == 403  # finance without identity
    assert (
        idw.owner.put(
            grant, json={"can_view_financials": True, "can_view_identities": True}
        ).status_code
        == 204
    )
    assert analyst.get(route).status_code == 200


def test_persisted_inputs_drive_the_008_engine(idw):
    """JV21: First, Last and Linear over the real journey and ledger; refunds, merges and
    erasure replace the inputs without changing money or resurrecting a removed person."""
    w = idw.w
    token = idw.browser_subject()["subject_token"]
    early = idw.event(token, payload={"url": "https://shop.example.test/a?utm_campaign=spring"})
    late = idw.event(token, payload={"url": "https://shop.example.test/b?utm_campaign=autumn"})
    server = idw.server_subject()
    code_response = idw.via_browser(
        token, [idw.identifier("email", "journey@example.test", "email_code")]
    )
    assert code_response.status_code == 201
    assertion = uuid4()
    assert (
        idw.via_server(
            server,
            ALL,
            [idw.identifier("email", "journey@example.test", "email_code")],
            assertion_id=assertion,
        ).status_code
        == 201
    )
    (buyer,) = only_person(w)
    sale(w, "S1", 9_999, when=datetime.now(UTC))
    assert associate(idw, assertion, "S1").status_code == 201

    def inputs():
        with Session(w.db.runtime) as session:
            moment = session.scalar(select(func.clock_timestamp()))
            touches = touchpoints(session, w.a, w.a1, buyer, moment)
            conversions = sale_conversions(session, w.a, w.a1, buyer, moment)
            return touches, conversions

    touches, conversions = inputs()
    assert {t.touchpoint_id for t in touches} == {str(early), str(late)}
    ((conversion, state),) = conversions
    runs = {}
    for model in AttributionModel:
        version = ModelVersion(f"v-{model.value}", model)
        runs[model] = attribute(conversion, touches, version, sale=state, ledger_position=1)
    first = {
        a.touch.campaign_ref: a.amount.minor for a in runs[AttributionModel.FIRST_CLICK].allocations
    }
    last = {
        a.touch.campaign_ref: a.amount.minor for a in runs[AttributionModel.LAST_CLICK].allocations
    }
    linear = {
        a.touch.campaign_ref: a.amount.minor for a in runs[AttributionModel.LINEAR].allocations
    }
    assert first == {"spring": 9_999} and last == {"autumn": 9_999}
    assert linear == {"spring": 5_000, "autumn": 4_999}
    # A refund changes only the revenue the engine allocates.
    sale(w, "R1", 3_333, kind=OperationKind.REFUND, parent="S1", when=datetime.now(UTC))
    _, ((conversion2, state2),) = inputs()
    assert conversion2.conversion_id == conversion.conversion_id and state2.net_minor == 6_666
    revised = attribute(
        conversion2,
        touches,
        ModelVersion("v-linear", AttributionModel.LINEAR),
        sale=state2,
        ledger_position=2,
        previous=runs[AttributionModel.LINEAR],
    )
    assert RevisionCause.REVENUE_CHANGED in revised.causes
    # A merge into another person yields a new conversion identity, never a mutated one.
    other_token = idw.browser_subject()["subject_token"]
    assert (
        idw.via_browser(
            other_token, [idw.identifier("email", "other@example.test", "email_code")]
        ).status_code
        == 201
    )
    survivor = [p for p in rows(w.db, select(IdentitySubject.id)) if p != buyer][0]
    merged = idw.owner.post(
        f"{idw.base}/clients/{w.a1}/identity/merges",
        json={
            "operation_id": str(uuid4()),
            "survivor_id": str(survivor),
            "merged_id": str(buyer),
            "survivor_version": 1,
            "merged_version": 1,
            "reason_code": "duplicate_account",
        },
    )
    assert merged.status_code == 201, merged.text
    touches3, ((conversion3, _),) = inputs()
    assert conversion3.conversion_id != conversion.conversion_id
    assert conversion3.person_id == str(survivor)
    assert {t.person_id for t in touches3} == {str(survivor)}
    reversal = idw.owner.post(
        f"{idw.base}/clients/{w.a1}/identity/merges/{merged.json()['merge_id']}/reversal",
        json={
            "operation_id": str(uuid4()),
            "survivor_version": 2,
            "merged_version": 2,
            "reason_code": "data_correction",
        },
    )
    assert reversal.status_code == 201
    touches4, ((conversion4, _),) = inputs()
    assert conversion4.conversion_id == conversion.conversion_id  # original ownership restored
    # Erasure removes the inputs; money stays.
    before = financial_snapshot(w)
    assert (
        idw.owner.post(
            f"{idw.base}/clients/{w.a1}/identity/erasures", json={"subject_id": str(buyer)}
        ).status_code
        == 201
    )
    with Session(w.db.runtime) as session:
        assert session.get(IdentitySubject, buyer) is None
    assert financial_snapshot(w) == before
    assert rows(w.db, select(SubjectDeletionRequest.status)) == ["completed"]
    assert all(b.owner_subject_id is None for b in bindings(w))
    assert IDENTITY
    assert UUID(str(buyer))
