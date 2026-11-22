"""Spend reads for readers with finance access (specification 014-A, D-064 decisions D3, D4, D10).

read_spend answers one spend connection of one client for a period of account-local dates at
the ad, ad set or campaign level: totals and rows per currency (amounts in different currencies
are never added), the provisional dates, the refused facts per reason, and the coverage of the
daily stream. The caller has resolved finance:read for the client; the connection must belong
to that client and be a spend connection. Nothing identifies a person.

Rows are grouped by object and currency, because each fact keeps the currency it was reported in
(D-064 D4), so one object can have rows in two currencies. Pages follow that complete key
(review finding R010): the cursor is "<object ID>:<currency>" of the last row, with an empty
object ID for facts without one at the level read, and the next page starts after that pair.
"""

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advertising.currencies import EXPONENTS, decimal_text
from app.models import AdAccount, AdObject, AdSpendFact, ConnectorCheckpoint, ConnectorConnection
from app.services.access import ScopedAccess
from app.services.connectors import ConnectorError
from app.services.tenancy import AccessDenied

SPEND_PROVIDERS = frozenset({"synthetic_meta_ads", "meta_ads"})
DAILY_STREAM = "ad_daily"
MAX_PERIOD_DAYS = 366
Level = Literal["ad", "adset", "campaign"]
KEYS = {"ad": "ad_id", "adset": "adset_id", "campaign": "campaign_id"}
# A page position: the object ID (empty when the level's ID is missing) and the currency.
CURSOR = re.compile(r"((?:[1-9][0-9]{0,31})?):([A-Z]{3})")


def page_cursor(key: str, currency: str) -> str:
    return f"{key}:{currency}"


def parse_page_cursor(cursor: str) -> tuple[str, str]:
    match = CURSOR.fullmatch(cursor)
    if match is None:
        raise ConnectorError("invalid_cursor", 422)
    return match.group(1), match.group(2)


def _connection(session: Session, access: ScopedAccess, connection_id: UUID) -> ConnectorConnection:
    connection = session.scalar(
        select(ConnectorConnection).where(
            ConnectorConnection.agency_id == access.agency_id,
            ConnectorConnection.client_id == access.client_id,
            ConnectorConnection.id == connection_id,
        )
    )
    if connection is None:
        raise AccessDenied()
    if connection.provider not in SPEND_PROVIDERS:
        raise ConnectorError("not_a_spend_connection", 422)
    return connection


def _local_date(instant: datetime | None, zone: str) -> date | None:
    return None if instant is None else instant.astimezone(ZoneInfo(zone)).date()


def _money(minor: int, currency: str) -> str:
    return decimal_text(minor, EXPONENTS[currency])


# The coverage of the daily stream as account-local dates: the first covered date and the last
# complete date (complete_through is the start of the first incomplete day).
def _coverage(
    session: Session, connection_id: UUID, zone: str | None, since: date, until: date
) -> dict[str, object]:
    checkpoint = session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connection_id == connection_id,
            ConnectorCheckpoint.stream == DAILY_STREAM,
        )
    )
    if checkpoint is None or zone is None or checkpoint.complete_through is None:
        return {"covered_from": None, "complete_through": None, "state": "not_synced"}
    first = _local_date(checkpoint.covered_from, zone)
    through = _local_date(checkpoint.complete_through, zone)
    last = through - timedelta(days=1) if through is not None else None
    complete = first is not None and last is not None and first <= since and until <= last
    return {
        "covered_from": first,
        "complete_through": last,
        "state": "complete" if complete else "partial",
    }


