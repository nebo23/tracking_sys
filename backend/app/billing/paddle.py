"""Paddle Billing adapter (specification 017-C, D-103 D2, D7 and D14; design-017c.md section 6).

Every shape below comes from Paddle's official documentation read on 2026-11-28 (design
section 2); none was observed live, because D-103 allows no Paddle call before the owner's
sandbox check after the merge:

- Base addresses https://sandbox-api.paddle.com and https://api.paddle.com, with separate keys
  per environment; requests carry Authorization: Bearer <key> and Paddle-Version: 1 (V-12).
- Answers wrap the entity in "data"; errors are {"error": {"type", "code", "detail"}, "meta":
  {"request_id"}}. The error code is mapped to a closed code and the provider's detail is never
  kept; 429 carries Retry-After (V-8, V-9, V-12).
- IDs are a prefix, an underscore and 26 lowercase letters or digits (pri_, sub_, txn_, ctm_,
  adj_, evt_), and amounts are integer strings in the lowest denomination (V-6, V-13).
- Webhooks carry Paddle-Signature "ts=<unix seconds>;h1=<hex>", the HMAC-SHA256 of the
  timestamp and the raw body joined by a colon under the destination's secret; several h1
  values may be sent while a secret rotates. Payloads carry event_id, event_type, occurred_at
  and the full entity in data; subscription.created alone carries transaction_id, and a
  checkout transaction's custom_data is copied to its subscription (V-4 to V-6).

The transport is urllib with a 10-second timeout and at most 1 MiB read; tests substitute a
synthetic Paddle-shaped server. The snapshots below keep only allowlisted fields (design section
5.3): IDs, statuses, amounts, currencies and times, never a name, email, address, card or
payment-method detail, discount, management URL or the rest of custom_data. Nothing here logs a
URL, header, key, signature or body, and the client's representation never shows its key.
"""

import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

BASE_URLS = {"sandbox": "https://sandbox-api.paddle.com", "live": "https://api.paddle.com"}
API_VERSION = "1"
TIMEOUT = 10
MAX_RESPONSE = 1_048_576
MAX_CENTS = 10**12
# D7: a signature older or newer than this many seconds is refused (section 2.3, item 1).
SIGNATURE_TOLERANCE = 300
MAX_SIGNATURE_HEADER = 1024
PRICE_ID = re.compile(r"pri_[a-z0-9]{26}")
SUBSCRIPTION_ID = re.compile(r"sub_[a-z0-9]{26}")
TRANSACTION_ID = re.compile(r"txn_[a-z0-9]{26}")
CUSTOMER_ID = re.compile(r"ctm_[a-z0-9]{26}")
ADJUSTMENT_ID = re.compile(r"adj_[a-z0-9]{26}")
EVENT_ID = re.compile(r"evt_[a-z0-9]{26}")
EVENT_TYPE = re.compile(r"[a-z_]{1,24}\.[a-z_]{1,23}")
SIGNATURE = re.compile(r"[0-9a-f]{64}")
CENTS = re.compile(r"[0-9]{1,13}")
CURRENCY = re.compile(r"[A-Z]{3}")
INVOICE_NUMBER = re.compile(r"[A-Za-z0-9-]{1,64}")
PRICE_STATUSES = ("active", "archived")
INTERVALS = ("day", "week", "month", "year")
SUBSCRIPTION_STATUSES = ("trialing", "active", "past_due", "paused", "canceled")
SCHEDULED_ACTIONS = ("cancel", "pause", "resume")
TRANSACTION_STATUSES = ("draft", "ready", "billed", "paid", "completed", "canceled", "past_due")
TRANSACTION_ORIGINS = (
    "api",
    "subscription_charge",
    "subscription_payment_method_change",
    "subscription_recurring",
    "subscription_update",
    "web",
)
ADJUSTMENT_ACTIONS = (
    "credit",
    "refund",
    "chargeback",
    "chargeback_reverse",
    "chargeback_warning",
    "chargeback_warning_reverse",
    "credit_reverse",
)
ADJUSTMENT_STATUSES = ("pending_approval", "approved", "rejected", "reversed")
PRORATION_MODES = ("prorated_immediately", "prorated_next_billing_period")
# Paddle's error codes that carry a meaning for billing (V-8, V-9, V-12).
LOCKED = frozenset({"subscription_locked_renewal", "subscription_locked_processing"})
MAPPED_ERRORS = {
    "subscription_locked_pending_changes": "pending_change",
    "subscription_update_when_past_due": "past_due",
    "subscription_is_canceled_action_invalid": "subscription_canceled",
    "subscription_update_when_canceled": "subscription_canceled",
}
# The closed codes of ProviderError.
CODES = frozenset(
    {
        "provider_unavailable",
        "provider_rate_limited",
        "provider_unauthorized",
        "provider_not_found",
        "provider_rejected",
        "provider_invalid_response",
        "subscription_locked",
        "pending_change",
        "past_due",
        "subscription_canceled",
        "change_limit",
    }
)


