"""Attribution model, status and run routes (specification 008-B, D-079 decision D10).

Below /agencies/{agency_id}/clients/{client_id}/attribution:
- GET /models and GET /status need client:read and are open to read service keys with the
  client's grant.
- POST /models, /models/{version_id}/default and /models/{version_id}/retire are for an
  Owner or Admin with a browser session, idempotent by operation ID and audited.
- GET /conversions/{conversion_id}/runs needs identity:read and is never open to a service
  key. It is a person-level read: it is built in a REPEATABLE READ snapshot, it answers the
  retryable attribution_stale (503) while the stored result could be stale, and the reader's
  scope is resolved again immediately before the response. A sale's amounts and transaction
  references also need finance:read; without it they answer permission_unavailable.
- GET /conversions (016-B, D-089 D11) lists the stored conversions of a period with the latest
  revision under one model version. It is person-level like the runs route (identity:read,
  never a service key, attribution_stale unless caught up, no CSV) and lists sales only with
  finance:read.

Both person-level routes read the consumer state's change token inside their snapshot and
again after the answer is built, and answer attribution_stale when it moved, so an erasure or a
worker pass that commits meanwhile refuses the answer (O1 of the 008-B merge review). The status
route reads inside one snapshot (O2). The aggregated reports are below /reports. Refusals carry
a closed code only.
"""

from datetime import date as CalendarDate
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field

from app.api.dependencies import BrowserDep, ReaderDep, SessionDep
from app.api.schemas import Input, Output
from app.reporting.common import ReportError
from app.reporting.periods import Period
from app.services import attribution_reads
from app.services.access import resolve_scope
from app.services.attribution_models import AttributionError, ModelAdmin, ensure_defaults, listing
from app.services.reporting import report_snapshot
from app.services.tenancy import AccessDenied

router = APIRouter(tags=["Attribution"])
BASE = "/agencies/{agency_id}/clients/{client_id}/attribution"


class ModelVersionView(Output):
    id: UUID
    version_key: str
    model: Literal["first_click", "last_click", "linear"]
    window_days: int
    rules: str
    is_default: bool
    status: Literal["active", "retired"]
    created_at: datetime
    retired_at: datetime | None


class ModelVersionList(Output):
    versions: list[ModelVersionView]
    default_version_id: UUID | None
    active_limit: int


class ModelVersionInput(Input):
    operation_id: UUID
    model: Literal["first_click", "last_click", "linear"]
    # Validated by the service, so an out-of-range window answers the closed invalid_window.
    window_days: Annotated[int, Field(strict=True)]


class ModelOperationInput(Input):
    operation_id: UUID


class ConsumerView(Output):
    generation: int
    status: Literal["ready", "building", "failed"]
    failure_code: str | None
    unit: Literal["incremental", "rebuild"] | None
    ledger_generation: int
    receipt_ordinal: int
    identity_seq: int
    model_set_current: bool
    published_at: datetime | None


class WatermarkView(Output):
    ledger: Literal["available", "unavailable", "none"]
    ledger_generation: int | None
    receipt_ordinal: int | None
    identity_seq: int


class AttributionStatusView(Output):
    state: Literal["caught_up", "behind", "rebuilding"]
    consumer: ConsumerView
    current: WatermarkView


class ShareView(Output):
    numerator: int
    denominator: int


AmountState = Literal["available", "permission_unavailable", "not_applicable"]


class RunAllocationView(Output):
    ordinal: int
    credited: bool
    recipient: Literal["campaign", "direct", "unknown"]
    basis: str
    position: int
    share: ShareView
    amount_minor: int | None
    touchpoint_id: UUID | None
    evidence_class: str | None
    occurred_at: datetime | None
    source: str | None
    campaign_ref: str | None
    content_ref: str | None
    link_ref: UUID | None


class RunDifferenceView(Output):
    ordinal: int
    effective_at: datetime
    recipient: Literal["campaign", "direct", "unknown"]
    touchpoint_id: UUID | None
    source: str | None
    campaign_ref: str | None
    content_ref: str | None
    link_ref: UUID | None
    delta_share: ShareView
    delta_minor: int | None


