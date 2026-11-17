"""Connector synchronization: run kinds and deferral, checkpoints, usage records

Revision ID: 0010_connector_sync
Revises: 0009_connector_runtime
Created: 2026-11-17

Specification 009-B (D-049 decisions D11-D15 and D20). Sync runs gain a kind (incremental or
backfill), a window, a not-before time for deferrals, a retry count, and a page count. Two
client-scoped tables are added: one checkpoint per connection and stream, holding the opaque
cursor of the next page and the coverage watermarks, and one usage record per provider data
call. Both reference their connection through the composite (agency_id, client_id, id) key.
tracking_app may insert checkpoints and usage records, update a checkpoint's position and
watermarks, settle a usage record's outcome, and delete checkpoints for the disconnect purge.
It cannot delete usage records, which hold no provider data and follow the pending run-history
retention (Q-012). The downgrade refuses populated 009-B state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0010_connector_sync"
down_revision: str | Sequence[str] | None = "0009_connector_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONNECTION = [
    "connector_connections.agency_id",
    "connector_connections.client_id",
    "connector_connections.id",
]
TABLES = ("connector_usage_records", "connector_checkpoints")
RUN_COLUMNS = ("kind", "window_since", "window_until", "not_before", "retries", "pages")
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    "GRANT UPDATE (run_id, cursor, covered_from, complete_through, updated_at) "
    "ON connector_checkpoints TO tracking_app",
    "GRANT DELETE ON connector_checkpoints TO tracking_app",
    "GRANT UPDATE (outcome, settled_at) ON connector_usage_records TO tracking_app",
    "GRANT UPDATE (window_since, window_until, not_before, retries, pages) "
    "ON connector_sync_runs TO tracking_app",
)


def _time(name: str, *, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
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
        ["run_id"], ["connector_sync_runs.id"], name=op.f(f"fk_{table}_run_id_connector_sync_runs")
    )


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def upgrade() -> None:
    table = "connector_sync_runs"
    op.add_column(
        table,
        sa.Column("kind", sa.String(length=16), server_default="incremental", nullable=False),
    )
    op.add_column(table, _time("window_since"))
    op.add_column(table, _time("window_until"))
    op.add_column(table, _time("not_before"))
    op.add_column(table, sa.Column("retries", sa.Integer(), server_default="0", nullable=False))
    op.add_column(table, sa.Column("pages", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint(
        op.f("ck_connector_sync_runs_valid_kind"), table, "kind IN ('incremental', 'backfill')"
    )
    op.create_check_constraint(
        op.f("ck_connector_sync_runs_valid_progress"), table, "retries >= 0 AND pages >= 0"
    )
    op.create_check_constraint(
        op.f("ck_connector_sync_runs_valid_window"),
        table,
        "window_since IS NULL OR window_until IS NULL OR window_since < window_until",
    )

    table = "connector_checkpoints"
    op.create_table(
        table,
        *_scope(),
        sa.Column("stream", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        _time("covered_from"),
        _time("complete_through"),
        _time("updated_at", nullable=False, default=True),
        _check(table, "bounded_cursor", "length(cursor) <= 512"),
        _check(
            table,
            "valid_coverage",
            "covered_from IS NULL OR complete_through IS NULL OR covered_from <= complete_through",
        ),
        _connection(table),
        _run(table),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_checkpoints")),
        sa.UniqueConstraint("connection_id", "stream", name="uq_connector_checkpoints_stream"),
    )

    table = "connector_usage_records"
    op.create_table(
        table,
        *_scope(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=16), server_default="reserved", nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        _time("occurred_at", nullable=False, default=True),
        _time("settled_at"),
        _check(table, "valid_operation", "operation IN ('fetch', 'refresh')"),
        _check(
            table,
            "valid_outcome",
            "outcome IN ('reserved', 'ok', 'unauthorized', 'forbidden', 'rate_limited', "
            "'retryable', 'permanent')",
        ),
        _check(table, "valid_quantity", "quantity > 0 AND attempt >= 1"),
        _connection(table),
        _run(table),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_usage_records")),
    )
    op.create_index(
        "ix_connector_usage_records_connection_period", table, ["connection_id", "period"]
    )
    op.create_index("ix_connector_usage_records_provider_period", table, ["provider", "period"])
    for statement in RUNTIME_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(
        sa.text(f"LOCK TABLE {', '.join(TABLES)}, connector_sync_runs IN ACCESS EXCLUSIVE MODE")
    )
    populated = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
    if connection.execute(
        sa.text(
            f"SELECT {populated} OR EXISTS (SELECT 1 FROM connector_sync_runs "
            "WHERE kind <> 'incremental' OR pages > 0 OR retries > 0)"
        )
    ).scalar_one():
        raise RuntimeError("Refuse to remove populated connector state; use a forward fix.")
    for table in TABLES:
        op.drop_table(table)
    for name in ("valid_window", "valid_progress", "valid_kind"):
        op.drop_constraint(op.f(f"ck_connector_sync_runs_{name}"), "connector_sync_runs", "check")
    for column in reversed(RUN_COLUMNS):
        op.drop_column("connector_sync_runs", column)
