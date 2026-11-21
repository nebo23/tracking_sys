"""Conversion delivery on disposable PostgreSQL (specification 014-B, D-064 decisions D6 to D10).

Uses the synthetic lab of connector_support with the Meta-shaped synthetic receiver that the API
builds next to the other synthetic providers, and real 004 consent, events and erasure through
the API, so the 003 cases C2, C3 and C5 and outbound replay blocking run end to end. Verified
sales come from the 007-A ledger; the journeys (person, subjects and clicks) are synthetic, as
006 is not implemented. Cases T-20 to T-35 of the entry review section 7.2 and T-52. No case
contacts Meta.
"""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from connector_support import make_lab
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.synthetic_meta_ads import SyntheticMetaAdsProvider
from app.connectors.synthetic_meta_capi import SyntheticMetaCapiProvider
from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind, calculate
from app.models import AuditEvent, ConversionAcknowledgement, ConversionDelivery
from app.privacy.consent import ConsentSource, ConsentState, Purpose
from app.security import digest, now_utc
from app.services.access import AccessService, ClientPermission
from app.services.collection import record_consent
from app.services.delivery import (
    ClickIdentifier,
    SaleCandidate,
    SyntheticJourney,
    _attempt,
    _claim,
    candidates_from_feed,
    candidates_from_ledger,
    enqueue_conversions,
    run_deliveries,
)

pytestmark = pytest.mark.integration
PROVIDER = "synthetic_meta_capi"
DATASET, OTHER_DATASET = "880001", "880002"
NOTICE = "a" * 64
GRANTED = {"ads.measurement": "granted", "sale_or_share": "granted", "attribution": "granted"}
USD = Currency("USD", 2)
ACCOUNT = "acct_shop"
FBCLID = "IwAR0SyntheticClickIdentifier_01"


@pytest.fixture
def capi(authenticated_world, api, tmp_path):
    lab = make_lab(authenticated_world, api, tmp_path)
    state = lab.state.with_name(lab.state.stem + "-meta-capi" + lab.state.suffix)
    lab.capi = SyntheticMetaCapiProvider(state)
    lab.registry = {PROVIDER: lab.capi}
    for dataset in (DATASET, OTHER_DATASET):
        lab.capi.define_dataset(dataset)
    lab.ingest = {}
    return lab


def _connect(lab, name, agency, client_id, dataset=DATASET, datasets=None, scopes=("ads_read",)):
    browser = lab.browser(name)
    response = browser.post(
        f"/agencies/{agency}/clients/{client_id}/connections",
        json={"provider": PROVIDER, "account": dataset},
    )
    assert response.status_code == 200, response.text
    url = response.json()["authorization_url"]
    code = lab.capi.approve(url, datasets or (dataset,), scopes=scopes)
    callback = browser.get(
        "/connectors/oauth/callback",
        params={"code": code, "state": parse_qs(urlsplit(url).query)["state"][0]},
        follow_redirects=False,
    )
    result = {k: v[0] for k, v in parse_qs(urlsplit(callback.headers["location"]).query).items()}
    return UUID(result["connection_id"]) if result.get("result") == "connected" else result


def _destination(lab, name, agency, client_id, connection_id, *, enable=True, **body):
    browser = lab.browser(name)
    base = f"/agencies/{agency}/clients/{client_id}/conversion-destinations"
    response = browser.post(base, json={"connection_id": str(connection_id), **body})
    assert response.status_code == 201, response.text
    destination = response.json()
    assert destination["enabled"] is False
    if enable:
        updated = browser.patch(f"{base}/{destination['id']}", json={"enabled": True})
        assert updated.status_code == 200, updated.text
        destination = updated.json()
    return UUID(destination["id"])


def _ingest(lab, agency, owner):
    if agency not in lab.ingest:
        issued = lab.browser(owner).post(
            f"/agencies/{agency}/service-credentials",
            json={
                "name": "Synthetic ingest",
                "kind": "ingest",
                "clients": [
                    {"client_id": str(client)}
                    for client in ((lab.w.a1, lab.w.a2) if agency == lab.w.a else (lab.w.b1,))
                ],
            },
        )
        assert issued.status_code == 201, issued.text
        client = lab.api_new_client()
        client.headers["Authorization"] = "Bearer " + issued.json()["key"]
        lab.ingest[agency] = client
    return lab.ingest[agency]


