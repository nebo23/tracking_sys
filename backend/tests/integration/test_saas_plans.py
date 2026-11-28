"""Plans, limits, usage, the operator command and migration 0031 (017-A, D-092).

Cases SV01-SV09, SV18 and the plan part of SV19 of the entry review's verification matrix, on
synthetic data in the disposable database only. Fixture imports deliberately expose the
existing collection and managed-link fixtures to pytest.
"""

# ruff: noqa: F811

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from connector_support import make_lab
from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session
from test_collection import c, envelope  # noqa: F401
from test_links import SHOP, links, new_link, visit  # noqa: F401

from app import agency_plans
from app.config import BACKEND_ROOT
from app.models import (
    Agency,
    AgencyPlanAssignment,
    AuditEvent,
    ClientWorkspace,
    CollectedEvent,
    ConnectorConnection,
    SaasPlan,
)
from app.security import now_utc
from app.services import plans
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import tenancy_transaction

pytestmark = pytest.mark.integration
CONFIG = Config(str(BACKEND_ROOT / "alembic.ini"))
HEAD = "0034_saas_billing"
PREVIOUS = "0030_reporting_indexes"
NEW_TABLES = ("saas_plans", "agency_plan_assignments", "agency_closures", "user_agreements")
DEVELOPMENT = {
    "clients_limit": 5,
    "seats_limit": 10,
    "connections_limit": 10,
    "managed_links_limit": 500,
    "tracked_events_limit": 100000,
}
UNLIMITED = dict.fromkeys(DEVELOPMENT)


def _version(db) -> str:
    with db.migration.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _current(db, agency_id) -> tuple[str, int, str, str]:
    with Session(db.migration) as session:
        row = session.execute(
            select(SaasPlan.key, AgencyPlanAssignment)
            .join(AgencyPlanAssignment, AgencyPlanAssignment.plan_id == SaasPlan.id)
            .where(AgencyPlanAssignment.agency_id == agency_id)
            .order_by(AgencyPlanAssignment.revision.desc())
            .limit(1)
        ).one()
        return row[0], row[1].revision, row[1].assigned_by, row[1].reason


def _audits(db, action: str) -> list[AuditEvent]:
    with Session(db.migration) as session:
        return list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id)
            )
        )


def _privilege(db, role, table, privilege, column=None) -> bool:
    with db.migration.connect() as connection:
        if column is None:
            return connection.execute(
                text("SELECT has_table_privilege(:r, :t, :p)"),
                {"r": role, "t": table, "p": privilege},
            ).scalar_one()
        return connection.execute(
            text("SELECT has_column_privilege(:r, :t, :c, :p)"),
            {"r": role, "t": table, "c": column, "p": privilege},
        ).scalar_one()


def _create(db, key: str, limits: dict, reason: str = "new_offer") -> dict:
    code, result = agency_plans.run(
        db.runtime,
        "create-plan",
        key=key,
        name=f"Synthetic {key}",
        reason=reason,
        limits=limits,
    )
    assert code == 0, result
    return result


def _new_agency(world, name: str = "Synthetic Agency C") -> UUID:
    with tenancy_transaction(world.db.runtime, world.users.owner_b) as service:
        return service.create_agency(name).id


def test_sv01_new_agencies_get_the_current_default_plan(world):
    w = world
    for agency in (w.a, w.b):
        assert _current(w.db, agency) == ("development", 1, "default", "new_agency")
    with Session(w.db.migration) as session:
        seed = session.scalar(select(SaasPlan).where(SaasPlan.key == "development"))
        assert seed is not None and seed.is_default and seed.reason == "seed"
        assert {name: getattr(seed, name) for name in DEVELOPMENT} == DEVELOPMENT
    _create(w.db, "growth", {**DEVELOPMENT, "clients_limit": 20})
    assert agency_plans.run(w.db.runtime, "set-default", plan="growth")[0] == 0
    created = _new_agency(w)
    assert _current(w.db, created) == ("growth", 1, "default", "new_agency")
    # A changed default applies to new agencies only.
    for agency in (w.a, w.b):
        assert _current(w.db, agency)[0] == "development"
    with Session(w.db.migration) as session:
        defaults = list(session.scalars(select(SaasPlan.key).where(SaasPlan.is_default)))
    assert defaults == ["growth"]


