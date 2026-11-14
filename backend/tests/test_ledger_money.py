"""Minor units, exchange-rate snapshots and explicit conversion (specification 007-A, D-043).

Synthetic currencies and synthetic rate snapshots only; no exchange-rate source is contacted.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ledger import (
    ConversionStatus,
    Currency,
    FxRateSnapshot,
    LedgerInputError,
    Money,
    convert,
)

AAA = Currency("AAA", 2)
BBB = Currency("BBB", 2)
CCC = Currency("CCC", 0)
DDD = Currency("DDD", 3)
EEE = Currency("EEE", 2)
AS_OF = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def quote(
    base: Currency,
    target: Currency,
    rate: str,
    *,
    age: timedelta = timedelta(hours=1),
    snapshot_id: str = "fx-synthetic-1",
) -> FxRateSnapshot:
    return FxRateSnapshot(
        snapshot_id, base, target, Decimal(rate), AS_OF - age, "synthetic-fixture"
    )


def code_of(callable_, *args, **kwargs) -> str:
    with pytest.raises(LedgerInputError) as raised:
        callable_(*args, **kwargs)
    return raised.value.code


@pytest.mark.parametrize(
    ("text", "currency", "minor"),
    [
        ("1000.00", AAA, 100_000),
        ("0.5", AAA, 50),
        ("-200.00", AAA, -20_000),
        ("7", CCC, 7),
        ("1.234", DDD, 1_234),
    ],
)
def test_parse_reads_decimal_text_exactly(text, currency, minor):
    assert Money.parse(text, currency) == Money(minor, currency)


@pytest.mark.parametrize(
    ("text", "currency"),
    [("10.005", AAA), ("1.5", CCC), ("1e3", AAA), ("1,000.00", AAA), (" 1.00", AAA), ("", AAA)],
)
def test_parse_refuses_values_it_would_have_to_round_or_guess(text, currency):
    assert code_of(Money.parse, text, currency) == "invalid_amount"


def test_amounts_are_integers_and_never_float():
    assert code_of(Money, 10.0, AAA) == "invalid_amount"
    assert code_of(Money, True, AAA) == "invalid_amount"
    assert code_of(Money, Decimal("10"), AAA) == "invalid_amount"
    assert code_of(Money, 10**30, AAA) == "invalid_amount"
    assert code_of(Money.parse, 10.5, AAA) == "invalid_amount"
    assert str(Money(-20_000, AAA)) == "-200.00 AAA"
    assert str(Money(7, CCC)) == "7 CCC"


def test_different_currencies_are_never_added():
    assert Money(1, AAA) + Money(2, AAA) == Money(3, AAA)
    assert code_of(lambda: Money(1, AAA) + Money(1, BBB)) == "currency_mismatch"
    assert code_of(lambda: Money(1, AAA) + Money(1, Currency("AAA", 3))) == "currency_mismatch"


@pytest.mark.parametrize(
    ("code", "exponent", "reason"),
    [
        ("aaa", 2, "invalid_currency"),
        ("AAAA", 2, "invalid_currency"),
        ("AA1", 2, "invalid_currency"),
        ("AAA", 9, "invalid_exponent"),
        ("AAA", -1, "invalid_exponent"),
        ("AAA", True, "invalid_exponent"),
    ],
)
def test_currency_requires_code_and_explicit_exponent(code, exponent, reason):
    assert code_of(Currency, code, exponent) == reason


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"rate": 2.0}, "invalid_rate"),
        ({"rate": Decimal("0")}, "invalid_rate"),
        ({"rate": Decimal("-2")}, "invalid_rate"),
        ({"rate": Decimal("NaN")}, "invalid_rate"),
        ({"rate": Decimal("Infinity")}, "invalid_rate"),
        ({"rate": Decimal("1." + "1" * 40)}, "invalid_rate"),
        ({"quote": AAA}, "invalid_currency_pair"),
        ({"effective_at": datetime(2026, 11, 14)}, "invalid_snapshot_time"),
        ({"source": ""}, "invalid_snapshot_source"),
        ({"snapshot_id": ""}, "invalid_snapshot"),
        ({"direction": "base_per_quote"}, "unsupported_direction"),
        ({"rounding": "half_up"}, "unsupported_rounding"),
    ],
)
def test_snapshot_records_exact_rate_pair_direction_time_source_and_rounding(changes, reason):
    fields = {
        "snapshot_id": "fx-synthetic-1",
        "base": AAA,
        "quote": BBB,
        "rate": Decimal("2"),
        "effective_at": AS_OF,
        "source": "synthetic-fixture",
    }
    fields.update(changes)
    assert code_of(FxRateSnapshot, **fields) == reason


@pytest.mark.parametrize(
    ("minor", "rate", "expected"),
    [
        (1, "1.5", 2),  # 1.5 -> 2
        (3, "1.5", 4),  # 4.5 -> 4
        (5, "1.5", 8),  # 7.5 -> 8
        (5, "0.5", 2),  # 2.5 -> 2
        (7, "0.5", 4),  # 3.5 -> 4
        (-3, "1.5", -4),  # -4.5 -> -4
        (10, "1.26", 13),  # 12.6 -> 13
    ],
)
def test_conversion_rounds_half_even(minor, rate, expected):
    conversion = convert(
        [Money(minor, AAA)], BBB, [quote(AAA, BBB, rate)], as_of=AS_OF, max_age=DAY
    )
    assert conversion.amount == Money(expected, BBB)


def test_conversion_scales_between_exponents():
    to_whole = quote(AAA, CCC, "1")
    assert convert([Money(1_050, AAA)], CCC, [to_whole], as_of=AS_OF, max_age=DAY).amount == Money(
        10, CCC
    )
    assert convert([Money(1_150, AAA)], CCC, [to_whole], as_of=AS_OF, max_age=DAY).amount == Money(
        12, CCC
    )
    to_three = quote(AAA, DDD, "1.2345")
    result = convert([Money(1, AAA)], DDD, [to_three], as_of=AS_OF, max_age=DAY)
    assert result.components[0].exact_minor == Decimal("12.345")
    assert result.amount == Money(12, DDD)


def test_conversion_rounds_the_combined_total_once():
    result = convert(
        [Money(3, AAA), Money(3, EEE)],
        BBB,
        [quote(AAA, BBB, "1.5"), quote(EEE, BBB, "1.5", snapshot_id="fx-synthetic-2")],
        as_of=AS_OF,
        max_age=DAY,
    )
    assert [c.exact_minor for c in result.components] == [Decimal("4.5"), Decimal("4.5")]
    assert result.amount == Money(9, BBB)  # rounding each component first would give 8


def test_conversion_uses_only_the_recorded_direction_and_usable_time():
    inverse = quote(BBB, AAA, "0.5")
    future = quote(AAA, BBB, "2", age=-timedelta(minutes=1))
    result = convert([Money(100, AAA)], BBB, [inverse, future], as_of=AS_OF, max_age=DAY)
    assert result.amount is None
    assert result.components[0].status is ConversionStatus.MISSING


def test_conversion_selects_the_latest_usable_snapshot():
    older = quote(AAA, BBB, "2", age=timedelta(hours=3), snapshot_id="fx-synthetic-old")
    newer = quote(AAA, BBB, "3", age=timedelta(hours=1), snapshot_id="fx-synthetic-new")
    result = convert([Money(100, AAA)], BBB, [newer, older], as_of=AS_OF, max_age=DAY)
    assert result.components[0].snapshot is newer
    assert result.amount == Money(300, BBB)


def test_conflicting_snapshots_make_the_total_unavailable():
    one = quote(AAA, BBB, "2", snapshot_id="fx-synthetic-1")
    other = quote(AAA, BBB, "2.1", snapshot_id="fx-synthetic-2")
    same = quote(AAA, BBB, "2.0", snapshot_id="fx-synthetic-3")
    conflicting = convert([Money(100, AAA)], BBB, [one, other], as_of=AS_OF, max_age=DAY)
    assert (conflicting.amount, conflicting.components[0].status) == (
        None,
        ConversionStatus.CONFLICTING,
    )
    agreeing = convert([Money(100, AAA)], BBB, [same, one], as_of=AS_OF, max_age=DAY)
    assert agreeing.components[0].snapshot is one
    assert agreeing.amount == Money(200, BBB)


def test_max_age_boundary():
    at_limit = quote(AAA, BBB, "2", age=DAY)
    beyond = quote(AAA, BBB, "2", age=DAY + timedelta(seconds=1))
    assert convert([Money(1, AAA)], BBB, [at_limit], as_of=AS_OF, max_age=DAY).available
    stale = convert([Money(1, AAA)], BBB, [beyond], as_of=AS_OF, max_age=DAY)
    assert stale.components[0].status is ConversionStatus.STALE


def test_amounts_in_one_currency_are_combined_before_conversion():
    result = convert(
        [Money(1, AAA), Money(2, AAA), Money(5, BBB)],
        BBB,
        [quote(AAA, BBB, "1.5")],
        as_of=AS_OF,
        max_age=DAY,
    )
    assert result.originals == (Money(3, AAA), Money(5, BBB))
    assert result.amount == Money(10, BBB)  # 4.5 + 5 = 9.5 -> 10


def test_conversion_rejects_malformed_requests():
    snapshot = quote(AAA, BBB, "2")
    assert code_of(convert, [1], BBB, [snapshot], as_of=AS_OF, max_age=DAY) == "invalid_amount"
    assert code_of(convert, [], "BBB", [snapshot], as_of=AS_OF, max_age=DAY) == "invalid_currency"
    assert code_of(convert, [], BBB, [object()], as_of=AS_OF, max_age=DAY) == "invalid_snapshot"
    assert (
        code_of(convert, [], BBB, [], as_of=datetime(2026, 11, 14), max_age=DAY) == "invalid_as_of"
    )
    assert code_of(convert, [], BBB, [], as_of=AS_OF, max_age=-DAY) == "invalid_max_age"
    assert (
        code_of(convert, [Money(1, Currency("AAA", 3))], BBB, [snapshot], as_of=AS_OF, max_age=DAY)
        == "currency_exponent_conflict"
    )