def _consent(lab, agency, client_id, choices, token=None, owner="owner_a"):
    body = {"choices": choices, "notice_sha256": NOTICE}
    if token:
        body["subject_token"] = token
    response = _ingest(lab, agency, owner).post(
        f"/agencies/{agency}/clients/{client_id}/consent", json=body
    )
    assert response.status_code == 200, response.text
    return response.json()["subject_token"] or token


def _event(lab, agency, client_id, token, event_id, owner="owner_a"):
    body = {
        "schema_version": 1,
        "event_id": str(event_id),
        "event_type": "page_view",
        "occurred_at": now_utc().isoformat(),
        "subject_token": token,
        "payload": {"url": f"https://shop.example.test/offer?fbclid={FBCLID}"},
    }
    response = _ingest(lab, agency, owner).post(
        f"/agencies/{agency}/clients/{client_id}/events", json=body
    )
    assert response.status_code in (200, 201, 202), response.text


def _erase(lab, agency, client_id, token, owner="owner_a"):
    response = lab.browser(owner).post(
        f"/agencies/{agency}/clients/{client_id}/deletion-requests", json={"subject_token": token}
    )
    assert response.status_code == 201, response.text


def _evidence(
    agency,
    client_id,
    operation,
    *,
    amount=10000,
    when=None,
    kind=None,
    parent=None,
    classification=EvidenceClass.CONFIRMED_CAPTURE,
    received=None,
):
    when = when or now_utc() - timedelta(hours=1)
    return Evidence(
        f"delivery-{operation}-{uuid4().hex[:8]}",
        agency,
        client_id,
        ACCOUNT,
        operation,
        kind or OperationKind.SALE,
        classification,
        Money(amount, USD),
        when,
        received or when + timedelta(minutes=1),
        parent_operation_id=parent,
    )


def _journey(tokens, *, clicks=None, source="system_generated", events=()):
    sale_hint = now_utc() - timedelta(hours=1)
    if clicks is None:
        clicks = (ClickIdentifier(FBCLID, sale_hint - timedelta(hours=2), uuid4()),)
    return SyntheticJourney(
        "person-1",
        tuple(digest(token) for token in tokens),
        tuple(clicks),
        source,
        tuple(events),
    )


def _candidates(records, journeys):
    return candidates_from_ledger(calculate(records), journeys)


def _key(agency, client_id, operation):
    from app.ledger import LedgerScope

    return (LedgerScope(agency, client_id, ACCOUNT), operation)


def _enqueue(lab, candidates, now=None):
    return enqueue_conversions(lab.w.db.runtime, lab.config, candidates, now=now)


def _deliver(lab, now=None, limit=10, registry=None):
    return run_deliveries(
        lab.w.db.runtime, lab.config, registry or lab.registry, now=now, limit=limit
    )


def _rows(lab, **conditions):
    with Session(lab.w.db.migration) as session:
        query = select(ConversionDelivery).order_by(ConversionDelivery.created_at)
        for name, value in conditions.items():
            query = query.where(getattr(ConversionDelivery, name) == value)
        return list(session.scalars(query))


def _acks(lab, delivery_id):
    with Session(lab.w.db.migration) as session:
        return list(
            session.scalars(
                select(ConversionAcknowledgement)
                .where(ConversionAcknowledgement.delivery_id == delivery_id)
                .order_by(ConversionAcknowledgement.attempt)
            )
        )


def _setup(lab, *, client_id=None, enable=True, **destination):
    w = lab.w
    client_id = client_id or w.a1
    connection = _connect(lab, "owner_a", w.a, client_id)
    target = _destination(lab, "owner_a", w.a, client_id, connection, enable=enable, **destination)
    token = _consent(lab, w.a, client_id, GRANTED)
    return connection, target, token


def _sale(lab, token, operation="sale-1", *, client_id=None, journey=None, **evidence):
    w = lab.w
    client_id = client_id or w.a1
    record = _evidence(w.a, client_id, operation, **evidence)
    if journey is None:
        # The click is received two hours before the sale.
        click = ClickIdentifier(FBCLID, record.effective_at - timedelta(hours=2), uuid4())
        journey = _journey([token], clicks=[click])
    journeys = {_key(w.a, client_id, operation): journey}
    return [record], journeys


@pytest.fixture(autouse=True)
def _client_factory(capi, api):
    capi.api_new_client = lambda: api.new_client(capi.config)