def test_sv08_operator_command_subcommands_audit_and_refusals(authenticated_world, capsys):
    w = authenticated_world
    run = agency_plans.run
    created = _create(w.db, "agency-pro", {**UNLIMITED, "seats_limit": 25}, "individual")
    assert created["limits"] == {
        "clients": None,
        "seats": 25,
        "connections": None,
        "managed_links": None,
        "tracked_events": None,
    }
    assert created["is_default"] is False and created["reason"] == "individual"
    again = {"key": "agency-pro", "name": "Again", "reason": "new_offer", "limits": UNLIMITED}
    assert run(w.db.runtime, "create-plan", **again) == (1, {"error": "plan_exists"})
    code, listed = run(w.db.runtime, "plans")
    assert code == 0
    assert {(item["key"], item["is_default"], item["agencies"]) for item in listed} == {
        ("development", True, 2),
        ("billing_hold", False, 0),
        ("agency-pro", False, 0),
    }
    # Assignment: a new revision under the agency lock, audited; refusals by closed code.
    code, assigned = run(
        w.db.runtime, "assign", agency=w.a, plan="agency-pro", reason="plan_change"
    )
    assert code == 0 and assigned["revision"] == 2 and assigned["plan"] == "agency-pro"
    assert _current(w.db, w.a) == ("agency-pro", 2, "platform_operator", "plan_change")
    assert run(w.db.runtime, "assign", agency=w.a, plan="agency-pro", reason="correction") == (
        1,
        {"error": "already_assigned"},
    )
    assert run(w.db.runtime, "assign", agency=uuid4(), plan="agency-pro", reason="correction")[
        1
    ] == {"error": "agency_not_found"}
    assert run(w.db.runtime, "assign", agency=w.a, plan="absent", reason="correction")[1] == {
        "error": "plan_not_found"
    }
    assert run(w.db.runtime, "set-default", plan="absent")[1] == {"error": "plan_not_found"}
    assert run(w.db.runtime, "set-default", plan="development")[1] == {"error": "already_default"}
    # Suspension and reactivation follow the closed transitions only.
    assert run(w.db.runtime, "reactivate", agency=w.b) == (
        1,
        {"error": "not_suspended", "status": "active"},
    )
    assert run(w.db.runtime, "suspend", agency=w.b) == (
        0,
        {"agency_id": str(w.b), "status": "suspended"},
    )
    assert run(w.db.runtime, "suspend", agency=w.b) == (
        1,
        {"error": "not_active", "status": "suspended"},
    )
    assert run(w.db.runtime, "reactivate", agency=w.b)[1]["status"] == "active"
    assert run(w.db.runtime, "suspend", agency=uuid4())[1] == {"error": "agency_not_found"}
    # Every change is audited with the platform operator as the actor and no user.
    events = {
        action: _audits(w.db, action)
        for action in (
            "plan.created",
            "agency.plan_assigned",
            "agency.suspended",
            "agency.reactivated",
        )
    }
    assert [len(rows) for rows in events.values()] == [1, 1, 1, 1]
    for rows in events.values():
        assert all(
            row.actor_kind == "platform_operator" and row.actor_user_id is None for row in rows
        )
    assert events["plan.created"][0].agency_id is None
    assert events["plan.created"][0].resource_type == "plan"
    assert events["agency.plan_assigned"][0].agency_id == w.a
    assert events["agency.plan_assigned"][0].resource_type == "plan_assignment"
    assert {row.agency_id for row in events["agency.suspended"]} == {w.b}
    assert run(w.db.runtime, "set-default", plan="agency-pro")[0] == 0
    assert _audits(w.db, "plan.default_set")[0].agency_id is None
    # Agency-level operator events reach the agency's audit log; plan events do not.
    audit = w.signed_in("owner_a").get(f"/agencies/{w.a}/audit").json()
    operator = [row for row in audit if row["action"] == "agency.plan_assigned"]
    assert len(operator) == 1 and operator[0]["actor_user_id"] is None
    assert operator[0]["actor_kind"] == "platform_operator"
    assert not {row["action"] for row in audit} & {"plan.created", "plan.default_set"}
    # The agencies listing: identifiers, keys, numbers and codes only, paged by agency ID.
    code, page = run(w.db.runtime, "agencies", limit=1)
    assert code == 0 and len(page["agencies"]) == 1 and page["next_after"] is not None
    code, rest = run(w.db.runtime, "agencies", after=UUID(page["next_after"]), limit=1)
    assert code == 0 and len(rest["agencies"]) == 1
    entries = {item["agency_id"]: item for item in page["agencies"] + rest["agencies"]}
    assert entries[str(w.a)]["plan"] == "agency-pro"
    assert entries[str(w.a)]["use"] == {
        "clients": 2,
        "seats": 4,
        "connections": 0,
        "managed_links": 0,
    }
    assert entries[str(w.b)]["tracked_events"] == {
        "count": 0,
        "count_capped": False,
        "allowance": 100000,
        "state": "within",
    }
    assert run(w.db.runtime, "agencies", over_allowance=True)[1]["agencies"] == []
    # main(): --confirm is required for every change, and output is JSON without names.
    for argv in (
        ["suspend", "--agency", str(w.b)],
        ["set-default", "--plan", "development"],
        ["assign", "--agency", str(w.b), "--plan", "development", "--reason", "correction"],
    ):
        with pytest.raises(SystemExit) as exit_info:
            agency_plans.main(argv)
        assert exit_info.value.code == 2
        assert "--confirm is required" in capsys.readouterr().err
    assert agency_plans.main(["agencies"]) == 0
    printed = capsys.readouterr().out
    listing = json.loads(printed)
    assert {item["agency_id"] for item in listing["agencies"]} == {str(w.a), str(w.b)}
    for forbidden in ("Synthetic Agency", "Synthetic Client", "@example.test", "tsk_"):
        assert forbidden not in printed


