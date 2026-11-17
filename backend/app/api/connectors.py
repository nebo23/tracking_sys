"""Connector connection routes (specification 009, D-048, D-049).

Owner/Admin browser sessions start connect and reconnect authorizations, request a sync, and
request disconnection; readers with client:read inspect status. The provider redirects to the
single fixed callback, the only connector route that accepts protocol values (code, state,
error) in its query string. Responses and redirects never contain a token, authorization code,
or state; the completion URL receives at most a fixed result code and the connection ID.

010-A (D-053) adds stream-aware sync requests and reads, and the public provider routes for a
signed deauthorize or data deletion request and the deletion status page.
"""

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlencode
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import Field

from app.api.dependencies import BrowserDep, RawBody, ReaderDep, SessionDep
from app.api.schemas import AuthorizationURL, ErrorResponse, Input, Output
from app.config import Settings
from app.connectors.contracts import SignedRequest, WebhookRejected
from app.security import now_utc
from app.services.access import Principal, resolve_scope
from app.services.auth import enforce_rate_limit
from app.services.connector_callbacks import deletion_status, receive_signed_request
from app.services.connector_coverage import coverage, records
from app.services.connector_webhooks import receive_delivery
from app.services.connectors import (
    CALLBACK_ERRORS,
    TRANSACTION_SECONDS,
    ConnectorAdmin,
    ConnectorError,
    can_manage,
    complete_authorization,
    connection_view,
    get_connection,
    list_connections,
    provider_for,
    stream_names,
)

router = APIRouter(tags=["Connectors"])
callback_router = APIRouter(prefix="/connectors/oauth", tags=["Connectors"])
webhook_router = APIRouter(prefix="/connectors/webhooks", tags=["Connectors"])
provider_router = APIRouter(prefix="/connectors", tags=["Connectors"])
Stream = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")]


class ConnectInput(Input):
    provider: Literal["synthetic", "synthetic_instagram"]


class AccountReference(Output):
    external_account_id: str
    label: str | None


class DisconnectState(Output):
    requested_at: datetime
    completed_at: datetime | None
    revocation: Literal["pending", "done", "unsupported", "failed"]
    secret_destruction: Literal["pending", "done"]
    data_purge: Literal["pending", "done"]
    purge_due_at: datetime
    deadline_met: bool | None


class ConnectionActions(Output):
    reconnect: bool
    disconnect: bool


class ConnectionResponse(Output):
    id: UUID
    provider: str
    account: AccountReference | None
    status: Literal["active", "reconnect_required", "disconnecting", "disconnected"]
    status_reason: str | None
    granted_scopes: list[str]
    connected_at: datetime
    last_successful_sync_at: datetime | None
    actions: ConnectionActions
    disconnect: DisconnectState | None


# A sync request (009-B, D-049 decision D12): an incremental read, the default, or a backfill
# extending the stored history `days` further back, within the provider's history limit.
# 010-A: `stream` names one of the provider's streams; the first stream is the default.
class SyncInput(Input):
    kind: Literal["incremental", "backfill"] = "incremental"
    days: int | None = Field(default=None, ge=1, le=3650)
    stream: Stream | None = None


class SyncRequestResponse(Output):
    run_id: UUID
    kind: Literal["incremental", "backfill"]
    status: Literal["queued", "running"]
    stream: str


# Coverage and provenance (009-C, D-049 decisions D16 and D17). Every value is paired with an
# explicit state; the cost block covers only the connection's own allocation.
class ConnectionSource(Output):
    provider: str
    adapter_version: str
    account_kind: str | None


class SyncState(Output):
    state: Literal["idle", "queued", "running", "delayed", "budget_stopped", "failed"]
    kind: Literal["incremental", "backfill"] | None
    reason: str | None
    next_attempt_at: datetime | None


class StreamCoverage(Output):
    stream: str
    state: Literal["not_synced", "partial", "complete"]
    covered_from: datetime | None
    complete_through: datetime | None
    history_limit_days: int
    sync: SyncState


class MetricAvailability(Output):
    name: str
    unit: str
    stream: str
    product_types: list[str] | None
    availability: Literal["available", "unsupported", "missing", "stale", "not_synced"]
    latest_observed_at: datetime | None


class CostState(Output):
    unit: str
    period_start: datetime
    consumed: int
    allocation: int
    remaining: int
    state: Literal["available", "exhausted"]
    reason: Literal["connection_allocation", "provider_quota"] | None


