"""Specification 007-B persisted revenue journal on disposable PostgreSQL (D-075 J7-J9, J11).

JV13: the 007-A acceptance and R007 behaviors repeated through stored receipts, with the
stored movements and journal identical to calculate() and ledger_feed() for inputs without a
held refund, including a seeded randomized log. JV14: concurrent duplicate deliveries, equal
receipt instants, per-client positions across other clients' sequence gaps and an injected
failure at the publication boundary. JV15: a held refund keeps its receipt and takes effect at
a later receipt without rewriting history. JV16: interrupted, resumed and conflicting backfills.
JV17: the reconciliation queue and its audited, idempotent review. Synthetic values only.
"""

import random
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from report_support import append, evidence
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.attribution import ledger_feed
from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind, calculate
from app.ledger_backfill import backfill
from app.models import (
    AuditEvent,
    LedgerMovement,
    LedgerProjectionState,
    LedgerReceipt,
    LedgerReconciliationAction,
    LedgerTransaction,
)
from app.services import ledger_store
from app.services.ledger_store import LedgerUnavailable
from app.services.revenue import append_evidence, client_ledger, load_evidence, lock_revenue

pytestmark = pytest.mark.integration

EGP = Currency("EGP", 2)
USD = Currency("USD", 2)
DAY = datetime(2026, 11, 1, tzinfo=UTC)


def stored(w, client=None):
    with Session(w.db.runtime) as session:
        return load_evidence(session, w.a, client or w.a1)


def ledger(w, client=None):
    with Session(w.db.runtime) as session:
        return client_ledger(session, w.a, client or w.a1)


def rows(w, query):
    with Session(w.db.migration, expire_on_commit=False) as session:
        return list(session.scalars(query))


def record(
    w,
    operation,
    kind=OperationKind.SALE,
    minor=10_000,
    *,
    parent=None,
    when=DAY,
    currency=EGP,
    classification=None,
    delivery=None,
    actor=None,
    reason=None,
    source_reference=None,
):
    classes = {
        OperationKind.SALE: EvidenceClass.CONFIRMED_CAPTURE,
        OperationKind.REFUND: EvidenceClass.CONFIRMED_ADJUSTMENT,
        OperationKind.CHARGEBACK: EvidenceClass.CONFIRMED_ADJUSTMENT,
        OperationKind.CHARGEBACK_REVERSAL: EvidenceClass.CONFIRMED_ADJUSTMENT,
        OperationKind.CORRECTION: EvidenceClass.AUDITED_CORRECTION,
    }
    return Evidence(
        delivery or f"d:{operation}:{kind.value}:{minor}",
        w.a,
        w.a1,
        "acct",
        operation,
        kind,
        classification or classes[kind],
        Money(minor, currency),
        when,
        when,
        parent_operation_id=parent,
        actor=actor,
        reason=reason,
        source_reference=source_reference,
    )


def put(w, items):
    append(w, items, intake="csv_import")


def assert_matches_reference(w, client=None):
    """The persisted view equals the in-memory reference for a log without held refunds."""
    items = stored(w, client)
    current = ledger(w, client)
    assert current.held == ()
    reference = calculate(items)
    assert current.calculation == reference
    assert current.journal == ledger_feed(items)
    projected = {
        (row.source_account_id, row.operation_id): row.net
        for row in rows(
            w,
            select(LedgerTransaction).where(
                LedgerTransaction.client_id == (client or w.a1),
                LedgerTransaction.generation == current.generation,
            ),
        )
    }
    assert projected == {
        (t.scope.source_account_id, t.operation_id): t.totals.net for t in reference.transactions
    }
    return current


