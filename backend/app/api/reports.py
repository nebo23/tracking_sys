"""Report routes (specification 016-A, D-072 decisions D1, D2 and D7 to D10; 016-B, D-089).

Read-only report families of one client: social (readers with client:read) over one Instagram
or YouTube connection, advertising spend (finance:read) over one spend connection, recorded
revenue (finance:read) over the client's ledger, and, since 016-B, attribution (client:read;
sale values also need finance:read) over the client's stored credit, ROAS (finance:read) over
one spend connection and the stored credit, and the funnel (client:read; sale values also need
finance:read). Browser sessions and read service keys use the same permission rules; ingest
keys are refused. Each family accepts start and end dates (end exclusive, at most 31 days),
optional compare=previous, page and page_size, expected_revision and format=json or csv. An
unknown or repeated query parameter is refused; filters are never broadened. CSV exports the
complete bounded result without page parameters.

Every answer comes from one consistent snapshot of the inputs, a fresh authorization and source
check before release, and Cache-Control: no-store. Nothing is stored, cached or scheduled, and
no provider is called. The dependency block names the family that serves attribution, content
revenue, funnels and ROAS.
"""

from datetime import date as CalendarDate
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies import ReaderDep, SessionDep
from app.api.schemas import Output
from app.reporting.common import PageRequest, ReportError
from app.reporting.csv_export import FILENAMES, report_csv
from app.security import now_utc
from app.services.access import Principal, resolve_scope
from app.services.reporting import (
    FINANCE_SPLIT,
    PERMISSIONS,
    Report,
    ReportQuery,
    build_report,
    check_revision,
    page_rows,
    release_check,
)
from app.services.tenancy import AccessDenied

router = APIRouter(tags=["Reports"])
BASE = "/agencies/{agency_id}/clients/{client_id}/reports"
COMMON = {"start", "end", "compare", "page", "page_size", "expected_revision", "format"}
ALLOWED = {
    "social": COMMON | {"connection_id", "view", "metrics"},
    "spend": COMMON | {"connection_id", "level"},
    "revenue": COMMON,
    "attribution": COMMON | {"group_by", "view", "model_version"},
    "roas": COMMON | {"connection_id", "level", "model_version"},
    "funnel": COMMON | {"group_by", "model_version"},
}
Revision = Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")]
Page = Annotated[int, Query(ge=1, le=100_000)]
PageSize = Annotated[int, Query(ge=1, le=500)]
Compare = Annotated[Literal["previous"], Query()]
Format = Annotated[Literal["json", "csv"], Query()]
Metrics = Annotated[
    str, Query(min_length=1, max_length=1700, pattern=r"^[A-Za-z_]{1,64}(,[A-Za-z_]{1,64}){0,24}$")
]
CSV_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        "description": "The report as JSON, or as a CSV attachment with format=csv.",
    }
}


class Amount(Output):
    minor: int
    decimal: str


class PeriodView(Output):
    start: CalendarDate
    end: CalendarDate
    days: int


class PageView(Output):
    page: int
    page_size: int
    total_rows: int
    total_pages: int


class Dependency(Output):
    capability: str
    state: Literal["available", "dependency_unavailable"]
    family: str | None = None
    requires: list[str]


class SyncView(Output):
    state: str
    reason: str | None
    in_progress: bool


# --- social -----------------------------------------------------------------------------------


class SocialRow(Output):
    stream: str
    metric: str
    unit: str
    metric_class: str
    date: CalendarDate | None = None
    content_id: str | None = None
    product_type: str | None = None
    published_at: datetime | None = None
    published_date: CalendarDate | None = None
    value: int | float | None
    availability: Literal["available", "missing", "unsupported", "not_synced"]
    reason: str | None
    provisional: bool
    definition_since: CalendarDate | None
    observed_at: datetime | None = None
    fetched_at: datetime | None


class SocialTotal(Output):
    period: Literal["current", "previous"]
    stream: str
    metric: str
    unit: str
    metric_class: str
    value: int | None
    status: Literal["complete", "partial", "unavailable"]
    reason: str | None
    provisional: bool
    definition_since: CalendarDate | None
    expected_days: int | None = None
    available_days: int | None = None
    missing_days: int | None = None
    unsupported_days: int | None = None
    not_synced_days: int | None = None
    contents: int | None = None
    applicable_contents: int | None = None
    available_contents: int | None = None
    missing_contents: int | None = None
    unsupported_contents: int | None = None
    fetched_from: datetime | None = None
    fetched_through: datetime | None = None


