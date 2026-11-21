"""Synthetic Paymob-shaped processed callbacks for tests (specification 015-B, D-067 D12).

Builds transaction processed callbacks with the structure of Paymob's documented sample (entry
review section 2.4): the transaction object with its flags, the order with merchant, shipping
and item data, source_data with the last four digits and the brand, the gateway data with a
masked card number, and payment key claims with billing data and a payment token. Every value is
synthetic. Callbacks are signed by the documented algorithm (HMAC-SHA512 over the documented
fields) with a test secret. Nothing here opens a network connection or calls Paymob.
"""

import copy
import json
from itertools import count
from typing import Any

from app.payments.paymob import TOKEN_FIELDS, TRANSACTION_FIELDS, signature

TEST_SECRET = "SYNTHETICPAYMOBHMACSECRET0000001"
OTHER_SECRET = "SYNTHETICPAYMOBHMACSECRET0000002"
# Synthetic values that must never be stored, logged or returned (T-16).
CARD_LAST_FOUR = "4931"
MASKED_PAN = "512345xxxxxx4931"
CARD_BRAND = "MasterCard"
CUSTOMER_EMAIL = "synthetic.buyer@example.test"
CUSTOMER_PHONE = "+201000000931"
CUSTOMER_NAME = "Synthetic Buyer"
STREET = "Synthetic Street 9"
CARD_TOKEN = "synthetic-card-token-0931"
PAYMENT_TOKEN = "synthetic-payment-token-0931"
FORBIDDEN = (
    CARD_LAST_FOUR,
    MASKED_PAN,
    CARD_BRAND,
    CUSTOMER_EMAIL,
    CUSTOMER_PHONE,
    CUSTOMER_NAME,
    STREET,
    CARD_TOKEN,
    PAYMENT_TOKEN,
)
_ids = count(700_000_001)


def next_id() -> int:
    return next(_ids)


def _person() -> dict[str, Any]:
    return {
        "first_name": "Synthetic",
        "last_name": "Buyer",
        "full_name": CUSTOMER_NAME,
        "street": STREET,
        "building": "9",
        "floor": "1",
        "apartment": "1",
        "city": "Cairo",
        "state": "Cairo",
        "country": "EG",
        "email": CUSTOMER_EMAIL,
        "phone_number": CUSTOMER_PHONE,
        "postal_code": "00000",
        "extra_description": "synthetic",
    }


# One transaction object with every documented flag. Defaults describe a successful live
# standalone card payment of 1,000.00 EGP created in Cairo local time without an offset.
def transaction(
    *,
    id: int | None = None,
    amount_cents: int = 100_000,
    currency: str = "EGP",
    created_at: str = "2026-11-10T11:33:44.592345",
    success: bool = True,
    pending: bool = False,
    error_occured: bool = False,
    is_auth: bool = False,
    is_capture: bool = False,
    is_standalone_payment: bool = True,
    is_voided: bool = False,
    is_refunded: bool = False,
    is_refund: bool = False,
    is_void: bool = False,
    is_live: bool = True,
    parent: int | None = None,
    order_id: int = 810_000_001,
    integration_id: int = 4_097_558,
    owner: int = 302_852,
) -> dict[str, Any]:
    identifier = id if id is not None else next_id()
    return {
        "id": identifier,
        "pending": pending,
        "amount_cents": amount_cents,
        "success": success,
        "is_auth": is_auth,
        "is_capture": is_capture,
        "is_standalone_payment": is_standalone_payment,
        "is_voided": is_voided,
        "is_refunded": is_refunded,
        "is_3d_secure": True,
        "integration_id": integration_id,
        "profile_id": 164_295,
        "has_parent_transaction": parent is not None,
        "order": {
            "id": order_id,
            "created_at": created_at,
            "merchant": {
                "id": 164_295,
                "phones": [CUSTOMER_PHONE],
                "company_emails": [CUSTOMER_EMAIL],
                "company_name": "Synthetic Merchant",
                "street": STREET,
            },
            "shipping_data": {**_person(), "id": 1, "order_id": order_id},
            "currency": currency,
            "merchant_order_id": CUSTOMER_EMAIL,
            "paid_amount_cents": amount_cents,
            "items": [{"name": "Synthetic item", "amount_cents": amount_cents, "quantity": 1}],
        },
        "created_at": created_at,
        "currency": currency,
        "source_data": {
            "pan": CARD_LAST_FOUR,
            "type": "card",
            "tenure": None,
            "sub_type": CARD_BRAND,
        },
        "api_source": "IFRAME",
        "is_void": is_void,
        "is_refund": is_refund,
        "data": {
            "card_num": MASKED_PAN,
            "card_type": CARD_BRAND.upper(),
            "message": "Approved",
            "migs_order": {"chargeback": {"amount": None, "currency": currency}},
        },
        "payment_key_claims": {
            "billing_data": _person(),
            "redirect_url": f"https://example.test/status?payment_token={PAYMENT_TOKEN}",
        },
        "error_occured": error_occured,
        "is_live": is_live,
        "refunded_amount_cents": 0,
        "is_captured": False,
        "captured_amount": 0,
        "updated_at": created_at,
        "owner": owner,
        "parent_transaction": parent,
    }