class CoverageResponse(Output):
    connection_id: UUID
    source: ConnectionSource
    status: Literal["active", "reconnect_required", "disconnecting", "disconnected"]
    last_successful_sync_at: datetime | None
    freshness: Literal["fresh", "stale", "never_synced"]
    freshness_hours: int
    sync: SyncState
    streams: list[StreamCoverage]
    metrics: list[MetricAvailability]
    cost: CostState


# A missing value carries the provider's closed reason when it gave one (010-A, D7).
class MetricValue(Output):
    state: Literal["observed", "missing", "unsupported", "stale"]
    value: int | float | None
    reason: Literal["not_returned", "below_threshold"] | None


class RecordSource(Output):
    provider: str
    adapter_version: str | None
    run_id: UUID | None


class RecordItem(Output):
    provider_object_id: str
    stream: str
    product_type: Literal["FEED", "REELS", "STORY"] | None
    observed_at: datetime
    fetched_at: datetime
    provisional: bool
    source: RecordSource
    metrics: dict[str, MetricValue]


class RecordPage(Output):
    records: list[RecordItem]
    next_after: str | None


class DeliveryResult(Output):
    result: Literal["accepted", "duplicate"]


class SignedRequestResult(Output):
    result: Literal["accepted"]


# Meta's documented data deletion callback answer: the status URL and confirmation code.
class DeletionReceiptResponse(Output):
    url: str
    confirmation_code: str


class DeletionStatus(Output):
    confirmation_code: str
    status: Literal["pending", "completed"]
    received_at: datetime
    completed_at: datetime | None


def _admin(request: Request, session: SessionDep, browser: BrowserDep) -> ConnectorAdmin:
    return ConnectorAdmin(
        session,
        browser.user.id,
        request.app.state.settings,
        request.app.state.connector_providers,
    )


# The action flags depend on the caller: only Owner/Admin sessions are offered mutations.
def _response(row, manage: bool) -> ConnectionResponse:
    return ConnectionResponse.model_validate(connection_view(row, manage=manage))


# Bind the authorization to this browser with a short-lived HttpOnly cookie limited to the
# callback path. SameSite=Lax lets the top-level redirect back from the provider include it.
def _binding_cookie(response: Response, settings: Settings, binding: str) -> None:
    response.set_cookie(
        settings.connector_cookie_name,
        binding,
        max_age=TRANSACTION_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/connectors/oauth",
    )


# Decorator dependency: persistent per-peer limit for the unauthenticated callback.
def _callback_limit(request: Request) -> None:
    settings = request.app.state.settings
    enforce_rate_limit(
        request.app.state.security_engine,
        settings,
        "connector-ip",
        request.client.host if request.client else "unknown",
        limit=settings.auth_requests_per_minute,
        period=60,
    )


# Start connecting a provider account to the client (Owner/Admin). The response carries the
# provider authorization URL for the browser to open.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/connections", response_model=AuthorizationURL
)
def connect(
    agency_id: UUID,
    client_id: UUID,
    data: ConnectInput,
    request: Request,
    response: Response,
    session: SessionDep,
    browser: BrowserDep,
) -> AuthorizationURL:
    url, binding = _admin(request, session, browser).begin(
        agency_id, client_id, data.provider, browser.token
    )
    _binding_cookie(response, request.app.state.settings, binding)
    return AuthorizationURL(authorization_url=url)


# Start reauthorizing a connection that requires reconnection (Owner/Admin).
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/reconnect",
    response_model=AuthorizationURL,
)
def reconnect(
    agency_id: UUID,
    client_id: UUID,
    connection_id: UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    browser: BrowserDep,
) -> AuthorizationURL:
    url, binding = _admin(request, session, browser).begin(
        agency_id, client_id, "", browser.token, connection_id
    )
    _binding_cookie(response, request.app.state.settings, binding)
    return AuthorizationURL(authorization_url=url)


@router.get(
    "/agencies/{agency_id}/clients/{client_id}/connections",
    response_model=list[ConnectionResponse],
)
def list_client_connections(
    agency_id: UUID, client_id: UUID, session: SessionDep, principal: ReaderDep
) -> list[ConnectionResponse]:
    access = resolve_scope(session, principal, agency_id, client_id)
    manage = can_manage(session, principal, agency_id)
    return [_response(row, manage) for row in list_connections(session, access)]


@router.get(
    "/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}",
    response_model=ConnectionResponse,
)
def read_connection(
    agency_id: UUID,
    client_id: UUID,
    connection_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
) -> ConnectionResponse:
    access = resolve_scope(session, principal, agency_id, client_id)
    manage = can_manage(session, principal, agency_id)
    return _response(get_connection(session, access, connection_id), manage)


