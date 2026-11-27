"""Retained report export routes (specification 016-C, D-095 decisions D2 to D7).

Below /agencies/{agency_id}/clients/{client_id}/report-exports, for browser sessions only (a
service key of either kind is refused):

- POST creates an export of one report family with the parameters and bounds of its report
  route and the dates of its period. It needs the family's permission; attribution and funnel
  exports hold sale values exactly when the creator holds finance:read. At most 50 unexpired
  exports per client; a missing token keyring answers not_configured.
- GET lists the visible exports, newest first; GET /{export_id} returns one.
- GET /{export_id}/download resolves the scope again and returns the CSV attachment, equal byte
  for byte to the direct CSV of the same revision, with Cache-Control: no-store.
- DELETE /{export_id} revokes it, by its creator or an Owner or Admin; audited.

A revoked or expired export answers export_gone (410).

Below /agencies/{agency_id}/clients/{client_id}/report-schedules (D8, D9): Owners and Admins
create, read, change and delete the schedules of a client (at most 10 active); a recipient reads
the schedules it receives and leaves one with DELETE /{schedule_id}/recipients/me. Recipients
are listed to managers only. Refusals carry a closed code only.
"""

from datetime import date as CalendarDate
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field, StringConstraints

from app.api.dependencies import BrowserDep, SessionDep
from app.api.schemas import Input, Output
from app.models import AgencyMembership, ReportExport, ReportSchedule
from app.reporting.csv_export import FILENAMES
from app.services.access import resolve_scope
from app.services.report_exports import (
    FAMILY_KEYS,
    ExportRequest,
    ExportService,
    create_export,
)
from app.services.report_schedules import (
    PLACEHOLDER,
    ScheduleService,
    schedule_spec,
)
from app.services.reporting import FINANCE_SPLIT, PERMISSIONS, ReportQuery
from app.services.tenancy import MANAGERS

router = APIRouter(tags=["Report delivery"])
BASE = "/agencies/{agency_id}/clients/{client_id}"
Metric = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_]{1,64}$")]
Compare = Literal["previous"] | None
CSV_DOWNLOAD: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        "description": "The stored CSV attachment of the export.",
    }
}


# --- report parameters (design-016c.md section 3.1) -------------------------------------------


class SocialParameters(Input):
    family: Literal["social"]
    connection_id: UUID
    view: Literal["daily", "content_cohort"]
    metrics: Annotated[list[Metric], Field(min_length=1, max_length=25)] | None = None
    compare: Compare = None


class SpendParameters(Input):
    family: Literal["spend"]
    connection_id: UUID
    level: Literal["ad", "adset", "campaign"] = "ad"
    compare: Compare = None


class RevenueParameters(Input):
    family: Literal["revenue"]
    compare: Compare = None


class AttributionParameters(Input):
    family: Literal["attribution"]
    group_by: Literal["campaign", "content", "link", "recipient"] = "campaign"
    view: Literal["groups", "models"] = "groups"
    model_version: UUID | None = None
    compare: Compare = None


class RoasParameters(Input):
    family: Literal["roas"]
    connection_id: UUID
    level: Literal["ad", "adset", "campaign"] = "ad"
    model_version: UUID | None = None
    compare: Compare = None


class FunnelParameters(Input):
    family: Literal["funnel"]
    group_by: Literal["campaign", "content", "link"] = "campaign"
    model_version: UUID | None = None
    compare: Compare = None


ReportParameters = Annotated[
    SocialParameters
    | SpendParameters
    | RevenueParameters
    | AttributionParameters
    | RoasParameters
    | FunnelParameters,
    Field(discriminator="family"),
]


class _Dates(Input):
    start: CalendarDate
    end: CalendarDate


class SocialExportInput(SocialParameters, _Dates):
    pass


class SpendExportInput(SpendParameters, _Dates):
    pass


class RevenueExportInput(RevenueParameters, _Dates):
    pass


