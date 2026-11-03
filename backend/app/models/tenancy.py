"""Tenant relationships and explicit agency/client authorization boundaries."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Entity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Entity, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email_normalized"),
        CheckConstraint(
            "email_normalized = lower(btrim(email_normalized)) AND length(email_normalized) > 0",
            name="normalized_email",
        ),
        CheckConstraint("length(btrim(display_name)) > 0", name="display_name_not_blank"),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
    )

    email_normalized: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Agency(Entity, Base):
    __tablename__ = "agencies"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("status IN ('active', 'suspended')", name="valid_status"),
    )

    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


class AgencyMembership(Entity, Base):
    __tablename__ = "agency_memberships"
    __table_args__ = (
        UniqueConstraint("agency_id", "user_id", name="uq_memberships_agency_user"),
        UniqueConstraint("agency_id", "id", name="uq_memberships_agency_id"),
        CheckConstraint(
            "role IN ('owner', 'admin', 'analyst', 'client_viewer')", name="valid_role"
        ),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
        Index("ix_agency_memberships_user_id", "user_id"),
    )

    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


class ClientWorkspace(Entity, Base):
    __tablename__ = "client_workspaces"
    __table_args__ = (
        UniqueConstraint("agency_id", "id"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("status IN ('active', 'archived')", name="valid_status"),
    )

    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


class ClientGrant(Base):
    __tablename__ = "client_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["agency_id", "membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        Index("ix_client_grants_agency_membership", "agency_id", "membership_id"),
    )

    agency_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    client_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    membership_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    can_view_financials: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["agency_id", "actor_user_id"],
            ["agency_memberships.agency_id", "agency_memberships.user_id"],
        ),
        CheckConstraint(
            "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
            "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
            "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
            "'credential.created', 'credential.revoked')",
            name="valid_action",
        ),
        CheckConstraint(
            "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential')",
            name="valid_resource",
        ),
        Index("ix_audit_events_agency_time", "agency_id", "occurred_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    client_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))
    resource_type: Mapped[str] = mapped_column(String(20))
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
