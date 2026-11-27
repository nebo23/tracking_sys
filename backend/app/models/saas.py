"""SaaS plans, plan assignments, agency closures and agreement records (017-A, D-092).

A plan is immutable data created by the platform operator: an internal key and name and five
limits, each nullable for unlimited; only its default flag changes, and exactly one plan is
the default. Assignments are an insert-only history per agency whose highest revision is the
current plan. A closure is one Owner request with a 30-day grace period; only its cancellation
and completion columns change, and at most one closure of an agency is open. An agreement row
records that an account agreed to one version of the Terms of Service or the Privacy Policy.

Rows hold identifiers, closed codes, numbers and times only: no agency or person name, email,
password, token or secret. Reference queries below are manual read-only diagnostics for an
authorized operator; replace the synthetic literals before use.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

LIMIT_COLUMNS = (
    "clients_limit",
    "seats_limit",
    "connections_limit",
    "managed_links_limit",
    "tracked_events_limit",
)
OPEN_CLOSURE = "cancelled_at IS NULL AND completed_at IS NULL"


# One plan (D2, D3). The migration seeds the development plan as the default.
# SELECT id, key, name, clients_limit, seats_limit, connections_limit, managed_links_limit,
#        tracked_events_limit, is_default, reason, created_at
# FROM public.saas_plans ORDER BY created_at, id;
class SaasPlan(Base):
    __tablename__ = "saas_plans"
    __table_args__ = (
        UniqueConstraint("key", name="uq_saas_plans_key"),
        Index(
            "uq_saas_plans_default", "is_default", unique=True, postgresql_where=text("is_default")
        ),
        CheckConstraint("key ~ '^[a-z][a-z0-9_-]{1,31}$'", name="valid_key"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            " AND ".join(f"({name} IS NULL OR {name} >= 0)" for name in LIMIT_COLUMNS),
            name="limits",
        ),
        CheckConstraint(
            "reason IN ('seed', 'new_offer', 'replacement', 'individual')", name="valid_reason"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100))
    clients_limit: Mapped[int | None] = mapped_column(Integer)
    seats_limit: Mapped[int | None] = mapped_column(Integer)
    connections_limit: Mapped[int | None] = mapped_column(Integer)
    managed_links_limit: Mapped[int | None] = mapped_column(Integer)
    # The monthly tracked-event allowance (D5): soft, it never refuses an event.
    tracked_events_limit: Mapped[int | None] = mapped_column(BigInteger)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    reason: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# One plan assignment of an agency; the highest revision is the current plan (D3, D7).
# SELECT revision, plan_id, assigned_at, assigned_by, reason
# FROM public.agency_plan_assignments
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid ORDER BY revision DESC;
class AgencyPlanAssignment(Base):
    __tablename__ = "agency_plan_assignments"
    __table_args__ = (
        UniqueConstraint("agency_id", "revision", name="uq_agency_plan_assignments_revision"),
        Index("ix_agency_plan_assignments_plan_id", "plan_id"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "assigned_by IN ('default', 'platform_operator')", name="valid_assigned_by"
        ),
        CheckConstraint(
            "reason IN ('initial', 'new_agency', 'plan_change', 'correction')", name="valid_reason"
        ),
        CheckConstraint(
            "(assigned_by = 'default') = (reason IN ('initial', 'new_agency'))",
            name="reason_matches",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("saas_plans.id"))
    revision: Mapped[int] = mapped_column(Integer)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    assigned_by: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(20))


# One closure request of an agency (D8). The lifecycle runner completes it at closes_at.
# SELECT id, requested_by_membership_id, requested_at, closes_at, cancelled_at,
#        cancelled_by_membership_id, completed_at
# FROM public.agency_closures
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid ORDER BY requested_at DESC;
class AgencyClosure(Base):
    __tablename__ = "agency_closures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "requested_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name="fk_agency_closures_requested_by_agency_memberships",
        ),
        ForeignKeyConstraint(
            ["agency_id", "cancelled_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name="fk_agency_closures_cancelled_by_agency_memberships",
        ),
        Index(
            "uq_agency_closures_open",
            "agency_id",
            unique=True,
            postgresql_where=text(OPEN_CLOSURE),
        ),
        Index("ix_agency_closures_due", "closes_at", postgresql_where=text(OPEN_CLOSURE)),
        CheckConstraint("closes_at > requested_at", name="grace_period"),
        CheckConstraint(
            "(cancelled_at IS NULL) = (cancelled_by_membership_id IS NULL) "
            "AND (cancelled_at IS NULL "
            "OR (cancelled_at >= requested_at AND cancelled_at < closes_at))",
            name="cancellation",
        ),
        CheckConstraint("completed_at IS NULL OR completed_at >= closes_at", name="completion"),
        CheckConstraint("cancelled_at IS NULL OR completed_at IS NULL", name="one_outcome"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    requested_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_membership_id: Mapped[UUID | None] = mapped_column(Uuid)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# One account's agreement to one version of a document (D10, 018 D15).
# SELECT document, version, accepted_at, channel
# FROM public.user_agreements
# WHERE user_id = '00000000-0000-0000-0000-000000000001'::uuid ORDER BY accepted_at, id;
class UserAgreement(Base):
    __tablename__ = "user_agreements"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "document", "version", name="uq_user_agreements_user_document_version"
        ),
        CheckConstraint("document IN ('terms', 'privacy')", name="valid_document"),
        CheckConstraint("version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$'", name="valid_version"),
        CheckConstraint(
            "channel IN ('registration', 'password_sign_in', 'google_sign_in')",
            name="valid_channel",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    document: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    channel: Mapped[str] = mapped_column(String(20))