def test_sv08_operator_command_runs_as_its_own_process(world):
    result = subprocess.run(
        [sys.executable, "-m", "app.agency_plans", "plans"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    # The two seeded plans (0031, 0034) may share one creation time; the listing then orders
    # them by key.
    assert sorted(item["key"] for item in json.loads(result.stdout)) == [
        "billing_hold",
        "development",
    ]
    refused = subprocess.run(
        [sys.executable, "-m", "app.agency_plans", "suspend", "--agency", str(world.a)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert refused.returncode == 2 and "--confirm is required" in refused.stderr
    assert _current(world.db, world.a)[0] == "development"


def test_sv09_suspension_stops_the_agency_and_reactivation_restores_it(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    issued = owner.post(
        f"/agencies/{w.a}/service-credentials",
        json={"name": "Synthetic reader", "clients": [{"client_id": str(w.a1)}]},
    )
    assert issued.status_code == 201
    reader = api.new_client()
    reader.headers["Authorization"] = "Bearer " + issued.json()["key"]
    base = f"/agencies/{w.a}"

    def works() -> list[int]:
        return [
            owner.get(base).status_code,
            owner.get(base + "/clients").status_code,
            owner.post(base + "/clients", json={"name": "Synthetic extra"}).status_code,
            reader.get(f"{base}/clients/{w.a1}").status_code,
        ]

    assert works() == [200, 200, 201, 200]
    assert str(w.a) in {item["agency_id"] for item in owner.get("/agencies").json()}
    assert agency_plans.run(w.db.runtime, "suspend", agency=w.a)[0] == 0
    assert works() == [403, 403, 403, 401]
    assert str(w.a) not in {item["agency_id"] for item in owner.get("/agencies").json()}
    # Another agency is unaffected.
    assert w.signed_in("owner_b").get(f"/agencies/{w.b}/clients").status_code == 200
    assert agency_plans.run(w.db.runtime, "reactivate", agency=w.a)[0] == 0
    assert works() == [200, 200, 201, 200]


def _seed_at_0030(w) -> UUID:
    agency = uuid4()
    with w.db.migration.begin() as connection:
        connection.execute(
            text("INSERT INTO agencies (id, name, status) VALUES (:id, 'Legacy agency', 'active')"),
            {"id": agency},
        )
        connection.execute(
            text(
                "INSERT INTO agencies (id, name, status) "
                "VALUES (:id, 'Legacy suspended', 'suspended')"
            ),
            {"id": uuid4()},
        )
    return agency


def test_sv18_upgrade_seeds_and_assigns_grants_and_guarded_downgrade(world):
    w = world
    assert _version(w.db) == HEAD
    # Default assignments of the seed plan are rebuilt by the upgrade, so they never block.
    command.downgrade(CONFIG, PREVIOUS)
    try:
        with w.db.migration.connect() as connection:
            present = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
            )
        assert present.isdisjoint(NEW_TABLES)
        legacy = _seed_at_0030(w)
        command.upgrade(CONFIG, "head")
        assert _version(w.db) == HEAD
        with Session(w.db.migration) as session:
            plans = list(session.scalars(select(SaasPlan).order_by(SaasPlan.key.desc())))
            # 0034 (017-C) also seeds the billing_hold plan, which is never assigned here.
            assert [(p.key, p.is_default, p.reason) for p in plans] == [
                ("development", True, "seed"),
                ("billing_hold", False, "seed"),
            ]
            assigned = list(session.scalars(select(AgencyPlanAssignment)))
            agencies = set(session.scalars(text("SELECT id FROM agencies")))
        assert {row.agency_id for row in assigned} == agencies and len(assigned) == 4
        assert {(row.revision, row.assigned_by, row.reason) for row in assigned} == {
            (1, "default", "initial")
        }
        assert {row.plan_id for row in assigned} == {plans[0].id}
        assert _current(w.db, legacy)[0] == "development"
    finally:
        if _version(w.db) != HEAD:
            command.upgrade(CONFIG, "head")
    # Grants (D12): the runtime reads and inserts, updates only the default flag and the
    # cancellation columns, and deletes nothing; the lifecycle role completes closures and
    # deletes the agreements of closed accounts only.
    for table in NEW_TABLES:
        assert _privilege(w.db, "tracking_app", table, "SELECT")
        assert _privilege(w.db, "tracking_app", table, "INSERT")
        assert not _privilege(w.db, "tracking_app", table, "DELETE")
        assert not _privilege(w.db, "tracking_app", table, "TRUNCATE")
    assert _privilege(w.db, "tracking_app", "saas_plans", "UPDATE", "is_default")
    for column in ("key", "name", "clients_limit", "tracked_events_limit", "reason"):
        assert not _privilege(w.db, "tracking_app", "saas_plans", "UPDATE", column)
    for column in ("agency_id", "plan_id", "revision", "assigned_at", "reason"):
        assert not _privilege(w.db, "tracking_app", "agency_plan_assignments", "UPDATE", column)
    for column in ("cancelled_at", "cancelled_by_membership_id"):
        assert _privilege(w.db, "tracking_app", "agency_closures", "UPDATE", column)
    for column in ("requested_at", "closes_at", "completed_at", "requested_by_membership_id"):
        assert not _privilege(w.db, "tracking_app", "agency_closures", "UPDATE", column)
    for column in ("user_id", "document", "version", "accepted_at", "channel"):
        assert not _privilege(w.db, "tracking_app", "user_agreements", "UPDATE", column)
    assert _privilege(w.db, "tracking_lifecycle", "agencies", "UPDATE", "status")
    assert not _privilege(w.db, "tracking_lifecycle", "agencies", "UPDATE", "name")
    assert not _privilege(w.db, "tracking_lifecycle", "agencies", "SELECT", "name")
    assert _privilege(w.db, "tracking_lifecycle", "agency_closures", "UPDATE", "completed_at")
    assert not _privilege(w.db, "tracking_lifecycle", "agency_closures", "UPDATE", "cancelled_at")
    assert not _privilege(w.db, "tracking_lifecycle", "agency_closures", "INSERT")
    assert _privilege(w.db, "tracking_lifecycle", "user_agreements", "DELETE")
    assert not _privilege(w.db, "tracking_lifecycle", "user_agreements", "SELECT", "version")
    for table in ("saas_plans", "agency_plan_assignments"):
        assert not _privilege(w.db, "tracking_lifecycle", table, "SELECT")
    # Every kind of stored row refuses the downgrade, which rolls back as a whole.
    stored = [
        (
            "INSERT INTO saas_plans (id, key, name, is_default, reason) "
            "VALUES (:id, 'synthetic-extra', 'Extra', false, 'new_offer')",
            "DELETE FROM saas_plans WHERE key = 'synthetic-extra'",
        ),
        (
            "INSERT INTO agency_closures (id, agency_id, requested_by_membership_id, "
            "requested_at, closes_at) VALUES (:id, :agency, :member, now(), "
            "now() + interval '30 days')",
            "DELETE FROM agency_closures",
        ),
        (
            "INSERT INTO user_agreements (id, user_id, document, version, channel) "
            "VALUES (:id, :user, 'terms', 'draft-1', 'registration')",
            "DELETE FROM user_agreements",
        ),
        (
            "UPDATE agencies SET status = 'closed' WHERE id = :agency",
            "UPDATE agencies SET status = 'active' WHERE id = :agency",
        ),
        (
            "INSERT INTO oauth_transactions (id, purpose, state_digest, binding_digest, "
            "terms_version, privacy_version, expires_at) VALUES (:id, 'login', :digest, "
            ":digest, 'draft-1', 'draft-1', now())",
            "DELETE FROM oauth_transactions",
        ),
        (
            "INSERT INTO audit_events (id, agency_id, actor_kind, action, resource_type, "
            "resource_id) VALUES (:id, :agency, 'platform_operator', 'agency.suspended', "
            "'agency', :agency)",
            "DELETE FROM audit_events WHERE actor_kind = 'platform_operator'",
        ),
    ]
    values = {
        "agency": w.a,
        "member": w.owner_a,
        "user": w.users.owner_a,
        "digest": "c" * 64,
    }
    for statement, cleanup in stored:
        with w.db.migration.begin() as connection:
            connection.execute(text(statement), {**values, "id": uuid4()})
        with pytest.raises(RuntimeError, match="stored plan, closure or agreement state"):
            command.downgrade(CONFIG, PREVIOUS)
        assert _version(w.db) == HEAD
        with w.db.migration.begin() as connection:
            connection.execute(text(cleanup), values)
    # An operator assignment is stored state as well.
    _create(w.db, "synthetic-move", UNLIMITED)
    assert (
        agency_plans.run(
            w.db.runtime, "assign", agency=w.b, plan="synthetic-move", reason="correction"
        )[0]
        == 0
    )
    try:
        with pytest.raises(RuntimeError, match="stored plan, closure or agreement state"):
            command.downgrade(CONFIG, PREVIOUS)
        assert _version(w.db) == HEAD
    finally:
        with w.db.migration.begin() as connection:
            connection.execute(text("DELETE FROM audit_events WHERE actor_kind <> 'user'"))
            connection.execute(
                text("DELETE FROM agency_plan_assignments WHERE assigned_by <> 'default'")
            )
            connection.execute(text("DELETE FROM saas_plans WHERE reason <> 'seed'"))
    command.downgrade(CONFIG, PREVIOUS)
    assert _version(w.db) == PREVIOUS
    with w.db.migration.connect() as connection:
        nullable = connection.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'audit_events' AND column_name IN "
                "('agency_id', 'actor_user_id', 'actor_kind')"
            )
        ).all()
    assert sorted(nullable) == [("actor_user_id", "NO"), ("agency_id", "NO")]
    command.upgrade(CONFIG, "head")
    assert _version(w.db) == HEAD
    assert _current(w.db, w.b) == ("development", 1, "default", "initial")


def test_agreements_of_closed_accounts_follow_the_credential_state(
    world, lifecycle_engine, lifecycle_settings
):
    w = world
    with w.db.migration.begin() as connection:
        for user in (w.users.viewer, w.users.outsider):
            for document in ("terms", "privacy"):
                connection.execute(
                    text(
                        "INSERT INTO user_agreements (id, user_id, document, version, channel) "
                        "VALUES (:id, :user, :document, 'draft-1', 'registration')"
                    ),
                    {"id": uuid4(), "user": user, "document": document},
                )
        connection.execute(
            text(
                "UPDATE users SET status = 'disabled', closed_at = now(), "
                "email_normalized = 'closed-synthetic@tracking.invalid' WHERE id = :user"
            ),
            {"user": w.users.viewer},
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed" and result["deleted"]["user_agreements"] == 2
    with w.db.migration.connect() as connection:
        left = connection.execute(text("SELECT DISTINCT user_id FROM user_agreements")).all()
    assert left == [(w.users.outsider,)]
    again = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert again["deleted"]["user_agreements"] == 0


# --- P2: limits (SV02-SV05), tracked events (SV06), the usage view (SV07) and isolation (SV19)


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


def _limits(db, agency, **values) -> str:
    key = f"tight-{uuid4().hex[:8]}"
    _create(db, key, {**UNLIMITED, **{f"{name}_limit": value for name, value in values.items()}})
    code, result = agency_plans.run(
        db.runtime, "assign", agency=agency, plan=key, reason="plan_change"
    )
    assert code == 0, result
    return key


def _refused(response, limit: str, value: int, used: int) -> None:
    assert response.status_code == 409, response.text
    assert response.json() == {
        "error": "plan_limit_reached",
        "limit": limit,
        "value": value,
        "used": used,
    }


def _count(db, model, *where) -> int:
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def test_sv02_clients_limit_refuses_exactly_the_creation_beyond_it(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}/clients"
    _limits(w.db, w.a, clients=3)
    third = owner.post(base, json={"name": "Synthetic third"})
    assert third.status_code == 201
    _refused(owner.post(base, json={"name": "Synthetic fourth"}), "clients", 3, 3)
    assert _count(w.db, ClientWorkspace, ClientWorkspace.agency_id == w.a) == 3
    assert len(_audits(w.db, "client.created")) == 2 + 2 + 1  # world: A1, A2, B1, B2; third
    # Archiving frees a place; reactivating an archived client counts like a creation.
    assert owner.patch(f"{base}/{w.a1}", json={"status": "archived"}).status_code == 200
    assert owner.post(base, json={"name": "Synthetic fourth"}).status_code == 201
    _refused(owner.patch(f"{base}/{w.a1}", json={"status": "active"}), "clients", 3, 3)
    assert owner.patch(f"{base}/{w.a1}", json={"name": "Renamed while archived"}).status_code == 200
    # The other agency keeps its own plan and use.
    assert (
        w.signed_in("owner_b").post(f"/agencies/{w.b}/clients", json={"name": "B3"}).status_code
        == 201
    )


def test_sv02_seats_count_members_and_pending_invitations(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}"

    def invite(email):
        return owner.post(f"{base}/invitations", json={"email": email, "role": "analyst"})

    _limits(w.db, w.a, seats=6)  # four active members
    assert invite("second_owner@example.test").status_code == 201
    assert invite("seat.two@example.test").status_code == 201
    _refused(invite("seat.three@example.test"), "seats", 6, 6)
    # Revoking an invitation frees its seat.
    pending = {
        item["email_normalized"]: item["id"] for item in owner.get(f"{base}/invitations").json()
    }
    assert owner.delete(f"{base}/invitations/{pending['seat.two@example.test']}").status_code == 204
    assert invite("seat.three@example.test").status_code == 201
    # An accepted invitation keeps its seat, also after a move to a smaller plan.
    token = [t for to, subject, t in api.mail_tokens() if subject == "Agency invitation"][0]
    _limits(w.db, w.a, seats=1)
    accepted = w.signed_in("second_owner").post("/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    # Re-enabling a disabled member takes a seat like a creation.
    assert owner.patch(f"{base}/members/{w.viewer}", json={"status": "disabled"}).status_code == 200
    _refused(owner.patch(f"{base}/members/{w.viewer}", json={"status": "active"}), "seats", 1, 5)
    assert owner.patch(f"{base}/members/{w.viewer}", json={"role": "analyst"}).status_code == 200


def test_sv02_connections_are_limited_at_the_start_and_at_installation(lab):
    w = lab.w
    _limits(w.db, w.a, connections=1)
    # Each authorization is bound to the browser that started it, so the admin starts this one
    # while the agency has no live connection.
    early = lab.start("admin", w.a, w.a2)
    first = lab.connect("owner_a", w.a, w.a1, account="syn-acct-first")
    started = lab.browser("owner_a").post(
        f"/agencies/{w.a}/clients/{w.a2}/connections", json={"provider": "synthetic"}
    )
    _refused(started, "connections", 1, 1)
    result, _ = lab.finish("admin", early, account="syn-acct-second")
    assert result == {"error": "plan_limit_reached"}
    assert lab.provider.grants()[-1] == ("syn-acct-second", True)  # the grant was disposed of
    assert _count(w.db, ConnectorConnection, ConnectorConnection.agency_id == w.a) == 1
    # A disconnect frees the place at once; a reconnect is never limited.
    assert lab.disconnect("owner_a", w.a, w.a1, first).status_code == 202
    assert lab.connect("owner_a", w.a, w.a2, account="syn-acct-third")


def test_sv02_managed_links_limit_counts_active_links(links):
    w = links.w
    _limits(w.db, w.a, managed_links=2)
    one, _two = new_link(links, "limit-one"), new_link(links, "limit-two")
    body = {"slug": "limit-three", "destination": f"{SHOP}/offer?ref=spring"}
    _refused(links.owner.post(f"{links.path}/managed-links", json=body), "managed_links", 2, 2)
    path = f"{links.path}/managed-links/{one['id']}"
    assert links.owner.patch(path, json={"status": "disabled"}).status_code == 200
    assert links.owner.post(f"{links.path}/managed-links", json=body).status_code == 201
    _refused(links.owner.patch(path, json={"status": "active"}), "managed_links", 2, 2)
    # Changing an active link's expiry is never limited.
    later = (now_utc() + timedelta(days=30)).isoformat()
    second = f"{links.path}/managed-links/{_two['id']}"
    assert links.owner.patch(second, json={"expires_at": later}).status_code == 200


def test_sv02_a_missing_limit_never_refuses(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    _limits(w.db, w.a)  # every limit unlimited
    for index in range(5):  # beyond the development plan's five clients
        assert (
            owner.post(f"/agencies/{w.a}/clients", json={"name": f"Many {index}"}).status_code
            == 201
        )
    assert _count(w.db, ClientWorkspace, ClientWorkspace.agency_id == w.a) == 7


def _race(first, second):
    barrier = Barrier(2)

    def run(call):
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=2) as executor:
        return sorted(executor.map(run, (first, second)))


def test_sv03_concurrent_creations_at_the_limit_have_one_winner(authenticated_world, lab, links):
    w = authenticated_world
    owner, admin = w.signed_in("owner_a"), w.signed_in("admin")
    base = f"/agencies/{w.a}"
    _limits(w.db, w.a, clients=3, seats=5, connections=1, managed_links=1)
    # Clients: two concurrent creations for the last place.
    statuses = _race(
        lambda: owner.post(f"{base}/clients", json={"name": "Race one"}).status_code,
        lambda: admin.post(f"{base}/clients", json={"name": "Race two"}).status_code,
    )
    assert statuses == [201, 409]
    assert _count(w.db, ClientWorkspace, ClientWorkspace.agency_id == w.a) == 3
    # Invitations: the last seat.
    statuses = _race(
        lambda: (
            owner.post(
                f"{base}/invitations", json={"email": "race.one@example.test", "role": "analyst"}
            ).status_code
        ),
        lambda: (
            admin.post(
                f"{base}/invitations", json={"email": "race.two@example.test", "role": "analyst"}
            ).status_code
        ),
    )
    assert statuses == [201, 409]
    # Links: the last place.
    statuses = _race(
        lambda: (
            owner.post(
                f"{links.path}/managed-links",
                json={"slug": "race-one", "destination": f"{SHOP}/offer?ref=one"},
            ).status_code
        ),
        lambda: (
            admin.post(
                f"{links.path}/managed-links",
                json={"slug": "race-two", "destination": f"{SHOP}/offer?ref=two"},
            ).status_code
        ),
    )
    assert statuses == [201, 409]
    # Connections: two connects that both passed their start complete concurrently.
    urls = (lab.start("owner_a", w.a, w.a1), lab.start("admin", w.a, w.a2))
    outcomes = _race(
        lambda: lab.finish("owner_a", urls[0], account="syn-race-one")[0].get("error", "ok"),
        lambda: lab.finish("admin", urls[1], account="syn-race-two")[0].get("error", "ok"),
    )
    assert outcomes == ["ok", "plan_limit_reached"]
    assert _count(w.db, ConnectorConnection, ConnectorConnection.agency_id == w.a) == 1


def _waiting_on_agency_lock(db) -> bool:
    with db.runtime.connect() as connection:
        return bool(
            connection.exec_driver_sql(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND query ILIKE '%%FROM agencies%%FOR UPDATE%%'"
            ).scalar_one()
        )


def test_sv03_a_waiting_creation_counts_after_the_lock(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    _limits(w.db, w.a, clients=3)
    with w.db.runtime.connect() as holder, ThreadPoolExecutor(max_workers=1) as executor:
        # A concurrent creation holds the agency lock and has inserted the third client.
        holder.execute(select(Agency.id).where(Agency.id == w.a).with_for_update())
        holder.execute(insert(ClientWorkspace).values(id=uuid4(), agency_id=w.a, name="Held third"))
        pending = executor.submit(
            owner.post, f"/agencies/{w.a}/clients", json={"name": "Waiting fourth"}
        )
        deadline = time.monotonic() + 5
        while not _waiting_on_agency_lock(w.db):
            assert time.monotonic() < deadline and not pending.done()
            time.sleep(0.02)
        holder.commit()
        response = pending.result(timeout=10)
    _refused(response, "clients", 3, 3)


def _snapshot(owner, base: str, links, lab, connection: UUID) -> dict:
    w = lab.w
    return {
        "clients": owner.get(f"{base}/clients").json(),
        "members": owner.get(f"{base}/members").json(),
        "invitations": owner.get(f"{base}/invitations").json(),
        "links": owner.get(f"{links.path}/managed-links").json(),
        "connection": lab.view("owner_a", w.a, w.a1, connection).json()["status"],
    }


def test_sv04_a_smaller_plan_keeps_everything_and_refuses_only_new_creations(lab, links):
    w = lab.w
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}"
    connection = lab.connect("owner_a", w.a, w.a1)
    new_link(links, "kept-link")
    invited = owner.post(
        f"{base}/invitations", json={"email": "kept@example.test", "role": "analyst"}
    )
    assert invited.status_code == 201
    before = _snapshot(owner, base, links, lab, connection)
    _limits(w.db, w.a, clients=0, seats=0, connections=0, managed_links=0)
    after = _snapshot(owner, base, links, lab, connection)
    assert after == before and after["connection"] == "active"
    assert visit(links.api.new_client(), "kept-link").status_code in {302, 303, 307}
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
            json={"slug": "new-link", "destination": f"{SHOP}/offer"},
        ),
        "managed_links",
        0,
        1,
    )
    started = lab.browser("owner_a").post(
        f"/agencies/{w.a}/clients/{w.a2}/connections", json={"provider": "synthetic"}
    )
    _refused(started, "connections", 0, 1)


def test_sv05_reads_syncs_redirects_collection_erasure_archival_and_revocation_are_never_refused(
    lab, links, c
):
    w = lab.w
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}"
    connection = lab.connect("owner_a", w.a, w.a1)
    link = new_link(links, "never-refused")
    invited = owner.post(
        f"{base}/invitations", json={"email": "never@example.test", "role": "analyst"}
    )
    key = owner.post(
        f"{base}/service-credentials",
        json={"name": "Never refused", "clients": [{"client_id": str(w.a1)}]},
    )
    assert invited.status_code == key.status_code == 201
    token = c.subject()
    assert c.send(envelope(token)).status_code == 201
    # Beyond every limit at once.
    _limits(w.db, w.a, clients=0, seats=0, connections=0, managed_links=0, tracked_events=0)
    assert owner.get(f"{base}/clients").status_code == 200
    assert owner.get(f"{base}/plan").status_code == 200
    assert lab.sync("owner_a", w.a, w.a1, connection).status_code == 202
    assert lab.worker()["sync"] == {"succeeded": 1}
    assert visit(links.api.new_client(), "never-refused").status_code in {302, 303, 307}
    second = envelope(token)
    assert c.send(second).status_code == 201
    assert c.collect(envelope(token)).status_code in {200, 201, 202}
    erased = owner.post(
        f"{base}/clients/{w.a1}/deletion-requests", json={"event_id": second["event_id"]}
    )
    assert erased.status_code == 201, erased.text
    credential = key.json()["credential"]["id"]
    assert owner.delete(f"{base}/invitations/{invited.json()['id']}").status_code == 204
    assert owner.delete(f"{base}/service-credentials/{credential}").status_code == 204
    assert owner.delete(f"{base}/members/{w.analyst}/clients/{w.a1}").status_code == 204
    assert owner.patch(f"{base}/clients/{w.a2}", json={"status": "archived"}).status_code == 200
    assert owner.patch(f"{base}/members/{w.viewer}", json={"status": "disabled"}).status_code == 200
    assert lab.disconnect("owner_a", w.a, w.a1, connection).status_code == 202
    disabled = owner.patch(f"{links.path}/managed-links/{link['id']}", json={"status": "disabled"})
    assert disabled.status_code == 200


def _copy_event(db, template: UUID, received: datetime) -> None:
    with db.migration.begin() as connection:
        columns = [
            name
            for name in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'collected_events' ORDER BY ordinal_position"
                )
            ).scalars()
            if name not in {"id", "event_id", "first_received_at", "last_received_at"}
        ]
        listed = ", ".join(columns)
        connection.execute(
            text(
                "INSERT INTO collected_events (id, event_id, first_received_at, "
                f"last_received_at, {listed}) SELECT :id, :event, :at, :at, {listed} "
                "FROM collected_events WHERE id = :template"
            ),
            {"id": uuid4(), "event": uuid4(), "at": received, "template": template},
        )


