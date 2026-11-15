"""Lead and revenue attribution acceptance cases (specification 008-A, D-046).

Every agency, client, person, touchpoint, operation and amount is synthetic. Each client has its
own isolated journey. Sales, refunds and releases are built through the real 007-A
app.ledger.calculate(); its movement journal drives the incremental consumer, which is compared
with a fresh calculation from the full receipt log after every step.
"""

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from fractions import Fraction
from uuid import UUID

import pytest

from app.attribution import (
    Association,
    AttributionHistory,
    AttributionInputError,
    AttributionModel,
    Conversion,
    ConversionKind,
    CreditBasis,
    EvidenceClass,
    ExclusionReason,
    IncrementalAttribution,
    ModelVersion,
    Recipient,
    RevisionCause,
    RunStatus,
    SaleState,
    Touchpoint,
    attribute,
    ledger_feed,
    sale_conversion,
    sale_state,
)
from app.ledger import Currency, Evidence, LedgerScope, Money, OperationKind, calculate
from app.ledger import EvidenceClass as LedgerClass
from app.privacy.consent import ConsentState

AGENCY = UUID("00000000-0000-4000-8000-00000000a001")
AGENCY_2 = UUID("00000000-0000-4000-8000-00000000a002")
CLIENT = UUID("00000000-0000-4000-8000-00000000c001")
CLIENT_2 = UUID("00000000-0000-4000-8000-00000000c002")
ACCOUNT = "acct-synthetic-1"
ACCOUNT_2 = "acct-synthetic-2"
PERSON = "person-synthetic-1"
AAA = Currency("AAA", 2)
BBB = Currency("BBB", 3)
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)  # the sale's effective instant
DAY = timedelta(days=1)
MICRO = timedelta(microseconds=1)

FIRST = ModelVersion("first-click.v1", AttributionModel.FIRST_CLICK)
LAST = ModelVersion("last-click.v1", AttributionModel.LAST_CLICK)
LINEAR = ModelVersion("linear.v1", AttributionModel.LINEAR)
MODELS = (FIRST, LAST, LINEAR)


# Journey and ledger fixtures.


def touch(
    touchpoint_id: str,
    occurred_at: datetime,
    evidence: EvidenceClass = EvidenceClass.CAMPAIGN_INTERACTION,
    *,
    agency: UUID = AGENCY,
    client: UUID = CLIENT,
    person: str = PERSON,
    association: Association = Association.ASSIGNED,
    consent: ConsentState = ConsentState.GRANTED,
    **refs,
) -> Touchpoint:
    if evidence is EvidenceClass.CAMPAIGN_INTERACTION and not refs:
        refs = {
            "source": "instagram",
            "campaign_ref": f"campaign-{touchpoint_id}",
            "content_ref": f"post-{touchpoint_id}",
            "link_ref": f"link-{touchpoint_id}",
        }
    return Touchpoint(
        touchpoint_id,
        agency,
        client,
        person,
        evidence,
        occurred_at,
        association,
        consent,
        **refs,
    )


def direct(touchpoint_id: str, occurred_at: datetime, **extra) -> Touchpoint:
    return touch(touchpoint_id, occurred_at, EvidenceClass.DIRECT_VISIT, source="direct", **extra)


A = touch("tp-a", T0 - 3 * DAY)
B = touch("tp-b", T0 - DAY)


def lead(
    effective_at: datetime = T0, *, conversion_id: str = "lead-1", client: UUID = CLIENT
) -> Conversion:
    return Conversion(conversion_id, AGENCY, client, PERSON, ConversionKind.LEAD, effective_at)


def ledger_record(
    operation_id: str,
    amount: str,
    kind: OperationKind = OperationKind.SALE,
    *,
    parent: str | None = None,
    classification: LedgerClass | None = None,
    delivery: str | None = None,
    effective: timedelta = timedelta(0),
    received: timedelta | None = None,
    agency: UUID = AGENCY,
    client: UUID = CLIENT,
    account: str = ACCOUNT,
    currency: Currency = AAA,
) -> Evidence:
    if classification is None:
        classification = (
            LedgerClass.CONFIRMED_CAPTURE
            if kind is OperationKind.SALE
            else LedgerClass.CONFIRMED_ADJUSTMENT
        )
    return Evidence(
        delivery_id=delivery or f"dlv-{operation_id}",
        agency_id=agency,
        client_id=client,
        source_account_id=account,
        operation_id=operation_id,
        kind=kind,
        classification=classification,
        amount=Money.parse(amount, currency),
        effective_at=T0 + effective,
        received_at=T0 + (received if received is not None else effective),
        parent_operation_id=parent,
    )


