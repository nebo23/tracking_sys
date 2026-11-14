"""Regressions for the independent review findings R007-01 to R007-11 of PR 6 (specification 007-A).

Every case uses the public calculate() and convert() entry points with synthetic evidence. The
module imports only names that already existed in the reviewed commit 0e4fca1, so each case
can be run against that commit to demonstrate its failure; newer fields are read with getattr.
For R007-01 to R007-03 each case checks balances and postings after every delivery, the full
replay, and that the movement journal of each call extends the journal of the call before it.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations
from uuid import UUID
from zoneinfo import ZoneInfo

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
    Stream,
    calculate,
    convert,
)
from app.ledger.money import MAX_MINOR

AGENCY = UUID("00000000-0000-4000-8000-00000000a001")
AGENCY_2 = UUID("00000000-0000-4000-8000-00000000a002")
CLIENT = UUID("00000000-0000-4000-8000-00000000c001")
CLIENT_2 = UUID("00000000-0000-4000-8000-00000000c002")
CLIENT_3 = UUID("00000000-0000-4000-8000-00000000c003")
ACCOUNT = "acct-synthetic-1"
ACCOUNT_2 = "acct-synthetic-2"
SCOPE = LedgerScope(AGENCY, CLIENT, ACCOUNT)
AAA = Currency("AAA", 2)
AAA_3 = Currency("AAA", 3)
BBB = Currency("BBB", 2)
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
AS_OF = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
NEW_YORK = ZoneInfo("America/New_York")  # 2026-11-01 01:00-02:00 occurs twice

POSTED = AdjustmentStatus.POSTED
PENDING = AdjustmentStatus.PENDING
RECONCILIATION = AdjustmentStatus.RECONCILIATION
_DEFAULT_CLASS = {
    OperationKind.SALE: EvidenceClass.CONFIRMED_CAPTURE,
    OperationKind.CORRECTION: EvidenceClass.AUDITED_CORRECTION,
}


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def record(
    operation_id: str,
    amount: str = "1000.00",
    kind: OperationKind = OperationKind.SALE,
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
    return record(operation_id, amount, **extra)


def refund(operation_id: str, amount: str, parent: str = "sale-1", **extra) -> Evidence:
    return record(operation_id, amount, OperationKind.REFUND, parent=parent, **extra)


def chargeback(operation_id: str, amount: str, parent: str = "sale-1", **extra) -> Evidence:
    return record(operation_id, amount, OperationKind.CHARGEBACK, parent=parent, **extra)


def reversal(operation_id: str, amount: str, parent: str = "chargeback-1", **extra) -> Evidence:
    return record(operation_id, amount, OperationKind.CHARGEBACK_REVERSAL, parent=parent, **extra)


def audited(operation_id: str, amount: str, **extra) -> Evidence:
    fields = {
        "actor": "reviewer-synthetic-1",
        "reason": "Synthetic reconciliation outcome",
        "source_reference": "statement-synthetic-7",
    }
    fields.update(extra)
    return record(operation_id, amount, OperationKind.CORRECTION, **fields)


def deliver(sequence) -> list[Evidence]:
    """Receive the records in this order, one minute apart, whatever their effective times."""
    return [
        replace(item, received_at=at(10_000 + position)) for position, item in enumerate(sequence)
    ]


def net(result, agency: UUID = AGENCY, client: UUID = CLIENT, code: str = "AAA") -> int | None:
    totals = result.totals(agency, client)
    return totals[code].net if code in totals else None


def postings(result) -> list[tuple[str, int]]:
    return [(entry.operation_id, entry.amount.minor) for entry in result.entries]


def states(result) -> list[tuple]:
    return [(a.operation_id, a.status, a.status_reason) for a in result.adjustments]


def review(result) -> list[tuple]:
    return [
        (item.operation_id, item.reason, tuple(e.delivery_id for e in item.evidence))
        for item in result.reconciliation
    ]


def journal(result) -> list[tuple]:
    """The movement journal; empty for an implementation that has none."""
    return [
        (m.sequence, m.operation_id, m.movement, m.amount.minor, m.trigger.delivery_id, m.reason)
        for m in getattr(result, "movements", None) or ()
    ]


def stepwise(sequence) -> list[tuple[int | None, list[tuple[str, int]]]]:
    """Net and postings after each delivery of the sequence."""
    delivered = deliver(sequence)
    steps = []
    for count in range(1, len(delivered) + 1):
        result = calculate(delivered[:count])
        steps.append((net(result), postings(result)))
    return steps


def assert_append_only(sequence) -> None:
    """Every call's journal extends the previous one, and the full replay reproduces the last."""
    delivered = deliver(sequence)
    previous: list[tuple] = []
    for count in range(1, len(delivered) + 1):
        result = calculate(delivered[:count])
        current = journal(result)
        assert current[: len(previous)] == previous
        assert sum(line[3] for line in current) == sum(t.net.minor for t in result.transactions)
        previous = current
    assert journal(calculate(delivered)) == previous


