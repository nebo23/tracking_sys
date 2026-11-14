"""Revenue ledger calculation contract, acceptance cases AC1-AC5 (specification 007-A, D-043).

All agencies, clients, source accounts, operations, currencies, rates and amounts are synthetic.
Effective times are fixed offsets from T0. deliver() reassigns receipt times by position, so a
permutation of its input changes the real arrival order, not only the order of the list.
"""

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations
from uuid import UUID

import pytest

from app.ledger import (
    AdjustmentStatus,
    ConversionStatus,
    Currency,
    Disposition,
    Evidence,
    EvidenceClass,
    FxRateSnapshot,
    LedgerInputError,
    LedgerScope,
    Money,
    OperationKind,
    PendingReason,
    ReconciliationReason,
    Stream,
    calculate,
    convert,
)

AGENCY = UUID("00000000-0000-4000-8000-00000000a001")
AGENCY_2 = UUID("00000000-0000-4000-8000-00000000a002")
CLIENT = UUID("00000000-0000-4000-8000-00000000c001")
CLIENT_2 = UUID("00000000-0000-4000-8000-00000000c002")
CLIENT_3 = UUID("00000000-0000-4000-8000-00000000c003")
ACCOUNT = "acct-synthetic-1"
ACCOUNT_2 = "acct-synthetic-2"
SCOPE = LedgerScope(AGENCY, CLIENT, ACCOUNT)
AAA = Currency("AAA", 2)
BBB = Currency("BBB", 2)
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
AS_OF = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)

POSTED = Disposition.POSTED
DUPLICATE = Disposition.DUPLICATE
SALE = OperationKind.SALE
REFUND = OperationKind.REFUND
_DEFAULT_CLASS = {
    OperationKind.SALE: EvidenceClass.CONFIRMED_CAPTURE,
    OperationKind.CORRECTION: EvidenceClass.AUDITED_CORRECTION,
}


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def record(
    operation_id: str,
    amount: str = "1000.00",
    kind: OperationKind = SALE,
    *,
    delivery: str | None = None,
    parent: str | None = None,
    classification: EvidenceClass | None = None,
    effective: int = 0,
    agency: UUID = AGENCY,
    client: UUID | None = CLIENT,
    account: str = ACCOUNT,
    currency: Currency = AAA,
    **extra,
) -> Evidence:
    return Evidence(
        delivery_id=delivery or f"dlv-{operation_id}",
        agency_id=agency,
        client_id=client,
        source_account_id=account,
        operation_id=operation_id,
        kind=kind,
        classification=classification
        or _DEFAULT_CLASS.get(kind, EvidenceClass.CONFIRMED_ADJUSTMENT),
        amount=Money.parse(amount, currency),
        effective_at=at(effective),
        received_at=at(effective),
        parent_operation_id=parent,
        **extra,
    )


def sale(operation_id: str = "sale-1", amount: str = "1000.00", **extra) -> Evidence:
    return record(operation_id, amount, SALE, **extra)


def refund(operation_id: str, amount: str, parent: str = "sale-1", **extra) -> Evidence:
    return record(operation_id, amount, REFUND, parent=parent, **extra)


def chargeback(operation_id: str, amount: str, parent: str = "sale-1", **extra) -> Evidence:
    return record(operation_id, amount, OperationKind.CHARGEBACK, parent=parent, **extra)


def reversal(operation_id: str, amount: str, parent: str = "chargeback-1", **extra) -> Evidence:
    return record(operation_id, amount, OperationKind.CHARGEBACK_REVERSAL, parent=parent, **extra)


def correction(operation_id: str, amount: str, parent: str = "sale-1", **extra) -> Evidence:
    return record(operation_id, amount, OperationKind.CORRECTION, parent=parent, **extra)


def audited(operation_id: str, amount: str, **extra) -> Evidence:
    return correction(
        operation_id,
        amount,
        actor="reviewer-synthetic-1",
        reason="Synthetic provider statement for the reconciled capture",
        source_reference="statement-synthetic-7",
        **extra,
    )