def test_sv06_events_beyond_the_allowance_are_accepted_and_counted_by_utc_month(c):
    w = c.w
    _limits(w.db, w.a, tracked_events=2)
    token = c.subject()
    sent = [c.send(envelope(token)) for _ in range(3)]
    assert [response.status_code for response in sent] == [201, 201, 201]
    view = c.owner.get(f"/agencies/{w.a}/plan").json()["tracked_events"]
    assert (view["count"], view["allowance"], view["state"], view["count_capped"]) == (
        3,
        2,
        "over_allowance",
        False,
    )
    listed = agency_plans.run(w.db.runtime, "agencies", over_allowance=True)[1]["agencies"]
    assert [item["agency_id"] for item in listed] == [str(w.a)]
    # Months are UTC calendar months, to the microsecond. The copies are dated in 2025, so
    # the events received by this run never fall into the months examined.
    with Session(w.db.migration) as session:
        template = session.scalar(
            select(CollectedEvent.id).where(CollectedEvent.client_id == w.a1).limit(1)
        )
    edges = (
        datetime(2025, 10, 31, 23, 59, 59, 999999, tzinfo=UTC),
        datetime(2025, 11, 1, tzinfo=UTC),
        datetime(2025, 11, 30, 23, 59, 59, 999999, tzinfo=UTC),
        datetime(2025, 12, 1, tzinfo=UTC),
    )
    for moment in edges:
        _copy_event(w.db, template, moment)
    with Session(w.db.runtime) as session:
        october = plans.tracked_events(session, w.a, 2, datetime(2025, 10, 15, tzinfo=UTC))
        november = plans.tracked_events(session, w.a, 2, datetime(2025, 11, 15, 12, tzinfo=UTC))
        december = plans.tracked_events(session, w.a, 2, datetime(2025, 12, 1, tzinfo=UTC))
        other = plans.tracked_events(session, w.b, None, datetime(2025, 11, 15, tzinfo=UTC))
    assert (october.count, october.period_start, october.period_end) == (
        1,
        datetime(2025, 10, 1, tzinfo=UTC),
        datetime(2025, 11, 1, tzinfo=UTC),
    )
    assert (november.count, november.state) == (2, "within")
    assert (december.count, december.period_end) == (1, datetime(2026, 1, 1, tzinfo=UTC))
    assert (other.count, other.state) == (0, "unlimited")