def capture(amount: str = "1000.00", **extra) -> Evidence:
    return ledger_record("sale-1", amount, **extra)


def refund(operation_id: str, amount: str, **extra) -> Evidence:
    return ledger_record(operation_id, amount, OperationKind.REFUND, parent="sale-1", **extra)


def sale_from(log, *, account: str = ACCOUNT, client: UUID = CLIENT, agency: UUID = AGENCY):
    """The sale conversion of sale-1 in the given scope, and the ledger it came from."""
    ledger = calculate(log)
    scope = LedgerScope(agency, client, account)
    transaction = next(
        t for t in ledger.transactions if t.scope == scope and t.operation_id == "sale-1"
    )
    return sale_conversion(transaction, conversion_id="conv-sale-1", person_id=PERSON), ledger


def run_sale(log, touches, version, **extra):
    conversion, ledger = sale_from(log, **extra)
    return attribute(conversion, touches, version, sale=sale_state(ledger, conversion))


def state(minor: int, currency: Currency = AAA) -> SaleState:
    return SaleState(LedgerScope(AGENCY, CLIENT, ACCOUNT), "sale-1", currency, T0, minor)


def credit(run) -> list[tuple]:
    """(recipient key, share, minor units or None) for each allocation, in order."""
    return [
        (
            a.touch.touchpoint_id if a.touch else a.recipient.value,
            a.share,
            a.amount and a.amount.minor,
        )
        for a in run.allocations
    ]


def excluded(run) -> dict[str, ExclusionReason]:
    return {item.touchpoint_id: item.reason for item in run.excluded}


def assert_balanced(run) -> None:
    """Lead credit sums to exactly one unit; sale credit sums to the net, minor unit for unit."""
    assert run.credited_share == 1
    if run.conversion.kind is ConversionKind.SALE:
        assert run.credited_minor == run.verified_net.minor
        assert {a.amount.currency for a in run.allocations} == {run.verified_net.currency}
    else:
        assert all(a.amount is None for a in run.allocations)


# Lead versus sale.


def test_lead_credit_is_one_unit_split_into_exact_shares():
    conversion = lead()
    first, last, linear = (attribute(conversion, [B, A], version) for version in MODELS)
    assert credit(first) == [("tp-a", Fraction(1), None)]
    assert credit(last) == [("tp-b", Fraction(1), None)]
    assert credit(linear) == [("tp-a", Fraction(1, 2), None), ("tp-b", Fraction(1, 2), None)]
    three = attribute(conversion, [A, B, touch("tp-c", T0 - 2 * DAY)], LINEAR)
    assert [share for _, share, _ in credit(three)] == [Fraction(1, 3)] * 3
    for run in (first, last, linear, three):
        assert run.status is RunStatus.COMPLETE and run.verified_net is None
        assert_balanced(run)
    with pytest.raises(AttributionInputError) as error:
        attribute(conversion, [A], LINEAR, sale=state(100))
    assert error.value.code == "lead_has_revenue"


def test_sale_uses_the_verified_net_of_its_ledger_transaction():
    log = [capture("100.00")]
    first, last, linear = (run_sale(log, [A, B], version) for version in MODELS)
    assert credit(first) == [("tp-a", 1, 10_000)]
    assert credit(last) == [("tp-b", 1, 10_000)]
    assert credit(linear) == [("tp-a", Fraction(1, 2), 5_000), ("tp-b", Fraction(1, 2), 5_000)]
    allocation = first.allocations[0]
    assert allocation.rule == "first_click/campaign"
    assert allocation.recipient is Recipient.CAMPAIGN
    assert (allocation.touch.source, allocation.touch.campaign_ref) == (
        "instagram",
        "campaign-tp-a",
    )
    assert (allocation.touch.content_ref, allocation.touch.link_ref) == ("post-tp-a", "link-tp-a")
    for run in (first, last, linear):
        assert run.verified_net == Money(10_000, AAA)
        assert_balanced(run)


