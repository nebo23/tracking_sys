"""Allow-listed spend currencies and exact spend parsing (specification 014-A, D4).

The table holds every currency code on Meta's Marketing API currency page (read 2026-11-20,
entry review section 2.4, V-2) that is current in ISO 4217, with its ISO 4217 minor-unit
exponent. Meta's API offset never exceeds that precision (offset 1 for exponent 0 or 2, offset
100 for exponent 2 or 3), so every spend value Meta can report parses exactly. FBZ (Facebook
credits, not an ISO code) and the withdrawn codes HRK, LTL, LVL, SKK and VEF are excluded.

parse_spend reads a decimal string with app.ledger.money.Money.parse. A value with more decimal
places than the exponent, a malformed or negative value, or a code outside the table is refused
with a closed reason and never rounded.
"""

from types import MappingProxyType

from app.ledger import Currency, LedgerInputError, Money

ZERO_DECIMAL = ("CLP", "ISK", "JPY", "KRW", "PYG", "VND")
THREE_DECIMAL = ("BHD", "JOD")
TWO_DECIMAL = (
    "AED",
    "ARS",
    "AUD",
    "BDT",
    "BGN",
    "BOB",
    "BRL",
    "CAD",
    "CHF",
    "CNY",
    "COP",
    "CRC",
    "CZK",
    "DKK",
    "DZD",
    "EGP",
    "EUR",
    "GBP",
    "GTQ",
    "HKD",
    "HNL",
    "HUF",
    "IDR",
    "ILS",
    "INR",
    "KES",
    "MOP",
    "MXN",
    "MYR",
    "NGN",
    "NIO",
    "NOK",
    "NZD",
    "PEN",
    "PHP",
    "PKR",
    "PLN",
    "QAR",
    "RON",
    "RSD",
    "RUB",
    "SAR",
    "SEK",
    "SGD",
    "THB",
    "TRY",
    "TWD",
    "UAH",
    "USD",
    "UYU",
    "VES",
    "ZAR",
)
EXPONENTS = MappingProxyType(
    {
        **dict.fromkeys(ZERO_DECIMAL, 0),
        **dict.fromkeys(TWO_DECIMAL, 2),
        **dict.fromkeys(THREE_DECIMAL, 3),
    }
)
UNPARSEABLE = "unparseable_amount"
UNSUPPORTED = "unsupported_currency"


# The allow-listed currency of a code, or None.
def currency(code: object) -> Currency | None:
    if not isinstance(code, str) or code not in EXPONENTS:
        return None
    return Currency(code, EXPONENTS[code])


# The exact non-negative amount of a spend string, or the closed reason it was refused.
def parse_spend(value: object, code: object) -> Money | str:
    unit = currency(code)
    if unit is None:
        return UNSUPPORTED
    if not isinstance(value, str):
        return UNPARSEABLE
    try:
        amount = Money.parse(value, unit)
    except LedgerInputError:
        return UNPARSEABLE
    return amount if amount.minor >= 0 else UNPARSEABLE


# The decimal string of minor units in a currency with the given exponent ("12.30").
def decimal_text(minor: int, exponent: int) -> str:
    return str(Money(minor, Currency("XXX", exponent)).to_decimal())
