"""Payment routes (specification 015-B, D-067 decisions D3, D4, D10, D12 and D13).

Owner and Admin sessions create, list, rename, disable and re-activate a client's Paymob sources
and replace their merchant HMAC secret, each audited. The secret is accepted once and never
returned. The public callback route verifies Paymob's documented HMAC before anything is stored
and answers every verified callback with 200, so Paymob stops retrying; an invalid signature, an
unknown, disabled or malformed source key all receive the same 401 and store nothing. While the
Paymob source type is off or its provider rules are not current, sources cannot be created and
callbacks are answered 503. The browser response redirect (GET) is never accepted.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import Field

from app.api.dependencies import BrowserDep, RawBody, SessionDep
from app.api.schemas import ErrorResponse, Input, Output
from app.payments.paymob import Unverifiable, verify
from app.security import now_utc
from app.services.auth import enforce_rate_limit
from app.services.collection import require_token_keys
from app.services.payments import (
    PaymentError,
    PaymentSourceAdmin,
    callback_path,
    live_secrets,
    live_source,
    receive_callback,
    require_paymob,
)

router = APIRouter(tags=["Payments"])
callback_router = APIRouter(prefix="/payments", tags=["Payment callbacks"])
HmacSecret = Annotated[str, Field(min_length=16, max_length=256, pattern=r"^[!-~]+$")]


class PaymentSourceInput(Input):
    provider: Literal["paymob"]
    region: Literal["egypt"]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    hmac_secret: HmacSecret


class PaymentSourceUpdate(Input):
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    status: Literal["active", "disabled"] | None = None


class SecretInput(Input):
    hmac_secret: HmacSecret


class PaymentSourceResponse(Output):
    id: UUID
    provider: str
    region: str
    name: str
    status: str
    callback_path: str
    created_at: datetime
    updated_at: datetime


class CallbackReceived(Output):
    status: Literal["received"]


def _admin(request: Request, session, browser) -> PaymentSourceAdmin:
    return PaymentSourceAdmin(session, browser.user.id, request.app.state.settings)


def _view(source) -> PaymentSourceResponse:
    return PaymentSourceResponse(
        id=source.id,
        provider=source.provider,
        region=source.region,
        name=source.name,
        status=source.status,
        callback_path=callback_path(source),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


SOURCES = "/agencies/{agency_id}/clients/{client_id}/payment-sources"


# Create a Paymob source with the merchant's HMAC secret (entered once, sealed, never returned).
@router.post(SOURCES, status_code=201, response_model=PaymentSourceResponse)
def create_payment_source(
    agency_id: UUID,
    client_id: UUID,
    data: PaymentSourceInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> PaymentSourceResponse:
    source = _admin(request, session, browser).create(
        agency_id,
        client_id,
        provider=data.provider,
        region=data.region,
        name=data.name,
        hmac_secret=data.hmac_secret,
    )
    session.refresh(source)
    return _view(source)


@router.get(SOURCES, response_model=list[PaymentSourceResponse])
def list_payment_sources(
    agency_id: UUID, client_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> list[PaymentSourceResponse]:
    return [_view(item) for item in _admin(request, session, browser).list(agency_id, client_id)]


# Replace the merchant HMAC secret; the previous one stays accepted for 24 hours.
@router.put(SOURCES + "/{source_id}/secret", response_model=PaymentSourceResponse)
def replace_payment_secret(
    agency_id: UUID,
    client_id: UUID,
    source_id: UUID,
    data: SecretInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> PaymentSourceResponse:
    source = _admin(request, session, browser).replace_secret(
        agency_id, client_id, source_id, data.hmac_secret
    )
    return _view(source)


@router.patch(SOURCES + "/{source_id}", response_model=PaymentSourceResponse)
def update_payment_source(
    agency_id: UUID,
    client_id: UUID,
    source_id: UUID,
    data: PaymentSourceUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> PaymentSourceResponse:
    if not data.model_fields_set:
        raise ValueError("An update field is required.")
    source = _admin(request, session, browser).update(
        agency_id, client_id, source_id, name=data.name, status=data.status
    )
    return _view(source)


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


# Paymob's transaction processed callback (D4). The gate comes first, then the per-peer and
# per-key rates (applied to any key, known or not, so a 429 reveals nothing), then the source,
# the bounded JSON body and the documented HMAC. Only a verified callback is recorded.
@callback_router.post(
    "/paymob/callback/{public_key}",
    response_model=CallbackReceived,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid signature or unknown source."},
        503: {"model": ErrorResponse, "description": "Paymob sources are not enabled."},
    },
    openapi_extra={
        "parameters": [
            {
                "name": "hmac",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "HMAC-SHA512 of the documented transaction fields (hex).",
            }
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
    },
)
def paymob_callback(
    public_key: str, request: Request, session: SessionDep, body: RawBody
) -> CallbackReceived:
    settings = request.app.state.settings
    now = now_utc()
    require_paymob(settings, now.date())
    peer = request.client.host if request.client else "unknown"
    _limit(request, "paymob-peer", peer)
    _limit(request, "paymob-key", public_key[:100])
    # A missing keyring answers 503 before the source lookup, for known and unknown keys alike.
    require_token_keys(settings)
    source = live_source(session, public_key)
    if source is None:
        raise PaymentError("invalid_signature", 401)
    try:
        verified = verify(
            body, request.query_params.get("hmac"), live_secrets(session, settings, source, now)
        )
    except Unverifiable as error:
        raise PaymentError("invalid_signature", 401) from error
    receive_callback(session, source, verified)
    return CallbackReceived(status="received")