# R007-01: a re-notification with another effective time cannot move a posted operation.


def test_r007_01_renotified_refund_with_an_earlier_time_keeps_800_and_the_200_posting():
    capture = sale()
    small = refund("refund-200", "200.00", effective=10)
    large = refund("refund-900", "900.00", effective=20)
    renotified = replace(large, delivery_id="dlv-refund-900-retry", effective_at=at(5))
    sequence = [capture, small, large, renotified]

    after_capture = (100_000, [("sale-1", 100_000)])
    after_refund = (80_000, [("sale-1", 100_000), ("refund-200", -20_000)])
    assert stepwise(sequence) == [after_capture, after_refund, after_refund, after_refund]

    result = calculate(deliver(sequence))
    assert net(result) == 80_000
    assert [e.delivery_id for e in result.entries[1].evidence] == ["dlv-refund-200"]
    [competing] = [a for a in result.adjustments if a.operation_id == "refund-900"]
    assert (competing.status, competing.status_reason, competing.effective_at) == (
        RECONCILIATION,
        "exceeds_outstanding",
        at(20),
    )
    assert review(result) == [
        ("refund-900", "conflicting_evidence", ("dlv-refund-900-retry",)),
        ("refund-900", "exceeds_outstanding", ("dlv-refund-900",)),
    ]
    copy = replace(large, delivery_id="dlv-refund-900-copy")
    copied = calculate(deliver([capture, small, large, copy]))
    assert copied.outcomes[-1].disposition is Disposition.DUPLICATE
    assert net(copied) == 80_000
    assert_append_only(sequence)


def test_r007_01_capture_and_settlement_keep_their_own_times():
    capture = sale(delivery="dlv-cap-1")
    settlement = replace(
        capture,
        delivery_id="dlv-settle-1",
        classification=EvidenceClass.CONFIRMED_SETTLEMENT,
        effective_at=at(60 * 24),
    )
    shifted = replace(capture, delivery_id="dlv-cap-2", effective_at=at(-30))

    result = calculate(deliver([capture, settlement, shifted]))

    [entry] = result.entries
    assert entry.effective_at == at(0)
    assert [(e.delivery_id, e.effective_at) for e in entry.evidence] == [
        ("dlv-cap-1", at(0)),
        ("dlv-settle-1", at(60 * 24)),
    ]
    assert review(result) == [("sale-1", "conflicting_evidence", ("dlv-cap-2",))]
    assert net(result) == 100_000


# R007-02: a committed effect changes only through an explicit, appended movement.


