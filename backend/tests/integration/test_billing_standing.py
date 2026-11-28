"""The billing standing: trial, trial end, hold and isolation (017-C, D-103 D4, D5, D11).

Cases BL02, BL03, BL04 and BL20 of the entry review's verification matrix, on synthetic data in
the disposable database only. A hold is reached through the worker at a trial's end, never by
writing the plan directly. Fixture imports deliberately expose the existing connector,
collection and managed-link fixtures to pytest.
"""

# ruff: noqa: F811

import re
from dataclasses import replace
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest
from billing_support import current_plan, make_billing_lab, set_trial, standing
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_collection import c, envelope  # noqa: F401
from test_links import SHOP, links, new_link, visit  # noqa: F401
from test_saas_plans import _refused, _snapshot, lab  # noqa: F401

from app.models import (
    AgencyBilling,
    AgencyMembership,
    AgencyPlanAssignment,
    ClientWorkspace,
    CollectedEvent,
    ConnectorConnection,
    ManagedLink,
)
from app.privacy import providers
from app.services.mail import process_mail

pytestmark = pytest.mark.integration


def _messages(config) -> list:
    found = []
    for path in sorted(config.mail_directory.glob("*.eml"), key=lambda p: p.stat().st_mtime_ns):
        found.append(BytesParser(policy=policy.default).parsebytes(path.read_bytes()))
    return found


def test_bl02_new_agency_standing_follows_the_setting(authenticated_world, api, monkeypatch):
    w = authenticated_world
    billing = make_billing_lab(w, api)
    # The world's agencies were created while billing was disabled: complimentary, default plan.
    for agency in (w.a, w.b):
        row = standing(w.db, agency)
        assert (row.standing, row.reason, row.trial_ends_at, row.version) == (
            "complimentary",
            "billing_disabled",
            None,
            1,
        )
        assert current_plan(w.db, agency) == ("development", 1, "default", "new_agency")
    # With billing enabled, a new agency is trialing for 14 days on the default plan.
    owner = billing.browser("owner_a")
    created = owner.post("/agencies", json={"name": "Synthetic Trial Agency"})
    assert created.status_code == 201, created.text
    agency = created.json()["id"]
    with Session(w.db.migration) as session:
        made = session.scalar(text("SELECT created_at FROM agencies WHERE id = :a"), {"a": agency})
    row = standing(w.db, agency)
    assert (row.standing, row.reason, row.trial_reminded_at) == ("trialing", "new_agency", None)
    assert abs(row.trial_ends_at - (made + timedelta(days=14))) < timedelta(seconds=5)
    assert current_plan(w.db, agency) == ("development", 1, "default", "new_agency")
    # The trial length follows the setting.
    short = billing.browser("owner_a", replace_config(billing.config, billing_trial_days=3))
    other = standing(w.db, short.post("/agencies", json={"name": "Synthetic Short"}).json()["id"])
    assert abs(other.trial_ends_at - other.created_at - timedelta(days=3)) < timedelta(seconds=5)
    # Disabled billing, or a Paddle rule that is not current, makes a new agency complimentary.
    plain = w.signed_in("owner_b").post("/agencies", json={"name": "Synthetic Plain Agency"})
    assert (standing(w.db, plain.json()["id"]).standing) == "complimentary"
    stale = tuple(
        replace(item, status=providers.RuleStatus.STALE)
        if item.rule_id == "paddle.billing"
        else item
        for item in providers.RULES
    )
    monkeypatch.setattr(providers, "RULES", stale)
    blocked = owner.post("/agencies", json={"name": "Synthetic Blocked Trial"})
    row = standing(w.db, blocked.json()["id"])
    assert (row.standing, row.reason) == ("complimentary", "billing_disabled")


def replace_config(config, **changes):
    return config.model_copy(update=changes)


def test_bl03_trial_reminder_and_end(authenticated_world, api):
    w = authenticated_world
    billing = make_billing_lab(w, api)
    owner = billing.browser("owner_a")
    agency = owner.post("/agencies", json={"name": "Synthetic Trial Agency"}).json()["id"]
    ends = standing(w.db, agency).trial_ends_at
    # Four days before the end: nothing yet.
    early = billing.worker(now=ends - timedelta(days=4))
    assert early == {
        "status": "completed",
        "trials_ended": 0,
        "grants_ended": 0,
        "messages": {"trial_ending": 0, "billing_hold": 0},
    }
    # Within three days: one reminder, sent once.
    soon = ends - timedelta(days=3) + timedelta(minutes=1)
    assert billing.worker(now=soon)["messages"] == {"trial_ending": 1, "billing_hold": 0}
    assert billing.worker(now=soon + timedelta(hours=1))["messages"]["trial_ending"] == 0
    assert standing(w.db, agency).trial_reminded_at is not None
    assert process_mail(w.db.runtime, billing.config)["delivered"] == 1
    (reminder,) = _messages(billing.config)
    body = reminder.get_body().get_content()
    assert (str(reminder["To"]), str(reminder["Subject"])) == (
        "owner_a@example.test",
        "Your trial ends soon",
    )
    assert f"/agencies/{agency}/billing" in body and "Synthetic" not in body
    assert ends.strftime("%Y-%m-%d") in body
    # At the end without a subscription: hold on the billing_hold plan, and one hold message.
    after = billing.worker(now=ends + timedelta(minutes=1))
    assert (after["trials_ended"], after["messages"]) == (
        1,
        {"trial_ending": 0, "billing_hold": 1},
    )
    row = standing(w.db, agency)
    assert (row.standing, row.reason, row.version) == ("hold", "trial_ended", 2)
    assert row.hold_started_at == ends + timedelta(minutes=1) and row.hold_notified_at
    assert current_plan(w.db, agency) == ("billing_hold", 2, "billing", "billing_hold")
    again = billing.worker(now=ends + timedelta(hours=2))
    assert (again["trials_ended"], again["messages"]["billing_hold"]) == (0, 0)
    assert process_mail(w.db.runtime, billing.config)["delivered"] == 1
    held = _messages(billing.config)[-1]
    assert str(held["Subject"]) == "Your agency is on hold"
    content = held.get_body().get_content()
    assert f"/agencies/{agency}/billing" in content and "nothing is deleted" in content
    # Only active, verified Owners receive billing messages.
    for message in _messages(billing.config):
        assert str(message["To"]) == "owner_a@example.test"
    # The worker changes nothing while billing is disabled.
    disabled = make_billing_lab(w, api, billing_enabled=False)
    set_trial(w.db, agency, ends)
    assert disabled.worker(now=ends + timedelta(days=1)) == {"status": "disabled"}
    assert standing(w.db, agency).standing == "trialing"


