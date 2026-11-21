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
    CrmDeal,
    IntegrationDelivery,
    IntegrationSourceSecret,
    RevenueEvidence,
)
from app.privacy import providers
from app.privacy.consent import ConsentSource, ConsentState, Purpose
from app.services.collection import record_consent
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
