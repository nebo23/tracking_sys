"""The plan and usage view of an agency (specification 017-A, D-092 decision D6).

Browser sessions only: a read or ingest key is refused by BrowserDep. After authentication the
answer is read in one READ ONLY REPEATABLE READ snapshot, which also checks the caller's
membership: an active Owner, Admin or Analyst of the active agency. The answer names no
client, person or event.
"""

from uuid import UUID

from fastapi import APIRouter, Request

from app.api.dependencies import BrowserDep
from app.api.schemas import (
    AgencyPlanResponse,
    PlanLimitUse,
    PlanSummary,
    TrackedEventsUse,
)
from app.services import plans
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