def test_sv06_the_count_is_bounded(c, monkeypatch):
    w = c.w
    token = c.subject()
    for _ in range(3):
        assert c.send(envelope(token)).status_code == 201
    monkeypatch.setattr(plans, "EVENT_COUNT_BOUND", 2)
    view = c.owner.get(f"/agencies/{w.a}/plan").json()["tracked_events"]
    assert (view["count"], view["count_capped"]) == (2, True)


def test_sv07_usage_view_roles_keys_and_answer(authenticated_world, api):
    w = authenticated_world
    path = f"/agencies/{w.a}/plan"
    answers = {name: w.signed_in(name).get(path) for name in ("owner_a", "admin", "analyst")}
    assert {name: response.status_code for name, response in answers.items()} == dict.fromkeys(
        answers, 200
    )
    body = answers["owner_a"].json()
    assert set(body) == {"agency_id", "plan", "limits", "tracked_events", "as_of"}
    assert body["plan"]["key"] == "development" and body["agency_id"] == str(w.a)
    assert body["limits"] == [
        {"limit": "clients", "value": 5, "used": 2, "state": "within"},
        {"limit": "seats", "value": 10, "used": 4, "state": "within"},
        {"limit": "connections", "value": 10, "used": 0, "state": "within"},
        {"limit": "managed_links", "value": 500, "used": 0, "state": "within"},
    ]
    events = body["tracked_events"]
    assert (events["count"], events["allowance"], events["state"]) == (0, 100000, "within")
    for private in (str(w.a1), str(w.a2), "Synthetic", "@example.test", str(w.users.owner_a)):
        assert private not in answers["owner_a"].text
    # A client viewer, another agency's Owner, a non-member and any bearer key are refused.
    assert w.signed_in("viewer").get(path).status_code == 403
    assert w.signed_in("owner_b").get(path).status_code == 403
    assert w.signed_in("outsider").get(path).status_code == 403
    owner = w.signed_in("owner_a")
    for kind in ("read", "ingest"):
        issued = owner.post(
            f"/agencies/{w.a}/service-credentials",
            json={
                "name": f"Synthetic {kind}",
                "kind": kind,
                "clients": [{"client_id": str(w.a1)}],
            },
        )
        assert issued.status_code == 201
        reader = api.new_client()
        reader.headers["Authorization"] = "Bearer " + issued.json()["key"]
        assert reader.get(path).status_code == 401
    # Limits at and beyond their value, and unlimited ones.
    _limits(w.db, w.a, clients=2, seats=3)
    limits = {item["limit"]: item for item in owner.get(path).json()["limits"]}
    assert limits["clients"]["state"] == limits["seats"]["state"] == "at_limit"
    assert limits["connections"] == {
        "limit": "connections",
        "value": None,
        "used": 0,
        "state": "unlimited",
    }
    assert owner.get(path).json()["tracked_events"]["state"] == "unlimited"


