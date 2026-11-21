"""Pure ROAS contract cases (specification 014-C, D-064 decision D11; T-40 to T-47).

Spend facts are built directly and credit comes from real 008-A runs over synthetic journeys
on real 007-A ledger transactions. No database and no network.
"""

from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from uuid import UUID

import pytest

from app.advertising.roas import Period, SpendFactView, roas_report
from app.attribution import (
    Association,
    AttributionInputError,
    AttributionModel,
    EvidenceClass,
    ModelVersion,
    Touchpoint,
    attribute,
    sale_conversion,
    sale_state,
)
from app.ledger import Currency, Evidence, Money, OperationKind, calculate
from app.ledger import EvidenceClass as LedgerClass
from app.privacy.consent import ConsentState

AGENCY, CLIENT, CONNECTION = UUID(int=1), UUID(int=2), UUID(int=3)
ZONE = "America/New_York"
PERIOD = Period(date(2026, 11, 1), date(2026, 11, 7))
AS_OF = datetime(2026, 12, 31, tzinfo=UTC)
COVERED = (date(2026, 10, 1), date(2026, 11, 30))
FIRST = ModelVersion("first-v1", AttributionModel.FIRST_CLICK)
LINEAR = ModelVersion("linear-v1", AttributionModel.LINEAR)
CAMPAIGN, ADSET, AD, OTHER_AD = "111", "211", "311", "321"


def _fact(day, minor=1000, *, ad=AD, currency="USD", refusal=None, provisional=None):
    return SpendFactView(
        ad,
        ADSET,
        CAMPAIGN,
        day,
        currency,
        None if refusal else minor,
        refusal,
        provisional or datetime(2026, 1, 1, tzinfo=UTC),
    )


def _touch(identifier, when, *, source="meta", campaign=CAMPAIGN, content=AD, person="p1"):
    return Touchpoint(
        identifier,
        AGENCY,
        CLIENT,
        person,
        EvidenceClass.CAMPAIGN_INTERACTION,
        when,
        Association.ASSIGNED,
        ConsentState.GRANTED,
        source,
        campaign,
        content,
    )


def _runs(sale_at, touches, version=FIRST, amount=5000, refund=0, currency="USD", operation="s1"):
    unit = Currency(currency, 2)
    records = [
        Evidence(
            f"d-{operation}",
            AGENCY,
            CLIENT,
            "acct",
            operation,
            OperationKind.SALE,
            LedgerClass.CONFIRMED_CAPTURE,
            Money(amount, unit),
            sale_at,
            sale_at,
        )
    ]
    if refund:
        records.append(
            Evidence(
                f"r-{operation}",
                AGENCY,
                CLIENT,
                "acct",
                f"refund-{operation}",
                OperationKind.REFUND,
                LedgerClass.CONFIRMED_ADJUSTMENT,
                Money(refund, unit),
                sale_at + timedelta(hours=1),
                sale_at + timedelta(hours=1),
                parent_operation_id=operation,
            )
        )
    ledger = calculate(records)
    (transaction,) = ledger.transactions
    conversion = sale_conversion(transaction, conversion_id=f"c-{operation}", person_id="p1")
    return attribute(conversion, touches, version, sale=sale_state(ledger, conversion))


def _report(facts, runs, version=FIRST, covered=COVERED, as_of=AS_OF):
    return roas_report(
        facts,
        runs,
        agency_id=AGENCY,
        client_id=CLIENT,
        connection_id=CONNECTION,
        period=PERIOD,
        zone=ZONE,
        model_version=version,
        as_of=as_of,
        covered=covered,
    )


def _rows(report, level):
    return {row.object_id: row for row in report.rows if row.level == level}


SALE = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
TOUCH = SALE - timedelta(days=2)


def test_rows_per_level_name_their_model_and_basis():
    # T-40: rows per ad, ad set and campaign, each naming model, version, window, period,
    # currency and basis; each model separately.
    facts = [_fact(PERIOD.since + timedelta(days=n)) for n in range(7)]
    for version in (FIRST, LINEAR):
        run = _runs(SALE, [_touch("t1", TOUCH)], version)
        report = _report(facts, [run], version)
        assert {row.level for row in report.rows} == {"ad", "adset", "campaign"}
        for row in report.rows:
            assert (row.model, row.model_version, row.window) == (
                version.model,
                version.version_id,
                timedelta(days=30),
            )
            assert (row.period, row.basis, row.currency) == (PERIOD, "conversion_date", "USD")
        ad = _rows(report, "ad")[AD]
        assert (ad.spend.minor, ad.credited.minor, ad.roas, ad.roas_text) == (
            7000,
            5000,
            Fraction(5, 7),
            "0.7143",
        )
        assert _rows(report, "campaign")[CAMPAIGN].roas == Fraction(5, 7)
    with pytest.raises(AttributionInputError) as raised:
        _report(facts, [_runs(SALE, [_touch("t1", TOUCH)], LINEAR)], FIRST)
    assert raised.value.code == "model_version_mismatch"


