"""The billing operator command, python -m app.agency_billing (017-C, D-103 D3 and D12).

Cases BL01 (prices) and BL18 (every subcommand, --confirm, audit rows and output without a name,
email or secret) of the entry review's verification matrix, against the synthetic Paddle-shaped
server and the disposable database only.
"""

import json
import subprocess
import sys
from datetime import timedelta
from uuid import uuid4

import pytest
from billing_support import current_plan, make_billing_lab, set_trial, standing
from paddle_api import API_KEY, WEBHOOK_SECRET
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app import agency_plans
from app.config import BACKEND_ROOT
from app.models import AuditEvent, BillingPrice

pytestmark = pytest.mark.integration


def _audits(db, action: str) -> list[AuditEvent]:
    with Session(db.migration) as session:
        rows = list(session.scalars(select(AuditEvent).where(AuditEvent.action == action)))
        for row in rows:
            session.expunge(row)
        return rows


def _now(db):
    with Session(db.migration) as session:
        return session.scalar(select(func.now()))


def test_bl01_register_and_retire_prices(authenticated_world, api):
    w = authenticated_world
    billing = make_billing_lab(w, api)
    monthly = billing.paddle.add_price(2900, "month")
    code, view = billing.command(
        "register-price", plan="development", price_id=monthly, amount_cents=2900, interval="month"
    )
    assert code == 0, view
    assert (view["plan"], view["provider_price_id"], view["amount_cents"]) == (
        "development",
        monthly,
        2900,
    )
    assert (view["currency"], view["interval"], view["offered"], view["retired_at"]) == (
        "USD",
        "month",
        True,
        None,
    )
    # Paddle's price was read once, at registration (D3).
    assert billing.paddle.paths() == [f"GET /prices/{monthly}"]
    (audit,) = _audits(w.db, "billing_price.registered")
    assert (audit.actor_kind, audit.actor_user_id, audit.agency_id, audit.resource_type) == (
        "platform_operator",
        None,
        None,
        "billing_price",
    )
    # A plan has one offered monthly price: another refuses unless it replaces it atomically.
    other = billing.paddle.add_price(3900, "month")
    assert billing.command(
        "register-price", plan="development", price_id=other, amount_cents=3900, interval="month"
    ) == (1, {"error": "price_offered", "price_id": monthly})
    code, replaced = billing.command(
        "register-price",
        plan="development",
        price_id=other,
        amount_cents=3900,
        interval="month",
        replaces=monthly,
    )
    assert code == 0 and replaced["offered"] is True
    annual = billing.paddle.add_price(29000, "year")
    code, yearly = billing.command(
        "register-price", plan="development", price_id=annual, amount_cents=29000, interval="year"
    )
    assert code == 0 and yearly["interval"] == "year"
    assert billing.command(
        "register-price", plan="development", price_id=annual, amount_cents=29000, interval="year"
    ) == (1, {"error": "price_exists"})
    code, listed = billing.command("prices")
    assert code == 0
    assert [(item["provider_price_id"], item["offered"]) for item in listed] == [
        (monthly, False),
        (other, True),
        (annual, True),
    ]
    assert listed[0]["retired_at"] is not None
    # Retirement is final and audited; existing rows are never rewritten.
    code, retired = billing.command("retire-price", price_id=annual)
    assert code == 0 and retired["offered"] is False
    assert billing.command("retire-price", price_id=annual) == (1, {"error": "price_retired"})
    assert billing.command("retire-price", price_id="pri_" + "0" * 26) == (
        1,
        {"error": "price_not_found"},
    )
    assert len(_audits(w.db, "billing_price.retired")) == 2
    assert len(_audits(w.db, "billing_price.registered")) == 3
    with pytest.raises(ProgrammingError, match="permission denied"):
        with w.db.runtime.begin() as connection:
            connection.execute(text("UPDATE billing_prices SET amount_cents = 1"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        with w.db.runtime.begin() as connection:
            connection.execute(text("DELETE FROM billing_prices"))


def test_bl01_price_rules(authenticated_world, api):
    w = authenticated_world
    billing = make_billing_lab(w, api)
    paddle = billing.paddle

    def register(price_id, amount=2900, interval="month", plan="development"):
        return billing.command(
            "register-price", plan=plan, price_id=price_id, amount_cents=amount, interval=interval
        )

    # Paddle's own price must be active, in USD, of the same amount and of a one-period cycle.
    assert register(paddle.add_price(2900), amount=2901) == (
        1,
        {"error": "price_mismatch", "field": "amount"},
    )
    assert register(paddle.add_price(2900, currency="EUR")) == (
        1,
        {"error": "price_mismatch", "field": "currency"},
    )
    assert register(paddle.add_price(2900, "year")) == (
        1,
        {"error": "price_mismatch", "field": "interval"},
    )
    assert register(paddle.add_price(2900, frequency=3)) == (
        1,
        {"error": "price_mismatch", "field": "interval"},
    )
    assert register(paddle.add_price(2900, status="archived")) == (
        1,
        {"error": "price_mismatch", "field": "status"},
    )
    assert register(paddle.add_price(2900), plan="absent") == (1, {"error": "plan_not_found"})
    assert register(paddle.add_price(2900), plan="billing_hold") == (
        1,
        {"error": "reserved_plan"},
    )
    paddle.fail_next(503, "internal_error")
    assert register(paddle.add_price(2900)) == (
        1,
        {"error": "provider_unavailable", "provider_code": "provider_unavailable"},
    )
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(BillingPrice)) == 0
    # While billing is disabled, listings answer and changes are refused.
    disabled = make_billing_lab(w, api, billing_enabled=False)
    assert disabled.command("prices") == (0, [])
    assert disabled.command(
        "register-price",
        plan="development",
        price_id=paddle.add_price(2900),
        amount_cents=2900,
        interval="month",
    ) == (1, {"error": "billing_unavailable"})
    # The billing_hold plan is reserved for billing in the 017-A command too.
    assert agency_plans.run(w.db.runtime, "set-default", plan="billing_hold") == (
        1,
        {"error": "reserved_plan"},
    )
    assert agency_plans.run(
        w.db.runtime, "assign", agency=w.a, plan="billing_hold", reason="correction"
    ) == (1, {"error": "reserved_plan"})


def test_bl18_operator_subcommands(authenticated_world, api):
    w = authenticated_world
    billing = make_billing_lab(w, api)
    now = _now(w.db)
    code, view = billing.command("status", agency=w.a)
    assert code == 0
    assert (view["status"], view["billing"]["standing"], view["billing"]["plan"]) == (
        "active",
        "complimentary",
        "development",
    )
    assert (view["subscriptions"], view["checkouts"], view["actions"], view["last_payment"]) == (
        [],
        [],
        [],
        None,
    )
    assert billing.command("status", agency=uuid4()) == (1, {"error": "agency_not_found"})
    # A grant with an end in the future; one in the past refuses.
    assert billing.command(
        "grant", agency=w.a, plan="development", until=now - timedelta(minutes=1)
    ) == (1, {"error": "invalid_until"})
    code, granted = billing.command(
        "grant", agency=w.a, plan="development", until=now + timedelta(days=30)
    )
    assert code == 0
    assert (granted["standing"], granted["reason"], granted["plan"]) == (
        "complimentary",
        "operator_grant",
        "development",
    )
    assert granted["grant_ends_at"] is not None
    assert billing.command("grant", agency=w.a, plan="billing_hold", until=None) == (
        1,
        {"error": "reserved_plan"},
    )
    # end-grant without a subscription holds the agency on the billing_hold plan.
    code, ended = billing.command("end-grant", agency=w.a)
    assert code == 0 and (ended["standing"], ended["reason"]) == ("hold", "grant_ended")
    assert current_plan(w.db, w.a) == ("billing_hold", 2, "billing", "billing_hold")
    assert billing.command("end-grant", agency=w.a) == (
        1,
        {"error": "not_granted", "standing": "hold"},
    )
    # A grant ends a hold at once.
    code, regranted = billing.command("grant", agency=w.a, plan="development", until=None)
    assert code == 0 and regranted["hold_started_at"] is None
    assert current_plan(w.db, w.a) == ("development", 3, "platform_operator", "plan_change")
    # extend-trial: only a trial; the end moves and a new reminder becomes due.
    assert billing.command("extend-trial", agency=w.b, days=7) == (
        1,
        {"error": "not_trialing", "standing": "complimentary"},
    )
    set_trial(w.db, w.b, now + timedelta(days=2))
    with w.db.migration.begin() as connection:
        connection.execute(
            text("UPDATE agency_billing SET trial_reminded_at = now() WHERE agency_id = :b"),
            {"b": w.b},
        )
    code, extended = billing.command("extend-trial", agency=w.b, days=7)
    assert code == 0 and extended["trial_reminded_at"] is None
    assert standing(w.db, w.b).trial_ends_at - (now + timedelta(days=2)) == timedelta(days=7)
    # agencies lists standings, by standing and by hold age.
    code, listed = billing.command("agencies")
    assert code == 0 and {item["agency_id"] for item in listed["agencies"]} == {
        str(w.a),
        str(w.b),
    }
    code, trials = billing.command("agencies", standing="trialing")
    assert [item["agency_id"] for item in trials["agencies"]] == [str(w.b)]
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE agency_billing SET standing = 'hold', reason = 'trial_ended', "
                "hold_started_at = now() - interval '61 days' WHERE agency_id = :b"
            ),
            {"b": w.b},
        )
    code, old = billing.command("agencies", held_days=60)
    assert [(item["agency_id"], item["held_days"]) for item in old["agencies"]] == [(str(w.b), 61)]
    # Every change is audited as the platform operator, on the agency's own log.
    for action, count in (
        ("billing.granted", 2),
        ("billing.grant_ended", 1),
        ("billing.trial_extended", 1),
    ):
        rows = _audits(w.db, action)
        assert len(rows) == count, action
        assert {(row.actor_kind, row.actor_user_id, row.resource_type) for row in rows} == {
            ("platform_operator", None, "agency_billing")
        }
    # A closed agency refuses every change.
    with w.db.migration.begin() as connection:
        connection.execute(text("UPDATE agencies SET status = 'closed' WHERE id = :b"), {"b": w.b})
    for command, options in (
        ("grant", {"plan": "development", "until": None}),
        ("end-grant", {}),
        ("extend-trial", {"days": 1}),
    ):
        assert billing.command(command, agency=w.b, **options) == (
            1,
            {"error": "agency_closed"},
        )
    # The output carries IDs, keys, codes and times only.
    printed = json.dumps([view, granted, ended, extended, listed, old])
    for forbidden in ("Synthetic Agency", "@example.test", API_KEY, WEBHOOK_SECRET):
        assert forbidden not in printed


def test_bl18_command_runs_as_its_own_process_and_requires_confirm(world):
    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "app.agency_billing", *args],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )

    listed = run("prices")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout) == []
    for change in (
        ["grant", "--agency", str(world.a), "--plan", "development"],
        ["end-grant", "--agency", str(world.a)],
        ["extend-trial", "--agency", str(world.a), "--days", "3"],
        ["retire-price", "--price-id", "pri_" + "1" * 26],
        [
            "register-price",
            "--plan",
            "development",
            "--price-id",
            "pri_" + "1" * 26,
            "--amount-cents",
            "100",
            "--interval",
            "month",
        ],
    ):
        refused = run(*change)
        assert refused.returncode == 2 and "--confirm is required" in refused.stderr
    # With --confirm, a change still needs billing to be enabled.
    unavailable = run("grant", "--agency", str(world.a), "--plan", "development", "--confirm")
    assert unavailable.returncode == 1
    assert json.loads(unavailable.stdout) == {"error": "billing_unavailable"}
    assert standing(world.db, world.a).standing == "complimentary"