def test_delivery_connect_needs_ads_read(capi, caplog):
    # T-52: a delivery connection without the delivery permission (ads_read, V-14) is refused;
    # a grant with an unrequested permission is kept and flagged.
    w = capi.w
    assert _connect(capi, "owner_a", w.a, w.a1, scopes=()) == {"error": "scopes_missing"}
    with caplog.at_level(logging.WARNING, logger="tracking"):
        connection = _connect(capi, "owner_a", w.a, w.a1, scopes=("ads_read", "ads_management"))
    assert isinstance(connection, UUID)
    assert "connector_extra_scopes" in [record.getMessage() for record in caplog.records]
    row = capi.row(connection)
    assert (row.external_account_id, row.granted_scopes) == (
        DATASET,
        ["ads_read", "ads_management"],
    )
    # Delivery connections are never synchronized.
    assert capi.sync("owner_a", w.a, w.a1, connection).status_code == 422
    assert capi.worker(registry=capi.registry, schedule=True)["sync"] == {}
    # A spend connection cannot carry a destination.
    spend_state = capi.state.with_name(capi.state.stem + "-meta-ads" + capi.state.suffix)
    ads = SyntheticMetaAdsProvider(spend_state)
    ads.define_account("act_1001")
    response = capi.browser("owner_a").post(
        f"/agencies/{w.a}/clients/{w.a2}/connections",
        json={"provider": "synthetic_meta_ads", "account": "act_1001"},
    )
    url = response.json()["authorization_url"]
    code = ads.approve(url, ("act_1001",))
    callback = capi.browser("owner_a").get(
        "/connectors/oauth/callback",
        params={"code": code, "state": parse_qs(urlsplit(url).query)["state"][0]},
        follow_redirects=False,
    )
    spend = parse_qs(urlsplit(callback.headers["location"]).query)["connection_id"][0]
    refused = capi.browser("owner_a").post(
        f"/agencies/{w.a}/clients/{w.a2}/conversion-destinations", json={"connection_id": spend}
    )
    assert (refused.status_code, refused.json()) == (422, {"error": "not_a_delivery_connection"})


def test_only_verified_sales_are_enqueued(capi):
    # T-20: only posted confirmed captures or settlements are enqueued; purchase signals and
    # manual declarations never are.
    w = capi.w
    _, _, token = _setup(capi)
    records = [
        _evidence(w.a, w.a1, "sale-capture"),
        _evidence(w.a, w.a1, "sale-settled", classification=EvidenceClass.CONFIRMED_SETTLEMENT),
        _evidence(w.a, w.a1, "sale-signal", classification=EvidenceClass.PURCHASE_SIGNAL),
        _evidence(w.a, w.a1, "sale-declared", classification=EvidenceClass.MANUAL_DECLARATION),
    ]
    journeys = {_key(w.a, w.a1, item.operation_id): _journey([token]) for item in records}
    ledger = calculate(records)
    candidates = candidates_from_ledger(ledger, journeys)
    assert {item.transaction_id for item in candidates} == {"sale-capture", "sale-settled"}
    forged = SaleCandidate(
        candidates[0].scope,
        "sale-signal",
        candidates[0].sale,
        frozenset({"purchase_signal"}),
        candidates[0].journey,
    )
    assert _enqueue(capi, [*candidates, forged]) == {"queued": 2, "not_verified": 1}
    assert len(_rows(capi)) == 2
    # The ledger_feed journal gives the same candidates.
    from app.attribution import ledger_feed

    fed = candidates_from_feed(ledger_feed(sorted(records, key=lambda r: r.received_at)), journeys)
    assert {item.transaction_id for item in fed} == {"sale-capture", "sale-settled"}
    assert all(
        item.evidence_classes <= {"confirmed_capture", "confirmed_settlement"} for item in fed
    )


def test_c2_measurement_denied(capi):
    # T-21 (003 C2): ads.measurement denied gives no outbox row; the refusal is counted.
    w = capi.w
    _setup(capi)
    token = _consent(capi, w.a, w.a1, {**GRANTED, "ads.measurement": "denied"})
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"consent_denied": 1}
    assert _rows(capi) == []


def test_sale_or_share_not_granted(capi):
    # T-22: sale_or_share not granted gives no outbox row.
    w = capi.w
    _setup(capi)
    token = _consent(capi, w.a, w.a1, {"ads.measurement": "granted", "attribution": "granted"})
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"consent_unknown": 1}
    assert _rows(capi) == []


