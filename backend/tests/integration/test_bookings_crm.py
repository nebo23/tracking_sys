"""Cal.com bookings, the signed webhook and CRM deals on disposable PostgreSQL (015-D).

D-068 decisions E2 to E6 and E9 to E11; cases T-50 to T-58, T-70 to T-72 of the second-round
entry review. Every delivery comes from tests/integration_senders.py with test secrets. No case
contacts Cal.com or a CRM.
"""

import itertools
import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from integration_senders import (
    CALCOM_SECRET,
    FORBIDDEN,
    OTHER_CALCOM_SECRET,
    booking_event,
    calcom,
    deal_event,
    signed_calcom,
    signed_contract,
    uid,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind
from app.models import (
    AuditEvent,
    Booking,
    BookingEvent,
    CollectionSubject,
    CrmDeal,
    IntegrationDelivery,
    IntegrationSourceSecret,
    RevenueEvidence,
    StoredConsentRecord,
    StoredTombstone,
)
from app.privacy import providers
from app.privacy.consent import ConsentSource, ConsentState, Purpose
from app.privacy.deletion import RequesterKind
from app.services.collection import CollectionError, erase_subject, find_subject, record_consent
from app.services.lifecycle import run_lifecycle
from app.services.revenue import append_evidence, lock_revenue

pytestmark = pytest.mark.integration
NOTICE = "a" * 64


@pytest.fixture
def lab(authenticated_world, api):
    w = authenticated_world
    config = api.config.model_copy(
        update={"integrations_calcom_enabled": True, "integrations_webhook_enabled": True}
    )

    def browser(name, settings=None):
        client = api.new_client(settings or config)
        api.login(client, f"{name}@example.test")
        return client

    def create(kind, name="owner_a", client_id=None, secret=None, settings=None):
        body = {"kind": kind, "name": f"Synthetic {kind}"}
        if secret is not None:
            body["secret"] = secret
        return browser(name, settings).post(
            f"/agencies/{w.a}/clients/{client_id or w.a1}/integration-sources", json=body
        )

    lab = SimpleNamespace(w=w, api=api, config=config, browser=browser, create=create)
    calcom_source = create("cal_com", secret=CALCOM_SECRET)
    assert calcom_source.status_code == 201, calcom_source.text
    lab.calcom = calcom_source.json()["source"]
    webhook = create("signed_webhook")
    assert webhook.status_code == 201, webhook.text
    lab.webhook = webhook.json()["source"]
    lab.webhook_secret = webhook.json()["signing_secret"]
    lab.public = api.new_client(config)

    def cal(body, secret=CALCOM_SECRET, path=None, client=None):
        raw, headers = signed_calcom(body, secret)
        return (client or lab.public).post(
            path or lab.calcom["callback_path"], content=raw, headers=headers
        )

    def hook(body, secret=None, path=None, client=None, at=None):
        raw, headers = signed_contract(body, secret or lab.webhook_secret, at)
        return (client or lab.public).post(
            path or lab.webhook["callback_path"], content=raw, headers=headers
        )

    lab.cal, lab.hook = cal, hook
    return lab


def _bookings(w, client_id=None):
    with Session(w.db.migration) as session:
        return list(
            session.scalars(select(Booking).where(Booking.client_id == (client_id or w.a1)))
        )


def _outcomes(w):
    with Session(w.db.migration) as session:
        return [
            (row.outcome, row.reason)
            for row in session.scalars(
                select(IntegrationDelivery).order_by(IntegrationDelivery.received_at)
            )
        ]


def _subject(w, choices):
    with Session(w.db.runtime) as session, session.begin():
        result = record_consent(
            session,
            w.a,
            w.a1,
            source=ConsentSource.API,
            notice_sha256=NOTICE,
            choices=choices,
            subject_token=None,
            captured_at=None,
            recheck=lambda: None,
        )
    return result.subject_token


def test_signed_calcom_callback_and_refusals(lab):
    # T-50 (M): a callback signed with the client's secret is accepted; a missing or wrong
    # signature, an unknown or disabled source and an unreadable body answer 401 and store nothing.
    ref = uid()
    body = calcom("BOOKING_CREATED", ref)
    raw, headers = signed_calcom(body)
    for content, sent in (
        (raw, {}),
        (raw, {"x-cal-signature-256": "0" * 64}),
        (raw, signed_calcom(body, OTHER_CALCOM_SECRET)[1]),
        (raw.replace(b"syn-booking", b"syn-bookinX", 1), headers),
        (b"[" * 30_000 + b"]" * 30_000, {"x-cal-signature-256": "0" * 64}),
    ):
        response = lab.public.post(lab.calcom["callback_path"], content=content, headers=sent)
        assert (response.status_code, response.json()) == (401, {"error": "invalid_signature"})
    unknown = "/integrations/cal-com/isk_" + "A" * 43
    assert lab.cal(body, path=unknown).status_code == 401
    # A webhook source key is not a Cal.com key.
    other = lab.webhook["callback_path"].replace("/webhook/", "/cal-com/")
    assert lab.cal(body, path=other).status_code == 401
    assert _bookings(lab.w) == [] and _outcomes(lab.w) == []
    response = lab.cal(body)
    assert response.status_code == 200 and response.json() == {"status": "received"}
    (booking,) = _bookings(lab.w)
    assert (booking.provider, booking.status, booking.event_type_ref) == (
        "cal_com",
        "scheduled",
        "501",
    )
    source = f"/agencies/{lab.w.a}/clients/{lab.w.a1}/integration-sources/{lab.calcom['id']}"
    assert lab.browser("owner_a").patch(source, json={"status": "disabled"}).status_code == 200
    assert lab.cal(calcom("BOOKING_CANCELLED", ref)).status_code == 401


def test_one_booking_through_reschedule_and_cancellation(lab):
    # T-51 (M): creation, a reschedule and a cancellation leave one booking, rescheduled once and
    # cancelled; nothing is written to the revenue ledger.
    first, second = uid(), uid()
    assert (
        lab.cal(calcom("BOOKING_CREATED", first, created_at="2026-11-10T09:00:00Z")).status_code
        == 200
    )
    moved = calcom(
        "BOOKING_RESCHEDULED",
        second,
        previous=first,
        created_at="2026-11-10T10:00:00Z",
        start="2026-11-14T10:00:00Z",
    )
    assert lab.cal(moved).status_code == 200
    (booking,) = _bookings(lab.w)
    assert (booking.status, booking.reschedule_count) == ("scheduled", 1)
    assert booking.start_at == datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    cancel = calcom(
        "BOOKING_CANCELLED", second, created_at="2026-11-10T11:00:00Z", start="2026-11-14T10:00:00Z"
    )
    assert lab.cal(cancel).status_code == 200
    (booking,) = _bookings(lab.w)
    assert (booking.status, booking.reschedule_count) == ("cancelled", 1)
    report = lab.browser("analyst").get(f"/agencies/{lab.w.a}/clients/{lab.w.a1}/bookings")
    assert report.status_code == 200
    assert report.json()["totals"]["cancelled"] == 1 and len(report.json()["bookings"]) == 1
    with Session(lab.w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(RevenueEvidence)) == 0


def test_every_order_gives_the_same_booking_and_duplicates_count_once(lab):
    # T-52 (M): every delivery order of created, rescheduled and cancelled gives the same booking;
    # repeated deliveries are counted once.
    finals = set()
    for order in itertools.permutations(range(3)):
        first, second = uid(), uid()
        bodies = [
            calcom("BOOKING_CREATED", first, created_at="2026-11-10T09:00:00Z"),
            calcom(
                "BOOKING_RESCHEDULED", second, previous=first, created_at="2026-11-10T10:00:00Z"
            ),
            calcom("BOOKING_CANCELLED", second, created_at="2026-11-10T11:00:00Z"),
        ]
        for index in order:
            assert lab.cal(bodies[index]).status_code == 200
            assert lab.cal(bodies[index]).status_code == 200  # a redelivery
    visible = [booking for booking in _bookings(lab.w) if booking.status != "merged"]
    for booking in visible:
        finals.add((booking.status, booking.reschedule_count))
    assert finals == {("cancelled", 1)} and len(visible) == 6
    report = lab.browser("owner_a").get(f"/agencies/{lab.w.a}/clients/{lab.w.a1}/bookings")
    assert report.json()["totals"]["cancelled"] == 6 and len(report.json()["bookings"]) == 6
    outcomes = _outcomes(lab.w)
    assert [outcome for outcome, _ in outcomes] == ["applied"] * 18
    assert {reason for _, reason in outcomes} <= {None, "merged"}
    with Session(lab.w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(IntegrationDelivery)) == 18
        assert session.scalar(select(func.count()).select_from(BookingEvent)) == 18


def test_lead_links_need_identifier_evidence_and_consent(lab):
    # T-53 (M): a valid subject token with granted attribution consent links the booking; without
    # a token, with an unknown token or without consent it stays unlinked; no token is stored.
    granted = _subject(lab.w, {Purpose.ATTRIBUTION: ConsentState.GRANTED})
    analytics = _subject(lab.w, {Purpose.ANALYTICS: ConsentState.GRANTED})
    cases = [
        (granted, "linked"),
        ("sbj_" + "U" * 43, "subject_unknown"),
        (analytics, "consent_missing"),
        (None, None),
    ]
    for token, _ in cases:
        assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=token)).status_code == 200
    assert [reason for _, reason in _outcomes(lab.w)] == [reason for _, reason in cases]
    linked = [booking for booking in _bookings(lab.w) if booking.subject_id is not None]
    assert len(linked) == 1 and linked[0].linked_at is not None
    with lab.w.db.migration.connect() as connection:
        for table in ("bookings", "booking_events", "integration_deliveries"):
            rows = [str(tuple(row)) for row in connection.execute(text(f"SELECT * FROM {table}"))]
            assert not any(granted in row or analytics in row for row in rows), table
    report = lab.browser("owner_a").get(f"/agencies/{lab.w.a}/clients/{lab.w.a1}/bookings")
    assert report.json()["totals"]["linked"] == 1