def test_zero_spend_has_no_value():
    # T-41: zero spend gives no value with zero_spend, never an infinite or very large number,
    # whether the ad had no spend facts or facts of zero.
    run = _runs(SALE, [_touch("t1", TOUCH)])
    objects = {AD: (CAMPAIGN, ADSET)}
    for facts in ([], [_fact(PERIOD.since, 0)]):
        report = roas_report(
            facts,
            [run],
            agency_id=AGENCY,
            client_id=CLIENT,
            connection_id=CONNECTION,
            period=PERIOD,
            zone=ZONE,
            model_version=FIRST,
            as_of=AS_OF,
            covered=COVERED,
            objects=objects,
        )
        for row in report.rows:
            assert (row.roas, row.roas_text, row.reason) == (None, None, "zero_spend")
            assert row.credited.minor == 5000


def test_spend_without_credit_gives_zero():
    # T-42: spend above zero with no credited revenue gives 0.
    row = _rows(_report([_fact(PERIOD.since)], []), "ad")[AD]
    assert (row.roas, row.roas_text, row.reason, row.credited.minor) == (
        Fraction(0),
        "0.0000",
        None,
        0,
    )


def test_currency_mismatch_has_no_value():
    # T-43: a currency mismatch gives no value; nothing is converted.
    run = _runs(SALE, [_touch("t1", TOUCH)], currency="EUR")
    row = _rows(_report([_fact(PERIOD.since)], [run]), "ad")[AD]
    assert (row.roas, row.reason, row.currency, row.spend, row.credited) == (
        None,
        "currency_mismatch",
        None,
        None,
        None,
    )
    mixed = [_fact(PERIOD.since), _fact(PERIOD.until, currency="EUR")]
    assert _rows(_report(mixed, []), "ad")[AD].reason == "currency_mismatch"


def test_provisional_and_incomplete_spend_is_marked():
    # T-44: provisional or incomplete spend days are marked on the row.
    late = datetime(2027, 1, 31, tzinfo=UTC)
    assert _rows(_report([_fact(PERIOD.since, provisional=late)], []), "ad")[AD].spend_state == (
        "provisional"
    )
    refused = [_fact(PERIOD.since), _fact(PERIOD.until, refusal="unparseable_amount")]
    assert _rows(_report(refused, []), "ad")[AD].spend_state == "incomplete"
    partial = (date(2026, 10, 1), date(2026, 11, 5))
    report = _report([_fact(PERIOD.since)], [], covered=partial)
    assert {row.spend_state for row in report.rows} == {"incomplete"}
    assert _rows(_report([_fact(PERIOD.since)], []), "ad")[AD].spend_state == "complete"


def test_unmatched_credit_is_reported_separately():
    # T-45: credit from touches without the URL convention, or for another account, is
    # reported as unmatched, never matched by name.
    runs = [
        _runs(SALE, [_touch("t1", TOUCH, source="facebook")], operation="s1"),
        _runs(SALE, [_touch("t2", TOUCH, content="999")], operation="s2"),
        _runs(SALE, [_touch("t3", TOUCH, campaign="112")], operation="s3"),
        _runs(SALE, [_touch("t4", TOUCH, campaign="Synthetic campaign")], operation="s4"),
    ]
    report = _report([_fact(PERIOD.since)], runs)
    assert _rows(report, "ad")[AD].credited.minor == 0
    assert [(item.minor, item.currency.code) for item in report.unmatched] == [(20000, "USD")]


def test_refund_lowers_the_credited_net():
    # T-46: a refund lowers the credited net through the 008-A revision.
    facts = [_fact(PERIOD.since, 10000)]
    before = _rows(_report(facts, [_runs(SALE, [_touch("t1", TOUCH)])]), "ad")[AD]
    after = _rows(_report(facts, [_runs(SALE, [_touch("t1", TOUCH)], refund=2000)]), "ad")[AD]
    assert (before.roas, after.roas) == (Fraction(1, 2), Fraction(3, 10))


def test_period_follows_the_account_zone():
    # T-47: a sale at 23:30 local time falls on the local date.
    late_local = datetime(2026, 11, 7, 23, 30, tzinfo=UTC) + timedelta(hours=5)  # EST
    early_next = datetime(2026, 11, 8, 4, 30, tzinfo=UTC) + timedelta(hours=1)  # 00:30 EST
    facts = [_fact(PERIOD.until)]
    inside = _rows(
        _report(facts, [_runs(late_local, [_touch("t1", late_local - timedelta(days=1))])]), "ad"
    )[AD]
    outside = _rows(
        _report(facts, [_runs(early_next, [_touch("t1", early_next - timedelta(days=1))])]), "ad"
    )[AD]
    assert (inside.credited.minor, outside.credited.minor) == (5000, 0)


def test_runs_of_another_client_are_refused():
    run = _runs(SALE, [_touch("t1", TOUCH)])
    with pytest.raises(AttributionInputError) as raised:
        roas_report(
            [],
            [run],
            agency_id=AGENCY,
            client_id=UUID(int=9),
            connection_id=CONNECTION,
            period=PERIOD,
            zone=ZONE,
            model_version=FIRST,
            as_of=AS_OF,
            covered=COVERED,
        )
    assert raised.value.code == "foreign_run"
