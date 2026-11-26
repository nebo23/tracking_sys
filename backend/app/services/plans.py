"""Plans, assignments and usage of an agency (specification 017-A, D-092 decisions D2-D7).

Every agency has exactly one current plan: its plan assignment with the highest revision. A new
agency gets the default plan in the transaction that creates it; the migration assigned the
seeded development plan to every agency that existed before. Use is computed from stored rows
on demand, never kept in a counter. The four counted limits are hard on creation only (D4);
the monthly tracked-event allowance is soft and never refuses an event (D5).

Callers that count for a limit check hold the agency row lock (SELECT ... FOR UPDATE through
TenancyService._manager(write=True)); under READ COMMITTED each count then sees every committed
creation, and a concurrent creation for the same agency waits and counts again.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import distinct, func, literal, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models import (
    AgencyInvitation,
    AgencyMembership,
    AgencyPlanAssignment,
    ClientWorkspace,
    CollectedEvent,
    ConnectorConnection,
    ManagedLink,
    SaasPlan,
)
from app.security import now_utc

Limit = Literal["clients", "seats", "connections", "managed_links"]
LIMITS: tuple[Limit, ...] = ("clients", "seats", "connections", "managed_links")
COLUMNS: dict[str, str] = {
    "clients": "clients_limit",
    "seats": "seats_limit",
    "connections": "connections_limit",
    "managed_links": "managed_links_limit",
    "tracked_events": "tracked_events_limit",
}
# Tracked events of one month are counted up to this bound; beyond it the count is reported as
# the bound with count_capped set (design-017a section 4).
EVENT_COUNT_BOUND = 1_000_000
LIVE_CONNECTIONS = ("active", "reconnect_required")


class PlanUnavailable(Exception):
    """The agency has no plan assignment, or no default plan exists; never expected."""

    code = "plan_unavailable"


@dataclass(frozen=True)
class CurrentPlan:
    plan: SaasPlan
    assignment: AgencyPlanAssignment


@dataclass(frozen=True)
class TrackedEvents:
    period_start: datetime
    period_end: datetime
    count: int
    count_capped: bool
    allowance: int | None

    @property
    def state(self) -> str:
        if self.allowance is None:
            return "unlimited"
        return "over_allowance" if self.count > self.allowance else "within"


@dataclass(frozen=True)
class LimitUse:
    limit: Limit
    value: int | None
    used: int

    @property
    def state(self) -> str:
        if self.value is None:
            return "unlimited"
        return "at_limit" if self.used >= self.value else "within"


@dataclass(frozen=True)
class AgencyUsage:
    agency_id: UUID
    current: CurrentPlan
    limits: tuple[LimitUse, ...]
    tracked_events: TrackedEvents
    as_of: datetime


# The agency's current plan and its assignment (the highest revision).
def current_plan(session: Session, agency_id: UUID) -> CurrentPlan:
    row = session.execute(
        select(SaasPlan, AgencyPlanAssignment)
        .join(AgencyPlanAssignment, AgencyPlanAssignment.plan_id == SaasPlan.id)
        .where(AgencyPlanAssignment.agency_id == agency_id)
        .order_by(AgencyPlanAssignment.revision.desc())
        .limit(1)
    ).first()
    if row is None:
        raise PlanUnavailable()
    return CurrentPlan(row[0], row[1])


# The plan new agencies receive.
def default_plan(session: Session) -> SaasPlan:
    plan = session.scalar(select(SaasPlan).where(SaasPlan.is_default.is_(True)))
    if plan is None:
        raise PlanUnavailable()
    return plan


# Record a new assignment of the agency (the caller holds the agency row lock or has just
# created the agency): the next revision, so the new row becomes the current plan.
def add_assignment(
    session: Session, agency_id: UUID, plan: SaasPlan, *, assigned_by: str, reason: str
) -> AgencyPlanAssignment:
    latest = session.scalar(
        select(func.max(AgencyPlanAssignment.revision)).where(
            AgencyPlanAssignment.agency_id == agency_id
        )
    )
    row = AgencyPlanAssignment(
        id=uuid4(),
        agency_id=agency_id,
        plan_id=plan.id,
        revision=(latest or 0) + 1,
        assigned_by=assigned_by,
        reason=reason,
    )
    session.add(row)
    session.flush()
    return row


# The default plan of a new agency, in the transaction that creates it (D3).
def assign_default(session: Session, agency_id: UUID) -> AgencyPlanAssignment:
    return add_assignment(
        session, agency_id, default_plan(session), assigned_by="default", reason="new_agency"
    )


# The agency's current use of one counted limit (design-017a section 3).
def use(session: Session, agency_id: UUID, limit: Limit, now: datetime | None = None) -> int:
    if limit == "clients":
        query = (
            select(func.count())
            .select_from(ClientWorkspace)
            .where(ClientWorkspace.agency_id == agency_id, ClientWorkspace.status == "active")
        )
    elif limit == "seats":
        moment = now or now_utc()
        members = (
            select(func.count())
            .select_from(AgencyMembership)
            .where(AgencyMembership.agency_id == agency_id, AgencyMembership.status == "active")
        )
        pending = (
            select(func.count())
            .select_from(AgencyInvitation)
            .where(
                AgencyInvitation.agency_id == agency_id,
                AgencyInvitation.status == "pending",
                AgencyInvitation.expires_at > moment,
            )
        )
        return int(session.scalar(members) or 0) + int(session.scalar(pending) or 0)
    elif limit == "connections":
        query = (
            select(func.count())
            .select_from(ConnectorConnection)
            .where(
                ConnectorConnection.agency_id == agency_id,
                ConnectorConnection.status.in_(LIVE_CONNECTIONS),
            )
        )
    elif limit == "managed_links":
        query = (
            select(func.count())
            .select_from(ManagedLink)
            .where(ManagedLink.agency_id == agency_id, ManagedLink.status == "active")
        )
    else:  # pragma: no cover - Limit is closed
        raise ValueError("Unknown limit.")
    return int(session.scalar(query) or 0)


# The UTC calendar month containing an instant: [start, end).
def month_of(instant: datetime) -> tuple[datetime, datetime]:
    moment = instant.astimezone(UTC)
    start = datetime(moment.year, moment.month, 1, tzinfo=UTC)
    if moment.month == 12:
        return start, datetime(moment.year + 1, 1, 1, tzinfo=UTC)
    return start, datetime(moment.year, moment.month + 1, 1, tzinfo=UTC)


# Events received in the month of `now` across every client of the agency, counted up to the
# bound with the (client_id, first_received_at) index. Nothing is refused or dropped (D5).
def tracked_events(
    session: Session, agency_id: UUID, allowance: int | None, now: datetime
) -> TrackedEvents:
    start, end = month_of(now)
    clients = list(
        session.scalars(select(ClientWorkspace.id).where(ClientWorkspace.agency_id == agency_id))
    )
    count = 0
    if clients:
        bounded = (
            select(literal(1))
            .where(
                CollectedEvent.agency_id == agency_id,
                CollectedEvent.client_id.in_(clients),
                CollectedEvent.first_received_at >= start,
                CollectedEvent.first_received_at < end,
            )
            .limit(EVENT_COUNT_BOUND + 1)
            .subquery()
        )
        count = int(session.scalar(select(func.count()).select_from(bounded)) or 0)
    capped = count > EVENT_COUNT_BOUND
    return TrackedEvents(start, end, min(count, EVENT_COUNT_BOUND), capped, allowance)


# The plan, the use of every limit and the month's tracked events of one agency, read in the
# caller's session (a READ ONLY REPEATABLE READ snapshot for the usage view).
def agency_usage(session: Session, agency_id: UUID, now: datetime | None = None) -> AgencyUsage:
    moment = now or session.scalar(select(func.now()))
    assert moment is not None
    current = current_plan(session, agency_id)
    limits = tuple(
        LimitUse(
            limit, getattr(current.plan, COLUMNS[limit]), use(session, agency_id, limit, moment)
        )
        for limit in LIMITS
    )
    events = tracked_events(session, agency_id, current.plan.tracked_events_limit, moment)
    return AgencyUsage(agency_id, current, limits, events, moment)


# The number of agencies whose current plan is each plan, for the operator's plan list.
def agencies_per_plan(session: Session) -> dict[UUID, int]:
    latest = (
        select(AgencyPlanAssignment.agency_id, AgencyPlanAssignment.plan_id)
        .ext(distinct_on(AgencyPlanAssignment.agency_id))
        .order_by(AgencyPlanAssignment.agency_id, AgencyPlanAssignment.revision.desc())
        .subquery()
    )
    rows = session.execute(
        select(latest.c.plan_id, func.count(distinct(latest.c.agency_id))).group_by(
            latest.c.plan_id
        )
    )
    return {plan_id: int(count) for plan_id, count in rows}