def test_no_personal_field_is_stored_logged_or_returned(lab, caplog):
    # T-54: no name, email, phone, answer, note, meeting link or token is stored, logged or
    # returned.
    caplog.set_level(logging.DEBUG)
    assert lab.cal(calcom("BOOKING_CREATED", uid())).status_code == 200
    assert lab.hook(booking_event("created", uid())).status_code == 200
    w = lab.w
    with w.db.migration.connect() as connection:
        stored = [
            str(tuple(row))
            for table in (
                "bookings",
                "booking_events",
                "integration_deliveries",
                "integration_sources",
            )
            for row in connection.execute(text(f"SELECT * FROM {table}"))
        ]
    answers = [
        lab.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/bookings").text,
        lab.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/integration-sources").text,
    ]
    logged = [record.getMessage() + str(record.__dict__) for record in caplog.records]
    for value in FORBIDDEN:
        for item in stored + answers + logged:
            assert value not in item, value


def test_signed_webhook_contract(lab):
    # T-55: the signed webhook accepts the documented booking and deal contract with the 004
    # signature, and refuses an old, missing or wrong signature with 401.
    ref = uid()
    assert lab.hook(booking_event("created", ref)).status_code == 200
    old = int(datetime.now(UTC).timestamp()) - 3600
    for response in (
        lab.hook(booking_event("cancelled", ref), at=old),
        lab.hook(booking_event("cancelled", ref), secret="whsec_wrong"),
        lab.public.post(lab.webhook["callback_path"], content=b"{}"),
    ):
        assert (response.status_code, response.json()) == (401, {"error": "invalid_signature"})
    assert (
        lab.hook(booking_event("cancelled", ref, occurred_at="2026-11-10T10:00:00Z")).status_code
        == 200
    )
    (booking,) = _bookings(lab.w)
    assert (booking.provider, booking.status) == ("signed_webhook", "cancelled")
    assert lab.hook({"type": "booking.paid", "booking": {}}).status_code == 200
    assert lab.hook(deal_event("D-1", "proposal")).status_code == 200
    assert _outcomes(lab.w)[-2:] == [("ignored", "unsupported_event"), ("applied", None)]


def _sale(w, operation):
    with Session(w.db.runtime) as session, session.begin():
        received = lock_revenue(session, w.a1)
        append_evidence(
            session,
            Evidence(
                f"paymob:{operation}:synthetic",
                w.a,
                w.a1,
                "paymob-egypt",
                operation,
                OperationKind.SALE,
                EvidenceClass.CONFIRMED_CAPTURE,
                Money(150_000, Currency("EGP", 2)),
                datetime(2026, 11, 9, tzinfo=UTC),
                received,
            ),
            "paymob",
            w.a1,
        )


