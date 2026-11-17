"""Connector connection routes (specification 009, D-048, D-049).

Owner/Admin browser sessions start connect and reconnect authorizations, request a sync, and
request disconnection; readers with client:read inspect status. The provider redirects to the
single fixed callback, the only connector route that accepts protocol values (code, state,
error) in its query string. Responses and redirects never contain a token, authorization code,
or state; the completion URL receives at most a fixed result code and the connection ID.
"""

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import Field

from app.api.dependencies import BrowserDep, ReaderDep, SessionDep
from app.api.schemas import AuthorizationURL, Input, Output
from app.config import Settings
from app.services.access import Principal, resolve_scope
from app.services.auth import enforce_rate_limit
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
)

router = APIRouter(tags=["Connectors"])
callback_router = APIRouter(prefix="/connectors/oauth", tags=["Connectors"])


class ConnectInput(Input):
    provider: Literal["synthetic"]


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
class SyncInput(Input):
    kind: Literal["incremental", "backfill"] = "incremental"
    days: int | None = Field(default=None, ge=1, le=3650)


class SyncRequestResponse(Output):
    run_id: UUID
    kind: Literal["incremental", "backfill"]
    status: Literal["queued", "running"]


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
        agency_id, client_id, connection_id, data.kind, data.days
    )
    return SyncRequestResponse(run_id=run.id, kind=run.kind, status=run.status)  # type: ignore[arg-type]


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
