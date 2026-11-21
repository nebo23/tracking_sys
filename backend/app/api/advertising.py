"""Advertising routes (specification 014, D-064 decision D10).

014-A: readers with finance:read read the spend of one spend connection. Amounts in different
currencies are never added; each total and row names its currency.

014-B: Owner and Admin sessions create, enable, disable and rename conversion destinations and
requeue or dismiss deliveries, each with an audit event; readers with client:read list
destinations without amounts, and readers with finance:read list deliveries with their values.
There is no route for enqueueing. No answer contains a person's identifier, a match key, a
payload, an event ID or a provider trace ID.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field

from app.api.dependencies import BrowserDep, ReaderDep, SessionDep
from app.api.schemas import Input, Output
from app.security import now_utc
from app.services.access import resolve_scope
from app.services.advertising import read_spend
from app.services.connectors import can_manage
from app.services.delivery import (
    DestinationAdmin,
    delivery_view,
    destination_view,
    list_deliveries,
    list_destinations,
)

router = APIRouter(tags=["Advertising"])
ObjectId = Annotated[str, Query(min_length=1, max_length=32, pattern=r"^[1-9][0-9]{0,31}$")]


class SpendAccount(Output):
    account_id: str
    currency: str
    time_zone: str
    status: int | None
    previous_currency: str | None
    currency_changed_at: datetime | None


class SpendTotal(Output):
    currency: str
    spend: str
    spend_minor: int
    impressions: int
    clicks: int
    days: int


class SpendRow(Output):
    object_id: str | None
    name: str | None
    currency: str
    spend: str
    spend_minor: int
    impressions: int
    clicks: int
    provisional: bool


class SpendRefusals(Output):
    unparseable_amount: int
    unsupported_currency: int


class SpendCoverage(Output):
    covered_from: date | None
    complete_through: date | None
    state: Literal["not_synced", "partial", "complete"]


class SpendReport(Output):
    connection_id: UUID
    account: SpendAccount | None
    level: Literal["ad", "adset", "campaign"]
    since: date
    until: date
    totals: list[SpendTotal]
    rows: list[SpendRow]
    next_after: str | None
    provisional_dates: list[date]
    refused: SpendRefusals
    coverage: SpendCoverage


# Spend of one spend connection for account-local dates since..until (inclusive, at most 366
# days), at the ad, ad set or campaign level, with rows paged by object ID.
@router.get("/agencies/{agency_id}/clients/{client_id}/ad-spend", response_model=SpendReport)
def read_ad_spend(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    connection_id: Annotated[UUID, Query()],
    since: Annotated[date, Query()],
    until: Annotated[date, Query()],
    level: Annotated[Literal["ad", "adset", "campaign"], Query()] = "ad",
    after: ObjectId | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> SpendReport:
    access = resolve_scope(session, principal, agency_id, client_id, "finance:read")
    return SpendReport.model_validate(
        read_spend(
            session,
            access,
            connection_id,
            since=since,
            until=until,
            level=level,
            now=now_utc(),
            after=after,
            limit=limit,
        )
    )


# --- 014-B: destinations and deliveries (D10) ----------------------------------------------

EventName = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]
TestCode = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")]


class DestinationInput(Input):
    connection_id: UUID
    event_name: EventName = "Purchase"
    test_event_code: TestCode | None = None


class DestinationUpdate(Input):
    enabled: bool | None = None
    event_name: EventName | None = None
    test_event_code: TestCode | None = None
    clear_test_event_code: bool = False


class DestinationActions(Output):
    update: bool


class DestinationResponse(Output):
    id: UUID
    connection_id: UUID
    event_name: str
    test_event_code: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    actions: DestinationActions


class DeliveryActions(Output):
    requeue: bool
    dismiss: bool


DeliveryStatus = Literal[
    "queued",
    "sending",
    "delivered",
    "blocked",
    "cancelled",
    "expired",
    "rejected",
    "undeliverable",
    "dismissed",
]


class DeliveryResponse(Output):
    id: UUID
    destination_id: UUID
    event_name: str
    action_source: str
    event_time: datetime
    status: DeliveryStatus
    reason: str | None
    rejection_class: Literal["configuration", "payload"] | None
    value: str
    currency: str
    attempts: int
    requeues: int
    next_attempt_at: datetime | None
    deadline: datetime
    created_at: datetime
    delivered_at: datetime | None
    ended_at: datetime | None
    actions: DeliveryActions


def _destinations(request: Request, session: SessionDep, browser: BrowserDep) -> DestinationAdmin:
    state = request.app.state
    return DestinationAdmin(session, browser.user.id, state.settings, state.connector_providers)


def _destination_response(row, manage: bool) -> DestinationResponse:
    return DestinationResponse.model_validate(destination_view(row, manage=manage))


def _delivery_response(row, manage: bool) -> DeliveryResponse:
    return DeliveryResponse.model_validate(delivery_view(row, manage=manage, now=now_utc()))


# Create the destination of one delivery connection of the client (Owner/Admin), disabled.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/conversion-destinations",
    status_code=201,
    response_model=DestinationResponse,
)
def create_destination(
    agency_id: UUID,
    client_id: UUID,
    data: DestinationInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> DestinationResponse:
    row = _destinations(request, session, browser).create(
        agency_id, client_id, data.connection_id, data.event_name, data.test_event_code
    )
    return _destination_response(row, True)


# Destinations with their status for readers with client:read; no amounts.
@router.get(
    "/agencies/{agency_id}/clients/{client_id}/conversion-destinations",
    response_model=list[DestinationResponse],
)
def read_destinations(
    agency_id: UUID, client_id: UUID, session: SessionDep, principal: ReaderDep
) -> list[DestinationResponse]:
    access = resolve_scope(session, principal, agency_id, client_id)
    manage = can_manage(session, principal, agency_id)
    return [_destination_response(row, manage) for row in list_destinations(session, access)]


# Enable, disable or rename a destination (Owner/Admin). Disabling cancels its open deliveries.
@router.patch(
    "/agencies/{agency_id}/clients/{client_id}/conversion-destinations/{destination_id}",
    response_model=DestinationResponse,
)
def update_destination(
    agency_id: UUID,
    client_id: UUID,
    destination_id: UUID,
    data: DestinationUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> DestinationResponse:
    row = _destinations(request, session, browser).update(
        agency_id,
        client_id,
        destination_id,
        enabled=data.enabled,
        event_name=data.event_name,
        test_event_code=data.test_event_code,
        clear_test_event_code=data.clear_test_event_code,
    )
    return _destination_response(row, True)


# Deliveries of the client, newest first, for readers with finance:read.
@router.get(
    "/agencies/{agency_id}/clients/{client_id}/conversion-deliveries",
    response_model=list[DeliveryResponse],
)
def read_deliveries(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    destination_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[DeliveryStatus | None, Query()] = None,
    after: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[DeliveryResponse]:
    access = resolve_scope(session, principal, agency_id, client_id, "finance:read")
    manage = can_manage(session, principal, agency_id)
    rows = list_deliveries(
        session, access, destination_id=destination_id, status=status, after=after, limit=limit
    )
    return [_delivery_response(row, manage) for row in rows]


# Requeue a configuration rejection after its repair (Owner/Admin); audited.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/conversion-deliveries/{delivery_id}/requeue",
    response_model=DeliveryResponse,
)
def requeue_delivery(
    agency_id: UUID,
    client_id: UUID,
    delivery_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> DeliveryResponse:
    row = _destinations(request, session, browser).requeue(agency_id, client_id, delivery_id)
    return _delivery_response(row, True)


# Dismiss a rejected or undeliverable delivery (Owner/Admin); audited.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/conversion-deliveries/{delivery_id}/dismiss",
    response_model=DeliveryResponse,
)
def dismiss_delivery(
    agency_id: UUID,
    client_id: UUID,
    delivery_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> DeliveryResponse:
    row = _destinations(request, session, browser).dismiss(agency_id, client_id, delivery_id)
    return _delivery_response(row, True)