def test_c3_withdrawal_after_enqueue_blocks_at_claim(capi):
    # T-23 (003 C3): a withdrawal after enqueue makes the claim suppress the delivery as
    # blocked; the payload is destroyed and nothing is sent.
    w = capi.w
    _, _, token = _setup(capi)
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"queued": 1}
    row = _rows(capi)[0]
    assert row.ciphertext is not None and row.consent_basis and row.policy_version == "003-B.1"
    _consent(capi, w.a, w.a1, {"ads.measurement": "withdrawn"}, token=token)
    assert _deliver(capi) == {"blocked": 1}
    row = _rows(capi)[0]
    assert (row.status, row.reason, row.ciphertext, row.attempts) == (
        "blocked",
        "consent_withdrawn",
        None,
        0,
    )
    assert capi.capi.received(DATASET) == []


def test_c5_gpc_suppresses(capi):
    # T-24 (003 C5): a GPC signal denies sale_or_share and ads.measurement and suppresses, at
    # enqueue and at the claim.
    w = capi.w
    _, _, token = _setup(capi)
    second = _consent(capi, w.a, w.a1, GRANTED)
    assert _enqueue(capi, _candidates(*_sale(capi, second, "sale-early"))) == {"queued": 1}
    for subject in (token, second):
        with Session(w.db.runtime) as session, session.begin():
            record_consent(
                session,
                w.a,
                w.a1,
                source=ConsentSource.GPC,
                notice_sha256=NOTICE,
                choices={
                    Purpose.SALE_OR_SHARE: ConsentState.DENIED,
                    Purpose.ADS_MEASUREMENT: ConsentState.DENIED,
                },
                subject_token=subject,
                captured_at=None,
                recheck=lambda: None,
            )
    assert _enqueue(capi, _candidates(*_sale(capi, token, "sale-late"))) == {"consent_denied": 1}
    assert _deliver(capi) == {"blocked": 1}
    assert _rows(capi)[0].reason == "consent_denied"
    assert capi.capi.received(DATASET) == []


def test_tombstones_block_enqueue_claim_and_replay(capi):
    # T-25: a subject tombstone blocks at enqueue and at the claim; a replay of an event ID known
    # before a deletion is blocked, even with another, consenting subject.
    w = capi.w
    _, _, token = _setup(capi)
    erased = _consent(capi, w.a, w.a1, GRANTED)
    _erase(capi, w.a, w.a1, erased)
    assert _enqueue(capi, _candidates(*_sale(capi, erased, "sale-erased"))) == {
        "subject_deleted": 1
    }
    later = _consent(capi, w.a, w.a1, GRANTED)
    assert _enqueue(capi, _candidates(*_sale(capi, later, "sale-later"))) == {"queued": 1}
    _erase(capi, w.a, w.a1, later)
    assert _deliver(capi) == {"blocked": 1}
    assert _rows(capi, status="blocked")[0].reason == "subject_deleted"
    # Replay: the click event of an erased subject cannot be reused for another subject.
    # A page view needs analytics consent (004, D-027).
    clicked = _consent(capi, w.a, w.a1, {**GRANTED, "analytics.first_party": "granted"})
    click_event = uuid4()
    _event(capi, w.a, w.a1, clicked, click_event)
    received = now_utc() - timedelta(hours=3)
    replay = _journey([token], clicks=[ClickIdentifier(FBCLID, received, click_event)])
    pending = _journey([token], clicks=[ClickIdentifier(FBCLID, received, click_event)])
    assert _enqueue(capi, _candidates(*_sale(capi, token, "sale-pending", journey=pending))) == {
        "queued": 1
    }
    _erase(capi, w.a, w.a1, clicked)
    assert _enqueue(capi, _candidates(*_sale(capi, token, "sale-replay", journey=replay))) == {
        "replay_before_deletion": 1
    }
    assert _deliver(capi) == {"blocked": 1}
    assert _rows(capi, status="blocked")[-1].reason == "replay_before_deletion"
    assert capi.capi.received(DATASET) == []