@pytest.mark.parametrize(
    "classification", [LedgerClass.PURCHASE_SIGNAL, LedgerClass.MANUAL_DECLARATION]
)
def test_unverified_purchase_evidence_supplies_no_revenue(classification):
    signal = capture("100.00", classification=classification)
    ledger = calculate([signal])
    assert ledger.transactions == ()
    conversion = Conversion(
        "conv-signal", AGENCY, CLIENT, PERSON, ConversionKind.SALE, T0, ACCOUNT, "sale-1"
    )
    assert sale_state(ledger, conversion) is None
    for version in MODELS:
        run = attribute(conversion, [A, B], version, sale=sale_state(ledger, conversion))
        assert run.status is RunStatus.NO_VERIFIED_REVENUE
        assert (run.verified_net, run.allocations, run.credited_minor) == (None, (), 0)


# Direct, unknown and scope.


def test_campaign_precedes_direct_and_direct_precedes_unknown():
    visit = direct("tp-direct", T0 - timedelta(hours=2))
    after_campaign = run_sale([capture("100.00")], [A, visit], LAST)
    assert credit(after_campaign) == [("tp-a", 1, 10_000)]
    assert excluded(after_campaign) == {"tp-direct": ExclusionReason.DIRECT_SUPERSEDED}

    direct_only = run_sale([capture("100.00")], [visit], LAST)
    assert direct_only.basis is CreditBasis.DIRECT_FALLBACK
    assert credit(direct_only) == [("tp-direct", 1, 10_000)]
    assert direct_only.allocations[0].recipient is Recipient.DIRECT
    assert direct_only.allocations[0].rule == "last_click/direct_fallback"

    for version in MODELS:
        unknown = run_sale([capture("100.00")], [], version)
        assert unknown.basis is CreditBasis.UNKNOWN_FALLBACK
        assert credit(unknown) == [("unknown", 1, 10_000)]
        assert unknown.allocations[0].touch is None
        assert_balanced(unknown)
        unknown_lead = attribute(lead(), [], version)
        assert credit(unknown_lead) == [("unknown", 1, None)]


def test_ineligible_evidence_cannot_identify_a_buyer():
    touches = [
        touch("tp-denied", T0 - 2 * DAY, consent=ConsentState.DENIED),
        touch("tp-withdrawn", T0 - 2 * DAY, consent=ConsentState.WITHDRAWN),
        touch("tp-unknown-consent", T0 - 2 * DAY, consent=ConsentState.UNKNOWN),
        touch("tp-ambiguous", T0 - 2 * DAY, association=Association.AMBIGUOUS),
        touch("tp-unresolved", T0 - 2 * DAY, association=Association.UNRESOLVED),
        touch("tp-other-owner", T0 - 2 * DAY, association=Association.EXCLUDED),
        touch("tp-views", T0 - 2 * DAY, EvidenceClass.AGGREGATE_METRIC, source="instagram"),
    ]
    run = run_sale([capture("100.00")], touches, LINEAR)
    assert credit(run) == [("unknown", 1, 10_000)]
    assert excluded(run) == {
        "tp-denied": ExclusionReason.CONSENT_NOT_GRANTED,
        "tp-withdrawn": ExclusionReason.CONSENT_NOT_GRANTED,
        "tp-unknown-consent": ExclusionReason.CONSENT_NOT_GRANTED,
        "tp-ambiguous": ExclusionReason.NOT_ASSIGNED,
        "tp-unresolved": ExclusionReason.NOT_ASSIGNED,
        "tp-other-owner": ExclusionReason.NOT_ASSIGNED,
        "tp-views": ExclusionReason.AGGREGATE_EVIDENCE,
    }
    with_eligible = run_sale([capture("100.00")], [*touches, B], LINEAR)
    assert credit(with_eligible) == [("tp-b", 1, 10_000)]


def test_repeated_identifiers_in_other_scopes_supply_no_touchpoints():
    # The same person and touchpoint IDs exist in another client and another agency.
    foreign = [
        replace(A, client_id=CLIENT_2, touchpoint_id="tp-x"),
        replace(B, agency_id=AGENCY_2),
        replace(A, client_id=CLIENT_2),  # same touchpoint ID as A, other client: no conflict
        replace(B, person_id="person-synthetic-2"),
    ]
    run = run_sale([capture("100.00")], [A, *foreign], LAST)
    assert credit(run) == [("tp-a", 1, 10_000)]
    assert run.excluded == ()  # another scope's touches are never listed
    other_client = run_sale([capture("100.00", client=CLIENT_2)], [A, B], LAST, client=CLIENT_2)
    assert credit(other_client) == [("unknown", 1, 10_000)]