def deliver(sequence) -> list[Evidence]:
    """Receive the records in this order, one minute apart, whatever their effective times."""
    return [
        replace(item, received_at=at(10_000 + position)) for position, item in enumerate(sequence)
    ]


def net(result, agency: UUID = AGENCY, client: UUID = CLIENT, code: str = "AAA") -> int:
    return result.totals(agency, client)[code].net


def postings(result) -> list[tuple]:
    return [
        (
            entry.scope,
            entry.transaction_id,
            entry.operation_id,
            entry.kind,
            entry.amount,
            entry.effective_at,
            tuple(evidence.delivery_id for evidence in entry.evidence),
        )
        for entry in result.entries
    ]


def states(result) -> list[tuple]:
    return [(a.scope, a.operation_id, a.status, a.status_reason) for a in result.adjustments]


def review(result) -> list[tuple]:
    return [
        (item.scope, item.operation_id, item.reason, tuple(e.delivery_id for e in item.evidence))
        for item in result.reconciliation
    ]


def view(result) -> tuple:
    return postings(result), states(result), review(result), result.totals(AGENCY, CLIENT)


def dispositions(result) -> list[tuple]:
    return [(o.evidence.delivery_id, o.disposition, o.reason) for o in result.outcomes]


# The owner's worked example: 1,000 sale, 200 refund, duplicated and early notifications.


def test_sale_of_1000_and_refund_of_200_net_800_despite_duplicates_and_early_refund():
    capture = sale(amount="1000.00")
    refund_200 = refund("refund-1", "200.00", effective=10)
    renotified = replace(refund_200, delivery_id="dlv-refund-1-retry")

    early = calculate(deliver([refund_200]))
    assert early.transactions == ()
    assert early.totals(AGENCY, CLIENT) == {}
    assert states(early) == [(SCOPE, "refund-1", AdjustmentStatus.PENDING, "parent_missing")]

    orders = list(permutations([capture, refund_200, refund_200, renotified]))
    assert len(orders) == 24
    for order in orders:
        result = calculate(deliver(order))
        assert [entry.amount.minor for entry in result.entries] == [100_000, -20_000]
        assert net(result) == 80_000
        assert str(result.transactions[0].net) == "800.00 AAA"
        assert result.pending == () and result.reconciliation == ()
        refund_entry = result.entries[1]
        assert [e.delivery_id for e in refund_entry.evidence] == [
            "dlv-refund-1",
            "dlv-refund-1-retry",
        ]


# AC1: deduplication of captures, settlements and conflicting claims.


def test_ac1_capture_replays_and_settlement_post_one_sale():
    capture = sale(delivery="dlv-cap-1")
    renotified = replace(capture, delivery_id="dlv-cap-2")
    settlement = replace(
        capture,
        delivery_id="dlv-settle-1",
        classification=EvidenceClass.CONFIRMED_SETTLEMENT,
        effective_at=at(60 * 24),
    )

    result = calculate(deliver([capture, capture, renotified, settlement]))

    [entry] = result.entries
    assert (entry.kind, entry.amount, entry.effective_at) == (SALE, Money(100_000, AAA), at(0))
    assert [e.delivery_id for e in entry.evidence] == ["dlv-cap-1", "dlv-cap-2", "dlv-settle-1"]
    assert net(result) == 100_000
    assert dispositions(result) == [
        ("dlv-cap-1", POSTED, "posted"),
        ("dlv-cap-1", DUPLICATE, "same_delivery"),
        ("dlv-cap-2", DUPLICATE, "same_operation"),
        ("dlv-settle-1", DUPLICATE, "same_operation"),
    ]


def test_ac1_settlement_before_capture_converges_on_one_sale():
    capture = sale(delivery="dlv-cap-1")
    settlement = replace(
        capture,
        delivery_id="dlv-settle-1",
        classification=EvidenceClass.CONFIRMED_SETTLEMENT,
        effective_at=at(60 * 24),
    )
    expected = postings(calculate([capture, settlement]))
    for order in permutations([capture, capture, settlement, settlement]):
        result = calculate(deliver(order))
        assert postings(result) == expected
        assert net(result) == 100_000


