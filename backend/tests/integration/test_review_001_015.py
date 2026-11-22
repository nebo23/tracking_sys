"""Independent regressions for the published Spec 015 head db750d1.

These assert the expected behavior and fail on the reviewed implementation.
Fixture imports deliberately expose the existing integration fixtures to pytest.
"""

# ruff: noqa: F811

import json

import pytest
from fastapi.testclient import TestClient
from integration_senders import booking_event, calcom, deal_event
from paymob_callbacks import refund, sale, signed
from sqlalchemy.orm import Session
from test_ad_spend import _connect, ads  # noqa: F401
from test_bookings_crm import _bookings, _deals, _sale, _subject, lab  # noqa: F401
from test_paymob import _evidence, _revenue, pay  # noqa: F401
from test_whatsapp import _messages, wa  # noqa: F401
from whatsapp_sender import message, notification
from whatsapp_sender import signed as whatsapp_signed

from app.main import create_app
from app.privacy.consent import ConsentSource, ConsentState, Purpose
from app.privacy.deletion import RequesterKind
from app.services.collection import erase_subject, record_consent

pytestmark = pytest.mark.integration


def test_review_test_payment_cannot_become_verified_with_same_signature(pay):
    obj = sale(is_live=False)
    body, params = signed(obj)
    assert pay.public.post(pay.path, content=body, params=params).status_code == 200
    assert not _evidence(pay.w)
    obj["is_live"] = True
    tampered = json.dumps({"type": "TRANSACTION", "obj": obj}).encode()
    response = pay.public.post(pay.path, content=tampered, params=params)
    assert not _evidence(pay.w), (response.status_code, _revenue(pay))


def test_review_refund_cannot_be_retargeted_with_same_signature(pay):
    first, second = sale(), sale()
    assert pay.send(first).status_code == pay.send(second).status_code == 200
    obj = refund(first["id"], 10000)
    body, params = signed(obj)
    obj["parent_transaction"] = second["id"]
    tampered = json.dumps({"type": "TRANSACTION", "obj": obj}).encode()
    response = pay.public.post(pay.path, content=tampered, params=params)
    assert all(row.parent_operation_id != str(second["id"]) for row in _evidence(pay.w)), (
        response.text
    )


def test_review_malformed_unsigned_callback_stays_401(pay):
    with TestClient(create_app(pay.config), raise_server_exceptions=False) as client:
        response = client.post(pay.path, json={"type": [], "obj": {}}, params={"hmac": "0" * 128})
    assert response.status_code == 401, (response.status_code, response.text)


def test_review_linked_booking_does_not_block_subject_erasure(lab):
    token = _subject(lab.w, {Purpose.ATTRIBUTION: ConsentState.GRANTED})
    assert (
        lab.cal(calcom("BOOKING_CREATED", "erase-booking", subject_token=token)).status_code == 200
    )
    with Session(lab.w.db.runtime) as session, session.begin():
        result = erase_subject(
            session,
            lab.config,
            lab.w.a,
            lab.w.a1,
            requester=RequesterKind.DATA_SUBJECT,
            subject_token=token,
        )
        assert result.status == "completed"


def test_review_booking_link_stops_on_withdrawal(lab):
    token = _subject(lab.w, {Purpose.ATTRIBUTION: ConsentState.GRANTED})
    assert (
        lab.cal(calcom("BOOKING_CREATED", "withdraw-booking", subject_token=token)).status_code
        == 200
    )
    with Session(lab.w.db.runtime) as session, session.begin():
        record_consent(
            session,
            lab.w.a,
            lab.w.a1,
            source=ConsentSource.API,
            notice_sha256="a" * 64,
            choices={Purpose.ATTRIBUTION: ConsentState.WITHDRAWN},
            subject_token=token,
            captured_at=None,
            recheck=lambda: None,
        )
    response = lab.browser("owner_a").get(f"/agencies/{lab.w.a}/clients/{lab.w.a1}/bookings")
    assert response.json()["totals"]["linked"] == 0, response.json()


def test_review_two_booking_sources_do_not_merge_local_identifiers(lab):
    other = lab.create("signed_webhook").json()
    body = booking_event("created", "booking-1")
    assert lab.hook(body).status_code == 200
    assert (
        lab.hook(
            body, path=other["source"]["callback_path"], secret=other["signing_secret"]
        ).status_code
        == 200
    )
    assert len(_bookings(lab.w)) == 2