def read_spend(
    session: Session,
    access: ScopedAccess,
    connection_id: UUID,
    *,
    since: date,
    until: date,
    level: Level,
    now: datetime,
    after: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    if access.permission != "finance:read":
        raise AccessDenied()
    if until < since or (until - since).days >= MAX_PERIOD_DAYS:
        raise ConnectorError("invalid_period", 422)
    position = None if after is None else parse_page_cursor(after)
    connection = _connection(session, access, connection_id)
    account = session.scalar(select(AdAccount).where(AdAccount.connection_id == connection.id))
    facts = list(
        session.scalars(
            select(AdSpendFact)
            .where(
                AdSpendFact.connection_id == connection.id,
                AdSpendFact.spend_date >= since,
                AdSpendFact.spend_date <= until,
            )
            .order_by(AdSpendFact.spend_date, AdSpendFact.ad_id)
        )
    )
    totals: dict[str, dict[str, object]] = {}
    groups: dict[tuple[str, str], dict[str, object]] = {}
    refused: dict[str, int] = defaultdict(int)
    provisional: set[date] = set()
    key_name = KEYS[level]
    for fact in facts:
        if fact.provisional_until > now:
            provisional.add(fact.spend_date)
        if fact.refusal is not None or fact.spend_minor is None or fact.currency is None:
            refused[fact.refusal or "unparseable_amount"] += 1
            continue
        total = totals.setdefault(
            fact.currency,
            {"spend_minor": 0, "impressions": 0, "clicks": 0, "days": set()},
        )
        total["spend_minor"] += fact.spend_minor  # type: ignore[operator]
        total["impressions"] += fact.impressions  # type: ignore[operator]
        total["clicks"] += fact.clicks  # type: ignore[operator]
        total["days"].add(fact.spend_date)  # type: ignore[union-attr]
        key = getattr(fact, key_name) or ""
        group = groups.setdefault(
            (key, fact.currency),
            {"spend_minor": 0, "impressions": 0, "clicks": 0, "provisional": False},
        )
        group["spend_minor"] += fact.spend_minor  # type: ignore[operator]
        group["impressions"] += fact.impressions  # type: ignore[operator]
        group["clicks"] += fact.clicks  # type: ignore[operator]
        group["provisional"] = bool(group["provisional"]) or fact.provisional_until > now
    ordered = sorted(item for item in groups if position is None or item > position)
    page = ordered[:limit]
    names = {
        row.object_id: row.name
        for row in session.scalars(
            select(AdObject).where(
                AdObject.connection_id == connection.id,
                AdObject.level == level,
                AdObject.object_id.in_([key for key, _ in page]),
            )
        )
    }
    rows = [
        {
            "object_id": key or None,
            "name": names.get(key),
            "currency": currency,
            "spend": _money(int(groups[key, currency]["spend_minor"]), currency),
            "spend_minor": groups[key, currency]["spend_minor"],
            "impressions": groups[key, currency]["impressions"],
            "clicks": groups[key, currency]["clicks"],
            "provisional": groups[key, currency]["provisional"],
        }
        for key, currency in page
    ]
    following = page_cursor(*page[-1]) if len(ordered) > limit and page else None
    zone = account.time_zone if account is not None else connection.day_zone
    return {
        "connection_id": connection.id,
        "account": None
        if account is None
        else {
            "account_id": account.account_id,
            "currency": account.currency,
            "time_zone": account.time_zone,
            "status": account.account_status,
            "previous_currency": account.previous_currency,
            "currency_changed_at": account.currency_changed_at,
        },
        "level": level,
        "since": since,
        "until": until,
        "totals": [
            {
                "currency": currency,
                "spend": _money(int(values["spend_minor"]), currency),
                "spend_minor": values["spend_minor"],
                "impressions": values["impressions"],
                "clicks": values["clicks"],
                "days": len(values["days"]),  # type: ignore[arg-type]
            }
            for currency, values in sorted(totals.items())
        ],
        "rows": rows,
        "next_after": following,
        "provisional_dates": sorted(provisional),
        "refused": {
            "unparseable_amount": refused.get("unparseable_amount", 0),
            "unsupported_currency": refused.get("unsupported_currency", 0),
        },
        "coverage": _coverage(session, connection.id, zone, since, until),
    }


__all__ = ["SPEND_PROVIDERS", "read_spend"]
