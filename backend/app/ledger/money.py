"""Currency amounts and exchange-rate snapshots for the revenue ledger (specification 007-A, D-043).

Amounts are integers in the minor unit of a currency with an explicit exponent (decision A2).
Nothing here uses floating point. Amounts in different currencies are never added together: a
combined figure exists only as an explicit conversion under recorded FxRateSnapshot evidence,
computed exactly and rounded once to the target currency with the half-even rule. Missing, stale
or conflicting conversion evidence makes the combined figure unavailable, while the original
amounts remain available. Failures raise LedgerInputError with a closed reason code and never
echo the rejected value.

Times are compared, ordered and subtracted as absolute UTC instants (utc_instant). Python
compares two aware datetimes that share one tzinfo object by wall-clock time and ignores fold,
which would misorder the two occurrences of a repeated local hour.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
)
from enum import StrEnum

MAX_EXPONENT = 8
MAX_MINOR = 10**30  # exclusive bound on the magnitude of one amount in minor units
MAX_RATE_DIGITS = 34
MAX_TEXT = 256
MAX_REASON = 1024
QUOTE_PER_BASE = "quote_per_base"
HALF_EVEN = "half_even"
_CODE = re.compile(r"[A-Z]{3}")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,8})?")
# Exact arithmetic: an operation that would need rounding raises instead of losing value.
_EXACT = Context(
    prec=200, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, Inexact, Overflow, DivisionByZero]
)
# The single documented rounding step of a conversion.
_ROUNDING = Context(prec=200, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, Overflow])


class LedgerInputError(ValueError):
    """A malformed ledger input; code is a closed reason, never the rejected value."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require_text(value: object, code: str, limit: int = MAX_TEXT) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or value != value.strip()
        or not value.isprintable()
    ):
        raise LedgerInputError(code)
    return value