class AttributionExportInput(AttributionParameters, _Dates):
    pass


class RoasExportInput(RoasParameters, _Dates):
    pass


class FunnelExportInput(FunnelParameters, _Dates):
    pass


ExportInput = Annotated[
    SocialExportInput
    | SpendExportInput
    | RevenueExportInput
    | AttributionExportInput
    | RoasExportInput
    | FunnelExportInput,
    Field(discriminator="family"),
]


def report_query(data: Any, start: CalendarDate, end: CalendarDate) -> ReportQuery:
    """The ReportQuery of a parameter object, validated like its report route."""
    values: dict[str, Any] = {key: getattr(data, key) for key in FAMILY_KEYS[data.family]}
    if values.get("metrics") is not None:
        values["metrics"] = tuple(values["metrics"])
    query = ReportQuery(data.family, start, end, data.compare is not None, **values)
    query.periods()
    return query


# --- answers ----------------------------------------------------------------------------------


class ExportPeriod(Output):
    start: CalendarDate
    end: CalendarDate
    days: int


class ReportExportView(Output):
    id: UUID
    client_id: UUID
    family: Literal["social", "spend", "revenue", "attribution", "roas", "funnel"]
    parameters: dict[str, Any]
    period: ExportPeriod
    includes_financials: bool
    source: Literal["manual", "schedule"]
    schedule_id: UUID | None
    requested_by_membership_id: UUID
    status: Literal["ready", "revoked", "expired"]
    revoked_reason: (
        Literal["manual", "erasure", "disconnection", "connection_purged", "client_archived"] | None
    )
    revoked_at: datetime | None
    created_at: datetime
    expires_at: datetime
    row_count: int | None
    byte_size: int | None
    report_revision: str | None
    download_count: int
    last_downloaded_at: datetime | None


class ReportExportList(Output):
    exports: list[ReportExportView]
    limit: int
    offset: int


def export_view(item: ReportExport, now: datetime) -> ReportExportView:
    status = item.status
    if status == "ready" and item.expires_at <= now:
        status = "expired"
    return ReportExportView(
        id=item.id,
        client_id=item.client_id,
        family=item.family,  # type: ignore[arg-type]
        parameters=dict(item.parameters),
        period=ExportPeriod(
            start=item.period_start,
            end=item.period_end,
            days=(item.period_end - item.period_start).days,
        ),
        includes_financials=item.includes_financials,
        source=item.source,  # type: ignore[arg-type]
        schedule_id=item.schedule_id,
        requested_by_membership_id=item.requested_by_membership_id,
        status=status,  # type: ignore[arg-type]
        revoked_reason=item.revoked_reason,  # type: ignore[arg-type]
        revoked_at=item.revoked_at,
        created_at=item.created_at,
        expires_at=item.expires_at,
        row_count=item.row_count,
        byte_size=item.byte_size,
        report_revision=item.report_revision,
        download_count=item.download_count,
        last_downloaded_at=item.last_downloaded_at,
    )


# --- routes -----------------------------------------------------------------------------------