def test_source_accounts_keep_repeated_transaction_ids_apart():
    log = [
        capture("100.00"),
        capture("700.00", account=ACCOUNT_2, delivery="dlv-acct-2"),
        refund("refund-1", "40.00", account=ACCOUNT_2, effective=DAY),
    ]
    first_account = run_sale(log, [A, B], LINEAR)
    second_account = run_sale(log, [A, B], LINEAR, account=ACCOUNT_2)
    assert credit(first_account) == [
        ("tp-a", Fraction(1, 2), 5_000),
        ("tp-b", Fraction(1, 2), 5_000),
    ]
    assert credit(second_account) == [
        ("tp-a", Fraction(1, 2), 33_000),
        ("tp-b", Fraction(1, 2), 33_000),
    ]


def test_retries_count_once_and_distinct_touches_with_one_content_count_separately():
    retry = replace(A, occurred_at=A.occurred_at.astimezone(timezone(timedelta(hours=2))))
    run = run_sale([capture("90.00")], [A, retry, A, B], LINEAR)
    assert credit(run) == [("tp-a", Fraction(1, 2), 4_500), ("tp-b", Fraction(1, 2), 4_500)]

    same_content = replace(B, touchpoint_id="tp-b-again", occurred_at=T0 - 2 * DAY)
    run = run_sale([capture("90.00")], [A, B, same_content], LINEAR)
    assert [key for key, _, _ in credit(run)] == ["tp-a", "tp-b-again", "tp-b"]
    assert [minor for _, _, minor in credit(run)] == [3_000, 3_000, 3_000]


def test_conflicting_records_of_one_touchpoint_are_excluded():
    moved = replace(B, occurred_at=T0 - 2 * DAY)
    run = run_sale([capture("100.00")], [A, B, moved], LAST)
    assert credit(run) == [("tp-a", 1, 10_000)]
    assert excluded(run) == {"tp-b": ExclusionReason.CONFLICTING_RECORDS}
    disputed = replace(B, association=Association.AMBIGUOUS)
    assert excluded(run_sale([capture("100.00")], [A, B, disputed], LAST)) == {
        "tp-b": ExclusionReason.CONFLICTING_RECORDS
    }


# Time and precision.


def test_window_is_inclusive_at_both_ends_in_utc():
    conversion = lead(T0)
    boundary = touch("tp-boundary", T0 - 30 * DAY)
    too_early = touch("tp-early", T0 - 30 * DAY - MICRO)
    at_conversion = touch("tp-at-conversion", T0)
    too_late = touch("tp-late", T0 + MICRO)
    touches = [boundary, too_early, at_conversion, too_late]
    first = attribute(conversion, touches, FIRST)
    last = attribute(conversion, touches, LAST)
    assert credit(first) == [("tp-boundary", 1, None)]
    assert credit(last) == [("tp-at-conversion", 1, None)]
    assert excluded(first) == {
        "tp-early": ExclusionReason.BEFORE_WINDOW,
        "tp-late": ExclusionReason.AFTER_CONVERSION,
    }
    assert (first.window_start, first.window_end) == (T0 - 30 * DAY, T0)

    # The same instants written with other offsets give the same result.
    cairo = timezone(timedelta(hours=2))
    shifted = [replace(t, occurred_at=t.occurred_at.astimezone(cairo)) for t in touches]
    shifted_conversion = lead(T0.astimezone(timezone(timedelta(hours=-5))))
    assert credit(attribute(shifted_conversion, shifted, FIRST)) == credit(first)
    assert excluded(attribute(shifted_conversion, shifted, FIRST)) == excluded(first)

    week = ModelVersion("first-click.7d", AttributionModel.FIRST_CLICK, window=7 * DAY)
    assert credit(attribute(conversion, [A, touch("tp-old", T0 - 8 * DAY)], week)) == [
        ("tp-a", 1, None)
    ]


def test_equal_instants_break_ties_by_touchpoint_id():
    # tp-ba is written first and in UTC; tp-ab is the same instant written at +02:00.
    instant = T0 - DAY
    ba = touch("tp-ba", instant)
    ab = touch("tp-ab", instant.astimezone(timezone(timedelta(hours=2))))
    for order in ([ba, ab], [ab, ba]):
        assert credit(attribute(lead(), order, FIRST)) == [("tp-ab", 1, None)]
        assert credit(attribute(lead(), order, LAST)) == [("tp-ba", 1, None)]
        assert [k for k, _, _ in credit(attribute(lead(), order, LINEAR))] == ["tp-ab", "tp-ba"]
        split = attribute(lead(), order, LINEAR)
        assert [a.position for a in split.allocations] == [1, 2]