class SocialComparison(Output):
    stream: str
    metric: str
    unit: str
    current_value: int | None
    previous_value: int | None
    current_status: str
    previous_status: str
    difference: int | None
    percent_change: str | None
    comparable: bool
    reason: str | None


class ReportStreamCoverage(Output):
    covered_from: datetime | None
    complete_through: datetime | None
    current: str | None = None
    previous: str | None = None


class StreamFreshness(Output):
    state: Literal["fresh", "stale", "never_synced"]
    freshness_hours: int
    last_stream_success_at: datetime | None
    fetched_from: datetime | None
    fetched_through: datetime | None


class StreamStatus(Output):
    stream: str
    coverage: ReportStreamCoverage
    sync: SyncView
    freshness: StreamFreshness
    provisional_delay_hours: int


class ExcludedMetric(Output):
    stream: str
    metric: str
    reason: str


class SocialSource(Output):
    provider: str
    family: str
    adapter_state: Literal["available", "unavailable"]
    adapter_version: str | None
    connection_status: str
    connection_last_successful_sync_at: datetime | None
    catalog_version: str
    excluded_metrics: list[ExcludedMetric]
    source_rows: int
    publication_unknown: int | None = None
    streams: list[StreamStatus]


class SocialReportResult(Output):
    contract_version: str
    family: Literal["social"]
    client_id: UUID
    connection_id: UUID
    view: Literal["daily", "content_cohort"]
    period: PeriodView
    comparison_period: PeriodView | None
    day_zone: str
    basis: str
    catalog_version: str
    generated_at: datetime
    revision: str
    totals: list[SocialTotal]
    comparison: list[SocialComparison] | None
    rows: list[SocialRow]
    page: PageView
    source_status: SocialSource
    dependencies: list[Dependency]


# --- spend ------------------------------------------------------------------------------------


class SpendReportRow(Output):
    object_id: str | None
    currency: str
    exponent: int
    spend: Amount
    impressions: int
    clicks: int
    days_with_spend: int
    provisional: bool


class SpendReportTotal(Output):
    period: Literal["current", "previous"]
    currency: str
    exponent: int
    spend: Amount
    impressions: int
    clicks: int
    days_with_spend: int
    provisional: bool
    status: Literal["complete", "partial"]
    reason: str | None


class SpendComparison(Output):
    currency: str
    exponent: int
    metric: Literal["spend", "impressions", "clicks"]
    current_value: Amount | int | None
    previous_value: Amount | int | None
    difference: Amount | int | None
    percent_change: str | None
    comparable: bool
    reason: str | None


class SpendReportRefusals(Output):
    unparseable_amount: int
    unsupported_currency: int


class SpendPeriodStatus(Output):
    period: Literal["current", "previous"]
    start: CalendarDate
    end: CalendarDate
    coverage: Literal["complete", "partial", "not_synced"]
    facts: int
    valued_facts: int
    refused: SpendReportRefusals
    provisional_dates: list[CalendarDate]
    fact_zones: list[str]
    status: Literal["complete", "partial", "unavailable"]
    reason: str | None


class SpendAccountView(Output):
    currency: str
    time_zone: str
    previous_currency: str | None
    currency_changed_at: datetime | None
    previous_time_zone: str | None
    time_zone_changed_at: datetime | None


class SpendFreshness(Output):
    state: Literal["fresh", "stale", "never_synced"]
    freshness_hours: int
    last_stream_success_at: datetime | None


class SpendStream(Output):
    stream: str
    covered_from: CalendarDate | None
    complete_through: CalendarDate | None
    sync: SyncView
    freshness: SpendFreshness


class SpendSource(Output):
    provider: str
    adapter_state: Literal["available", "unavailable"]
    adapter_version: str | None
    connection_status: str
    connection_last_successful_sync_at: datetime | None
    account: SpendAccountView | None
    stream: SpendStream
    periods: list[SpendPeriodStatus]
    source_rows: int