@router.post(f"{BASE}/report-exports", status_code=201, response_model=ReportExportView)
def create_report_export(
    agency_id: UUID,
    client_id: UUID,
    data: ExportInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ReportExportView:
    state = request.app.state
    query = report_query(data, data.start, data.end)
    service = ExportService(session, browser.user.id)
    viewer = service.viewer(agency_id, client_id)
    access = resolve_scope(
        session, viewer.principal, agency_id, client_id, PERMISSIONS[query.family]
    )
    finance = viewer.finance if query.family in FINANCE_SPLIT else False
    export_id = create_export(
        state.engine,
        session,
        state.settings,
        state.connector_providers,
        ExportRequest(access, query, finance, viewer.member.id),
        audit_actor=browser.user.id,
    )
    item = session.get(ReportExport, export_id, populate_existing=True)
    assert item is not None
    return export_view(item, service.clock())


@router.get(f"{BASE}/report-exports", response_model=ReportExportList)
def list_report_exports(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    browser: BrowserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ReportExportList:
    service = ExportService(session, browser.user.id)
    items = service.list(agency_id, client_id, limit=limit, offset=offset)
    return ReportExportList(
        exports=[export_view(item, service.clock()) for item in items],
        limit=limit,
        offset=offset,
    )


@router.get(f"{BASE}/report-exports/{{export_id}}", response_model=ReportExportView)
def read_report_export(
    agency_id: UUID, client_id: UUID, export_id: UUID, session: SessionDep, browser: BrowserDep
) -> ReportExportView:
    service = ExportService(session, browser.user.id)
    item = service.get(agency_id, client_id, export_id)
    return export_view(item, service.clock())


@router.get(f"{BASE}/report-exports/{{export_id}}/download", responses=CSV_DOWNLOAD)
def download_report_export(
    agency_id: UUID,
    client_id: UUID,
    export_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> Response:
    item, data = ExportService(session, browser.user.id).download(
        request.app.state.settings, agency_id, client_id, export_id
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{FILENAMES[item.family]}"'},
    )


@router.delete(f"{BASE}/report-exports/{{export_id}}", response_model=ReportExportView)
def revoke_report_export(
    agency_id: UUID, client_id: UUID, export_id: UUID, session: SessionDep, browser: BrowserDep
) -> ReportExportView:
    service = ExportService(session, browser.user.id)
    item = service.revoke(agency_id, client_id, export_id)
    return export_view(item, service.clock())


# --- schedules (D8, D9) -------------------------------------------------------------------------

ScheduleName = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=100, strip_whitespace=True, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]
Weekday = Annotated[int, Field(ge=1, le=7)]
Hour = Annotated[int, Field(ge=0, le=23)]
TimeZone = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Recipients = Annotated[list[UUID], Field(max_length=20)]


class ScheduleInput(Input):
    name: ScheduleName
    report: ReportParameters
    sale_values: bool = False
    cadence: Literal["daily", "weekly", "monthly"]
    weekday: Weekday | None = None
    hour: Hour
    time_zone: TimeZone
    recipients: Recipients = []


class ScheduleChangeInput(Input):
    name: ScheduleName | None = None
    report: ReportParameters | None = None
    sale_values: bool | None = None
    cadence: Literal["daily", "weekly", "monthly"] | None = None
    weekday: Weekday | None = None
    hour: Hour | None = None
    time_zone: TimeZone | None = None
    recipients: Recipients | None = None
    status: Literal["active", "paused"] | None = None


class ScheduleRun(Output):
    at: datetime | None
    outcome: Literal["built", "failed"] | None
    error_code: str | None
    notified: int
    skipped: int


class ReportScheduleView(Output):
    id: UUID
    client_id: UUID
    name: str
    report: dict[str, Any]
    sale_values: bool
    cadence: Literal["daily", "weekly", "monthly"]
    weekday: int | None
    hour: int
    time_zone: str
    status: Literal["active", "paused"]
    pause_reason: Literal["manual", "owner_access_lost", "repeated_failures"] | None
    owner_membership_id: UUID
    next_run_at: datetime | None
    last_run: ScheduleRun
    consecutive_failures: int
    receiving: bool
    recipients: list[UUID] | None
    created_at: datetime
    updated_at: datetime


class ReportScheduleList(Output):
    schedules: list[ReportScheduleView]
    limit: int
    offset: int


def schedule_view(
    service: ScheduleService, member: AgencyMembership, schedule: ReportSchedule
) -> ReportScheduleView:
    recipients = service.recipients(schedule)
    return ReportScheduleView(
        id=schedule.id,
        client_id=schedule.client_id,
        name=schedule.name,
        report={"family": schedule.family, **schedule.parameters},
        sale_values=schedule.sale_values,
        cadence=schedule.cadence,  # type: ignore[arg-type]
        weekday=schedule.weekday,
        hour=schedule.hour,
        time_zone=schedule.time_zone,
        status=schedule.status,  # type: ignore[arg-type]
        pause_reason=schedule.pause_reason,  # type: ignore[arg-type]
        owner_membership_id=schedule.owner_membership_id,
        next_run_at=schedule.next_run_at,
        last_run=ScheduleRun(
            at=schedule.last_run_at,
            outcome=schedule.last_outcome,  # type: ignore[arg-type]
            error_code=schedule.last_error_code,
            notified=schedule.last_notified,
            skipped=schedule.last_skipped,
        ),
        consecutive_failures=schedule.consecutive_failures,
        receiving=member.id in recipients,
        recipients=recipients if member.role in MANAGERS else None,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _schedules(request: Request, session: SessionDep, browser: BrowserDep) -> ScheduleService:
    return ScheduleService(session, browser.user.id, request.app.state.settings)


@router.post(f"{BASE}/report-schedules", status_code=201, response_model=ReportScheduleView)
def create_report_schedule(
    agency_id: UUID,
    client_id: UUID,
    data: ScheduleInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ReportScheduleView:
    service = _schedules(request, session, browser)
    spec = schedule_spec(
        data.name,
        report_query(data.report, *PLACEHOLDER),
        data.sale_values,
        data.cadence,
        data.weekday,
        data.hour,
        data.time_zone,
        data.recipients,
    )
    schedule = service.create(agency_id, client_id, spec)
    member, schedule = service.get(agency_id, client_id, schedule.id)
    return schedule_view(service, member, schedule)


@router.get(f"{BASE}/report-schedules", response_model=ReportScheduleList)
def list_report_schedules(
    agency_id: UUID,
    client_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ReportScheduleList:
    service = _schedules(request, session, browser)
    member, items = service.listing(agency_id, client_id, limit=limit, offset=offset)
    return ReportScheduleList(
        schedules=[schedule_view(service, member, item) for item in items],
        limit=limit,
        offset=offset,
    )


@router.get(f"{BASE}/report-schedules/{{schedule_id}}", response_model=ReportScheduleView)
def read_report_schedule(
    agency_id: UUID,
    client_id: UUID,
    schedule_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ReportScheduleView:
    service = _schedules(request, session, browser)
    member, schedule = service.get(agency_id, client_id, schedule_id)
    return schedule_view(service, member, schedule)


@router.patch(f"{BASE}/report-schedules/{{schedule_id}}", response_model=ReportScheduleView)
def change_report_schedule(
    agency_id: UUID,
    client_id: UUID,
    schedule_id: UUID,
    data: ScheduleChangeInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ReportScheduleView:
    service = _schedules(request, session, browser)
    changes: dict[str, Any] = {
        key: getattr(data, key)
        for key in data.model_fields_set
        if key != "report" and getattr(data, key) is not None
    }
    if "weekday" in data.model_fields_set:
        changes["weekday"] = data.weekday
    if data.report is not None:
        changes["query"] = report_query(data.report, *PLACEHOLDER)
    service.update(agency_id, client_id, schedule_id, changes)
    member, schedule = service.get(agency_id, client_id, schedule_id)
    return schedule_view(service, member, schedule)


@router.delete(f"{BASE}/report-schedules/{{schedule_id}}", status_code=204)
def delete_report_schedule(
    agency_id: UUID,
    client_id: UUID,
    schedule_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> Response:
    _schedules(request, session, browser).delete(agency_id, client_id, schedule_id)
    return Response(status_code=204)


@router.delete(f"{BASE}/report-schedules/{{schedule_id}}/recipients/me", status_code=204)
def leave_report_schedule(
    agency_id: UUID,
    client_id: UUID,
    schedule_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> Response:
    _schedules(request, session, browser).leave(agency_id, client_id, schedule_id)
    return Response(status_code=204)
