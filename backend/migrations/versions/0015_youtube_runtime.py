"""YouTube-shaped connector runtime extensions

Revision ID: 0015_youtube_runtime
Revises: 0014_instagram_provider
Created: 2026-11-18

Specification 011-A (D-058, D-060; design in specs/011-youtube/design-011a.md). Connections,
webhook deliveries and data deletion requests accept the YouTube-shaped synthetic provider.
Connections add the reason authorization_lost, the shared revocation outcome, the start of the
reconnection grace period, the label refresh time, the grant expiry and the agent approval;
OAuth transactions carry the approval to the installation. Token versions add the shared
revocation outcome. Usage rows name their quota bucket and allow the confirm operation and the
budget_exhausted outcome of a provider quota answer. Records widen the product types and add
allow-listed attributes with their refresh time and the end of a lifetime total's provisional
period. tracking_app gains the column privileges these writes need; tracking_lifecycle may
clear attributes and labels not refreshed for 30 days and read the provider of a connection for
per-provider retention, but still cannot read labels or change metrics. The downgrade refuses
populated 011-A state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0015_youtube_runtime"
down_revision: str | Sequence[str] | None = "0014_instagram_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONNECTIONS = "connector_connections"
TRANSACTIONS = "connector_oauth_transactions"
SECRETS = "connector_token_secrets"
USAGE = "connector_usage_records"
RECORDS = "connector_records"
PROVIDER_TABLES = (CONNECTIONS, "connector_webhook_deliveries", "connector_deletion_requests")
OLD_PROVIDERS = "provider IN ('synthetic', 'synthetic_instagram', 'instagram')"
NEW_PROVIDERS = "provider IN ('synthetic', 'synthetic_instagram', 'instagram', 'synthetic_youtube')"
OLD_REASONS = (
    "status_reason IS NULL OR status_reason IN "
    "('credential_expired', 'provider_revoked', 'user_requested', 'deauthorized', "
    "'deletion_requested')"
)
NEW_REASONS = OLD_REASONS[:-1] + ", 'authorization_lost')"
OUTCOMES = (
    "(revocation_status IS NULL OR revocation_status IN ({values})) "
    "AND (destruction_status IS NULL OR destruction_status IN ('pending', 'done')) "
    "AND (purge_status IS NULL OR purge_status IN ('pending', 'done'))"
)
OLD_OUTCOMES = OUTCOMES.format(values="'pending', 'done', 'unsupported', 'failed'")
NEW_OUTCOMES = OUTCOMES.format(values="'pending', 'done', 'unsupported', 'failed', 'shared'")
OLD_REVOCATION = (
    "revocation IS NULL OR revocation IN ('done', 'unsupported', 'failed', 'not_required')"
)
NEW_REVOCATION = (
    "revocation IS NULL OR revocation IN "
    "('done', 'unsupported', 'failed', 'not_required', 'shared')"
)
OLD_OPERATIONS = "operation IN ('fetch', 'refresh')"
OUTCOME_VALUES = (
    "outcome IN ('reserved', 'ok', 'unauthorized', 'forbidden', 'rate_limited', "
    "'retryable', 'permanent'"
)
OLD_USAGE_OUTCOMES = OUTCOME_VALUES + ")"
NEW_USAGE_OUTCOMES = OUTCOME_VALUES + ", 'budget_exhausted')"
NEW_OPERATIONS = "operation IN ('fetch', 'refresh', 'confirm')"
OLD_PRODUCT_TYPES = "product_type IS NULL OR product_type IN ('FEED', 'REELS', 'STORY')"
NEW_PRODUCT_TYPES = (
    "product_type IS NULL OR product_type IN ('FEED', 'REELS', 'STORY', 'SHORTS', "
    "'VIDEO_ON_DEMAND', 'LIVE_STREAM', 'UNSPECIFIED')"
)
APPROVAL = "(agent_approved_at IS NULL) = (agent_disclosure IS NULL)"
CONNECTION_COLUMNS = (
    "reconnect_required_since",
    "account_label_refreshed_at",
    "grant_expires_at",
    "agent_approved_at",
)
RUNTIME_GRANTS = (
    f"GRANT UPDATE ({', '.join(CONNECTION_COLUMNS)}, agent_disclosure) "
    f"ON {CONNECTIONS} TO tracking_app",
    f"GRANT UPDATE (attributes, attributes_refreshed_at, provisional_until) "
    f"ON {RECORDS} TO tracking_app",
)
LIFECYCLE_GRANTS = (
    f"GRANT SELECT (id, provider, account_label_refreshed_at) ON {CONNECTIONS} "
    "TO tracking_lifecycle",
    f"GRANT UPDATE (account_label, account_label_refreshed_at) ON {CONNECTIONS} "
    "TO tracking_lifecycle",
    f"GRANT UPDATE (attributes, attributes_refreshed_at) ON {RECORDS} TO tracking_lifecycle",
)


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _time(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    for table in PROVIDER_TABLES:
        _replace_check(table, "valid_provider", NEW_PROVIDERS)
    _replace_check(CONNECTIONS, "valid_reason", NEW_REASONS)
    _replace_check(CONNECTIONS, "valid_outcomes", NEW_OUTCOMES)
    for name in CONNECTION_COLUMNS:
        op.add_column(CONNECTIONS, _time(name))
    op.add_column(CONNECTIONS, sa.Column("agent_disclosure", sa.String(length=64), nullable=True))
    # Connections already waiting for reconnection start their grace period at their last
    # change; providers without a grace period never act on it.
    op.execute(
        f"UPDATE {CONNECTIONS} SET reconnect_required_since = updated_at "
        "WHERE status = 'reconnect_required'"
    )
    op.create_check_constraint(
        op.f(f"ck_{CONNECTIONS}_reconnect_since"),
        CONNECTIONS,
        "(status = 'reconnect_required') = (reconnect_required_since IS NOT NULL)",
    )
    op.create_check_constraint(op.f(f"ck_{CONNECTIONS}_agent_approval"), CONNECTIONS, APPROVAL)

    op.add_column(TRANSACTIONS, _time("agent_approved_at"))
    op.add_column(TRANSACTIONS, sa.Column("agent_disclosure", sa.String(length=64), nullable=True))
    op.create_check_constraint(op.f(f"ck_{TRANSACTIONS}_agent_approval"), TRANSACTIONS, APPROVAL)

    _replace_check(SECRETS, "valid_revocation", NEW_REVOCATION)

    op.add_column(USAGE, sa.Column("bucket", sa.String(length=32), nullable=True))
    _replace_check(USAGE, "valid_operation", NEW_OPERATIONS)
    _replace_check(USAGE, "valid_outcome", NEW_USAGE_OUTCOMES)
    op.create_index(
        "ix_connector_usage_records_bucket_period", USAGE, ["provider", "bucket", "period"]
    )

    _replace_check(RECORDS, "valid_product_type", NEW_PRODUCT_TYPES)
    op.add_column(
        RECORDS,
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(RECORDS, _time("attributes_refreshed_at"))
    op.add_column(RECORDS, _time("provisional_until"))
    op.create_check_constraint(
        op.f(f"ck_{RECORDS}_object_attributes"), RECORDS, "jsonb_typeof(attributes) = 'object'"
    )
    op.create_check_constraint(
        op.f(f"ck_{RECORDS}_bounded_attributes"), RECORDS, "length(attributes::text) <= 1024"
    )
    op.create_check_constraint(
        op.f(f"ck_{RECORDS}_attributes_refreshed"),
        RECORDS,
        "attributes = '{}'::jsonb OR attributes_refreshed_at IS NOT NULL",
    )

    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    tables = PROVIDER_TABLES + (TRANSACTIONS, SECRETS, USAGE, RECORDS)
    for table in tables:
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(
                f"EXISTS (SELECT 1 FROM {table} WHERE provider = 'synthetic_youtube')"
                for table in PROVIDER_TABLES + (TRANSACTIONS, USAGE)
            )
            + f" OR EXISTS (SELECT 1 FROM {CONNECTIONS} WHERE revocation_status = 'shared' "
            "OR status_reason = 'authorization_lost' OR agent_approved_at IS NOT NULL "
            "OR account_label_refreshed_at IS NOT NULL OR grant_expires_at IS NOT NULL)"
            f" OR EXISTS (SELECT 1 FROM {TRANSACTIONS} WHERE agent_approved_at IS NOT NULL)"
            f" OR EXISTS (SELECT 1 FROM {SECRETS} WHERE revocation = 'shared')"
            f" OR EXISTS (SELECT 1 FROM {USAGE} WHERE bucket IS NOT NULL "
            "OR operation = 'confirm' OR outcome = 'budget_exhausted')"
            f" OR EXISTS (SELECT 1 FROM {RECORDS} WHERE attributes <> '{{}}'::jsonb "
            "OR provisional_until IS NOT NULL "
            "OR product_type NOT IN ('FEED', 'REELS', 'STORY'))"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove populated connector state; use a forward fix.")
    op.execute(
        f"REVOKE UPDATE (attributes, attributes_refreshed_at) ON {RECORDS} FROM tracking_lifecycle"
    )
    op.execute(
        f"REVOKE UPDATE (account_label, account_label_refreshed_at) ON {CONNECTIONS} "
        "FROM tracking_lifecycle"
    )
    op.execute(
        f"REVOKE SELECT (id, provider, account_label_refreshed_at) ON {CONNECTIONS} "
        "FROM tracking_lifecycle"
    )
    op.execute(
        f"REVOKE UPDATE (attributes, attributes_refreshed_at, provisional_until) "
        f"ON {RECORDS} FROM tracking_app"
    )
    op.execute(
        f"REVOKE UPDATE ({', '.join(CONNECTION_COLUMNS)}, agent_disclosure) "
        f"ON {CONNECTIONS} FROM tracking_app"
    )

    for name in ("attributes_refreshed", "bounded_attributes", "object_attributes"):
        op.drop_constraint(op.f(f"ck_{RECORDS}_{name}"), RECORDS, type_="check")
    for column in ("provisional_until", "attributes_refreshed_at", "attributes"):
        op.drop_column(RECORDS, column)
    _replace_check(RECORDS, "valid_product_type", OLD_PRODUCT_TYPES)

    op.drop_index("ix_connector_usage_records_bucket_period", table_name=USAGE)
    _replace_check(USAGE, "valid_outcome", OLD_USAGE_OUTCOMES)
    _replace_check(USAGE, "valid_operation", OLD_OPERATIONS)
    op.drop_column(USAGE, "bucket")

    _replace_check(SECRETS, "valid_revocation", OLD_REVOCATION)

    op.drop_constraint(op.f(f"ck_{TRANSACTIONS}_agent_approval"), TRANSACTIONS, type_="check")
    op.drop_column(TRANSACTIONS, "agent_disclosure")
    op.drop_column(TRANSACTIONS, "agent_approved_at")

    for name in ("agent_approval", "reconnect_since"):
        op.drop_constraint(op.f(f"ck_{CONNECTIONS}_{name}"), CONNECTIONS, type_="check")
    op.drop_column(CONNECTIONS, "agent_disclosure")
    for name in reversed(CONNECTION_COLUMNS):
        op.drop_column(CONNECTIONS, name)
    _replace_check(CONNECTIONS, "valid_outcomes", OLD_OUTCOMES)
    _replace_check(CONNECTIONS, "valid_reason", OLD_REASONS)
    for table in PROVIDER_TABLES:
        _replace_check(table, "valid_provider", OLD_PROVIDERS)
