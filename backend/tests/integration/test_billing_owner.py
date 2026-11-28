"""The Owner routes, closure actions, reconciliation and the journey (017-C, D-103).

Cases BL01 (the price list), BL05 (checkout), BL09 (plan changes), BL11 (cancellation), BL13
(invoice), BL14 (closure), BL15 (purge), BL17 (reconciliation) and BL23 (the end-to-end journey)
of the entry review's verification matrix, with the retention of billing events and checkouts.
Paddle is the synthetic server of tests/paddle_api.py; the database is the disposable one.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from billing_support import (
    current_plan,
    database_now,
    make_billing_lab,
    owner_membership,
    standing,
)
from offboarding_support import close_agency, end_grace_period, request_closure, status_of
from paddle_api import API_KEY, CLIENT_TOKEN, INVOICE_HOST, event, paddle_id
from report_support import grant, key_client, service_key
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import agency_plans
from app.billing.paddle import PaddleClient
from app.config import LifecycleSettings
from app.logging_config import AllowlistFormatter
from app.models import (
    AgencySubscription,
    AuditEvent,
    BillingAction,
    BillingCheckout,
    BillingEvent,
    BillingPayment,
)
from app.services.agency_offboarding import run_offboarding
from app.services.billing_actions import reconcile_one
from app.services.billing_owner import BillingOwnerService
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration
UNLIMITED = {
    "clients_limit": None,
    "seats_limit": None,
    "connections_limit": None,
    "managed_links_limit": None,
    "tracked_events_limit": None,
}


def _plan(db, key: str) -> None:
    code, result = agency_plans.run(
        db.runtime, "create-plan", key=key, name=key.title(), reason="new_offer", limits=UNLIMITED
    )
    assert code == 0, result


def _count(db, model, *where) -> int:
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def _audits(db, action: str) -> int:
    return _count(db, AuditEvent, AuditEvent.action == action)


def _subscription(db, provider_id: str) -> AgencySubscription:
    with Session(db.migration) as session:
        row = session.scalar(
            select(AgencySubscription).where(
                AgencySubscription.provider_subscription_id == provider_id
            )
        )
        session.expunge(row)
        return row


def _actions(db, agency) -> list[tuple[str, str, str | None]]:
    with Session(db.migration) as session:
        return [
            (row.action, row.status, row.last_error)
            for row in session.scalars(
                select(BillingAction)
                .where(BillingAction.agency_id == agency)
                .order_by(BillingAction.created_at, BillingAction.id)
            )
        ]


def test_bl01_price_list_offers_only_offered_prices(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    _plan(w.db, "agency-pro")
    monthly = lab.price()
    annual = lab.price(amount=29000, interval="year")
    pro = lab.price("agency-pro", 9900)
    assert lab.command("retire-price", price_id=annual["provider_price_id"])[0] == 0
    viewer = lab.browser("viewer")
    answer = viewer.get("/billing/prices")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["environment"], body["client_token"]) == ("sandbox", CLIENT_TOKEN)
    assert {item["id"] for item in body["prices"]} == {monthly["id"], pro["id"]}
    offered = {item["id"]: item for item in body["prices"]}
    assert offered[pro["id"]]["plan"]["key"] == "agency-pro"
    assert offered[monthly["id"]]["plan"]["limits"]["clients"] == 5
    assert (offered[monthly["id"]]["amount_cents"], offered[monthly["id"]]["currency"]) == (
        2900,
        "USD",
    )
    # Browser sessions only; while billing is disabled the list is unavailable.
    assert api.new_client().get("/billing/prices").status_code == 401
    raw = service_key(w, api, [grant(w.a1)])
    assert key_client(api, raw).get("/billing/prices").status_code == 401
    off = make_billing_lab(w, api, billing_enabled=False).browser("viewer")
    refused = off.get("/billing/prices")
    assert refused.status_code == 503 and refused.json() == {"error": "billing_unavailable"}


def test_bl05_checkout_roles_and_refusals(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price, other = lab.price(), lab.price(amount=29000, interval="year")
    url = f"/agencies/{w.a}/billing/checkout"
    for name in ("admin", "analyst", "viewer", "owner_b"):
        assert lab.browser(name).post(url, json={"price_id": price["id"]}).status_code == 403
    raw = service_key(w, api, [grant(w.a1)])
    assert key_client(api, raw).post(url, json={"price_id": price["id"]}).status_code == 401
    owner = lab.browser("owner_a")
    unsigned = lab.browser("owner_a")
    unsigned.headers.pop("X-CSRF-Token")
    assert unsigned.post(url, json={"price_id": price["id"]}).json() == {"error": "csrf_failed"}
    first = owner.post(url, json={"price_id": price["id"]})
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["transaction_id"].startswith("txn_") and body["status"] == "open"
    # The same price while it is open returns the same transaction; Paddle is called once.
    again = owner.post(url, json={"price_id": price["id"]})
    assert again.status_code == 200 and again.json() == body
    assert lab.paddle.paths().count("POST /transactions") == 1
    sent = lab.paddle.requests[-1].body
    assert sent["custom_data"] == {"agency_id": str(w.a), "checkout_id": body["checkout_id"]}
    assert sent["currency_code"] == "USD" and sent["collection_mode"] == "automatic"
    # Another price replaces the open checkout; one checkout is open at a time.
    replaced = owner.post(url, json={"price_id": other["id"]})
    assert (
        replaced.status_code == 201 and replaced.json()["transaction_id"] != body["transaction_id"]
    )
    assert _count(w.db, BillingCheckout, BillingCheckout.agency_id == w.a) == 2
    assert (
        _count(
            w.db,
            BillingCheckout,
            BillingCheckout.agency_id == w.a,
            BillingCheckout.status == "open",
        )
        == 1
    )
    assert _audits(w.db, "billing.checkout_created") == 2
    # Prices that are not offered, a provider failure and disabled billing change nothing.
    assert lab.command("retire-price", price_id=other["provider_price_id"])[0] == 0
    for price_id in (other["id"], str(uuid4())):
        refused = owner.post(url, json={"price_id": price_id})
        assert refused.json() == {"error": "price_not_offered"}
    lab.paddle.fail_next(503, "internal_error")
    failed = owner.post(url, json={"price_id": price["id"]})
    assert failed.status_code == 503 and failed.json() == {"error": "billing_provider_unavailable"}
    assert _count(w.db, BillingCheckout, BillingCheckout.agency_id == w.a) == 2
    off = make_billing_lab(w, api, billing_enabled=False).browser("owner_a")
    assert off.post(url, json={"price_id": price["id"]}).json() == {"error": "billing_unavailable"}
    # A subscription that has not ended refuses a new checkout.
    lab.subscribe(w.a, price)
    blocked = owner.post(url, json={"price_id": price["id"]})
    assert blocked.status_code == 409 and blocked.json() == {"error": "already_subscribed"}
    # A closing agency is refused like any agency that is not active.
    with w.db.migration.begin() as connection:
        connection.execute(text("UPDATE agencies SET status = 'closing' WHERE id = :b"), {"b": w.b})
    b = lab.browser("owner_b")
    assert (
        b.post(f"/agencies/{w.b}/billing/checkout", json={"price_id": price["id"]}).status_code
        == 403
    )


def test_bl05_one_open_checkout_under_concurrency(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    original = lab.paddle.__call__

    # Paddle answers slowly, so the second request waits for the agency lock held by the first.
    def slow(method, url, headers, body):
        if method == "POST":
            time.sleep(0.5)
        return original(method, url, headers, body)

    gate = Barrier(2)

    def checkout():
        gate.wait()
        with Session(w.db.runtime, expire_on_commit=False) as session, session.begin():
            service = BillingOwnerService(
                session, w.users.owner_a, lab.config, PaddleClient(API_KEY, "sandbox", slow)
            )
            row, created = service.checkout(w.a, price["id"])
            return row.provider_transaction_id, created

    with ThreadPoolExecutor(2) as pool:
        results = [future.result() for future in [pool.submit(checkout) for _ in range(2)]]
    assert len({transaction for transaction, _ in results}) == 1
    assert sorted(created for _, created in results) == [False, True]
    assert lab.paddle.paths().count("POST /transactions") == 1
    assert _count(w.db, BillingCheckout, BillingCheckout.agency_id == w.a) == 1


def test_bl09_plan_changes_and_preview(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    _plan(w.db, "agency-pro")
    basic, pro = lab.price(amount=2900), lab.price("agency-pro", 9900)
    yearly = lab.price("agency-pro", 99000, "year")
    start = database_now(w.db)
    subscription = lab.subscribe(w.a, basic, start)
    owner = lab.browser("owner_a")
    url = f"/agencies/{w.a}/billing/change"
    # A preview returns Paddle's amounts and changes nothing.
    preview = owner.post(url, json={"price_id": pro["id"], "preview": True})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["proration"] == "prorated_immediately"
    assert body["immediate"]["subtotal_cents"] == 7000 and body["result"]["action"] == "charge"
    assert (
        lab.paddle.subscriptions[subscription["id"]]["items"][0]["price"]["id"]
        == basic["provider_price_id"]
    )
    assert current_plan(w.db, w.a)[0] == "development"
    # An upgrade is charged at once; the limits follow subscription.updated only.
    requested = owner.post(url, json={"price_id": pro["id"]})
    assert requested.status_code == 202
    assert requested.json() == {"status": "requested", "proration": "prorated_immediately"}
    assert lab.paddle.requests[-1].body["proration_billing_mode"] == "prorated_immediately"
    assert current_plan(w.db, w.a)[0] == "development"
    changed = lab.paddle.subscriptions[subscription["id"]]
    lab.delivered(event("subscription.updated", changed, occurred_at=start + timedelta(hours=1)))
    assert current_plan(w.db, w.a) == ("agency-pro", 2, "billing", "subscription")
    assert _audits(w.db, "billing.plan_change_requested") == 1
    # A downgrade is credited on the next bill; monthly to annual is charged at once.
    down = owner.post(url, json={"price_id": basic["id"], "preview": True}).json()
    assert down["proration"] == "prorated_next_billing_period"
    up = owner.post(url, json={"price_id": yearly["id"], "preview": True}).json()
    assert up["proration"] == "prorated_immediately"
    assert owner.post(url, json={"price_id": pro["id"]}).json() == {"error": "same_price"}
    assert lab.browser("admin").post(url, json={"price_id": basic["id"]}).status_code == 403
    # Within 30 minutes of the renewal, and while past due, a change is not allowed.
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE agency_subscriptions SET next_billed_at = now() + interval '20 minutes' "
                "WHERE provider_subscription_id = :s"
            ),
            {"s": subscription["id"]},
        )
    soon = owner.post(url, json={"price_id": basic["id"], "preview": True})
    assert soon.status_code == 409 and soon.json() == {"error": "change_not_allowed"}
    lab.delivered(
        event(
            "subscription.past_due",
            changed | {"status": "past_due"},
            occurred_at=start + timedelta(hours=2),
        )
    )
    assert owner.post(url, json={"price_id": basic["id"]}).json() == {"error": "change_not_allowed"}
    # Paddle's refusal of a change becomes change_not_allowed too.
    lab.delivered(
        event(
            "subscription.updated",
            changed | {"status": "active", "next_billed_at": "2030-01-01T00:00:00Z"},
            occurred_at=start + timedelta(hours=3),
        )
    )
    lab.paddle.fail_next(400, "subscription_locked_pending_changes")
    refused = owner.post(url, json={"price_id": basic["id"]})
    assert refused.status_code == 409 and refused.json() == {"error": "change_not_allowed"}


def test_bl11_cancel_undo_and_resubscribe(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    start = database_now(w.db)
    subscription = lab.subscribe(w.a, price, start)
    owner = lab.browser("owner_a")
    url = f"/agencies/{w.a}/billing/cancel"
    cancelled = owner.post(url)
    assert cancelled.status_code == 200, cancelled.text
    scheduled = cancelled.json()["scheduled_change"]
    assert scheduled["action"] == "cancel"
    assert _subscription(w.db, subscription["id"]).cancel_origin == "owner"
    entity = lab.paddle.subscriptions[subscription["id"]]
    lab.delivered(event("subscription.updated", entity, occurred_at=start + timedelta(hours=1)))
    # Access is kept until the scheduled cancellation takes effect.
    assert standing(w.db, w.a).standing == "subscribed"
    calls = len(lab.paddle.requests)
    assert owner.post(url).json()["scheduled_change"]["action"] == "cancel"
    assert len(lab.paddle.requests) == calls
    # Undo before the end of the period.
    assert owner.delete(url).status_code == 204
    assert lab.paddle.subscriptions[subscription["id"]]["scheduled_change"] is None
    assert _subscription(w.db, subscription["id"]).cancel_origin is None
    lab.delivered(event("subscription.updated", entity, occurred_at=start + timedelta(hours=2)))
    assert owner.delete(url).json() == {"error": "no_scheduled_cancel"}
    assert (_audits(w.db, "billing.cancel_scheduled"), _audits(w.db, "billing.cancel_removed")) == (
        1,
        1,
    )
    # The effective cancellation puts the agency on hold; it can subscribe again from hold.
    assert owner.post(url).status_code == 200
    lab.delivered(
        event(
            "subscription.canceled",
            entity | {"status": "canceled", "canceled_at": "2026-12-28T00:00:00Z"},
            occurred_at=start + timedelta(days=30),
        )
    )
    assert standing(w.db, w.a).standing == "hold"
    assert owner.post(url).json() == {"error": "not_subscribed"}
    again = owner.post(f"/agencies/{w.a}/billing/checkout", json={"price_id": price["id"]})
    assert again.status_code == 201, again.text
    lab.pay(again.json()["transaction_id"], start + timedelta(days=31))
    assert standing(w.db, w.a).standing == "subscribed"
    assert _count(w.db, AgencySubscription, AgencySubscription.agency_id == w.a) == 2
    # The payment-method transaction for Paddle.js.
    method = owner.post(f"/agencies/{w.a}/billing/payment-method")
    assert method.status_code == 200 and method.json()["transaction_id"].startswith("txn_")
    view = owner.get(f"/agencies/{w.a}/billing").json()
    assert (view["standing"], view["subscription"]["status"]) == ("subscribed", "active")
    assert view["last_payment"]["total_cents"] == 3190 and view["plan"]["key"] == "development"
    assert lab.browser("analyst").get(f"/agencies/{w.a}/billing").status_code == 403


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(AllowlistFormatter().format(record))


def test_bl13_invoice_redirect(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    lab.subscribe(w.a, price)
    owner = lab.browser("owner_a")
    (payment,) = owner.get(f"/agencies/{w.a}/billing/payments").json()
    assert (payment["status"], payment["total_cents"], payment["invoice_available"]) == (
        "completed",
        3190,
        True,
    )
    collected = _Collect()
    logger = logging.getLogger("tracking")
    logger.addHandler(collected)
    try:
        invoice = f"/agencies/{w.a}/billing/payments/{payment['id']}/invoice"
        for name in ("owner_a", "admin"):
            redirect = lab.browser(name).get(invoice, follow_redirects=False)
            assert redirect.status_code == 302, redirect.text
            assert redirect.headers["location"].startswith(INVOICE_HOST)
        assert lab.browser("analyst").get(invoice, follow_redirects=False).status_code == 403
        foreign = f"/agencies/{w.b}/billing/payments/{payment['id']}/invoice"
        assert lab.browser("owner_b").get(foreign, follow_redirects=False).status_code == 403
    finally:
        logger.removeHandler(collected)
    # The address is fetched at request time and is never stored or logged.
    assert not any(INVOICE_HOST in line for line in collected.lines)
    with w.db.migration.connect() as connection:
        for table in ("billing_payments", "billing_events", "audit_events"):
            found = connection.execute(
                text(f"SELECT count(*) FROM {table} t WHERE t::text LIKE :host"),
                {"host": f"%{INVOICE_HOST}%"},
            ).scalar_one()
            assert found == 0, table
    # A payment that is not completed, or of zero value, has no invoice.
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO billing_payments (id, agency_id, provider_transaction_id, status, "
                "origin, currency, subtotal_cents, tax_cents, total_cents, last_event_at) VALUES "
                "(:id, :a, :t, 'completed', 'subscription_payment_method_change', 'USD', 0, 0, 0, "
                "now())"
            ),
            {"id": (zero := uuid4()), "a": w.a, "t": paddle_id("txn")},
        )
    unavailable = owner.get(f"/agencies/{w.a}/billing/payments/{zero}/invoice")
    assert unavailable.status_code == 409 and unavailable.json() == {"error": "invoice_unavailable"}


def test_bl14_closure_actions(authenticated_world, api, lifecycle_engine, lifecycle_settings):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    start = database_now(w.db)
    first = lab.subscribe(w.a, price, start)
    # A closure request queues the cancellation at the period end; the worker executes it.
    request_closure(w, api, w.a)
    assert _actions(w.db, w.a) == [("cancel_next_period", "pending", None)]
    assert lab.worker()["actions"] == {"done": 1, "skipped": 0, "retried": 0, "failed": 0}
    assert lab.paddle.subscriptions[first["id"]]["scheduled_change"]["action"] == "cancel"
    assert _subscription(w.db, first["id"]).cancel_origin == "closure"
    # A cancelled closure removes the closure's cancellation.
    assert w.signed_in("owner_a").delete(f"/agencies/{w.a}/closure").status_code == 204
    assert _actions(w.db, w.a)[-1] == ("remove_scheduled_cancel", "pending", None)
    assert lab.worker()["actions"]["done"] == 1
    assert lab.paddle.subscriptions[first["id"]]["scheduled_change"] is None
    assert _subscription(w.db, first["id"]).cancel_origin is None
    lab.delivered(
        event(
            "subscription.updated",
            lab.paddle.subscriptions[first["id"]],
            occurred_at=database_now(w.db),
        )
    )
    assert _subscription(w.db, first["id"]).scheduled_action is None
    # A request cancelled before the worker claimed its action is skipped; nothing is called.
    calls = len(lab.paddle.requests)
    request_closure(w, api, w.a)
    assert w.signed_in("owner_a").delete(f"/agencies/{w.a}/closure").status_code == 204
    assert _actions(w.db, w.a)[-1] == ("cancel_next_period", "skipped", "closure_cancelled")
    assert lab.worker()["actions"] == {"done": 0, "skipped": 0, "retried": 0, "failed": 0}
    assert len(lab.paddle.requests) == calls
    # An Owner's earlier cancellation is kept through a closure and its cancellation.
    second = lab.subscribe(w.b, price, start)
    assert lab.browser("owner_b").post(f"/agencies/{w.b}/billing/cancel").status_code == 200
    request_closure(w, api, w.b, owner="owner_b")
    assert _actions(w.db, w.b) == []
    assert w.signed_in("owner_b").delete(f"/agencies/{w.b}/closure").status_code == 204
    assert _actions(w.db, w.b) == []
    assert lab.paddle.subscriptions[second["id"]]["scheduled_change"]["action"] == "cancel"
    # The completion cancels at once, without a refund; failures retry, a canceled
    # subscription is skipped.
    request_closure(w, api, w.b, owner="owner_b")
    end_grace_period(w.db, w.b)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["deleted"].get("agency_closures_completed") == 1
    assert _actions(w.db, w.b) == [("cancel_now", "pending", None)]
    lab.paddle.fail_next(503, "internal_error")
    assert lab.worker()["actions"]["retried"] == 1
    assert _actions(w.db, w.b) == [("cancel_now", "pending", "provider_unavailable")]
    later = database_now(w.db) + timedelta(minutes=6)
    assert lab.worker(now=later)["actions"]["done"] == 1
    assert lab.paddle.subscriptions[second["id"]]["status"] == "canceled"
    assert not [request for request in lab.paddle.requests if "adjustment" in request.path]


def test_bl15_purge_keeps_financial_records(
    authenticated_world, api, lifecycle_engine, lifecycle_settings
):
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
                "action": "credit",
                "status": "approved",
                "transaction_id": next(iter(lab.paddle.transactions)),
                "subscription_id": subscription["id"],
                "currency_code": "USD",
                "totals": {"total": "500"},
            },
            occurred_at=start + timedelta(hours=1),
        )
    )
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    assert run_offboarding(w.db.runtime, api.config)["offboarded"] == 1
    # The purge waits while the cancellation is pending.
    waiting = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert waiting["deleted"].get("agencies_purged", 0) == 0
    assert _actions(w.db, w.a) == [
        ("cancel_next_period", "pending", None),
        ("cancel_now", "pending", None),
    ]
    assert lab.worker()["actions"]["skipped"] == 1
    assert (
        run_lifecycle(lifecycle_engine, lifecycle_settings)["deleted"].get("agencies_purged", 0)
        == 0
    )
    assert lab.worker()["actions"]["done"] == 1
    assert _actions(w.db, w.a) == [
        ("cancel_next_period", "skipped", "superseded"),
        ("cancel_now", "done", None),
    ]
    assert lab.paddle.subscriptions[subscription["id"]]["status"] == "canceled"
    purged = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert purged["deleted"].get("agencies_purged") == 1
    with w.db.migration.connect() as connection:
        for table in ("agency_billing", "billing_checkouts", "billing_events", "billing_actions"):
            count = connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE agency_id = :a"), {"a": w.a}
            ).scalar_one()
            assert count == 0, table
        for table in ("agency_subscriptions", "billing_payments", "billing_adjustments"):
            count = connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE agency_id = :a"), {"a": w.a}
            ).scalar_one()
            assert count >= 1, table
    assert status_of(w.db, w.a) == "closed"
    assert standing(w.db, w.b) is not None


def test_bl17_reconciliation_corrects_a_missed_event(authenticated_world, api):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    # The webhooks happened before the reads; a read is newer than every event it follows.
    start = database_now(w.db) - timedelta(minutes=5)
    first = lab.subscribe(w.a, price, start)
    second = lab.subscribe(w.b, price, start)
    # A missed event: Paddle moved the subscription to past_due, but no webhook arrived.
    lab.paddle.subscriptions[first["id"]]["status"] = "past_due"
    passes = [lab.worker(limit=1)["reconciliation"] for _ in range(2)]
    assert [item["checked"] for item in passes] == [1, 1]
    assert sum(item["corrected"] for item in passes) == 1
    assert standing(w.db, w.a).standing == "past_due"
    with Session(w.db.migration) as session:
        recorded = session.scalar(
            select(BillingEvent).where(BillingEvent.source == "reconciliation")
        )
    assert (recorded.event_type, recorded.outcome, recorded.agency_id) == (
        "subscription.reconciled",
        "applied",
        w.a,
    )
    # Nothing is due again within 24 hours.
    assert lab.worker()["reconciliation"] == {"checked": 0, "corrected": 0, "failed": 0}
    assert _count(w.db, BillingEvent, BillingEvent.source == "reconciliation") == 1
    # A read older than the last webhook is recorded stale and changes nothing.
    row = _subscription(w.db, second["id"])
    snapshot = lab.provider.get_subscription(second["id"])
    stale = snapshot.__class__(**{**snapshot.__dict__, "status": "paused"})
    earlier = row.last_event_at - timedelta(minutes=1)
    assert reconcile_one(w.db.runtime, row.id, stale, earlier) == "checked"
    assert standing(w.db, w.b).standing == "subscribed"
    assert _count(w.db, BillingEvent, BillingEvent.outcome == "stale") == 1
    # The operator's reconcile reads an agency at once and audits a correction.
    lab.paddle.subscriptions[second["id"]]["status"] = "past_due"
    code, done = lab.command("reconcile", agency=w.b)
    assert (code, done) == (0, {"checked": 1, "corrected": 1, "failed": 0})
    assert _audits(w.db, "billing.reconciled") == 1
    # A provider failure is counted and retried on a later pass.
    lab.paddle.fail_next(503, "internal_error")
    later = database_now(w.db) + timedelta(hours=25)
    assert lab.worker(now=later, limit=1)["reconciliation"]["failed"] == 1


def test_billing_retention(authenticated_world, api, lifecycle_engine, lifecycle_settings):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    price = lab.price()
    lab.subscribe(w.a, price)
    member = owner_membership(w.db, w.b)
    with w.db.migration.begin() as connection:
        connection.execute(
            text("UPDATE billing_events SET received_at = now() - interval '396 days'")
        )
        connection.execute(
            text(
                "INSERT INTO billing_checkouts (id, agency_id, price_id, "
                "requested_by_membership_id, provider_transaction_id, status, created_at, "
                "expires_at) VALUES (:id, :b, :p, :m, :t, 'expired', now() - interval '32 days', "
                "now() - interval '31 days')"
            ),
            {"id": uuid4(), "b": w.b, "p": price["id"], "m": member, "t": paddle_id("txn")},
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["deleted"]["billing_events"] == 4
    assert result["deleted"]["billing_checkouts"] == 1
    # The completed checkout of the subscription stays until the purge.
    assert _count(w.db, BillingCheckout) == 1
    assert _count(w.db, BillingPayment) == 1
    assert (
        lifecycle_settings.billing_event_retention_days,
        lifecycle_settings.billing_checkout_retention_days,
    ) == (395, 30)
    for field, value in (
        ("billing_event_retention_days", 396),
        ("billing_checkout_retention_days", 31),
    ):
        with pytest.raises(ValueError):
            LifecycleSettings(
                _env_file=None, TRACKING_LIFECYCLE_PASSWORD="synthetic", **{field: value}
            )


def test_bl23_journey(authenticated_world, api, lifecycle_engine, lifecycle_settings):
    w = authenticated_world
    lab = make_billing_lab(w, api)
    _plan(w.db, "agency-pro")
    basic, pro = lab.price(amount=2900), lab.price("agency-pro", 9900)
    owner = lab.browser("owner_a")
    # A new agency tries the platform for 14 days, then holds.
    agency = owner.post("/agencies", json={"name": "Synthetic Journey Agency"}).json()["id"]
    trial = standing(w.db, agency)
    assert trial.standing == "trialing"
    assert lab.worker(now=trial.trial_ends_at + timedelta(minutes=1))["trials_ended"] == 1
    held = owner.post(f"/agencies/{agency}/clients", json={"name": "Held client"})
    assert held.status_code == 409 and held.json()["error"] == "plan_limit_reached"
    # It checks out from hold and is activated.
    checkout = owner.post(f"/agencies/{agency}/billing/checkout", json={"price_id": basic["id"]})
    assert checkout.status_code == 201, checkout.text
    start = database_now(w.db)
    subscription = lab.pay(checkout.json()["transaction_id"], start)
    assert standing(w.db, agency).standing == "subscribed"
    assert (
        owner.post(f"/agencies/{agency}/clients", json={"name": "First client"}).status_code == 201
    )
    # It upgrades: charged at once, the plan follows Paddle's event.
    upgrade = owner.post(f"/agencies/{agency}/billing/change", json={"price_id": pro["id"]})
    assert upgrade.status_code == 202
    entity = lab.paddle.subscriptions[subscription["id"]]
    lab.delivered(event("subscription.updated", entity, occurred_at=start + timedelta(hours=1)))
    assert current_plan(w.db, agency)[0] == "agency-pro"
    # A renewal fails and is recovered.
    lab.delivered(
        event(
            "subscription.past_due",
            entity | {"status": "past_due"},
            occurred_at=start + timedelta(days=30),
        )
    )
    assert standing(w.db, agency).standing == "past_due"
    assert owner.post(f"/agencies/{agency}/billing/payment-method").status_code == 200
    lab.delivered(
        event(
            "subscription.updated",
            entity | {"status": "active"},
            occurred_at=start + timedelta(days=31),
        )
    )
    assert (standing(w.db, agency).standing, current_plan(w.db, agency)[0]) == (
        "subscribed",
        "agency-pro",
    )
    # It cancels at the period end and returns to hold when the cancellation takes effect.
    assert owner.post(f"/agencies/{agency}/billing/cancel").status_code == 200
    lab.delivered(event("subscription.updated", entity, occurred_at=start + timedelta(days=32)))
    assert standing(w.db, agency).standing == "subscribed"
    lab.delivered(
        event(
            "subscription.canceled",
            entity | {"status": "canceled", "canceled_at": "2027-01-28T00:00:00Z"},
            occurred_at=start + timedelta(days=60),
        )
    )
    assert (standing(w.db, agency).standing, current_plan(w.db, agency)[0]) == (
        "hold",
        "billing_hold",
    )
    # The agency closes and is purged; the financial records stay.
    closing = w.signed_in("owner_a").post(
        f"/agencies/{agency}/closure",
        json={"confirm_name": "Synthetic Journey Agency", "password": api.password},
    )
    assert closing.status_code == 201, closing.text
    end_grace_period(w.db, agency)
    assert (
        run_lifecycle(lifecycle_engine, lifecycle_settings)["deleted"].get(
            "agency_closures_completed"
        )
        == 1
    )
    assert run_offboarding(w.db.runtime, api.config)["offboarded"] == 1
    assert _actions(w.db, agency) == []  # the subscription had already ended
    assert (
        run_lifecycle(lifecycle_engine, lifecycle_settings)["deleted"].get("agencies_purged") == 1
    )
    assert standing(w.db, agency) is None
    assert _count(w.db, AgencySubscription, AgencySubscription.agency_id == agency) == 1
    assert _count(w.db, BillingPayment, BillingPayment.agency_id == agency) >= 1
    # Nothing outside billing changed for the world's agencies.
    assert (standing(w.db, w.a).standing, standing(w.db, w.b).standing) == (
        "complimentary",
        "complimentary",
    )
