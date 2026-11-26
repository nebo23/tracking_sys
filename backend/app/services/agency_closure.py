"""Agency closure by its Owner (specification 017-A, D-092 decision D8; design-017a section 5).

An active Owner requests closure with the agency's exact name and the account-closure
reauthentication of D-024. The agency becomes closing at once, which stops it exactly as a
suspended agency is stopped, because every existing check requires status 'active'. For 30
days an Owner can read the closure and cancel it, which returns the agency to active with its
connections untouched. Then the lifecycle runner marks the agency closed
(app.services.agency_lifecycle); a closed agency is refused everywhere and nothing reopens it.
The closure routes are the only routes, besides the agency list, that read a closing agency.
"""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Agency, AgencyClosure, AgencyMembership, AuthSession, User
from app.security import now_utc
from app.services.auth import AuthService
from app.services.tenancy import AccessDenied, Role, TenancyService

GRACE_PERIOD = timedelta(days=30)
READABLE = ("active", "closing")


class ClosureRefused(Exception):
    """A refusal of a closure route with a closed code and HTTP status."""

    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


# The open closure of an agency (neither cancelled nor completed), optionally locked.
def open_closure(session: Session, agency_id: UUID, *, lock: bool = False) -> AgencyClosure | None:
    query = select(AgencyClosure).where(
        AgencyClosure.agency_id == agency_id,
        AgencyClosure.cancelled_at.is_(None),
        AgencyClosure.completed_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    return session.scalar(query.execution_options(populate_existing=True))


class ClosureService(TenancyService):
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    # The actor's active Owner membership in an active or closing agency; with write=True the
    # agency row is locked first, as every agency mutation does. Anything else is denied.
    def _closure_owner(self, agency_id: UUID, *, write: bool) -> tuple[Agency, AgencyMembership]:
        query = select(Agency).where(Agency.id == agency_id, Agency.status.in_(READABLE))
        if write:
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
        if member is None or member.role != Role.OWNER:
            raise AccessDenied()
        return agency, member

    # Request closure (D8): Owner only, the exact agency name, then the reauthentication of
    # account closure (the current password, or for an account without one a recent session).
    # The closure row and the closing status are written together and audited.
    def request(
        self,
        agency_id: UUID,
        *,
        confirm_name: str,
        password: str | None,
        user: User,
        auth_session: AuthSession,
        now: datetime | None = None,
    ) -> AgencyClosure:
        agency, member = self._closure_owner(agency_id, write=True)
        if agency.status != "active":
            raise ClosureRefused("closure_in_progress", 409)
        if confirm_name != agency.name:
            raise ClosureRefused("confirmation_mismatch", 422)
        AuthService(self.session, self.settings).reauthenticate(user, auth_session, password)
        moment = now or now_utc()
        closure = AgencyClosure(
            id=uuid4(),
            agency_id=agency_id,
            requested_by_membership_id=member.id,
            requested_at=moment,
            closes_at=moment + GRACE_PERIOD,
        )
        self.session.add(closure)
        agency.status = "closing"
        self._audit(agency_id, "agency.closure_requested", "agency_closure", closure.id)
        return closure

    # The agency's status and its open closure, for its Owners while active or closing.
    def read(self, agency_id: UUID) -> tuple[Agency, AgencyClosure | None]:
        agency, _ = self._closure_owner(agency_id, write=False)
        return agency, open_closure(self.session, agency_id)

    # Cancel within the grace period (D8): the agency is active again and its connections,
    # never revoked by the request, keep working. Audited.
    def cancel(self, agency_id: UUID, *, now: datetime | None = None) -> Agency:
        agency, member = self._closure_owner(agency_id, write=True)
        closure = open_closure(self.session, agency_id, lock=True)
        if agency.status != "closing" or closure is None:
            raise ClosureRefused("closure_not_open", 409)
        moment = now or now_utc()
        if moment >= closure.closes_at:
            raise ClosureRefused("grace_period_ended", 409)
        closure.cancelled_at, closure.cancelled_by_membership_id = moment, member.id
        agency.status = "active"
        self._audit(agency_id, "agency.closure_cancelled", "agency_closure", closure.id)
        return agency