class SpendReportResult(Output):
    contract_version: str
    family: Literal["spend"]
    client_id: UUID
    connection_id: UUID
    level: Literal["ad", "adset", "campaign"]
    period: PeriodView
    comparison_period: PeriodView | None
    day_zone: str | None
    basis: str
    generated_at: datetime
    revision: str
    totals: list[SpendReportTotal]
    comparison: list[SpendComparison] | None
    rows: list[SpendReportRow]
    page: PageView
    source_status: SpendSource
    dependencies: list[Dependency]


# --- revenue ----------------------------------------------------------------------------------


class RevenueRow(Output):
    block: Literal["verified", "declared"]
    currency: str
    exponent: int
    date: CalendarDate
    kind: str
    amount: Amount
    postings: int


class RevenueTotal(Output):
    block: Literal["verified", "declared"]
    period: Literal["current", "previous"]
    currency: str
    exponent: int
    captured: Amount | None = None
    refunded: Amount | None = None
    charged_back: Amount | None = None
    reversed: Amount | None = None
    corrected: Amount | None = None
    net: Amount | None = None
    postings: int | None = None
    sales: Amount | None = None
    refunds: Amount | None = None
    items: int | None = None


class RevenueComparison(Output):
    block: Literal["verified", "declared"]
    currency: str
    exponent: int
    metric: str
    current_value: Amount
    previous_value: Amount
    difference: Amount | None
    percent_change: str | None
    comparable: bool
    reason: str | None


class Unresolved(Output):
    scope: Literal["all_evidence"]
    pending: int
    pending_reasons: dict[str, int]
    held: int
    reconciliation: int
    reconciliation_reasons: dict[str, int]
    evidence_rows: int
    evidence_limit: int
    external_completeness: Literal["unknown"]


class RevenueReportResult(Output):
    contract_version: str
    family: Literal["revenue"]
    client_id: UUID
    period: PeriodView
    comparison_period: PeriodView | None
    day_zone: Literal["UTC"]
    basis: str
    generated_at: datetime
    revision: str
    totals: list[RevenueTotal]
    comparison: list[RevenueComparison] | None
    unresolved: Unresolved
    rows: list[RevenueRow]
    page: PageView
    dependencies: list[Dependency]


# --- attribution (016-B) ----------------------------------------------------------------------


class ExactShare(Output):
    numerator: int
    denominator: int
    decimal: str


class ReportModelVersion(Output):
    id: UUID
    version_key: str
    model: Literal["first_click", "last_click", "linear"]
    window_days: int
    rules: str
    is_default: bool
    status: Literal["active", "retired"]
    created_at: datetime
    retired_at: datetime | None


class ConsumerMarks(Output):
    ledger_generation: int
    receipt_ordinal: int
    identity_seq: int


class CurrentMarks(Output):
    ledger: Literal["available", "unavailable", "none"]
    ledger_generation: int | None
    receipt_ordinal: int | None
    identity_seq: int


class AttributionFreshness(Output):
    state: Literal["caught_up", "behind", "rebuilding", "failed"]
    reason: str | None
    published_generation: int
    published_at: datetime | None
    failure_code: str | None
    unit: Literal["incremental", "rebuild"] | None
    consumer: ConsumerMarks
    current: CurrentMarks


class ValuesState(Output):
    state: Literal["available", "not_ready"]
    reason: str | None


class CreditSaleItem(Output):
    currency: str
    exponent: int
    credited_revenue: Amount
    credited_sales: ExactShare
    conversions: int


class CreditSales(Output):
    state: Literal["available", "permission_unavailable"]
    items: list[CreditSaleItem] | None


class CreditLeads(Output):
    credited_leads: ExactShare
    conversions: int


class SocialContentItem(Output):
    connection_id: UUID
    provider: str
    stream: str
    content_id: str


class CreditModelValues(Output):
    model_version_id: UUID
    sales: CreditSales
    leads: CreditLeads


class AttributionGroupRow(Output):
    recipient: Literal["campaign", "direct", "unknown"]
    group_ref: str | None
    registered: bool | None
    content_items: list[SocialContentItem] | None
    sales: CreditSales | None
    leads: CreditLeads | None
    models: list[CreditModelValues] | None


class CreditSaleTotal(Output):
    period: Literal["current", "previous"]
    currency: str
    exponent: int
    recipient: Literal["all", "campaign", "direct", "unknown"]
    credited_revenue: Amount
    credited_sales: ExactShare
    conversions: int