def sale(**changes: Any) -> dict[str, Any]:
    return transaction(**changes)


def refund(parent: int, amount_cents: int, **changes: Any) -> dict[str, Any]:
    changes.setdefault("created_at", "2026-11-10T15:00:00.000001")
    return transaction(
        parent=parent,
        amount_cents=amount_cents,
        is_standalone_payment=False,
        is_refund=True,
        **changes,
    )


def void(parent: int, amount_cents: int, **changes: Any) -> dict[str, Any]:
    changes.setdefault("created_at", "2026-11-10T12:00:00.000001")
    return transaction(
        parent=parent,
        amount_cents=amount_cents,
        is_standalone_payment=False,
        is_void=True,
        **changes,
    )


def capture(parent: int, amount_cents: int, **changes: Any) -> dict[str, Any]:
    changes.setdefault("created_at", "2026-11-10T13:00:00.000001")
    return transaction(
        parent=parent,
        amount_cents=amount_cents,
        is_standalone_payment=False,
        is_capture=True,
        **changes,
    )


def authorization(**changes: Any) -> dict[str, Any]:
    return transaction(is_auth=True, is_standalone_payment=False, **changes)


# The parent re-sent by Paymob after a refund or void, with the flag set (V-4).
def resent_parent(
    obj: dict[str, Any], *, refunded: int = 0, voided: bool = False
) -> dict[str, Any]:
    item = copy.deepcopy(obj)
    item["is_refunded"] = refunded > 0
    item["refunded_amount_cents"] = refunded
    item["is_voided"] = voided
    return item


def token(**changes: Any) -> dict[str, Any]:
    item = {
        "id": next_id(),
        "token": CARD_TOKEN,
        "masked_pan": MASKED_PAN,
        "merchant_id": 164_295,
        "card_subtype": CARD_BRAND,
        "created_at": "2026-11-10T13:28:31.015314",
        "email": CUSTOMER_EMAIL,
        "order_id": "810000001",
        "user_added": False,
        "next_payment_intention": "pi_test_synthetic",
    }
    item.update(changes)
    return item


# A signed processed callback: the JSON body and the query string with its hmac.
def signed(obj: dict[str, Any], secret: str = TEST_SECRET, kind: str = "TRANSACTION"):
    fields = TRANSACTION_FIELDS if kind == "TRANSACTION" else TOKEN_FIELDS
    body = json.dumps({"type": kind, "obj": obj, "issuer_bank": None}).encode()
    return body, {"hmac": signature(secret, obj, fields)}


# A signed callback padded with a long order item description to the given body size.
def padded(obj: dict[str, Any], size: int, secret: str = TEST_SECRET):
    item = copy.deepcopy(obj)
    item["order"]["items"][0]["description"] = ""
    base = len(signed(item, secret)[0])
    item["order"]["items"][0]["description"] = "x" * (size - base)
    body, query = signed(item, secret)
    assert len(body) == size
    return body, query
