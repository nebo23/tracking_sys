"""WhatsApp numbers and referral messages (specification 015-E, D-068 decisions E7 to E10).

An Owner or Admin registers a client's claim to a WhatsApp Business phone number ID. The claim
is pending and routes nothing until a platform operator verifies it (D-070, review finding
R004): agency authority over a workspace is not proof of owning the provider's number. Only a
verified, active binding attributes notifications for that ID to the client, and each number
has at most one verified binding. For each inbound message, only the Click-to-WhatsApp
referral is kept: the source type, the ad ID and whether a click ID was present (E8). A message
without a referral is recorded as unknown. No row holds a phone number, name, sender ID, message
text, ad text, media URL or click ID, so no conversation is correlated with a person (no valid
grant exists before 006). The message key is a SHA-256 of the provider's message ID, which makes
a repeated notification a no-op. tracking_lifecycle deletes messages 395 days after receipt
(E9). Reference queries below are manual read-only diagnostics for an authorized operator;
replace the synthetic literals before use.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])
SOURCE_TYPES = ("ad", "post", "other")
# D-070 claim states: pending (claimed, routes nothing), active and disabled (verified by the
# platform operator), revoked (ended by the operator).
CLAIM_STATES = ("pending", "active", "disabled", "revoked")
VERIFIED = "status IN ('active', 'disabled')"


# One client's claim to a WhatsApp Business phone number ID, verified or not.
# SELECT id, phone_number_id, name, status, verified_at FROM public.whatsapp_numbers
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY created_at LIMIT 100;
class WhatsappNumber(Base):
    __tablename__ = "whatsapp_numbers"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_whatsapp_numbers_scope"),
        Index(
            "uq_whatsapp_numbers_verified",
            "phone_number_id",
            unique=True,
            postgresql_where=text(VERIFIED),
        ),
        Index(
            "uq_whatsapp_numbers_claim",
            "client_id",
            "phone_number_id",
            unique=True,
            postgresql_where=text("status <> 'revoked'"),
        ),
        CheckConstraint("phone_number_id ~ '^[1-9][0-9]{0,31}$'", name="valid_phone_number_id"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{item}'" for item in CLAIM_STATES) + ")",
            name="valid_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND verified_at IS NULL) "
            "OR (status IN ('active', 'disabled') AND verified_at IS NOT NULL) "
            "OR status = 'revoked'",
            name="valid_verification",
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="valid_name"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    phone_number_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# One inbound message of one registered number: its referral, or none (unknown).
# SELECT received_at, has_referral, source_type, source_id, click_id_present
# FROM public.whatsapp_messages WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY received_at DESC LIMIT 100;
class WhatsappMessage(Base):
    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "number_id"],
            ["whatsapp_numbers.agency_id", "whatsapp_numbers.client_id", "whatsapp_numbers.id"],
        ),
        UniqueConstraint("message_digest", name="uq_whatsapp_messages_digest"),
        Index("ix_whatsapp_messages_client_received", "client_id", "received_at"),
        CheckConstraint("message_digest ~ '^[0-9a-f]{64}$'", name="valid_digest"),
        CheckConstraint(
            "(has_referral = false AND source_type IS NULL AND source_id IS NULL "
            "AND click_id_present = false) OR (has_referral = true AND source_type IN "
            "('ad', 'post', 'other') AND (source_id IS NULL OR source_id ~ '^[1-9][0-9]{0,31}$'))",
            name="valid_referral",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    number_id: Mapped[UUID] = mapped_column(Uuid)
    message_digest: Mapped[str] = mapped_column(String(64))
    message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    has_referral: Mapped[bool] = mapped_column(Boolean)
    source_type: Mapped[str | None] = mapped_column(String(8))
    source_id: Mapped[str | None] = mapped_column(String(32))
    click_id_present: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