def test_r007_02_late_earlier_effective_refund_is_traced_by_a_release_movement():
    capture = sale()
    small = refund("refund-200", "200.00", effective=20)
    large = refund("refund-900", "900.00", effective=10)
    sequence = [capture, small, large]

    assert stepwise(sequence) == [
        (100_000, [("sale-1", 100_000)]),
        (80_000, [("sale-1", 100_000), ("refund-200", -20_000)]),
        (10_000, [("sale-1", 100_000), ("refund-900", -90_000)]),
    ]
    result = calculate(deliver(sequence))
    assert journal(result) == [
        (1, "sale-1", "posting", 100_000, "dlv-sale-1", None),
        (2, "refund-200", "posting", -20_000, "dlv-refund-200", None),
        (3, "refund-200", "release", 20_000, "dlv-refund-900", "exceeds_outstanding"),
        (4, "refund-900", "posting", -90_000, "dlv-refund-900", None),
    ]
    assert states(result) == [
        ("refund-200", RECONCILIATION, "exceeds_outstanding"),
        ("refund-900", POSTED, None),
    ]
    assert_append_only(sequence)

    expected = (postings(result), states(result), review(result), result.totals(AGENCY, CLIENT))
    for order in permutations(sequence):
        shuffled = calculate(deliver(order))
        assert (
            postings(shuffled),
            states(shuffled),
            review(shuffled),
            shuffled.totals(AGENCY, CLIENT),
        ) == expected
        assert sum(line[3] for line in journal(shuffled)) == 10_000


# R007-03: a chargeback is normalized with its reversals before competing refunds are judged.


def test_r007_03_full_chargeback_reversal_and_full_refund_leave_net_zero():
    capture = sale()
    debit = chargeback("chargeback-1", "1000.00", effective=10)
    refund_all = refund("refund-1", "1000.00", effective=20)
    restore = reversal("reversal-1", "1000.00", effective=30)
    sequence = [capture, debit, refund_all, restore]

    assert stepwise(sequence) == [
        (100_000, [("sale-1", 100_000)]),
        (0, [("sale-1", 100_000), ("chargeback-1", -100_000)]),
        (0, [("sale-1", 100_000), ("chargeback-1", -100_000)]),
        (
            0,
            [
                ("sale-1", 100_000),
                ("chargeback-1", -100_000),
                ("reversal-1", 100_000),
                ("refund-1", -100_000),
            ],
        ),
    ]
    for order in permutations(sequence):
        result = calculate(deliver(order))
        totals = result.totals(AGENCY, CLIENT)["AAA"]
        assert (
            totals.captured,
            totals.refunded,
            totals.charged_back,
            totals.reversed,
            totals.net,
        ) == (100_000, 100_000, 100_000, 100_000, 0)
        assert result.reconciliation == ()
    assert_append_only(sequence)


def test_r007_03_partial_reversal_and_a_refund_that_still_exceeds():
    capture = sale()
    debit = chargeback("chargeback-1", "1000.00", effective=10)
    partial = reversal("reversal-1", "400.00", effective=30)
    fitting = refund("refund-1", "400.00", effective=20)
    excessive = refund("refund-2", "500.00", effective=20)

    for order in permutations([capture, debit, partial, fitting]):
        assert net(calculate(deliver(order))) == 0
    for order in permutations([capture, debit, partial, excessive]):
        result = calculate(deliver(order))
        assert net(result) == 40_000
        assert ("refund-2", RECONCILIATION, "exceeds_outstanding") in states(result)
    assert_append_only([capture, debit, fitting, partial])

    second = reversal("reversal-2", "700.00", effective=40)
    result = calculate([capture, debit, partial, second])
    assert ("reversal-2", RECONCILIATION, "reversal_exceeds_debit") in states(result)
    assert net(result) == 40_000


# R007-04: evidence of other tenants cannot interrupt a valid client's calculation.


