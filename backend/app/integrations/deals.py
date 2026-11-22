"""CRM stage changes of the signed webhook contract (specification 015-D, D-068 E5 and E6).

Pure functions only. parse_deal reads {"type": "deal.stage_changed", "id", "occurred_at",
"deal": {"id", "pipeline", "stage", "previous_stage"?, "amount"?, "currency"?,
"payment_reference"?}}. Text values are bounded and refused when they carry an email address, an
international phone number or a card number; an amount is an exact decimal in major units of an
allow-listed currency. Contacts, names and notes are not part of the contract and are dropped.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.advertising.currencies import currency
from app.declarations import MAX_MINOR
from app.integrations.bookings import Invalid, Unsupported
from app.ledger import LedgerInputError, Money
from app.privacy.collection import contains_card_number

TEXT = 128
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_PHONE = re.compile(r"\+\s*\d(?:[\s().-]*\d){7,14}")


@dataclass(frozen=True)
class StageChange:
    deal_ref: str
    pipeline: str
    stage: str
    previous_stage: str | None
    occurred_at: datetime
    amount: Money | None
    payment_reference: str | None


def _text(value: Any, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= TEXT
        or value != value.strip()
        or not value.isprintable()
        or _EMAIL.search(value)
        or _PHONE.search(value)
        or contains_card_number(value)
    ):
        raise Invalid("invalid_deal")
    return value


def _time(value: Any) -> datetime:
    if isinstance(value, str) and 10 <= len(value) <= 40:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            moment = None
        if moment is not None and moment.tzinfo is not None:
            return moment.astimezone(UTC)
    raise Invalid("invalid_deal")


def _amount(value: Any, code: Any) -> Money | None:
    if value is None and code is None:
        return None
    unit = currency(code)
    if unit is None or not isinstance(value, str):
        raise Invalid("invalid_deal")
    try:
        amount = Money.parse(value, unit)
    except LedgerInputError as error:
        raise Invalid("invalid_deal") from error
    if not 0 < amount.minor <= MAX_MINOR:
        raise Invalid("invalid_deal")
    return amount


def parse_deal(body: Mapping[str, Any]) -> StageChange:
    if body.get("type") != "deal.stage_changed":
        raise Unsupported("unsupported_event")
    deal = body.get("deal")
    if not isinstance(deal, Mapping):
        raise Invalid("invalid_deal")
    return StageChange(
        _text(deal.get("id")),
        _text(deal.get("pipeline")),
        _text(deal.get("stage")),
        _text(deal.get("previous_stage"), required=False),
        _time(body.get("occurred_at")),
        _amount(deal.get("amount"), deal.get("currency")),
        _text(deal.get("payment_reference"), required=False),
    )