def test_one_minor_unit_goes_to_the_first_touch_in_stable_order():
    run = run_sale([capture("0.01")], [B, A], LINEAR)
    assert credit(run) == [("tp-a", Fraction(1, 2), 1), ("tp-b", Fraction(1, 2), 0)]
    three = run_sale([capture("1.00")], [A, B, touch("tp-c", T0 - 2 * DAY)], LINEAR)
    assert [minor for _, _, minor in credit(three)] == [34, 33, 33]
    thousandths = run_sale([capture("0.005", currency=BBB)], [A, B], LINEAR)
    assert [a.amount for a in thousandths.allocations] == [Money(3, BBB), Money(2, BBB)]


def test_allocations_always_sum_to_the_net_and_ignore_input_order():
    generator = random.Random(8008)
    for _ in range(200):
        count = generator.randint(0, 7)
        touches = [
            touch(
                f"tp-{index}", T0 - generator.randint(0, 40) * DAY - generator.randint(0, 9) * MICRO
            )
            for index in range(count)
        ]
        if generator.random() < 0.3:
            touches.append(direct("tp-direct", T0 - generator.randint(0, 40) * DAY))
        minor = generator.randint(0, 10**9)
        conversion = Conversion(
            "conv-random", AGENCY, CLIENT, PERSON, ConversionKind.SALE, T0, ACCOUNT, "sale-1"
        )
        for version in MODELS:
            run = attribute(conversion, touches, version, sale=state(minor))
            assert_balanced(run)
            shuffled = touches[:]
            generator.shuffle(shuffled)
            again = attribute(conversion, shuffled, version, sale=state(minor))
            assert again == run


# Real ledger replay.


def test_refund_reduces_the_linear_allocation_of_each_touch():
    before = run_sale([capture()], [A, B], LINEAR)
    after = run_sale([capture(), refund("refund-200", "200.00", effective=DAY)], [A, B], LINEAR)
    assert credit(before) == [("tp-a", Fraction(1, 2), 50_000), ("tp-b", Fraction(1, 2), 50_000)]
    assert credit(after) == [("tp-a", Fraction(1, 2), 40_000), ("tp-b", Fraction(1, 2), 40_000)]
    assert after.window_end == T0  # anchored to the original sale instant, not the refund


def _tie_log():
    """The 007-A equal-receipt case: refund-900 arrives at the same instant as refund-200."""
    received = 10 * DAY
    return [
        capture(received=9 * DAY),
        refund("refund-200", "200.00", delivery="dlv-b", effective=20 * MICRO, received=received),
        refund("refund-900", "900.00", delivery="dlv-a", effective=10 * MICRO, received=received),
    ]


def _fresh(log, conversion, touches, version):
    ledger = calculate(log)
    sale = sale_state(ledger, conversion)
    return attribute(conversion, touches, version, sale=sale, ledger_position=len(log))


def test_resuming_from_receipt_two_equals_full_replay():
    log = _tie_log()
    conversion, _ = sale_from(log)
    consumer = IncrementalAttribution(MODELS)
    consumer.set_journey(AGENCY, CLIENT, PERSON, [A, B])
    consumer.register(conversion)

    read = ledger_feed(log[:2])
    assert [(i.receipt, i.movement.sequence, i.movement.operation_id) for i in read] == [
        (1, 1, "sale-1"),
        (2, 2, "refund-200"),
    ]
    assert [i.movement.amount.minor for i in read] == [100_000, -20_000]
    consumer.apply(read)
    assert consumer.checkpoint == 2
    assert credit(consumer.runs(conversion)[LINEAR.version_id]) == [
        ("tp-a", Fraction(1, 2), 40_000),
        ("tp-b", Fraction(1, 2), 40_000),
    ]

    journal = ledger_feed(log)
    assert journal[:2] == read
    assert [(i.receipt, i.index, i.count, i.movement.sequence) for i in journal[2:]] == [
        (3, 1, 2, 3),
        (3, 2, 2, 4),
    ]
    assert [(i.movement.movement.value, i.movement.amount.minor) for i in journal[2:]] == [
        ("release", 20_000),
        ("posting", -90_000),
    ]
    changed = consumer.apply(journal)  # the full journal: receipts 1 and 2 are skipped
    assert consumer.checkpoint == 3
    assert {run.model_version.version_id for run in changed} == {v.version_id for v in MODELS}
    runs = consumer.runs(conversion)
    assert credit(runs[LINEAR.version_id]) == [
        ("tp-a", Fraction(1, 2), 5_000),
        ("tp-b", Fraction(1, 2), 5_000),
    ]
    for version in MODELS:
        assert runs[version.version_id].outcome == _fresh(log, conversion, [A, B], version).outcome
        assert runs[version.version_id].ledger_position == 3

    # Retrying the same receipts, or the whole journal, leaves every allocation unchanged.
    assert consumer.apply(journal) == ()
    assert consumer.apply(journal[2:]) == ()
    assert consumer.runs(conversion) == runs


