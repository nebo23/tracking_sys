"""In-memory Paddle Billing API and signed webhook sender for the billing tests (017-C, D-103).

A transport stand-in built from the shapes recorded in Phase 0 (design-017c.md sections 2 and 6):
the price, transaction, subscription, preview, cancellation, payment-method and invoice calls
with Paddle's "data" envelope and error bodies, the 30-minute renewal lock, the past_due and
pending-change refusals, a checkout that completes a transaction and creates a subscription with
the transaction's custom_data copied, and events signed with the documented Paddle-Signature
header. It never opens a socket. Every request is recorded with its parsed body for assertions.
All values are synthetic; the credentials are assembled at run time so that no file holds a
string of a real credential's form.
"""

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from app.billing.paddle import BASE_URLS, Reply

API_KEY = "_".join(("pdl", "sdbx", "apikey", "01" + "a" * 24, "S" * 22, "Abc"))
LIVE_API_KEY = "_".join(("pdl", "live", "apikey", "01" + "a" * 24, "S" * 22, "Abc"))
WEBHOOK_SECRET = "_".join(("pdl", "ntfset", "01" + "b" * 24, "W" * 32))
CLIENT_TOKEN = "test_" + "c" * 27
INVOICE_HOST = "https://invoices.paddle-synthetic.test"
RENEWAL_LOCK = timedelta(minutes=30)


def paddle_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(13)}"


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str]
    body: Any


def _error(status: int, code: str, kind: str = "request_error") -> Reply:
    return Reply(
        status,
        {
            "error": {
                "type": kind,
                "code": code,
                "detail": "Synthetic detail that must never be kept.",
                "documentation_url": f"https://developer.paddle.com/errors/shared/{code}",
            },
            "meta": {"request_id": "synthetic-request"},
        },
    )


def _ok(data: Any) -> Reply:
    return Reply(200, {"data": data, "meta": {"request_id": "synthetic-request"}})


def totals(subtotal: int, tax: int) -> dict[str, str]:
    return {
        "subtotal": str(subtotal),
        "discount": "0",
        "tax": str(tax),
        "total": str(subtotal + tax),
        "credit": "0",
        "balance": str(subtotal + tax),
        "grand_total": str(subtotal + tax),
        "fee": "0",
        "earnings": "0",
        "currency_code": "USD",
    }