def _deals(lab, name="owner_a", amounts=False):
    w = lab.w
    query = "?include_amounts=true" if amounts else ""
    return lab.browser(name).get(f"/agencies/{w.a}/clients/{w.a1}/crm/deals{query}")


def test_stage_changes_never_become_revenue_without_rule_and_evidence(lab):
    # T-56 (M): without a won rule a deal stays open; with the rule and no matching verified sale
    # it is won and unverified; with a matching verified sale it is won and verified; no case
    # writes ledger evidence.
    w = lab.w
    for deal, reference in (("D-1", None), ("D-2", "700000123"), ("D-3", "700000999")):
        body = deal_event(
            deal, "closed_won", amount="1500.00", currency="EGP", payment_reference=reference
        )
        assert lab.hook(body).status_code == 200
    assert _deals(lab).json()["totals"] == {
        "open": 3,
        "won_verified": 0,
        "won_unverified": 0,
        "lost": 0,
    }
    rules = f"/agencies/{w.a}/clients/{w.a1}/crm/stage-rules"
    created = lab.browser("owner_a").post(
        rules, json={"pipeline": "sales", "stage": "closed_won", "outcome": "won"}
    )
    assert created.status_code == 201, created.text
    assert _deals(lab).json()["totals"] == {
        "open": 0,
        "won_verified": 0,
        "won_unverified": 3,
        "lost": 0,
    }
    with Session(w.db.migration) as session:
        before = session.scalar(select(func.count()).select_from(RevenueEvidence))
    _sale(w, "700000123")
    report = _deals(lab, amounts=True).json()
    assert report["totals"] == {"open": 0, "won_verified": 1, "won_unverified": 2, "lost": 0}
    verified = [item for item in report["deals"] if item["status"] == "won_verified"]
    assert verified[0]["deal_ref"] == "D-2" and verified[0]["linked_sale"] == "700000123"
    assert verified[0]["amount"] == "1500.00"
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(RevenueEvidence)) == before + 1
    revenue = lab.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/revenue").json()
    assert revenue["verified"]["totals"][0]["captured"] == "1500.00"  # the sale alone
    rule_id = created.json()["id"]
    assert (
        lab.browser("owner_a").patch(f"{rules}/{rule_id}", json={"status": "disabled"}).status_code
        == 200
    )
    assert _deals(lab).json()["totals"]["open"] == 3


def test_rules_sources_and_amounts_permissions(lab, api):
    # T-57: rules and sources need an Owner or Admin, are audited and isolated per client; deal
    # amounts need finance:read.
    w = lab.w
    rules = f"/agencies/{w.a}/clients/{w.a1}/crm/stage-rules"
    rule = {"pipeline": "sales", "stage": "won", "outcome": "won"}
    for name in ("analyst", "viewer", "owner_b"):
        assert lab.browser(name).post(rules, json=rule).status_code == 403, name
        assert lab.create("signed_webhook", name).status_code == 403, name
    assert lab.browser("admin").post(rules, json=rule).status_code == 201
    assert lab.browser("admin").post(rules, json=rule).status_code == 409
    assert lab.create("cal_com", "owner_a", client_id=w.b1, secret=CALCOM_SECRET).status_code == 403
    assert lab.create("cal_com", secret="short").status_code == 422
    assert lab.create("signed_webhook", secret=CALCOM_SECRET).status_code == 422
    assert lab.hook(deal_event("D-9", "won", amount="10.00", currency="EGP")).status_code == 200
    assert _deals(lab, "analyst").status_code == 200
    assert "amount" not in _deals(lab, "analyst").json()["deals"][0]
    assert _deals(lab, "analyst", amounts=True).status_code == 403
    assert _deals(lab, "owner_a", amounts=True).json()["deals"][0]["amount"] == "10.00"
    assert (
        lab.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a2}/crm/deals").json()["deals"]
        == []
    )
    path = f"/agencies/{w.a}/clients/{w.a1}/integration-sources/{lab.webhook['id']}/secret"
    rotated = lab.browser("owner_a").put(path, json={})
    assert rotated.status_code == 200 and rotated.json()["signing_secret"].startswith("whsec_")
    assert (
        lab.hook(deal_event("D-9", "won2", occurred_at="2026-11-10T10:00:00Z")).status_code == 200
    )
    new = rotated.json()["signing_secret"]
    assert (
        lab.hook(
            deal_event("D-9", "won3", occurred_at="2026-11-10T11:00:00Z"), secret=new
        ).status_code
        == 200
    )
    with Session(w.db.migration) as session:
        actions = sorted(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.resource_type.in_(("integration_source", "crm_rule"))
                )
            )
        )
    assert actions == [
        "crm_rule.created",
        "integration.created",
        "integration.created",
        "integration.secret_replaced",
    ]


def test_out_of_order_stage_changes_keep_the_latest(lab):
    # T-58: out-of-order stage changes keep the latest by occurrence time.
    late = deal_event("D-5", "won", occurred_at="2026-11-10T12:00:00Z", previous="proposal")
    early = deal_event("D-5", "proposal", occurred_at="2026-11-10T09:00:00Z")
    assert lab.hook(late).status_code == 200
    assert lab.hook(early).status_code == 200
    with Session(lab.w.db.migration) as session:
        (deal,) = session.scalars(select(CrmDeal)).all()
    assert (deal.stage, deal.previous_stage) == ("won", "proposal")


def _stale(monkeypatch, rule_id, **changes):
    rules = tuple(
        replace(item, **changes) if item.rule_id == rule_id else item for item in providers.RULES
    )
    monkeypatch.setattr(providers, "RULES", rules)