def test_ac1_conflicting_amount_is_reconciled_and_posted_balance_preserved():
    capture = sale(delivery="dlv-cap-1")
    conflicting = replace(capture, delivery_id="dlv-cap-9", amount=Money.parse("1200.00", AAA))
    before = calculate(deliver([capture]))

    after = calculate(deliver([capture, conflicting, conflicting]))

    assert after.entries == before.entries
    assert net(after) == 100_000
    [item] = after.reconciliation
    assert (item.scope, item.operation_id, item.reason) == (
        SCOPE,
        "sale-1",
        ReconciliationReason.CONFLICTING_EVIDENCE,
    )
    assert [e.delivery_id for e in item.evidence] == ["dlv-cap-9"]
    assert item.retained.delivery_id == "dlv-cap-1"
    assert dispositions(after) == [
        ("dlv-cap-1", POSTED, "posted"),
        ("dlv-cap-9", Disposition.RECONCILIATION, "conflicting_evidence"),
        ("dlv-cap-9", DUPLICATE, "same_delivery"),
    ]


def test_ac1_settlement_with_other_amount_is_conflicting_evidence():
    capture = sale(delivery="dlv-cap-1")
    settlement = replace(
        capture,
        delivery_id="dlv-settle-1",
        classification=EvidenceClass.CONFIRMED_SETTLEMENT,
        amount=Money.parse("990.00", AAA),
    )
    result = calculate(deliver([capture, settlement]))
    assert net(result) == 100_000
    assert review(result) == [
        (SCOPE, "sale-1", ReconciliationReason.CONFLICTING_EVIDENCE, ("dlv-settle-1",))
    ]


def test_ac1_reused_delivery_id_with_other_content_is_reconciled():
    capture = sale(delivery="dlv-cap-1")
    altered = replace(capture, amount=Money.parse("1.00", AAA))
    result = calculate(deliver([capture, altered]))
    assert net(result) == 100_000
    [item] = result.reconciliation
    assert item.reason is ReconciliationReason.DELIVERY_ID_REUSED
    assert item.retained == result.entries[0].evidence[0]


# AC2: partial and full refund.


def test_ac2_partial_then_full_refund_balances():
    sequence = [
        sale(amount="1000.00"),
        refund("refund-1", "200.00", effective=10),
        refund("refund-2", "800.00", effective=20),
    ]
    balances = [net(calculate(deliver(sequence[:count]))) for count in (1, 2, 3)]
    assert balances == [100_000, 80_000, 0]

    result = calculate(deliver(sequence))
    totals = result.totals(AGENCY, CLIENT)["AAA"]
    assert (totals.captured, totals.refunded, totals.net) == (100_000, 100_000, 0)
    assert [
        (e.operation_id, e.amount.minor, e.parent_operation_id, [x.delivery_id for x in e.evidence])
        for e in result.entries
        if e.kind is REFUND
    ] == [
        ("refund-1", -20_000, "sale-1", ["dlv-refund-1"]),
        ("refund-2", -80_000, "sale-1", ["dlv-refund-2"]),
    ]


def test_ac2_replayed_refunds_post_once():
    first = refund("refund-1", "200.00", effective=10)
    second = refund("refund-2", "800.00", effective=20)
    sequence = [
        sale(),
        first,
        first,
        replace(first, delivery_id="dlv-refund-1-b"),
        second,
        second,
        replace(second, delivery_id="dlv-refund-2-b"),
    ]
    balances = [net(calculate(deliver(sequence[:count]))) for count in range(1, 8)]
    assert balances == [100_000, 80_000, 80_000, 80_000, 0, 0, 0]

    result = calculate(deliver(sequence))
    assert [e.amount.minor for e in result.entries] == [100_000, -20_000, -80_000]
    assert [o.disposition for o in result.outcomes].count(DUPLICATE) == 4


