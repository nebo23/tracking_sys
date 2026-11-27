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

A revoked or expired export answers export_gone (410). Refusals carry a closed code only.
"""

from datetime import date as CalendarDate
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field, StringConstraints

from app.api.dependencies import BrowserDep, SessionDep
from app.api.schemas import Input, Output
from app.models import ReportExport
from app.reporting.csv_export import FILENAMES
from app.services.access import resolve_scope
from app.services.report_exports import (
    FAMILY_KEYS,
    ExportRequest,
    ExportService,
    create_export,
)
from app.services.reporting import FINANCE_SPLIT, PERMISSIONS, ReportQuery

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
