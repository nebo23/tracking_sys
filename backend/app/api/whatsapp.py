"""WhatsApp routes (specification 015-E, D-068 decisions E7, E8, E10 and E11).

The public webhook answers Meta's verification handshake only with the configured verify token,
and accepts notifications signed with the Meta app secret (X-Hub-Signature-256); an invalid
signature gets 401 and stores nothing, and every verified notification gets 200. Owner and Admin
sessions register a client's phone number IDs, each audited; a registration is a pending claim
that routes nothing until the platform operator verifies it with python -m app.whatsapp_binding
(D-070, review finding R004), and only a verified binding can be disabled or re-activated here.
Readers with client:read see the
client's message counts by referral, never a person field. While the setting is off or the rule
is not current, the webhook answers 503 and numbers cannot be registered.
"""

import hmac
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import Field

from app.api.dependencies import BrowserDep, RawBody, ReaderDep, SessionDep
from app.api.schemas import ErrorResponse, Input, Output
from app.integrations.whatsapp import Unverifiable, messages, verify
from app.security import now_utc
from app.services.access import resolve_scope
from app.services.auth import enforce_rate_limit
from app.services.whatsapp import (
    WhatsappError,
    WhatsappNumberAdmin,
    receive_messages,
    referrals_view,
    require_whatsapp,
)

router = APIRouter(tags=["WhatsApp"])
webhook_router = APIRouter(prefix="/integrations/whatsapp", tags=["Integration callbacks"])
NUMBERS = "/agencies/{agency_id}/clients/{client_id}/whatsapp-numbers"
PhoneNumberId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,31}$")]


class NumberInput(Input):
    phone_number_id: PhoneNumberId
    name: Annotated[str, Field(min_length=1, max_length=200)]


class NumberUpdate(Input):
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    status: Literal["active", "disabled"] | None = None


class NumberView(Output):
    id: UUID
    phone_number_id: str
    name: str
    status: Literal["pending", "active", "disabled", "revoked"]
    created_at: datetime
    updated_at: datetime
    verified_at: datetime | None


class Received(Output):
    status: Literal["received"]


class ReferralSource(Output):
    source_type: str
    source_id: str | None
    messages: int
    with_click_id: int


class ReferralReport(Output):
    since: date
    until: date
    total: int
    unknown: int
    sources: list[ReferralSource]


def _admin(request: Request, session, browser) -> WhatsappNumberAdmin:
    return WhatsappNumberAdmin(session, browser.user.id, request.app.state.settings)


@router.post(NUMBERS, status_code=201, response_model=NumberView)
def create_whatsapp_number(
    agency_id: UUID,
    client_id: UUID,
    data: NumberInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> NumberView:
    item = _admin(request, session, browser).create(
        agency_id, client_id, phone_number_id=data.phone_number_id, name=data.name
    )
    session.refresh(item)
    return NumberView.model_validate(item)


@router.get(NUMBERS, response_model=list[NumberView])
def list_whatsapp_numbers(
    agency_id: UUID, client_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> list[NumberView]:
    return [
        NumberView.model_validate(item)
        for item in _admin(request, session, browser).list(agency_id, client_id)
    ]


@router.patch(NUMBERS + "/{number_id}", response_model=NumberView)
def update_whatsapp_number(
    agency_id: UUID,
    client_id: UUID,
    number_id: UUID,
    data: NumberUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> NumberView:
    if not data.model_fields_set:
        raise ValueError("An update field is required.")
    item = _admin(request, session, browser).update(
        agency_id, client_id, number_id, name=data.name, status=data.status
    )
    session.flush()
    return NumberView.model_validate(item)


# Meta's verification handshake (W-6): the challenge is returned only with the verify token.
@webhook_router.get(
    "/webhook", response_class=PlainTextResponse, responses={403: {"model": ErrorResponse}}
)
def whatsapp_verification(
    request: Request,
    mode: Annotated[str | None, Query(alias="hub.mode", max_length=32)] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token", max_length=256)] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge", max_length=256)] = None,
) -> PlainTextResponse:
    settings = request.app.state.settings
    require_whatsapp(settings, now_utc().date())
    expected = settings.whatsapp_verify_token.get_secret_value()
    if (
        mode != "subscribe"
        or token is None
        or challenge is None
        or not expected
        or not hmac.compare_digest(token.encode(), expected.encode())
    ):
        raise WhatsappError("verification_failed", 403)
    return PlainTextResponse(challenge)


# Signed notifications (W-6, W-7): every verified notification answers 200, so Meta stops
# retrying; only the referral of each inbound message of a registered number is kept.
@webhook_router.post(
    "/webhook",
    response_model=Received,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid signature."},
        503: {"model": ErrorResponse, "description": "WhatsApp intake is not enabled."},
    },
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {"schema": {}}}}
    },
)
def whatsapp_notification(request: Request, session: SessionDep, body: RawBody) -> Received:
    settings = request.app.state.settings
    require_whatsapp(settings, now_utc().date())
    peer = request.client.host if request.client else "unknown"
    enforce_rate_limit(
        request.app.state.security_engine,
        settings,
        "whatsapp-peer",
        peer,
        limit=settings.ingest_trusted_per_minute,
        period=60,
    )
    try:
        payload = verify(
            body,
            request.headers.get("x-hub-signature-256"),
            settings.whatsapp_app_secret.get_secret_value(),
        )
    except Unverifiable as error:
        raise WhatsappError("invalid_signature", 401) from error
    receive_messages(session, list(messages(payload)))
    return Received(status="received")


# A client's messages by referral over UTC days since..until (exclusive, at most 92 days).
@router.get(
    "/agencies/{agency_id}/clients/{client_id}/whatsapp/referrals", response_model=ReferralReport
)
def read_referrals(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    since: Annotated[date | None, Query()] = None,
    until: Annotated[date | None, Query()] = None,
) -> ReferralReport:
    resolve_scope(session, principal, agency_id, client_id, "client:read")
    end = until or (now_utc().date() + timedelta(days=1))
    start = since or (end - timedelta(days=30))
    return ReferralReport.model_validate(referrals_view(session, agency_id, client_id, start, end))
