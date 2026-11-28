"""Platform billing routes (specification 017-C, D-103 D6 to D9 and D11; design-017c.md section 7).

The Paddle webhook (D7) follows the order of the 015 signed intake: the gate (billing enabled
and the paddle.billing rule current, otherwise 503), the per-peer rate, the 256 KiB body bound
of ROUTE_LIMITS, then Paddle-Signature over the raw body with its timestamp within 300 seconds
(401 otherwise), the envelope (400), and the record and its effects in the request's
transaction. Every verified event is answered 200, so Paddle stops retrying; a repeated, late
or unmatched event changes nothing. Nothing here logs or returns a signature, a body, a name or
an email.
"""

from typing import Literal

from fastapi import APIRouter, Request

from app.api.dependencies import RawBody, SessionDep
from app.api.schemas import ErrorResponse, Output
from app.billing.paddle import InvalidPayload, InvalidSignature, parse_event, verify_signature
from app.security import now_utc
from app.services.auth import enforce_rate_limit
from app.services.billing import BillingRefused, require_billing
from app.services.billing_events import receive_event

webhook_router = APIRouter(prefix="/billing", tags=["Billing webhooks"])


class WebhookReceived(Output):
    status: Literal["received"]


# Paddle's notifications (D7). Answered within the request; no outbound call is made.
@webhook_router.post(
    "/paddle/webhook",
    response_model=WebhookReceived,
    responses={
        400: {"model": ErrorResponse, "description": "A verified body without a valid event."},
        401: {"model": ErrorResponse, "description": "A missing, old or invalid signature."},
        413: {"model": ErrorResponse, "description": "A body above 256 KiB."},
        429: {"model": ErrorResponse, "description": "Too many notifications from the peer."},
        503: {"model": ErrorResponse, "description": "Billing is not enabled."},
    },
    openapi_extra={
        "parameters": [
            {
                "name": "Paddle-Signature",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
                "description": "ts=<unix seconds>;h1=<HMAC-SHA256 of ts:body, hexadecimal>.",
            }
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
    },
)
def paddle_webhook(request: Request, session: SessionDep, body: RawBody) -> WebhookReceived:
    settings = request.app.state.settings
    now = now_utc()
    require_billing(settings, now.date())
    peer = request.client.host if request.client else "unknown"
    enforce_rate_limit(
        request.app.state.security_engine,
        settings,
        "paddle-peer",
        peer,
        limit=settings.ingest_trusted_per_minute,
        period=60,
    )
    try:
        verify_signature(
            request.headers.get("paddle-signature"),
            body,
            settings.billing_paddle_webhook_secret.get_secret_value(),
            now.timestamp(),
        )
    except InvalidSignature:
        raise BillingRefused("invalid_signature", 401) from None
    try:
        event = parse_event(body)
    except InvalidPayload:
        raise BillingRefused("invalid_payload", 400) from None
    receive_event(session, event)
    return WebhookReceived(status="received")
