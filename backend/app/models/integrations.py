"""Integration sources, deliveries and bookings (specification 015-D, D-068 E2 to E5, E9, E10).

An integration source belongs to one client: a Cal.com source verifies Cal.com's signature with
the secret the client set in Cal.com, and a signed webhook source verifies the 004 signature with
a secret the platform issued. Both secrets are sealed under the D-025 keyring. Each verified
delivery leaves one row in integration_deliveries (a digest of the body, its receipt time and a
closed outcome), which also makes a repeated delivery a no-op; tracking_lifecycle deletes them
after 30 days. A booking is one chain of provider booking IDs: a reschedule adds an ID to the
chain, and the booking's state is derived from its minimal events, so every delivery order gives
the same result. A booking is never revenue. It references a 004 collection subject only through
identifier evidence with attribution consent (E4); erasing the subject clears the reference. No
table holds a name, email, phone, answer, note, meeting link or token (E3). tracking_lifecycle
deletes bookings 395 days after their last update (E9). Reference queries below are manual
read-only diagnostics for an authorized operator; replace the synthetic literals before use.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])
SOURCE_FK = (
    ["agency_id", "client_id", "source_id"],
    [
        "integration_sources.agency_id",
        "integration_sources.client_id",
        "integration_sources.id",
    ],
)
KINDS = ("cal_com", "signed_webhook")
PUBLIC_KEY = "^isk_[A-Za-z0-9_-]{43}$"
DELIVERY_OUTCOMES = ("applied", "duplicate", "ignored", "invalid")
DELIVERY_REASONS = (
    "unsupported_event",
    "invalid_booking",
    "invalid_deal",
    "merged",
    "subject_unknown",
    "consent_missing",
    "linked",
)
# "merged" marks a chain whose events moved into an earlier chain; reads never show it.
BOOKING_STATUSES = ("requested", "scheduled", "cancelled", "rejected", "completed", "merged")
EVENT_KINDS = ("requested", "created", "rescheduled", "cancelled", "rejected", "completed")


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


# One client's integration source: its kind, name, status and the public key of its callback URL.
# SELECT id, kind, name, status, created_at FROM public.integration_sources
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY created_at LIMIT 100;
class IntegrationSource(Base):
    __tablename__ = "integration_sources"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_integration_sources_scope"),
        UniqueConstraint("public_key", name="uq_integration_sources_public_key"),
        Index("ix_integration_sources_agency_client", "agency_id", "client_id"),
        CheckConstraint(f"kind IN ({_values(KINDS)})", name="valid_kind"),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="valid_name"),
        CheckConstraint(f"public_key ~ '{PUBLIC_KEY}'", name="valid_public_key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    public_key: Mapped[str] = mapped_column(String(64))
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Sealed signing secret versions of one source (kind integration_signing); a replaced version
# stays valid until retires_at, 24 hours later.
class IntegrationSourceSecret(Base):
    __tablename__ = "integration_source_secrets"
    __table_args__ = (
        ForeignKeyConstraint(*SOURCE_FK),
        UniqueConstraint("source_id", "version", name="uq_integration_source_secrets_version"),
        CheckConstraint("version >= 1", name="positive_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    kek_id: Mapped[str] = mapped_column(String(32))
    wrap_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# One verified delivery of one source: a SHA-256 of the body (unique per source, which makes a
# redelivery a no-op), the receipt time and a closed outcome and reason. Deleted after 30 days.
# SELECT received_at, outcome, reason FROM public.integration_deliveries
# WHERE source_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY received_at DESC LIMIT 100;
class IntegrationDelivery(Base):
    __tablename__ = "integration_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(*SOURCE_FK),
        UniqueConstraint("source_id", "delivery_digest", name="uq_integration_deliveries_digest"),
        Index("ix_integration_deliveries_received_at", "received_at"),
        CheckConstraint(f"outcome IN ({_values(DELIVERY_OUTCOMES)})", name="valid_outcome"),
        CheckConstraint(
            f"reason IS NULL OR reason IN ({_values(DELIVERY_REASONS)})", name="valid_reason"
        ),
        CheckConstraint("delivery_digest ~ '^[0-9a-f]{64}$'", name="valid_digest"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    delivery_digest: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(32))


# One booking chain of one source of one client, with the state derived from its events. The
# provider's booking IDs are scoped to the source that delivered them (review finding R006).
# SELECT id, provider, status, start_at, reschedule_count, subject_id IS NOT NULL AS linked
# FROM public.bookings WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY updated_at DESC LIMIT 100;
class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(*SOURCE_FK),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_bookings_scope"),
        Index("ix_bookings_client_updated", "client_id", "updated_at"),
        CheckConstraint(f"provider IN ({_values(KINDS)})", name="valid_provider"),
        CheckConstraint(f"status IN ({_values(BOOKING_STATUSES)})", name="valid_status"),
        CheckConstraint("reschedule_count >= 0", name="valid_reschedules"),
        CheckConstraint("(subject_id IS NULL) = (linked_at IS NULL)", name="valid_link"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    event_type_ref: Mapped[str | None] = mapped_column(String(128))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reschedule_count: Mapped[int] = mapped_column(Integer, server_default="0")
    subject_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("collection_subjects.id", ondelete="SET NULL")
    )
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# One minimal event of one booking chain: its kind, the provider booking ID it concerns, the
# previous ID of a reschedule, its occurrence time and the schedule it carried.
class BookingEvent(Base):
    __tablename__ = "booking_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "booking_id"],
            ["bookings.agency_id", "bookings.client_id", "bookings.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(*SOURCE_FK),
        UniqueConstraint(
            "booking_id", "kind", "ref", "occurred_at", name="uq_booking_events_event"
        ),
        Index("ix_booking_events_source_ref", "source_id", "ref"),
        Index("ix_booking_events_source_previous", "source_id", "previous_ref"),
        CheckConstraint(f"kind IN ({_values(EVENT_KINDS)})", name="valid_kind"),
        CheckConstraint(f"provider IN ({_values(KINDS)})", name="valid_provider"),
        CheckConstraint(
            "(kind = 'rescheduled') = (previous_ref IS NOT NULL) "
            "AND (previous_ref IS NULL OR previous_ref <> ref)",
            name="valid_reschedule",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    booking_id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    ref: Mapped[str] = mapped_column(String(128))
    previous_ref: Mapped[str | None] = mapped_column(String(128))
    event_type_ref: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