def test_repeated_enqueue_and_retry_keep_one_event(capi):
    # T-26: a repeated enqueue leaves one row; a retry sends the same event_id, and the
    # synthetic receiver counts one event.
    _, _, token = _setup(capi)
    candidates = _candidates(*_sale(capi, token))
    assert _enqueue(capi, candidates) == {"queued": 1}
    assert _enqueue(capi, candidates) == {"unchanged": 1}
    assert len(_rows(capi)) == 1
    capi.capi.set_behavior("send_script", "throttled,server_error")
    start = now_utc()
    assert _deliver(capi, now=start) == {"deferred": 1}
    assert _deliver(capi, now=start + timedelta(seconds=61)) == {"deferred": 1}
    assert _deliver(capi, now=start + timedelta(seconds=200)) == {"delivered": 1}
    row = _rows(capi)[0]
    assert (row.status, row.attempts, row.ciphertext) == ("delivered", 3, None)
    assert [ack.outcome for ack in _acks(capi, row.id)] == ["rate_limited", "retryable", "accepted"]
    received = capi.capi.received(DATASET)
    assert [item["event_id"] for item in received] == [row.event_id]
    assert capi.capi.counted(DATASET) == [("Purchase", row.event_id)]
    # A delivered sale is never sent again.
    assert _enqueue(capi, candidates) == {"unchanged": 1}
    assert _deliver(capi, now=start + timedelta(hours=1)) == {}


def test_attempt_cap_and_deadline(capi):
    # T-27: retryable failures back off and stop after 5 attempts; no attempt is made after the
    # age limit less 1 hour; event_time is never moved.
    w = capi.w
    _, _, token = _setup(capi)
    start = now_utc()
    sale_time = start - timedelta(hours=2)
    records, journeys = _sale(capi, token, "sale-capped", when=sale_time)
    assert _enqueue(capi, _candidates(records, journeys), now=start) == {"queued": 1}
    capi.capi.set_behavior("send_script", ",".join(["server_error"] * 6))
    moment, outcomes = start, []
    for _ in range(6):
        outcomes.append(_deliver(capi, now=moment))
        moment += timedelta(minutes=20)
    assert outcomes == [{"deferred": 1}] * 4 + [{"undeliverable": 1}, {}]
    row = _rows(capi)[0]
    assert (row.status, row.reason, row.attempts, row.ciphertext) == (
        "undeliverable",
        "retries_exhausted",
        5,
        None,
    )
    assert len(_acks(capi, row.id)) == 5
    assert row.event_time == sale_time
    # A sale close to its age limit: the retry would start after the deadline, so it expires.
    old = start - timedelta(days=7) + timedelta(hours=1, seconds=10)
    records, journeys = _sale(capi, token, "sale-old", when=old)
    assert _enqueue(capi, _candidates(records, journeys), now=start) == {"queued": 1}
    capi.capi.set_behavior("send_script", "server_error")
    assert _deliver(capi, now=start) == {"expired": 1}
    expired = _rows(capi, status="expired")[0]
    assert (expired.reason, expired.attempts, expired.deadline) == (
        "deadline_passed",
        1,
        old + timedelta(days=7) - timedelta(hours=1),
    )
    # Past the deadline nothing is claimed at all, and an older sale is refused at enqueue.
    records, journeys = _sale(capi, token, "sale-waiting", when=start - timedelta(days=6))
    assert _enqueue(capi, _candidates(records, journeys), now=start) == {"queued": 1}
    assert _deliver(capi, now=start + timedelta(days=2)) == {"expired": 1}
    records, journeys = _sale(capi, token, "sale-ancient", when=start - timedelta(days=8))
    assert _enqueue(capi, _candidates(records, journeys), now=start) == {"too_old": 1}
    assert [item["event_time"] for item in capi.capi.received(DATASET)] == []
    assert all(ack.attempt >= 1 for ack in _acks(capi, expired.id))
    assert w.a  # agency fixture in use


