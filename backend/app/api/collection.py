"""Event collection routes (specification 004, D-027): trusted, public, webhook, and admin.

Trusted routes authenticate an ingest key; public routes are limited-trust and routed by a
non-secret public key with an exact Origin allowlist, and their responses are readable only by
that registered origin (app.api.public_cors); webhook routes verify an HMAC over the raw body
before parsing. Every write runs the admission transaction in app.services.collection,
and the request's SessionDep commits counters with it, including for rejected input.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.collection_schemas import (
    ConsentInput,
    ConsentResponse,
    ConsentStateInput,
    ConsentStateResponse,
    DiagnosticResponse,
    ErasureInput,
    ErasureRequestInput,
    ErasureRequestResponse,
    EventMetadata,
    EventResult,
    FormResponse,
    IssuedSecret,
    IssuedSource,
    Received,
    SourceInput,
    SourceResponse,
    SourceUpdate,
)
from app.api.dependencies import BrowserDep, IngestDep, RawBody, ReaderDep, SessionDep
from app.api.public_cors import grant_origin
from app.api.schemas import ErrorResponse
from app.collection.contract import Envelope, FormDefinition, Rejected, verify_webhook
from app.privacy.consent import ConsentSource, ConsentState, Purpose
from app.privacy.deletion import RequesterKind
from app.security import AuthError, now_utc
from app.services.access import resolve_scope
from app.services.auth import enforce_rate_limit
from app.services.collection import (
    Admission,
    Channel,
    CollectionAdmin,
    CollectionError,
    admit,
    diagnostics,
    erase_subject,
    event_metadata,
    live_source,
    live_webhook_secrets,
    read_consent_state,
    record_consent,
    require_live_source,
    require_token_keys,
)

UNAVAILABLE = {404: {"model": ErrorResponse, "description": "Unknown or inactive source."}}
PUBLIC_MEDIA_TYPES = frozenset({"text/plain", "application/json"})
router = APIRouter(tags=["Event collection"])
public_router = APIRouter(
    prefix="/collect/v1",
    tags=["Public collection"],
    responses={
        **UNAVAILABLE,
        415: {"model": ErrorResponse, "description": "Body is not text/plain or JSON."},
    },
)
webhook_router = APIRouter(prefix="/webhooks/v1", tags=["Webhooks"], responses=UNAVAILABLE)
PublicKey = Annotated[str, Path(pattern=r"^pk_[A-Za-z0-9_-]{43}$")]
FormKey = Annotated[str, Path(pattern=r"^[a-z0-9_-]{1,100}$")]
ENVELOPE_BODY = {
    "required": True,
    "content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}},
        "text/plain": {"schema": {"type": "string", "description": "Envelope as JSON text."}},
    },
}
TRUSTED_RESPONSES = {
    200: {"model": EventResult, "description": "Duplicate or upgraded copy."},
    409: {"model": ErrorResponse, "description": "Conflicting copy of an accepted event."},
    422: {"model": ErrorResponse, "description": "Rejected or consent-suppressed event."},
}


# Map an admission outcome to the trusted response contract (design section 14).
def trusted_response(result: Admission) -> JSONResponse:
    if result.outcome == "accepted":
        return JSONResponse({"status": "accepted", "revision": result.revision}, 201)
    if result.outcome in {"duplicate", "upgraded"}:
        return JSONResponse({"status": result.outcome, "revision": result.revision}, 200)
    if result.outcome == "conflict":
        return JSONResponse({"error": "event_conflict"}, 409)
    return JSONResponse({"error": result.reason}, 422)


def consent_response(result) -> ConsentResponse:
    return ConsentResponse(
        subject_token=result.subject_token,
        receipts=result.receipts,
        states={purpose.value: state.value for purpose, state in result.states.items()},
        expires_at={purpose.value: moment for purpose, moment in result.expires_at.items()},
        server_time=result.server_time,
    )


def _choices(data: ConsentInput) -> dict[Purpose, ConsentState]:
    return {Purpose(purpose): ConsentState(state) for purpose, state in data.choices.items()}


def _limit(request: Request, scope: str, subject: str, limit: int) -> None:
    enforce_rate_limit(
        request.app.state.security_engine,
        request.app.state.settings,
        scope,
        subject,
        limit=limit,
        period=60,
    )


# Trusted server intake with an ingest key granted this client (rank 2).
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/events",
    status_code=201,
    response_model=EventResult,
    responses=TRUSTED_RESPONSES,
)
def ingest_event(
    agency_id: UUID,
    client_id: UUID,
    envelope: Envelope,
    request: Request,
    session: SessionDep,
    principal: IngestDep,
) -> JSONResponse:
    settings = request.app.state.settings
    _limit(request, "ingest-key", str(principal.identifier), settings.ingest_trusted_per_minute)
    resolve_scope(session, principal, agency_id, client_id, "events:write")
    result = admit(
        session,
        settings,
        agency_id,
        client_id,
        Channel("server", credential_id=principal.identifier),
        envelope,
        recheck=lambda: resolve_scope(session, principal, agency_id, client_id, "events:write"),
    )
    return trusted_response(result)


# Trusted API consent (source "api"); the sender attests the notice digest it showed.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/consent",
    response_model=ConsentResponse,
)
def ingest_consent(
    agency_id: UUID,
    client_id: UUID,
    data: ConsentInput,
    request: Request,
    session: SessionDep,
    principal: IngestDep,
) -> ConsentResponse:
    settings = request.app.state.settings
    _limit(request, "ingest-key", str(principal.identifier), settings.ingest_trusted_per_minute)
    if data.notice_sha256 is None:
        raise ValueError("Trusted consent needs the notice digest.")
    resolve_scope(session, principal, agency_id, client_id, "events:write")
    result = record_consent(
        session,
        agency_id,
        client_id,
        source=ConsentSource.API,
        notice_sha256=data.notice_sha256,
        choices=_choices(data),
        subject_token=data.subject_token,
        captured_at=data.captured_at,
        recheck=lambda: resolve_scope(session, principal, agency_id, client_id, "events:write"),
    )
    return consent_response(result)


# Resolve an active browser source, require an exact allowed Origin, and apply the per-source
# and per-peer rate limit. A public key and Origin route and limit abuse; they authorize nothing.
# Once the Origin is accepted, PublicCollectionCors lets that origin read the response, which
# carries the subject token on first consent (R004-01). Earlier failures stay unreadable. The
# grant precedes the rate limit, so an accepted origin can read a 429 and its Retry-After.
# Consent-state reads use their own bucket (specification 005).
def _browser_source(request: Request, session, public_key: str, *, bucket: str = "ingest-public"):
    source = live_source(session, "browser", public_key=public_key)
    if source is None:
        raise CollectionError("source_unavailable", 404)
    origin = request.headers.get("origin")
    if origin is None or origin not in (source.allowed_origins or []):
        raise AuthError("origin_not_allowed", 403)
    grant_origin(request.scope, origin)
    peer = request.client.host if request.client else "unknown"
    settings = request.app.state.settings
    limit = (
        settings.consent_state_per_minute
        if bucket == "consent-state"
        else settings.ingest_public_per_minute
    )
    _limit(request, bucket, f"{source.id}:{peer}", limit)
    return source


# Parse a public JSON body sent as text/plain (a CORS simple request without preflight) or as
# application/json (which browsers preflight; PublicCollectionCors answers for registered
# origins). Any other or missing media type is refused with 415.
def _public_body[T: BaseModel](request: Request, body: bytes, model: type[T]) -> T:
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media not in PUBLIC_MEDIA_TYPES:
        raise CollectionError("unsupported_media_type", 415)
    return model.model_validate_json(body)


# Public browser intake (rank 1). Accepted, duplicate, conflicting, suppressed, unknown-subject,
# and replayed submissions all receive the same 202, so responses reveal no stored state.
@public_router.post(
    "/{public_key}/events",
    status_code=202,
    response_model=Received,
    openapi_extra={"requestBody": ENVELOPE_BODY},
)
def collect_event(
    public_key: PublicKey, request: Request, session: SessionDep, body: RawBody
) -> Received:
    source = _browser_source(request, session, public_key)
    envelope = _public_body(request, body, Envelope)
    admit(
        session,
        request.app.state.settings,
        source.agency_id,
        source.client_id,
        Channel("browser", source_id=source.id),
        envelope,
        recheck=lambda: require_live_source(session, "browser", source.id),
        user_agent=request.headers.get("user-agent", ""),
    )
    return Received()


# Public consent from the source's banner; the notice digest is the source's registered one.
@public_router.post(
    "/{public_key}/consent",
    response_model=ConsentResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/ConsentInput"}},
                "text/plain": {"schema": {"type": "string"}},
            },
        }
    },
)
def collect_consent(
    public_key: PublicKey, request: Request, session: SessionDep, body: RawBody
) -> ConsentResponse:
    source = _browser_source(request, session, public_key)
    data = _public_body(request, body, ConsentInput)
    if data.notice_sha256 is not None:
        raise ValueError("The public route uses the source's registered notice.")
    result = record_consent(
        session,
        source.agency_id,
        source.client_id,
        source=ConsentSource.TRACKER_BANNER,
        notice_sha256=source.notice_sha256 or "",
        choices=_choices(data),
        subject_token=data.subject_token,
        captured_at=data.captured_at,
        recheck=lambda: require_live_source(session, "browser", source.id),
    )
    return consent_response(result)


# Current consent of a subject token holder (specification 005, D-033). It never issues a
# token, appends a record, renews an expiry, or refreshes subject activity, so a tracker can
# resume after a reload without recreating consent. Missing and erased subjects both answer
# with the fixed unknown state.
@public_router.post(
    "/{public_key}/consent-state",
    response_model=ConsentStateResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"subject_token": {"type": "string"}},
                        "required": ["subject_token"],
                        "additionalProperties": False,
                    }
                },
                "text/plain": {"schema": {"type": "string"}},
            },
        }
    },
)
def collect_consent_state(
    public_key: PublicKey, request: Request, session: SessionDep, body: RawBody
) -> ConsentStateResponse:
    source = _browser_source(request, session, public_key, bucket="consent-state")
    data = _public_body(request, body, ConsentStateInput)
    view = read_consent_state(
        session,
        source.client_id,
        subject_token=data.subject_token,
        recheck=lambda: require_live_source(session, "browser", source.id),
    )
    return ConsentStateResponse(
        status=view.status,
        states={purpose.value: state.value for purpose, state in view.states.items()},
        expires_at={purpose.value: moment for purpose, moment in view.expires_at.items()},
        server_time=view.server_time,
    )


# Self-erasure by the holder of a subject token; always the same 202.
@public_router.post(
    "/{public_key}/erasure",
    status_code=202,
    response_model=Received,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"subject_token": {"type": "string"}},
                        "required": ["subject_token"],
                        "additionalProperties": False,
                    }
                },
                "text/plain": {"schema": {"type": "string"}},
            },
        }
    },
)
def collect_erasure(
    public_key: PublicKey, request: Request, session: SessionDep, body: RawBody
) -> Received:
    source = _browser_source(request, session, public_key)
    data = _public_body(request, body, ErasureInput)
    erase_subject(
        session,
        request.app.state.settings,
        source.agency_id,
        source.client_id,
        requester=RequesterKind.DATA_SUBJECT,
        subject_token=data.subject_token,
    )
    return Received()


# Generic signed webhook (rank 2). The signature over the exact raw body is verified before
# the body is parsed; a source's current and overlapping previous secrets are accepted.
@webhook_router.post(
    "/{source_id}/events",
    status_code=201,
    response_model=EventResult,
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid, or expired signature."},
        **TRUSTED_RESPONSES,
    },
    openapi_extra={
        "requestBody": ENVELOPE_BODY,
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
def webhook_event(
    source_id: UUID, request: Request, session: SessionDep, body: RawBody
) -> JSONResponse:
    settings = request.app.state.settings
    source = live_source(session, "webhook", source_id=source_id)
    if source is None:
        raise CollectionError("source_unavailable", 404)
    _limit(request, "ingest-webhook", str(source.id), settings.ingest_trusted_per_minute)
    secrets = live_webhook_secrets(session, require_token_keys(settings), source, now_utc())
    try:
        verify_webhook(request.headers.get("x-tracking-signature"), body, secrets, now_utc())
    except Rejected as rejection:
        raise CollectionError(rejection.reason, 401) from rejection
    envelope = Envelope.model_validate_json(body)
    result = admit(
        session,
        settings,
        source.agency_id,
        source.client_id,
        Channel("webhook", source_id=source.id),
        envelope,
        recheck=lambda: require_live_source(session, "webhook", source.id),
    )
    return trusted_response(result)


def _admin(request: Request, session, browser) -> CollectionAdmin:
    return CollectionAdmin(session, browser.user.id, request.app.state.settings)


# Create a browser source (returns its public key) or a webhook source (returns its signing
# secret once). Owner/Admin; audited.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/ingestion-sources",
    status_code=201,
    response_model=IssuedSource,
)
def create_source(
    agency_id: UUID,
    client_id: UUID,
    data: SourceInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> IssuedSource:
    source, secret = _admin(request, session, browser).create_source(
        agency_id,
        client_id,
        kind=data.kind,
        name=data.name,
        allowed_origins=data.allowed_origins,
        notice_sha256=data.notice_sha256,
    )
    return IssuedSource(source=SourceResponse.model_validate(source), signing_secret=secret)


@router.get(
    "/agencies/{agency_id}/clients/{client_id}/ingestion-sources",
    response_model=list[SourceResponse],
)
def list_sources(
    agency_id: UUID, client_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> list[SourceResponse]:
    return [
        SourceResponse.model_validate(item)
        for item in _admin(request, session, browser).list_sources(agency_id, client_id)
    ]


@router.patch(
    "/agencies/{agency_id}/clients/{client_id}/ingestion-sources/{source_id}",
    response_model=SourceResponse,
)
def update_source(
    agency_id: UUID,
    client_id: UUID,
    source_id: UUID,
    data: SourceUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> SourceResponse:
    if not data.model_fields_set:
        raise ValueError("An update field is required.")
    return SourceResponse.model_validate(
        _admin(request, session, browser).update_source(
            agency_id,
            client_id,
            source_id,
            name=data.name,
            status=data.status,
            allowed_origins=data.allowed_origins,
            notice_sha256=data.notice_sha256,
        )
    )


# Rotate a webhook signing secret; the previous one stays valid for 24 hours.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/ingestion-sources/{source_id}/secret",
    status_code=201,
    response_model=IssuedSecret,
)
def rotate_secret(
    agency_id: UUID,
    client_id: UUID,
    source_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> IssuedSecret:
    return IssuedSecret(
        signing_secret=_admin(request, session, browser).rotate_secret(
            agency_id, client_id, source_id
        )
    )


@router.put(
    "/agencies/{agency_id}/clients/{client_id}/collection-forms/{form_key}",
    response_model=FormResponse,
)
def put_form(
    agency_id: UUID,
    client_id: UUID,
    form_key: FormKey,
    data: FormDefinition,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> FormResponse:
    return FormResponse.model_validate(
        _admin(request, session, browser).put_form(agency_id, client_id, form_key, data)
    )


@router.get(
    "/agencies/{agency_id}/clients/{client_id}/collection-forms",
    response_model=list[FormResponse],
)
def list_forms(
    agency_id: UUID, client_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> list[FormResponse]:
    return [
        FormResponse.model_validate(item)
        for item in _admin(request, session, browser).list_forms(agency_id, client_id)
    ]


# Erase a subject identified by token or by one of its event IDs (Owner/Admin); audited.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/deletion-requests",
    status_code=201,
    response_model=ErasureRequestResponse,
)
def request_erasure(
    agency_id: UUID,
    client_id: UUID,
    data: ErasureRequestInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ErasureRequestResponse:
    return ErasureRequestResponse.model_validate(
        _admin(request, session, browser).request_erasure(
            agency_id,
            client_id,
            subject_token=data.subject_token,
            event_id=data.event_id,
            objected=data.objected,
        )
    )


@router.get(
    "/agencies/{agency_id}/clients/{client_id}/deletion-requests",
    response_model=list[ErasureRequestResponse],
)
def list_erasure_requests(
    agency_id: UUID, client_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> list[ErasureRequestResponse]:
    return [
        ErasureRequestResponse.model_validate(item)
        for item in _admin(request, session, browser).list_requests(agency_id, client_id)
    ]


# Daily outcome counters (client:read) over at most 31 days.
@router.get(
    "/agencies/{agency_id}/clients/{client_id}/event-diagnostics",
    response_model=list[DiagnosticResponse],
)
def read_diagnostics(
    agency_id: UUID,
    client_id: UUID,
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
    session: SessionDep,
    principal: ReaderDep,
) -> list[DiagnosticResponse]:
    resolve_scope(session, principal, agency_id, client_id)
    return [
        DiagnosticResponse.model_validate(item)
        for item in diagnostics(session, agency_id, client_id, start, end)
    ]


# Metadata of one accepted event (client:read); no payload, subject, or fingerprint.
@router.get(
    "/agencies/{agency_id}/clients/{client_id}/events/{event_id}",
    response_model=EventMetadata,
)
def read_event(
    agency_id: UUID, client_id: UUID, event_id: UUID, session: SessionDep, principal: ReaderDep
) -> EventMetadata:
    resolve_scope(session, principal, agency_id, client_id)
    return EventMetadata.model_validate(event_metadata(session, agency_id, client_id, event_id))