def test_ac2_refund_beyond_remaining_balance_goes_to_reconciliation():
    extra = refund("refund-3", "0.01", effective=30)
    result = calculate(
        [
            sale(),
            refund("refund-1", "200.00", effective=10),
            refund("refund-2", "800.00", effective=20),
            extra,
        ]
    )
    assert net(result) == 0
    assert states(result)[-1] == (
        SCOPE,
        "refund-3",
        AdjustmentStatus.RECONCILIATION,
        "exceeds_outstanding",
    )
    assert review(result) == [
        (SCOPE, "refund-3", ReconciliationReason.EXCEEDS_OUTSTANDING, ("dlv-refund-3",))
    ]


# AC3: out-of-order inputs, reversal limits and audited corrections.


def test_ac3_refund_before_capture_is_pending_until_the_capture_arrives():
    capture = sale()
    refund_200 = refund("refund-1", "200.00", effective=10)

    early = calculate(deliver([refund_200, refund_200]))
    [pending] = early.pending
    assert (pending.status_reason, pending.transaction_id) == (PendingReason.PARENT_MISSING, None)
    assert dispositions(early) == [
        ("dlv-refund-1", Disposition.PENDING, "parent_missing"),
        ("dlv-refund-1", DUPLICATE, "same_delivery"),
    ]

    expected = view(calculate([capture, refund_200]))
    retry = replace(refund_200, delivery_id="dlv-refund-1-retry")
    for order in permutations([capture, refund_200, refund_200]):
        assert view(calculate(deliver(order))) == expected
    for order in permutations([capture, refund_200, retry]):
        assert net(calculate(deliver(order))) == 80_000


def test_ac3_chargeback_reversal_before_its_debit():
    capture = sale()
    debit = chargeback("chargeback-1", "300.00", effective=10)
    restore = reversal("reversal-1", "300.00", effective=20)

    waiting = calculate(deliver([capture, restore]))
    assert net(waiting) == 100_000
    assert states(waiting) == [(SCOPE, "reversal-1", AdjustmentStatus.PENDING, "parent_missing")]

    orphaned = calculate(deliver([restore, debit]))
    assert states(orphaned) == [
        (SCOPE, "chargeback-1", AdjustmentStatus.PENDING, "parent_missing"),
        (SCOPE, "reversal-1", AdjustmentStatus.PENDING, "parent_unresolved"),
    ]
    assert net(calculate(deliver([capture, debit]))) == 70_000

    expected = view(calculate([capture, debit, restore]))
    for order in permutations([capture, debit, restore, restore]):
        assert view(calculate(deliver(order))) == expected
    totals = calculate([capture, debit, restore]).totals(AGENCY, CLIENT)["AAA"]
    assert (totals.captured, totals.charged_back, totals.reversed, totals.net) == (
        100_000,
        30_000,
        30_000,
        100_000,
    )


def test_ac3_reversal_restores_only_the_outstanding_debit():
    capture = sale()
    debit = chargeback("chargeback-1", "300.00", effective=10)
    partial = reversal("reversal-1", "200.00", effective=20)
    excess = reversal("reversal-2", "200.00", effective=30)
    remainder = reversal("reversal-3", "100.00", effective=40)

    expected = view(calculate([capture, debit, partial, excess]))
    for order in permutations([capture, debit, partial, excess]):
        assert view(calculate(deliver(order))) == expected
    result = calculate([capture, debit, partial, excess])
    assert net(result) == 90_000
    assert states(result)[-1] == (
        SCOPE,
        "reversal-2",
        AdjustmentStatus.RECONCILIATION,
        "reversal_exceeds_debit",
    )

    assert net(calculate([capture, debit, partial, remainder])) == 100_000
    too_much = reversal("reversal-4", "300.01", effective=20)
    assert review(calculate([capture, debit, too_much])) == [
        (SCOPE, "reversal-4", ReconciliationReason.REVERSAL_EXCEEDS_DEBIT, ("dlv-reversal-4",))
    ]