class RunExcludedView(Output):
    touchpoint_id: UUID | None
    reason: str


class RunView(Output):
    revision: int
    status: Literal["complete", "no_verified_revenue", "net_out_of_range", "superseded"]
    basis: str | None
    causes: list[str]
    recorded_at: datetime
    window_start: datetime | None
    window_end: datetime | None
    amounts: AmountState
    currency: str | None
    currency_exponent: int | None
    verified_net_minor: int | None
    ledger_generation: int | None
    receipt_ordinal: int | None
    identity_seq: int
    touch_bound_exceeded: bool
    allocations: list[RunAllocationView]
    differences: list[RunDifferenceView]
    excluded: list[RunExcludedView]


class ConversionTransactionView(Output):
    state: AmountState
    source_account_id: str | None
    sale_operation_id: str | None


class ConversionView(Output):
    id: UUID
    kind: Literal["sale", "lead"]
    status: Literal["active", "superseded"]
    effective_at: datetime
    superseded_at: datetime | None
    superseded_reason: str | None
    scrubbed: bool
    person_id: UUID | None
    lead_event_id: UUID | None
    transaction: ConversionTransactionView


class ConversionRunsView(Output):
    generation: int
    conversion: ConversionView
    model_version: ModelVersionView
    runs: list[RunView]


class ListedRun(Output):
    revision: int
    status: Literal["complete", "no_verified_revenue", "net_out_of_range", "superseded"]
    basis: str | None
    causes: list[str]
    recorded_at: datetime
    window_end: datetime | None
    currency: str | None
    currency_exponent: int | None
    verified_net_minor: int | None
    touch_bound_exceeded: bool


class ListedTransaction(Output):
    source_account_id: str | None
    sale_operation_id: str | None


class ListedConversion(Output):
    id: UUID
    kind: Literal["sale", "lead"]
    status: Literal["active", "superseded"]
    effective_at: datetime
    superseded_at: datetime | None
    superseded_reason: str | None
    scrubbed: bool
    person_id: UUID | None
    lead_event_id: UUID | None
    transaction: ListedTransaction | None
    latest_run: ListedRun | None


class ConversionListView(Output):
    generation: int
    model_version: ModelVersionView
    sales: Literal["available", "permission_unavailable"]
    items: list[ListedConversion]
    next_cursor: str | None


LIST_PARAMETERS = {
    "start",
    "end",
    "kind",
    "status",
    "person_id",
    "model_version",
    "after",
    "limit",
}


def _finance(session, principal, agency_id: UUID, client_id: UUID) -> bool:
    try:
        resolve_scope(session, principal, agency_id, client_id, "finance:read")
    except AccessDenied:
        return False
    return True


# The change token of the snapshot must still hold after the answer was built (O1).
def _unchanged(session, client_id: UUID, token) -> None:
    if attribution_reads.change_token(session, client_id) != token:
        raise AttributionError(*attribution_reads.STALE)


@router.get(f"{BASE}/models", response_model=ModelVersionList)
def list_attribution_models(
    agency_id: UUID, client_id: UUID, session: SessionDep, principal: ReaderDep
) -> JSONResponse:
    resolve_scope(session, principal, agency_id, client_id)
    return JSONResponse(listing(session, agency_id, client_id))