def test_gates_and_rules(lab, monkeypatch):
    # T-70 (M): with a setting off or the Cal.com rule stale or overdue, the kind is unusable.
    w = lab.w
    off = lab.config.model_copy(
        update={"integrations_calcom_enabled": False, "integrations_webhook_enabled": False}
    )
    assert lab.create("cal_com", secret=CALCOM_SECRET, settings=off).status_code == 503
    assert lab.create("signed_webhook", settings=off).status_code == 503
    closed = lab.api.new_client(off)
    assert lab.cal(calcom("BOOKING_CREATED", uid()), client=closed).status_code == 503
    assert lab.hook(booking_event("created", uid()), client=closed).status_code == 503
    for changes in ({"status": providers.RuleStatus.STALE}, {"review_due_at": date(2026, 1, 1)}):
        with monkeypatch.context() as patched:
            _stale(patched, "calcom.webhooks", **changes)
            assert lab.create("cal_com", secret=CALCOM_SECRET).status_code == 503
            assert lab.cal(calcom("BOOKING_CREATED", uid())).status_code == 503
            assert lab.hook(booking_event("created", uid())).status_code == 200
    assert len(_bookings(w)) == 2


def test_body_bounds(lab):
    # T-71: the Cal.com and signed webhook routes take up to 64 KiB.
    body = calcom("BOOKING_CREATED", uid())
    raw, _ = signed_calcom(body)
    body["payload"]["additionalNotes"] = "x" * (
        65_536 - len(raw) + len(body["payload"]["additionalNotes"])
    )
    raw, headers = signed_calcom(body)
    assert len(raw) == 65_536
    assert (
        lab.public.post(lab.calcom["callback_path"], content=raw, headers=headers).status_code
        == 200
    )
    body["payload"]["additionalNotes"] += "x"
    raw, headers = signed_calcom(body)
    response = lab.public.post(lab.calcom["callback_path"], content=raw, headers=headers)
    assert response.status_code == 413


def test_lifecycle_deletes_bookings_deals_deliveries_and_secrets(
    lab, lifecycle_engine, lifecycle_settings
):
    # T-72: bookings and deals 395 days after their last update, deliveries after 30 days, and
    # retired secrets.
    w = lab.w
    assert lab.cal(calcom("BOOKING_CREATED", uid())).status_code == 200
    assert lab.cal(calcom("BOOKING_CREATED", uid())).status_code == 200
    assert lab.hook(deal_event("D-7", "proposal")).status_code == 200
    path = f"/agencies/{w.a}/clients/{w.a1}/integration-sources/{lab.calcom['id']}/secret"
    assert lab.browser("owner_a").put(path, json={"secret": OTHER_CALCOM_SECRET}).status_code == 200
    now = datetime.now(UTC)
    with Session(w.db.migration) as session, session.begin():
        first = session.scalars(select(Booking.id).order_by(Booking.first_received_at)).first()
        session.execute(
            update(Booking).where(Booking.id == first).values(updated_at=now - timedelta(days=396))
        )
        session.execute(update(CrmDeal).values(updated_at=now - timedelta(days=396)))
        oldest = session.scalars(
            select(IntegrationDelivery.id).order_by(IntegrationDelivery.received_at)
        ).first()
        session.execute(
            update(IntegrationDelivery)
            .where(IntegrationDelivery.id == oldest)
            .values(received_at=now - timedelta(days=31))
        )
        session.execute(
            update(IntegrationSourceSecret)
            .where(
                IntegrationSourceSecret.version == 1,
                IntegrationSourceSecret.source_id == lab.calcom["id"],
            )
            .values(retires_at=now - timedelta(minutes=1))
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed"
    deleted = result["deleted"]
    assert (deleted["bookings"], deleted["crm_deals"]) == (1, 1)
    assert (deleted["integration_deliveries"], deleted["integration_source_secrets"]) == (1, 1)
    assert len(_bookings(w)) == 1
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(BookingEvent)) == 1
    assert lab.cal(calcom("BOOKING_CREATED", uid()), secret=OTHER_CALCOM_SECRET).status_code == 200


# --- Review finding R002 (D-069, D-070): subject erasure and expiry with linked bookings ------


def _client_subject(w, client_id, choices):
    with Session(w.db.runtime) as session, session.begin():
        return record_consent(
            session,
            w.a,
            client_id,
            source=ConsentSource.API,
            notice_sha256=NOTICE,
            choices=choices,
            subject_token=None,
            captured_at=None,
            recheck=lambda: None,
        ).subject_token


def _links(w):
    with Session(w.db.migration) as session:
        return {
            row.id: (row.client_id, row.subject_id is not None, row.linked_at is not None)
            for row in session.scalars(select(Booking))
        }


def test_erasure_detaches_linked_bookings_and_blocks_replay(lab):
    # R002: erasing a linked subject completes; its bookings stay with both link columns
    # cleared and the booking store recorded; other subjects and clients keep their links; the
    # erased token never links again.
    w = lab.w
    granted = {Purpose.ATTRIBUTION: ConsentState.GRANTED}
    token = _client_subject(w, w.a1, granted)
    kept = _client_subject(w, w.a1, granted)
    foreign = _client_subject(w, w.a2, granted)
    other_source = lab.create("cal_com", client_id=w.a2, secret=CALCOM_SECRET).json()["source"]
    first, second = uid(), uid()
    assert lab.cal(calcom("BOOKING_CREATED", first, subject_token=token)).status_code == 200
    assert lab.cal(calcom("BOOKING_CREATED", second, subject_token=token)).status_code == 200
    assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=kept)).status_code == 200
    response = lab.cal(
        calcom("BOOKING_CREATED", uid(), subject_token=foreign),
        path=other_source["callback_path"],
    )
    assert response.status_code == 200
    before = _links(w)
    assert sorted(item[1:] for item in before.values()) == [(True, True)] * 4
    erased = lab.browser("owner_a").post(
        f"/agencies/{w.a}/clients/{w.a1}/deletion-requests", json={"subject_token": token}
    )
    assert erased.status_code == 201, erased.text
    assert erased.json()["status"] == "completed"
    assert erased.json()["target_outcomes"]["booking_links"] == "done"
    after = _links(w)
    assert set(after) == set(before)  # every booking is kept
    assert sorted(after.values(), key=str) == sorted(
        [(w.a1, False, False), (w.a1, False, False), (w.a1, True, True), (w.a2, True, True)],
        key=str,
    )
    assert {row.status for row in _bookings(w)} == {"scheduled"}
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(CollectionSubject)) == 2
        tombstones = session.scalars(
            select(StoredTombstone.match_type).where(StoredTombstone.client_id == w.a1)
        ).all()
    assert tombstones == ["subject_token"]
    # A later delivery that still carries the erased token cannot link, and the token cannot
    # record consent again.
    later = calcom(
        "BOOKING_RESCHEDULED",
        uid(),
        previous=first,
        subject_token=token,
        created_at="2026-11-10T10:00:00.000Z",
    )
    assert lab.cal(later).status_code == 200
    assert _outcomes(w)[-1] == ("applied", "subject_unknown")
    assert sum(1 for item in _links(w).values() if item == (w.a1, True, True)) == 1
    with Session(w.db.runtime) as session, session.begin():
        with pytest.raises(CollectionError, match="unknown_subject"):
            record_consent(
                session,
                w.a,
                w.a1,
                source=ConsentSource.API,
                notice_sha256=NOTICE,
                choices=granted,
                subject_token=token,
                captured_at=None,
                recheck=lambda: None,
            )
    # An erasure of a subject without bookings reports the booking store as not applicable.
    plain = _client_subject(w, w.a1, granted)
    with Session(w.db.runtime) as session, session.begin():
        request = erase_subject(
            session,
            lab.config,
            w.a,
            w.a1,
            requester=RequesterKind.DATA_SUBJECT,
            subject_token=plain,
        )
        assert request.target_outcomes["booking_links"] == "not_applicable"