def test_ac3_canonical_order_decides_which_refund_exceeds_the_balance():
    capture = sale()
    earlier = refund("refund-a", "600.00", effective=10)
    later = refund("refund-b", "600.00", effective=20)
    for order in permutations([capture, earlier, later]):
        result = calculate(deliver(order))
        assert states(result) == [
            (SCOPE, "refund-a", AdjustmentStatus.POSTED, None),
            (SCOPE, "refund-b", AdjustmentStatus.RECONCILIATION, "exceeds_outstanding"),
        ]
        assert net(result) == 40_000


def test_ac3_audited_correction_adds_a_posting_and_preserves_the_original():
    capture = sale(delivery="dlv-cap-1")
    conflicting = replace(capture, delivery_id="dlv-cap-9", amount=Money.parse("1200.00", AAA))
    fix = audited("correction-1", "200.00", effective=60)

    before = calculate(deliver([capture, conflicting]))
    after = calculate(deliver([capture, conflicting, fix, fix]))

    assert after.transactions[0].sale == before.transactions[0].sale
    assert [(e.kind, e.amount.minor) for e in after.entries] == [
        (SALE, 100_000),
        (OperationKind.CORRECTION, 20_000),
    ]
    totals = after.totals(AGENCY, CLIENT)["AAA"]
    assert (totals.captured, totals.corrected, totals.net) == (100_000, 20_000, 120_000)
    [adjustment] = after.adjustments
    assert (
        adjustment.status,
        adjustment.actor,
        adjustment.reason,
        adjustment.source_reference,
        adjustment.parent_operation_id,
    ) == (
        AdjustmentStatus.POSTED,
        "reviewer-synthetic-1",
        "Synthetic provider statement for the reconciled capture",
        "statement-synthetic-7",
        "sale-1",
    )
    assert review(after) == review(before)


def test_ac3_correction_cannot_take_the_transaction_below_zero():
    capture = sale()
    assert net(calculate([capture, audited("correction-1", "-50.00", effective=10)])) == 95_000
    result = calculate([capture, audited("correction-2", "-1000.01", effective=10)])
    assert net(result) == 100_000
    assert states(result) == [
        (SCOPE, "correction-2", AdjustmentStatus.RECONCILIATION, "correction_below_zero")
    ]


def test_ac3_correction_requires_actor_reason_and_source_reference():
    complete = {
        "actor": "reviewer-synthetic-1",
        "reason": "Synthetic reason",
        "source_reference": "statement-synthetic-7",
    }
    for missing in complete:
        fields = {name: value for name, value in complete.items() if name != missing}
        with pytest.raises(LedgerInputError) as raised:
            correction("correction-1", "1.00", **fields)
        assert raised.value.code == "incomplete_correction"


def test_ac3_mixed_linked_operations_converge_under_shuffled_arrival():
    capture = sale(delivery="dlv-cap-1")
    records = [
        capture,
        replace(
            capture,
            delivery_id="dlv-settle-1",
            classification=EvidenceClass.CONFIRMED_SETTLEMENT,
            effective_at=at(60 * 24),
        ),
        refund("refund-1", "200.00", effective=10),
        chargeback("chargeback-1", "300.00", effective=20),
        reversal("reversal-1", "100.00", effective=30),
        reversal("reversal-2", "250.00", effective=40),  # only 200.00 of the debit remains
        refund("refund-2", "600.00", effective=50),  # exactly the remaining balance
        audited("correction-1", "25.00", parent="refund-2", effective=60),
        sale("sale-2", "40.00", currency=BBB),
        refund("refund-3", "40.00", parent="sale-2", currency=BBB, effective=5),
    ]
    records += [records[2], replace(records[3], delivery_id="dlv-chargeback-1-b")]
    expected = view(calculate(records))
    shuffler = random.Random(20261114)
    for _ in range(200):
        order = records[:]
        shuffler.shuffle(order)
        assert view(calculate(deliver(order))) == expected

    result = calculate(records)
    assert {code: totals.net for code, totals in result.totals(AGENCY, CLIENT).items()} == {
        "AAA": 2_500,
        "BBB": 0,
    }
    assert review(result) == [
        (SCOPE, "reversal-2", ReconciliationReason.REVERSAL_EXCEEDS_DEBIT, ("dlv-reversal-2",))
    ]