class ProviderError(Exception):
    """A Paddle failure with a closed code; it never carries a URL, key, body or message."""

    def __init__(self, code: str, retry_after: int | None = None) -> None:
        assert code in CODES
        self.code, self.retry_after = code, retry_after
        super().__init__(code)


class InvalidSignature(Exception):
    """A webhook whose Paddle-Signature is missing, malformed, outside the window or wrong."""


class InvalidPayload(Exception):
    """A verified body or entity that does not have the documented shape."""


@dataclass
class Reply:
    status: int
    body: Any
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[str, str, Mapping[str, str], bytes | None], Reply]


# Send one request. A network failure, a timeout or an answer above MAX_RESPONSE is
# provider_unavailable, without the URL or any provider text. Header names are lower-cased.
def http_send(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> Reply:
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                status, received = response.status, dict(response.headers)
                raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as error:
            status, received = error.code, dict(error.headers or {})
            raw = error.read(MAX_RESPONSE + 1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ProviderError("provider_unavailable") from None
    if len(raw) > MAX_RESPONSE:
        raise ProviderError("provider_unavailable")
    try:
        parsed = json.loads(raw or b"{}")
    except ValueError:
        parsed = None
    return Reply(status, parsed, {name.lower(): value for name, value in received.items()})


def _retry_after(headers: Mapping[str, str]) -> int | None:
    value = headers.get("retry-after", "")
    return int(value) if value.isascii() and value.isdigit() and int(value) <= 86400 else None


# The closed code of a failed answer (design section 6).
def error_of(reply: Reply) -> ProviderError:
    if reply.status >= 500:
        return ProviderError("provider_unavailable")
    if reply.status == 429:
        return ProviderError("provider_rate_limited", _retry_after(reply.headers))
    error = reply.body.get("error") if isinstance(reply.body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if code in LOCKED:
        return ProviderError("subscription_locked")
    if code in MAPPED_ERRORS:
        return ProviderError(MAPPED_ERRORS[code])
    if isinstance(code, str) and code.startswith("subscription_immediate_charge"):
        return ProviderError("change_limit")
    if reply.status in (401, 403):
        return ProviderError("provider_unauthorized")
    if reply.status == 404:
        return ProviderError("provider_not_found")
    return ProviderError("provider_rejected")


def invalid() -> ProviderError:
    return ProviderError("provider_invalid_response")


def cents(value: Any) -> int:
    """An amount in the lowest denomination, sent by Paddle as an integer string."""
    if not isinstance(value, str) or not CENTS.fullmatch(value) or int(value) > MAX_CENTS:
        raise invalid()
    return int(value)


def require(pattern: re.Pattern[str], value: Any) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise invalid()
    return value


def _optional(pattern: re.Pattern[str], value: Any) -> str | None:
    return None if value is None else require(pattern, value)


def _choice(values: tuple[str, ...], value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if value not in values:
        raise invalid()
    return value


def _time(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise invalid()
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise invalid() from None
    if moment.tzinfo is None:
        raise invalid()
    return moment


def _object(value: Any, *, nullable: bool = False) -> dict[str, Any]:
    if value is None and nullable:
        return {}
    if not isinstance(value, dict):
        raise invalid()
    return value


# Our own custom_data on a checkout transaction (and copied to its subscription): only the
# agency and checkout IDs are read, and only when they are UUIDs; nothing else is kept.
def _custom(data: Mapping[str, Any]) -> tuple[UUID | None, UUID | None]:
    custom = data.get("custom_data")
    if not isinstance(custom, dict):
        return None, None
    values = []
    for key in ("agency_id", "checkout_id"):
        try:
            values.append(UUID(custom[key]) if isinstance(custom.get(key), str) else None)
        except ValueError:
            values.append(None)
    return values[0], values[1]


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


@dataclass(frozen=True)
class SubscriptionSnapshot:
    id: str
    status: str
    customer_id: str | None
    price_id: str | None
    item_count: int
    period_starts_at: datetime | None
    period_ends_at: datetime | None
    next_billed_at: datetime | None
    scheduled_action: str | None
    scheduled_at: datetime | None
    canceled_at: datetime | None
    currency: str | None
    transaction_id: str | None = None
    custom_agency: UUID | None = None
    custom_checkout: UUID | None = None

    # The allowlisted fields stored with the event (design section 5.3).
    def fields(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "customer_id": self.customer_id,
            "price_id": self.price_id,
            "item_count": self.item_count,
            "period_starts_at": _iso(self.period_starts_at),
            "period_ends_at": _iso(self.period_ends_at),
            "next_billed_at": _iso(self.next_billed_at),
            "scheduled_action": self.scheduled_action,
            "scheduled_at": _iso(self.scheduled_at),
            "canceled_at": _iso(self.canceled_at),
            "currency": self.currency,
        }

    # A snapshot rebuilt from the stored fields of an earlier event of the same subscription.
    @classmethod
    def from_fields(cls, subscription_id: str, fields: Mapping[str, Any]) -> "SubscriptionSnapshot":
        try:
            return cls(
                id=require(SUBSCRIPTION_ID, subscription_id),
                status=_choice(SUBSCRIPTION_STATUSES, fields.get("status")),
                customer_id=_optional(CUSTOMER_ID, fields.get("customer_id")),
                price_id=_optional(PRICE_ID, fields.get("price_id")),
                item_count=int(fields.get("item_count", 0)),
                period_starts_at=_time(fields.get("period_starts_at")),
                period_ends_at=_time(fields.get("period_ends_at")),
                next_billed_at=_time(fields.get("next_billed_at")),
                scheduled_action=_choice(
                    SCHEDULED_ACTIONS, fields.get("scheduled_action"), nullable=True
                ),
                scheduled_at=_time(fields.get("scheduled_at")),
                canceled_at=_time(fields.get("canceled_at")),
                currency=_optional(CURRENCY, fields.get("currency")),
            )
        except (ProviderError, TypeError, ValueError):
            raise InvalidPayload() from None


def subscription_of(data: Any) -> SubscriptionSnapshot:
    data = _object(data)
    items = data.get("items")
    if not isinstance(items, list):
        raise invalid()
    price_id = None
    if len(items) == 1:
        price = _object(_object(items[0]).get("price"))
        price_id = require(PRICE_ID, price.get("id"))
    period = _object(data.get("current_billing_period"), nullable=True)
    change = _object(data.get("scheduled_change"), nullable=True)
    action = _choice(SCHEDULED_ACTIONS, change.get("action"), nullable=True)
    scheduled_at = _time(change.get("effective_at"))
    if (action is None) != (scheduled_at is None):
        raise invalid()
    agency, checkout = _custom(data)
    return SubscriptionSnapshot(
        id=require(SUBSCRIPTION_ID, data.get("id")),
        status=_choice(SUBSCRIPTION_STATUSES, data.get("status")),
        customer_id=_optional(CUSTOMER_ID, data.get("customer_id")),
        price_id=price_id,
        item_count=len(items),
        period_starts_at=_time(period.get("starts_at")),
        period_ends_at=_time(period.get("ends_at")),
        next_billed_at=_time(data.get("next_billed_at")),
        scheduled_action=action,
        scheduled_at=scheduled_at,
        canceled_at=_time(data.get("canceled_at")),
        currency=_optional(CURRENCY, data.get("currency_code")),
        transaction_id=_optional(TRANSACTION_ID, data.get("transaction_id")),
        custom_agency=agency,
        custom_checkout=checkout,
    )


@dataclass(frozen=True)
class TransactionSnapshot:
    id: str
    status: str
    origin: str | None
    subscription_id: str | None
    customer_id: str | None
    currency: str
    subtotal: int
    tax: int
    total: int
    billed_at: datetime | None
    invoice_number: str | None
    custom_agency: UUID | None = None
    custom_checkout: UUID | None = None

    def fields(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "origin": self.origin,
            "subscription_id": self.subscription_id,
            "currency": self.currency,
            "subtotal": self.subtotal,
            "tax": self.tax,
            "total": self.total,
            "billed_at": _iso(self.billed_at),
            "invoice_number": self.invoice_number,
        }


def transaction_of(data: Any) -> TransactionSnapshot:
    data = _object(data)
    totals = _object(_object(data.get("details")).get("totals"))
    agency, checkout = _custom(data)
    return TransactionSnapshot(
        id=require(TRANSACTION_ID, data.get("id")),
        status=_choice(TRANSACTION_STATUSES, data.get("status")),
        origin=_choice(TRANSACTION_ORIGINS, data.get("origin"), nullable=True),
        subscription_id=_optional(SUBSCRIPTION_ID, data.get("subscription_id")),
        customer_id=_optional(CUSTOMER_ID, data.get("customer_id")),
        currency=require(CURRENCY, data.get("currency_code")),
        subtotal=cents(totals.get("subtotal")),
        tax=cents(totals.get("tax")),
        total=cents(totals.get("total")),
        billed_at=_time(data.get("billed_at")),
        invoice_number=_optional(INVOICE_NUMBER, data.get("invoice_number")),
        custom_agency=agency,
        custom_checkout=checkout,
    )


@dataclass(frozen=True)
class AdjustmentSnapshot:
    id: str
    action: str
    status: str
    transaction_id: str
    subscription_id: str | None
    currency: str
    total: int

    def fields(self) -> dict[str, Any]:
        values = asdict(self)
        values.pop("id")
        return values


def adjustment_of(data: Any) -> AdjustmentSnapshot:
    data = _object(data)
    totals = _object(data.get("totals"))
    return AdjustmentSnapshot(
        id=require(ADJUSTMENT_ID, data.get("id")),
        action=_choice(ADJUSTMENT_ACTIONS, data.get("action")),
        status=_choice(ADJUSTMENT_STATUSES, data.get("status")),
        transaction_id=require(TRANSACTION_ID, data.get("transaction_id")),
        subscription_id=_optional(SUBSCRIPTION_ID, data.get("subscription_id")),
        currency=require(CURRENCY, data.get("currency_code")),
        total=cents(totals.get("total")),
    )


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str
    occurred_at: datetime
    data: Mapping[str, Any]


# The envelope of a verified webhook body (V-6); raises InvalidPayload otherwise.
def parse_event(body: bytes) -> Event:
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise InvalidPayload()
        occurred = _time(payload.get("occurred_at"))
        if occurred is None:
            raise InvalidPayload()
        return Event(
            event_id=require(EVENT_ID, payload.get("event_id")),
            event_type=require(EVENT_TYPE, payload.get("event_type")),
            occurred_at=occurred,
            data=payload["data"],
        )
    except (ValueError, ProviderError):
        raise InvalidPayload() from None


# Check Paddle-Signature over the exact raw body (V-4): every h1 value is compared in constant
# time with the expected HMAC, and the timestamp must be within SIGNATURE_TOLERANCE seconds.
def verify_signature(header: str | None, body: bytes, secret: str, now: float) -> None:
    if not header or len(header) > MAX_SIGNATURE_HEADER or not secret:
        raise InvalidSignature()
    stamp: str | None = None
    signatures: list[str] = []
    for part in header.split(";"):
        key, sep, value = part.strip().partition("=")
        if not sep:
            raise InvalidSignature()
        if key == "ts":
            if stamp is not None or not value.isascii() or not value.isdigit() or len(value) > 12:
                raise InvalidSignature()
            stamp = value
        elif key == "h1":
            if not SIGNATURE.fullmatch(value):
                raise InvalidSignature()
            signatures.append(value)
    if stamp is None or not signatures or abs(now - int(stamp)) > SIGNATURE_TOLERANCE:
        raise InvalidSignature()
    # The signed string is the header's own timestamp text, a colon and the raw body.
    expected = hmac.new(
        secret.encode("utf-8"), stamp.encode("ascii") + b":" + body, hashlib.sha256
    ).hexdigest()
    matched = False
    for candidate in signatures:
        matched |= hmac.compare_digest(expected, candidate)
    if not matched:
        raise InvalidSignature()


@dataclass(frozen=True)
class PriceSnapshot:
    id: str
    status: str
    amount_cents: int
    currency: str
    interval: str | None
    frequency: int | None


@dataclass(frozen=True)
class Totals:
    currency: str
    subtotal: int
    tax: int
    total: int


@dataclass(frozen=True)
class Preview:
    immediate: Totals | None
    next: Totals | None
    credit: int | None
    charge: int | None
    result_action: str | None
    result_amount: int | None


def _totals(value: Any) -> Totals | None:
    if value is None:
        return None
    totals = _object(_object(_object(value).get("details")).get("totals"))
    return Totals(
        currency=require(CURRENCY, totals.get("currency_code")),
        subtotal=cents(totals.get("subtotal")),
        tax=cents(totals.get("tax")),
        total=cents(totals.get("total")),
    )


def _amount(summary: Mapping[str, Any], key: str) -> int | None:
    item = summary.get(key)
    return None if item is None else cents(_object(item).get("amount"))


class PaddleClient:
    """The calls of design section 6 for one environment and API key."""

    def __init__(self, api_key: str, environment: str, transport: Transport | None = None) -> None:
        if environment not in BASE_URLS:
            raise ValueError("Unknown Paddle environment.")
        self._key, self.environment = api_key, environment
        self._base, self._transport = BASE_URLS[environment], transport

    def __repr__(self) -> str:
        return f"PaddleClient(environment={self.environment!r})"

    def _send(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Paddle-Version": API_VERSION,
            "Accept": "application/json",
        }
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        reply = (self._transport or http_send)(method, self._base + path, headers, body)
        if not 200 <= reply.status < 300:
            raise error_of(reply)
        if not isinstance(reply.body, dict) or "data" not in reply.body:
            raise invalid()
        return reply.body["data"]

    def _subscription(self, method: str, path: str, payload: Any = None) -> SubscriptionSnapshot:
        return subscription_of(self._send(method, path, payload))

    # A registered price as Paddle reports it (D3: the operator registers it with its amount,
    # currency and interval, which must agree).
    def get_price(self, price_id: str) -> PriceSnapshot:
        data = self._send("GET", f"/prices/{require(PRICE_ID, price_id)}")
        if not isinstance(data, dict) or data.get("id") != price_id:
            raise invalid()
        unit = data.get("unit_price")
        cycle = data.get("billing_cycle")
        if data.get("status") not in PRICE_STATUSES or not isinstance(unit, dict):
            raise invalid()
        interval = frequency = None
        if cycle is not None:
            if not isinstance(cycle, dict) or cycle.get("interval") not in INTERVALS:
                raise invalid()
            frequency = cycle.get("frequency")
            if not isinstance(frequency, int) or isinstance(frequency, bool) or frequency < 1:
                raise invalid()
            interval = cycle["interval"]
        return PriceSnapshot(
            id=price_id,
            status=data["status"],
            amount_cents=cents(unit.get("amount")),
            currency=require(CURRENCY, unit.get("currency_code")),
            interval=interval,
            frequency=frequency,
        )

    # The checkout transaction of D6 (V-7): one item of the price, the agency's customer when
    # known, our IDs in custom_data, automatic collection, in USD. Returns its transaction ID.
    def create_transaction(
        self, price_id: str, customer_id: str | None, custom_data: Mapping[str, str]
    ) -> str:
        payload: dict[str, Any] = {
            "items": [{"price_id": require(PRICE_ID, price_id), "quantity": 1}],
            "custom_data": dict(custom_data),
            "collection_mode": "automatic",
            "currency_code": "USD",
        }
        if customer_id is not None:
            payload["customer_id"] = require(CUSTOMER_ID, customer_id)
        data = _object(self._send("POST", "/transactions", payload))
        _choice(TRANSACTION_STATUSES, data.get("status"))
        return require(TRANSACTION_ID, data.get("id"))

    def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        return self._subscription(
            "GET", f"/subscriptions/{require(SUBSCRIPTION_ID, subscription_id)}"
        )

    def _items(self, price_id: str, mode: str) -> dict[str, Any]:
        return {
            "items": [{"price_id": require(PRICE_ID, price_id), "quantity": 1}],
            "proration_billing_mode": _choice(PRORATION_MODES, mode),
        }

    # D8: what a change of the subscription's price would charge or credit, changing nothing.
    def preview_update(self, subscription_id: str, price_id: str, mode: str) -> Preview:
        path = f"/subscriptions/{require(SUBSCRIPTION_ID, subscription_id)}/preview"
        data = _object(self._send("PATCH", path, self._items(price_id, mode)))
        summary = _object(data.get("update_summary"), nullable=True)
        result = _object(summary.get("result"), nullable=True)
        return Preview(
            immediate=_totals(data.get("immediate_transaction")),
            next=_totals(data.get("next_transaction")),
            credit=_amount(summary, "credit"),
            charge=_amount(summary, "charge"),
            result_action=_choice(("credit", "charge"), result.get("action"), nullable=True),
            result_amount=None if not result else cents(result.get("amount")),
        )

    # D8: the change itself; a failed payment of an upgrade leaves the subscription unchanged.
    def update_items(self, subscription_id: str, price_id: str, mode: str) -> SubscriptionSnapshot:
        payload = {**self._items(price_id, mode), "on_payment_failure": "prevent_change"}
        return self._subscription(
            "PATCH", f"/subscriptions/{require(SUBSCRIPTION_ID, subscription_id)}", payload
        )

    # D9, D10: cancel at the end of the billing period, or at once.
    def cancel(self, subscription_id: str, *, immediately: bool) -> SubscriptionSnapshot:
        effective = "immediately" if immediately else "next_billing_period"
        return self._subscription(
            "POST",
            f"/subscriptions/{require(SUBSCRIPTION_ID, subscription_id)}/cancel",
            {"effective_from": effective},
        )

    # D9, D10: remove a scheduled change (a scheduled cancellation).
    def remove_scheduled_change(self, subscription_id: str) -> SubscriptionSnapshot:
        return self._subscription(
            "PATCH",
            f"/subscriptions/{require(SUBSCRIPTION_ID, subscription_id)}",
            {"scheduled_change": None},
        )

    # D9 (V-10): the transaction that Paddle.js opens to update the payment method.
    def payment_method_transaction(self, subscription_id: str) -> str:
        path = (
            f"/subscriptions/{require(SUBSCRIPTION_ID, subscription_id)}"
            "/update-payment-method-transaction"
        )
        return require(TRANSACTION_ID, _object(self._send("GET", path)).get("id"))

    # D11 (V-11): Paddle's temporary invoice address, valid for an hour; never stored or logged.
    def invoice_url(self, transaction_id: str) -> str:
        path = f"/transactions/{require(TRANSACTION_ID, transaction_id)}/invoice"
        url = _object(self._send("GET", path)).get("url")
        if not isinstance(url, str) or not url.startswith("https://") or len(url) > 4096:
            raise invalid()
        return url


def build_billing_provider(settings: Any) -> PaddleClient | None:
    """The live adapter when billing is enabled; tests substitute one bound to a synthetic
    server. The validated settings guarantee the key matches the environment."""
    if not settings.billing_enabled:
        return None
    return PaddleClient(
        settings.billing_paddle_api_key.get_secret_value(), settings.billing_paddle_environment
    )