def test_failed_erasure_keeps_the_link(lab):
    # R002: the detach is part of the erasure transaction; a rollback leaves the link, the
    # subject and its consent in place and writes no tombstone.
    w = lab.w
    token = _subject(w, {Purpose.ATTRIBUTION: ConsentState.GRANTED})
    assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=token)).status_code == 200
    with pytest.raises(RuntimeError, match="abort"):
        with Session(w.db.runtime) as session, session.begin():
            erase_subject(
                session,
                lab.config,
                w.a,
                w.a1,
                requester=RequesterKind.DATA_SUBJECT,
                subject_token=token,
            )
            raise RuntimeError("abort")
    assert [item[1:] for item in _links(w).values()] == [(True, True)]
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(CollectionSubject)) == 1
        assert session.scalar(select(func.count()).select_from(StoredTombstone)) == 0


def test_lifecycle_expiry_detaches_a_newer_booking_from_an_old_subject(
    lab, lifecycle_engine, lifecycle_settings
):
    # R002: a subject past its retention whose bookings are recent. The lifecycle run, as the
    # restricted tracking_lifecycle role under the client's privacy lock, deletes the consent
    # history, clears both link columns of each booking and deletes the subject; the bookings
    # stay. A subject still in use keeps its link.
    w = lab.w
    granted = {Purpose.ATTRIBUTION: ConsentState.GRANTED}
    old = _subject(w, granted)
    active = _subject(w, granted)
    assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=old)).status_code == 200
    assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=old)).status_code == 200
    assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=active)).status_code == 200
    with Session(w.db.runtime) as session:
        old_id = find_subject(session, w.a1, old).id
    long_ago = datetime.now(UTC) - timedelta(days=400)
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            update(CollectionSubject)
            .where(CollectionSubject.id == old_id)
            .values(created_at=long_ago, last_activity_at=long_ago)
        )
        session.execute(
            update(StoredConsentRecord)
            .where(StoredConsentRecord.subject_id == old_id)
            .values(received_at=long_ago, expires_at=long_ago + timedelta(days=365))
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed", result
    deleted = result["deleted"]
    assert (deleted["booking_links"], deleted["collection_subjects"]) == (2, 1)
    assert deleted["consent_records"] == 1 and deleted["bookings"] == 0
    links = _links(w)
    assert len(links) == 3
    assert sorted(item[1:] for item in links.values()) == [
        (False, False),
        (False, False),
        (True, True),
    ]
    with Session(w.db.migration) as session:
        assert session.get(CollectionSubject, old_id) is None
        assert session.scalar(select(func.count()).select_from(CollectionSubject)) == 1
    # A second run finds nothing more to do.
    again = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert again["status"] == "completed"
    assert again["deleted"]["booking_links"] == again["deleted"]["collection_subjects"] == 0


# --- Review finding R003 (D-069): booking links follow the current attribution consent -------


def _consent(w, token, state, client_id=None):
    with Session(w.db.runtime) as session, session.begin():
        record_consent(
            session,
            w.a,
            client_id or w.a1,
            source=ConsentSource.API,
            notice_sha256=NOTICE,
            choices={Purpose.ATTRIBUTION: state},
            subject_token=token,
            captured_at=None,
            recheck=lambda: None,
        )


def _linked(lab):
    w = lab.w
    report = lab.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/bookings").json()
    flags = sorted(item["linked"] for item in report["bookings"])
    assert report["totals"]["linked"] == sum(flags)
    return report["totals"]["linked"]


def _stored_links(w):
    return sum(1 for item in _links(w).values() if item[1])


def _expire(w, token):
    with Session(w.db.runtime) as session:
        subject_id = find_subject(session, w.a1, token).id
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            update(StoredConsentRecord)
            .where(StoredConsentRecord.subject_id == subject_id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )


def test_withdrawal_detaches_and_a_new_grant_restores_nothing(lab):
    # R003: a withdrawal removes the link at once; later and replayed deliveries cannot restore
    # it while consent is withdrawn; a new grant alone restores nothing, and only a later
    # delivery that carries the token again links under the new grant.
    w = lab.w
    token = _subject(w, {Purpose.ATTRIBUTION: ConsentState.GRANTED})
    first = uid()
    created = calcom("BOOKING_CREATED", first, subject_token=token)
    assert lab.cal(created).status_code == 200
    assert (_linked(lab), _stored_links(w)) == (1, 1)
    _consent(w, token, ConsentState.WITHDRAWN)
    assert (_linked(lab), _stored_links(w)) == (0, 0)
    moved = uid()
    later = calcom(
        "BOOKING_RESCHEDULED",
        moved,
        previous=first,
        subject_token=token,
        created_at="2026-11-10T10:00:00.000Z",
    )
    assert lab.cal(later).status_code == 200
    assert _outcomes(w)[-1] == ("applied", "consent_missing")
    recorded = len(_outcomes(w))
    assert lab.cal(created).status_code == 200  # an exact replay is a no-op duplicate
    assert len(_outcomes(w)) == recorded
    assert (_linked(lab), _stored_links(w)) == (0, 0)
    _consent(w, token, ConsentState.GRANTED)
    assert (_linked(lab), _stored_links(w)) == (0, 0)
    assert lab.cal(created).status_code == 200  # a replay after the grant is still a no-op
    assert len(_outcomes(w)) == recorded
    assert (_linked(lab), _stored_links(w)) == (0, 0)
    again = calcom(
        "BOOKING_RESCHEDULED",
        uid(),
        previous=moved,
        subject_token=token,
        created_at="2026-11-10T11:00:00.000Z",
    )
    assert lab.cal(again).status_code == 200
    assert _outcomes(w)[-1] == ("applied", "linked")
    assert (_linked(lab), _stored_links(w)) == (1, 1)
    # A denial also detaches.
    _consent(w, token, ConsentState.DENIED)
    assert (_linked(lab), _stored_links(w)) == (0, 0)


def test_expiry_stops_the_link_and_a_renewal_after_the_lapse_restores_nothing(lab):
    # R003: an expired grant stops counting at once on every read; renewing it after the lapse
    # detaches the old link instead of reviving it; a renewal before expiry keeps the link.
    w = lab.w
    lapsed = _subject(w, {Purpose.ATTRIBUTION: ConsentState.GRANTED})
    renewed = _subject(w, {Purpose.ATTRIBUTION: ConsentState.GRANTED})
    assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=lapsed)).status_code == 200
    assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=renewed)).status_code == 200
    assert (_linked(lab), _stored_links(w)) == (2, 2)
    _consent(w, renewed, ConsentState.GRANTED)  # renewal before expiry: continuous
    _expire(w, lapsed)
    assert (_linked(lab), _stored_links(w)) == (1, 2)
    _consent(w, lapsed, ConsentState.GRANTED)  # renewal after the lapse
    assert (_linked(lab), _stored_links(w)) == (1, 1)
    assert lab.cal(calcom("BOOKING_CREATED", uid(), subject_token=lapsed)).status_code == 200
    assert (_linked(lab), _stored_links(w)) == (2, 2)


