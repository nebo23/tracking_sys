"""The Paddle webhook and its records (specification 017-C, D-103 D6, D7, D9 and D11).

Cases BL06 (signature, body bound and rate), BL07 (idempotency and order), BL08 (activation),
BL10 (failed payments), BL12 (payments and adjustments), BL16 (unmatched events and duplicate
subscriptions), BL19 (separation from agency-client revenue) and the log part of BL22 of the
entry review's verification matrix. Paddle is the synthetic server of tests/paddle_api.py and
its events are signed by the synthetic sender; the database is the disposable one.
"""

import ast
import copy
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from billing_support import current_plan, database_now, make_billing_lab, set_trial, standing
from paddle_api import API_KEY, WEBHOOK_SECRET, created, event, paddle_id, signed
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import agency_plans
from app.config import BACKEND_ROOT
from app.logging_config import AllowlistFormatter
from app.models import (
    AgencySubscription,
    BillingAdjustment,
    BillingCheckout,
    BillingEvent,
    BillingPayment,
)

pytestmark = pytest.mark.integration
UNLIMITED = {
    "clients_limit": None,
    "seats_limit": None,
    "connections_limit": None,
    "managed_links_limit": None,
    "tracked_events_limit": None,
}


def _count(db, model, *where) -> int:
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def _events(db) -> list[BillingEvent]:
    with Session(db.migration) as session:
        rows = list(session.scalars(select(BillingEvent).order_by(BillingEvent.received_at)))
        for row in rows:
            session.expunge(row)
        return rows


def _subscription(db, provider_id) -> AgencySubscription:
    with Session(db.migration) as session:
        row = session.scalar(
            select(AgencySubscription).where(
                AgencySubscription.provider_subscription_id == provider_id
            )
        )
        session.expunge(row)
        return row


def _plan(db, key: str) -> None:
    code, result = agency_plans.run(
        db.runtime, "create-plan", key=key, name=key.title(), reason="new_offer", limits=UNLIMITED
    )
    assert code == 0, result


def _ignored(subscription_id: str | None = None) -> dict:
    return event("transaction.created", {"id": paddle_id("txn"), "status": "draft"})


