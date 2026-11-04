"""Authentication invitations and service credentials

Revision ID: 0003_auth
Revises: 0002_tenancy
Created: 2026-10-30 01:35:37.472685
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0003_auth"
down_revision: str | Sequence[str] | None = "0002_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # D-019: additive auth state with restricted runtime privileges.
    op.create_table(
        "auth_rate_limits",
        sa.Column("bucket_key", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_auth_rate_limits_nonnegative_attempts")),
        sa.PrimaryKeyConstraint("bucket_key", name=op.f("pk_auth_rate_limits")),
    )
    op.create_table(
        "mail_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=True),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('verify', 'reset', 'invitation')",
            name=op.f("ck_mail_outbox_valid_purpose"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_mail_outbox_nonnegative_attempts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_outbox")),
    )
    op.create_index(
        op.f("ix_mail_outbox_next_attempt_at"), "mail_outbox", ["next_attempt_at"], unique=False
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_auth_sessions_token_digest")),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('verify', 'reset')", name=op.f("ck_auth_tokens_valid_purpose")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_tokens_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_auth_tokens_token_digest")),
    )
    op.create_index(op.f("ix_auth_tokens_user_id"), "auth_tokens", ["user_id"], unique=False)
    op.create_table(
        "password_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_password_credentials_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_password_credentials")),
    )
    op.create_table(
        "security_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('registered', 'email_verified', 'login_succeeded', 'login_failed', "
            "'logout', 'logout_all', 'password_changed', 'reset_requested', 'reset_completed')",
            name=op.f("ck_security_events_valid_action"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_security_events_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
    )
    op.create_index(
        op.f("ix_security_events_user_id"), "security_events", ["user_id"], unique=False
    )
    op.create_table(
        "agency_invitations",
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("inviter_membership_id", sa.Uuid(), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'analyst', 'client_viewer')",
            name=op.f("ck_agency_invitations_valid_role"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked')",
            name=op.f("ck_agency_invitations_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            name=op.f("fk_agency_invitations_accepted_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "inviter_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f("fk_agency_invitations_agency_id_agency_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f("fk_agency_invitations_agency_id_agencies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agency_invitations")),
        sa.UniqueConstraint("agency_id", "id", name="uq_invitations_agency_id"),
        sa.UniqueConstraint("token_digest", name=op.f("uq_agency_invitations_token_digest")),
    )
    op.create_table(
        "service_credentials",
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("creator_membership_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')", name=op.f("ck_service_credentials_valid_status")
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0", name=op.f("ck_service_credentials_name_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "creator_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f("fk_service_credentials_agency_id_agency_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f("fk_service_credentials_agency_id_agencies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_credentials")),
        sa.UniqueConstraint("agency_id", "id", name="uq_service_credentials_agency_id"),
        sa.UniqueConstraint("token_digest", name=op.f("uq_service_credentials_token_digest")),
    )
    op.create_table(
        "invitation_client_grants",
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column(
            "can_view_financials", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name=op.f("fk_invitation_client_grants_agency_id_client_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "invitation_id"],
            ["agency_invitations.agency_id", "agency_invitations.id"],
            name=op.f("fk_invitation_client_grants_agency_id_agency_invitations"),
        ),
        sa.PrimaryKeyConstraint(
            "agency_id", "invitation_id", "client_id", name=op.f("pk_invitation_client_grants")
        ),
    )
    op.create_table(
        "service_client_grants",
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column(
            "can_view_financials", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name=op.f("fk_service_client_grants_agency_id_client_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "credential_id"],
            ["service_credentials.agency_id", "service_credentials.id"],
            name=op.f("fk_service_client_grants_agency_id_service_credentials"),
        ),
        sa.PrimaryKeyConstraint(
            "agency_id", "credential_id", "client_id", name=op.f("pk_service_client_grants")
        ),
    )
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_constraint(op.f("ck_audit_events_valid_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_action"),
        "audit_events",
        "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
        "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
        "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
        "'credential.created', 'credential.revoked')",
    )
    op.drop_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_resource"),
        "audit_events",
        "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential')",
    )
    op.execute("GRANT INSERT ON users TO tracking_app")
    op.execute("GRANT UPDATE (email_verified_at, updated_at) ON users TO tracking_app")
    op.execute("GRANT SELECT, INSERT ON security_events TO tracking_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON password_credentials, auth_sessions, auth_tokens, "
        "auth_rate_limits, mail_outbox, agency_invitations, service_credentials TO tracking_app"
    )
    op.execute(
        "GRANT SELECT, INSERT ON invitation_client_grants, service_client_grants TO tracking_app"
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    tables = (
        "service_client_grants",
        "invitation_client_grants",
        "service_credentials",
        "agency_invitations",
        "security_events",
        "password_credentials",
        "auth_tokens",
        "auth_sessions",
        "mail_outbox",
        "auth_rate_limits",
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE "
            + ", ".join((*tables, "users", "audit_events"))
            + " IN ACCESS EXCLUSIVE MODE"
        )
    )
    for table in tables:
        if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar_one():
            raise RuntimeError(
                "Refuse to remove non-empty authentication state; use a forward fix."
            )
    if connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM users WHERE email_verified_at IS NOT NULL)")
    ).scalar_one():
        raise RuntimeError("Refuse to remove non-empty verification state; use a forward fix.")
    if connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM audit_events "
            "WHERE resource_type IN ('invitation', 'credential'))"
        )
    ).scalar_one():
        raise RuntimeError("Refuse to remove non-empty auth audit state; use a forward fix.")
    op.execute("REVOKE INSERT ON users FROM tracking_app")
    op.execute("REVOKE UPDATE (email_verified_at, updated_at) ON users FROM tracking_app")
    op.drop_constraint(op.f("ck_audit_events_valid_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_action"),
        "audit_events",
        "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
        "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
        "'grant.revoked')",
    )
    op.drop_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_resource"),
        "audit_events",
        "resource_type IN ('agency', 'client', 'membership')",
    )
    op.drop_column("users", "email_verified_at")
    op.drop_table("service_client_grants")
    op.drop_table("invitation_client_grants")
    op.drop_table("service_credentials")
    op.drop_table("agency_invitations")
    op.drop_index(op.f("ix_security_events_user_id"), table_name="security_events")
    op.drop_table("security_events")
    op.drop_table("password_credentials")
    op.drop_index(op.f("ix_auth_tokens_user_id"), table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_mail_outbox_next_attempt_at"), table_name="mail_outbox")
    op.drop_table("mail_outbox")
    op.drop_table("auth_rate_limits")
