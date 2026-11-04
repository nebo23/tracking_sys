"""Lifecycle role grants for ended credential state

Revision ID: 0005_lifecycle
Revises: 0004_identity
Created: 2026-11-04

Specification 003-A3 (D-024 decisions 2 and 4). The dedicated tracking_lifecycle login role
is created outside migrations, like the runtime and migrator roles (infra/postgres and the
Docker initialization script). This revision grants it SELECT and DELETE on the six tables
whose ended rows the lifecycle runner removes. It changes no table, no data, and no
tracking_app privilege; audit and security events stay out of the role's reach.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0005_lifecycle"
down_revision: str | Sequence[str] | None = "0004_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "tracking_lifecycle"
TABLES = (
    "auth_sessions",
    "auth_tokens",
    "verification_challenges",
    "oauth_transactions",
    "auth_rate_limits",
    "mail_outbox",
)


def upgrade() -> None:
    if not context.is_offline_mode():
        exists = (
            op.get_bind()
            .execute(
                sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
                {"role": ROLE},
            )
            .scalar_one()
        )
        if not exists:
            raise RuntimeError(
                "Create the tracking_lifecycle role first; see infra/postgres/lifecycle-role.sql."
            )
    op.execute(f"GRANT SELECT, DELETE ON {', '.join(TABLES)} TO {ROLE}")


def downgrade() -> None:
    # Revoking grants removes no data.
    op.execute(f"REVOKE SELECT, DELETE ON {', '.join(TABLES)} FROM {ROLE}")