def test_a_merge_never_carries_an_ineffective_link(lab):
    # R003: when a later event joins two chains, the link of the later chain moves to the
    # earlier one only while its subject's consent is granted.
    w = lab.w
    for expire in (False, True):
        token = _subject(w, {Purpose.ATTRIBUTION: ConsentState.GRANTED})
        original, replacement = uid(), uid()
        assert lab.cal(calcom("BOOKING_CREATED", original)).status_code == 200
        cancelled = calcom(
            "BOOKING_CANCELLED",
            replacement,
            subject_token=token,
            created_at="2026-11-10T12:00:00.000Z",
        )
        assert lab.cal(cancelled).status_code == 200
        if expire:
            _expire(w, token)
        joined = calcom(
            "BOOKING_RESCHEDULED",
            replacement,
            previous=original,
            created_at="2026-11-10T11:00:00.000Z",
        )
        assert lab.cal(joined).status_code == 200
        assert _outcomes(w)[-1] == ("applied", "merged")
        with Session(w.db.runtime) as session:
            subject_id = find_subject(session, w.a1, token).id
        with Session(w.db.migration) as session:
            holders = session.scalars(
                select(Booking.status).where(Booking.subject_id == subject_id)
            ).all()
        assert holders == ([] if expire else ["cancelled"]), (expire, holders)
    assert (_linked(lab), _stored_links(w)) == (1, 1)


def test_withdrawal_and_a_delivery_serialize_on_the_privacy_lock(lab):
    # R003: a withdrawal and a booking delivery for the same subject take the client's privacy
    # lock, so neither order can leave a link after a committed withdrawal.
    from concurrent.futures import ThreadPoolExecutor

    from test_collection import wait_for_blocked_lock

    from app.services.integrations import body_digest, live_source, receive_booking

    w = lab.w
    granted = {Purpose.ATTRIBUTION: ConsentState.GRANTED}
    # The withdrawal holds the lock; the delivery waits, then finds the consent withdrawn.
    token = _subject(w, granted)
    with Session(w.db.runtime) as session:
        session.begin()
        record_consent(
            session,
            w.a,
            w.a1,
            source=ConsentSource.API,
            notice_sha256=NOTICE,
            choices={Purpose.ATTRIBUTION: ConsentState.WITHDRAWN},
            subject_token=token,
            captured_at=None,
            recheck=lambda: None,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                lab.cal, calcom("BOOKING_CREATED", uid(), subject_token=token)
            )
            wait_for_blocked_lock(w.db)
            assert not pending.done()
            session.commit()
            assert pending.result(timeout=10).status_code == 200
    assert _outcomes(w)[-1] == ("applied", "consent_missing")
    assert (_linked(lab), _stored_links(w)) == (0, 0)
    # The delivery holds the lock and links; the withdrawal waits, then detaches the link.
    other = _subject(w, granted)
    body = calcom("BOOKING_CREATED", uid(), subject_token=other)
    raw, _ = signed_calcom(body)
    with Session(w.db.runtime) as session:
        session.begin()
        key = lab.calcom["callback_path"].rsplit("/", 1)[-1]
        source = live_source(session, "cal_com", key)
        assert receive_booking(session, source, body, body_digest(raw)) == "applied"
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(_consent, w, other, ConsentState.WITHDRAWN)
            wait_for_blocked_lock(w.db)
            assert not pending.done()
            session.commit()
            pending.result(timeout=10)
    assert (_linked(lab), _stored_links(w)) == (0, 0)


# --- Review finding R006 (D-069, D-070): booking identities belong to their source -----------


def _by_source(w, client_id=None):
    rows = [row for row in _bookings(w, client_id) if row.status != "merged"]
    return {str(row.source_id): row for row in rows}


