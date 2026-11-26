"""The plan, usage and closure routes of an agency (specification 017-A, D-092 D6 and D8).

Browser sessions only: a read or ingest key is refused by BrowserDep. The usage view is read
after authentication in one READ ONLY REPEATABLE READ snapshot, which also checks the caller's
membership: an active Owner, Admin or Analyst of the active agency. The answer names no client,
person or event. The closure routes are for an agency's active Owners, also while the agency is
closing; a request is throttled like account closure and reauthenticated.
"""

from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.api.auth import throttle
from app.api.dependencies import BrowserDep, SessionDep
from app.api.schemas import (
    AgencyClosureInput,
    AgencyClosureResponse,
    AgencyPlanResponse,
    OpenAgencyClosure,
    PlanLimitUse,
    PlanSummary,
    TrackedEventsUse,
)
from app.models import Agency, AgencyClosure
from app.services import plans
from app.services.agency_closure import ClosureService
from app.services.reporting import report_snapshot
from app.services.tenancy import AccessDenied, Role, TenancyService

router = APIRouter(tags=["Plans and closure"])


# The agency's plan, the use of each limit and the current UTC month's tracked events. The
# answer is built inside the snapshot, before its commit expires the loaded rows.
@router.get("/agencies/{agency_id}/plan", response_model=AgencyPlanResponse)
def agency_plan(agency_id: UUID, request: Request, browser: BrowserDep) -> AgencyPlanResponse:
    with report_snapshot(request.app.state.engine) as snapshot:
        member = TenancyService(snapshot, browser.user.id)._membership(agency_id)
        if member.role == Role.CLIENT_VIEWER:
            raise AccessDenied()
        usage = plans.agency_usage(snapshot, agency_id)
        events = usage.tracked_events
        return AgencyPlanResponse(
            agency_id=agency_id,
            plan=PlanSummary(
                key=usage.current.plan.key,
                name=usage.current.plan.name,
                assigned_at=usage.current.assignment.assigned_at,
            ),
            limits=[
                PlanLimitUse(limit=item.limit, value=item.value, used=item.used, state=item.state)
                for item in usage.limits
            ],
            tracked_events=TrackedEventsUse(
                period_start=events.period_start,
                period_end=events.period_end,
                count=events.count,
                count_capped=events.count_capped,
                allowance=events.allowance,
                state=events.state,
            ),
            as_of=usage.as_of,
        )


def _closure(request: Request, session, browser) -> ClosureService:
    return ClosureService(session, browser.user.id, request.app.state.settings)


def _state(agency: Agency, closure: AgencyClosure | None) -> AgencyClosureResponse:
    return AgencyClosureResponse(
        agency_id=agency.id,
        agency_status="closing" if agency.status == "closing" else "active",
        closure=None if closure is None else OpenAgencyClosure.model_validate(closure),
    )


# Request the closure of the agency (Owner only): the exact name and the reauthentication of
# account closure. The agency stops at once and closes after 30 days unless an Owner cancels.
@router.post("/agencies/{agency_id}/closure", status_code=201, response_model=AgencyClosureResponse)
def request_closure(
    agency_id: UUID,
    data: AgencyClosureInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> AgencyClosureResponse:
    throttle(request, "agency-closure", str(browser.user.id))
    service = _closure(request, session, browser)
    closure = service.request(
        agency_id,
        confirm_name=data.confirm_name,
        password=data.password.get_secret_value() if data.password is not None else None,
        user=browser.user,
        auth_session=browser.session,
    )
    session.flush()
    return _state(session.get_one(Agency, agency_id), closure)


# The closure state of the agency, for its Owners while it is active or closing.
@router.get("/agencies/{agency_id}/closure", response_model=AgencyClosureResponse)
def read_closure(
    agency_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> AgencyClosureResponse:
    agency, closure = _closure(request, session, browser).read(agency_id)
    return _state(agency, closure)


# Cancel the closure within its grace period (Owner only); the agency is active again.
@router.delete("/agencies/{agency_id}/closure", status_code=204)
def cancel_closure(
    agency_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> Response:
    _closure(request, session, browser).cancel(agency_id)
    return Response(status_code=204)
