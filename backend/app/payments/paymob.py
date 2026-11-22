"""Paymob processed callbacks: verification, minimization and mapping (specification 015-B).

D-067 decisions D4 to D7 with amendment A1; facts from the official pages read on 2026-11-21
(entry review section 2.4) and parameters in design-015a.md section 4. Pure functions only: no
database, no network and no logging. Nothing here calls Paymob.

verify() recomputes the documented HMAC-SHA512 over the concatenated values of the documented,
ordered fields of a processed callback (V-2) and compares it in constant time with every live
secret. minimize() reduces a verified transaction to the allowed fields at once (D6): card,
billing, shipping, customer, item and token data never leave this module. map_transaction()
turns the minimized transaction into one 007-A Evidence description or a closed outcome that
posts nothing (D5, A1, notes N1 and N2 of entry review section 2.5).

The HMAC does not cover is_live, parent_transaction, is_refund or is_void (V-2), so a holder of
one signed callback could change them without breaking the signature (review finding R001).
D-070 therefore takes both financial properties from signed fields: a transaction is live only
when its signed integration_id is one of the live integration IDs the merchant declared for the
source (Paymob issues separate integration IDs for test and live mode) and its is_live is true,
and a refund or void adjusts only a sale that carries the same signed order ID (same_order). The
order rule is enforced where both records are known: at intake when the parent sale is already
stored, and on every ledger read for a refund that arrived before its parent.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.advertising.currencies import EXPONENTS
from app.ledger import Currency, EvidenceClass, Money, OperationKind

# The documented processed-callback HMAC fields, in their documented order (V-2). The
# response redirect uses id and order_id instead of obj.id and order.id; it is never accepted.
TRANSACTION_FIELDS = (
    "amount_cents",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order.id",
    "owner",
    "pending",
    "source_data.pan",
    "source_data.sub_type",
    "source_data.type",
    "success",
)
# The documented card token callback fields (V-8); such a callback stores and posts nothing.
TOKEN_FIELDS = (
    "card_subtype",
    "created_at",
    "email",
    "id",
    "masked_pan",
    "merchant_id",
    "order_id",
    "token",
)
SIGNATURE = re.compile(r"[0-9a-fA-F]{128}")
# The only fields that survive verification (D6). Everything else is dropped at once.
KEPT = (
    "id",
    "amount_cents",
    "currency",
    "created_at",
    "success",
    "pending",
    "error_occured",
    "is_auth",
    "is_capture",
    "is_standalone_payment",
    "has_parent_transaction",
    "is_refund",
    "is_void",
    "is_live",
    "parent_transaction",
    "integration_id",
    "order_id",
)
# Regions of this round (V-9) with the zone that applies to a created_at without an offset (V-7).
REGIONS = {"egypt": "Africa/Cairo"}
SOURCE_ACCOUNTS = {"egypt": "paymob-egypt"}
_POSITIVE = re.compile(r"[1-9][0-9]{0,18}")

Outcome = Literal["stored", "duplicate", "not_posted", "unmapped", "test_mode"]


class Unverifiable(ValueError):
    """The callback cannot be verified; the route answers 401 and stores nothing."""


@dataclass(frozen=True)
class Verified:
    """A verified callback: its type and, for a transaction, the minimized fields only."""

    kind: Literal["TRANSACTION", "TOKEN"]
    transaction: Mapping[str, Any] | None
    delivery_digest: str  # SHA-256 of the received hmac value; reveals nothing without the secret


@dataclass(frozen=True)
class Posting:
    """The 007-A terms of a posting transaction (receipt time and tenant added by the caller)."""

    delivery_id: str
    source_account_id: str
    operation_id: str
    kind: OperationKind
    classification: EvidenceClass
    amount: Money
    effective_at: datetime
    parent_operation_id: str | None
    reason: str | None
    source_reference: str


@dataclass(frozen=True)
class Mapped:
    """The result of mapping one verified transaction: a posting, or a closed outcome."""

    outcome: Outcome
    reason: str | None
    posting: Posting | None = None


def _lookup(item: Mapping[str, Any], path: str) -> Any:
    value: Any = item
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise Unverifiable("missing_field")
        value = value[part]
    return value


# The documented text form of one signed value: booleans as "true" or "false", integers in
# decimal, strings unchanged. A null is written as an empty string, which the pages read do not
# document (unverified until the live check). Floats, lists and objects cannot be verified.
def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    raise Unverifiable("unsupported_value")


def signed_string(item: Mapping[str, Any], fields: Iterable[str]) -> str:
    return "".join(_text(_lookup(item, path)) for path in fields)


def signature(secret: str, item: Mapping[str, Any], fields: Iterable[str]) -> str:
    message = signed_string(item, fields).encode()
    return hmac.new(secret.encode(), message, hashlib.sha512).hexdigest()


def parse_body(body: bytes) -> tuple[str, Mapping[str, Any]]:
    try:
        payload = json.loads(body)
    # A body nested too deeply for the decoder raises RecursionError; like any other unreadable
    # body it cannot be verified.
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise Unverifiable("invalid_body") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("obj"), dict):
        raise Unverifiable("invalid_body")
    kind = payload.get("type")
    if kind not in {"TRANSACTION", "TOKEN"}:
        raise Unverifiable("unsupported_type")
    return kind, payload["obj"]


# Verify a processed callback body against every live secret (current and overlapping previous
# ones), trying each in constant time. Returns the minimized result, or raises Unverifiable.
def verify(body: bytes, received: str | None, secrets: Iterable[str]) -> Verified:
    if received is None or not SIGNATURE.fullmatch(received):
        raise Unverifiable("missing_signature")
    kind, obj = parse_body(body)
    fields = TRANSACTION_FIELDS if kind == "TRANSACTION" else TOKEN_FIELDS
    signed_string(obj, fields)  # every signed field must be present and representable
    expected = received.lower().encode()
    matched = False
    for secret in secrets:
        computed = signature(secret, obj, fields).encode()
        matched = hmac.compare_digest(computed, expected) | matched
    if not matched:
        raise Unverifiable("invalid_signature")
    digest = hashlib.sha256(expected).hexdigest()
    return Verified(kind, minimize(obj) if kind == "TRANSACTION" else None, digest)


# The allowed fields of a verified transaction (D6). order.id is kept as order_id; nothing else of
# the order, and nothing of source_data, data, billing, shipping or payment key claims.
def minimize(obj: Mapping[str, Any]) -> dict[str, Any]:
    order = obj.get("order")
    kept = {key: obj.get(key) for key in KEPT if key != "order_id"}
    kept["order_id"] = order.get("id") if isinstance(order, Mapping) else None
    return kept


def _flag(item: Mapping[str, Any], key: str) -> bool:
    return item.get(key) is True


def _identifier(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and _POSITIVE.fullmatch(value):
        return value
    return None


# created_at with an offset is used as given; without one it is local time in the region's zone,
# and a repeated local hour resolves to its first occurrence (fold 0).
def effective_time(value: Any, region: str) -> datetime | None:
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(REGIONS[region]))
    return moment.astimezone(UTC)


def _canonical(posting: dict[str, Any]) -> str:
    return json.dumps(posting, sort_keys=True, separators=(",", ":"))


def delivery_id(operation_id: str, state: dict[str, Any]) -> str:
    return f"paymob:{operation_id}:{hashlib.sha256(_canonical(state).encode()).hexdigest()[:32]}"


def source_reference(integration: str, order: str | None) -> str:
    return f"paymob:{integration}:{order or 'unknown'}"


# The signed order ID of a Paymob posting, kept as the last part of its source reference
# paymob:<integration>:<order>; None when the callback carried no positive order ID.
def signed_order(reference: str | None) -> str | None:
    parts = reference.split(":") if isinstance(reference, str) else []
    if len(parts) != 3 or parts[0] != "paymob":
        return None
    return parts[2] if _POSITIVE.fullmatch(parts[2]) else None


# D-070: a refund or void may adjust a sale only when both carry the same signed order ID. The
# parent_transaction that names the sale is unsigned; the order ID is signed in both callbacks.
def same_order(refund_reference: str | None, sale_reference: str | None) -> bool:
    order = signed_order(refund_reference)
    return order is not None and order == signed_order(sale_reference)


def _kind(item: Mapping[str, Any]) -> tuple[OperationKind, str | None] | None:
    """The kind and reason of a posting state whose signed flags agree with it (N1)."""
    parent = _flag(item, "has_parent_transaction")
    capture = _flag(item, "is_capture")
    standalone = _flag(item, "is_standalone_payment")
    refund, void = _flag(item, "is_refund"), _flag(item, "is_void")
    if not parent and standalone and not capture and not refund and not void:
        return OperationKind.SALE, None
    if parent and capture and not standalone and not refund and not void:
        return OperationKind.SALE, None
    if parent and not capture and not standalone and refund != void:
        return OperationKind.REFUND, "void" if void else None
    return None


# Map one minimized, verified transaction of a source in the given region (design section 4.4).
# live_integrations are the source's declared live integration IDs (D-070): the unsigned is_live
# alone never makes a transaction live, and a signed integration_id outside the declared list is
# a test-mode (or unknown) integration that posts nothing.
def map_transaction(
    item: Mapping[str, Any], region: str, *, live_integrations: Collection[int]
) -> Mapped:
    if not _flag(item, "is_live"):
        return Mapped("test_mode", None)
    integration = _identifier(item.get("integration_id"))
    if integration is None or int(integration) not in live_integrations:
        return Mapped("test_mode", "undeclared_integration")
    if not _flag(item, "success") or _flag(item, "error_occured"):
        return Mapped("not_posted", "failed")
    if _flag(item, "pending"):
        return Mapped("not_posted", "pending")
    if _flag(item, "is_auth"):
        return Mapped("not_posted", "authorization")
    shape = _kind(item)
    operation = _identifier(item.get("id"))
    if shape is None or operation is None:
        return Mapped("unmapped", "unsupported_state")
    kind, reason = shape
    parent = None
    if kind is OperationKind.REFUND:
        parent = _identifier(item.get("parent_transaction"))
        if parent is None or parent == operation:
            return Mapped("unmapped", "invalid_parent")
    amount = item.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        return Mapped("unmapped", "invalid_amount")
    code = item.get("currency")
    if not isinstance(code, str) or EXPONENTS.get(code) != 2:
        return Mapped("unmapped", "unsupported_currency")
    effective = effective_time(item.get("created_at"), region)
    if effective is None:
        return Mapped("unmapped", "invalid_time")
    classification = (
        EvidenceClass.CONFIRMED_CAPTURE
        if kind is OperationKind.SALE
        else EvidenceClass.CONFIRMED_ADJUSTMENT
    )
    money = Money(amount, Currency(code, 2))
    state = {
        "kind": kind.value,
        "classification": classification.value,
        "minor": amount,
        "currency": code,
        "exponent": 2,
        "effective_at": effective.isoformat(timespec="microseconds"),
        "parent": parent,
        "reason": reason,
    }
    posting = Posting(
        delivery_id(operation, state),
        SOURCE_ACCOUNTS[region],
        operation,
        kind,
        classification,
        money,
        effective,
        parent,
        reason,
        source_reference(integration, _identifier(item.get("order_id"))),
    )
    return Mapped("stored", None, posting)
