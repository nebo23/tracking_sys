"""Google identities, OAuth transactions, and numeric verification challenges

Revision ID: 0004_identity
Revises: 0003_auth
Created: 2026-11-04 17:06:26.279925
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0004_identity"
down_revision: str | Sequence[str] | None = "0003_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS_ACTIONS = (
    "action IN ('registered', 'email_verified', 'login_succeeded', 'login_failed', "
    "'logout', 'logout_all', 'password_changed', 'reset_requested', 'reset_completed')"
)
ACTIONS = (
    "action IN ('registered', 'email_verified', 'login_succeeded', 'login_failed', "
    "'logout', 'logout_all', 'password_changed', 'reset_requested', 'reset_completed', "
    "'google_login_succeeded', 'google_registered', 'google_identity_linked', "
    "'verification_code_failed')"
)
NEW_TABLES = ("external_identities", "oauth_transactions", "verification_challenges")


def upgrade() -> None:
    # D-022: additive identity/verification state with least-privilege runtime grants.
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider IN ('google')", name=op.f("ck_external_identities_valid_provider")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_external_identities_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_identities")),
        sa.UniqueConstraint("provider", "subject", name="uq_external_identities_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_external_identities_user_provider"),
    )
    op.create_table(
        "oauth_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=8), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("binding_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(purpose = 'login' AND user_id IS NULL) OR (purpose = 'link' AND user_id IS NOT NULL)",
            name=op.f("ck_oauth_transactions_link_has_user"),
        ),
        sa.CheckConstraint(
            "purpose IN ('login', 'link')", name=op.f("ck_oauth_transactions_valid_purpose")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_oauth_transactions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_transactions")),
        sa.UniqueConstraint("state_digest", name=op.f("uq_oauth_transactions_state_digest")),
    )
    op.create_table(
        "verification_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("verifier", sa.String(length=64), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('email_verification')",
            name=op.f("ck_verification_challenges_valid_purpose"),
        ),
        sa.CheckConstraint(
            "failed_attempts >= 0", name=op.f("ck_verification_challenges_nonnegative_attempts")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_verification_challenges_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_challenges")),
    )
    op.create_index(
        op.f("ix_verification_challenges_user_id"),
        "verification_challenges",
        ["user_id"],
        unique=False,
    )
    op.add_column("mail_outbox", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f("ck_security_events_valid_action"), "security_events", type_="check")
    op.create_check_constraint(op.f("ck_security_events_valid_action"), "security_events", ACTIONS)
    op.execute("GRANT SELECT, INSERT ON external_identities TO tracking_app")
    op.execute("GRANT UPDATE (last_login_at) ON external_identities TO tracking_app")
    op.execute("GRANT SELECT, INSERT ON oauth_transactions TO tracking_app")
    op.execute("GRANT UPDATE (consumed_at) ON oauth_transactions TO tracking_app")
    op.execute("GRANT SELECT, INSERT ON verification_challenges TO tracking_app")
    op.execute(
        "GRANT UPDATE (failed_attempts, consumed_at, invalidated_at) "
        "ON verification_challenges TO tracking_app"
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE "
            + ", ".join((*NEW_TABLES, "mail_outbox", "security_events"))
            + " IN ACCESS EXCLUSIVE MODE"
        )
    )
    for table in NEW_TABLES:
        if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar_one():
            raise RuntimeError("Refuse to remove non-empty identity state; use a forward fix.")
    if connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM mail_outbox WHERE expires_at IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM security_events WHERE NOT (" + PREVIOUS_ACTIONS + "))"
        )
    ).scalar_one():
        raise RuntimeError("Refuse to remove populated verification state; use a forward fix.")
    op.drop_constraint(op.f("ck_security_events_valid_action"), "security_events", type_="check")
    op.create_check_constraint(
        op.f("ck_security_events_valid_action"), "security_events", PREVIOUS_ACTIONS
    )
    op.drop_column("mail_outbox", "expires_at")
    op.drop_index(op.f("ix_verification_challenges_user_id"), table_name="verification_challenges")
    op.drop_table("verification_challenges")
    op.drop_table("oauth_transactions")
    op.drop_table("external_identities")
