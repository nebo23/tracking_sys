"""Advertising routes (specification 014, D-064 decision D10).

014-A: readers with finance:read read the spend of one spend connection. Amounts in different
currencies are never added; each total and row names its currency. No answer contains a
person's identifier, a payload or a provider trace ID.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import ReaderDep, SessionDep
from app.api.schemas import Output
from app.security import now_utc
from app.services.access import resolve_scope
from app.services.advertising import read_spend

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