def test_r007_04_other_agencies_and_clients_cannot_interrupt_a_valid_client():
    valid = [sale(), sale("sale-2", "50.00", account=ACCOUNT_2)]
    foreign_subscription = record(
        "subscription-1",
        "9.990",
        agency=AGENCY_2,
        client=None,
        stream=Stream.AGENCY_SUBSCRIPTION,
        currency=AAA_3,
    )
    same_agency_subscription = record(
        "subscription-2", "9.990", client=None, stream=Stream.AGENCY_SUBSCRIPTION, currency=AAA_3
    )
    other_agency = sale("sale-x", "5.000", agency=AGENCY_2, client=CLIENT_3, currency=AAA_3)
    mixed_client = [
        sale("sale-y", "5.000", client=CLIENT_2, currency=AAA_3),
        sale("sale-z", "5.00", client=CLIENT_2, account=ACCOUNT_2),
    ]
    records = [*valid, foreign_subscription, same_agency_subscription, other_agency, *mixed_client]

    result = calculate(records)

    totals = result.totals(AGENCY, CLIENT)["AAA"]
    assert (totals.currency, totals.net) == (AAA, 105_000)
    assert result.totals(AGENCY, CLIENT, ACCOUNT)["AAA"].net == 100_000
    assert result.totals(AGENCY_2, CLIENT_3)["AAA"].currency == AAA_3
    with pytest.raises(LedgerInputError) as raised:
        result.totals(AGENCY, CLIENT_2)
    assert raised.value.code == "currency_exponent_conflict"
    assert result.totals(AGENCY, CLIENT_2, ACCOUNT)["AAA"].currency == AAA_3
    assert set(result.excluded) == {foreign_subscription, same_agency_subscription}


# R007-05: unverified evidence cannot reserve a delivery ID of confirmed evidence.


def test_r007_05_signal_and_capture_sharing_a_delivery_id_post_one_sale_in_either_order():
    capture = sale(delivery="dlv-shared")
    signal = record(
        "order-1", "1000.00", classification=EvidenceClass.PURCHASE_SIGNAL, delivery="dlv-shared"
    )
    for order in ([signal, capture], [capture, signal]):
        result = calculate(deliver(order))
        assert net(result) == 100_000
        assert postings(result) == [("sale-1", 100_000)]
        assert [e.operation_id for e in result.unverified] == ["order-1"]
        outcomes = {o.evidence.operation_id: o.disposition for o in result.outcomes}
        assert outcomes == {"sale-1": Disposition.POSTED, "order-1": Disposition.UNVERIFIED}
        [collision] = result.reconciliation
        assert (collision.reason, [e.classification for e in collision.evidence]) == (
            "delivery_id_shared",
            [EvidenceClass.CONFIRMED_CAPTURE, EvidenceClass.PURCHASE_SIGNAL],
        )


# R007-06: aware times are compared as absolute instants.


def _snapshot(effective_at: datetime, source: str = "synthetic-fixture", snapshot_id="fx-1"):
    return FxRateSnapshot(snapshot_id, AAA, BBB, Decimal("2"), effective_at, source)


@pytest.mark.parametrize(
    ("as_of", "quoted", "max_age", "status"),
    [
        # 01:30 first fold is 05:30 UTC; 01:10 second fold is 06:10 UTC, a future quote.
        (
            datetime(2026, 11, 1, 1, 30, tzinfo=NEW_YORK),
            datetime(2026, 11, 1, 1, 10, tzinfo=NEW_YORK, fold=1),
            DAY,
            ConversionStatus.MISSING,
        ),
        # 01:40 second fold is 06:40 UTC, after the 06:10 UTC quote.
        (
            datetime(2026, 11, 1, 1, 40, tzinfo=NEW_YORK, fold=1),
            datetime(2026, 11, 1, 1, 10, tzinfo=NEW_YORK, fold=1),
            DAY,
            ConversionStatus.CONVERTED,
        ),
        # A 05:50 UTC quote is 30 minutes old at 06:20 UTC: stale under a 20-minute limit.
        (
            datetime(2026, 11, 1, 1, 20, tzinfo=NEW_YORK, fold=1),
            datetime(2026, 11, 1, 1, 50, tzinfo=NEW_YORK),
            timedelta(minutes=20),
            ConversionStatus.STALE,
        ),
    ],
)
def test_r007_06_quote_eligibility_and_age_use_absolute_instants(as_of, quoted, max_age, status):
    local = convert([Money(100, AAA)], BBB, [_snapshot(quoted)], as_of=as_of, max_age=max_age)
    in_utc = convert(
        [Money(100, AAA)],
        BBB,
        [_snapshot(quoted.astimezone(UTC))],
        as_of=as_of.astimezone(UTC),
        max_age=max_age,
    )
    assert local.components[0].status is status
    assert in_utc.components[0].status is status
    # PEP 495: a datetime whose fold changes its offset never equals one in another zone, so
    # the complete records are compared with their times as UTC instants.
    assert _as_utc(local) == _as_utc(in_utc)