def test_ac3_manual_adjustments_and_invalid_parents_do_not_change_verified_totals():
    capture = sale()
    declared = refund(
        "refund-1", "200.00", classification=EvidenceClass.MANUAL_DECLARATION, effective=10
    )
    wrong_parent = reversal("reversal-1", "100.00", parent="sale-1", effective=20)
    result = calculate([capture, declared, wrong_parent])
    assert net(result) == 100_000
    assert result.unverified == (declared,)
    assert states(result) == [
        (SCOPE, "reversal-1", AdjustmentStatus.RECONCILIATION, "invalid_parent")
    ]


# AC4: reproducible conversion; original-currency totals stay separate.


def _ledger_nets():
    result = calculate([sale("sale-a", "10.00"), sale("sale-b", "20.00", currency=BBB)])
    totals = result.totals(AGENCY, CLIENT)
    assert {code: item.net for code, item in totals.items()} == {"AAA": 1_000, "BBB": 2_000}
    return [item.net_amount for item in totals.values()]


def _snapshot(rate: str = "2", age: timedelta = timedelta(hours=1)) -> FxRateSnapshot:
    return FxRateSnapshot(
        "fx-synthetic-1", AAA, BBB, Decimal(rate), AS_OF - age, "synthetic-fixture"
    )


def test_ac4_converted_total_is_reproducible_from_the_same_snapshot():
    nets = _ledger_nets()
    snapshot = _snapshot()

    first = convert(nets, BBB, [snapshot], as_of=AS_OF, max_age=DAY)
    again = convert(nets, BBB, [snapshot], as_of=AS_OF, max_age=DAY)

    assert first == again
    assert first.amount == Money(4_000, BBB)
    assert str(first.amount) == "40.00 BBB"
    assert first.originals == (Money(1_000, AAA), Money(2_000, BBB))
    assert [(c.status, c.snapshot, c.exact_minor) for c in first.components] == [
        (ConversionStatus.CONVERTED, snapshot, Decimal(2_000)),
        (ConversionStatus.IDENTITY, None, Decimal(2_000)),
    ]
    assert (
        snapshot.pair,
        snapshot.rate,
        snapshot.direction,
        snapshot.effective_at,
        snapshot.source,
        snapshot.rounding,
        first.rounding,
    ) == (
        "AAA/BBB",
        Decimal("2"),
        "quote_per_base",
        AS_OF - timedelta(hours=1),
        "synthetic-fixture",
        "half_even",
        "half_even",
    )


def test_ac4_missing_or_stale_snapshot_makes_the_combined_total_unavailable():
    nets = _ledger_nets()

    missing = convert(nets, BBB, [], as_of=AS_OF, max_age=DAY)
    assert (missing.amount, missing.available) == (None, False)
    assert [c.status for c in missing.components] == [
        ConversionStatus.MISSING,
        ConversionStatus.IDENTITY,
    ]
    assert missing.originals == (Money(1_000, AAA), Money(2_000, BBB))

    old = _snapshot(age=timedelta(days=2))
    stale = convert(nets, BBB, [old], as_of=AS_OF, max_age=DAY)
    assert stale.amount is None
    assert (stale.components[0].status, stale.components[0].snapshot) == (
        ConversionStatus.STALE,
        old,
    )
    assert stale.originals == missing.originals


def test_ac4_rounds_once_half_even_to_the_target_currency():
    conversion = convert(
        [Money.parse("0.03", AAA)], BBB, [_snapshot("1.5")], as_of=AS_OF, max_age=DAY
    )
    assert conversion.components[0].exact_minor == Decimal("4.5")
    assert conversion.amount == Money(4, BBB)
    assert str(conversion.amount) == "0.04 BBB"


# AC5: tenant isolation and exclusion of non-client revenue.


