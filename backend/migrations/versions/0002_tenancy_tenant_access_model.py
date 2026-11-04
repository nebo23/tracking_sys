"""Tenant access model

Revision ID: 0002_tenancy
Revises: 0001_foundation
Created: 2026-10-29 23:58:27.705400
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002_tenancy"
down_revision: str | Sequence[str] | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive schema approved in D-017; reviewed composite keys preserve tenant relationships.
    op.create_table(
        "agencies",
        sa.Column("name", sa.String(length=200), nullable=False),
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
            "status IN ('active', 'suspended')", name=op.f("ck_agencies_valid_status")
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name=op.f("ck_agencies_name_not_blank")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agencies")),
    )
    op.create_table(
        "users",
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
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
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_users_valid_status")),
        sa.CheckConstraint(
            "email_normalized = lower(btrim(email_normalized)) AND length(email_normalized) > 0",
            name=op.f("ck_users_normalized_email"),
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0", name=op.f("ck_users_display_name_not_blank")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email_normalized", name=op.f("uq_users_email_normalized")),
    )
    op.create_table(
        "agency_memberships",
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
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
            "role IN ('owner', 'admin', 'analyst', 'client_viewer')",
            name=op.f("ck_agency_memberships_valid_role"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')", name=op.f("ck_agency_memberships_valid_status")
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f("fk_agency_memberships_agency_id_agencies")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agency_memberships_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agency_memberships")),
        sa.UniqueConstraint("agency_id", "id", name="uq_memberships_agency_id"),
        sa.UniqueConstraint("agency_id", "user_id", name="uq_memberships_agency_user"),
    )
    op.create_index(
        "ix_agency_memberships_user_id", "agency_memberships", ["user_id"], unique=False
    )
    op.create_table(
        "client_workspaces",
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
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
            "status IN ('active', 'archived')", name=op.f("ck_client_workspaces_valid_status")
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0", name=op.f("ck_client_workspaces_name_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f("fk_client_workspaces_agency_id_agencies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_workspaces")),
        sa.UniqueConstraint("agency_id", "id", name=op.f("uq_client_workspaces_agency_id")),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=20), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
            "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
            "'grant.revoked')",
            name=op.f("ck_audit_events_valid_action"),
        ),
        sa.CheckConstraint(
            "resource_type IN ('agency', 'client', 'membership')",
            name=op.f("ck_audit_events_valid_resource"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_audit_events_actor_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "actor_user_id"],
            ["agency_memberships.agency_id", "agency_memberships.user_id"],
            name=op.f("fk_audit_events_agency_id_agency_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name=op.f("fk_audit_events_agency_id_client_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f("fk_audit_events_agency_id_agencies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_agency_time",
        "audit_events",
        ["agency_id", "occurred_at", "id"],
        unique=False,
    )
    op.create_table(
        "client_grants",
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "can_view_financials", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name=op.f("fk_client_grants_agency_id_client_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f("fk_client_grants_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint(
            "agency_id", "client_id", "membership_id", name=op.f("pk_client_grants")
        ),
    )
    op.create_index(
        "ix_client_grants_agency_membership",
        "client_grants",
        ["agency_id", "membership_id"],
        unique=False,
    )
    op.execute("GRANT SELECT ON users TO tracking_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON agencies, agency_memberships, "
        "client_workspaces TO tracking_app"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON client_grants TO tracking_app")
    op.execute("GRANT SELECT, INSERT ON audit_events TO tracking_app")


def downgrade() -> None:
    # A rollback must never erase identities, tenants, grants, or audit history.
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-table check.")
    connection = op.get_bind()
    # Keep the emptiness check and DROP atomic against concurrent writers.
    connection.execute(
        sa.text(
            "LOCK TABLE audit_events, client_grants, agency_memberships, "
            "client_workspaces, users, agencies IN ACCESS EXCLUSIVE MODE"
        )
    )
    for table in (
        "audit_events",
        "client_grants",
        "agency_memberships",
        "client_workspaces",
        "users",
        "agencies",
    ):
        if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar_one():
            raise RuntimeError(
                "Refuse to drop non-empty tenancy tables; use a reviewed forward fix."
            )
    op.drop_index("ix_client_grants_agency_membership", table_name="client_grants")
    op.drop_table("client_grants")
    op.drop_index("ix_audit_events_agency_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("client_workspaces")
    op.drop_index("ix_agency_memberships_user_id", table_name="agency_memberships")
    op.drop_table("agency_memberships")
    op.drop_table("users")
    op.drop_table("agencies")