def test_acceptance_cases_through_stored_receipts(world):
    """007 AC1-AC5 and R007 behaviors with persisted receipts, movements and projections."""
    w = world
    put(
        w,
        [
            record(w, "S1", minor=100_000),
            record(w, "S1", minor=100_000),  # exact redelivery: no evidence, no receipt
            record(w, "R1", OperationKind.REFUND, 20_000, parent="S1"),
            record(w, "R-early", OperationKind.REFUND, 5_000, parent="S2"),  # before its sale
            record(w, "S2", minor=50_000, delivery="d:S2:other"),
            record(w, "S3", minor=30_000),
            record(w, "R3", OperationKind.REFUND, 30_000, parent="S3"),  # full refund
            record(w, "CB", OperationKind.CHARGEBACK, 10_000, parent="S2"),
            record(w, "CBR", OperationKind.CHARGEBACK_REVERSAL, 10_000, parent="CB"),
            record(w, "S-usd", minor=7_000, currency=USD),
            record(
                w,
                "X1",
                OperationKind.CORRECTION,
                -1_000,
                parent="S1",
                actor="ops",
                reason="fee",
                source_reference="ticket-1",
            ),
            record(w, "M1", classification=EvidenceClass.MANUAL_DECLARATION, minor=9_000),
            record(w, "S1", minor=99_999, delivery="d:S1:conflict"),  # conflicting evidence
            record(w, "R-too-big", OperationKind.REFUND, 999_999, parent="S2"),
        ],
    )
    current = assert_matches_reference(w)
    totals = current.calculation.totals(w.a, w.a1)
    assert totals["EGP"].net == 100_000 - 20_000 - 1_000 + 50_000 - 5_000 + 30_000 - 30_000
    assert totals["USD"].net == 7_000  # currencies are never added
    assert [item.operation_id for item in current.calculation.unverified] == ["M1"]
    receipts = rows(
        w,
        select(LedgerReceipt)
        .where(LedgerReceipt.client_id == w.a1)
        .order_by(LedgerReceipt.receipt_ordinal),
    )
    assert [r.receipt_ordinal for r in receipts] == list(range(1, 14))  # 14 deliveries, 1 duplicate
    assert {r.outcome for r in receipts} >= {"posted", "pending", "reconciliation", "unverified"}
    assert all(
        r.previous_digest == previous.receipt_digest
        for previous, r in zip(receipts, receipts[1:], strict=False)
    )
    state = rows(w, select(LedgerProjectionState))[0]
    assert (state.status, state.generation, state.receipt_ordinal) == ("ready", 1, 13)
    assert state.movement_sequence == len(current.calculation.movements)


def test_seeded_random_logs_match_the_reference(world):
    w = world
    generator = random.Random(20261123)
    items = []
    sales = []
    for index in range(60):
        choice = generator.random()
        if choice < 0.4 or not sales:
            operation = f"S{index}"
            sales.append(operation)
            items.append(
                record(
                    w,
                    operation,
                    minor=generator.randint(1_000, 90_000),
                    when=DAY + timedelta(minutes=generator.randint(0, 600)),
                )
            )
        elif choice < 0.75:
            items.append(
                record(
                    w,
                    f"R{index}",
                    OperationKind.REFUND,
                    generator.randint(500, 40_000),
                    parent=generator.choice(sales + ["missing"]),
                    when=DAY + timedelta(minutes=generator.randint(0, 900)),
                )
            )
        elif choice < 0.85:
            items.append(generator.choice(items))  # redelivery
        else:
            items.append(
                record(
                    w,
                    generator.choice(sales),
                    minor=generator.randint(1, 5),
                    delivery=f"d:conflict:{index}",
                )
            )
    put(w, items)
    assert_matches_reference(w)


