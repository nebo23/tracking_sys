"""Admit the live YouTube provider

Revision ID: 0016_youtube_provider
Revises: 0015_youtube_runtime
Created: 2026-11-18

Specification 011-C (D-060). Connections, webhook deliveries and data deletion requests accept
the live provider "youtube" next to the synthetic ones, and connections accept the reason
operator_purged for the operator purge that a loss of API access requires (entry review
section 4.2). No table, column, index or privilege changes. The downgrade refuses any connector
state of the live provider and any operator-purged connection.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0016_youtube_provider"
down_revision: str | Sequence[str] | None = "0015_youtube_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKED = ("connector_connections", "connector_webhook_deliveries", "connector_deletion_requests")
# Tables that name a provider without a check constraint; the downgrade refuses their live rows
# too, because the previous revision's code does not know the provider.
UNCHECKED = ("connector_oauth_transactions", "connector_usage_records")
OLD_PROVIDERS = "provider IN ('synthetic', 'synthetic_instagram', 'instagram', 'synthetic_youtube')"
NEW_PROVIDERS = (
    "provider IN ('synthetic', 'synthetic_instagram', 'instagram', 'synthetic_youtube', 'youtube')"
)
REASONS = (
    "status_reason IS NULL OR status_reason IN "
    "('credential_expired', 'provider_revoked', 'user_requested', 'deauthorized', "
    "'deletion_requested', 'authorization_lost'"
)
OLD_REASONS = REASONS + ")"
NEW_REASONS = REASONS + ", 'operator_purged')"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    for table in CHECKED:
        _replace_check(table, "valid_provider", NEW_PROVIDERS)
    _replace_check("connector_connections", "valid_reason", NEW_REASONS)


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
                f"EXISTS (SELECT 1 FROM {table} WHERE provider = 'youtube')" for table in tables
            )
            + " OR EXISTS (SELECT 1 FROM connector_connections "
            "WHERE status_reason = 'operator_purged')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove live YouTube connector state; use a forward fix.")
    _replace_check("connector_connections", "valid_reason", OLD_REASONS)
    for table in CHECKED:
        _replace_check(table, "valid_provider", OLD_PROVIDERS)