def test_requeue_and_dismiss(capi):
    # T-28: a configuration rejection can be requeued by an Owner or Admin at most 3 times
    # with the same event ID and an audit event; a payload rejection can only be dismissed.
    w = capi.w
    _, _, token = _setup(capi)
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"queued": 1}
    base = f"/agencies/{w.a}/clients/{w.a1}/conversion-deliveries"
    capi.capi.set_behavior("send_script", ",".join(["permission"] * 4))
    row = None
    for round_ in range(4):
        assert _deliver(capi) == {"rejected": 1}
        row = _rows(capi)[0]
        assert (row.status, row.rejection_class, row.reason) == (
            "rejected",
            "configuration",
            "permission_missing",
        )
        assert row.ciphertext is not None
        # Nothing loops automatically.
        assert _deliver(capi) == {}
        if round_ < 3:
            assert capi.browser("analyst").post(f"{base}/{row.id}/requeue").status_code == 403
            requeued = capi.browser("admin").post(f"{base}/{row.id}/requeue")
            assert requeued.status_code == 200, requeued.text
            assert requeued.json()["status"] == "queued"
    refused = capi.browser("owner_a").post(f"{base}/{row.id}/requeue")
    assert (refused.status_code, refused.json()) == (409, {"error": "requeue_not_available"})
    assert {ack.attempt for ack in _acks(capi, row.id)} == {1, 2, 3, 4}
    assert len({item.event_id for item in _rows(capi)}) == 1
    dismissed = capi.browser("owner_a").post(f"{base}/{row.id}/dismiss")
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"
    assert _rows(capi)[0].ciphertext is None
    # A payload rejection can only be dismissed.
    assert _enqueue(capi, _candidates(*_sale(capi, token, "sale-bad"))) == {"queued": 1}
    capi.capi.set_behavior("send_script", "invalid_parameter")
    assert _deliver(capi) == {"rejected": 1}
    bad = _rows(capi, rejection_class="payload")[0]
    assert (bad.reason, bad.ciphertext, bad.ended_at is not None) == (
        "invalid_parameter",
        None,
        True,
    )
    assert capi.browser("owner_a").post(f"{base}/{bad.id}/requeue").status_code == 409
    assert capi.browser("owner_a").post(f"{base}/{bad.id}/dismiss").status_code == 200
    with Session(w.db.migration) as session:
        actions = list(
            session.scalars(select(AuditEvent.action).where(AuditEvent.action.like("delivery.%")))
        )
    assert sorted(actions) == ["delivery.dismissed"] * 2 + ["delivery.requeued"] * 3


def test_refunds_before_the_claim(capi):
    # T-29: a sale fully refunded before the claim is cancelled; a partial refund sends the net
    # in the sale's minor units and original currency.
    w = capi.w
    _, _, token = _setup(capi)
    full = _evidence(w.a, w.a1, "sale-full", amount=10000)
    partial = _evidence(w.a, w.a1, "sale-partial", amount=10000)
    journeys = {
        _key(w.a, w.a1, "sale-full"): _journey([token]),
        _key(w.a, w.a1, "sale-partial"): _journey([token]),
    }
    assert _enqueue(capi, candidates_from_ledger(calculate([full, partial]), journeys)) == {
        "queued": 2
    }
    refunds = [
        _evidence(
            w.a,
            w.a1,
            "refund-full",
            amount=10000,
            kind=OperationKind.REFUND,
            classification=EvidenceClass.CONFIRMED_ADJUSTMENT,
            parent="sale-full",
        ),
        _evidence(
            w.a,
            w.a1,
            "refund-partial",
            amount=3050,
            kind=OperationKind.REFUND,
            classification=EvidenceClass.CONFIRMED_ADJUSTMENT,
            parent="sale-partial",
        ),
    ]
    ledger = calculate([full, partial, *refunds])
    assert _enqueue(capi, candidates_from_ledger(ledger, journeys)) == {
        "cancelled": 1,
        "updated": 1,
    }
    assert _deliver(capi) == {"delivered": 1}
    cancelled = _rows(capi, status="cancelled")[0]
    assert (cancelled.reason, cancelled.ciphertext) == ("sale_reversed", None)
    delivered = _rows(capi, status="delivered")[0]
    assert (delivered.value_minor, delivered.currency) == (6950, "USD")
    (event,) = capi.capi.received(DATASET)
    assert event["custom_data"] == {"value": 69.5, "currency": "USD"}
    assert event["event_name"] == "Purchase" and "order_id" not in event["custom_data"]