def test_concurrent_duplicates_equal_instants_and_other_clients(world):
    """JV14: one receipt per stored row and contiguous per-client positions."""
    w = world
    item = record(w, "C1", minor=12_345)
    barrier = threading.Barrier(2)
    outcomes = []

    def deliver():
        barrier.wait()
        with Session(w.db.runtime) as session, session.begin():
            received = lock_revenue(session, w.a1)
            outcomes.append(
                append_evidence(session, replace(item, received_at=received), "paymob", uuid4())
            )

    threads = [threading.Thread(target=deliver) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["duplicate", "stored"]
    # Equal receipt instants (one CSV commit): positions follow the insertion sequence.
    with Session(w.db.runtime) as session, session.begin():
        received = lock_revenue(session, w.a1)
        for operation in ("E1", "E2", "E3"):
            append_evidence(
                session, replace(record(w, operation), received_at=received), "csv_import", uuid4()
            )
    # Interleave another client: global sequence gaps never look like missing local receipts.
    other = [replace(record(w, f"B{index}"), client_id=w.a2) for index in range(3)]
    for index, item_b in enumerate(other):
        put(w, [item_b, record(w, f"A{index}")])
    for client in (w.a1, w.a2):
        ordinals = rows(
            w,
            select(LedgerReceipt.receipt_ordinal)
            .where(LedgerReceipt.client_id == client)
            .order_by(LedgerReceipt.receipt_ordinal),
        )
        assert ordinals == list(range(1, len(ordinals) + 1))
    assert_matches_reference(w)
    assert_matches_reference(w, w.a2)


def test_failure_at_the_publication_boundary_loses_and_doubles_nothing(world, monkeypatch):
    w = world
    put(w, [record(w, "P1", minor=10_000)])
    original = ledger_store.write_transactions

    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic crash after the movements were written")

    monkeypatch.setattr(ledger_store, "write_transactions", failing)
    with pytest.raises(RuntimeError):
        put(w, [record(w, "P2", minor=5_000)])
    monkeypatch.setattr(ledger_store, "write_transactions", original)
    assert [item.operation_id for item in stored(w)] == ["P1"]
    assert len(rows(w, select(LedgerReceipt))) == 1
    put(w, [record(w, "P2", minor=5_000)])  # the retry
    current = assert_matches_reference(w)
    assert current.calculation.totals(w.a, w.a1)["EGP"].net == 15_000


def test_held_refund_keeps_its_position_and_posts_at_a_later_receipt(world):
    """JV15 and D-070: no earlier receipt or movement is rewritten when eligibility changes."""
    w = world
    refund = evidence(w, "777", OperationKind.REFUND, 4_000, when=DAY, parent="700", order="9001")
    append(w, [refund])
    append(w, [evidence(w, "700", minor=10_000, when=DAY, order="8000")])  # another order
    before = rows(
        w,
        select(LedgerReceipt)
        .where(LedgerReceipt.client_id == w.a1)
        .order_by(LedgerReceipt.receipt_ordinal),
    )
    assert [r.outcome for r in before] == ["pending", "posted"]
    held = ledger(w)
    assert [item.operation_id for item in held.held] == ["777"]
    assert held.calculation.totals(w.a, w.a1)["EGP"].net == 10_000
    # A settlement record of the sale carrying the refund's order proves the parent.
    settlement = replace(
        evidence(
            w,
            "700",
            minor=10_000,
            when=DAY,
            order="9001",
            classification=EvidenceClass.CONFIRMED_SETTLEMENT,
            delivery="d:settle",
        ),
    )
    append(w, [settlement])
    after = rows(
        w,
        select(LedgerReceipt)
        .where(LedgerReceipt.client_id == w.a1)
        .order_by(LedgerReceipt.receipt_ordinal),
    )
    assert [(r.receipt_ordinal, r.receipt_digest, r.outcome) for r in after[:2]] == [
        (r.receipt_ordinal, r.receipt_digest, r.outcome) for r in before
    ]
    moves = rows(
        w,
        select(LedgerMovement)
        .where(LedgerMovement.client_id == w.a1)
        .order_by(LedgerMovement.movement_sequence),
    )
    refund_moves = [m for m in moves if m.operation_id == "777"]
    assert [(m.direction, m.amount_minor, m.receipt_id) for m in refund_moves] == [
        ("posting", -4_000, after[2].id)
    ]
    current = ledger(w)
    assert current.held == () and current.calculation.totals(w.a, w.a1)["EGP"].net == 6_000
    # The historical filtered reference would have posted the refund at its own receipt.
    reference = calculate(stored(w))
    assert reference.movements[0].operation_id == "700"


def _drop_projection(w, client=None):
    with Session(w.db.migration) as session, session.begin():
        for model in (LedgerMovement, LedgerReceipt, LedgerTransaction, LedgerProjectionState):
            session.execute(delete(model).where(model.client_id == (client or w.a1)))


def test_backfill_interrupts_resumes_and_catches_up(world):
    """JV16: legacy evidence without a projection; staging is never visible."""
    w = world
    put(w, [record(w, f"L{index}", minor=1_000 + index) for index in range(7)])
    _drop_projection(w)
    with pytest.raises(LedgerUnavailable):
        ledger(w)
    assert backfill(w.db.migration, w.a, w.a1, batch_size=3, stop_after_batches=1) == "interrupted"
    with pytest.raises(LedgerUnavailable):
        ledger(w)
    state = rows(w, select(LedgerProjectionState))[0]
    assert (state.status, state.generation, state.staging_generation) == ("building", 0, 1)
    put(w, [record(w, "late", minor=50)])  # stored while building; not projected yet
    with pytest.raises(LedgerUnavailable):
        ledger(w)

    def concurrent_append():
        put(w, [record(w, "during", minor=60)])

    assert (
        backfill(w.db.migration, w.a, w.a1, batch_size=3, before_publish=concurrent_append)
        == "published"
    )
    current = assert_matches_reference(w)
    assert len(current.records) == 9
    put(w, [record(w, "after", minor=70)])  # incremental again
    assert_matches_reference(w)


def test_conflicting_backfill_exposes_no_staging_rows(world):
    w = world
    put(w, [record(w, f"K{index}") for index in range(5)])
    _drop_projection(w)
    staged = {}

    def operator_restarts_and_publishes():
        staged["first"] = rows(w, select(LedgerProjectionState))[0].staging_generation
        assert backfill(w.db.migration, w.a, w.a1, batch_size=2, restart=True) == "published"

    # The first run's swap fails: the published generation it captured has changed.
    result = backfill(
        w.db.migration, w.a, w.a1, batch_size=2, before_publish=operator_restarts_and_publishes
    )
    assert result == "conflict"
    state = rows(w, select(LedgerProjectionState))[0]
    assert state.status == "ready" and state.generation > staged["first"]
    assert state.staging_generation is None
    generations = set(
        rows(w, select(LedgerReceipt.generation).where(LedgerReceipt.client_id == w.a1))
    )
    assert generations == {state.generation}
    assert_matches_reference(w)


def test_reconciliation_queue_and_review(authenticated_world, api):
    """JV17: scoped, versioned, idempotent and audited; never changes evidence or amounts."""
    w = authenticated_world
    put(
        w,
        [
            record(w, "Q1", minor=10_000),
            record(w, "Q1", minor=10_001, delivery="d:Q1:conflict"),
            record(w, "Q-pending", OperationKind.REFUND, 100, parent="nowhere"),
            record(w, "Q-manual", classification=EvidenceClass.MANUAL_DECLARATION, minor=500),
        ],
    )
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}/clients/{w.a1}/revenue"
    queue = owner.get(base + "/reconciliation")
    assert queue.status_code == 200, queue.text
    body = queue.json()
    assert body["unresolved_count"] == 2
    kinds = {item["kind"]: item for item in body["issues"]}
    assert set(kinds) == {"reconciliation", "pending"}
    issue = kinds["reconciliation"]["issue_id"]
    before = owner.get(base).json()
    operation = str(uuid4())
    review = {
        "operation_id": operation,
        "expected_financial_revision": body["financial_revision"],
        "action": "acknowledge",
        "reason_code": "provider_contacted",
    }
    first = owner.post(f"{base}/reconciliation/{issue}/actions", json=review)
    assert first.status_code == 201, first.text
    again = owner.post(f"{base}/reconciliation/{issue}/actions", json=review)
    assert again.status_code == 200 and again.json() == first.json()
    changed = owner.post(
        f"{base}/reconciliation/{issue}/actions", json={**review, "action": "reopen"}
    )
    assert (changed.status_code, changed.json()) == (409, {"error": "operation_conflict"})
    stale = owner.post(
        f"{base}/reconciliation/{issue}/actions",
        json={**review, "operation_id": str(uuid4()), "expected_financial_revision": 0},
    )
    assert (stale.status_code, stale.json()) == (409, {"error": "financial_revision_changed"})
    foreign = owner.post(
        f"/agencies/{w.a}/clients/{w.a2}/revenue/reconciliation/{issue}/actions",
        json={**review, "operation_id": str(uuid4()), "expected_financial_revision": 0},
    )
    assert foreign.status_code in {404, 409}
    for name in ("analyst", "viewer"):
        denied = w.signed_in(name).post(
            f"{base}/reconciliation/{issue}/actions", json={**review, "operation_id": str(uuid4())}
        )
        assert denied.status_code == 403
    after = owner.get(base + "/reconciliation").json()
    assert after["unresolved_count"] == 2
    reviewed = {item["issue_id"]: item for item in after["issues"]}[issue]["review"]
    assert reviewed["action"] == "acknowledge" and reviewed["current"] is True
    assert owner.get(base).json() == before  # amounts, declarations and evidence unchanged
    assert [item["operation_id"] for item in before["declared"]["items"]] == ["Q-manual"]
    audits = rows(
        w, select(AuditEvent.action).where(AuditEvent.action == "revenue.reconciliation_reviewed")
    )
    assert audits == ["revenue.reconciliation_reviewed"]
    assert len(rows(w, select(LedgerReconciliationAction))) == 1
    # Movements: a finance reader pages the stored journal bound to its generation.
    put(w, [record(w, "Q2", minor=2_000)])
    page = owner.get(base + "/movements?limit=1").json()
    assert page["generation"] == 1 and len(page["movements"]) == 1
    nxt = owner.get(base + f"/movements?after={page['next_after']}&generation=1").json()
    assert nxt["movements"][0]["sequence"] == page["movements"][0]["sequence"] + 1
    wrong = owner.get(base + "/movements?generation=2")
    assert (wrong.status_code, wrong.json()) == (409, {"error": "ledger_generation_changed"})
    assert w.signed_in("analyst").get(base + "/movements").status_code == 403


