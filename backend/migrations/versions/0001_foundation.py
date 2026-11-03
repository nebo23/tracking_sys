"""Establish the migration baseline without creating business tables."""

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic owns its version table; the runtime role may inspect but not change it.
    op.execute("GRANT SELECT ON TABLE alembic_version TO tracking_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON TABLE alembic_version FROM tracking_app")