@dataclass
class PaddleApi:
    environment: str = "sandbox"
    api_key: str = API_KEY
    prices: dict[str, dict] = field(default_factory=dict)
    transactions: dict[str, dict] = field(default_factory=dict)
    subscriptions: dict[str, dict] = field(default_factory=dict)
    queued: list[Reply] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)
    tax_rate: int = 10
    clock: datetime | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def now(self) -> datetime:
        return self.clock or datetime.now(UTC)

    # A Paddle price (V-13 shapes): active by default, in USD, one month or one year.
    def add_price(
        self,
        amount: int,
        interval: str = "month",
        *,
        currency: str = "USD",
        status: str = "active",
        frequency: int = 1,
    ) -> str:
        price_id = paddle_id("pri")
        self.prices[price_id] = {
            "id": price_id,
            "product_id": paddle_id("pro"),
            "status": status,
            "unit_price": {"amount": str(amount), "currency_code": currency},
            "billing_cycle": {"interval": interval, "frequency": frequency},
        }
        return price_id

    # Answer the next request with this reply instead (an error or a malformed body).
    def fail_next(self, status: int, code: str, *, headers: Mapping[str, str] | None = None):
        reply = _error(status, code)
        reply.headers = dict(headers or {})
        self.queued.append(reply)

    def answer_next(self, reply: Reply) -> None:
        self.queued.append(reply)

    def paths(self) -> list[str]:
        return [f"{request.method} {request.path}" for request in self.requests]

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> Reply:
        parts = urlsplit(url)
        assert f"{parts.scheme}://{parts.netloc}" == BASE_URLS[self.environment], "base address"
        assert headers.get("Paddle-Version") == "1", "version header"
        parsed = None if body is None else json.loads(body)
        with self.lock:
            self.requests.append(Request(method, parts.path, dict(headers), parsed))
            if headers.get("Authorization") != f"Bearer {self.api_key}":
                return _error(403, "invalid_token", "request_error")
            if self.queued:
                return self.queued.pop(0)
            return self._route(method, parts.path, parsed)

    def _route(self, method: str, path: str, body: Any) -> Reply:
        segments = path.strip("/").split("/")
        if method == "GET" and segments[0] == "prices" and len(segments) == 2:
            price = self.prices.get(segments[1])
            return _ok(price) if price else _error(404, "not_found")
        if method == "POST" and path == "/transactions":
            return self._create_transaction(body)
        if segments[0] == "transactions" and len(segments) == 3 and segments[2] == "invoice":
            return self._invoice(segments[1])
        if segments[0] != "subscriptions" or len(segments) < 2:
            return _error(404, "not_found")
        subscription = self.subscriptions.get(segments[1])
        if subscription is None:
            return _error(404, "not_found")
        tail = segments[2] if len(segments) > 2 else ""
        if method == "GET" and not tail:
            return _ok(subscription)
        if method == "PATCH" and tail in ("", "preview"):
            return self._update(subscription, body, preview=tail == "preview")
        if method == "POST" and tail == "cancel":
            return self._cancel(subscription, body)
        if method == "GET" and tail == "update-payment-method-transaction":
            return self._payment_method(subscription)
        return _error(404, "not_found")

    def _create_transaction(self, body: Any) -> Reply:
        items = body.get("items")
        if not isinstance(items, list) or len(items) != 1:
            return _error(400, "invalid_field")
        price = self.prices.get(items[0].get("price_id"))
        if price is None or price["status"] != "active":
            return _error(400, "invalid_field")
        transaction_id = paddle_id("txn")
        self.transactions[transaction_id] = {
            "id": transaction_id,
            "status": "draft",
            "customer_id": body.get("customer_id"),
            "address_id": None,
            "subscription_id": None,
            "origin": "api",
            "collection_mode": body.get("collection_mode", "automatic"),
            "currency_code": body.get("currency_code", "USD"),
            "custom_data": body.get("custom_data"),
            "items": [{"price": price, "quantity": items[0].get("quantity", 1)}],
            "details": {"totals": totals(0, 0)},
            "billed_at": None,
            "invoice_number": None,
            "checkout": {"url": f"https://synthetic.test/pay?_ptxn={transaction_id}"},
        }
        return _ok(self.transactions[transaction_id])

    def _invoice(self, transaction_id: str) -> Reply:
        transaction = self.transactions.get(transaction_id)
        if transaction is None:
            return _error(404, "not_found")
        if transaction["status"] != "completed" or transaction["details"]["totals"]["total"] == "0":
            return _error(400, "transaction_invoice_unavailable")
        return _ok({"url": f"{INVOICE_HOST}/{transaction_id}.pdf?token={secrets.token_hex(8)}"})

    def _locked(self, subscription: dict) -> bool:
        billed = subscription.get("next_billed_at")
        if billed is None:
            return False
        moment = datetime.fromisoformat(billed.replace("Z", "+00:00"))
        return self.now() >= moment - RENEWAL_LOCK

    def _update(self, subscription: dict, body: Any, *, preview: bool) -> Reply:
        if "scheduled_change" in body:
            if body["scheduled_change"] is not None:
                return _error(400, "invalid_field")
            if not preview:
                subscription["scheduled_change"] = None
            return _ok(subscription)
        if subscription["status"] == "past_due":
            return _error(400, "subscription_update_when_past_due")
        if subscription["status"] == "canceled":
            return _error(400, "subscription_update_when_canceled")
        if subscription.get("scheduled_change"):
            return _error(400, "subscription_locked_pending_changes")
        if self._locked(subscription):
            return _error(409, "subscription_locked_renewal")
        items = body.get("items")
        mode = body.get("proration_billing_mode")
        if not isinstance(items, list) or len(items) != 1 or mode is None:
            return _error(400, "invalid_field")
        price = self.prices.get(items[0].get("price_id"))
        if price is None:
            return _error(400, "invalid_field")
        current = int(subscription["items"][0]["price"]["unit_price"]["amount"])
        amount = int(price["unit_price"]["amount"])
        if preview:
            immediate = None
            if mode in ("prorated_immediately", "full_immediately"):
                charge = max(amount - current, 0)
                immediate = {"details": {"totals": totals(charge, charge * self.tax_rate // 100)}}
            tax = amount * self.tax_rate // 100
            return _ok(
                {
                    "immediate_transaction": immediate,
                    "next_transaction": {"details": {"totals": totals(amount, tax)}},
                    "update_summary": {
                        "credit": {"amount": str(max(current - amount, 0)), "currency_code": "USD"},
                        "charge": {"amount": str(max(amount - current, 0)), "currency_code": "USD"},
                        "result": {
                            "action": "charge" if amount >= current else "credit",
                            "amount": str(abs(amount - current)),
                            "currency_code": "USD",
                        },
                    },
                }
            )
        subscription["items"] = [{"price": price, "quantity": 1, "status": "active"}]
        return _ok(subscription)

    def _cancel(self, subscription: dict, body: Any) -> Reply:
        if subscription["status"] == "canceled":
            return _error(400, "subscription_is_canceled_action_invalid")
        effective = (body or {}).get("effective_from", "next_billing_period")
        if effective == "next_billing_period":
            if subscription["status"] == "paused":
                return _error(400, "invalid_field")
            if self._locked(subscription):
                return _error(409, "subscription_locked_renewal")
            if subscription.get("scheduled_change"):
                return _error(400, "subscription_locked_pending_changes")
            subscription["scheduled_change"] = {
                "action": "cancel",
                "effective_at": subscription["next_billed_at"],
                "resume_at": None,
            }
            return _ok(subscription)
        subscription.update(
            status="canceled",
            canceled_at=iso(self.now()),
            scheduled_change=None,
            next_billed_at=None,
            current_billing_period=None,
        )
        return _ok(subscription)

    def _payment_method(self, subscription: dict) -> Reply:
        if subscription["status"] not in ("active", "past_due", "trialing"):
            return _error(400, "subscription_is_canceled_action_invalid")
        transaction_id = paddle_id("txn")
        self.transactions[transaction_id] = {
            "id": transaction_id,
            "status": "ready",
            "origin": "subscription_payment_method_change",
            "subscription_id": subscription["id"],
            "customer_id": subscription["customer_id"],
            "currency_code": "USD",
            "custom_data": subscription.get("custom_data"),
            "details": {"totals": totals(0, 0)},
            "billed_at": None,
            "invoice_number": None,
        }
        return _ok(self.transactions[transaction_id])

    # The buyer pays a checkout transaction: Paddle completes it and creates a subscription for
    # the customer with the transaction's custom_data copied (V-6). Returns the subscription.
    def pay(self, transaction_id: str, *, customer_id: str | None = None) -> dict:
        transaction = self.transactions[transaction_id]
        price = transaction["items"][0]["price"]
        amount = int(price["unit_price"]["amount"])
        customer = customer_id or transaction.get("customer_id") or paddle_id("ctm")
        start = self.now().replace(microsecond=0)
        period = 30 if price["billing_cycle"]["interval"] == "month" else 365
        subscription_id = paddle_id("sub")
        self.subscriptions[subscription_id] = {
            "id": subscription_id,
            "status": "active",
            "customer_id": customer,
            "address_id": paddle_id("add"),
            "currency_code": "USD",
            "items": [{"price": price, "quantity": 1, "status": "active"}],
            "current_billing_period": {
                "starts_at": iso(start),
                "ends_at": iso(start + timedelta(days=period)),
            },
            "next_billed_at": iso(start + timedelta(days=period)),
            "scheduled_change": None,
            "canceled_at": None,
            "paused_at": None,
            "custom_data": transaction.get("custom_data"),
        }
        transaction.update(
            status="completed",
            customer_id=customer,
            subscription_id=subscription_id,
            origin="web",
            billed_at=iso(start),
            invoice_number=f"325-{secrets.randbelow(10**5):05d}",
            details={"totals": totals(amount, amount * self.tax_rate // 100)},
        )
        return self.subscriptions[subscription_id]


def event(
    event_type: str,
    data: dict,
    *,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> dict:
    return {
        "event_id": event_id or paddle_id("evt"),
        "event_type": event_type,
        "occurred_at": iso(occurred_at or datetime.now(UTC)),
        "notification_id": paddle_id("ntf"),
        "data": json.loads(json.dumps(data)),
    }


def created(subscription: dict, transaction_id: str, **options: Any) -> dict:
    """subscription.created carries the transaction that created it (V-6)."""
    return event(
        "subscription.created", {**subscription, "transaction_id": transaction_id}, **options
    )


# Sign a payload as Paddle does (V-4): HMAC-SHA256 of "ts:body" under the destination secret.
def signed(
    payload: dict | bytes, secret: str = WEBHOOK_SECRET, ts: int | None = None
) -> tuple[bytes, str]:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    moment = int(time.time()) if ts is None else ts
    digest = hmac.new(secret.encode(), f"{moment}:".encode() + body, hashlib.sha256).hexdigest()
    return body, f"ts={moment};h1={digest}"
