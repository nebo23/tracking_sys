"""The Paddle webhook contract and the adapter's requests (017-C, D-103 D7 and D8; BL06, BL09).

Unit cases without a database: the Paddle-Signature rules (V-4), the event envelope and the
allowlisted snapshots (V-6, design-017c.md section 5.3), and the request bodies of the adapter's
calls against the synthetic Paddle-shaped server (V-7 to V-11). No Paddle call is made.
"""

import json

import pytest
from paddle_api import API_KEY, WEBHOOK_SECRET, PaddleApi, created, paddle_id, signed

from app.billing import paddle
from app.billing.paddle import PaddleClient, ProviderError


def test_bl06_signature_rules():
    body = b'{"event_id": "x"}'
    now = 1_800_000_000
    _, header = signed(body, WEBHOOK_SECRET, now)
    paddle.verify_signature(header, body, WEBHOOK_SECRET, now)
    paddle.verify_signature(header, body, WEBHOOK_SECRET, now + 300)
    paddle.verify_signature(f"{header};h1={'0' * 64}", body, WEBHOOK_SECRET, now)
    paddle.verify_signature(f"h1={'0' * 64};{header}", body, WEBHOOK_SECRET, now)
    digest = header.split("h1=")[1]
    refused = (
        (header, body + b" ", WEBHOOK_SECRET, now),
        (header, body, WEBHOOK_SECRET + "x", now),
        (header, body, WEBHOOK_SECRET, now + 301),
        (header, body, WEBHOOK_SECRET, now - 301),
        (None, body, WEBHOOK_SECRET, now),
        ("", body, WEBHOOK_SECRET, now),
        (f"ts={now}", body, WEBHOOK_SECRET, now),
        (f"h1={digest}", body, WEBHOOK_SECRET, now),
        (f"ts={now};ts={now};h1={digest}", body, WEBHOOK_SECRET, now),
        (f"ts=0{now};h1={digest}", body, WEBHOOK_SECRET, now),
        (f"ts={now};h1={digest.upper()}", body, WEBHOOK_SECRET, now),
        (f"ts={now};h1={digest[:-1]}", body, WEBHOOK_SECRET, now),
        (f"ts={now};{'x' * 1024};h1={digest}", body, WEBHOOK_SECRET, now),
        (f"ts=-{now};h1={digest}", body, WEBHOOK_SECRET, now),
        (header, body, "", now),
    )
    for values in refused:
        with pytest.raises(paddle.InvalidSignature):
            paddle.verify_signature(*values)


def test_event_envelope_and_allowlisted_snapshots():
    api = PaddleApi()
    price = api.add_price(2900)
    agency = "00000000-0000-0000-0000-000000000001"
    transaction = PaddleClient(API_KEY, "sandbox", api).create_transaction(
        price, None, {"agency_id": agency, "checkout_id": "not-a-uuid"}
    )
    subscription = api.pay(transaction)
    subscription["custom_data"]["note"] = "Synthetic Person, person@example.test"
    payload = created(subscription, transaction)
    parsed = paddle.parse_event(json.dumps(payload).encode())
    assert (parsed.event_id, parsed.event_type) == (payload["event_id"], "subscription.created")
    snapshot = paddle.subscription_of(parsed.data)
    assert (snapshot.id, snapshot.status, snapshot.price_id, snapshot.item_count) == (
        subscription["id"],
        "active",
        price,
        1,
    )
    assert snapshot.transaction_id == transaction and snapshot.custom_checkout is None
    assert str(snapshot.custom_agency) == agency
    fields = json.dumps(snapshot.fields())
    for forbidden in ("Synthetic Person", "example.test", "address", "custom_data", "note"):
        assert forbidden not in fields
    rebuilt = paddle.SubscriptionSnapshot.from_fields(snapshot.id, snapshot.fields())
    assert (rebuilt.status, rebuilt.next_billed_at, rebuilt.price_id) == (
        snapshot.status,
        snapshot.next_billed_at,
        snapshot.price_id,
    )
    entity = api.transactions[transaction]
    money = paddle.transaction_of(entity)
    assert (money.subtotal, money.tax, money.total, money.currency) == (2900, 290, 3190, "USD")
    assert set(money.fields()) == {
        "status",
        "origin",
        "subscription_id",
        "currency",
        "subtotal",
        "tax",
        "total",
        "billed_at",
        "invoice_number",
    }
    for bad in (
        b"not json",
        b"[]",
        json.dumps({**payload, "event_id": "evt_short"}).encode(),
        json.dumps({**payload, "occurred_at": "2026-11-28T00:00:00"}).encode(),
        json.dumps({**payload, "data": []}).encode(),
        json.dumps({**payload, "event_type": "Subscription.Created"}).encode(),
    ):
        with pytest.raises(paddle.InvalidPayload):
            paddle.parse_event(bad)
    for broken in (
        subscription | {"status": "deleted"},
        subscription | {"id": "sub_x"},
        subscription | {"scheduled_change": {"action": "cancel", "effective_at": None}},
        subscription | {"next_billed_at": "yesterday"},
        subscription | {"items": "none"},
    ):
        with pytest.raises(ProviderError):
            paddle.subscription_of(broken)
    with pytest.raises(ProviderError):
        paddle.transaction_of(entity | {"details": {"totals": {"subtotal": "1.5"}}})


