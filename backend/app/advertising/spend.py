"""Storage of advertising spend pages (specification 014-A, D-064 decisions D3, D4 and D13).

The connector runtime calls these functions inside the fenced transaction that also moves the
stream's checkpoint, so a page's rows and its cursor commit together:

- store_account keeps the ad account a connect described (D2) or the account stream read, and
  records a changed currency or time zone. The connection's day zone and label follow it.
- store_page writes one page of the account, ad_objects or ad_daily stream. A daily row's spend
  is parsed exactly in its own currency (app.advertising.currencies); a refused value stores a
  closed refusal and no amount. The unique (connection, ad, date) key makes a re-read update
  the row, and a changed value increments its revision count. A row the provider omits is never
  deleted: Meta does not say whether deleted ads stay in insights (V-1).
- purge removes every spend row of a connection when its disconnect completes.

Nothing here reads or returns data across clients; every write is keyed by the claimed
connection, whose agency and client the fence has checked.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.advertising.currencies import parse_spend
from app.connectors.contracts import AccountSnapshot, ProviderPage
from app.models import AdAccount, AdObject, AdSpendFact, ConnectorConnection
from app.models.advertising import ACCOUNT_PATTERN, OBJECT_PATTERN

# A day stays provisional until 28 days after it ends: Meta's insights "do not change after 28
# days of being reported" (V-4).
PROVISIONAL_DAYS = 28
LEVELS = ("campaign", "adset", "ad")
ACCOUNT, OBJECTS, DAILY = "account", "ad_objects", "ad_daily"


def _matches(pattern: str, value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern.strip("^$"), value) is not None


def _zone(value: object) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return value


def _currency(value: object) -> str | None:
    if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isupper():
        return value
    return None


def _count(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


# The instant until which a fact of `day` is provisional in `zone`.
def provisional_until(day: date, zone: str) -> datetime:
    local = ZoneInfo(zone)
    return datetime.combine(day + timedelta(days=1 + PROVISIONAL_DAYS), time(), local)


@dataclass(frozen=True)
class PageContext:
    agency_id: UUID
    client_id: UUID
    connection_id: UUID
    run_id: UUID
    adapter_version: str | None
    stream: str
    day_zone: str | None


# Keep the described or read account, recording a change of currency or time zone, and let the
# connection's day zone and label follow it. Returns False when the attributes are unusable.
def store_account(
    session: Session,
    connection: ConnectorConnection,
    account_id: str,
    attributes: Mapping[str, Any],
    label: str | None,
    now: datetime,
) -> bool:
    currency = _currency(attributes.get("currency"))
    zone = _zone(attributes.get("timezone_name"))
    if not _matches(ACCOUNT_PATTERN, account_id) or currency is None or zone is None:
        return False
    status = attributes.get("account_status")
    status = status if isinstance(status, int) and not isinstance(status, bool) else None
    name = label[:200] if isinstance(label, str) else None
    row = session.scalar(
        select(AdAccount).where(AdAccount.connection_id == connection.id).with_for_update()
    )
    if row is None:
        session.add(
            AdAccount(
                id=uuid4(),
                agency_id=connection.agency_id,
                client_id=connection.client_id,
                connection_id=connection.id,
                account_id=account_id,
                name=name,
                currency=currency,
                time_zone=zone,
                account_status=status,
                observed_at=now,
                refreshed_at=now,
            )
        )
    else:
        if row.currency != currency:
            row.previous_currency, row.currency_changed_at = row.currency, now
            row.currency = currency
        if row.time_zone != zone:
            row.previous_time_zone, row.time_zone_changed_at = row.time_zone, now
            row.time_zone = zone
        row.name, row.account_status, row.refreshed_at = name, status, now
    connection.day_zone = zone
    if name is not None:
        connection.account_label = name
    return True


# Keep the account a connect described (D2), in the installation's transaction.
def store_snapshot(
    session: Session, connection: ConnectorConnection, snapshot: AccountSnapshot, now: datetime
) -> bool:
    return store_account(
        session, connection, snapshot.account_id, snapshot.attributes, snapshot.label, now
    )


def _store_objects(
    session: Session, context: PageContext, page: ProviderPage, now: datetime
) -> None:
    for record in page.records:
        attributes = record.attributes
        level = attributes.get("level")
        campaign, adset = attributes.get("campaign_id"), attributes.get("adset_id")
        parents_ok = (
            (level == "campaign" and campaign is None and adset is None)
            or (level == "adset" and _matches(OBJECT_PATTERN, campaign) and adset is None)
            or (
                level == "ad"
                and _matches(OBJECT_PATTERN, campaign)
                and _matches(OBJECT_PATTERN, adset)
            )
        )
        if not _matches(OBJECT_PATTERN, record.provider_object_id) or not parents_ok:
            continue
        name = attributes.get("name")
        status = attributes.get("effective_status")
        values = {
            "id": uuid4(),
            "agency_id": context.agency_id,
            "client_id": context.client_id,
            "connection_id": context.connection_id,
            "object_id": record.provider_object_id,
            "level": level,
            "campaign_id": campaign,
            "adset_id": adset,
            "name": name[:400] if isinstance(name, str) else None,
            "effective_status": status[:32] if isinstance(status, str) else None,
            "first_observed_at": now,
            "refreshed_at": now,
            "source_run_id": context.run_id,
            "adapter_version": context.adapter_version,
        }
        statement = insert(AdObject).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_ad_objects_object",
                set_={
                    name: getattr(statement.excluded, name)
                    for name in (
                        "level",
                        "campaign_id",
                        "adset_id",
                        "name",
                        "effective_status",
                        "refreshed_at",
                        "source_run_id",
                        "adapter_version",
                    )
                },
            )
        )


# The values a daily row stores: exact spend in its currency, or a closed refusal.
def fact_values(attributes: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, Any]:
    code = attributes.get("currency")
    parsed = parse_spend(attributes.get("spend"), code)
    refused = isinstance(parsed, str)
    return {
        "currency": _currency(code),
        "spend_minor": None if refused else parsed.minor,
        "refusal": parsed if refused else None,
        "impressions": _count(metrics.get("impressions")),
        "clicks": _count(metrics.get("clicks")),
    }


CHANGED = ("currency", "spend_minor", "refusal", "impressions", "clicks")


def _store_daily(session: Session, context: PageContext, page: ProviderPage, now: datetime) -> None:
    zone = context.day_zone
    if zone is None:
        return
    for record in page.records:
        attributes = record.attributes
        try:
            day = date.fromisoformat(str(attributes.get("date")))
        except ValueError:
            continue
        campaign, adset = attributes.get("campaign_id"), attributes.get("adset_id")
        if not _matches(OBJECT_PATTERN, record.provider_object_id):
            continue
        values = {
            "id": uuid4(),
            "agency_id": context.agency_id,
            "client_id": context.client_id,
            "connection_id": context.connection_id,
            "ad_id": record.provider_object_id,
            "adset_id": adset if _matches(OBJECT_PATTERN, adset) else None,
            "campaign_id": campaign if _matches(OBJECT_PATTERN, campaign) else None,
            "spend_date": day,
            "time_zone": zone,
            "provisional_until": provisional_until(day, zone),
            "revisions": 0,
            "first_observed_at": now,
            "last_observed_at": now,
            "source_run_id": context.run_id,
            "adapter_version": context.adapter_version,
            **fact_values(attributes, record.metrics),
        }
        statement = insert(AdSpendFact).values(**values)
        excluded = statement.excluded
        changed = or_(
            *(
                getattr(AdSpendFact, name).is_distinct_from(getattr(excluded, name))
                for name in CHANGED
            )
        )
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_ad_spend_facts_day",
                set_={
                    **{
                        name: getattr(excluded, name)
                        for name in (
                            *CHANGED,
                            "adset_id",
                            "campaign_id",
                            "time_zone",
                            "provisional_until",
                            "last_observed_at",
                            "source_run_id",
                            "adapter_version",
                        )
                    },
                    "revisions": AdSpendFact.revisions + case((changed, 1), else_=0),
                },
            )
        )


# Store one page of an advertising stream under the caller's fence.
def store_page(
    session: Session,
    connection: ConnectorConnection,
    context: PageContext,
    page: ProviderPage,
    now: datetime,
) -> None:
    if context.stream == ACCOUNT:
        for record in page.records:
            label = record.attributes.get("name")
            store_account(
                session,
                connection,
                record.provider_object_id,
                record.attributes,
                label if isinstance(label, str) else page.account_label,
                now,
            )
    elif context.stream == OBJECTS:
        _store_objects(session, context, page, now)
    elif context.stream == DAILY:
        _store_daily(session, context, page, now)


# Remove every spend row of a connection whose disconnect completes (D13).
def purge(session: Session, connection_id: UUID) -> None:
    for model in (AdSpendFact, AdObject, AdAccount):
        session.execute(delete(model).where(model.connection_id == connection_id))


__all__ = [
    "PROVISIONAL_DAYS",
    "PageContext",
    "fact_values",
    "provisional_until",
    "purge",
    "store_account",
    "store_page",
    "store_snapshot",
]
