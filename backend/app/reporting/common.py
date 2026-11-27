"""Shared report contracts (specification 016-A, D-072 decisions D6 to D8; 016-B, D-089).

ReportError carries a closed public code and an HTTP status, never a rejected value. Pages are
integer positions starting at 1 over the complete, already ordered result. Comparisons of two
periods produce a difference and a percentage change only when both values are complete and
compatible; otherwise both stay null with the applicable reason. Percentages are exact decimal
text rounded half-even to two places, never binary floating point or infinity. Shares and
ratios (016-B) are exact fractions with a decimal text rounded half-even from the exact value.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal
from fractions import Fraction
from itertools import islice
from typing import Any

from app.advertising.currencies import decimal_text

CONTRACT_VERSION = "016b.1"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500
MAX_SOURCE_ROWS = 10_000  # social and spend inputs across both periods (D8)
MAX_EVIDENCE_ROWS = 200  # whole-client revenue evidence before the calculation (D8)
_PERCENT = Context(prec=60, rounding=ROUND_HALF_EVEN)
_HUNDREDTH = Decimal("0.01")
SHARE_PLACES = 4

# The four capabilities 016-A answered as dependency_unavailable, each now served by a 016-B
# report family (D-089 D6). requires keeps the specifications each capability rests on.
DEPENDENCIES = (
    {
        "capability": "attribution",
        "state": "available",
        "family": "attribution",
        "requires": ["006", "007-B", "007-C", "008"],
    },
    {
        "capability": "content_revenue",
        "state": "available",
        "family": "attribution",
        "requires": ["006", "007-B", "007-C", "008", "014-C"],
    },
    {
        "capability": "funnels",
        "state": "available",
        "family": "funnel",
        "requires": ["006"],
    },
    {
        "capability": "roas",
        "state": "available",
        "family": "roas",
        "requires": ["006", "007-B", "007-C", "008", "014-C"],
    },
)


class ReportError(Exception):
    """A refused report request; code is a closed public reason."""

    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class PageRequest:
    page: int = 1
    size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if not isinstance(self.page, int) or isinstance(self.page, bool) or self.page < 1:
            raise ReportError("invalid_page", 422)
        if (
            not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or not 1 <= self.size <= MAX_PAGE_SIZE
        ):
            raise ReportError("invalid_page", 422)


# The rows of one page of an ordered result of total_rows rows, and the page metadata. A page
# after the last one is refused; an empty result has exactly one empty first page.
def page_of(
    rows: Iterable[dict[str, Any]], total_rows: int, request: PageRequest
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    pages = max(1, -(-total_rows // request.size))
    if request.page > pages:
        raise ReportError("invalid_page", 422)
    start = (request.page - 1) * request.size
    selected = list(islice(iter(rows), start, start + request.size))
    return selected, {
        "page": request.page,
        "page_size": request.size,
        "total_rows": total_rows,
        "total_pages": pages,
    }


# Exact percentage change from previous to current as decimal text, or None for a zero baseline.
def percent_change(current: int, previous: int) -> str | None:
    if previous == 0:
        return None
    value = _PERCENT.divide(Decimal(current - previous) * 100, Decimal(previous))
    return str(value.quantize(_HUNDREDTH, rounding=ROUND_HALF_EVEN, context=_PERCENT))


# A labeled comparison of two values: difference and percentage only when comparable, which
# the caller decides; a zero baseline keeps the difference and gives zero_baseline.
def compare_values(current: int | None, previous: int | None, reason: str | None) -> dict[str, Any]:
    if reason is not None or current is None or previous is None:
        return {
            "difference": None,
            "percent_change": None,
            "comparable": False,
            "reason": reason or "unavailable",
        }
    change = percent_change(current, previous)
    return {
        "difference": current - previous,
        "percent_change": change,
        "comparable": True,
        "reason": "zero_baseline" if change is None else None,
    }


# An exact amount in minor units with its canonical decimal text.
def amount(minor: int, exponent: int) -> dict[str, Any]:
    return {"minor": minor, "decimal": decimal_text(minor, exponent)}


def _half_even(value: Fraction) -> int:
    whole = value.numerator // value.denominator
    rest = value - whole
    if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and whole % 2 == 1):
        return whole + 1
    return whole


# The decimal text of an exact fraction, rounded half-even from the exact value to places.
def fraction_text(value: Fraction, places: int = SHARE_PLACES) -> str:
    scaled = _half_even(Fraction(value) * 10**places)
    sign = "-" if scaled < 0 else ""
    digits = str(abs(scaled)).rjust(places + 1, "0")
    if places == 0:
        return sign + digits
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


# An exact share or ratio in lowest terms with its 4-decimal text.
def share(value: Fraction) -> dict[str, Any]:
    value = Fraction(value)
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": fraction_text(value),
    }


# A labeled comparison of two exact fractions, with the rules of compare_values.
def compare_fractions(
    current: Fraction | None, previous: Fraction | None, reason: str | None
) -> dict[str, Any]:
    if reason is not None or current is None or previous is None:
        return {
            "difference": None,
            "percent_change": None,
            "comparable": False,
            "reason": reason or "unavailable",
        }
    change = None if previous == 0 else fraction_text((current - previous) * 100 / previous, 2)
    return {
        "difference": share(current - previous),
        "percent_change": change,
        "comparable": True,
        "reason": "zero_baseline" if change is None else None,
    }


def take(rows: Iterator[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return list(islice(rows, limit))
