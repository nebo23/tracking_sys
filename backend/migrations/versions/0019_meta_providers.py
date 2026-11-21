"""Admit the live Meta advertising providers

Revision ID: 0019_meta_providers
Revises: 0018_conversion_delivery
Created: 2026-11-21

Specification 014-D (D-064 decisions D12 and D14). Connections, webhook deliveries and data
deletion requests accept the live providers "meta_ads" (spend connections) and "meta_capi"
(delivery connections) next to the synthetic ones. No table, column, index or privilege
changes. The downgrade refuses any connector state of either live provider.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0019_meta_providers"
down_revision: str | Sequence[str] | None = "0018_conversion_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKED = ("connector_connections", "connector_webhook_deliveries", "connector_deletion_requests")
# Tables that name a provider without a check constraint; the downgrade refuses their live rows
# too, because the previous revision's code does not know the providers.
UNCHECKED = ("connector_oauth_transactions", "connector_usage_records")
PROVIDERS = (
    "provider IN ('synthetic', 'synthetic_instagram', 'instagram', 'synthetic_youtube', "
    "'youtube', 'synthetic_meta_ads', 'synthetic_meta_capi'"
)
OLD_PROVIDERS = PROVIDERS + ")"
NEW_PROVIDERS = PROVIDERS + ", 'meta_ads', 'meta_capi')"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    for table in CHECKED:
        _replace_check(table, "valid_provider", NEW_PROVIDERS)


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
                f"EXISTS (SELECT 1 FROM {table} WHERE provider IN ('meta_ads', 'meta_capi'))"
                for table in tables
            )
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove live Meta connector state; use a forward fix.")
    for table in CHECKED:
        _replace_check(table, "valid_provider", OLD_PROVIDERS)