def test_measured_writes_backfill_and_reads(world):
    """JV24 measurements at the current bounds (no SLO): one write, a backfill and a read."""
    w = world
    timings = {}
    for size in (50, 100, 200):
        client = w.a1 if size == 50 else (w.a2 if size == 100 else w.b1)
        agency = w.b if client == w.b1 else w.a
        items = [
            replace(record(w, f"T{index}", minor=100 + index), client_id=client, agency_id=agency)
            for index in range(size - 1)
        ]
        put(w, items)
        started = time.perf_counter()
        put(w, [replace(record(w, "last", minor=1), client_id=client, agency_id=agency)])
        timings[f"write_receipt_{size}"] = time.perf_counter() - started
        with Session(w.db.runtime) as session:
            started = time.perf_counter()
            client_ledger(session, agency, client)
            timings[f"read_{size}"] = time.perf_counter() - started
        with Session(w.db.migration) as session, session.begin():
            for model in (LedgerMovement, LedgerReceipt, LedgerTransaction, LedgerProjectionState):
                session.execute(delete(model).where(model.client_id == client))
        started = time.perf_counter()
        assert backfill(w.db.migration, agency, client, batch_size=200) == "published"
        timings[f"backfill_{size}"] = time.perf_counter() - started
    print("LEDGER_TIMINGS", {key: round(value, 3) for key, value in timings.items()})
    assert all(value > 0 for value in timings.values())


