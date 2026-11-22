"""Stored revenue evidence and the ledger read on disposable PostgreSQL (specification 015-A).

D-067 decisions D2 and D11; cases T-01 to T-05 of the entry review section 7.1. Every record is
synthetic and is appended through app.services.revenue.append_evidence under the client's
revenue lock, whose clock read is the receipt time. No case contacts a payment provider.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.attribution import (
    Association,
    AttributionModel,
    ModelVersion,
    Touchpoint,
    attribute,
    ledger_feed,
    sale_conversion,
    sale_state,
)
from app.attribution import EvidenceClass as TouchClass
from app.ledger import (
    Currency,
    Evidence,
    EvidenceClass,
    LedgerScope,
    Money,
    OperationKind,
    calculate,
)
from app.models import RevenueEvidence
from app.privacy.consent import ConsentState
from app.services.access import AccessService, ClientPermission
from app.services.delivery import (
    ClickIdentifier,
    SyntheticJourney,
    candidates_from_feed,
    candidates_from_ledger,
)
from app.services.revenue import append_evidence, client_ledger, load_evidence, lock_revenue

pytestmark = pytest.mark.integration

EGP = Currency("EGP", 2)
USD = Currency("USD", 2)
ACCOUNT = "paymob-egypt"
SALE_AT = datetime(2026, 11, 10, 9, 30, tzinfo=UTC)


def _record(
    world,
    operation,
    kind=OperationKind.SALE,
    classification=EvidenceClass.CONFIRMED_CAPTURE,
    amount=100_000,
    *,
    currency=EGP,
    client=None,
    agency=None,
    parent=None,
    delivery=None,
    when=SALE_AT,
    reason=None,
):
    # A Paymob record carries its signed order ID in the source reference, and an adjustment
    # carries its sale's order (D-070); the synthetic order is "8" and the sale's operation.
    order = parent if parent is not None else operation
    return Evidence(
        delivery or f"synthetic:{operation}:{kind.value}:{amount}",
        agency or world.a,
        client or world.a1,
        ACCOUNT,
        operation,
        kind,
        classification,
        Money(amount, currency),
        when,
        when,  # replaced by the database clock when appended
        parent_operation_id=parent,
        reason=reason,
        source_reference=f"paymob:4097558:8{order}",
    )


# Append records one per transaction under the client's revenue lock; returns the records with
# their stored receipt times and the append outcomes.
def _append(db, records, intake="paymob"):
    stored, outcomes = [], []
    for item in records:
        with Session(db.runtime) as session, session.begin():
            received = lock_revenue(session, item.client_id)
            item = replace(item, received_at=received)
            outcomes.append(append_evidence(session, item, intake, uuid4()))
            stored.append(item)
    return stored, outcomes


def _rows(db, client_id):
    with Session(db.migration) as session:
        return session.scalar(
            select(func.count())
            .select_from(RevenueEvidence)
            .where(RevenueEvidence.client_id == client_id)
        )


def _revenue(client, world, agency=None, client_id=None):
    return client.get(f"/agencies/{agency or world.a}/clients/{client_id or world.a1}/revenue")


def test_stored_ledger_equals_in_memory_calculation(world):
    # T-01: the stored records, replayed in receipt order, give the same calculation and
    # journal as the in-memory 007-A calculation of the same records.
    records = [
        _record(
            world,
            "9001",
            OperationKind.REFUND,
            EvidenceClass.CONFIRMED_ADJUSTMENT,
            30_000,
            parent="9000",
            when=SALE_AT + timedelta(hours=2),
        ),
        _record(world, "9000"),
        _record(world, "9002", amount=50_000, currency=USD),
        _record(
            world,
            "9003",
            OperationKind.REFUND,
            EvidenceClass.CONFIRMED_ADJUSTMENT,
            10_000,
            parent="9002",
            currency=USD,
            when=SALE_AT + timedelta(hours=3),
            reason="void",
        ),
        _record(
            world,
            "9010",
            OperationKind.REFUND,
            EvidenceClass.CONFIRMED_ADJUSTMENT,
            5_000,
            parent="missing",
        ),
        _record(world, "9100", classification=EvidenceClass.MANUAL_DECLARATION, amount=7_000),
    ]
    stored, outcomes = _append(world.db, records)
    assert outcomes == ["stored"] * len(records)
    with Session(world.db.runtime) as session:
        loaded = load_evidence(session, world.a, world.a1)
        ledger = client_ledger(session, world.a, world.a1)
    assert loaded == stored
    assert ledger.calculation == calculate(stored)
    assert ledger.journal == ledger_feed(stored)
    totals = ledger.calculation.totals(world.a, world.a1)
    assert totals["EGP"].net == 70_000 and totals["USD"].net == 40_000
    assert [item.operation_id for item in ledger.calculation.pending] == ["9010"]
    assert [item.operation_id for item in ledger.calculation.unverified] == ["9100"]
    # The receipt order is the database clock under the lock, increasing per client.
    times = [item.received_at for item in loaded]
    assert times == sorted(times)


def test_exact_redelivery_is_stored_once(world):
    # T-02 (M): an exact redelivery (same delivery ID and content) inserts nothing, and the
    # ledger counts the sale once.
    sale = _record(world, "9200")
    _, outcomes = _append(world.db, [sale, sale, sale])
    assert outcomes == ["stored", "duplicate", "duplicate"]
    assert _rows(world.db, world.a1) == 1
    with Session(world.db.runtime) as session:
        ledger = client_ledger(session, world.a, world.a1)
    assert ledger.calculation.totals(world.a, world.a1)["EGP"].captured == 100_000


def test_reused_delivery_id_is_reported(world):
    # T-02: a reused delivery ID with other content is stored, and 007-A reports it.
    first = _record(world, "9300", delivery="paymob:9300:reused")
    other = _record(world, "9300", amount=90_000, delivery="paymob:9300:reused")
    _, outcomes = _append(world.db, [first, other])
    assert outcomes == ["stored", "stored"]
    with Session(world.db.runtime) as session:
        ledger = client_ledger(session, world.a, world.a1)
    reasons = [item.reason.value for item in ledger.calculation.reconciliation]
    assert reasons == ["delivery_id_reused"]
    assert ledger.calculation.totals(world.a, world.a1)["EGP"].captured == 100_000


def test_revenue_read_needs_finance_access(authenticated_world, api):
    # T-03 (M): two agencies with two clients each. The read needs finance:read: managers and
    # read keys with the financial grant; client:read readers, other agencies and ingest keys
    # are refused, and no answer carries another client's data.
    w = authenticated_world
    _append(
        w.db,
        [
            _record(w, "9400"),
            _record(w, "9401", client=w.a2, amount=1_111),
            _record(w, "9402", agency=w.b, client=w.b1, amount=2_222),
        ],
    )
    owner = _revenue(w.signed_in("owner_a"), w)
    assert owner.status_code == 200
    body = owner.json()
    assert [item["operation_id"] for item in body["verified"]["transactions"]] == ["9400"]
    assert body["verified"]["totals"] == [
        {
            "currency": "EGP",
            "captured": "1000.00",
            "refunded": "0.00",
            "charged_back": "0.00",
            "reversed": "0.00",
            "corrected": "0.00",
            "net": "1000.00",
        }
    ]
    assert "1111" not in owner.text and "2222" not in owner.text and "11.11" not in owner.text
    assert _revenue(w.signed_in("admin"), w).status_code == 200
    for name in ("analyst", "viewer", "owner_b", "outsider"):
        assert _revenue(w.signed_in(name), w).status_code == 403, name
    assert (
        _revenue(w.signed_in("owner_b"), w, w.b, w.b1).json()["verified"]["transactions"][0][
            "operation_id"
        ]
        == "9402"
    )
    assert _revenue(w.signed_in("owner_a"), w, w.a, w.b1).status_code == 403
    keys = {}
    for kind, financial in (("read", True), ("read", False), ("ingest", False)):
        with Session(w.db.runtime, expire_on_commit=False) as session, session.begin():
            _, raw = AccessService(session, w.users.owner_a, api.config).issue_service_key(
                w.a, f"Synthetic {kind}", [ClientPermission(w.a1, financial)], kind=kind
            )
        client = api.new_client()
        client.headers["Authorization"] = f"Bearer {raw}"
        keys[kind, financial] = client
    assert _revenue(keys["read", True], w).status_code == 200
    assert _revenue(keys["read", True], w, w.a, w.a2).status_code == 403
    assert _revenue(keys["read", False], w).status_code == 403
    assert _revenue(keys["ingest", False], w).status_code == 401


def test_runtime_role_cannot_update_or_delete_evidence(world):
    # T-04: tracking_app may insert and read evidence, never update or delete it.
    _append(world.db, [_record(world, "9500")])
    for statement in (
        "UPDATE revenue_evidence SET amount_minor = 1",
        "DELETE FROM revenue_evidence",
        "TRUNCATE revenue_evidence",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            with world.db.runtime.begin() as connection:
                connection.execute(text(statement))
    assert _rows(world.db, world.a1) == 1


def test_stored_ledger_feeds_delivery_and_attribution(world):
    # T-05: the stored calculation and journal feed 014-B and 008-A unchanged; journeys stay
    # synthetic until 006.
    records = [
        _record(world, "9600"),
        _record(
            world,
            "9601",
            OperationKind.REFUND,
            EvidenceClass.CONFIRMED_ADJUSTMENT,
            25_000,
            parent="9600",
            when=SALE_AT + timedelta(hours=1),
        ),
        _record(world, "9602", classification=EvidenceClass.MANUAL_DECLARATION, amount=9_000),
    ]
    stored, _ = _append(world.db, records)
    with Session(world.db.runtime) as session:
        ledger = client_ledger(session, world.a, world.a1)
    scope = LedgerScope(world.a, world.a1, ACCOUNT)
    click = ClickIdentifier("synthetic-fbclid-0001", SALE_AT - timedelta(hours=2), uuid4())
    journeys = {
        (scope, operation): SyntheticJourney("person-1", (), (click,))
        for operation in ("9600", "9602")
    }
    candidates = candidates_from_ledger(ledger.calculation, journeys)
    assert candidates == candidates_from_ledger(calculate(stored), journeys)
    # The declaration never becomes a candidate.
    assert [item.transaction_id for item in candidates] == ["9600"]
    assert candidates[0].sale.net_minor == 75_000
    assert candidates_from_feed(ledger.journal, journeys) == candidates_from_feed(
        ledger_feed(stored), journeys
    )
    transaction = ledger.calculation.transactions[0]
    conversion = sale_conversion(transaction, conversion_id="conversion-1", person_id="person-1")
    touch = Touchpoint(
        "touch-1",
        world.a,
        world.a1,
        "person-1",
        TouchClass.CAMPAIGN_INTERACTION,
        SALE_AT - timedelta(hours=3),
        Association.ASSIGNED,
        ConsentState.GRANTED,
        "meta",
        "111001",
        "311001",
    )
    version = ModelVersion("last-v1", AttributionModel.LAST_CLICK)
    run = attribute(conversion, [touch], version, sale=sale_state(ledger.calculation, conversion))
    expected = attribute(
        conversion, [touch], version, sale=sale_state(calculate(stored), conversion)
    )
    assert run == expected
    assert run.verified_net == Money(75_000, EGP)
    assert sum(item.amount.minor for item in run.allocations) == 75_000