def test_incremental_consumer_matches_fresh_calculation_after_every_record():
    log = [
        capture(),
        refund("refund-200", "200.00", effective=DAY, received=DAY),
        refund("refund-200", "200.00", effective=DAY, received=DAY + MICRO),  # redelivery
        *_tie_log()[2:],
        refund("refund-50", "50.00", effective=2 * DAY, received=11 * DAY),
        refund("refund-60", "60.00", effective=3 * DAY, received=12 * DAY),  # exceeds 50.00
    ]
    conversion, _ = sale_from(log[:1])
    consumer = IncrementalAttribution(MODELS)
    consumer.set_journey(AGENCY, CLIENT, PERSON, [A, B])
    consumer.register(conversion)
    nets = []
    for count in range(1, len(log) + 1):
        journal = ledger_feed(log[:count])
        consumer.apply(journal)
        consumer.apply(journal)  # a repeated notification
        for version in MODELS:
            current = consumer.runs(conversion)[version.version_id]
            assert current.outcome == _fresh(log[:count], conversion, [A, B], version).outcome
            assert_balanced(current)
        nets.append(consumer.net(conversion).minor)
    assert nets == [100_000, 80_000, 80_000, 10_000, 5_000, 5_000]


def test_checkpoint_advances_only_after_the_allocation_commit():
    log = _tie_log()
    conversion, _ = sale_from(log)
    committed = []
    failures = iter([True])

    def commit(runs):
        if next(failures, False):
            raise RuntimeError("synthetic write failure")
        committed.append(runs)

    consumer = IncrementalAttribution([LINEAR], commit=commit)
    consumer.set_journey(AGENCY, CLIENT, PERSON, [A, B])
    with pytest.raises(RuntimeError):
        consumer.register(conversion)
    assert consumer.runs(conversion) == {}
    consumer.register(conversion)
    assert consumer.runs(conversion)[LINEAR.version_id].status is RunStatus.NO_VERIFIED_REVENUE

    journal = ledger_feed(log)
    consumer.apply(journal[:2])
    failures = iter([True])
    with pytest.raises(RuntimeError):
        consumer.apply(journal)
    assert consumer.checkpoint == 2
    assert consumer.net(conversion) == Money(80_000, AAA)
    assert credit(consumer.runs(conversion)[LINEAR.version_id])[0][2] == 40_000

    consumer.apply(journal)  # the retry applies receipt 3 (movements 3 and 4) once
    assert consumer.checkpoint == 3
    assert consumer.net(conversion) == Money(10_000, AAA)
    revisions = consumer.history.revisions(conversion, LINEAR)
    # Receipts 1 and 2 arrived in one page and still keep a revision each (R008-04).
    assert [r.revision for r in revisions] == [1, 2, 3, 4]
    assert [r.verified_net and r.verified_net.minor for r in revisions] == [
        None,
        100_000,
        80_000,
        10_000,
    ]
    assert [r.ledger_position for r in revisions] == [0, 1, 2, 3]
    assert [r.causes for r in revisions] == [
        (RevisionCause.INITIAL,),
        (RevisionCause.REVENUE_CHANGED,),
        (RevisionCause.REVENUE_CHANGED,),
        (RevisionCause.REVENUE_CHANGED,),
    ]
    assert revisions[0].eligible_ids == revisions[3].eligible_ids == ("tp-a", "tp-b")
    assert len(committed) == 3


def test_a_journal_gap_is_refused_without_any_change():
    journal = ledger_feed(_tie_log())
    consumer = IncrementalAttribution([LINEAR])
    consumer.apply(journal[:1])
    with pytest.raises(AttributionInputError) as error:
        consumer.apply(journal[2:])
    assert error.value.code == "journal_gap"
    assert consumer.checkpoint == 1


