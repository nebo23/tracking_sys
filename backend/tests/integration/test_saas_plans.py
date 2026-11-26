"""Plans, assignments, the operator command and migration 0031 (017-A, D-092).

Cases SV01, SV08, SV09 and SV18 of the entry review's verification matrix, on synthetic data
in the disposable database only. Later phases add the limit, usage and isolation cases.
"""

import json
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import agency_plans
from app.config import BACKEND_ROOT
from app.models import AgencyPlanAssignment, AuditEvent, SaasPlan
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import tenancy_transaction

pytestmark = pytest.mark.integration
CONFIG = Config(str(BACKEND_ROOT / "alembic.ini"))
HEAD = "0031_saas_plans"
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
    assert [item["key"] for item in json.loads(result.stdout)] == ["development"]
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
            plans = list(session.scalars(select(SaasPlan)))
            assert [(p.key, p.is_default, p.reason) for p in plans] == [
                ("development", True, "seed")
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
    for insert, cleanup in stored:
        with w.db.migration.begin() as connection:
            connection.execute(text(insert), {**values, "id": uuid4()})
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