# Coverage of one connection for readers with client:read (009-C).
@router.get(
    "/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/coverage",
    response_model=CoverageResponse,
)
def read_coverage(
    agency_id: UUID,
    client_id: UUID,
    connection_id: UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
) -> CoverageResponse:
    access = resolve_scope(session, principal, agency_id, client_id)
    state = request.app.state
    return CoverageResponse.model_validate(
        coverage(
            session, state.settings, state.connector_providers, access, connection_id, now_utc()
        )
    )


# Stored records of one connection with provenance and per-metric states, at most `limit` per
# page ordered by provider object ID; `after` continues from the previous page's next_after.
@router.get(
    "/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/records",
    response_model=RecordPage,
)
def read_records(
    agency_id: UUID,
    client_id: UUID,
    connection_id: UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
    after: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    stream: Annotated[str | None, Query(min_length=1, max_length=32, pattern=r"^[a-z_]+$")] = None,
) -> RecordPage:
    access = resolve_scope(session, principal, agency_id, client_id)
    items, following = records(
        session,
        request.app.state.connector_providers,
        access,
        connection_id,
        now_utc(),
        after=after,
        limit=limit,
        stream=stream,
    )
    return RecordPage.model_validate({"records": items, "next_after": following})


# Queue a synchronization of an active connection (Owner/Admin). An open run of the same kind
# is returned; an open run of the other kind answers 409 sync_in_progress.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/sync",
    status_code=202,
    response_model=SyncRequestResponse,
)
def request_sync(
    agency_id: UUID,
    client_id: UUID,
    connection_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
    data: Annotated[SyncInput | None, Body()] = None,
) -> SyncRequestResponse:
    data = data or SyncInput()
    run = _admin(request, session, browser).request_sync(
        agency_id, client_id, connection_id, data.kind, data.days, data.stream
    )
    return SyncRequestResponse(
        run_id=run.id,
        kind=run.kind,  # type: ignore[arg-type]
        status=run.status,  # type: ignore[arg-type]
        stream=run.stream,
    )


# Request disconnection (Owner/Admin); the worker revokes, destroys, and purges. Repeated
# requests return the current state without changing the deadline.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/disconnect",
    status_code=202,
    response_model=ConnectionResponse,
)
def disconnect(
    agency_id: UUID,
    client_id: UUID,
    connection_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ConnectionResponse:
    row = _admin(request, session, browser).disconnect(agency_id, client_id, connection_id)
    session.flush()
    return _response(row, can_manage(session, Principal("user", browser.user.id), agency_id))


# The provider redirects here. The single-use state, the session-bound binding cookie, and
# PKCE protect the callback; it requires no Origin header. The browser is always redirected
# (303) to the completion URL with a fixed result code and, on success, the connection ID.
@callback_router.get(
    "/callback",
    status_code=303,
    response_class=RedirectResponse,
    dependencies=[Depends(_callback_limit)],
)
def callback(
    request: Request,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=128)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> RedirectResponse:
    settings = request.app.state.settings
    result: dict[str, str] = {}
    if error:
        result["error"] = "connection_cancelled"
    elif not code or not state:
        result["error"] = "connection_failed"
    else:
        try:
            outcome = complete_authorization(
                request.app.state.engine,
                settings,
                request.app.state.connector_providers,
                state,
                request.cookies.get(settings.connector_cookie_name),
                code,
                request.cookies.get(settings.cookie_name),
            )
        except ConnectorError as failure:
            known = failure.code in CALLBACK_ERRORS
            result["error"] = failure.code if known else "connection_failed"
        else:
            result["result"] = "connected" if outcome.purpose == "connect" else "reconnected"
            result["connection_id"] = str(outcome.connection_id)
    target = settings.connector_completion_url
    separator = "&" if "?" in target else "?"
    response = RedirectResponse(f"{target}{separator}{urlencode(result)}", status_code=303)
    response.delete_cookie(settings.connector_cookie_name, path="/connectors/oauth")
    return response


# Provider webhook (009-D, D-049 decisions D18 and D19). The adapter verifies its signature over
# the exact raw body before reading it (the synthetic adapter reuses the Spec 004 scheme in
# X-Synthetic-Signature); a refused delivery stores and queues nothing. The only effect of a
# verified delivery is a coalesced incremental sync for each active connection of the named
# account; the response is the same whether or not any connection matched. Bodies above 16 KiB
# are refused before routing (413 request_too_large).
@webhook_router.post(
    "/{provider}",
    response_model=DeliveryResult,
    responses={
        400: {"model": ErrorResponse, "description": "A verified body the adapter cannot read."},
        401: {"model": ErrorResponse, "description": "Missing, invalid, or expired signature."},
    },
)
def provider_webhook(
    provider: Annotated[str, Path(min_length=1, max_length=32)],
    request: Request,
    body: RawBody,
) -> DeliveryResult:
    state = request.app.state
    adapter = provider_for(state.connector_providers, provider)
    if not adapter.capability.webhooks:
        raise ConnectorError("provider_unavailable", 404)
    enforce_rate_limit(
        state.security_engine,
        state.settings,
        "connector-webhook",
        f"{provider}:{request.client.host if request.client else 'unknown'}",
        limit=state.settings.ingest_trusted_per_minute,
        period=60,
    )
    try:
        delivery = adapter.verify_webhook(request.headers, body, now_utc())
    except WebhookRejected as rejection:
        status = 400 if rejection.reason == "invalid_delivery" else 401
        raise ConnectorError(rejection.reason, status) from None
    return DeliveryResult(
        result=receive_delivery(state.engine, provider, delivery, now_utc(), stream_names(adapter))
    )


# Verify a provider's signed_request, sent as the form field `signed_request`, before reading
# it. The rate limit is per provider and peer at the trusted intake rate.
def _signed_request(request: Request, provider: str, body: bytes, kind: str) -> SignedRequest:
    state = request.app.state
    adapter = provider_for(state.connector_providers, provider)
    if not adapter.capability.signed_requests:
        raise ConnectorError("provider_unavailable", 404)
    enforce_rate_limit(
        state.security_engine,
        state.settings,
        f"connector-{kind}",
        f"{provider}:{request.client.host if request.client else 'unknown'}",
        limit=state.settings.ingest_trusted_per_minute,
        period=60,
    )
    try:
        fields = parse_qs(body.decode("ascii"), max_num_fields=4, strict_parsing=True)
    except (UnicodeDecodeError, ValueError):
        raise ConnectorError("invalid_delivery", 400) from None
    values = fields.get("signed_request", [])
    if len(values) != 1:
        raise ConnectorError("invalid_delivery", 400)
    try:
        return adapter.verify_signed_request(values[0], now_utc())
    except WebhookRejected as rejection:
        status = 400 if rejection.reason == "invalid_delivery" else 401
        raise ConnectorError(rejection.reason, status) from None


SIGNED_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorResponse, "description": "A verified request the adapter cannot read."},
    401: {"model": ErrorResponse, "description": "Missing, invalid, or expired signature."},
}


