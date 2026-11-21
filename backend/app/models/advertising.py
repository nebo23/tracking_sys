"""Advertising spend state (specification 014-A, D-064 decisions D3, D4 and D13).

Every table is scoped by agency and client and references its spend connection through the
composite (agency_id, client_id, connection_id) key, so spend can never point at another
client's connection. Names are advertiser business data, not personal data; all rows are
purged when the connection's disconnect completes, and tracking_lifecycle deletes spend facts
730 days after their spend date. Reference queries below are manual read-only diagnostics for
an authorized operator; replace the synthetic literals before use.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.connectors import CONNECTION_FK

ACCOUNT_PATTERN = "^act_[1-9][0-9]{0,19}$"
OBJECT_PATTERN = "^[1-9][0-9]{0,31}$"
CURRENCY_PATTERN = "^[A-Z]{3}$"
RUN_FK = (
    ["agency_id", "client_id", "connection_id", "source_run_id"],
    [
        "connector_sync_runs.agency_id",
        "connector_sync_runs.client_id",
        "connector_sync_runs.connection_id",
        "connector_sync_runs.id",
    ],
)


def _time(nullable: bool = True, *, default: bool = False) -> Any:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now() if default else None,
        nullable=nullable,
    )


# The ad account of one spend connection as last read (D2, D4), with the previous currency or
# time zone when either changed. One row per connection.
# SELECT account_id, currency, time_zone, account_status, currency_changed_at, refreshed_at
# FROM public.ad_accounts
# WHERE connection_id = '00000000-0000-0000-0000-000000000009'::uuid;
class AdAccount(Base):
    __tablename__ = "ad_accounts"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        UniqueConstraint("connection_id", name="uq_ad_accounts_connection"),
        CheckConstraint(f"account_id ~ '{ACCOUNT_PATTERN}'", name="valid_account"),
        CheckConstraint(
            f"currency ~ '{CURRENCY_PATTERN}' AND (previous_currency IS NULL "
            f"OR previous_currency ~ '{CURRENCY_PATTERN}')",
            name="valid_currency",
        ),
        CheckConstraint(
            "(previous_currency IS NULL) = (currency_changed_at IS NULL) "
            "AND (previous_time_zone IS NULL) = (time_zone_changed_at IS NULL)",
            name="recorded_changes",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    account_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3))
    time_zone: Mapped[str] = mapped_column(String(64))
    account_status: Mapped[int | None] = mapped_column(Integer)
    previous_currency: Mapped[str | None] = mapped_column(String(3))
    currency_changed_at: Mapped[datetime | None] = _time()
    previous_time_zone: Mapped[str | None] = mapped_column(String(64))
    time_zone_changed_at: Mapped[datetime | None] = _time()
    observed_at: Mapped[datetime] = _time(False, default=True)
    refreshed_at: Mapped[datetime] = _time(False, default=True)


# Campaigns, ad sets and ads of a spend connection with their parents, names and effective
# statuses, refreshed by each inventory read. Objects a later read omits keep their last state.
# SELECT level, object_id, campaign_id, adset_id, effective_status, refreshed_at
# FROM public.ad_objects
# WHERE connection_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY level, object_id LIMIT 100;
class AdObject(Base):
    __tablename__ = "ad_objects"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        ForeignKeyConstraint(*RUN_FK),
        UniqueConstraint("connection_id", "object_id", name="uq_ad_objects_object"),
        CheckConstraint("level IN ('campaign', 'adset', 'ad')", name="valid_level"),
        CheckConstraint(
            f"object_id ~ '{OBJECT_PATTERN}' "
            f"AND (campaign_id IS NULL OR campaign_id ~ '{OBJECT_PATTERN}') "
            f"AND (adset_id IS NULL OR adset_id ~ '{OBJECT_PATTERN}')",
            name="valid_ids",
        ),
        CheckConstraint(
            "(level = 'campaign' AND campaign_id IS NULL AND adset_id IS NULL) "
            "OR (level = 'adset' AND campaign_id IS NOT NULL AND adset_id IS NULL) "
            "OR (level = 'ad' AND campaign_id IS NOT NULL AND adset_id IS NOT NULL)",
            name="valid_parents",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    object_id: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(16))
    campaign_id: Mapped[str | None] = mapped_column(String(32))
    adset_id: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(400))
    effective_status: Mapped[str | None] = mapped_column(String(32))
    first_observed_at: Mapped[datetime] = _time(False, default=True)
    refreshed_at: Mapped[datetime] = _time(False, default=True)
    source_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    adapter_version: Mapped[str | None] = mapped_column(String(32))


# One ad's spend on one account-local day (D3, D4): exact minor units of the currency the day
# was reported in, or a closed refusal without an amount. The unique key makes a re-read update
# the row; a changed value increments revisions. A day is provisional until provisional_until.
# SELECT spend_date, ad_id, currency, spend_minor, refusal, revisions, provisional_until
# FROM public.ad_spend_facts
# WHERE connection_id = '00000000-0000-0000-0000-000000000009'::uuid
#   AND spend_date BETWEEN DATE '2026-11-01' AND DATE '2026-11-07'
# ORDER BY spend_date, ad_id LIMIT 100;
class AdSpendFact(Base):
    __tablename__ = "ad_spend_facts"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        ForeignKeyConstraint(*RUN_FK),
        UniqueConstraint("connection_id", "ad_id", "spend_date", name="uq_ad_spend_facts_day"),
        CheckConstraint(
            f"ad_id ~ '{OBJECT_PATTERN}' "
            f"AND (campaign_id IS NULL OR campaign_id ~ '{OBJECT_PATTERN}') "
            f"AND (adset_id IS NULL OR adset_id ~ '{OBJECT_PATTERN}')",
            name="valid_ids",
        ),
        CheckConstraint(
            f"currency IS NULL OR currency ~ '{CURRENCY_PATTERN}'", name="valid_currency"
        ),
        CheckConstraint(
            "refusal IS NULL OR refusal IN ('unparseable_amount', 'unsupported_currency')",
            name="valid_refusal",
        ),
        CheckConstraint(
            "(refusal IS NULL) = (spend_minor IS NOT NULL) "
            "AND (refusal IS NOT NULL OR currency IS NOT NULL)",
            name="amount_or_refusal",
        ),
        CheckConstraint(
            "(spend_minor IS NULL OR spend_minor >= 0) AND impressions >= 0 AND clicks >= 0 "
            "AND revisions >= 0",
            name="valid_counts",
        ),
        Index("ix_ad_spend_facts_connection_date", "connection_id", "spend_date"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    ad_id: Mapped[str] = mapped_column(String(32))
    adset_id: Mapped[str | None] = mapped_column(String(32))
    campaign_id: Mapped[str | None] = mapped_column(String(32))
    spend_date: Mapped[date] = mapped_column(Date)
    time_zone: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(3))
    spend_minor: Mapped[int | None] = mapped_column(BigInteger)
    impressions: Mapped[int] = mapped_column(BigInteger, server_default="0")
    clicks: Mapped[int] = mapped_column(BigInteger, server_default="0")
    refusal: Mapped[str | None] = mapped_column(String(24))
    provisional_until: Mapped[datetime] = _time(False)
    revisions: Mapped[int] = mapped_column(Integer, server_default="0")
    first_observed_at: Mapped[datetime] = _time(False, default=True)
    last_observed_at: Mapped[datetime] = _time(False, default=True)
    source_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    adapter_version: Mapped[str | None] = mapped_column(String(32))