def _as_utc(conversion) -> tuple:
    return (
        conversion.as_of.astimezone(UTC),
        conversion.amount,
        [
            (
                c.original,
                c.status,
                c.exact_minor,
                None
                if c.snapshot is None
                else replace(c.snapshot, effective_at=c.snapshot.effective_at.astimezone(UTC)),
            )
            for c in conversion.components
        ],
    )


def test_r007_06_ledger_orders_effective_and_receipt_times_by_instant():
    second_fold = datetime(2026, 11, 1, 1, 10, tzinfo=NEW_YORK, fold=1)  # 06:10 UTC
    first_fold = datetime(2026, 11, 1, 1, 40, tzinfo=NEW_YORK)  # 05:40 UTC, earlier
    capture = sale()
    later = replace(refund("refund-a", "600.00"), effective_at=second_fold)
    earlier = replace(refund("refund-b", "600.00"), effective_at=first_fold)
    for local in (True, False):
        convert_time = (lambda value: value) if local else (lambda value: value.astimezone(UTC))
        records = [
            capture,
            replace(later, effective_at=convert_time(second_fold)),
            replace(earlier, effective_at=convert_time(first_fold)),
        ]
        result = calculate(records)
        assert states(result) == [
            ("refund-a", RECONCILIATION, "exceeds_outstanding"),
            ("refund-b", POSTED, None),
        ]

    first_received = replace(sale(delivery="dlv-cap-1"), received_at=first_fold)
    second_received = replace(
        sale("sale-1", "1200.00", delivery="dlv-cap-2"), received_at=second_fold
    )
    result = calculate([second_received, first_received])
    assert net(result) == 100_000
    assert review(result) == [("sale-1", "conflicting_evidence", ("dlv-cap-2",))]


# R007-07: per-delivery provenance is evidence, not an economic term.


def test_r007_07_capture_and_settlement_references_attach_to_one_sale():
    capture = sale(delivery="dlv-cap-1", source_reference="capture-doc-1")
    settlement = replace(
        capture,
        delivery_id="dlv-settle-1",
        classification=EvidenceClass.CONFIRMED_SETTLEMENT,
        effective_at=at(60 * 24),
        source_reference="settlement-doc-7",
    )
    result = calculate(deliver([capture, settlement]))
    assert result.reconciliation == ()
    [entry] = result.entries
    assert [e.source_reference for e in entry.evidence] == ["capture-doc-1", "settlement-doc-7"]

    short = replace(settlement, delivery_id="dlv-settle-2", amount=Money.parse("990.00", AAA))
    assert review(calculate(deliver([capture, short]))) == [
        ("sale-1", "conflicting_evidence", ("dlv-settle-2",))
    ]

    fix = audited("correction-1", "5.00", parent="sale-1", effective=30)
    restated = replace(fix, delivery_id="dlv-correction-1-b", reason="Another synthetic reason")
    corrected = calculate(deliver([capture, fix, restated]))
    [adjustment] = corrected.adjustments
    assert (adjustment.actor, adjustment.reason, adjustment.source_reference) == (
        "reviewer-synthetic-1",
        "Synthetic reconciliation outcome",
        "statement-synthetic-7",
    )
    assert review(corrected) == [("correction-1", "conflicting_evidence", ("dlv-correction-1-b",))]


# R007-08: one discrepancy produces one reconciliation item, however often it is repeated.