def test_lease_fencing_and_crash_after_send(capi):
    # T-30: two workers: one claims and sends; after a lease expires the next attempt is fenced
    # and a superseded attempt writes nothing; a crash after sending re-sends the same event_id.
    _, _, token = _setup(capi)
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"queued": 1}
    engine, config = capi.w.db.runtime, capi.config
    keyring, keys = config.token_keys(), config.tombstone_keys()
    start = now_utc()
    first = _claim(engine, keyring, keys, (PROVIDER,), start)
    assert first.attempt == 1
    assert _claim(engine, keyring, keys, (PROVIDER,), start + timedelta(seconds=30)) is None
    # The lease expires; the next worker reclaims the delivery under attempt 2 and sends it.
    assert _deliver(capi, now=start + timedelta(minutes=3)) == {"delivered": 1}
    assert _attempt(engine, capi.registry, first, lambda: start + timedelta(minutes=4)) == (
        "superseded"
    )
    row = _rows(capi)[0]
    assert [ack.attempt for ack in _acks(capi, row.id)] == [2]
    # A crash after sending: the next attempt sends the same event_id and Meta counts one.
    assert _enqueue(capi, _candidates(*_sale(capi, token, "sale-crash"))) == {"queued": 1}

    class Crash(BaseException):
        pass

    class CrashAfterSend:
        capability = capi.capi.capability

        def send_event(self, token, **arguments):
            capi.capi.send_event(token, **arguments)
            raise Crash()

    with pytest.raises(Crash):
        _deliver(capi, now=start, registry={PROVIDER: CrashAfterSend()})
    assert _deliver(capi, now=start + timedelta(minutes=3)) == {"delivered": 1}
    crashed = _rows(capi, status="delivered")[-1]
    copies = [item for item in capi.capi.received(DATASET) if item["event_id"] == crashed.event_id]
    assert len(copies) == 2
    assert capi.capi.counted(DATASET).count(("Purchase", crashed.event_id)) == 1


def test_invalid_token_waits_for_reconnection(capi):
    # T-31: an invalid token makes the delivery connection reconnect_required; its deliveries
    # wait, resume after reconnection, and otherwise expire.
    w = capi.w
    connection, _, token = _setup(capi)
    start = now_utc()
    late = start - timedelta(days=6, hours=22)
    records, journeys = _sale(capi, token, "sale-1")
    late_records, late_journeys = _sale(capi, token, "sale-late", when=late)
    assert _enqueue(
        capi, _candidates(records + late_records, {**journeys, **late_journeys}), now=start
    ) == {"queued": 2}
    capi.capi.set_behavior("send_script", "invalid_token")
    assert _deliver(capi, now=start, limit=1) == {"waiting": 1}
    row = capi.row(connection)
    assert (row.status, row.status_reason) == ("reconnect_required", "provider_revoked")
    assert {item.status for item in _rows(capi)} == {"queued"}
    assert _deliver(capi, now=start + timedelta(minutes=5)) == {}
    reconnect = capi.browser("owner_a").post(
        f"/agencies/{w.a}/clients/{w.a1}/connections/{connection}/reconnect"
    )
    url = reconnect.json()["authorization_url"]
    code = capi.capi.approve(url, (DATASET,))
    callback = capi.browser("owner_a").get(
        "/connectors/oauth/callback",
        params={"code": code, "state": parse_qs(urlsplit(url).query)["state"][0]},
        follow_redirects=False,
    )
    assert "result=reconnected" in callback.headers["location"]
    assert _deliver(capi, now=start + timedelta(hours=3)) == {"expired": 1, "delivered": 1}
    assert _rows(capi, status="expired")[0].event_time == late


def test_disabling_cancels_and_destroys(capi):
    # T-32: disabling a destination cancels its queued deliveries and destroys their payloads.
    w = capi.w
    _, target, token = _setup(capi)
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"queued": 1}
    response = capi.browser("owner_a").patch(
        f"/agencies/{w.a}/clients/{w.a1}/conversion-destinations/{target}", json={"enabled": False}
    )
    assert response.status_code == 200 and response.json()["enabled"] is False
    row = _rows(capi)[0]
    assert (row.status, row.reason, row.ciphertext) == ("cancelled", "destination_disabled", None)
    assert _enqueue(capi, _candidates(*_sale(capi, token, "sale-2"))) == {"no_destination": 1}
    assert _deliver(capi) == {}


def test_test_event_code(capi):
    # T-33: a test event code, when set, is sent with each event; the receiver keeps test events
    # apart and never counts them.
    _, _, token = _setup(capi, test_event_code="TEST12345")
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"queued": 1}
    assert _deliver(capi) == {"delivered": 1}
    assert capi.capi.received(DATASET) == []
    (event,) = capi.capi.received(DATASET, test=True)
    assert event["test_event_code"] == "TEST12345"
    assert capi.capi.counted(DATASET) == []


