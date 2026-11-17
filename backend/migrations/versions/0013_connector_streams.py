"""Connector streams, metric availability and provider data deletion requests

Revision ID: 0013_connector_streams
Revises: 0012_connector_webhooks
Created: 2026-11-17

Specification 010-A (D-053). Runs and records carry their stream, with one open run per
connection and stream, and records are unique per connection, stream and provider object.
Records add the media product type and the closed reason for each metric the provider did not
report. Connections accept the Instagram-shaped synthetic provider and the provider-initiated
reasons deauthorized and deletion_requested, and may reference the data deletion request that
started their disconnect. connector_deletion_requests keeps no account or tenant data.
tracking_app gains the column privileges these writes need; tracking_lifecycle may delete
records observed more than 730 days ago. The downgrade refuses populated 010-A state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0013_connector_streams"
down_revision: str | Sequence[str] | None = "0012_connector_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REQUESTS = "connector_deletion_requests"
OLD_PROVIDERS = "provider IN ('synthetic')"
NEW_PROVIDERS = "provider IN ('synthetic', 'synthetic_instagram')"
OLD_REASONS = (
    "status_reason IS NULL OR status_reason IN "
    "('credential_expired', 'provider_revoked', 'user_requested')"
)
NEW_REASONS = (
    "status_reason IS NULL OR status_reason IN "
    "('credential_expired', 'provider_revoked', 'user_requested', 'deauthorized', "
    "'deletion_requested')"
)
OPEN = "status IN ('queued', 'running')"
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {REQUESTS} TO tracking_app",
    f"GRANT UPDATE (connections, completed_at) ON {REQUESTS} TO tracking_app",
    "GRANT UPDATE (deletion_request_id) ON connector_connections TO tracking_app",
    "GRANT UPDATE (stream, product_type, unavailable) ON connector_records TO tracking_app",
)
LIFECYCLE_GRANT = "GRANT SELECT, DELETE ON connector_records TO tracking_lifecycle"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    op.create_table(
        REQUESTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("confirmation_code", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("connections", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(NEW_PROVIDERS, name=op.f(f"ck_{REQUESTS}_valid_provider")),
        sa.CheckConstraint(
            "confirmation_code ~ '^[A-Za-z0-9_-]{16,64}$'", name=op.f(f"ck_{REQUESTS}_valid_code")
        ),
        sa.CheckConstraint("connections >= 0", name=op.f(f"ck_{REQUESTS}_valid_connections")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{REQUESTS}")),
        sa.UniqueConstraint("confirmation_code", name=op.f(f"uq_{REQUESTS}_confirmation_code")),
    )

    table = "connector_connections"
    _replace_check(table, "valid_provider", NEW_PROVIDERS)
    _replace_check(table, "valid_reason", NEW_REASONS)
    op.add_column(table, sa.Column("deletion_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f(f"fk_{table}_deletion_request_id_{REQUESTS}"),
        table,
        REQUESTS,
        ["deletion_request_id"],
        ["id"],
    )

    table = "connector_sync_runs"
    op.add_column(
        table, sa.Column("stream", sa.String(length=32), server_default="objects", nullable=False)
    )
    op.drop_index("uq_connector_sync_runs_open", table_name=table)
    op.create_index(
        "uq_connector_sync_runs_open",
        table,
        ["connection_id", "stream"],
        unique=True,
        postgresql_where=sa.text(OPEN),
    )

    table = "connector_records"
    op.add_column(
        table, sa.Column("stream", sa.String(length=32), server_default="objects", nullable=False)
    )
    op.add_column(table, sa.Column("product_type", sa.String(length=16), nullable=True))
    op.add_column(
        table,
        sa.Column(
            "unavailable",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.drop_constraint("uq_connector_records_object", table, type_="unique")
    op.create_unique_constraint(
        "uq_connector_records_object", table, ["connection_id", "stream", "provider_object_id"]
    )
    op.create_check_constraint(
        op.f(f"ck_{table}_object_unavailable"), table, "jsonb_typeof(unavailable) = 'object'"
    )
    op.create_check_constraint(
        op.f(f"ck_{table}_bounded_unavailable"), table, "length(unavailable::text) <= 2048"
    )
    op.create_check_constraint(
        op.f(f"ck_{table}_valid_product_type"),
        table,
        "product_type IS NULL OR product_type IN ('FEED', 'REELS', 'STORY')",
    )
    op.create_index("ix_connector_records_observed", table, ["observed_at"])

    _replace_check("connector_webhook_deliveries", "valid_provider", NEW_PROVIDERS)

    for statement in RUNTIME_GRANTS:
        op.execute(statement)
    op.execute(LIFECYCLE_GRANT)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (
        REQUESTS,
        "connector_connections",
        "connector_sync_runs",
        "connector_records",
        "connector_webhook_deliveries",
    ):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    populated = connection.execute(
        sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {REQUESTS}) "
            "OR EXISTS (SELECT 1 FROM connector_connections WHERE provider <> 'synthetic' "
            "OR deletion_request_id IS NOT NULL "
            "OR status_reason IN ('deauthorized', 'deletion_requested')) "
            "OR EXISTS (SELECT 1 FROM connector_sync_runs WHERE stream <> 'objects') "
            "OR EXISTS (SELECT 1 FROM connector_records WHERE stream <> 'objects' "
            "OR product_type IS NOT NULL OR unavailable <> '{}'::jsonb) "
            "OR EXISTS (SELECT 1 FROM connector_webhook_deliveries WHERE provider <> 'synthetic')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove populated connector state; use a forward fix.")
    op.execute("REVOKE SELECT, DELETE ON connector_records FROM tracking_lifecycle")
    op.execute(
        "REVOKE UPDATE (stream, product_type, unavailable) ON connector_records FROM tracking_app"
    )
    op.execute("REVOKE UPDATE (deletion_request_id) ON connector_connections FROM tracking_app")

    _replace_check("connector_webhook_deliveries", "valid_provider", OLD_PROVIDERS)

    table = "connector_records"
    op.drop_index("ix_connector_records_observed", table_name=table)
    for name in ("valid_product_type", "bounded_unavailable", "object_unavailable"):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.drop_constraint("uq_connector_records_object", table, type_="unique")
    op.create_unique_constraint(
        "uq_connector_records_object", table, ["connection_id", "provider_object_id"]
    )
    for column in ("unavailable", "product_type", "stream"):
        op.drop_column(table, column)

    table = "connector_sync_runs"
    op.drop_index("uq_connector_sync_runs_open", table_name=table)
    op.create_index(
        "uq_connector_sync_runs_open",
        table,
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text(OPEN),
    )
    op.drop_column(table, "stream")

    table = "connector_connections"
    op.drop_constraint(
        op.f(f"fk_{table}_deletion_request_id_{REQUESTS}"), table, type_="foreignkey"
    )
    op.drop_column(table, "deletion_request_id")
    _replace_check(table, "valid_reason", OLD_REASONS)
    _replace_check(table, "valid_provider", OLD_PROVIDERS)

    op.drop_table(REQUESTS)