def test_r007_08_identical_retries_of_a_reused_delivery_id_form_one_discrepancy():
    capture = sale(delivery="dlv-cap-1")
    altered = replace(capture, amount=Money.parse("1.00", AAA))
    different = replace(capture, amount=Money.parse("2.00", AAA))

    result = calculate(deliver([capture, altered, altered, altered]))
    assert review(result) == [("sale-1", "delivery_id_reused", ("dlv-cap-1",) * 3)]
    assert [o.disposition for o in result.outcomes] == [Disposition.POSTED] + [
        Disposition.RECONCILIATION
    ] * 3
    assert net(result) == 100_000

    mixed = calculate(deliver([capture, altered, different, altered]))
    assert sorted(len(item.evidence) for item in mixed.reconciliation) == [1, 2]

    claim = replace(capture, delivery_id="dlv-cap-9", amount=Money.parse("1200.00", AAA))
    repeated = calculate(deliver([capture, claim, replace(claim, delivery_id="dlv-cap-10")]))
    assert review(repeated) == [("sale-1", "conflicting_evidence", ("dlv-cap-9", "dlv-cap-10"))]


# R007-09: impossible parent chains are reconciled; a missing parent still waits.


def test_r007_09_cycles_and_invalid_parent_kinds_go_to_reconciliation():
    capture = sale()
    first = audited("correction-a", "1.00", parent="correction-b", effective=10)
    second = audited("correction-b", "1.00", parent="correction-a", effective=20)
    waiting = refund("refund-1", "10.00", parent="sale-9", effective=30)
    nested = refund("refund-2", "10.00", parent="refund-1", effective=40)

    result = calculate([capture, first, second, waiting, nested])

    assert states(result) == [
        ("correction-a", RECONCILIATION, "parent_cycle"),
        ("correction-b", RECONCILIATION, "parent_cycle"),
        ("refund-1", PENDING, "parent_missing"),
        ("refund-2", RECONCILIATION, "invalid_parent"),
    ]
    assert [item.reason for item in result.reconciliation] == [
        "parent_cycle",
        "parent_cycle",
        "invalid_parent",
    ]
    resolved = calculate([capture, first, second, waiting, nested, sale("sale-9", "100.00")])
    assert ("refund-1", POSTED, None) in states(resolved)
    assert ("refund-2", RECONCILIATION, "invalid_parent") in states(resolved)
    assert net(resolved) == 100_000 + 10_000 - 1_000


# R007-10: exact accumulation before output bounds.


def test_r007_10_same_currency_inputs_accumulate_exactly_in_every_order():
    largest = MAX_MINOR - 1
    for order in permutations([Money(largest, BBB), Money(1, BBB), Money(-1, BBB)]):
        assert convert(order, BBB, [], as_of=AS_OF, max_age=DAY).amount == Money(largest, BBB)
    with pytest.raises(LedgerInputError) as raised:
        convert([Money(largest, BBB), Money(1, BBB)], BBB, [], as_of=AS_OF, max_age=DAY)
    assert raised.value.code == "invalid_amount"

    capture = replace(sale(), amount=Money(largest, AAA))
    plus = replace(audited("correction-1", "0.01", parent="sale-1", effective=10))
    minus = replace(audited("correction-2", "-0.01", parent="sale-1", effective=10))
    for order in permutations([capture, plus, minus]):
        assert calculate(deliver(order)).transactions[0].net == Money(largest, AAA)


# R007-11: snapshot provenance does not depend on input order.


