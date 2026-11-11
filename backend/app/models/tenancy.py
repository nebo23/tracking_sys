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


# Reference queries below are manual read-only diagnostics for an authorized database operator
# (for example in pgAdmin). Replace the clearly synthetic literals before use. They do not
# implement application authorization; never paste real account values into shared logs.
#
# Reusable column mixin with no table of its own (there is no entities table): it adds a UUID
# primary key and server-side created/updated timestamps to the mapped classes that inherit it.
class Entity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Platform identity; one user may belong to several agencies. status = 'active' means
# administratively enabled, while email_verified_at separately records verified mailbox
# ownership. An active but unverified user is still denied password login. closed_at records a
# self-service closure (D-024): the email and name were replaced by pseudonyms and the account
# is permanently disabled; an administrator-disabled account keeps closed_at NULL.
# SELECT id, email_normalized, display_name, status, email_verified_at, closed_at, created_at
# FROM public.users
# WHERE id = '00000000-0000-0000-0000-000000000001'::uuid;
# SELECT id, email_normalized, display_name, status, email_verified_at, created_at
# FROM public.users
# WHERE email_normalized = 'synthetic.user@example.test'
# ORDER BY created_at, id LIMIT 1;
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
        CheckConstraint("closed_at IS NULL OR status = 'disabled'", name="closed_is_disabled"),
    )

    email_normalized: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Tenant boundary: an agency is active or suspended and owns its client workspaces.
# SELECT id, name, status, created_at, updated_at
# FROM public.agencies
# WHERE id = '00000000-0000-0000-0000-000000000002'::uuid;
# SELECT id, name, status, created_at
# FROM public.agencies
# WHERE status = 'active'
# ORDER BY created_at, id LIMIT 100;
class Agency(Entity, Base):
    __tablename__ = "agencies"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("status IN ('active', 'suspended')", name="valid_status"),
    )

    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


# A user's role and status within one agency; disabling it affects no other agency.
# SELECT id, agency_id, user_id, role, status, created_at, updated_at
# FROM public.agency_memberships
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND user_id = '00000000-0000-0000-0000-000000000001'::uuid;
# SELECT id, user_id, role, status, created_at
# FROM public.agency_memberships
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND role IN ('owner', 'admin') AND status = 'active'
# ORDER BY created_at, id LIMIT 100;
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


# Client workspace that belongs to exactly one agency; active or archived.
# SELECT id, agency_id, name, status, created_at, updated_at
# FROM public.client_workspaces
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND id = '00000000-0000-0000-0000-000000000003'::uuid;
# SELECT id, name, status, created_at
# FROM public.client_workspaces
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
# ORDER BY created_at, id LIMIT 100;
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


# Explicit client access for a restricted membership. Composite foreign keys keep the client
# and membership in the same agency; financial visibility defaults to false.
# SELECT agency_id, client_id, membership_id, can_view_financials
# FROM public.client_grants
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid
#   AND membership_id = '00000000-0000-0000-0000-000000000004'::uuid;
# SELECT client_id, membership_id, can_view_financials
# FROM public.client_grants
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND membership_id = '00000000-0000-0000-0000-000000000004'::uuid
# ORDER BY client_id LIMIT 100;
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


# Append-only record of successful sensitive tenant mutations: identifiers and action codes
# only, with no passwords, tokens, emails, or customer payloads. The runtime may only insert.
# SELECT id, agency_id, client_id, actor_user_id, action, resource_type, resource_id,
#        occurred_at
# FROM public.audit_events
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
# ORDER BY occurred_at DESC, id DESC LIMIT 100;
# SELECT id, client_id, action, resource_type, resource_id, occurred_at
# FROM public.audit_events
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND actor_user_id = '00000000-0000-0000-0000-000000000001'::uuid
#   AND occurred_at >= now() - interval '7 days'
# ORDER BY occurred_at DESC, id DESC LIMIT 100;
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
            "'credential.created', 'credential.revoked', 'source.created', 'source.updated', "
            "'source.secret_rotated', 'form.updated', 'deletion.requested', "
            "'campaign.created', 'campaign.updated', 'content.created', 'content.updated', "
            "'template.created', 'template.updated', 'origin.created', 'origin.updated', "
            "'domain.created', 'domain.updated', 'domain.challenge_issued', 'domain.checked', "
            "'link.created', 'link.updated')",
            name="valid_action",
        ),
        CheckConstraint(
            "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
            "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
            "'utm_template', 'destination_origin', 'domain', 'link')",
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
