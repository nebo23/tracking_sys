"""Regressions for the pre-PR review findings R008-01 to R008-12 (specification 008-A).

Each case uses public attribution entry points, synthetic journeys and the real 007-A ledger.
The module imports only names that already existed in the reviewed commit 3d772d1; the
corrected interfaces (ledger_feed, sale_state, SaleState) are reached through the adapter
below, so every case can be run against that commit to demonstrate its failure. The adapter
delivers raw movements there and receipt journal items after the correction; the cut points of
a page split refer to whichever units the build delivers.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from fractions import Fraction
from itertools import combinations
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

import app.attribution as attribution
from app.attribution import (
    Association,
    AttributionHistory,
    AttributionInputError,
    AttributionModel,
    Conversion,
    ConversionKind,
    EvidenceClass,
    ExclusionReason,
    IncrementalAttribution,
    ModelVersion,
    RevisionCause,
    Touchpoint,
    attribute,
    sale_conversion,
)
from app.ledger import Currency, Evidence, LedgerScope, Money, OperationKind, calculate
from app.ledger import EvidenceClass as LedgerClass
from app.ledger.money import MAX_MINOR
from app.privacy.consent import ConsentState

CORRECTED = hasattr(attribution, "ledger_feed")

AGENCY = UUID("00000000-0000-4000-8000-00000000a001")
CLIENT = UUID("00000000-0000-4000-8000-00000000c001")
ACCOUNT = "acct-synthetic-1"
ACCOUNT_2 = "acct-synthetic-2"
PERSON = "person-synthetic-1"
PERSON_2 = "person-synthetic-2"
AAA = Currency("AAA", 2)
BBB = Currency("BBB", 3)
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)

FIRST = ModelVersion("first-click.v1", AttributionModel.FIRST_CLICK)
LAST = ModelVersion("last-click.v1", AttributionModel.LAST_CLICK)
LINEAR = ModelVersion("linear.v1", AttributionModel.LINEAR)
MODELS = (FIRST, LAST, LINEAR)
AUDIT = {
    "actor": "reviewer-synthetic-1",
    "reason": "Synthetic reconciliation outcome",
    "source_reference": "statement-synthetic-7",
}


def touch(touchpoint_id, occurred_at, *, person=PERSON, campaign=None, **extra) -> Touchpoint:
    campaign = campaign or touchpoint_id
    fields = {
        "source": "instagram",
        "campaign_ref": f"campaign-{campaign}",
        "content_ref": f"post-{campaign}",
        "link_ref": f"link-{campaign}",
        "association": Association.ASSIGNED,
        "consent": ConsentState.GRANTED,
    }
    fields.update(extra)
    return Touchpoint(
        touchpoint_id,
        AGENCY,
        CLIENT,
        person,
        EvidenceClass.CAMPAIGN_INTERACTION,
        occurred_at,
        **fields,
    )


A = touch("tp-a", T0 - 3 * DAY)
B = touch("tp-b", T0 - DAY)


def ledger_record(
    operation_id: str,
    amount: str | Money,
    kind: OperationKind = OperationKind.SALE,
    *,
    parent: str | None = None,
    classification: LedgerClass | None = None,
    delivery: str | None = None,
    effective: timedelta = timedelta(0),
    received: timedelta | None = None,
    account: str = ACCOUNT,
    **extra,
) -> Evidence:
    if classification is None:
        classification = {
            OperationKind.SALE: LedgerClass.CONFIRMED_CAPTURE,
            OperationKind.CORRECTION: LedgerClass.AUDITED_CORRECTION,
        }.get(kind, LedgerClass.CONFIRMED_ADJUSTMENT)
    if kind is OperationKind.CORRECTION:
        extra = {**AUDIT, **extra}
    return Evidence(
        delivery_id=delivery or f"dlv-{operation_id}",
        agency_id=AGENCY,
        client_id=CLIENT,
        source_account_id=account,
        operation_id=operation_id,
        kind=kind,
        classification=classification,
        amount=amount if isinstance(amount, Money) else Money.parse(amount, AAA),
        effective_at=T0 + effective,
        received_at=T0 + (received if received is not None else effective),
        parent_operation_id=parent,
        **extra,
    )


def capture(amount="100.00", **extra) -> Evidence:
    return ledger_record("sale-1", amount, **extra)


def adjustment(kind, operation_id, amount, parent="sale-1", **extra) -> Evidence:
    return ledger_record(operation_id, amount, kind, parent=parent, **extra)


def sale_of(log, *, conversion_id="conv-sale-1", person=PERSON, account=ACCOUNT) -> Conversion:
    scope = LedgerScope(AGENCY, CLIENT, account)
    transaction = next(
        t for t in calculate(log).transactions if t.scope == scope and t.operation_id == "sale-1"
    )
    return sale_conversion(transaction, conversion_id=conversion_id, person_id=person)


def lead(effective_at=T0, conversion_id="lead-1") -> Conversion:
    return Conversion(conversion_id, AGENCY, CLIENT, PERSON, ConversionKind.LEAD, effective_at)


# Adapter between the reviewed and the corrected interfaces.


def snapshot(log, conversion) -> dict:
    """The financial input of one conversion after the whole log, at its receipt position."""
    ledger = calculate(log)
    if CORRECTED:
        return {"sale": attribution.sale_state(ledger, conversion), "ledger_position": len(log)}
    return {
        "verified_net": attribution.verified_net(ledger, conversion),
        "ledger_position": len(log),
    }


def money_input(conversion, money: Money, position=None) -> dict:
    if CORRECTED:
        state = attribution.SaleState(
            *conversion.ledger_key, money.currency, conversion.effective_at, money.minor
        )
        return {"sale": state, "ledger_position": position}
    return {"verified_net": money, "ledger_position": position}


def fresh(log, conversion, touches, version):
    return attribute(conversion, touches, version, **snapshot(log, conversion))


def units(log) -> tuple:
    return attribution.ledger_feed(log) if CORRECTED else calculate(log).movements


def pages(sequence, cuts) -> list:
    bounds = [0, *cuts, len(sequence)]
    return [sequence[a:b] for a, b in zip(bounds, bounds[1:], strict=False)]


def deliver(consumer, log, cuts=()) -> None:
    for page in pages(units(log), cuts):
        consumer.apply(page)


def eligible_ids(run) -> tuple:
    return tuple(getattr(t, "touchpoint_id", t) for t in run.eligible)


def credit(run) -> list[tuple]:
    return [
        (
            a.touch.touchpoint_id if a.touch else a.recipient.value,
            a.share,
            a.amount and a.amount.minor,
        )
        for a in run.allocations
    ]


def excluded(run) -> dict:
    return {item.touchpoint_id: item.reason for item in run.excluded}


def view(run) -> tuple:
    """The current view of a run, independent of how its revisions were reached."""
    net = run.verified_net.minor if run.verified_net else None
    return (run.status.value, net, run.window_end, credit(run), sorted(excluded(run).items()))


def campaign_report(revisions) -> tuple[dict, dict]:
    """Per-campaign shares and minor units rebuilt by a downstream report: the allocations of
    revision 1, then the signed differences of every later revision."""
    shares: dict = {}
    amounts: dict = {}

    def book(key, share, minor):
        shares[key] = shares.get(key, 0) + share
        amounts[key] = amounts.get(key, 0) + minor

    for allocation in revisions[0].allocations:
        campaign = allocation.touch.campaign_ref if allocation.touch else None
        minor = allocation.amount.minor if allocation.amount else 0
        book((allocation.recipient.value, campaign), allocation.share, minor)
    for run in revisions[1:]:
        for d in run.differences:
            book(
                (d.recipient.value, getattr(d, "campaign_ref", None)), d.delta_share, d.delta_minor
            )
    return (
        {k: v for k, v in shares.items() if v},
        {k: v for k, v in amounts.items() if v},
    )


def expected_report(run) -> tuple[dict, dict]:
    return campaign_report((run,))


def consumer_for(touches_by_person, *versions, **extra):
    consumer = IncrementalAttribution(versions or MODELS, **extra)
    for person, touches in touches_by_person.items():
        consumer.set_journey(AGENCY, CLIENT, person, touches)
    return consumer


# R008-01: one scoped sale contributes once per model.


def test_r008_01_one_scoped_sale_is_credited_once_per_model():
    log = [capture("100.00"), capture("70.00", account=ACCOUNT_2, delivery="dlv-acct-2")]
    first = sale_of(log, conversion_id="conv-1")
    other_person = sale_of(log, conversion_id="conv-2", person=PERSON_2)
    same_person = sale_of(log, conversion_id="conv-3")
    elsewhere = sale_of(log, conversion_id="conv-4", person=PERSON_2, account=ACCOUNT_2)
    consumer = consumer_for({PERSON: [A], PERSON_2: [touch("tp-c", T0 - DAY, person=PERSON_2)]})

    consumer.register(first)
    with pytest.raises(AttributionInputError) as error:
        consumer.register(other_person)
    assert error.value.code == "sale_association_conflict"
    with pytest.raises(AttributionInputError) as error:
        consumer.register(same_person)
    assert error.value.code == "sale_already_registered"
    assert consumer.register(first) == ()  # a genuine retry is idempotent
    consumer.register(elsewhere)  # the same sale reference in another source account
    deliver(consumer, log)

    for version in MODELS:  # 100.00 once in the first account, 70.00 in the other
        assert consumer.history.latest(first, version).credited_minor == 10_000
        assert consumer.history.latest(elsewhere, version).credited_minor == 7_000

    history = AttributionHistory()
    history.calculate(first, [A], LAST, **snapshot(log, first))
    with pytest.raises(AttributionInputError) as error:
        history.calculate(other_person, [A], LAST, **snapshot(log, other_person))
    assert error.value.code == "sale_association_conflict"


# R008-02: a corrected sale instant moves the window although no movement is emitted.


def test_r008_02_confirmed_capture_time_reanchors_the_sale():
    settlement = capture(
        classification=LedgerClass.CONFIRMED_SETTLEMENT,
        delivery="dlv-settle",
        effective=2 * DAY,  # Nov 3
        received=2 * DAY + HOUR,
    )
    confirmation = capture(delivery="dlv-capture", effective=timedelta(0), received=3 * DAY)
    log = [settlement, confirmation]
    assert len(calculate(log).movements) == len(calculate(log[:1]).movements) == 1
    nov2 = touch("tp-nov2", T0 + DAY)
    anchored = sale_of(log[:1])
    assert anchored.effective_at == T0 + 2 * DAY

    consumer = consumer_for({PERSON: [nov2]})
    consumer.register(anchored)
    deliver(consumer, log[:1])
    assert credit(consumer.runs(anchored)[LAST.version_id]) == [("tp-nov2", 1, 10_000)]

    deliver(consumer, log)  # the receipt journal carries the corrected sale instant
    assert credit(consumer.runs(anchored)[LAST.version_id]) == [("unknown", 1, 10_000)]
    assert consumer.runs(anchored)[LAST.version_id].window_end == T0
    corrected = sale_of(log)
    assert corrected.effective_at == T0
    assert consumer.register(corrected) == ()  # re-registering the corrected sale is accepted
    for version in MODELS:
        current = consumer.runs(corrected)[version.version_id]
        assert credit(current) == [("unknown", 1, 10_000)]
        assert excluded(current) == {"tp-nov2": ExclusionReason.AFTER_CONVERSION}
        assert current.window_end == T0
        assert view(current) == view(fresh(log, corrected, [nov2], version))
        revisions = consumer.history.revisions(corrected, version)
        assert credit(revisions[-2]) == [("tp-nov2", 1, 10_000)]
        assert revisions[-2].window_end == T0 + 2 * DAY
        assert getattr(RevisionCause, "SALE_TIME_CHANGED", None) in current.causes


# R008-03: an older financial position never supersedes a newer revision.


def test_r008_03_stale_snapshots_cannot_restore_an_earlier_balance():
    log = [capture("100.00"), adjustment(OperationKind.REFUND, "refund-20", "20.00", effective=DAY)]
    conversion = sale_of(log)
    history = AttributionHistory()
    history.calculate(conversion, [A, B], LINEAR, **snapshot(log[:1], conversion))
    history.calculate(conversion, [A, B], LINEAR, **snapshot(log, conversion))
    with pytest.raises(AttributionInputError) as error:
        history.calculate(conversion, [A, B], LINEAR, **snapshot(log[:1], conversion))
    assert error.value.code == "stale_ledger_position"
    assert history.latest(conversion, LINEAR).credited_minor == 8_000

    # A journey update at the same financial position is legitimate.
    journey = history.calculate(conversion, [A], LINEAR, **snapshot(log, conversion))
    assert credit(journey) == [("tp-a", 1, 8_000)]
    assert [r.credited_minor for r in history.revisions(conversion, LINEAR)] == [
        10_000,
        8_000,
        8_000,
    ]


def test_r008_03_a_consumer_on_a_populated_history_publishes_no_spurious_zero():
    log = [capture("100.00"), adjustment(OperationKind.REFUND, "refund-20", "20.00", effective=DAY)]
    conversion = sale_of(log)
    history = AttributionHistory()
    original = consumer_for({PERSON: [A, B]}, history=history)
    original.register(conversion)
    deliver(original, log)
    recorded = {v.version_id: history.revisions(conversion, v) for v in MODELS}

    restarted = consumer_for({PERSON: [A, B]}, history=history)
    assert restarted.register(conversion) == ()
    deliver(restarted, log)
    assert {v.version_id: history.revisions(conversion, v) for v in MODELS} == recorded
    assert [r.credited_minor for r in recorded[LINEAR.version_id]] == [0, 10_000, 8_000]
    assert restarted.runs(conversion) == original.runs(conversion)


# R008-04: distinct receipts keep their own revisions whatever the transport batching.


def test_r008_04_each_receipt_keeps_its_revision_in_one_batch():
    log = [
        capture("100.00"),
        adjustment(OperationKind.REFUND, "refund-20", "20.00", effective=DAY),
        adjustment(OperationKind.CORRECTION, "correction-20", "20.00", effective=2 * DAY),
    ]
    conversion = sale_of(log[:1])

    def history_of(cuts):
        consumer = consumer_for({PERSON: [A, B]}, LINEAR)
        consumer.register(conversion)
        deliver(consumer, log, cuts)
        revisions = consumer.history.revisions(conversion, LINEAR)
        return [
            (
                r.verified_net and r.verified_net.minor,
                [(d.touchpoint_id, d.delta_minor) for d in r.differences],
            )
            for r in revisions
        ], campaign_report(revisions)

    separate, separate_report = history_of((1, 2))
    for cuts in ((), (1,), (2,)):
        assert history_of(cuts) == (separate, separate_report)
    assert separate == [
        (None, []),
        (10_000, [("tp-a", 5_000), ("tp-b", 5_000)]),
        (8_000, [("tp-a", -1_000), ("tp-b", -1_000)]),
        (10_000, [("tp-a", 1_000), ("tp-b", 1_000)]),
    ]
    final = fresh(log, conversion, [A, B], LINEAR)
    assert separate_report == expected_report(final)


# R008-05: one receipt with two movements delivered across pages.


def test_r008_05_paged_receipt_converges_without_a_negative_balance():
    log = [
        capture("100.00"),
        adjustment(OperationKind.REFUND, "refund-100", "100.00", effective=DAY),
        adjustment(
            OperationKind.CHARGEBACK_REVERSAL,
            "reversal-1",
            "100.00",
            parent="chargeback-1",
            effective=3 * DAY,
        ),
        adjustment(
            OperationKind.CHARGEBACK, "chargeback-1", "100.00", effective=2 * DAY, received=4 * DAY
        ),
    ]
    journal = calculate(log).movements
    assert [(m.sequence, m.operation_id, m.amount.minor) for m in journal] == [
        (1, "sale-1", 10_000),
        (2, "refund-100", -10_000),
        (3, "chargeback-1", -10_000),
        (4, "reversal-1", 10_000),
    ]
    assert journal[2].trigger == journal[3].trigger == log[3]
    conversion = sale_of(log)
    sequence = units(log)
    expected = {v.version_id: view(fresh(log, conversion, [A, B], v)) for v in MODELS}

    for size in range(len(sequence)):
        for cuts in combinations(range(1, len(sequence)), size):
            published = []
            failing = [False]

            def commit(runs, failing=failing, published=published):
                if failing[0]:
                    failing[0] = False
                    raise RuntimeError("synthetic write failure")
                published.extend(runs)

            consumer = consumer_for({PERSON: [A, B]}, commit=commit)
            consumer.register(conversion)
            for page in pages(sequence, cuts):
                before = (consumer.checkpoint, consumer.runs(conversion))
                failing[0] = True
                try:
                    consumer.apply(page)
                except RuntimeError:
                    assert (consumer.checkpoint, consumer.runs(conversion)) == before
                    consumer.apply(page)
                failing[0] = False
                consumer.apply(page)  # a repeated notification
            assert consumer.checkpoint == 4
            assert getattr(consumer, "buffered", 0) == 0
            assert consumer.net(conversion) == Money(0, AAA)
            for run in published:
                assert all(a.amount is None or a.amount.minor >= 0 for a in run.allocations)
            for version in MODELS:
                assert (
                    view(consumer.runs(conversion)[version.version_id])
                    == expected[version.version_id]
                )


# R008-06: the current view follows consent and ownership even when credit is unchanged.


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"consent": ConsentState.WITHDRAWN}, ExclusionReason.CONSENT_NOT_GRANTED),
        ({"association": Association.EXCLUDED}, ExclusionReason.NOT_ASSIGNED),
    ],
)
def test_r008_06_a_non_winning_touch_leaves_the_current_view(change, reason):
    log = [capture("100.00")]
    conversion = sale_of(log)
    history = AttributionHistory()
    before = history.calculate(conversion, [A, B], FIRST, **snapshot(log, conversion))
    after = history.calculate(
        conversion, [A, replace(B, **change)], FIRST, **snapshot(log, conversion)
    )
    assert credit(after) == credit(before) == [("tp-a", 1, 10_000)]
    assert after is not before and after.revision == 2
    assert excluded(after) == {"tp-b": reason}
    assert eligible_ids(after) == ("tp-a",)
    assert eligible_ids(history.revisions(conversion, FIRST)[0]) == ("tp-a", "tp-b")
    assert view(after) == view(fresh(log, conversion, [A, replace(B, **change)], FIRST))
    assert after.differences == ()
    assert RevisionCause.TOUCHES_CHANGED in after.causes


# R008-07: a reassigned touch moves its credit between campaigns in the differences.


def test_r008_07_reassigned_campaign_transfers_credit_in_the_differences():
    log = [capture("100.00")]
    conversion = sale_of(log)
    reassigned = touch("tp-a", A.occurred_at, campaign="c")
    for subject, version, unit in ((conversion, LAST, 10_000), (lead(), LINEAR, None)):
        history = AttributionHistory()
        money = snapshot(log, subject) if subject.kind is ConversionKind.SALE else {}
        history.calculate(subject, [A], version, **money)
        revised = history.calculate(subject, [reassigned], version, **money)
        assert revised.revision == 2 and revised.causes
        assert credit(revised)[0][0] == "tp-a"
        assert revised.allocations[0].touch.campaign_ref == "campaign-c"
        moved = {
            getattr(d, "campaign_ref", None): (d.delta_share, d.delta_minor)
            for d in revised.differences
        }
        assert moved == {
            "campaign-c": (1, unit or 0),
            "campaign-tp-a": (-1, -(unit or 0)),
        }
        assert {getattr(d, "content_ref", None) for d in revised.differences} == {
            "post-c",
            "post-tp-a",
        }
        assert campaign_report(history.revisions(subject, version)) == expected_report(revised)
    assert RevisionCause.EVIDENCE_CHANGED in revised.causes


# R008-08: identical copies coalesce; a mismatched replay differs from a gap.


def test_r008_08_identical_copies_within_one_delivery_coalesce():
    log = [capture("100.00")]
    conversion = sale_of(log)
    consumer = consumer_for({PERSON: [A]}, LAST)
    consumer.register(conversion)
    unit = units(log)[0]
    consumer.apply([unit, unit])
    assert consumer.net(conversion) == Money(10_000, AAA)
    assert credit(consumer.runs(conversion)[LAST.version_id]) == [("tp-a", 1, 10_000)]


def test_r008_08_mismatched_replay_and_gap_are_refused_without_change():
    log = [capture("100.00")]
    conversion = sale_of(log)
    consumer = consumer_for({PERSON: [A]}, LAST)
    consumer.register(conversion)
    deliver(consumer, log)
    state = (
        consumer.checkpoint,
        consumer.net(conversion),
        consumer.history.revisions(conversion, LAST),
    )

    other = [
        capture("90.00"),
        adjustment(OperationKind.REFUND, "refund-20", "20.00", effective=DAY),
    ]
    with pytest.raises(AttributionInputError) as error:
        consumer.apply(units(other))
    assert error.value.code == "journal_mismatch"
    assert (
        consumer.checkpoint,
        consumer.net(conversion),
        consumer.history.revisions(conversion, LAST),
    ) == state

    longer = [
        *log,
        adjustment(OperationKind.REFUND, "refund-20", "20.00", effective=DAY),
        adjustment(OperationKind.REFUND, "refund-30", "30.00", effective=2 * DAY),
    ]
    with pytest.raises(AttributionInputError) as error:
        consumer.apply(units(longer)[2:])
    assert error.value.code == "journal_gap"
    assert (
        consumer.checkpoint,
        consumer.net(conversion),
        consumer.history.revisions(conversion, LAST),
    ) == state
    deliver(consumer, longer)
    assert consumer.net(conversion) == Money(5_000, AAA)


# R008-09: history reads and writes validate the conversion and the model definition.


def test_r008_09_history_validates_conversions_and_model_definitions():
    log = [capture("100.00")]
    conversion = sale_of(log)
    history = AttributionHistory()
    run = history.calculate(conversion, [A], LAST, **snapshot(log, conversion))
    assert history.latest(conversion, LAST) is run
    impostor = Conversion(
        conversion.conversion_id,
        AGENCY,
        CLIENT,
        PERSON_2,
        ConversionKind.SALE,
        T0,
        ACCOUNT_2,
        "sale-9",
    )
    for read in (history.latest, history.revisions):
        with pytest.raises(AttributionInputError) as error:
            read(impostor, LAST)
        assert error.value.code == "conversion_mismatch"
    with pytest.raises(AttributionInputError) as error:
        history.calculate(impostor, [A], LAST)
    assert error.value.code == "conversion_mismatch"

    redefined = ModelVersion(LAST.version_id, AttributionModel.FIRST_CLICK)
    with pytest.raises(AttributionInputError) as error:
        history.latest(conversion, redefined)
    assert error.value.code == "model_version_conflict"
    with pytest.raises(AttributionInputError) as error:
        history.calculate(lead(), [A], redefined)  # the same ID for another conversion
    assert error.value.code == "model_version_conflict"
    assert history.calculate(lead(), [A], LAST).model_version == LAST
    assert history.revisions(conversion, LAST) == (run,)


# R008-10: exact accumulation with an unrepresentable intermediate receipt.


def test_r008_10_unrepresentable_intermediate_receipt_recovers():
    log = [
        ledger_record("sale-1", Money(MAX_MINOR - 1, AAA)),
        adjustment(OperationKind.CORRECTION, "correction-up", Money(1, AAA), effective=DAY),
        adjustment(OperationKind.CORRECTION, "correction-down", Money(-1, AAA), effective=2 * DAY),
    ]
    assert [m.amount.minor for m in calculate(log).movements] == [MAX_MINOR - 1, 1, -1]
    assert calculate(log).transactions[0].totals.net == MAX_MINOR - 1
    conversion = sale_of(log)
    consumer = consumer_for({PERSON: [A, B]}, LINEAR)
    consumer.register(conversion)
    deliver(consumer, log)
    current = consumer.runs(conversion)[LINEAR.version_id]
    assert consumer.checkpoint == 3
    assert current.credited_minor == MAX_MINOR - 1
    assert [a.amount.minor for a in current.allocations] == [MAX_MINOR // 2, MAX_MINOR // 2 - 1]
    assert view(current) == view(fresh(log, conversion, [A, B], LINEAR))
    statuses = [r.status.value for r in consumer.history.revisions(conversion, LINEAR)]
    assert statuses == ["no_verified_revenue", "complete", "net_out_of_range", "complete"]


# R008-11: evidence changes are compared as absolute instants.


def test_r008_11_corrected_repeated_local_hour_is_a_new_revision():
    new_york = ZoneInfo("America/New_York")
    earlier = datetime(2026, 11, 1, 1, 30, tzinfo=new_york)  # 05:30 UTC
    later = earlier.replace(fold=1)  # 06:30 UTC
    history = AttributionHistory()
    first = history.calculate(lead(), [touch("tp-ny", earlier)], FIRST)
    revised = history.calculate(lead(), [touch("tp-ny", later)], FIRST)
    assert revised is not first and revised.revision == 2
    assert revised.allocations[0].touch.instant == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert getattr(RevisionCause, "EVIDENCE_CHANGED", None) in revised.causes
    same_instant = touch("tp-ny", datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
    assert history.calculate(lead(), [same_instant], FIRST) is revised


# R008-12: a sale keeps its original currency and exponent.


def test_r008_12_currency_change_is_refused_before_a_revision():
    log = [capture("100.00")]
    conversion = sale_of(log)
    history = AttributionHistory()
    run = history.calculate(conversion, [A], LAST, **money_input(conversion, Money(10_000, AAA)))
    for currency in (BBB, Currency("AAA", 3)):
        with pytest.raises(AttributionInputError) as error:
            history.calculate(
                conversion, [A], LAST, **money_input(conversion, Money(10_000, currency))
            )
        assert error.value.code == "currency_changed"
    assert history.revisions(conversion, LAST) == (run,)


# Window boundary: timedelta.max and the earliest representable dates.


def test_window_boundary_at_the_earliest_representable_instant():
    earliest = datetime.min.replace(tzinfo=UTC)
    unlimited = ModelVersion("first-click.max", AttributionModel.FIRST_CLICK, window=timedelta.max)
    ancient = touch("tp-ancient", earliest)
    run = attribute(lead(), [ancient, A], unlimited)
    assert run.window_start == earliest
    assert credit(run) == [("tp-ancient", 1, None)]

    early = lead(earliest + DAY)
    near = attribute(early, [touch("tp-near", earliest + HOUR)], LINEAR)
    assert near.window_start == earliest
    assert credit(near) == [("tp-near", 1, None)]
    with pytest.raises(AttributionInputError) as error:
        touch("tp-offset", datetime(1, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=2))))
    assert error.value.code == "invalid_occurred_at"
    bounded = attribute(lead(), [touch("tp-edge", T0 - 30 * DAY), A], FIRST)
    assert credit(bounded) == [("tp-edge", 1, None)]
    assert bounded.window_start == T0 - 30 * DAY
    assert Fraction(run.credited_share) == 1
