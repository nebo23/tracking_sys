"""Connector coverage and provenance: account kind, record source run and adapter version

Revision ID: 0011_connector_coverage
Revises: 0010_connector_sync
Created: 2026-11-17

Specification 009-C (D-049 decisions D16, D17 and D20). A connection records the provider's
account kind, which decides the metrics it supports; the disconnect purge clears it with the
account reference. A provider record keeps the run that stored it and the adapter version that
read it. The record-to-run reference is a composite (agency_id, client_id, connection_id, id)
foreign key, so a record can only name a run of its own connection. tracking_app may update the
account kind and the two provenance columns. The downgrade refuses populated 009-C state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0011_connector_coverage"
down_revision: str | Sequence[str] | None = "0010_connector_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_GRANTS = (
    "GRANT UPDATE (account_kind) ON connector_connections TO tracking_app",
    "GRANT UPDATE (source_run_id, adapter_version) ON connector_records TO tracking_app",
)


def upgrade() -> None:
    op.add_column(
        "connector_connections", sa.Column("account_kind", sa.String(length=32), nullable=True)
    )
    op.create_unique_constraint(
        "uq_connector_sync_runs_scope",
        "connector_sync_runs",
        ["agency_id", "client_id", "connection_id", "id"],
    )
    op.add_column("connector_records", sa.Column("source_run_id", sa.Uuid(), nullable=True))
    op.add_column(
        "connector_records", sa.Column("adapter_version", sa.String(length=32), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_connector_records_agency_id_connector_sync_runs"),
        "connector_records",
        "connector_sync_runs",
        ["agency_id", "client_id", "connection_id", "source_run_id"],
        ["agency_id", "client_id", "connection_id", "id"],
    )
    for statement in RUNTIME_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(
        sa.text("LOCK TABLE connector_connections, connector_records IN ACCESS EXCLUSIVE MODE")
    )
    if connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM connector_connections WHERE account_kind IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM connector_records WHERE source_run_id IS NOT NULL "
            "OR adapter_version IS NOT NULL)"
        )
    ).scalar_one():
        raise RuntimeError("Refuse to remove populated connector state; use a forward fix.")
    op.drop_constraint(
        op.f("fk_connector_records_agency_id_connector_sync_runs"),
        "connector_records",
        type_="foreignkey",
    )
    op.drop_column("connector_records", "adapter_version")
    op.drop_column("connector_records", "source_run_id")
    op.drop_constraint("uq_connector_sync_runs_scope", "connector_sync_runs", type_="unique")
    op.drop_column("connector_connections", "account_kind")