def test_each_source_keeps_its_own_booking_identities(lab):
    # R006: two signed webhook sources of one client both use booking-1. Each keeps its own
    # booking; a reschedule or cancellation from one never moves or cancels the other's.
    w = lab.w
    other = lab.create("signed_webhook").json()
    second = {"path": other["source"]["callback_path"], "secret": other["signing_secret"]}
    first_id, second_id = lab.webhook["id"], other["source"]["id"]
    assert lab.hook(booking_event("created", "booking-1")).status_code == 200
    assert lab.hook(booking_event("created", "booking-1"), **second).status_code == 200
    assert set(_by_source(w)) == {first_id, second_id}
    moved = booking_event(
        "rescheduled", "booking-2", previous="booking-1", occurred_at="2026-11-10T10:00:00Z"
    )
    assert lab.hook(moved, **second).status_code == 200
    gone = booking_event("cancelled", "booking-2", occurred_at="2026-11-10T11:00:00Z")
    assert lab.hook(gone, **second).status_code == 200
    rows = _by_source(w)
    assert (rows[first_id].status, rows[first_id].reschedule_count) == ("scheduled", 0)
    assert (rows[second_id].status, rows[second_id].reschedule_count) == ("cancelled", 1)
    # A cancellation of booking-2 from the first source, which never used that ID, starts a
    # chain of its own there and changes nothing in the second source.
    stray = booking_event("cancelled", "booking-2", occurred_at="2026-11-10T12:00:00Z")
    assert lab.hook(stray).status_code == 200
    rows = _by_source(w)
    assert rows[second_id].status == "cancelled" and rows[second_id].reschedule_count == 1
    statuses = sorted(row.status for row in _bookings(w) if str(row.source_id) == first_id)
    assert statuses == ["cancelled", "scheduled"]
    # The second source's own cancellation of booking-1 (moved away) is ignored there, and the
    # first source's booking-1 stays scheduled.
    late = booking_event("cancelled", "booking-1", occurred_at="2026-11-10T13:00:00Z")
    assert lab.hook(late, **second).status_code == 200
    rows = _by_source(w)
    assert rows[second_id].status == "cancelled"
    assert any(row.status == "scheduled" for row in _bookings(w) if str(row.source_id) == first_id)


def test_duplicates_and_out_of_order_chains_stay_within_one_source(lab):
    # R006: within one source, a repeated delivery and a re-sent event with a new envelope ID
    # are still one event, and an out-of-order chain still ends in one booking; another
    # client's source with the same IDs keeps its own booking.
    w = lab.w
    created = booking_event("created", "booking-9a")
    resent = dict(created, id="evt-booking-9a-created-resent")
    assert lab.hook(created).status_code == 200
    assert lab.hook(created).status_code == 200
    assert lab.hook(resent).status_code == 200
    with Session(w.db.migration) as session:
        events = session.scalar(select(func.count()).select_from(BookingEvent))
    assert events == 1 and len(_by_source(w)) == 1
    for body in (
        booking_event("cancelled", "booking-8b", occurred_at="2026-11-10T11:00:00Z"),
        booking_event("created", "booking-8a"),
        booking_event(
            "rescheduled", "booking-8b", previous="booking-8a", occurred_at="2026-11-10T10:00:00Z"
        ),
    ):
        assert lab.hook(body).status_code == 200
    visible = [row for row in _bookings(w) if row.status != "merged"]
    assert sorted((row.status, row.reschedule_count) for row in visible) == [
        ("cancelled", 1),
        ("scheduled", 0),
    ]
    foreign = lab.create("signed_webhook", client_id=w.a2).json()
    for body in (booking_event("created", "booking-9a"), booking_event("created", "booking-8a")):
        response = lab.hook(
            body, path=foreign["source"]["callback_path"], secret=foreign["signing_secret"]
        )
        assert response.status_code == 200
    assert len(_by_source(w, w.a2)) == 1 and len(_bookings(w, w.a2)) == 2
    assert len([row for row in _bookings(w) if row.status != "merged"]) == 2
    # Two Cal.com sources of one client are separate namespaces as well.
    calcom_two = lab.create("cal_com", secret=CALCOM_SECRET).json()["source"]
    shared = uid()
    assert lab.cal(calcom("BOOKING_CREATED", shared)).status_code == 200
    assert (
        lab.cal(calcom("BOOKING_CREATED", shared), path=calcom_two["callback_path"]).status_code
        == 200
    )
    sources = {str(row.source_id) for row in _bookings(w) if row.provider == "cal_com"}
    assert sources == {lab.calcom["id"], calcom_two["id"]}


# --- Review finding R007 (D-069, D-070): CRM changes are order-independent partial updates ---


def _deal_state(w, deal_ref):
    with Session(w.db.migration) as session:
        deal = session.scalars(select(CrmDeal).where(CrmDeal.deal_ref == deal_ref)).one()
        return (
            deal.pipeline,
            deal.stage,
            deal.previous_stage,
            deal.stage_at,
            deal.amount_minor,
            deal.currency,
            deal.amount_at,
            deal.payment_reference,
            deal.payment_reference_at,
        )


def _won_rule(lab):
    w = lab.w
    rules = f"/agencies/{w.a}/clients/{w.a1}/crm/stage-rules"
    created = lab.browser("owner_a").post(
        rules, json={"pipeline": "sales", "stage": "won", "outcome": "won"}
    )
    assert created.status_code == 201


def test_every_delivery_order_gives_the_same_deal(lab):
    # R007: four changes of one deal, two of which omit the optional values, delivered in all
    # 24 orders, end in one state: the latest stage, the latest supplied amount (with its
    # currency) and the latest supplied payment reference.
    w = lab.w
    _sale(w, "700000123")
    _won_rule(lab)

    def changes(ref):
        return [
            deal_event(ref, "new", occurred_at="2026-11-10T08:00:00Z", payment_reference="R-0"),
            deal_event(
                ref,
                "paid",
                occurred_at="2026-11-10T09:00:00Z",
                amount="1500.00",
                currency="EGP",
                payment_reference="700000123",
            ),
            deal_event(ref, "won", occurred_at="2026-11-10T10:00:00Z", previous="paid"),
            deal_event(
                ref, "won", occurred_at="2026-11-10T11:00:00Z", amount="80.00", currency="USD"
            ),
        ]

    states = set()
    for number, order in enumerate(itertools.permutations(range(4))):
        ref = f"P-{number:02d}"
        bodies = changes(ref)
        for index in order:
            assert lab.hook(bodies[index]).status_code == 200
        states.add(_deal_state(w, ref)[1:])
    assert len(states) == 1
    (state,) = states
    assert state[:2] == ("won", None)  # the 11:00 change carried no previous stage
    assert state[3:5] == (8_000, "USD") and state[6] == "700000123"
    deals = _deals(lab, amounts=True).json()["deals"]
    assert len(deals) == 24
    assert {
        (row["status"], row["amount"], row["currency"], row["linked_sale"]) for row in deals
    } == {("won_verified", "80.00", "USD", "700000123")}
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(RevenueEvidence)) == 1