def test_ac5_operation_and_delivery_ids_are_isolated_by_agency_client_and_account():
    records = [
        sale("op-1", "1000.00", delivery="dlv-1"),
        refund("rf-1", "200.00", parent="op-1", delivery="dlv-2", effective=10),
        sale("op-1", "500.00", client=CLIENT_2, delivery="dlv-1"),
        refund("rf-1", "100.00", parent="op-1", client=CLIENT_2, delivery="dlv-2", effective=10),
        sale("op-1", "300.00", agency=AGENCY_2, client=CLIENT_3, delivery="dlv-1"),
        sale("op-1", "50.00", account=ACCOUNT_2, delivery="dlv-1"),
        refund(
            "rf-9",
            "10.00",
            parent="op-1",
            client=CLIENT_2,
            account=ACCOUNT_2,
            delivery="dlv-3",
            effective=10,
        ),
    ]
    result = calculate(records)

    assert len(result.transactions) == 4
    assert result.reconciliation == ()
    assert DUPLICATE not in {outcome.disposition for outcome in result.outcomes}
    client_one = result.totals(AGENCY, CLIENT)["AAA"]
    assert (client_one.captured, client_one.refunded, client_one.net) == (105_000, 20_000, 85_000)
    assert result.totals(AGENCY, CLIENT, ACCOUNT)["AAA"].net == 80_000
    assert result.totals(AGENCY, CLIENT, ACCOUNT_2)["AAA"].net == 5_000
    assert net(result, client=CLIENT_2) == 40_000
    assert net(result, agency=AGENCY_2, client=CLIENT_3) == 30_000
    assert result.totals(AGENCY_2, CLIENT) == {}
    assert result.totals(AGENCY, CLIENT_3) == {}
    assert states(result) == [
        (SCOPE, "rf-1", AdjustmentStatus.POSTED, None),
        (LedgerScope(AGENCY, CLIENT_2, ACCOUNT), "rf-1", AdjustmentStatus.POSTED, None),
        (
            LedgerScope(AGENCY, CLIENT_2, ACCOUNT_2),
            "rf-9",
            AdjustmentStatus.PENDING,
            "parent_missing",
        ),
    ]
    second = next(t for t in result.transactions if t.scope.client_id == CLIENT_2)
    assert [e.amount.minor for e in second.entries] == [50_000, -10_000]


def test_ac5_subscription_signal_and_declaration_add_no_verified_sales():
    subscription = record(
        "subscription-2026-11",
        "99.00",
        client=None,
        stream=Stream.AGENCY_SUBSCRIPTION,
        delivery="dlv-sub-1",
    )
    misrouted = record("op-1", "99.00", stream=Stream.AGENCY_SUBSCRIPTION, delivery="dlv-sub-2")
    signal = record(
        "order-77", "900.00", classification=EvidenceClass.PURCHASE_SIGNAL, delivery="dlv-sig-1"
    )
    declaration = record(
        "manual-1",
        "400.00",
        classification=EvidenceClass.MANUAL_DECLARATION,
        actor="member-synthetic-1",
        delivery="dlv-man-1",
    )
    refund_of_signal = refund("refund-77", "100.00", parent="order-77", effective=10)

    unverified_only = calculate([subscription, misrouted, signal, declaration, refund_of_signal])
    assert unverified_only.totals(AGENCY, CLIENT) == {}
    assert unverified_only.transactions == ()

    result = calculate(
        [sale("op-1"), subscription, misrouted, signal, declaration, refund_of_signal]
    )
    totals = result.totals(AGENCY, CLIENT)["AAA"]
    assert (totals.captured, totals.net) == (100_000, 100_000)
    assert result.excluded == (subscription, misrouted)
    assert set(result.unverified) == {signal, declaration}
    assert result.reconciliation == ()
    assert states(result) == [(SCOPE, "refund-77", AdjustmentStatus.PENDING, "parent_missing")]
    reasons = {o.evidence.delivery_id: (o.disposition, o.reason) for o in result.outcomes}
    assert reasons["dlv-sub-1"] == (Disposition.EXCLUDED, "agency_subscription")
    assert reasons["dlv-sub-2"] == (Disposition.EXCLUDED, "agency_subscription")
    assert reasons["dlv-sig-1"] == (Disposition.UNVERIFIED, "purchase_signal")
    assert reasons["dlv-man-1"] == (Disposition.UNVERIFIED, "manual_declaration")


