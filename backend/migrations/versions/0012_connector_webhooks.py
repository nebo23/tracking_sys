"""Connector provider webhooks: verified delivery records

Revision ID: 0012_connector_webhooks
Revises: 0011_connector_coverage
Created: 2026-11-17

Specification 009-D (D-049 decisions D18, D19 and D20). Adds connector_webhook_deliveries, which
records each verified provider webhook delivery by provider and SHA-256 digest of its event ID,
with its receipt time and the number of connections notified, so a repeated delivery has no
further effect. It holds no payload, account, or tenant data and is therefore not
tenant-scoped. tracking_app may insert rows and update the notified count; tracking_lifecycle
deletes rows 7 days after receipt. The downgrade refuses populated 009-D state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0012_connector_webhooks"
down_revision: str | Sequence[str] | None = "0011_connector_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "connector_webhook_deliveries"


def _check(name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{TABLE}_{name}"))


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notified", sa.Integer(), server_default="0", nullable=False),
        _check("valid_provider", "provider IN ('synthetic')"),
        _check("event_digest", "event_digest ~ '^[0-9a-f]{64}$'"),
        _check("valid_notified", "notified >= 0"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint(
            "provider", "event_digest", name="uq_connector_webhook_deliveries_event"
        ),
    )
    op.create_index("ix_connector_webhook_deliveries_received", TABLE, ["received_at"])
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO tracking_app")
    op.execute(f"GRANT UPDATE (notified) ON {TABLE} TO tracking_app")
    op.execute(f"GRANT SELECT, DELETE ON {TABLE} TO tracking_lifecycle")


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {TABLE})")).scalar_one():
        raise RuntimeError("Refuse to remove populated connector state; use a forward fix.")
    op.execute(f"REVOKE SELECT, DELETE ON {TABLE} FROM tracking_lifecycle")
    op.drop_table(TABLE)
