"""Integration routes (specification 015, D-068 decisions E2 to E5, E7, E10 and E11).

Owner and Admin sessions manage a client's integration sources: a Cal.com source takes the secret
the client set in Cal.com, and a signed webhook source returns a platform-issued secret once.
Each change is audited. The public callback routes verify the provider's signature before
anything is stored and answer every verified delivery with 200; an invalid signature or an
unknown, malformed or disabled source key receives the same 401 and stores nothing. While a
source kind is off, its sources cannot be created and its callbacks answer 503. Readers with
client:read see a client's bookings, never a personal field.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field

from app.api.dependencies import BrowserDep, RawBody, ReaderDep, SessionDep
from app.api.schemas import ErrorResponse, Input, Output
from app.security import now_utc
from app.services.access import resolve_scope
from app.services.auth import enforce_rate_limit
from app.services.collection import require_token_keys
from app.services.integrations import (
    CrmRuleAdmin,
    IntegrationAdmin,
    IntegrationError,
    Unverifiable,
    body_digest,
    bookings_view,
    callback_path,
    deals_view,
    live_secrets,
    live_source,
    receive_booking,
    receive_deal,
    require_kind,
    verify_calcom,
    verify_signed,
)

router = APIRouter(tags=["Integrations"])
callback_router = APIRouter(prefix="/integrations", tags=["Integration callbacks"])
ClientSecret = Annotated[str, Field(min_length=16, max_length=256, pattern=r"^[!-~]+$")]
SOURCES = "/agencies/{agency_id}/clients/{client_id}/integration-sources"
CALLBACK_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Invalid signature or unknown source."},
    503: {"model": ErrorResponse, "description": "The integration kind is not enabled."},
}


class SourceInput(Input):
    kind: Literal["cal_com", "signed_webhook"]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    secret: ClientSecret | None = None


class SourceUpdate(Input):
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    status: Literal["active", "disabled"] | None = None


class SecretInput(Input):
    secret: ClientSecret | None = None


class SourceView(Output):
    id: UUID
    kind: str
    name: str
    status: str
    callback_path: str
    created_at: datetime
    updated_at: datetime


class IssuedSource(Output):
    source: SourceView
    signing_secret: str | None


class Received(Output):
    status: Literal["received"]


class BookingTotals(Output):
    requested: int
    scheduled: int
    cancelled: int
    rejected: int
    completed: int
    linked: int


class BookingView(Output):
    id: UUID
    provider: str
    status: str
    event_type_ref: str | None
    start_at: datetime | None
    end_at: datetime | None
    reschedule_count: int
    linked: bool
    updated_at: datetime


class BookingReport(Output):
    totals: BookingTotals
    bookings: list[BookingView]


def _admin(request: Request, session, browser) -> IntegrationAdmin:
    return IntegrationAdmin(session, browser.user.id, request.app.state.settings)


def _view(source) -> SourceView:
    return SourceView(
        id=source.id,
        kind=source.kind,
        name=source.name,
        status=source.status,
        callback_path=callback_path(source),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


# Create a Cal.com source with the client's Cal.com secret, or a signed webhook source whose
# issued secret is returned once.
@router.post(SOURCES, status_code=201, response_model=IssuedSource)
def create_integration_source(
    agency_id: UUID,
    client_id: UUID,
    data: SourceInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> IssuedSource:
    source, issued = _admin(request, session, browser).create(
        agency_id, client_id, kind=data.kind, name=data.name, secret=data.secret
    )
    session.refresh(source)
    return IssuedSource(source=_view(source), signing_secret=issued)


@router.get(SOURCES, response_model=list[SourceView])
def list_integration_sources(
    agency_id: UUID, client_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> list[SourceView]:
    return [_view(item) for item in _admin(request, session, browser).list(agency_id, client_id)]


# Replace the signing secret; the previous one stays accepted for 24 hours.
@router.put(SOURCES + "/{source_id}/secret", response_model=IssuedSource)
def replace_integration_secret(
    agency_id: UUID,
    client_id: UUID,
    source_id: UUID,
    data: SecretInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> IssuedSource:
    source, issued = _admin(request, session, browser).replace_secret(
        agency_id, client_id, source_id, data.secret
    )
    return IssuedSource(source=_view(source), signing_secret=issued)


@router.patch(SOURCES + "/{source_id}", response_model=SourceView)
def update_integration_source(
    agency_id: UUID,
    client_id: UUID,
    source_id: UUID,
    data: SourceUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> SourceView:
    if not data.model_fields_set:
        raise ValueError("An update field is required.")
    return _view(
        _admin(request, session, browser).update(
            agency_id, client_id, source_id, name=data.name, status=data.status
        )
    )


def _limit(request: Request, scope: str, subject: str) -> None:
    settings = request.app.state.settings
    enforce_rate_limit(
        request.app.state.security_engine,
        settings,
        scope,
        subject,
        limit=settings.ingest_trusted_per_minute,
        period=60,
    )


def _source(request: Request, session, kind: str, public_key: str):
    settings = request.app.state.settings
    now = now_utc()
    require_kind(settings, kind, now.date())
    peer = request.client.host if request.client else "unknown"
    _limit(request, "integration-peer", peer)
    _limit(request, "integration-key", public_key[:100])
    require_token_keys(settings)  # before the lookup, for known and unknown keys alike
    source = live_source(session, kind, public_key)
    if source is None:
        raise IntegrationError("invalid_signature", 401)
    return source, live_secrets(session, settings, source, now), now


# Cal.com booking webhooks (E2): x-cal-signature-256 over the body under the client's secret.
@callback_router.post(
    "/cal-com/{public_key}",
    response_model=Received,
    responses=CALLBACK_RESPONSES,
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {"schema": {}}}}
    },
)
def calcom_callback(
    public_key: str, request: Request, session: SessionDep, body: RawBody
) -> Received:
    source, secrets, _ = _source(request, session, "cal_com", public_key)
    try:
        payload = verify_calcom(body, request.headers.get("x-cal-signature-256"), secrets)
    except Unverifiable as error:
        raise IntegrationError("invalid_signature", 401) from error
    receive_booking(session, source, payload, body_digest(body))
    return Received(status="received")


# The provider-neutral signed webhook (E5): X-Tracking-Signature with the 004 scheme, carrying
# booking.* or deal.stage_changed events of the documented contract.
@callback_router.post(
    "/webhook/{public_key}",
    response_model=Received,
    responses=CALLBACK_RESPONSES,
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {"schema": {}}}},
        "parameters": [
            {
                "name": "X-Tracking-Signature",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
                "description": "t=<unix seconds>,v1=<hex HMAC-SHA256 of '<t>.<raw body>'>",
            }
        ],
    },
)
def signed_callback(
    public_key: str, request: Request, session: SessionDep, body: RawBody
) -> Received:
    source, secrets, now = _source(request, session, "signed_webhook", public_key)
    try:
        payload = verify_signed(body, request.headers.get("x-tracking-signature"), secrets, now)
    except Unverifiable as error:
        raise IntegrationError("invalid_signature", 401) from error
    if str(payload.get("type", "")).startswith("deal."):
        receive_deal(session, source, payload, body_digest(body))
    else:
        receive_booking(session, source, payload, body_digest(body))
    return Received(status="received")


# A client's bookings (E10): totals by status, the linked count and the newest bookings.
@router.get("/agencies/{agency_id}/clients/{client_id}/bookings", response_model=BookingReport)
def read_bookings(
    agency_id: UUID, client_id: UUID, session: SessionDep, principal: ReaderDep
) -> BookingReport:
    resolve_scope(session, principal, agency_id, client_id, "client:read")
    return BookingReport.model_validate(bookings_view(session, agency_id, client_id))


# --- CRM stage rules and deals (E6, E10) ----------------------------------------------------

Name = Annotated[str, Field(min_length=1, max_length=128)]
RULES = "/agencies/{agency_id}/clients/{client_id}/crm/stage-rules"


class RuleInput(Input):
    pipeline: Name
    stage: Name
    outcome: Literal["won", "lost"]


class RuleUpdate(Input):
    outcome: Literal["won", "lost"] | None = None
    status: Literal["active", "disabled"] | None = None


class RuleView(Output):
    id: UUID
    pipeline: str
    stage: str
    outcome: str
    status: str
    created_at: datetime
    updated_at: datetime


class DealTotals(Output):
    open: int
    won_verified: int
    won_unverified: int
    lost: int


class DealView(Output):
    id: UUID
    deal_ref: str
    pipeline: str
    stage: str
    previous_stage: str | None
    stage_at: datetime
    status: Literal["open", "won_verified", "won_unverified", "lost"]
    amount: str | None = None
    currency: str | None = None
    linked_sale: str | None = None


class DealReport(Output):
    # Totals cover every deal of the client; deals is one page (R008).
    totals: DealTotals
    deals: list[DealView]
    has_more: bool
    # The cursor of the next page; present only when has_more is true.
    next_after: str | None = None


def _rules(session, browser) -> CrmRuleAdmin:
    return CrmRuleAdmin(session, browser.user.id)


# Approve a won or lost stage for a pipeline (E6); audited.
@router.post(RULES, status_code=201, response_model=RuleView)
def create_stage_rule(
    agency_id: UUID, client_id: UUID, data: RuleInput, session: SessionDep, browser: BrowserDep
) -> RuleView:
    item = _rules(session, browser).create(
        agency_id, client_id, pipeline=data.pipeline, stage=data.stage, outcome=data.outcome
    )
    session.refresh(item)
    return RuleView.model_validate(item)


@router.get(RULES, response_model=list[RuleView])
def list_stage_rules(
    agency_id: UUID, client_id: UUID, session: SessionDep, browser: BrowserDep
) -> list[RuleView]:
    return [
        RuleView.model_validate(item)
        for item in _rules(session, browser).list(agency_id, client_id)
    ]


@router.patch(RULES + "/{rule_id}", response_model=RuleView)
def update_stage_rule(
    agency_id: UUID,
    client_id: UUID,
    rule_id: UUID,
    data: RuleUpdate,
    session: SessionDep,
    browser: BrowserDep,
) -> RuleView:
    if not data.model_fields_set:
        raise ValueError("An update field is required.")
    item = _rules(session, browser).update(
        agency_id, client_id, rule_id, outcome=data.outcome, status=data.status
    )
    session.flush()
    return RuleView.model_validate(item)


# A client's deals with their rule-based status; amounts and the linked sale need finance:read.
# The totals cover every deal; the rows are paged newest first received, by at most 500, and
# next_after continues after the last row (R008).
@router.get(
    "/agencies/{agency_id}/clients/{client_id}/crm/deals",
    response_model=DealReport,
    response_model_exclude_none=True,
)
def read_deals(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    include_amounts: Annotated[bool, Query()] = False,
    after: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> DealReport:
    permission = "finance:read" if include_amounts else "client:read"
    resolve_scope(session, principal, agency_id, client_id, permission)
    return DealReport.model_validate(
        deals_view(
            session,
            agency_id,
            client_id,
            include_amounts=include_amounts,
            after=after,
            limit=limit,
        )
    )