class CreditLeadTotal(Output):
    period: Literal["current", "previous"]
    recipient: Literal["all", "campaign", "direct", "unknown"]
    credited_leads: ExactShare
    conversions: int


class CreditSaleTotals(Output):
    state: Literal["available", "permission_unavailable", "not_ready"]
    reason: str | None
    items: list[CreditSaleTotal] | None


class CreditLeadTotals(Output):
    state: Literal["available", "not_ready"]
    reason: str | None
    items: list[CreditLeadTotal] | None


class CreditTotals(Output):
    sales: CreditSaleTotals
    leads: CreditLeadTotals


class CreditModelTotals(CreditTotals):
    model_version_id: UUID


class ReconciliationItem(Output):
    period: Literal["current", "previous"]
    currency: str
    exponent: int
    credited_revenue: Amount
    ledger_net: Amount
    difference: Amount
    state: Literal["reconciled", "difference"]
    reason: str | None


class CreditReconciliation(Output):
    state: Literal["available", "permission_unavailable", "not_ready", "unavailable"]
    reason: str | None
    ledger: Literal["available", "unavailable", "none"] | None
    items: list[ReconciliationItem] | None


class CreditModelReconciliation(CreditReconciliation):
    model_version_id: UUID


class CreditComparison(Output):
    metric: str
    kind: Literal["sale", "lead"]
    currency: str | None
    exponent: int | None
    current_value: Amount | ExactShare | int | None
    previous_value: Amount | ExactShare | int | None
    difference: Amount | ExactShare | int | None
    percent_change: str | None
    comparable: bool
    reason: str | None


class AttributionReportResult(Output):
    contract_version: str
    family: Literal["attribution"]
    client_id: UUID
    view: Literal["groups", "models"]
    group_by: Literal["campaign", "content", "link", "recipient"]
    period: PeriodView
    comparison_period: PeriodView | None
    day_zone: Literal["UTC"]
    basis: Literal["conversion_date"]
    generated_at: datetime
    revision: str
    model_version: ReportModelVersion | None
    model_versions: list[ReportModelVersion] | None
    attribution: AttributionFreshness
    finance: Literal["available", "permission_unavailable"]
    values: ValuesState
    totals: CreditTotals | None
    model_totals: list[CreditModelTotals] | None
    reconciliation: CreditReconciliation | None
    model_reconciliation: list[CreditModelReconciliation] | None
    comparison: list[CreditComparison] | None
    rows: list[AttributionGroupRow]
    page: PageView
    dependencies: list[Dependency]


MODELS = {
    "social": SocialReportResult,
    "spend": SpendReportResult,
    "revenue": RevenueReportResult,
    "attribution": AttributionReportResult,
}


# Refuse unknown or repeated query parameters, and page parameters with format=csv.
def _strict(request: Request, family: str, output: str) -> None:
    keys = [key for key, _ in request.query_params.multi_items()]
    if len(keys) != len(set(keys)) or set(keys) - ALLOWED[family]:
        raise ReportError("unknown_parameter", 422)
    if output == "csv" and {"page", "page_size"} & set(keys):
        raise ReportError("csv_pagination_unsupported", 422)


def _serve(
    request: Request,
    session: SessionDep,
    principal: Principal,
    agency_id: UUID,
    client_id: UUID,
    query: ReportQuery,
    output: str,
    page: int,
    page_size: int,
    expected: str | None,
) -> Any:
    state = request.app.state
    access = resolve_scope(session, principal, agency_id, client_id, PERMISSIONS[query.family])
    finance = False
    if query.family in FINANCE_SPLIT:
        # Lead credit and visits need client:read only; sale values need finance:read too.
        try:
            resolve_scope(session, principal, agency_id, client_id, "finance:read")
            finance = True
        except AccessDenied:
            finance = False
    request_page = None if output == "csv" else PageRequest(page, page_size)
    now = now_utc()
    report: Report = build_report(
        state.engine, state.connector_providers, access, query, now, finance=finance
    )
    check_revision(report, expected, request_page)
    if request_page is None:
        data = report_csv(report.body, report.rows(), report.total_rows)
        release_check(
            state.engine, state.connector_providers, principal, access, query, report, now
        )
        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{FILENAMES[query.family]}"'},
        )
    rows, info = page_rows(report, request_page)
    body = MODELS[query.family].model_validate({**report.body, "rows": rows, "page": info})
    release_check(state.engine, state.connector_providers, principal, access, query, report, now)
    return body