def test_sv19_agencies_never_see_each_other_and_output_carries_no_secret(
    authenticated_world, capfd
):
    w = authenticated_world
    owner_a, owner_b = w.signed_in("owner_a"), w.signed_in("owner_b")
    _limits(w.db, w.b, clients=2)
    _refused(owner_b.post(f"/agencies/{w.b}/clients", json={"name": "B3"}), "clients", 2, 2)
    # Agency A keeps its own plan and counts only its own rows.
    assert owner_a.post(f"/agencies/{w.a}/clients", json={"name": "A3"}).status_code == 201
    view_a = owner_a.get(f"/agencies/{w.a}/plan").json()
    view_b = owner_b.get(f"/agencies/{w.b}/plan").json()
    assert view_a["plan"]["key"] == "development" and view_b["plan"]["key"].startswith("tight-")
    assert {item["limit"]: item["used"] for item in view_a["limits"]}["clients"] == 3
    assert {item["limit"]: item["used"] for item in view_b["limits"]}["clients"] == 2
    assert owner_a.get(f"/agencies/{w.b}/plan").status_code == 403
    assert owner_b.get(f"/agencies/{w.a}/plan").status_code == 403
    code, listing = agency_plans.run(w.db.runtime, "agencies")
    assert code == 0
    printed = json.dumps(listing)
    captured = capfd.readouterr()
    for private in ("Synthetic Agency", "Synthetic Client", "@example.test", "tsk_", "password"):
        assert private not in printed
        assert private not in captured.out + captured.err