def test_a_closing_state_that_disagrees_with_its_movements_is_refused():
    log = _tie_log()
    conversion, _ = sale_from(log)
    journal = ledger_feed(log)
    closing = journal[1]
    assert closing.sales[0].net_minor == 80_000
    forged = replace(closing, sales=(replace(closing.sales[0], net_minor=90_000),))
    consumer = IncrementalAttribution([LINEAR])
    consumer.set_journey(AGENCY, CLIENT, PERSON, [A, B])
    consumer.register(conversion)
    consumer.apply(journal[:1])
    with pytest.raises(AttributionInputError) as error:
        consumer.apply([forged])
    assert error.value.code == "journal_mismatch"
    assert (consumer.checkpoint, consumer.net(conversion)) == (1, Money(100_000, AAA))
    unmoved = replace(closing, sales=())  # the moved transaction has no closing state
    with pytest.raises(AttributionInputError) as error:
        consumer.apply([unmoved])
    assert error.value.code == "journal_mismatch"
    consumer.apply(journal)
    assert consumer.net(conversion) == Money(10_000, AAA)


def test_journal_items_and_feeds_are_validated():
    journal = ledger_feed(_tie_log())
    for change in (
        {"index": 3},
        {"receipt": 0},
        {"sales": journal[1].sales, "index": 1, "count": 2},
    ):
        with pytest.raises(AttributionInputError) as error:
            replace(journal[1], **change)
        assert error.value.code == "invalid_journal_item"
    late_first = [replace(_tie_log()[0], received_at=T0 + 11 * DAY), *_tie_log()[1:]]
    with pytest.raises(AttributionInputError) as error:
        ledger_feed(late_first)
    assert error.value.code == "receipt_log_out_of_order"


# Revisions and evidence.


def test_late_touch_creates_a_revision_that_explains_the_difference():
    history = AttributionHistory()
    conversion, ledger = sale_from([capture("100.00")])
    sale = sale_state(ledger, conversion)
    first = history.calculate(conversion, [A], LAST, sale=sale)
    assert (first.revision, first.causes) == (1, (RevisionCause.INITIAL,))
    assert credit(first) == [("tp-a", 1, 10_000)]
    assert history.calculate(conversion, [A], LAST, sale=sale) is first

    second = history.calculate(conversion, [A, B], LAST, sale=sale)
    assert (second.revision, second.causes) == (2, (RevisionCause.TOUCHES_CHANGED,))
    assert credit(second) == [("tp-b", 1, 10_000)]
    assert [(d.touchpoint_id, d.delta_share, d.delta_minor) for d in second.differences] == [
        ("tp-b", 1, 10_000),
        ("tp-a", -1, -10_000),
    ]
    assert history.calculate(conversion, [B, A, A], LAST, sale=sale) is second
    assert history.revisions(conversion, LAST) == (first, second)

    # A touch received late but outside the window, or after the sale, changes no credit. The
    # current view lists it as excluded (R008-06): a revision with a cause and no differences.
    late = [A, B, touch("tp-old", T0 - 31 * DAY), touch("tp-after", T0 + DAY)]
    third = history.calculate(conversion, late, LAST, sale=sale)
    assert (third.revision, third.causes, third.differences) == (
        3,
        (RevisionCause.TOUCHES_CHANGED,),
        (),
    )
    assert credit(third) == credit(second)
    assert excluded(third) == {
        "tp-old": ExclusionReason.BEFORE_WINDOW,
        "tp-after": ExclusionReason.AFTER_CONVERSION,
    }
    assert history.calculate(conversion, late, LAST, sale=sale) is third


def test_a_changed_model_version_keeps_the_earlier_history():
    history = AttributionHistory()
    conversion, ledger = sale_from([capture("100.00")])
    sale = sale_state(ledger, conversion)
    touches = [touch("tp-old", T0 - 10 * DAY), B]
    v1 = history.calculate(conversion, touches, FIRST, sale=sale)
    week = ModelVersion("first-click.v2", AttributionModel.FIRST_CLICK, window=7 * DAY)
    v2 = history.calculate(conversion, touches, week, sale=sale)
    assert credit(v1) == [("tp-old", 1, 10_000)]
    assert credit(v2) == [("tp-b", 1, 10_000)]
    assert (v1.revision, v2.revision) == (1, 1)
    assert history.revisions(conversion, FIRST) == (v1,)
    assert history.revisions(conversion, week) == (v2,)
    with pytest.raises(AttributionInputError) as error:
        attribute(conversion, touches, week, sale=sale, previous=v1)
    assert error.value.code == "revision_mismatch"