def test_changes_at_the_same_instant_resolve_the_same_way(lab):
    # R007: two changes with the same occurrence time but different values give the same deal
    # in both orders; the amount and its currency never mix.
    w = lab.w
    first = deal_event(
        "T-a",
        "won",
        occurred_at="2026-11-10T09:00:00Z",
        amount="1500.00",
        currency="EGP",
        payment_reference="REF-A",
    )
    second = deal_event(
        "T-a",
        "lost",
        occurred_at="2026-11-10T09:00:00Z",
        amount="20.00",
        currency="USD",
        payment_reference="REF-B",
    )
    for ref, order in (("T-a", (first, second)), ("T-b", (second, first))):
        for body in order:
            item = dict(body, id=f"{body['id']}-{ref}", deal=dict(body["deal"], id=ref))
            assert lab.hook(item).status_code == 200
    assert _deal_state(w, "T-a")[1:] == _deal_state(w, "T-b")[1:]
    _, stage, _, _, minor, code, _, reference, _ = _deal_state(w, "T-a")
    assert (stage, minor, code, reference) == ("won", 2_000, "USD", "REF-B")
    # A later change without optional values keeps them; an older one supplying them loses.
    assert lab.hook(deal_event("T-a", "won", occurred_at="2026-11-10T10:00:00Z")).status_code == 200
    older = deal_event(
        "T-a", "won", occurred_at="2026-11-10T08:00:00Z", amount="9.00", currency="EGP"
    )
    assert lab.hook(dict(older, id="evt-older")).status_code == 200
    assert _deal_state(w, "T-a")[4:6] == (2_000, "USD")


def test_the_latest_payment_reference_decides_verification(lab):
    # R007: a later change with another payment reference replaces an earlier matching one in
    # either order, so the same history gives the same verification state.
    w = lab.w
    _sale(w, "700000123")
    _won_rule(lab)
    matching = deal_event(
        "V", "won", occurred_at="2026-11-10T09:00:00Z", payment_reference="700000123"
    )
    other = deal_event("V", "won", occurred_at="2026-11-10T10:00:00Z", payment_reference="999")
    for ref, order in (("V-1", (matching, other)), ("V-2", (other, matching))):
        for body in order:
            item = dict(body, id=f"{body['id']}-{ref}", deal=dict(body["deal"], id=ref))
            assert lab.hook(item).status_code == 200
    statuses = {row["deal_ref"]: row["status"] for row in _deals(lab).json()["deals"]}
    assert statuses == {"V-1": "won_unverified", "V-2": "won_unverified"}


# --- Review finding R008 (D-069): CRM totals cover every deal; detail rows are paged ---------


def _bulk_deals(lab, client_id, specs):
    from uuid import UUID, uuid4

    w = lab.w
    source = lab.webhook["id"] if client_id == w.a1 else None
    if source is None:
        source = lab.create("signed_webhook", client_id=client_id).json()["source"]["id"]
    now = datetime.now(UTC)
    with Session(w.db.migration) as session, session.begin():
        session.add_all(
            CrmDeal(
                id=uuid4(),
                agency_id=w.a,
                client_id=client_id,
                source_id=UUID(source),
                deal_ref=f"bulk-{prefix}-{index}",
                pipeline="sales",
                stage=stage,
                stage_at=now,
                amount_minor=1_000 + index,
                currency=currency,
                currency_exponent=2,
                amount_at=now,
                payment_reference=reference,
                payment_reference_at=None if reference is None else now,
                first_received_at=now - timedelta(seconds=index % 7),
                updated_at=now,
            )
            for prefix, stage, reference, currency, count in specs
            for index in range(count)
        )


def test_deal_totals_cover_every_deal_and_every_row_is_reachable(lab):
    # R008: with 1,203 deals the totals count every deal by status, the rows come in pages
    # with a complete cursor, every deal of the client appears exactly once, and no other
    # client's deal appears; amounts stay per deal and per currency for finance readers only.
    w = lab.w
    _sale(w, "700000123")
    _won_rule(lab)
    rules = f"/agencies/{w.a}/clients/{w.a1}/crm/stage-rules"
    lost = {"pipeline": "sales", "stage": "lost", "outcome": "lost"}
    assert lab.browser("owner_a").post(rules, json=lost).status_code == 201
    _bulk_deals(
        lab,
        w.a1,
        [
            ("open", "new", None, "EGP", 501),
            ("verified", "won", "700000123", "USD", 300),
            ("unverified", "won", "999", "EGP", 150),
            ("plain", "won", None, "USD", 50),
            ("lost", "lost", None, "EGP", 202),
        ],
    )
    _bulk_deals(lab, w.a2, [("foreign", "new", None, "EGP", 30)])
    expected = {"open": 501, "won_verified": 300, "won_unverified": 200, "lost": 202}
    path = f"/agencies/{w.a}/clients/{w.a1}/crm/deals"
    reader = lab.browser("analyst")
    first = reader.get(path).json()
    assert first["totals"] == expected
    assert len(first["deals"]) == 500 and first["has_more"] is True
    assert reader.get(path, params={"limit": 1}).json()["totals"] == expected
    seen, after, pages = [], None, 0
    while True:
        params = {"limit": 250} | ({"after": after} if after else {})
        page = reader.get(path, params=params).json()
        assert page["totals"] == expected
        seen.extend(row["id"] for row in page["deals"])
        pages += 1
        if not page["has_more"]:
            assert "next_after" not in page
            break
        after = page["next_after"]
    assert pages == 5 and len(seen) == len(set(seen)) == 1_203
    with Session(w.db.migration) as session:
        own = {
            str(item)
            for item in session.scalars(select(CrmDeal.id).where(CrmDeal.client_id == w.a1))
        }
    assert set(seen) == own
    assert all("amount" not in row for row in first["deals"])
    owner = lab.browser("owner_a")
    detailed = owner.get(path, params={"include_amounts": "true", "limit": 500}).json()
    assert {row["currency"] for row in detailed["deals"]} == {"EGP", "USD"}
    assert reader.get(path, params={"include_amounts": "true"}).status_code == 403
    for params in (
        {"after": "not-a-cursor"},
        {"after": "MjAyNi0xMS0xMHwx"},
        {"limit": 0},
        {"limit": 501},
    ):
        assert reader.get(path, params=params).status_code == 422, params