def _csv(*rows: str) -> bytes:
    header = (
        "operation_id,kind,amount,currency,effective_at,parent_operation_id,source_reference,reason"
    )
    return ((chr(13) + chr(10)).join((header, *rows)) + chr(13) + chr(10)).encode()


def test_large_import_keeps_intake_behavior_and_fails_closed(world):
    """J11/A3: above 200 rows a CSV commit stores evidence without inline receipts; reads fail
    closed until the operator backfill catches up, and later single intake never blocks."""
    from app.services.declarations import DeclarationService, file_digest

    w = world
    put(w, [record(w, "before", minor=100)])
    body = _csv(
        *(f"BULK-{index},sale,1.00,EGP,2026-11-01T00:00:00Z,,,declared" for index in range(250))
    )
    started = time.perf_counter()
    with Session(w.db.runtime) as session, session.begin():
        result = DeclarationService(session, w.users.owner_a).commit(
            w.a, w.a1, file_digest(body), body
        )
        stored_rows = result.record.stored_rows
    elapsed = time.perf_counter() - started
    print("CSV_250_COMMIT", round(elapsed, 2))
    assert stored_rows == 250
    with pytest.raises(LedgerUnavailable):
        ledger(w)
    put(w, [record(w, "single", minor=5)])  # intake still works; the projection stays behind
    with pytest.raises(LedgerUnavailable):
        ledger(w)
    assert backfill(w.db.migration, w.a, w.a1, batch_size=100) == "published"
    current = assert_matches_reference(w)
    assert len(current.calculation.unverified) == 250
    put(w, [record(w, "after", minor=7)])
    assert_matches_reference(w)