def _counts(db, agency) -> dict[str, int]:
    with Session(db.migration) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.agency_id == agency)
            )
            for model in (
                ClientWorkspace,
                AgencyMembership,
                ConnectorConnection,
                ManagedLink,
                CollectedEvent,
                AgencyPlanAssignment,
            )
        }


def test_bl04_hold_refuses_creations_and_stops_nothing(lab, links, c, api):
    w = lab.w
    billing = make_billing_lab(w, api)
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}"
    connection = lab.connect("owner_a", w.a, w.a1)
    new_link(links, "held-link")
    invited = owner.post(
        f"{base}/invitations", json={"email": "held@example.test", "role": "analyst"}
    )
    assert invited.status_code == 201
    token = c.subject()
    assert c.send(envelope(token)).status_code == 201
    before = _snapshot(owner, base, links, lab, connection)
    rows = _counts(w.db, w.a)
    # The trial ends without a subscription: the worker puts the agency on hold.
    with Session(w.db.migration) as session:
        now = session.scalar(select(func.now()))
    set_trial(w.db, w.a, now - timedelta(minutes=1))
    assert billing.worker()["trials_ended"] == 1
    assert current_plan(w.db, w.a)[0] == "billing_hold"
    # Nothing that exists changed or was removed.
    assert _snapshot(owner, base, links, lab, connection) == before
    assert before["connection"] == "active"
    assert {
        **_counts(w.db, w.a),
        "agency_plan_assignments": rows["agency_plan_assignments"],
    } == rows
    # Every new client, seat, managed link and connection is refused with plan_limit_reached.
    _refused(owner.post(f"{base}/clients", json={"name": "New"}), "clients", 0, 2)
    _refused(
        owner.post(f"{base}/invitations", json={"email": "new@example.test", "role": "analyst"}),
        "seats",
        0,
        5,
    )
    _refused(
        owner.post(
            f"{links.path}/managed-links",
            json={"slug": "new-held-link", "destination": f"{SHOP}/offer"},
        ),
        "managed_links",
        0,
        1,
    )
    started = lab.browser("owner_a").post(
        f"/agencies/{w.a}/clients/{w.a2}/connections", json={"provider": "synthetic"}
    )
    _refused(started, "connections", 0, 1)
    # Sign-in, reads, reports, exports, synchronization, redirects and collection go on.
    again = api.new_client()
    api.login(again, "owner_a@example.test")
    assert again.get(f"{base}/clients").status_code == 200
    assert again.get(f"{base}/plan").json()["plan"]["key"] == "billing_hold"
    span = "start=2026-11-01&end=2026-11-03"
    assert again.get(f"{base}/clients/{w.a1}/reports/revenue?{span}").status_code == 200
    export = again.post(
        f"{base}/clients/{w.a1}/report-exports",
        json={"family": "revenue", "start": "2026-11-01", "end": "2026-11-03"},
    )
    assert export.status_code == 201, export.text
    download = again.get(f"{base}/clients/{w.a1}/report-exports/{export.json()['id']}/download")
    assert download.status_code == 200
    assert lab.sync("owner_a", w.a, w.a1, connection).status_code == 202
    assert lab.worker()["sync"] == {"succeeded": 1}
    assert visit(links.api.new_client(), "held-link").status_code in {302, 303, 307}
    assert c.send(envelope(token)).status_code == 201
    # The other agency's plan never changed (BL20).
    assert current_plan(w.db, w.b) == ("development", 1, "default", "new_agency")


def test_bl20_other_agencies_never_change(authenticated_world, api):
    w = authenticated_world
    billing = make_billing_lab(w, api)
    with Session(w.db.migration) as session:
        now = session.scalar(select(func.now()))
    set_trial(w.db, w.a, now - timedelta(minutes=1))
    other_before = standing(w.db, w.b)
    plan_before = current_plan(w.db, w.b)
    result = billing.worker()
    assert result["trials_ended"] == 1 and result["messages"]["billing_hold"] == 1
    assert standing(w.db, w.a).standing == "hold"
    after = standing(w.db, w.b)
    assert (after.standing, after.reason, after.version, after.updated_at) == (
        other_before.standing,
        other_before.reason,
        other_before.version,
        other_before.updated_at,
    )
    assert current_plan(w.db, w.b) == plan_before
    # The operator's grant and trial extension of one agency touch no other.
    code, granted = billing.command("grant", agency=w.a, plan="development", until=None)
    assert code == 0 and granted["standing"] == "complimentary"
    assert standing(w.db, w.b).version == other_before.version
    with Session(w.db.migration) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgencyBilling)
                .where(AgencyBilling.agency_id == w.b, AgencyBilling.standing != "complimentary")
            )
            == 0
        )
    assert re.fullmatch(r"[0-9a-f-]{36}", granted["agency_id"])