def test_isolation_and_no_identifiers_in_answers(capi, api, caplog):
    # T-34: deliveries never cross clients; values need finance:read; no answer or log contains
    # fbc, fbclid, a payload, the event ID or a trace ID.
    w = capi.w
    caplog.set_level(logging.DEBUG)
    _, target, token = _setup(capi)
    other_connection = _connect(capi, "owner_a", w.a, w.a2, OTHER_DATASET)
    _destination(capi, "owner_a", w.a, w.a2, other_connection)
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"queued": 1}
    assert _deliver(capi) == {"delivered": 1}
    (row,) = _rows(capi)
    assert row.client_id == w.a1 and capi.capi.received(OTHER_DATASET) == []
    deliveries = f"/agencies/{w.a}/clients/{w.a1}/conversion-deliveries"
    destinations = f"/agencies/{w.a}/clients/{w.a1}/conversion-destinations"
    owner = capi.browser("owner_a").get(deliveries)
    assert owner.status_code == 200
    (item,) = owner.json()
    assert (item["value"], item["currency"], item["status"]) == ("100.00", "USD", "delivered")
    assert capi.browser("analyst").get(deliveries).status_code == 403
    assert capi.browser("viewer").get(deliveries).status_code == 403
    assert capi.browser("analyst").get(destinations).status_code == 200
    assert capi.browser("owner_b").get(deliveries).status_code == 403
    assert (
        capi.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a2}/conversion-deliveries").json()
        == []
    )
    keys = {}
    for kind, financial in (("read", True), ("read", False), ("ingest", False)):
        with Session(w.db.runtime, expire_on_commit=False) as session, session.begin():
            _, raw = AccessService(session, w.users.owner_a, capi.config).issue_service_key(
                w.a, f"Synthetic {kind}", [ClientPermission(w.a1, financial)], kind=kind
            )
        client = api.new_client(capi.config)
        client.headers["Authorization"] = f"Bearer {raw}"
        keys[kind, financial] = client
    assert keys["read", True].get(deliveries).status_code == 200
    assert keys["read", False].get(deliveries).status_code == 403
    assert keys["ingest", False].get(deliveries).status_code == 401
    trace = _acks(capi, row.id)[0].trace_id
    answers = owner.text + capi.browser("owner_a").get(destinations).text
    logs = caplog.text
    for secret in (FBCLID, "fb.1.", row.event_id, trace):
        assert secret not in answers and secret not in logs, secret
    assert target  # destination of client A1


def test_field_and_match_key_refusals(capi):
    # T-35: a website conversion lacks client_user_agent, which is never collected, so it is
    # refused as provider_field_missing; a conversion without fbc is refused as no_match_key.
    _, _, token = _setup(capi)
    website = _journey([token], source="website")
    assert _enqueue(capi, _candidates(*_sale(capi, token, journey=website))) == {
        "provider_field_missing": 1
    }
    late_click = ClickIdentifier(FBCLID, now_utc(), uuid4())
    for journey in (_journey([token], clicks=[]), _journey([token], clicks=[late_click])):
        assert _enqueue(capi, _candidates(*_sale(capi, token, journey=journey))) == {
            "no_match_key": 1
        }
    assert _rows(capi) == []
    # The fbc sent is fb.1.<first receipt in milliseconds>.<fbclid>, never hashed.
    received = datetime(2026, 11, 20, 8, 30, 15, 123000, tzinfo=UTC)
    clicked = _journey([token], clicks=[ClickIdentifier(FBCLID, received, uuid4())])
    assert _enqueue(capi, _candidates(*_sale(capi, token, "sale-ok", journey=clicked))) == {
        "queued": 1
    }
    assert _deliver(capi) == {"delivered": 1}
    (event,) = capi.capi.received(DATASET)
    assert event["user_data"] == {"fbc": f"fb.1.{int(received.timestamp() * 1000)}.{FBCLID}"}
    assert set(event) == {
        "event_name",
        "event_time",
        "event_id",
        "action_source",
        "user_data",
        "custom_data",
        "test_event_code",
    }


def test_disconnect_ends_deliveries(capi):
    # D13: a delivery connection's disconnect cancels its open deliveries and disables its
    # destination, which keeps its configuration.
    w = capi.w
    connection, target, token = _setup(capi)
    assert _enqueue(capi, _candidates(*_sale(capi, token))) == {"queued": 1}
    assert capi.disconnect("owner_a", w.a, w.a1, connection).status_code == 202
    assert capi.worker(registry=capi.registry)["teardown"] == {"disconnected": 1}
    row = _rows(capi)[0]
    assert (row.status, row.reason, row.ciphertext) == ("cancelled", "connection_ended", None)
    listed = (
        capi.browser("owner_a")
        .get(f"/agencies/{w.a}/clients/{w.a1}/conversion-destinations")
        .json()
    )
    assert [(item["id"], item["enabled"]) for item in listed] == [(str(target), False)]
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(ConversionDelivery)) == 1
