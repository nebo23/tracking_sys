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
    )
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    creator_membership_id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(100))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


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