def require_aware(value: object, code: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise LedgerInputError(code)
    return value


def utc_instant(value: datetime) -> datetime:
    """The absolute instant of an aware datetime, safe to compare whatever its tzinfo or fold."""
    return value.astimezone(UTC)


def register_currency(known: dict[str, int], currency: "Currency") -> None:
    """Refuse two exponents for one currency code within one conversion request."""
    if known.setdefault(currency.code, currency.exponent) != currency.exponent:
        raise LedgerInputError("currency_exponent_conflict")


@dataclass(frozen=True, slots=True, order=True)
class Currency:
    """An alphabetic currency code and its minor-unit exponent (2 means 1.00 is 100 units)."""

    code: str
    exponent: int

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not _CODE.fullmatch(self.code):
            raise LedgerInputError("invalid_currency")
        if type(self.exponent) is not int or not 0 <= self.exponent <= MAX_EXPONENT:
            raise LedgerInputError("invalid_exponent")


@dataclass(frozen=True, slots=True)
class Money:
    """A signed integer amount in the minor unit of one currency."""

    minor: int
    currency: Currency

    def __post_init__(self) -> None:
        if type(self.minor) is not int or abs(self.minor) >= MAX_MINOR:
            raise LedgerInputError("invalid_amount")
        if not isinstance(self.currency, Currency):
            raise LedgerInputError("invalid_currency")

    @classmethod
    def parse(cls, value: str, currency: Currency) -> "Money":
        """Read a decimal string such as "1000.00" exactly.

        A value with more fractional digits than the currency exponent is refused, not rounded.
        """
        if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
            raise LedgerInputError("invalid_amount")
        if not isinstance(currency, Currency):
            raise LedgerInputError("invalid_currency")
        scaled = Decimal(value).scaleb(currency.exponent, context=_EXACT)
        if scaled != scaled.to_integral_value(context=_EXACT):
            raise LedgerInputError("invalid_amount")
        return cls(int(scaled), currency)

    def to_decimal(self) -> Decimal:
        return Decimal(self.minor).scaleb(-self.currency.exponent, context=_EXACT)

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if other.currency != self.currency:
            raise LedgerInputError("currency_mismatch")
        return Money(self.minor + other.minor, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.minor, self.currency)

    def __str__(self) -> str:
        return f"{self.to_decimal()} {self.currency.code}"


@dataclass(frozen=True, slots=True)
class FxRateSnapshot:
    """One recorded quotation: one unit of base equals `rate` units of quote at effective_at.

    The rate is an exact Decimal. A snapshot converts only in its recorded direction (base to
    quote); an inverse conversion needs its own snapshot, so no derived rate is ever rounded.
    """

    snapshot_id: str
    base: Currency
    quote: Currency
    rate: Decimal
    effective_at: datetime
    source: str
    direction: str = QUOTE_PER_BASE
    rounding: str = HALF_EVEN

    def __post_init__(self) -> None:
        require_text(self.snapshot_id, "invalid_snapshot")
        require_text(self.source, "invalid_snapshot_source")
        if (
            not isinstance(self.base, Currency)
            or not isinstance(self.quote, Currency)
            or self.base.code == self.quote.code
        ):
            raise LedgerInputError("invalid_currency_pair")
        if (
            not isinstance(self.rate, Decimal)
            or not self.rate.is_finite()
            or self.rate <= 0
            or len(self.rate.as_tuple().digits) > MAX_RATE_DIGITS
            or not -MAX_RATE_DIGITS <= self.rate.as_tuple().exponent <= MAX_RATE_DIGITS
        ):
            raise LedgerInputError("invalid_rate")
        require_aware(self.effective_at, "invalid_snapshot_time")
        if self.direction != QUOTE_PER_BASE:
            raise LedgerInputError("unsupported_direction")
        if self.rounding != HALF_EVEN:
            raise LedgerInputError("unsupported_rounding")

    @property
    def pair(self) -> str:
        return f"{self.base.code}/{self.quote.code}"


class ConversionStatus(StrEnum):
    IDENTITY = "identity"  # already in the target currency
    CONVERTED = "converted"
    MISSING = "missing"  # no snapshot for the pair effective at or before as_of
    STALE = "stale"  # the latest usable snapshot is older than max_age
    CONFLICTING = "conflicting"  # snapshots for the pair at the same time quote different rates


@dataclass(frozen=True, slots=True)
class ConversionComponent:
    """One original-currency amount and the evidence used, or missing, to convert it."""

    original: Money
    status: ConversionStatus
    snapshot: FxRateSnapshot | None
    exact_minor: Decimal | None  # target minor units before the single rounding step


@dataclass(frozen=True, slots=True)
class Conversion:
    """A combined amount in one target currency, available only with usable evidence for all."""

    target: Currency
    as_of: datetime
    max_age: timedelta
    components: tuple[ConversionComponent, ...]
    amount: Money | None
    rounding: str = HALF_EVEN

    @property
    def available(self) -> bool:
        return self.amount is not None

    @property
    def originals(self) -> tuple[Money, ...]:
        return tuple(component.original for component in self.components)


def convert(
    amounts: Iterable[Money],
    target: Currency,
    snapshots: Iterable[FxRateSnapshot],
    *,
    as_of: datetime,
    max_age: timedelta,
) -> Conversion:
    """Combine original-currency amounts into the target currency under recorded snapshots.

    For each source currency the latest snapshot effective at or before as_of is used; it must
    be no older than max_age. Every component is computed exactly and the sum is rounded once,
    half-even, to the target exponent. If any component lacks usable evidence, amount is None
    and each component reports its status.

    Amounts in one currency are added exactly before any bound applies, so input order cannot
    change the result; only the combined original amount must be representable as Money.
    Snapshots at the same latest instant conflict when they quote different rates or when one
    snapshot ID names different sources. Otherwise the snapshot with the smallest (snapshot ID,
    source) supplies the recorded provenance, whatever the input order.
    """
    if not isinstance(target, Currency):
        raise LedgerInputError("invalid_currency")
    require_aware(as_of, "invalid_as_of")
    if not isinstance(max_age, timedelta) or max_age < timedelta(0):
        raise LedgerInputError("invalid_max_age")
    known: dict[str, int] = {}
    register_currency(known, target)
    sums: dict[str, int] = {}
    currencies: dict[str, Currency] = {}
    for amount in amounts:
        if not isinstance(amount, Money):
            raise LedgerInputError("invalid_amount")
        register_currency(known, amount.currency)
        sums[amount.currency.code] = sums.get(amount.currency.code, 0) + amount.minor
        currencies[amount.currency.code] = amount.currency
    by_code = {code: Money(total, currencies[code]) for code, total in sums.items()}
    as_of_instant = utc_instant(as_of)
    quotes: dict[tuple[str, str], list[FxRateSnapshot]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, FxRateSnapshot):
            raise LedgerInputError("invalid_snapshot")
        register_currency(known, snapshot.base)
        register_currency(known, snapshot.quote)
        quotes.setdefault((snapshot.base.code, snapshot.quote.code), []).append(snapshot)

    components = []
    for code in sorted(by_code):
        original = by_code[code]
        if code == target.code:
            components.append(
                ConversionComponent(
                    original, ConversionStatus.IDENTITY, None, Decimal(original.minor)
                )
            )
            continue
        usable = [
            snapshot
            for snapshot in quotes.get((code, target.code), ())
            if utc_instant(snapshot.effective_at) <= as_of_instant
        ]
        if not usable:
            components.append(ConversionComponent(original, ConversionStatus.MISSING, None, None))
            continue
        latest = max(utc_instant(snapshot.effective_at) for snapshot in usable)
        current = [s for s in usable if utc_instant(s.effective_at) == latest]
        if _conflicting(current):
            components.append(
                ConversionComponent(original, ConversionStatus.CONFLICTING, None, None)
            )
            continue
        snapshot = min(current, key=lambda candidate: (candidate.snapshot_id, candidate.source))
        if as_of_instant - latest > max_age:
            components.append(ConversionComponent(original, ConversionStatus.STALE, snapshot, None))
            continue
        exact = _EXACT.multiply(Decimal(original.minor), snapshot.rate).scaleb(
            target.exponent - original.currency.exponent, context=_EXACT
        )
        components.append(
            ConversionComponent(original, ConversionStatus.CONVERTED, snapshot, exact)
        )

    amount = None
    if all(component.exact_minor is not None for component in components):
        total = Decimal(0)
        for component in components:
            total = _EXACT.add(total, component.exact_minor)
        rounded = total.quantize(Decimal(1), rounding=ROUND_HALF_EVEN, context=_ROUNDING)
        amount = Money(int(rounded), target)
    return Conversion(target, as_of, max_age, tuple(components), amount)


def _conflicting(current: list[FxRateSnapshot]) -> bool:
    if len({snapshot.rate for snapshot in current}) > 1:
        return True
    sources: dict[str, set[str]] = {}
    for snapshot in current:
        sources.setdefault(snapshot.snapshot_id, set()).add(snapshot.source)
    return any(len(names) > 1 for names in sources.values())