# Provider deauthorize callback (010-A, D-053 decision D5): every live connection of the named
# account starts disconnecting. The answer does not reveal whether any connection matched.
@provider_router.post(
    "/{provider}/deauthorize", response_model=SignedRequestResult, responses=SIGNED_RESPONSES
)
def provider_deauthorize(
    provider: Annotated[str, Path(min_length=1, max_length=32)],
    request: Request,
    body: RawBody,
) -> SignedRequestResult:
    signed = _signed_request(request, provider, body, "deauthorize")
    state = request.app.state
    receive_signed_request(state.engine, state.settings, provider, "deauthorize", signed, now_utc())
    return SignedRequestResult(result="accepted")


# Provider data deletion callback (010-A, D-053 decision D5): disconnects and purges every
# connection of the named account and answers with a status URL and confirmation code.
@provider_router.post(
    "/{provider}/data-deletion",
    response_model=DeletionReceiptResponse,
    responses=SIGNED_RESPONSES,
)
def provider_data_deletion(
    provider: Annotated[str, Path(min_length=1, max_length=32)],
    request: Request,
    body: RawBody,
) -> DeletionReceiptResponse:
    signed = _signed_request(request, provider, body, "deletion")
    state = request.app.state
    receipt = receive_signed_request(
        state.engine, state.settings, provider, "deletion", signed, now_utc()
    )
    assert receipt is not None
    return DeletionReceiptResponse(url=receipt.url, confirmation_code=receipt.confirmation_code)


# Public status of a data deletion request, identified only by its confirmation code.
@provider_router.get(
    "/{provider}/data-deletion/{code}",
    response_model=DeletionStatus,
    responses={404: {"model": ErrorResponse, "description": "Unknown confirmation code."}},
)
def provider_deletion_status(
    provider: Annotated[str, Path(min_length=1, max_length=32)],
    code: Annotated[str, Path(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")],
    request: Request,
) -> DeletionStatus:
    status = deletion_status(request.app.state.engine, provider, code)
    if status is None:
        raise ConnectorError("deletion_request_not_found", 404)
    return DeletionStatus.model_validate(status)
