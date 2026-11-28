"""Platform billing routes (specification 017-C, D-103 D6 to D9 and D11; design-017c.md section 7).

Browser sessions only: BrowserDep refuses every read or ingest key and requires the
session-bound CSRF token and an allowed origin for writes. Owners act and Owners and Admins
read, in an active agency; every other role or agency gets the uniform access denial. While
billing is disabled every route answers 503 billing_unavailable. Routes that call Paddle are
throttled per user. The answers carry IDs, codes, amounts, currencies and times, never a card,
a provider secret, a name or an email; an invoice address is a redirect fetched at request time.

The Paddle webhook (D7) follows the order of the 015 signed intake: the gate (billing enabled
and the paddle.billing rule current, otherwise 503), the per-peer rate, the 256 KiB body bound
of ROUTE_LIMITS, then Paddle-Signature over the raw body with its timestamp within 300 seconds
(401 otherwise), the envelope (400), and the record and its effects in the request's
transaction. Every verified event is answered 200, so Paddle stops retrying; a repeated, late
or unmatched event changes nothing. Nothing here logs or returns a signature, a body, a name or
an email.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.api.dependencies import BrowserDep, RawBody, SessionDep
from app.api.schemas import ErrorResponse, Input, Output
from app.billing.paddle import (
    InvalidPayload,
    InvalidSignature,
    Totals,
    parse_event,
    verify_signature,
)
from app.security import now_utc
from app.services.auth import enforce_rate_limit
from app.services.billing import BillingRefused, require_billing
from app.services.billing_events import receive_event
from app.services.billing_owner import BillingOwnerService, invoice_available, plan_limits

router = APIRouter(tags=["Billing"])
webhook_router = APIRouter(prefix="/billing", tags=["Billing webhooks"])
BASE = "/agencies/{agency_id}/billing"
# Calls to Paddle per user and minute, well below Paddle's 240 per IP (V-12).
USER_CALLS_PER_MINUTE = 20
REFUSALS = {
    403: {"model": ErrorResponse, "description": "Not an allowed member of an active agency."},
    409: {"model": ErrorResponse, "description": "A closed billing refusal."},
    503: {"model": ErrorResponse, "description": "Billing or Paddle is unavailable."},
}


class BillingPlan(Output):
    key: str
    name: str
    limits: dict[str, int | None]


class BillingPriceView(Output):
    id: UUID
    plan: BillingPlan
    amount_cents: int
    currency: str
    interval: Literal["month", "year"]


class BillingPrices(Output):
    environment: Literal["sandbox", "live"]
    client_token: str | None
    prices: list[BillingPriceView]


class BillingPriceRef(Output):
    id: UUID
    amount_cents: int
    currency: str
    interval: Literal["month", "year"]


class BillingScheduledChange(Output):
    action: Literal["cancel", "pause", "resume"]
    effective_at: datetime


class BillingSubscriptionView(Output):
    id: UUID
    status: Literal["trialing", "active", "past_due", "paused", "canceled"]
    price: BillingPriceRef | None
    current_period_ends_at: datetime | None
    next_billed_at: datetime | None
    scheduled_change: BillingScheduledChange | None


class BillingLastPayment(Output):
    id: UUID
    status: str
    currency: str
    total_cents: int
    billed_at: datetime | None


class BillingCurrentPlan(Output):
    key: str
    name: str


class AgencyBillingView(Output):
    agency_id: UUID
    standing: Literal["complimentary", "trialing", "subscribed", "past_due", "hold"]
    reason: str
    trial_ends_at: datetime | None
    grant_ends_at: datetime | None
    hold_started_at: datetime | None
    plan: BillingCurrentPlan
    subscription: BillingSubscriptionView | None
    last_payment: BillingLastPayment | None
    version: int


class BillingCheckoutInput(Input):
    price_id: UUID


class BillingCheckoutView(Output):
    checkout_id: UUID
    transaction_id: str
    status: Literal["open"]
    expires_at: datetime


class BillingChangeInput(Input):
    price_id: UUID
    preview: bool = False


class BillingTotals(Output):
    currency: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int


class BillingChangeResult(Output):
    action: Literal["credit", "charge"]
    amount_cents: int


class BillingChangePreview(Output):
    proration: Literal["prorated_immediately", "prorated_next_billing_period"]
    immediate: BillingTotals | None
    next: BillingTotals | None
    credit_cents: int | None
    charge_cents: int | None
    result: BillingChangeResult | None


class BillingChangeRequested(Output):
    status: Literal["requested"]
    proration: Literal["prorated_immediately", "prorated_next_billing_period"]


class BillingCancellation(Output):
    scheduled_change: BillingScheduledChange | None


class BillingPaymentMethod(Output):
    transaction_id: str


class BillingPaymentView(Output):
    id: UUID
    status: str
    origin: str | None
    currency: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    billed_at: datetime | None
    invoice_number: str | None
    invoice_available: bool


class BillingWebhookReceived(Output):
    status: Literal["received"]


def _service(request: Request, session, browser) -> BillingOwnerService:  # noqa: ANN001
    return BillingOwnerService(
        session,
        browser.user.id,
        request.app.state.settings,
        request.app.state.billing_provider,
    )


def _throttle(request: Request, browser) -> None:  # noqa: ANN001
    enforce_rate_limit(
        request.app.state.security_engine,
        request.app.state.settings,
        "billing-user",
        str(browser.user.id),
        limit=USER_CALLS_PER_MINUTE,
        period=60,
    )


def _totals(value: Totals | None) -> BillingTotals | None:
    if value is None:
        return None
    return BillingTotals(
        currency=value.currency,
        subtotal_cents=value.subtotal,
        tax_cents=value.tax,
        total_cents=value.total,
    )


def _scheduled(action: str | None, effective_at: datetime | None) -> BillingScheduledChange | None:
    if action is None or effective_at is None:
        return None
    return BillingScheduledChange(action=action, effective_at=effective_at)


# The offered prices, for any signed-in user, with the Paddle environment and client token.
@router.get("/billing/prices", response_model=BillingPrices, responses=REFUSALS)
def billing_prices(request: Request, session: SessionDep, browser: BrowserDep) -> BillingPrices:
    found = _service(request, session, browser).prices()
    return BillingPrices(
        environment=found["environment"],
        client_token=found["client_token"],
        prices=[
            BillingPriceView(
                id=price.id,
                plan=BillingPlan(key=plan.key, name=plan.name, limits=plan_limits(plan)),
                amount_cents=price.amount_cents,
                currency=price.currency,
                interval=price.billing_interval,
            )
            for price, plan in found["prices"]
        ],
    )


# The agency's billing (Owners and Admins).
@router.get(BASE, response_model=AgencyBillingView, responses=REFUSALS)
def agency_billing(
    agency_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> AgencyBillingView:
    found = _service(request, session, browser).view(agency_id)
    standing, plan, subscription = found["standing"], found["plan"], found["subscription"]
    price, payment = found["price"], found["payment"]
    return AgencyBillingView(
        agency_id=agency_id,
        standing=standing.standing,
        reason=standing.reason,
        trial_ends_at=standing.trial_ends_at,
        grant_ends_at=standing.grant_ends_at,
        hold_started_at=standing.hold_started_at,
        plan=BillingCurrentPlan(key=plan.key, name=plan.name),
        subscription=None
        if subscription is None
        else BillingSubscriptionView(
            id=subscription.id,
            status=subscription.status,
            price=None
            if price is None
            else BillingPriceRef(
                id=price.id,
                amount_cents=price.amount_cents,
                currency=price.currency,
                interval=price.billing_interval,
            ),
            current_period_ends_at=subscription.current_period_ends_at,
            next_billed_at=subscription.next_billed_at,
            scheduled_change=_scheduled(subscription.scheduled_action, subscription.scheduled_at),
        ),
        last_payment=None
        if payment is None
        else BillingLastPayment(
            id=payment.id,
            status=payment.status,
            currency=payment.currency,
            total_cents=payment.total_cents,
            billed_at=payment.billed_at,
        ),
        version=standing.version,
    )


# D6: open (or return) the agency's checkout for a price (Owners); Paddle.js opens its
# transaction ID.
@router.post(
    f"{BASE}/checkout", status_code=201, response_model=BillingCheckoutView, responses=REFUSALS
)
def billing_checkout(
    agency_id: UUID,
    data: BillingCheckoutInput,
    request: Request,
    response: Response,
    session: SessionDep,
    browser: BrowserDep,
) -> BillingCheckoutView:
    _throttle(request, browser)
    checkout, created = _service(request, session, browser).checkout(agency_id, data.price_id)
    if not created:
        response.status_code = 200
    return BillingCheckoutView(
        checkout_id=checkout.id,
        transaction_id=checkout.provider_transaction_id,
        status="open",
        expires_at=checkout.expires_at,
    )


# D8: preview or request a change of the subscription's price (Owners).
@router.post(
    f"{BASE}/change",
    response_model=BillingChangePreview | BillingChangeRequested,
    responses={**REFUSALS, 202: {"model": BillingChangeRequested}},
)
def billing_change(
    agency_id: UUID,
    data: BillingChangeInput,
    request: Request,
    response: Response,
    session: SessionDep,
    browser: BrowserDep,
) -> BillingChangePreview | BillingChangeRequested:
    _throttle(request, browser)
    found = _service(request, session, browser).change(
        agency_id, data.price_id, preview=data.preview
    )
    preview = found["preview"]
    if preview is None:
        response.status_code = 202
        return BillingChangeRequested(status="requested", proration=found["proration"])
    return BillingChangePreview(
        proration=found["proration"],
        immediate=_totals(preview.immediate),
        next=_totals(preview.next),
        credit_cents=preview.credit,
        charge_cents=preview.charge,
        result=None
        if preview.result_action is None or preview.result_amount is None
        else BillingChangeResult(action=preview.result_action, amount_cents=preview.result_amount),
    )


# D9: schedule the cancellation at the end of the paid period (Owners).
@router.post(f"{BASE}/cancel", response_model=BillingCancellation, responses=REFUSALS)
def billing_cancel(
    agency_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> BillingCancellation:
    _throttle(request, browser)
    action, effective_at = _service(request, session, browser).cancel(agency_id)
    return BillingCancellation(scheduled_change=_scheduled(action, effective_at))


# D9: undo the scheduled cancellation (Owners).
@router.delete(f"{BASE}/cancel", status_code=204, responses=REFUSALS)
def billing_undo_cancel(
    agency_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> Response:
    _throttle(request, browser)
    _service(request, session, browser).undo_cancel(agency_id)
    return Response(status_code=204)


# D9: the payment-method transaction that Paddle.js opens (Owners).
@router.post(f"{BASE}/payment-method", response_model=BillingPaymentMethod, responses=REFUSALS)
def billing_payment_method(
    agency_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> BillingPaymentMethod:
    _throttle(request, browser)
    transaction = _service(request, session, browser).payment_method(agency_id)
    return BillingPaymentMethod(transaction_id=transaction)


# D11: the payment history, newest first (Owners and Admins).
@router.get(f"{BASE}/payments", response_model=list[BillingPaymentView], responses=REFUSALS)
def billing_payments(
    agency_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> list[BillingPaymentView]:
    rows = _service(request, session, browser).payments(agency_id, limit=limit, offset=offset)
    return [
        BillingPaymentView(
            id=row.id,
            status=row.status,
            origin=row.origin,
            currency=row.currency,
            subtotal_cents=row.subtotal_cents,
            tax_cents=row.tax_cents,
            total_cents=row.total_cents,
            billed_at=row.billed_at,
            invoice_number=row.invoice_number,
            invoice_available=invoice_available(row),
        )
        for row in rows
    ]


# D11: a redirect to Paddle's temporary invoice address (Owners and Admins).
@router.get(
    f"{BASE}/payments/{{payment_id}}/invoice",
    status_code=302,
    response_class=RedirectResponse,
    responses={**REFUSALS, 302: {"description": "Paddle's temporary invoice address."}},
)
def billing_invoice(
    agency_id: UUID, payment_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> RedirectResponse:
    _throttle(request, browser)
    url = _service(request, session, browser).invoice(agency_id, payment_id)
    return RedirectResponse(url, status_code=302)


# Paddle's notifications (D7). Answered within the request; no outbound call is made.
@webhook_router.post(
    "/paddle/webhook",
    response_model=BillingWebhookReceived,
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
def paddle_webhook(request: Request, session: SessionDep, body: RawBody) -> BillingWebhookReceived:
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
    return BillingWebhookReceived(status="received")