def test_r007_11_snapshots_differing_only_in_source_give_the_same_record_in_both_orders():
    quoted = AS_OF - timedelta(hours=1)
    feed_a = _snapshot(quoted, source="feed-a")
    feed_b = _snapshot(quoted, source="feed-b")
    forward = convert([Money(100, AAA)], BBB, [feed_a, feed_b], as_of=AS_OF, max_age=DAY)
    backward = convert([Money(100, AAA)], BBB, [feed_b, feed_a], as_of=AS_OF, max_age=DAY)
    assert forward == backward
    assert (forward.components[0].status, forward.amount) == (ConversionStatus.CONFLICTING, None)

    first = _snapshot(quoted, source="feed-b", snapshot_id="fx-1")
    second = _snapshot(quoted, source="feed-a", snapshot_id="fx-2")
    forward = convert([Money(100, AAA)], BBB, [first, second], as_of=AS_OF, max_age=DAY)
    backward = convert([Money(100, AAA)], BBB, [second, first], as_of=AS_OF, max_age=DAY)
    assert forward == backward
    assert forward.components[0].snapshot == first
    assert forward.amount == Money(200, BBB)


# R007-02 follow-up: records received at the same instant keep the journal append-only.

RECEIVED = at(10_000)


def _tie_case():
    capture = replace(sale(), received_at=at(9_000))
    small = replace(
        refund("refund-200", "200.00", delivery="dlv-b", effective=20), received_at=RECEIVED
    )
    large = replace(
        refund("refund-900", "900.00", delivery="dlv-a", effective=10), received_at=RECEIVED
    )
    return capture, small, large


def assert_log_extends(log) -> None:
    """After each appended record the earlier journal is an exact prefix of the new one, and a
    consumer that reads only movements after its last sequence reaches the recalculated net."""
    previous = ()
    consumer_balance = 0
    for count in range(1, len(log) + 1):
        result = calculate(log[:count])
        assert result.movements[: len(previous)] == previous
        last = previous[-1].sequence if previous else 0
        consumer_balance += sum(m.amount.minor for m in result.movements if m.sequence > last)
        assert consumer_balance == sum(t.net.minor for t in result.transactions)
        previous = result.movements


def test_r007_02_equal_receipt_instants_keep_returned_movements():
    capture, small, large = _tie_case()

    first = calculate([capture, small])
    read = first.movements
    assert net(first) == 80_000
    assert journal(first) == [
        (1, "sale-1", "posting", 100_000, "dlv-sale-1", None),
        (2, "refund-200", "posting", -20_000, "dlv-b", None),
    ]

    second = calculate([capture, small, large])
    assert second.movements[: len(read)] == read
    assert journal(second)[len(read) :] == [
        (3, "refund-200", "release", 20_000, "dlv-a", "exceeds_outstanding"),
        (4, "refund-900", "posting", -90_000, "dlv-a", None),
    ]
    consumer = net(first) + sum(
        m.amount.minor for m in second.movements if m.sequence > read[-1].sequence
    )
    assert consumer == net(second) == 10_000
    assert_log_extends([capture, small, large])


def test_r007_02_equal_receipt_instants_in_the_other_order():
    capture, small, large = _tie_case()
    forward = calculate([capture, small, large])
    backward = calculate([capture, large, small])

    assert net(backward) == net(forward) == 10_000
    assert postings(backward) == postings(forward)
    assert states(backward) == states(forward)
    assert journal(backward) == [
        (1, "sale-1", "posting", 100_000, "dlv-sale-1", None),
        (2, "refund-900", "posting", -90_000, "dlv-a", None),
    ]
    assert_log_extends([capture, large, small])


def test_r007_02_identical_resend_and_microsecond_receipts():
    capture, small, large = _tie_case()
    resent = replace(small, received_at=RECEIVED)
    with_resend = calculate([capture, small, resent, large])
    assert journal(with_resend) == journal(calculate([capture, small, large]))
    assert with_resend.outcomes[2].disposition is Disposition.DUPLICATE
    assert_log_extends([capture, small, resent, large, replace(large, received_at=at(10_001))])

    later = replace(large, received_at=RECEIVED + timedelta(microseconds=1))
    assert journal(calculate([capture, small, later])) == journal(
        calculate([capture, small, large])
    )
    earlier = replace(large, received_at=RECEIVED - timedelta(microseconds=1))
    assert journal(calculate([capture, small, earlier])) == journal(
        calculate([capture, large, small])
    )
    assert_log_extends([capture, small, later])