def test_full_refund_revises_every_allocation_to_zero():
    consumer = IncrementalAttribution(MODELS)
    log = [capture()]
    conversion, _ = sale_from(log)
    consumer.set_journey(AGENCY, CLIENT, PERSON, [A, B])
    consumer.register(conversion)
    consumer.apply(ledger_feed(log))
    log.append(refund("refund-all", "1000.00", effective=DAY))
    consumer.apply(ledger_feed(log))
    linear = consumer.runs(conversion)[LINEAR.version_id]
    assert credit(linear) == [("tp-a", Fraction(1, 2), 0), ("tp-b", Fraction(1, 2), 0)]
    assert linear.causes == (RevisionCause.REVENUE_CHANGED,)
    assert [d.delta_minor for d in linear.differences] == [-50_000, -50_000]
    assert_balanced(linear)


def test_withdrawal_and_ownership_correction_remove_matched_touches():
    consumer = IncrementalAttribution([LINEAR])
    log = [capture("100.00")]
    conversion, _ = sale_from(log)
    consumer.set_journey(AGENCY, CLIENT, PERSON, [A, B])
    consumer.register(conversion)
    consumer.apply(ledger_feed(log))
    assert [m for _, _, m in credit(consumer.runs(conversion)[LINEAR.version_id])] == [5_000] * 2

    consumer.set_journey(AGENCY, CLIENT, PERSON, [A, replace(B, consent=ConsentState.WITHDRAWN)])
    withdrawn = consumer.runs(conversion)[LINEAR.version_id]
    assert credit(withdrawn) == [("tp-a", 1, 10_000)]
    assert excluded(withdrawn) == {"tp-b": ExclusionReason.CONSENT_NOT_GRANTED}
    assert [(d.touchpoint_id, d.delta_minor) for d in withdrawn.differences] == [
        ("tp-a", 5_000),
        ("tp-b", -5_000),
    ]

    corrected = replace(A, association=Association.EXCLUDED)
    consumer.set_journey(
        AGENCY, CLIENT, PERSON, [corrected, replace(B, consent=ConsentState.WITHDRAWN)]
    )
    final = consumer.runs(conversion)[LINEAR.version_id]
    assert credit(final) == [("unknown", 1, 10_000)]
    assert final.basis is CreditBasis.UNKNOWN_FALLBACK
    assert [r.revision for r in consumer.history.revisions(conversion, LINEAR)] == [1, 2, 3, 4]
    with pytest.raises(AttributionInputError) as error:
        consumer.set_journey(AGENCY, CLIENT_2, PERSON, [A])
    assert error.value.code == "journey_scope_mismatch"


def test_identical_inputs_reproduce_identical_runs():
    log = [capture(), refund("refund-200", "200.00", effective=DAY)]
    for version in MODELS:
        assert run_sale(log, [A, B], version) == run_sale(list(log), [B, A], version)
        assert attribute(lead(), [A, B], version) == attribute(lead(), [B, A], version)


def test_contract_inputs_are_validated():
    with pytest.raises(AttributionInputError) as error:
        ModelVersion("v", AttributionModel.LINEAR, window=timedelta(0))
    assert error.value.code == "invalid_window"
    with pytest.raises(AttributionInputError) as error:
        touch("tp", T0, source="instagram")  # a campaign interaction without a reference
    assert error.value.code == "campaign_reference_required"
    with pytest.raises(AttributionInputError) as error:
        touch("tp", T0, EvidenceClass.DIRECT_VISIT, link_ref="link-1")
    assert error.value.code == "direct_visit_has_campaign"
    with pytest.raises(AttributionInputError) as error:
        touch("tp", datetime(2026, 11, 1, 9, 0))
    assert error.value.code == "invalid_occurred_at"
    with pytest.raises(AttributionInputError) as error:
        Conversion("c", AGENCY, CLIENT, PERSON, ConversionKind.SALE, T0)
    assert error.value.code == "invalid_source_account"
    with pytest.raises(AttributionInputError) as error:
        attribute(
            lead(), [A], LINEAR, previous=attribute(lead(conversion_id="lead-2"), [A], LINEAR)
        )
    assert error.value.code == "revision_mismatch"
    with pytest.raises(AttributionInputError) as error:
        IncrementalAttribution([LINEAR, LINEAR])
    assert error.value.code == "duplicate_model_version"
