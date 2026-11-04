"""Database-backed access checks for trusted actors, never HTTP identity input.

Use tenancy_transaction for each unit of work. HTTP routes derive actor identifiers
from authenticated sessions; never accept an actor identifier from request data.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Engine, Select, func, select
from sqlalchemy.orm import Session

from app.models import Agency, AgencyMembership, AuditEvent, ClientGrant, ClientWorkspace, User


# Uniform denial for missing, foreign, inactive, or unauthorized resources. The API maps it to
# one 403 code, so callers cannot distinguish nonexistent from forbidden objects.
class AccessDenied(PermissionError):
    # Use a fixed message so no identifier or policy detail leaks through the exception.
    def __init__(self) -> None:
        super().__init__("Access is not permitted.")


class MembershipConflict(ValueError):
    """An allowed request conflicts with membership invariants."""


# Fixed versioned role policy stored as lowercase strings; unknown stored roles are denied.
class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    CLIENT_VIEWER = "client_viewer"


# Roles allowed to administer agency settings, clients, members, grants, audit, and keys.
MANAGERS = frozenset({Role.OWNER, Role.ADMIN})


# Context manager for non-HTTP callers and tests: one Session/transaction per unit of work.
@contextmanager
def tenancy_transaction(engine: Engine, actor_user_id: UUID) -> Iterator["TenancyService"]:
    """Commit mutations and audit together; close/roll back the session on failure."""
    with Session(engine, expire_on_commit=False) as session, session.begin():
        yield TenancyService(session, actor_user_id)


# Agency and client authorization plus audited mutations for one trusted actor. Every check
# reads current database state; nothing is trusted from caller-supplied roles. Methods flush but
# never commit: the caller's transaction commits mutations and audit events together.
class TenancyService:
    # Bind the caller's transaction and the actor ID resolved by authentication.
    def __init__(self, session: Session, actor_user_id: UUID) -> None:
        self.session = session
        self.actor_user_id = actor_user_id

    # Require an administratively active user (no row lock); disabled or unknown users are denied.
    def _active_user(self, user_id: UUID) -> User:
        user = self.session.scalar(
            select(User)
            .where(User.id == user_id, User.status == "active")
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise AccessDenied()
        return user

    # Resolve the actor's active membership in an active agency. With write=True the agency row is
    # locked FOR UPDATE first, serializing every agency mutation, including Owner changes.
    def _membership(self, agency_id: UUID, *, write: bool = False) -> AgencyMembership:
        query = select(Agency).where(Agency.id == agency_id, Agency.status == "active")
        if write:
            # All agency mutations share this lock, including owner changes/revocation.
            query = query.with_for_update()
        agency = self.session.scalar(query.execution_options(populate_existing=True))
        if agency is None:
            raise AccessDenied()
        self._active_user(self.actor_user_id)
        member = self.session.scalar(
            select(AgencyMembership)
            .where(
                AgencyMembership.agency_id == agency_id,
                AgencyMembership.user_id == self.actor_user_id,
                AgencyMembership.status == "active",
            )
            .execution_options(populate_existing=True)
        )
        if member is None or member.role not in set(Role):
            raise AccessDenied()
        return member

    # Like _membership, but additionally require the Owner or Admin role.
    def _manager(self, agency_id: UUID, *, write: bool = False) -> AgencyMembership:
        member = self._membership(agency_id, write=write)
        if member.role not in MANAGERS:
            raise AccessDenied()
        return member

    # Trim and bound agency, client, and credential names to 1-200 characters.
    @staticmethod
    def _name(value: str) -> str:
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("A name must contain between 1 and 200 characters.")
        return value

    # Append an audit event attributed to this service's actor in the same transaction. Flushing
    # before and after surfaces foreign-key or constraint errors inside the mutating operation.
    def _audit(
        self,
        agency_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        client_id: UUID | None = None,
    ) -> None:
        # Flush referenced entities first; the audit shares the caller's transaction.
        self.session.flush()
        self.session.add(
            AuditEvent(
                agency_id=agency_id,
                client_id=client_id,
                actor_user_id=self.actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )
        self.session.flush()

    # Create an agency and an Owner membership for the actor; audited.
    def create_agency(self, name: str) -> Agency:
        self._active_user(self.actor_user_id)
        agency = Agency(name=self._name(name))
        self.session.add(agency)
        self.session.flush()
        self.session.add(
            AgencyMembership(agency_id=agency.id, user_id=self.actor_user_id, role=Role.OWNER.value)
        )
        self._audit(agency.id, "agency.created", "agency", agency.id)
        return agency

    # Return the agency profile to Owner, Admin, or Analyst members; ClientViewer is denied.
    def get_agency(self, agency_id: UUID) -> Agency:
        member = self._membership(agency_id)
        if member.role == Role.CLIENT_VIEWER:
            raise AccessDenied()
        return self.session.get_one(Agency, agency_id)

    # Rename the agency under the manager write lock; audited.
    def rename_agency(self, agency_id: UUID, name: str) -> Agency:
        self._manager(agency_id, write=True)
        agency = self.session.get_one(Agency, agency_id)
        agency.name = self._name(name)
        self._audit(agency_id, "agency.updated", "agency", agency_id)
        return agency

    # Create a client workspace under the manager write lock; audited with its client ID.
    def create_client(self, agency_id: UUID, name: str) -> ClientWorkspace:
        self._manager(agency_id, write=True)
        client = ClientWorkspace(agency_id=agency_id, name=self._name(name))
        self.session.add(client)
        self.session.flush()
        self._audit(agency_id, "client.created", "client", client.id, client.id)
        return client

    # Build the query of active clients visible to a membership: managers see every client in the
    # agency; restricted roles see only clients with an explicit grant to that membership.
    def _client_query(self, member: AgencyMembership) -> Select[tuple[ClientWorkspace]]:
        query = select(ClientWorkspace).where(
            ClientWorkspace.agency_id == member.agency_id,
            ClientWorkspace.status == "active",
        )
        if member.role not in MANAGERS:
            query = query.join(
                ClientGrant,
                (
                    (ClientGrant.agency_id == ClientWorkspace.agency_id)
                    & (ClientGrant.client_id == ClientWorkspace.id)
                    & (ClientGrant.membership_id == member.id)
                ),
            )
        return query.execution_options(populate_existing=True)

    # List visible active clients in stable ID order for any active member.
    def list_clients(
        self, agency_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[ClientWorkspace]:
        member = self._membership(agency_id)
        return list(
            self.session.scalars(
                self._client_query(member).order_by(ClientWorkspace.id).limit(limit).offset(offset)
            )
        )

    # List all memberships of the agency for Owner/Admin managers.
    def list_members(
        self, agency_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgencyMembership]:
        self._manager(agency_id)
        return list(
            self.session.scalars(
                select(AgencyMembership)
                .where(AgencyMembership.agency_id == agency_id)
                .order_by(AgencyMembership.id)
                .limit(limit)
                .offset(offset)
            )
        )

    # Return one visible active client or raise AccessDenied.
    def get_client(self, agency_id: UUID, client_id: UUID) -> ClientWorkspace:
        member = self._membership(agency_id)
        client = self.session.scalar(
            self._client_query(member).where(ClientWorkspace.id == client_id)
        )
        if client is None:
            raise AccessDenied()
        return client

    # Authorize future financial reads: managers qualify for visible clients; restricted roles need
    # a grant with can_view_financials set. No financial data exists in this specification.
    def require_financial_access(self, agency_id: UUID, client_id: UUID) -> None:
        member = self._membership(agency_id)
        client = self.session.scalar(
            self._client_query(member).where(ClientWorkspace.id == client_id)
        )
        if client is None:
            raise AccessDenied()
        if member.role not in MANAGERS:
            allowed = self.session.scalar(
                select(ClientGrant.can_view_financials).where(
                    ClientGrant.agency_id == agency_id,
                    ClientGrant.client_id == client_id,
                    ClientGrant.membership_id == member.id,
                )
            )
            if allowed is not True:
                raise AccessDenied()

    # Rename or change the status of a client (including archived ones) under the manager write
    # lock; audited.
    def update_client(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
    ) -> ClientWorkspace:
        self._manager(agency_id, write=True)
        client = self.session.scalar(
            select(ClientWorkspace)
            .where(ClientWorkspace.agency_id == agency_id, ClientWorkspace.id == client_id)
            .execution_options(populate_existing=True)
        )
        if client is None:
            raise AccessDenied()
        if status is not None and status not in {"active", "archived"}:
            raise ValueError("Invalid workspace status.")
        if name is not None:
            client.name = self._name(name)
        if status is not None:
            client.status = status
        self._audit(agency_id, "client.updated", "client", client.id, client.id)
        return client

    # Add an active user as a member under the manager write lock. Only an Owner may add an Owner;
    # an existing membership in the agency conflicts. Audited as the acting manager.
    def add_member(self, agency_id: UUID, user_id: UUID, role: Role) -> AgencyMembership:
        actor = self._manager(agency_id, write=True)
        role = Role(role)
        if role == Role.OWNER and actor.role != Role.OWNER:
            raise AccessDenied()
        self._active_user(user_id)
        existing = self.session.scalar(
            select(AgencyMembership.id).where(
                AgencyMembership.agency_id == agency_id, AgencyMembership.user_id == user_id
            )
        )
        if existing is not None:
            raise MembershipConflict("This user already has a membership in the agency.")
        member = AgencyMembership(agency_id=agency_id, user_id=user_id, role=role.value)
        self.session.add(member)
        self.session.flush()
        self._audit(agency_id, "membership.created", "membership", member.id)
        return member

    # Load a membership only within the given agency; foreign IDs are denied.
    def _target_member(self, agency_id: UUID, membership_id: UUID) -> AgencyMembership:
        member = self.session.scalar(
            select(AgencyMembership)
            .where(AgencyMembership.agency_id == agency_id, AgencyMembership.id == membership_id)
            .execution_options(populate_existing=True)
        )
        if member is None:
            raise AccessDenied()
        return member

    # Change role/status under the agency write lock. Admins cannot change or create Owners. Because
    # the lock serializes all agency mutations, the active-Owner count cannot race: removing or
    # demoting the last active Owner whose user is active raises MembershipConflict. Audited.
    def update_member(
        self,
        agency_id: UUID,
        membership_id: UUID,
        *,
        role: Role | None = None,
        status: str | None = None,
    ) -> AgencyMembership:
        actor = self._manager(agency_id, write=True)
        member = self._target_member(agency_id, membership_id)
        next_role = Role(role) if role is not None else Role(member.role)
        next_status = status if status is not None else member.status
        if next_status not in {"active", "disabled"}:
            raise ValueError("Invalid membership status.")
        if actor.role != Role.OWNER and (member.role == Role.OWNER or next_role == Role.OWNER):
            raise AccessDenied()
        if (
            member.role == Role.OWNER
            and member.status == "active"
            and (next_role != Role.OWNER or next_status != "active")
        ):
            owners = self.session.scalar(
                select(func.count())
                .select_from(AgencyMembership)
                .join(User, User.id == AgencyMembership.user_id)
                .where(
                    AgencyMembership.agency_id == agency_id,
                    AgencyMembership.role == Role.OWNER,
                    AgencyMembership.status == "active",
                    User.status == "active",
                )
            )
            if owners is None or owners <= 1:
                raise MembershipConflict("An agency must retain an active Owner.")
        member.role, member.status = next_role.value, next_status
        self._audit(agency_id, "membership.updated", "membership", member.id)
        return member

    # Create or update an explicit client grant for an active membership in the same agency, with
    # optional financial visibility. Admins cannot grant to Owner memberships. Audited.
    def grant_client(
        self,
        agency_id: UUID,
        client_id: UUID,
        membership_id: UUID,
        *,
        can_view_financials: bool = False,
    ) -> ClientGrant:
        actor = self._manager(agency_id, write=True)
        member = self._target_member(agency_id, membership_id)
        if actor.role != Role.OWNER and member.role == Role.OWNER:
            raise AccessDenied()
        if member.status != "active":
            raise AccessDenied()
        self.get_client(agency_id, client_id)
        grant = self.session.get(ClientGrant, (agency_id, client_id, membership_id))
        action = "grant.updated" if grant is not None else "grant.created"
        if grant is None:
            grant = ClientGrant(
                agency_id=agency_id, client_id=client_id, membership_id=membership_id
            )
            self.session.add(grant)
        grant.can_view_financials = can_view_financials
        self._audit(agency_id, action, "membership", membership_id, client_id)
        return grant

    # Delete an explicit grant if present (idempotent otherwise); audited when a row is removed.
    def revoke_client(self, agency_id: UUID, client_id: UUID, membership_id: UUID) -> None:
        actor = self._manager(agency_id, write=True)
        member = self._target_member(agency_id, membership_id)
        if actor.role != Role.OWNER and member.role == Role.OWNER:
            raise AccessDenied()
        client = self.session.scalar(
            select(ClientWorkspace.id).where(
                ClientWorkspace.agency_id == agency_id, ClientWorkspace.id == client_id
            )
        )
        if client is None:
            raise AccessDenied()
        grant = self.session.get(ClientGrant, (agency_id, client_id, membership_id))
        if grant is not None:
            self.session.delete(grant)
            self._audit(agency_id, "grant.revoked", "membership", membership_id, client_id)

    # Return the newest agency audit events for Owner/Admin managers, bounded to 100.
    def list_audit(self, agency_id: UUID, *, limit: int = 100) -> list[AuditEvent]:
        self._manager(agency_id)
        if not 1 <= limit <= 100:
            raise ValueError("Audit page size must be between 1 and 100.")
        return list(
            self.session.scalars(
                select(AuditEvent)
                .where(AuditEvent.agency_id == agency_id)
                .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
                .limit(limit)
            )
        )