def test_bl09_adapter_sends_the_documented_requests():
    api = PaddleApi()
    client = PaddleClient(API_KEY, "sandbox", api)
    monthly, larger = api.add_price(2900), api.add_price(9900)
    customer = paddle_id("ctm")
    custom = {"agency_id": "a", "checkout_id": "c"}
    transaction = client.create_transaction(monthly, customer, custom)
    assert api.requests[-1].body == {
        "items": [{"price_id": monthly, "quantity": 1}],
        "custom_data": custom,
        "collection_mode": "automatic",
        "currency_code": "USD",
        "customer_id": customer,
    }
    subscription = api.pay(transaction)["id"]
    preview = client.preview_update(subscription, larger, "prorated_immediately")
    assert api.requests[-1].body == {
        "items": [{"price_id": larger, "quantity": 1}],
        "proration_billing_mode": "prorated_immediately",
    }
    assert preview.immediate.subtotal == 7000 and preview.next.total == 10890
    assert (preview.result_action, preview.result_amount) == ("charge", 7000)
    assert api.subscriptions[subscription]["items"][0]["price"]["id"] == monthly
    updated = client.update_items(subscription, larger, "prorated_immediately")
    assert api.requests[-1].body["on_payment_failure"] == "prevent_change"
    assert updated.price_id == larger
    client.preview_update(subscription, monthly, "prorated_next_billing_period")
    assert api.requests[-1].body["proration_billing_mode"] == "prorated_next_billing_period"
    with pytest.raises(ProviderError):
        client.preview_update(subscription, monthly, "full_immediately")
    scheduled = client.cancel(subscription, immediately=False)
    assert api.requests[-1].body == {"effective_from": "next_billing_period"}
    assert scheduled.scheduled_action == "cancel" and scheduled.status == "active"
    with pytest.raises(ProviderError) as raised:
        client.update_items(subscription, monthly, "prorated_next_billing_period")
    assert raised.value.code == "pending_change"
    removed = client.remove_scheduled_change(subscription)
    assert api.requests[-1].body == {"scheduled_change": None}
    assert removed.scheduled_action is None
    method = client.payment_method_transaction(subscription)
    assert api.requests[-1].path.endswith("/update-payment-method-transaction")
    assert method.startswith("txn_")
    url = client.invoice_url(transaction)
    assert url.startswith("https://")
    assert api.requests[-1].path == f"/transactions/{transaction}/invoice"
    ended = client.cancel(subscription, immediately=True)
    assert api.requests[-1].body == {"effective_from": "immediately"}
    assert ended.status == "canceled"
    with pytest.raises(ProviderError) as raised:
        client.cancel(subscription, immediately=True)
    assert raised.value.code == "subscription_canceled"
    fetched = client.get_subscription(subscription)
    assert fetched.status == "canceled" and fetched.canceled_at is not None
    # Every request carried the version header, and no body named a person.
    assert {request.headers["Paddle-Version"] for request in api.requests} == {"1"}
    assert all("example.test" not in json.dumps(request.body) for request in api.requests)
