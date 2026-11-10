"""Scoped invitations and service credentials; raw bearer tokens are never persisted."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.tenancy import Entity


# Reference queries below are manual read-only diagnostics for an authorized database operator.
# Replace the synthetic literals before use. Token and key digests are deliberately omitted.
# They are scoped by agency and do not implement application authorization.
#
# Email invitation to join one agency with a role; only the token digest is stored. Status moves
# from pending to accepted or revoked; expiry is checked when the token is used.
# SELECT id, agency_id, inviter_membership_id, email_normalized, role, status, expires_at,
#        accepted_by_user_id, created_at
# FROM public.agency_invitations
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND id = '00000000-0000-0000-0000-000000000007'::uuid;
# SELECT id, email_normalized, role, status, expires_at, created_at
# FROM public.agency_invitations
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid AND status = 'pending'
# ORDER BY created_at, id LIMIT 100;
class AgencyInvitation(Entity, Base):
    __tablename__ = "agency_invitations"
    __table_args__ = (
        UniqueConstraint("agency_id", "id", name="uq_invitations_agency_id"),
        ForeignKeyConstraint(
            ["agency_id", "inviter_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'analyst', 'client_viewer')", name="valid_role"
        ),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="valid_status"),
    )
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    inviter_membership_id: Mapped[UUID] = mapped_column(Uuid)
    email_normalized: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


# Client grants to apply when an invitation is accepted; composite keys keep one agency.
# SELECT agency_id, invitation_id, client_id, can_view_financials
# FROM public.invitation_client_grants
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND invitation_id = '00000000-0000-0000-0000-000000000007'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid;
# SELECT client_id, can_view_financials
# FROM public.invitation_client_grants
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND invitation_id = '00000000-0000-0000-0000-000000000007'::uuid
# ORDER BY client_id LIMIT 100;
class InvitationClientGrant(Base):
    __tablename__ = "invitation_client_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "invitation_id"],
            ["agency_invitations.agency_id", "agency_invitations.id"],
        ),
        ForeignKeyConstraint(
            ["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"]
        ),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    invitation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    client_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    can_view_financials: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


# Expiring service API key for one agency; only the key digest is stored. Its creator
# membership must remain an active manager for the key to work. kind is immutable: "read" keys
# (every key issued before 004) read granted clients; "ingest" keys (D-027) only write events
# and API consent for granted clients and can read nothing.
# SELECT id, agency_id, creator_membership_id, name, kind, status, expires_at, created_at
# FROM public.service_credentials
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND id = '00000000-0000-0000-0000-000000000008'::uuid;
# SELECT id, name, status, expires_at, created_at
# FROM public.service_credentials
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND status = 'active' AND expires_at > now()
# ORDER BY created_at, id LIMIT 100;
class ServiceCredential(Entity, Base):
    __tablename__ = "service_credentials"
    __table_args__ = (
        UniqueConstraint("agency_id", "id", name="uq_service_credentials_agency_id"),
        ForeignKeyConstraint(
            ["agency_id", "creator_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        CheckConstraint("status IN ('active', 'revoked')", name="valid_status"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("kind IN ('read', 'ingest')", name="valid_kind"),
    )
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    creator_membership_id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16), server_default="read")
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


# Explicit client read grant for a service credential, optionally including financial reads.
# SELECT agency_id, credential_id, client_id, can_view_financials
# FROM public.service_client_grants
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND credential_id = '00000000-0000-0000-0000-000000000008'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid;
# SELECT client_id, can_view_financials
# FROM public.service_client_grants
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND credential_id = '00000000-0000-0000-0000-000000000008'::uuid
# ORDER BY client_id LIMIT 100;
class ServiceClientGrant(Base):
    __tablename__ = "service_client_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "credential_id"],
            ["service_credentials.agency_id", "service_credentials.id"],
        ),
        ForeignKeyConstraint(
            ["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"]
        ),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    credential_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    client_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    can_view_financials: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