# Social report of one Instagram or YouTube connection: daily values on the provider's own days,
# or the lifetime values of content published on the requested dates (view=content_cohort).
@router.get(f"{BASE}/social", response_model=SocialReportResult, responses=CSV_RESPONSE)
def social_report(
    agency_id: UUID,
    client_id: UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
    connection_id: Annotated[UUID, Query()],
    view: Annotated[Literal["daily", "content_cohort"], Query()],
    start: Annotated[CalendarDate, Query()],
    end: Annotated[CalendarDate, Query()],
    compare: Compare | None = None,
    metrics: Metrics | None = None,
    page: Page = 1,
    page_size: PageSize = 100,
    expected_revision: Revision | None = None,
    format: Format = "json",
) -> Any:
    _strict(request, "social", format)
    query = ReportQuery(
        "social",
        start,
        end,
        compare is not None,
        connection_id=connection_id,
        view=view,
        metrics=None if metrics is None else tuple(metrics.split(",")),
    )
    query.periods()
    return _serve(
        request,
        session,
        principal,
        agency_id,
        client_id,
        query,
        format,
        page,
        page_size,
        expected_revision,
    )


# Spend report of one spend connection on the ad account's own days, by level object and
# currency.
@router.get(f"{BASE}/spend", response_model=SpendReportResult, responses=CSV_RESPONSE)
def spend_report(
    agency_id: UUID,
    client_id: UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
    connection_id: Annotated[UUID, Query()],
    start: Annotated[CalendarDate, Query()],
    end: Annotated[CalendarDate, Query()],
    level: Annotated[Literal["ad", "adset", "campaign"], Query()] = "ad",
    compare: Compare | None = None,
    page: Page = 1,
    page_size: PageSize = 100,
    expected_revision: Revision | None = None,
    format: Format = "json",
) -> Any:
    _strict(request, "spend", format)
    query = ReportQuery(
        "spend", start, end, compare is not None, connection_id=connection_id, level=level
    )
    query.periods()
    return _serve(
        request,
        session,
        principal,
        agency_id,
        client_id,
        query,
        format,
        page,
        page_size,
        expected_revision,
    )


# Recorded-revenue activity of the client's ledger by UTC posting date, verified and declared
# apart, per original currency.
@router.get(f"{BASE}/revenue", response_model=RevenueReportResult, responses=CSV_RESPONSE)
def revenue_report(
    agency_id: UUID,
    client_id: UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
    start: Annotated[CalendarDate, Query()],
    end: Annotated[CalendarDate, Query()],
    compare: Compare | None = None,
    page: Page = 1,
    page_size: PageSize = 100,
    expected_revision: Revision | None = None,
    format: Format = "json",
) -> Any:
    _strict(request, "revenue", format)
    query = ReportQuery("revenue", start, end, compare is not None)
    query.periods()
    return _serve(
        request,
        session,
        principal,
        agency_id,
        client_id,
        query,
        format,
        page,
        page_size,
        expected_revision,
    )


# Attribution of the client's stored credit (016-B, D-089 D3 to D6): credit by campaign,
# content, link or recipient class under one model version (view=groups), or the same groups
# under every active version side by side (view=models), on the UTC conversion date.
@router.get(f"{BASE}/attribution", response_model=AttributionReportResult, responses=CSV_RESPONSE)
def attribution_report(
    agency_id: UUID,
    client_id: UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
    start: Annotated[CalendarDate, Query()],
    end: Annotated[CalendarDate, Query()],
    group_by: Annotated[Literal["campaign", "content", "link", "recipient"], Query()] = "campaign",
    view: Annotated[Literal["groups", "models"], Query()] = "groups",
    model_version: Annotated[UUID | None, Query()] = None,
    compare: Compare | None = None,
    page: Page = 1,
    page_size: PageSize = 100,
    expected_revision: Revision | None = None,
    format: Format = "json",
) -> Any:
    _strict(request, "attribution", format)
    query = ReportQuery(
        "attribution",
        start,
        end,
        compare is not None,
        view=view,
        group_by=group_by,
        model_version=model_version,
    )
    query.periods()
    return _serve(
        request,
        session,
        principal,
        agency_id,
        client_id,
        query,
        format,
        page,
        page_size,
        expected_revision,
    )
