"""Real PostgreSQL evidence for the approved 002-A authorization boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.database import Base, expected_revision, readiness_failure
from app.models import Agency, AgencyMembership, AuditEvent, ClientGrant, ClientWorkspace, User
from app.services.tenancy import AccessDenied, MembershipConflict, Role, tenancy_transaction

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "operation",
    [
        "read",
        "list",
        "update",
        "foreign_client_grant",
        "foreign_member_grant",
        "member_update",
        "audit",
        "agency_update",
        "revoke",
    ],
)
def test_cross_agency_operations_are_denied(world: SimpleNamespace, operation: str) -> None:
    w = world
    with pytest.raises(AccessDenied), tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        match operation:
            case "read":
                service.get_client(w.a, w.b1)
            case "list":
                service.list_clients(w.b)
            case "update":
                service.update_client(w.a, w.b1, name="Unauthorized change")
            case "foreign_client_grant":
                service.grant_client(w.a, w.b1, w.analyst)
            case "foreign_member_grant":
                service.grant_client(w.a, w.a1, w.other_member)
            case "member_update":
                service.update_member(w.a, w.other_member, status="disabled")
            case "audit":
                service.list_audit(w.b)
            case "agency_update":
                service.rename_agency(w.b, "Unauthorized change")
            case "revoke":
                service.revoke_client(w.a, w.b2, w.other_member)
    with tenancy_transaction(w.db.runtime, w.users.owner_b) as service:
        assert service.get_client(w.b, w.b1).name == "Synthetic Client B1"
        assert service.get_agency(w.b).name == "Synthetic Agency B"


@pytest.mark.parametrize("actor", ["analyst", "viewer"])
def test_restricted_members_need_explicit_client_and_financial_grants(
    world: SimpleNamespace, actor: str
) -> None:
    w = world
    actor_id = getattr(w.users, actor)
    with tenancy_transaction(w.db.runtime, actor_id) as service:
        assert [client.id for client in service.list_clients(w.a)] == [w.a1]
        assert service.get_client(w.a, w.a1).id == w.a1
        with pytest.raises(AccessDenied):
            service.get_client(w.a, w.a2)
        with pytest.raises(AccessDenied):
            service.require_financial_access(w.a, w.a1)
        with pytest.raises(AccessDenied):
            service.create_client(w.a, "Unauthorized client")
        with pytest.raises(AccessDenied):
            service.list_audit(w.a)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.grant_client(w.a, w.a1, getattr(w, actor), can_view_financials=True)
    with tenancy_transaction(w.db.runtime, actor_id) as service:
        service.require_financial_access(w.a, w.a1)
        with pytest.raises(AccessDenied):
            service.require_financial_access(w.a, w.a2)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.grant_client(w.a, w.a1, getattr(w, actor), can_view_financials=False)
    with pytest.raises(AccessDenied), tenancy_transaction(w.db.runtime, actor_id) as service:
        service.require_financial_access(w.a, w.a1)


def test_same_user_has_different_roles_per_agency(world: SimpleNamespace) -> None:
    w = world
    with tenancy_transaction(w.db.runtime, w.users.analyst) as service:
        assert len(service.list_clients(w.a)) == 1
        assert {client.id for client in service.list_clients(w.b)} == {w.b1, w.b2}
        service.require_financial_access(w.b, w.b1)
    with pytest.raises(AccessDenied), tenancy_transaction(w.db.runtime, w.users.viewer) as service:
        service.get_agency(w.a)


@pytest.mark.parametrize("boundary", ["membership", "user", "agency", "client", "grant"])
def test_revocation_is_rechecked_in_an_existing_session(
    world: SimpleNamespace, boundary: str
) -> None:
    w = world
    with tenancy_transaction(w.db.runtime, w.users.analyst) as current:
        assert current.get_client(w.a, w.a1).id == w.a1
        if boundary in {"user", "agency"}:
            model, key, status = (
                (User, w.users.analyst, "disabled")
                if boundary == "user"
                else (Agency, w.a, "suspended")
            )
            with w.db.migration.begin() as connection:
                connection.execute(update(model).where(model.id == key).values(status=status))
        else:
            with tenancy_transaction(w.db.runtime, w.users.owner_a) as owner:
                if boundary == "membership":
                    owner.update_member(w.a, w.analyst, status="disabled")
                elif boundary == "client":
                    owner.update_client(w.a, w.a1, status="archived")
                else:
                    owner.revoke_client(w.a, w.a1, w.analyst)
        with pytest.raises(AccessDenied):
            current.get_client(w.a, w.a1)


@pytest.mark.parametrize("operation", ["promote", "disable_owner", "demote_owner", "grant_owner"])
def test_admin_cannot_manage_owner_privileges(world: SimpleNamespace, operation: str) -> None:
    w = world
    with pytest.raises(AccessDenied), tenancy_transaction(w.db.runtime, w.users.admin) as service:
        match operation:
            case "promote":
                service.update_member(w.a, w.admin, role=Role.OWNER)
            case "disable_owner":
                service.update_member(w.a, w.owner_a, status="disabled")
            case "demote_owner":
                service.update_member(w.a, w.owner_a, role=Role.ANALYST)
            case "grant_owner":
                service.grant_client(w.a, w.a1, w.owner_a)


@pytest.mark.parametrize("operation", ["disable", "demote"])
def test_last_owner_cannot_be_removed(world: SimpleNamespace, operation: str) -> None:
    w = world
    with pytest.raises(MembershipConflict), tenancy_transaction(w.db.runtime, w.users.owner_a) as s:
        if operation == "disable":
            s.update_member(w.a, w.owner_a, status="disabled")
        else:
            s.update_member(w.a, w.owner_a, role=Role.ADMIN)


def test_concurrent_owner_changes_preserve_an_active_owner(world: SimpleNamespace) -> None:
    w = world
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        second = service.add_member(w.a, w.users.second_owner, Role.OWNER)
    barrier = Barrier(2)

    def demote_self(user_id: UUID, membership_id: UUID) -> str:
        barrier.wait(timeout=5)
        try:
            with tenancy_transaction(w.db.runtime, user_id) as service:
                service.update_member(w.a, membership_id, role=Role.ADMIN)
            return "changed"
        except MembershipConflict:
            return "protected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(demote_self, w.users.owner_a, w.owner_a)
        other = pool.submit(demote_self, w.users.second_owner, second.id)
        assert sorted([first.result(timeout=10), other.result(timeout=10)]) == [
            "changed",
            "protected",
        ]
    with Session(w.db.runtime) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgencyMembership)
                .where(
                    AgencyMembership.agency_id == w.a,
                    AgencyMembership.role == "owner",
                    AgencyMembership.status == "active",
                )
            )
            == 1
        )


@pytest.mark.parametrize("foreign_field", ["client", "membership"])
def test_database_rejects_cross_agency_grants(world: SimpleNamespace, foreign_field: str) -> None:
    w = world
    with pytest.raises(IntegrityError), Session(w.db.runtime) as session, session.begin():
        session.add(
            ClientGrant(
                agency_id=w.a,
                client_id=w.b1 if foreign_field == "client" else w.a1,
                membership_id=w.other_member if foreign_field == "membership" else w.analyst,
            )
        )
        session.flush()


@pytest.mark.parametrize("foreign_field", ["client", "actor"])
def test_database_rejects_cross_agency_audit_references(
    world: SimpleNamespace, foreign_field: str
) -> None:
    w = world
    with pytest.raises(IntegrityError), Session(w.db.runtime) as session, session.begin():
        session.add(
            AuditEvent(
                agency_id=w.a,
                client_id=w.b1 if foreign_field == "client" else w.a1,
                actor_user_id=w.users.owner_b if foreign_field == "actor" else w.users.owner_a,
                action="client.updated",
                resource_type="client",
                resource_id=w.a1,
            )
        )
        session.flush()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action='client.updated'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
        "UPDATE alembic_version SET version_num='tampered'",
        "UPDATE users SET created_at = now()",
        "DELETE FROM client_workspaces",
    ],
)
def test_runtime_has_only_required_table_privileges(world: SimpleNamespace, statement: str) -> None:
    with pytest.raises(DBAPIError) as error, world.db.runtime.begin() as connection:
        connection.execute(text(statement))
    assert error.value.orig.sqlstate == "42501"


def test_mutation_and_audit_roll_back_together(world: SimpleNamespace) -> None:
    w = world
    with Session(w.db.runtime) as session:
        before = session.scalar(select(func.count()).select_from(AuditEvent))
    with pytest.raises(RuntimeError), tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        client = service.create_client(w.a, "Must roll back")
        client_id = client.id
        raise RuntimeError("Synthetic transaction failure")
    with Session(w.db.runtime) as session:
        assert session.get(ClientWorkspace, client_id) is None
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == before


def test_audit_constraint_failure_rolls_back_the_mutation(world: SimpleNamespace) -> None:
    w = world
    with (
        pytest.raises(IntegrityError),
        tenancy_transaction(w.db.runtime, w.users.owner_a) as service,
    ):
        service.rename_agency(w.a, "Must roll back")
        service.session.add(
            AuditEvent(
                agency_id=w.a,
                actor_user_id=w.users.owner_a,
                action="invalid_action",
                resource_type="agency",
                resource_id=w.a,
            )
        )
        service.session.flush()
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        assert service.get_agency(w.a).name == "Synthetic Agency A"
        assert all(event.agency_id == w.a for event in service.list_audit(w.a))


def test_successful_changes_have_scoped_identifier_only_audit(world: SimpleNamespace) -> None:
    w = world
    with tenancy_transaction(w.db.runtime, w.users.admin) as service:
        service.update_client(w.a, w.a1, name="Updated synthetic client")
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        events = [event for event in service.list_audit(w.a) if event.action == "client.updated"]
        assert len(events) == 1
        assert (events[0].actor_user_id, events[0].client_id, events[0].resource_id) == (
            w.users.admin,
            w.a1,
            w.a1,
        )
        assert events[0].occurred_at.tzinfo is not None
    assert set(AuditEvent.__table__.columns.keys()) == {
        "id",
        "agency_id",
        "client_id",
        "actor_user_id",
        "action",
        "resource_type",
        "resource_id",
        "occurred_at",
    }


def test_unknown_actor_is_denied(world: SimpleNamespace) -> None:
    with pytest.raises(AccessDenied), tenancy_transaction(world.db.runtime, uuid4()) as service:
        service.get_client(world.a, world.a1)


def test_duplicate_membership_and_invalid_role_do_not_add_access(world: SimpleNamespace) -> None:
    w = world
    with pytest.raises(MembershipConflict), tenancy_transaction(w.db.runtime, w.users.owner_a) as s:
        s.add_member(w.a, w.users.analyst, Role.ADMIN)
    with pytest.raises(ValueError), tenancy_transaction(w.db.runtime, w.users.owner_a) as s:
        s.add_member(w.a, w.users.second_owner, "unknown_role")


def test_populated_schema_cannot_be_downgraded(world: SimpleNamespace) -> None:
    with pytest.raises(RuntimeError, match="non-empty"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0001_foundation")
    assert readiness_failure(world.db.runtime, expected_revision()) is None
    with tenancy_transaction(world.db.runtime, world.users.owner_a) as service:
        assert service.get_client(world.a, world.a1).id == world.a1


def test_migration_matches_model_metadata(db: SimpleNamespace) -> None:
    with db.migration.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
    assert readiness_failure(db.runtime, expected_revision()) is None