def test_bl06_webhook_signature_bound_and_rate(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    accepted = lab.deliver(_ignored())
    assert accepted.status_code == 200 and accepted.json() == {"status": "received"}
    assert _count(w.db, BillingEvent) == 1
    now = int(time.time())
    other_secret = "_".join(("pdl", "ntfset", "01" + "c" * 24, "X" * 32))
    payload = _ignored()
    body, header = signed(payload)
    refused = (
        lab.deliver(_ignored(), secret=other_secret),
        lab.hook().post(
            "/billing/paddle/webhook",
            content=body.replace(b"draft", b"ready"),
            headers={"Paddle-Signature": header, "Content-Type": "application/json"},
        ),
        lab.deliver(_ignored(), ts=now - 301),
        lab.deliver(_ignored(), ts=now + 301),
        lab.deliver(_ignored(), header=False),
        lab.deliver(_ignored(), header="ts=1;h1=zz"),
        lab.deliver(_ignored(), header=f"ts={now}"),
        lab.deliver(_ignored(), header="garbage"),
    )
    for response in refused:
        assert response.status_code == 401, response.text
        assert response.json() == {"error": "invalid_signature"}
    assert _count(w.db, BillingEvent) == 1
    # Within the 300-second window, and with a second h1 of a rotation, it is accepted.
    assert lab.deliver(_ignored(), ts=now - 299).status_code == 200
    body, header = signed(_ignored())
    rotated = f"{header};h1={'0' * 64}"
    response = lab.hook().post(
        "/billing/paddle/webhook",
        content=body,
        headers={"Paddle-Signature": rotated, "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    # A verified body that is not an event is refused without being stored.
    assert lab.deliver(b"[]").status_code == 400
    assert lab.deliver({"event_id": "evt_bad", "event_type": "x.y", "data": {}}).status_code == 400
    # The body bound is 256 KiB, before anything else.
    large = lab.deliver(event("transaction.created", {"pad": "x" * 262144}))
    assert large.status_code == 413 and large.json() == {"error": "request_too_large"}
    assert _count(w.db, BillingEvent) == 3
    # The per-peer rate applies before the signature check (the bucket of this peer already
    # counts the deliveries above, within the same minute).
    tight = make_billing_lab(w, api, ingest_trusted_per_minute=2)
    limited = tight.deliver(_ignored(), header=False)
    assert limited.status_code == 429 and limited.json() == {"error": "rate_limited"}
    assert int(limited.headers["Retry-After"]) >= 1
    # While billing is disabled, the webhook answers 503 and stores nothing.
    disabled = make_billing_lab(w, api, billing_enabled=False)
    off = disabled.deliver(_ignored())
    assert off.status_code == 503 and off.json() == {"error": "billing_unavailable"}
    assert _count(w.db, BillingEvent) == 3


def test_bl07_repeated_and_older_events(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    start = database_now(w.db)
    subscription = lab.subscribe(w.a, price, start)
    assert standing(w.db, w.a).standing == "subscribed"
    version = standing(w.db, w.a).version
    events = len(_events(w.db))
    # The same event twice has one effect.
    past_due = copy.deepcopy(subscription) | {"status": "past_due"}
    notice = event("subscription.past_due", past_due, occurred_at=start + timedelta(minutes=10))
    lab.delivered(notice)
    after = standing(w.db, w.a)
    assert (after.standing, after.version) == ("past_due", version + 1)
    lab.delivered(notice)
    assert standing(w.db, w.a).version == version + 1
    assert len(_events(w.db)) == events + 1
    # An older event after a newer one is stale and changes nothing.
    older = event(
        "subscription.updated",
        copy.deepcopy(subscription),
        occurred_at=start + timedelta(minutes=5),
    )
    lab.delivered(older)
    assert standing(w.db, w.a).standing == "past_due"
    stored = {row.provider_event_id: row for row in _events(w.db)}
    assert stored[older["event_id"]].outcome == "stale"
    assert stored[notice["event_id"]].outcome == "applied"
    assert _subscription(w.db, subscription["id"]).status == "past_due"


def test_bl08_activation_ends_trial_and_hold(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    _plan(w.db, "agency-pro")
    pro = lab.price("agency-pro", 9900)
    now = database_now(w.db)
    # A trialing agency subscribes: the trial ends at once and the price's plan applies.
    set_trial(w.db, w.a, now + timedelta(days=10))
    lab.subscribe(w.a, pro, now)
    row = standing(w.db, w.a)
    assert (row.standing, row.reason) == ("subscribed", "subscription_active")
    assert current_plan(w.db, w.a) == ("agency-pro", 2, "billing", "subscription")
    assert row.provider_customer_id is not None
    checkout = _count(w.db, BillingCheckout, BillingCheckout.status == "completed")
    assert checkout == 1
    # An agency on hold subscribes: the hold ends at once.
    set_trial(w.db, w.b, now - timedelta(minutes=1))
    assert lab.worker()["trials_ended"] == 1
    assert current_plan(w.db, w.b)[0] == "billing_hold"
    lab.subscribe(w.b, pro, now)
    held = standing(w.db, w.b)
    assert (held.standing, held.hold_started_at) == ("subscribed", None)
    assert current_plan(w.db, w.b) == ("agency-pro", 3, "billing", "subscription")


def test_bl10_past_due_recovery_and_cancellation(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    _plan(w.db, "agency-pro")
    pro = lab.price("agency-pro", 9900)
    start = database_now(w.db)
    subscription = lab.subscribe(w.a, pro, start)
    plan = current_plan(w.db, w.a)
    # A failed renewal: past_due keeps the plan while Paddle retries.
    lab.delivered(
        event(
            "subscription.past_due",
            subscription | {"status": "past_due"},
            occurred_at=start + timedelta(days=30),
        )
    )
    assert (standing(w.db, w.a).standing, current_plan(w.db, w.a)) == ("past_due", plan)
    # The payment is recovered: subscribed again, same plan.
    lab.delivered(
        event(
            "subscription.updated",
            subscription | {"status": "active"},
            occurred_at=start + timedelta(days=31),
        )
    )
    row = standing(w.db, w.a)
    assert (row.standing, row.reason, current_plan(w.db, w.a)) == (
        "subscribed",
        "payment_recovered",
        plan,
    )
    # A cancellation after the last retry puts the agency on hold on the billing_hold plan.
    lab.delivered(
        event(
            "subscription.canceled",
            subscription | {"status": "canceled", "canceled_at": "2027-01-30T00:00:00Z"},
            occurred_at=start + timedelta(days=60),
        )
    )
    row = standing(w.db, w.a)
    assert (row.standing, row.reason) == ("hold", "subscription_canceled")
    assert current_plan(w.db, w.a)[0] == "billing_hold"
    assert lab.worker()["messages"]["billing_hold"] == 1
    # A paused subscription also holds, and a resumed one restores the plan.
    other = lab.subscribe(w.b, pro, start)
    lab.delivered(
        event(
            "subscription.paused",
            other | {"status": "paused"},
            occurred_at=start + timedelta(days=1),
        )
    )
    assert (standing(w.db, w.b).standing, standing(w.db, w.b).reason) == (
        "hold",
        "subscription_paused",
    )
    lab.delivered(
        event(
            "subscription.resumed",
            other | {"status": "active"},
            occurred_at=start + timedelta(days=2),
        )
    )
    assert standing(w.db, w.b).standing == "subscribed"
    assert current_plan(w.db, w.b)[0] == "agency-pro"


def test_bl12_payments_and_adjustments(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price(amount=2900)
    start = database_now(w.db)
    subscription = lab.subscribe(w.a, price, start)
    with Session(w.db.migration) as session:
        payment = session.scalar(select(BillingPayment).where(BillingPayment.agency_id == w.a))
    assert (payment.status, payment.origin, payment.currency) == ("completed", "web", "USD")
    assert (payment.subtotal_cents, payment.tax_cents, payment.total_cents) == (2900, 290, 3190)
    assert payment.invoice_number and payment.billed_at
    assert payment.subscription_id == _subscription(w.db, subscription["id"]).id
    version = standing(w.db, w.a).version
    # A refund requested, then approved: recorded, and no standing changes.
    refund = {
        "id": paddle_id("adj"),
        "action": "refund",
        "status": "pending_approval",
        "transaction_id": payment.provider_transaction_id,
        "subscription_id": subscription["id"],
        "customer_id": subscription["customer_id"],
        "currency_code": "USD",
        "reason": "Synthetic reason that is never stored",
        "totals": {"subtotal": "2900", "tax": "290", "total": "3190", "fee": "0"},
    }
    lab.delivered(event("adjustment.created", refund, occurred_at=start + timedelta(hours=1)))
    lab.delivered(
        event(
            "adjustment.updated",
            refund | {"status": "approved"},
            occurred_at=start + timedelta(hours=2),
        )
    )
    with Session(w.db.migration) as session:
        adjustment = session.scalar(select(BillingAdjustment))
    assert (adjustment.action, adjustment.status, adjustment.total_cents) == (
        "refund",
        "approved",
        3190,
    )
    assert adjustment.payment_id == payment.id
    after = standing(w.db, w.a)
    assert (after.standing, after.version) == ("subscribed", version)
    # A renewal: billed, then completed; and an adjustment that arrives before its payment is
    # linked once the payment is recorded.
    renewal = {
        "id": paddle_id("txn"),
        "status": "completed",
        "origin": "subscription_recurring",
        "subscription_id": subscription["id"],
        "customer_id": subscription["customer_id"],
        "currency_code": "USD",
        "details": {"totals": {"subtotal": "2900", "tax": "290", "total": "3190"}},
        "billed_at": "2026-12-28T00:00:00Z",
        "invoice_number": "325-00002",
        "custom_data": subscription.get("custom_data"),
    }
    early = refund | {"id": paddle_id("adj"), "transaction_id": renewal["id"], "action": "credit"}
    lab.delivered(event("adjustment.created", early, occurred_at=start + timedelta(days=30)))
    lab.delivered(event("transaction.completed", renewal, occurred_at=start + timedelta(days=30)))
    with Session(w.db.migration) as session:
        renewed = session.scalar(
            select(BillingPayment).where(BillingPayment.provider_transaction_id == renewal["id"])
        )
        linked = session.scalar(
            select(BillingAdjustment).where(BillingAdjustment.provider_adjustment_id == early["id"])
        )
    assert renewed.origin == "subscription_recurring" and linked.payment_id == renewed.id
    # Only allowlisted fields are stored.
    stored = json.dumps([row.fields for row in _events(w.db)])
    for forbidden in ("reason", "Synthetic reason", "address", "email", "name"):
        assert forbidden not in stored


def test_bl16_unmatched_and_duplicates(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    start = database_now(w.db)
    # An event of an unknown subscription is stored unmatched, answered 200 and listed.
    stranger = lab.paddle.pay(lab.provider.create_transaction(price["provider_price_id"], None, {}))
    lab.delivered(event("subscription.updated", stranger, occurred_at=start))
    lab.delivered(created(stranger, paddle_id("txn"), occurred_at=start))
    # custom_data that names another agency than the checkout's is a binding conflict.
    _, transaction = lab.open_checkout(w.a, price)
    forged = lab.paddle.pay(transaction)
    forged["custom_data"] = {"agency_id": str(w.b), "checkout_id": str(uuid4())}
    lab.delivered(created(forged, transaction, occurred_at=start))
    code, unmatched = lab.command("events", limit=10)
    assert code == 0
    assert {(item["provider_subscription_id"], item["error_code"]) for item in unmatched} == {
        (stranger["id"], None),
        (forged["id"], "binding_conflict"),
    }
    assert standing(w.db, w.a).standing == "complimentary"
    # Out of order: an update that arrives before subscription.created is replayed at binding.
    _, transaction = lab.open_checkout(w.b, price)
    first = lab.paddle.pay(transaction)
    later = first | {"scheduled_change": None, "status": "past_due"}
    early = event("subscription.updated", later, occurred_at=start + timedelta(minutes=5))
    lab.delivered(early)
    lab.delivered(created(first, transaction, occurred_at=start))
    row = _subscription(w.db, first["id"])
    assert row.status == "past_due" and standing(w.db, w.b).standing == "past_due"
    replayed = {item.provider_event_id: item for item in _events(w.db)}[early["event_id"]]
    assert (replayed.outcome, replayed.agency_id) == ("applied", w.b)
    # A second paid checkout of the same agency is a duplicate: it changes no standing and is
    # listed, and nothing is canceled automatically.
    lab.subscribe(w.a, price, start)
    duplicate = lab.subscribe(w.a, price, start + timedelta(minutes=1))
    assert _subscription(w.db, duplicate["id"]).duplicate is True
    lab.delivered(
        event(
            "subscription.canceled",
            duplicate | {"status": "canceled"},
            occurred_at=start + timedelta(hours=1),
        )
    )
    assert standing(w.db, w.a).standing == "subscribed"
    code, duplicates = lab.command("duplicates")
    assert code == 0 and [item["provider_subscription_id"] for item in duplicates] == [
        duplicate["id"]
    ]
    assert duplicates[0]["primary_subscription_id"] is not None
    assert not [path for path in lab.paddle.paths() if path.endswith("/cancel")]


def test_bl19_billing_never_touches_client_revenue(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    start = database_now(w.db)
    subscription = lab.subscribe(w.a, price, start)
    lab.delivered(
        event(
            "adjustment.created",
            {
                "id": paddle_id("adj"),
                "action": "refund",
                "status": "approved",
                "transaction_id": next(iter(lab.paddle.transactions)),
                "subscription_id": subscription["id"],
                "currency_code": "USD",
                "totals": {"total": "100"},
            },
            occurred_at=start + timedelta(hours=1),
        )
    )
    with w.db.migration.connect() as connection:
        for table in (
            "revenue_evidence",
            "ledger_receipts",
            "ledger_movements",
            "ledger_transactions",
            "payment_sources",
            "payment_callback_diagnostics",
            "revenue_imports",
        ):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
    # The 015 callback route behaves as before: Paymob is off, so it answers 503.
    response = lab.hook().post("/payments/paymob/callback/ppk_" + "a" * 43, content=b"{}")
    assert response.status_code == 503 and response.json() == {"error": "payments_unavailable"}
    # No billing module imports agency-client revenue.
    modules = (
        "app/services/billing.py",
        "app/services/billing_events.py",
        "app/billing/paddle.py",
        "app/api/billing.py",
        "app/agency_billing.py",
        "app/billing_worker.py",
    )
    forbidden = ("app.services.revenue", "app.ledger", "app.services.payments", "app.payments")
    for module in modules:
        tree = ast.parse(Path(BACKEND_ROOT, module).read_bytes())
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not {name for name in imported if name and name.startswith(forbidden)}, module


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []
        self.events: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.events.append(record.getMessage())
        self.lines.append(AllowlistFormatter().format(record))


def test_bl22_no_secret_in_logs_answers_or_outputs(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    collected = _Collect()
    logger = logging.getLogger("tracking")
    logger.addHandler(collected)
    try:
        _secrets_stay_out(w, lab, collected)
    finally:
        logger.removeHandler(collected)


def _secrets_stay_out(w, lab, collected) -> None:
    price = lab.price()
    start = database_now(w.db)
    subscription = lab.subscribe(w.a, price, start)
    stranger = event("subscription.updated", subscription | {"id": paddle_id("sub")})
    body, header = signed(stranger)
    answers = [
        lab.hook().post(
            "/billing/paddle/webhook",
            content=body,
            headers={"Paddle-Signature": header, "Content-Type": "application/json"},
        ),
        lab.deliver(_ignored(), secret="_".join(("pdl", "ntfset", "0" * 26, "Y" * 32))),
    ]
    output = json.dumps(
        [
            lab.worker(now=start + timedelta(days=1)),
            lab.command("status", agency=w.a),
            lab.command("events", limit=5),
            lab.command("prices"),
        ]
    )
    texts = collected.lines + [answer.text for answer in answers] + [output]
    signature = header.split("h1=")[1]
    for forbidden in (
        API_KEY,
        WEBHOOK_SECRET,
        signature,
        "owner_a@example.test",
        "Synthetic Agency",
        "example.test",
    ):
        assert not any(forbidden in item for item in texts), forbidden
    assert "billing_event_unmatched" in collected.events
    assert all('"event": "log_event_rejected"' not in line for line in collected.lines)
    assert {answer.status_code for answer in answers} == {200, 401}
    assert datetime.now(UTC) > start
