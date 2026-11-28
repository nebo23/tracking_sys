"""Paddle Billing adapter (specification 017-C, D-103 D2 and D14; design-017c.md section 6).

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

The transport is urllib with a 10-second timeout and at most 1 MiB read; tests substitute a
synthetic Paddle-shaped server. Nothing here logs a URL, header, key or body, and the client's
representation never shows its key.
"""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

BASE_URLS = {"sandbox": "https://sandbox-api.paddle.com", "live": "https://api.paddle.com"}
API_VERSION = "1"
TIMEOUT = 10
MAX_RESPONSE = 1_048_576
MAX_CENTS = 10**12
PRICE_ID = re.compile(r"pri_[a-z0-9]{26}")
CENTS = re.compile(r"[0-9]{1,13}")
CURRENCY = re.compile(r"[A-Z]{3}")
PRICE_STATUSES = ("active", "archived")
INTERVALS = ("day", "week", "month", "year")
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


@dataclass(frozen=True)
class PriceSnapshot:
    id: str
    status: str
    amount_cents: int
    currency: str
    interval: str | None
    frequency: int | None


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


def build_billing_provider(settings: Any) -> PaddleClient | None:
    """The live adapter when billing is enabled; tests substitute one bound to a synthetic
    server. The validated settings guarantee the key matches the environment."""
    if not settings.billing_enabled:
        return None
    return PaddleClient(
        settings.billing_paddle_api_key.get_secret_value(), settings.billing_paddle_environment
    )
