"""Admit the live Instagram provider

Revision ID: 0014_instagram_provider
Revises: 0013_connector_streams
Created: 2026-11-17

Specification 010-C (D-055). Connections, webhook deliveries and data deletion requests accept
the live provider "instagram" next to the two synthetic providers. No table, column, index or
privilege changes. The downgrade refuses any connector state of the live provider.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0014_instagram_provider"
down_revision: str | Sequence[str] | None = "0013_connector_streams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKED = ("connector_connections", "connector_webhook_deliveries", "connector_deletion_requests")
# Tables that name a provider without a check constraint; the downgrade refuses their live rows
# too, because the previous revision's code does not know the provider.
UNCHECKED = ("connector_oauth_transactions", "connector_usage_records")
OLD_PROVIDERS = "provider IN ('synthetic', 'synthetic_instagram')"
NEW_PROVIDERS = "provider IN ('synthetic', 'synthetic_instagram', 'instagram')"


def _replace_check(table: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_valid_provider"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_valid_provider"), table, condition)


def upgrade() -> None:
    for table in CHECKED:
        _replace_check(table, NEW_PROVIDERS)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    tables = CHECKED + UNCHECKED
    for table in tables:
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(
                f"EXISTS (SELECT 1 FROM {table} WHERE provider = 'instagram')" for table in tables
            )
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove live Instagram connector state; use a forward fix.")
    for table in CHECKED:
        _replace_check(table, OLD_PROVIDERS)
