"""Advertising spend: ad accounts, ad objects and daily spend facts

Revision ID: 0017_ad_spend
Revises: 0016_youtube_provider
Created: 2026-11-21

Specification 014-A (D-064 decisions D2 to D4, D13 and D14; design in
specs/014-ad-spend-capi/design-014.md). Adds three client-scoped spend tables whose every
reference to a connection or run is a composite (agency_id, client_id, ...) key: ad_accounts
(one per spend connection), ad_objects (campaigns, ad sets and ads) and ad_spend_facts (one row
per connection, ad and account-local day, with exact minor units or a closed refusal and no
amount). Connections add the day zone of their account, and connector OAuth transactions the
account the connect request named. Connections, webhook deliveries and data deletion requests
accept the provider synthetic_meta_ads. tracking_app may insert, update the columns a re-read
or refresh changes, and delete spend rows for the disconnect purge; tracking_lifecycle may
delete spend facts 730 days after their spend date and read nothing else. The downgrade refuses
populated 014-A state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0017_ad_spend"
down_revision: str | Sequence[str] | None = "0016_youtube_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONNECTIONS = "connector_connections"
TRANSACTIONS = "connector_oauth_transactions"
CHECKED = (CONNECTIONS, "connector_webhook_deliveries", "connector_deletion_requests")
UNCHECKED = (TRANSACTIONS, "connector_usage_records")
PROVIDERS = (
    "provider IN ('synthetic', 'synthetic_instagram', 'instagram', 'synthetic_youtube', 'youtube'"
)
OLD_PROVIDERS = PROVIDERS + ")"
NEW_PROVIDERS = PROVIDERS + ", 'synthetic_meta_ads')"
CONNECTION = [
    "connector_connections.agency_id",
    "connector_connections.client_id",
    "connector_connections.id",
]
RUN = [
    "connector_sync_runs.agency_id",
    "connector_sync_runs.client_id",
    "connector_sync_runs.connection_id",
    "connector_sync_runs.id",
]
ACCOUNT_PATTERN = "^act_[1-9][0-9]{0,19}$"
OBJECT_PATTERN = "^[1-9][0-9]{0,31}$"
CURRENCY_PATTERN = "^[A-Z]{3}$"
# Children before parents.
TABLES = ("ad_spend_facts", "ad_objects", "ad_accounts")
ACCOUNT_UPDATES = (
    "name",
    "currency",
    "time_zone",
    "account_status",
    "previous_currency",
    "currency_changed_at",
    "previous_time_zone",
    "time_zone_changed_at",
    "refreshed_at",
)
OBJECT_UPDATES = (
    "level",
    "campaign_id",
    "adset_id",
    "name",
    "effective_status",
    "refreshed_at",
    "source_run_id",
    "adapter_version",
)
FACT_UPDATES = (
    "adset_id",
    "campaign_id",
    "time_zone",
    "currency",
    "spend_minor",
    "impressions",
    "clicks",
    "refusal",
    "provisional_until",
    "revisions",
    "last_observed_at",
    "source_run_id",
    "adapter_version",
)
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT, DELETE ON {', '.join(TABLES)} TO tracking_app",
    f"GRANT UPDATE ({', '.join(ACCOUNT_UPDATES)}) ON ad_accounts TO tracking_app",
    f"GRANT UPDATE ({', '.join(OBJECT_UPDATES)}) ON ad_objects TO tracking_app",
    f"GRANT UPDATE ({', '.join(FACT_UPDATES)}) ON ad_spend_facts TO tracking_app",
    f"GRANT UPDATE (day_zone) ON {CONNECTIONS} TO tracking_app",
)
LIFECYCLE_GRANTS = (
    "GRANT SELECT (id, spend_date) ON ad_spend_facts TO tracking_lifecycle",
    "GRANT DELETE ON ad_spend_facts TO tracking_lifecycle",
)


def _scope() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
    ]


def _connection(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", "connection_id"],
        CONNECTION,
        name=op.f(f"fk_{table}_agency_id_connector_connections"),
    )


def _run(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", "connection_id", "source_run_id"],
        RUN,
        name=op.f(f"fk_{table}_agency_id_connector_sync_runs"),
    )


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _time(name: str, *, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    for table in CHECKED:
        _replace_check(table, "valid_provider", NEW_PROVIDERS)
    op.add_column(CONNECTIONS, sa.Column("day_zone", sa.String(length=64), nullable=True))
    op.add_column(TRANSACTIONS, sa.Column("requested_account", sa.String(length=32), nullable=True))

    table = "ad_accounts"
    op.create_table(
        table,
        *_scope(),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("account_status", sa.Integer(), nullable=True),
        sa.Column("previous_currency", sa.String(length=3), nullable=True),
        _time("currency_changed_at"),
        sa.Column("previous_time_zone", sa.String(length=64), nullable=True),
        _time("time_zone_changed_at"),
        _time("observed_at", nullable=False, default=True),
        _time("refreshed_at", nullable=False, default=True),
        _check(table, "valid_account", f"account_id ~ '{ACCOUNT_PATTERN}'"),
        _check(
            table,
            "valid_currency",
            f"currency ~ '{CURRENCY_PATTERN}' AND (previous_currency IS NULL "
            f"OR previous_currency ~ '{CURRENCY_PATTERN}')",
        ),
        _check(
            table,
            "recorded_changes",
            "(previous_currency IS NULL) = (currency_changed_at IS NULL) "
            "AND (previous_time_zone IS NULL) = (time_zone_changed_at IS NULL)",
        ),
        _connection(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("connection_id", name="uq_ad_accounts_connection"),
    )

    table = "ad_objects"
    op.create_table(
        table,
        *_scope(),
        sa.Column("object_id", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("campaign_id", sa.String(length=32), nullable=True),
        sa.Column("adset_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=400), nullable=True),
        sa.Column("effective_status", sa.String(length=32), nullable=True),
        _time("first_observed_at", nullable=False, default=True),
        _time("refreshed_at", nullable=False, default=True),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("adapter_version", sa.String(length=32), nullable=True),
        _check(table, "valid_level", "level IN ('campaign', 'adset', 'ad')"),
        _check(
            table,
            "valid_ids",
            f"object_id ~ '{OBJECT_PATTERN}' "
            f"AND (campaign_id IS NULL OR campaign_id ~ '{OBJECT_PATTERN}') "
            f"AND (adset_id IS NULL OR adset_id ~ '{OBJECT_PATTERN}')",
        ),
        _check(
            table,
            "valid_parents",
            "(level = 'campaign' AND campaign_id IS NULL AND adset_id IS NULL) "
            "OR (level = 'adset' AND campaign_id IS NOT NULL AND adset_id IS NULL) "
            "OR (level = 'ad' AND campaign_id IS NOT NULL AND adset_id IS NOT NULL)",
        ),
        _connection(table),
        _run(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("connection_id", "object_id", name="uq_ad_objects_object"),
    )

    table = "ad_spend_facts"
    op.create_table(
        table,
        *_scope(),
        sa.Column("ad_id", sa.String(length=32), nullable=False),
        sa.Column("adset_id", sa.String(length=32), nullable=True),
        sa.Column("campaign_id", sa.String(length=32), nullable=True),
        sa.Column("spend_date", sa.Date(), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("spend_minor", sa.BigInteger(), nullable=True),
        sa.Column("impressions", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("refusal", sa.String(length=24), nullable=True),
        _time("provisional_until", nullable=False),
        sa.Column("revisions", sa.Integer(), server_default="0", nullable=False),
        _time("first_observed_at", nullable=False, default=True),
        _time("last_observed_at", nullable=False, default=True),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("adapter_version", sa.String(length=32), nullable=True),
        _check(
            table,
            "valid_ids",
            f"ad_id ~ '{OBJECT_PATTERN}' "
            f"AND (campaign_id IS NULL OR campaign_id ~ '{OBJECT_PATTERN}') "
            f"AND (adset_id IS NULL OR adset_id ~ '{OBJECT_PATTERN}')",
        ),
        _check(table, "valid_currency", f"currency IS NULL OR currency ~ '{CURRENCY_PATTERN}'"),
        _check(
            table,
            "valid_refusal",
            "refusal IS NULL OR refusal IN ('unparseable_amount', 'unsupported_currency')",
        ),
        _check(
            table,
            "amount_or_refusal",
            "(refusal IS NULL) = (spend_minor IS NOT NULL) "
            "AND (refusal IS NOT NULL OR currency IS NOT NULL)",
        ),
        _check(
            table,
            "valid_counts",
            "(spend_minor IS NULL OR spend_minor >= 0) AND impressions >= 0 AND clicks >= 0 "
            "AND revisions >= 0",
        ),
        _connection(table),
        _run(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("connection_id", "ad_id", "spend_date", name="uq_ad_spend_facts_day"),
    )
    op.create_index("ix_ad_spend_facts_connection_date", table, ["connection_id", "spend_date"])

    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in TABLES + CHECKED + UNCHECKED:
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
            + " OR "
            + " OR ".join(
                f"EXISTS (SELECT 1 FROM {table} WHERE provider = 'synthetic_meta_ads')"
                for table in CHECKED + UNCHECKED
            )
            + f" OR EXISTS (SELECT 1 FROM {CONNECTIONS} WHERE day_zone IS NOT NULL)"
            + f" OR EXISTS (SELECT 1 FROM {TRANSACTIONS} WHERE requested_account IS NOT NULL)"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove populated spend state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    op.execute(f"REVOKE UPDATE (day_zone) ON {CONNECTIONS} FROM tracking_app")
    for table in TABLES:
        op.drop_table(table)
    op.drop_column(TRANSACTIONS, "requested_account")
    op.drop_column(CONNECTIONS, "day_zone")
    for table in CHECKED:
        _replace_check(table, "valid_provider", OLD_PROVIDERS)