def test_review_crm_payment_evidence_survives_out_of_order_events(lab):
    _sale(lab.w, "700000123")
    w = lab.w
    rules = f"/agencies/{w.a}/clients/{w.a1}/crm/stage-rules"
    assert (
        lab.browser("owner_a")
        .post(rules, json={"pipeline": "sales", "stage": "won", "outcome": "won"})
        .status_code
        == 201
    )
    for ref, reverse in [("ordered", False), ("reversed", True)]:
        bodies = [
            deal_event(
                ref,
                "paid",
                occurred_at="2026-11-10T09:00:00Z",
                amount="1500.00",
                currency="EGP",
                payment_reference="700000123",
            ),
            deal_event(ref, "won", occurred_at="2026-11-10T10:00:00Z"),
        ]
        for body in reversed(bodies) if reverse else bodies:
            assert lab.hook(body).status_code == 200
    deals = _deals(lab, amounts=True).json()["deals"]
    assert {row["status"] for row in deals} == {"won_verified"}, deals


def test_review_crm_totals_cover_more_than_500_deals(lab):
    from uuid import UUID, uuid4

    from app.models import CrmDeal
    from app.security import now_utc

    now = now_utc()
    with Session(lab.w.db.migration) as session, session.begin():
        session.add_all(
            CrmDeal(
                id=uuid4(),
                agency_id=lab.w.a,
                client_id=lab.w.a1,
                source_id=UUID(lab.webhook["id"]),
                deal_ref=f"deal-{i}",
                pipeline="sales",
                stage="new",
                stage_at=now,
                first_received_at=now,
                updated_at=now,
            )
            for i in range(501)
        )
    report = _deals(lab).json()
    assert report["totals"]["open"] == 501, report["totals"]


def test_review_ad_spend_pagination_preserves_both_currencies(ads):
    from datetime import UTC, date, datetime

    from app.models import AdSpendFact

    w = ads.w
    connection = _connect(ads, "owner_a", w.a, w.a1)
    now = datetime(2026, 11, 22, tzinfo=UTC)
    with Session(w.db.migration) as session, session.begin():
        for day, currency in [(1, "EGP"), (2, "USD")]:
            session.add(
                AdSpendFact(
                    agency_id=w.a,
                    client_id=w.a1,
                    connection_id=connection,
                    ad_id="111",
                    adset_id="222",
                    campaign_id="333",
                    spend_date=date(2026, 11, day),
                    time_zone="UTC",
                    currency=currency,
                    spend_minor=100,
                    provisional_until=now,
                )
            )
    path = f"/agencies/{w.a}/clients/{w.a1}/ad-spend"
    params = {
        "connection_id": str(connection),
        "since": "2026-11-01",
        "until": "2026-11-02",
        "limit": 1,
    }
    client = ads.browser("owner_a")
    first = client.get(path, params=params).json()
    assert first["next_after"] is not None
    second = client.get(path, params={**params, "after": first["next_after"]}).json()
    assert {row["currency"] for row in first["rows"] + second["rows"]} == {"EGP", "USD"}, (
        first,
        second,
    )


def test_review_whatsapp_number_requires_ownership_before_routing(wa):
    # Agency B knows an unregistered provider ID but has no grant for that number.
    # A legitimate provider notification must not become B's data merely because
    # B was first to submit that identifier to the registration endpoint.
    w = wa.w
    victim_number = "106540352242999"
    response = wa.browser("owner_b").post(
        f"/agencies/{w.b}/clients/{w.b1}/whatsapp-numbers",
        json={"phone_number_id": victim_number, "name": "Unproven number claim"},
    )
    assert response.status_code in {201, 202, 403, 422}, response.text
    assert wa.send(notification(victim_number, message())).status_code == 200
    assert _messages(w, w.b1) == [], response.json()


@pytest.mark.parametrize("malformed", ["source_type", "timestamp"])
def test_review_whatsapp_malformed_message_does_not_discard_valid_batch(wa, malformed):
    bad = message()
    if malformed == "source_type":
        bad["referral"]["source_type"] = []
    else:
        bad["timestamp"] = "999999999999"
    raw, headers = whatsapp_signed(notification(wa.number["phone_number_id"], bad, message()))
    with TestClient(create_app(wa.config), raise_server_exceptions=False) as client:
        response = client.post("/integrations/whatsapp/webhook", content=raw, headers=headers)
    assert response.status_code == 200, (response.status_code, response.text)
    assert len(_messages(wa.w)) >= 1