def test_ac5_currencies_of_one_client_stay_separate():
    result = calculate(
        [
            sale("op-1", "1000.00"),
            sale("op-2", "70.00", currency=BBB),
            refund("rf-1", "200.00", parent="op-1", effective=10),
            refund("rf-2", "5.00", parent="op-1", currency=BBB, effective=20),
        ]
    )
    totals = result.totals(AGENCY, CLIENT)
    assert list(totals) == ["AAA", "BBB"]
    assert (totals["AAA"].net, totals["BBB"].net) == (80_000, 7_000)
    assert states(result)[-1] == (
        SCOPE,
        "rf-2",
        AdjustmentStatus.RECONCILIATION,
        "currency_mismatch",
    )
    with pytest.raises(LedgerInputError) as raised:
        totals["AAA"] + totals["BBB"]
    assert raised.value.code == "currency_mismatch"


# Contract validation.


def test_sale_with_unknown_purchaser_posts():
    """The contract carries no person reference; verified revenue needs no known purchaser."""
    assert net(calculate([sale()])) == 100_000


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"amount": Money(0, AAA)}, "invalid_amount"),
        ({"amount": Money(-1, AAA)}, "invalid_amount"),
        ({"amount": 1000}, "invalid_amount"),
        ({"effective_at": datetime(2026, 11, 1)}, "invalid_effective_at"),
        ({"received_at": datetime(2026, 11, 1)}, "invalid_received_at"),
        ({"parent_operation_id": "sale-0"}, "invalid_parent"),
        ({"classification": EvidenceClass.CONFIRMED_ADJUSTMENT}, "invalid_classification"),
        ({"classification": "confirmed_capture"}, "invalid_classification"),
        ({"kind": "sale"}, "invalid_kind"),
        ({"client_id": None}, "invalid_client"),
        ({"agency_id": "agency"}, "invalid_agency"),
        ({"delivery_id": ""}, "invalid_delivery_id"),
        ({"operation_id": " sale-1"}, "invalid_operation_id"),
        ({"source_account_id": "x" * 257}, "invalid_source_account"),
        ({"stream": "client_revenue"}, "invalid_stream"),
    ],
)
def test_evidence_rejects_malformed_fields(changes, code):
    with pytest.raises(LedgerInputError) as raised:
        replace(sale(), **changes)
    assert raised.value.code == code


@pytest.mark.parametrize(
    ("build", "code"),
    [
        (lambda: refund("refund-1", "1.00", parent=None), "invalid_parent"),
        (lambda: refund("refund-1", "1.00", parent="refund-1"), "invalid_parent"),
        (
            lambda: refund("refund-1", "1.00", classification=EvidenceClass.PURCHASE_SIGNAL),
            "invalid_classification",
        ),
        (
            lambda: sale(classification=EvidenceClass.AUDITED_CORRECTION),
            "invalid_classification",
        ),
        (lambda: audited("correction-1", "0.00"), "invalid_amount"),
    ],
)
def test_adjustments_reject_malformed_links(build, code):
    with pytest.raises(LedgerInputError) as raised:
        build()
    assert raised.value.code == code


def test_calculation_rejects_foreign_records_and_inconsistent_exponents():
    with pytest.raises(LedgerInputError) as raised:
        calculate([object()])
    assert raised.value.code == "invalid_evidence"
    # Since R007-04 the conflict is confined to the affected client's totals.
    result = calculate([sale(), sale("sale-2", "1.000", currency=Currency("AAA", 3))])
    with pytest.raises(LedgerInputError) as raised:
        result.totals(AGENCY, CLIENT)
    assert raised.value.code == "currency_exponent_conflict"