@router.post(f"{BASE}/models", status_code=201, response_model=ModelVersionView)
def create_attribution_model(
    agency_id: UUID,
    client_id: UUID,
    data: ModelVersionInput,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = ModelAdmin(session, browser.user.id).create(
        agency_id, client_id, **data.model_dump()
    )
    return JSONResponse(result, status)


@router.post(
    f"{BASE}/models/{{version_id}}/default", status_code=201, response_model=ModelVersionView
)
def set_default_attribution_model(
    agency_id: UUID,
    client_id: UUID,
    version_id: UUID,
    data: ModelOperationInput,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = ModelAdmin(session, browser.user.id).set_default(
        agency_id, client_id, version_id, operation_id=data.operation_id
    )
    return JSONResponse(result, status)


@router.post(
    f"{BASE}/models/{{version_id}}/retire", status_code=201, response_model=ModelVersionView
)
def retire_attribution_model(
    agency_id: UUID,
    client_id: UUID,
    version_id: UUID,
    data: ModelOperationInput,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = ModelAdmin(session, browser.user.id).retire(
        agency_id, client_id, version_id, operation_id=data.operation_id
    )
    return JSONResponse(result, status)


@router.get(f"{BASE}/status", response_model=AttributionStatusView)
def read_attribution_status(
    agency_id: UUID, client_id: UUID, request: Request, session: SessionDep, principal: ReaderDep
) -> JSONResponse:
    resolve_scope(session, principal, agency_id, client_id)
    ensure_defaults(session, agency_id, client_id)
    # One snapshot, so the consumer state, the ledger position, the feed watermark and the
    # state-based slots come from the same moment (O2).
    with report_snapshot(request.app.state.engine) as snapshot:
        body = attribution_reads.status(snapshot, agency_id, client_id)
    return JSONResponse(body)


@router.get(f"{BASE}/conversions/{{conversion_id}}/runs", response_model=ConversionRunsView)
def read_attribution_runs(
    agency_id: UUID,
    client_id: UUID,
    conversion_id: UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
    model_version: UUID | None = None,
) -> JSONResponse:
    resolve_scope(session, principal, agency_id, client_id, "identity:read")
    finance = _finance(session, principal, agency_id, client_id)
    with report_snapshot(request.app.state.engine) as snapshot:
        token = attribution_reads.change_token(snapshot, client_id)
        body = attribution_reads.runs(
            snapshot, agency_id, client_id, conversion_id, model_version, finance=finance
        )
    _unchanged(session, client_id, token)
    # Recheck current scope immediately before releasing person-level data; a body built with
    # finance access carries amounts, so that access is rechecked too (R0607-14 pattern).
    resolve_scope(session, principal, agency_id, client_id, "identity:read")
    if finance:
        resolve_scope(session, principal, agency_id, client_id, "finance:read")
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get(f"{BASE}/conversions", response_model=ConversionListView)
def list_attribution_conversions(
    agency_id: UUID,
    client_id: UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
    start: Annotated[CalendarDate, Query()],
    end: Annotated[CalendarDate, Query()],
    kind: Annotated[Literal["sale", "lead"] | None, Query()] = None,
    status: Annotated[Literal["active", "superseded"] | None, Query()] = None,
    person_id: Annotated[UUID | None, Query()] = None,
    model_version: Annotated[UUID | None, Query()] = None,
    after: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> JSONResponse:
    keys = [key for key, _ in request.query_params.multi_items()]
    if len(keys) != len(set(keys)) or set(keys) - LIST_PARAMETERS:
        raise ReportError("unknown_parameter", 422)
    low, high = Period(start, end).bounds("UTC")
    resolve_scope(session, principal, agency_id, client_id, "identity:read")
    finance = _finance(session, principal, agency_id, client_id)
    with report_snapshot(request.app.state.engine) as snapshot:
        token = attribution_reads.change_token(snapshot, client_id)
        body = attribution_reads.conversions(
            snapshot,
            agency_id,
            client_id,
            start=low,
            end=high,
            kind=kind,
            status_filter=status,
            person_id=person_id,
            version_id=model_version,
            after=after,
            limit=limit,
            finance=finance,
        )
    _unchanged(session, client_id, token)
    # Person-level data is released only while the reader's scope still holds; sales were
    # listed with finance access, so that access is rechecked too.
    resolve_scope(session, principal, agency_id, client_id, "identity:read")
    if finance:
        resolve_scope(session, principal, agency_id, client_id, "finance:read")
    return JSONResponse(jsonable_encoder(body), headers={"Cache-Control": "no-store"})
