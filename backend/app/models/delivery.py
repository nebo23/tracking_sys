"""Conversion destinations, the delivery outbox and acknowledgements (specification 014-B).

D-064 decisions D7, D9, D10 and D13, with the D9 delivery key amended by D-065. Every table is
scoped by agency and client; a delivery references its destination and its delivery connection
through composite (agency_id, client_id, ...) keys, so it can never point at another client's
destination or connection. A sale has one event ID per dataset, and at most one delivery per
client and event ID holds it (HOLDS_EVENT), whatever the destination or connection. Delivery rows
hold no person identifier: the match key, the subject references and the replay keys live only
in the sealed payload, which is destroyed when the delivery ends. tracking_lifecycle deletes
ended deliveries and their acknowledgements 30 days after they end. Reference queries below are
manual read-only diagnostics for an authorized operator; replace the synthetic literals before
use. Sealed material is omitted.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.connectors import CONNECTION_FK, MEMBERSHIP

STATUSES = (
    "queued",
    "sending",
    "delivered",
    "blocked",
    "cancelled",
    "expired",
    "rejected",
    "undeliverable",
    "dismissed",
)
ENDED = ("delivered", "blocked", "cancelled", "expired", "undeliverable", "dismissed")
REASONS = (
    # blocked at the claim (E5)
    "consent_unknown",
    "consent_denied",
    "consent_withdrawn",
    "consent_expired",
    "subject_deleted",
    "subject_unknown",
    "subject_objected",
    "no_consent_after_deletion",
    "replay_before_deletion",
    # cancelled
    "destination_disabled",
    "connection_ended",
    "sale_reversed",
    # expired
    "deadline_passed",
    # rejected (and kept after a dismissal)
    "permission_missing",
    "dataset_unavailable",
    "invalid_parameter",
    "invalid_event",
    # undeliverable
    "retries_exhausted",
    # queued again after a failed attempt
    "retryable",
    "rate_limited",
    "count_mismatch",
    "invalid_token",
)
ACTION_SOURCES = (
    "email",
    "website",
    "phone_call",
    "chat",
    "physical_store",
    "system_generated",
    "business_messaging",
    "other",
)
OUTCOMES = (
    "accepted",
    "count_mismatch",
    "retryable",
    "rate_limited",
    "unauthorized",
    "configuration",
    "payload",
)
MATERIAL = ("kek_id", "wrap_nonce", "wrapped_dek", "nonce", "ciphertext")
EVENT_NAME = "^[A-Za-z][A-Za-z0-9_]{0,39}$"
TEST_CODE = "^[A-Za-z0-9]{1,32}$"
# Cancellation reasons that, with no attempt made, mean the delivery never reached Meta.
UNSENT = ("destination_disabled", "connection_ended")


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


# The rows that hold their event ID (D-065): every delivery except one cancelled before any
# attempt because its destination was disabled or its connection ended, which never reached
# Meta. At most one holder may exist per client and event ID, so a sale reaches a dataset at
# most once; the enqueue looks up an existing delivery with the same predicate.
HOLDS_EVENT = (
    f"NOT (status = 'cancelled' AND attempts = 0 AND COALESCE(reason, '') IN ({_values(UNSENT)}))"
)


def _time(nullable: bool = True, *, default: bool = False) -> Any:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now() if default else None,
        nullable=nullable,
    )


# The conversion destination of one delivery connection (D10): the event name, an optional
# test event code and an enabled flag, off until an Owner or Admin enables it. The dataset is
# the connection's external account and is not copied here.
# SELECT id, connection_id, event_name, test_event_code IS NOT NULL AS testing, enabled,
#        created_at, updated_at
# FROM public.conversion_destinations
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at, id LIMIT 100;
class ConversionDestination(Base):
    __tablename__ = "conversion_destinations"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        ForeignKeyConstraint(["agency_id", "created_by_membership_id"], MEMBERSHIP),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_conversion_destinations_scope"),
        UniqueConstraint("connection_id", name="uq_conversion_destinations_connection"),
        CheckConstraint(f"event_name ~ '{EVENT_NAME}'", name="valid_event_name"),
        CheckConstraint(
            f"test_event_code IS NULL OR test_event_code ~ '{TEST_CODE}'", name="valid_test_code"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    event_name: Mapped[str] = mapped_column(String(40), server_default="Purchase")
    test_event_code: Mapped[str | None] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = _time(False, default=True)
    updated_at: Mapped[datetime] = _time(False, default=True)


# One verified sale for one destination (D9 as amended by D-065): a deterministic event ID
# derived from the client, the dataset and the sale, unique per client among the rows that hold
# it (HOLDS_EVENT), the event time (the authoritative sale instant, never moved), the deadline
# (the 7-day age limit less 1 hour), the value in minor units of the sale's currency, the
# consent basis and policy version of the enqueue (D7), the state with its closed reason, the
# attempt fence and the retry, requeue and lease state, and the sealed payload while the
# delivery has not ended.
# SELECT id, destination_id, event_name, action_source, event_time, deadline, currency,
#        value_minor, status, reason, rejection_class, attempts, retries, requeues,
#        not_before, created_at, delivered_at, ended_at
# FROM public.conversion_deliveries
# WHERE destination_id = '00000000-0000-0000-0000-00000000000a'::uuid
# ORDER BY created_at DESC, id LIMIT 100;
class ConversionDelivery(Base):
    __tablename__ = "conversion_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "destination_id"],
            [
                "conversion_destinations.agency_id",
                "conversion_destinations.client_id",
                "conversion_destinations.id",
            ],
        ),
        ForeignKeyConstraint(*CONNECTION_FK),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_conversion_deliveries_scope"),
        CheckConstraint(f"status IN ({_values(STATUSES)})", name="valid_status"),
        CheckConstraint(f"reason IS NULL OR reason IN ({_values(REASONS)})", name="valid_reason"),
        CheckConstraint(f"action_source IN ({_values(ACTION_SOURCES)})", name="valid_source"),
        CheckConstraint(
            "(rejection_class IS NULL OR rejection_class IN ('configuration', 'payload')) "
            "AND (status <> 'rejected' OR rejection_class IS NOT NULL) "
            "AND (rejection_class IS NULL OR status IN ('rejected', 'dismissed'))",
            name="valid_rejection",
        ),
        CheckConstraint(
            f"(status IN ({_values(ENDED)})) <= (ended_at IS NOT NULL) "
            "AND (status IN ('queued', 'sending')) <= (ended_at IS NULL) "
            "AND (status <> 'rejected' OR (rejection_class = 'payload') = (ended_at IS NOT NULL))",
            name="ended_state",
        ),
        CheckConstraint(
            "(ended_at IS NULL AND "
            + " AND ".join(f"{name} IS NOT NULL" for name in MATERIAL)
            + ") OR (ended_at IS NOT NULL AND "
            + " AND ".join(f"{name} IS NULL" for name in MATERIAL)
            + ")",
            name="payload_state",
        ),
        CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL) "
            "AND (status <> 'sending' OR lease_expires_at IS NOT NULL)",
            name="delivery_times",
        ),
        CheckConstraint(
            "event_id ~ '^[0-9a-f]{64}$' AND currency ~ '^[A-Z]{3}$' "
            f"AND event_name ~ '{EVENT_NAME}' AND deadline > event_time",
            name="valid_event",
        ),
        CheckConstraint(
            "value_minor > 0 AND currency_exponent BETWEEN 0 AND 8 AND attempts >= 0 "
            "AND retries >= 0 AND requeues BETWEEN 0 AND 3",
            name="valid_counters",
        ),
        Index(
            "uq_conversion_deliveries_event",
            "client_id",
            "event_id",
            unique=True,
            postgresql_where=text(HOLDS_EVENT),
        ),
        Index(
            "ix_conversion_deliveries_open",
            "created_at",
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index(
            "ix_conversion_deliveries_ended",
            "ended_at",
            postgresql_where=text("ended_at IS NOT NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    destination_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    event_id: Mapped[str] = mapped_column(String(64))
    event_name: Mapped[str] = mapped_column(String(40))
    action_source: Mapped[str] = mapped_column(String(24))
    event_time: Mapped[datetime] = _time(False)
    deadline: Mapped[datetime] = _time(False)
    currency: Mapped[str] = mapped_column(String(3))
    currency_exponent: Mapped[int] = mapped_column(SmallInteger)
    value_minor: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    reason: Mapped[str | None] = mapped_column(String(32))
    rejection_class: Mapped[str | None] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    retries: Mapped[int] = mapped_column(Integer, server_default="0")
    requeues: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    not_before: Mapped[datetime | None] = _time()
    lease_expires_at: Mapped[datetime | None] = _time()
    consent_basis: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    policy_version: Mapped[str] = mapped_column(String(32))
    kek_id: Mapped[str | None] = mapped_column(String(32))
    wrap_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _time(False, default=True)
    updated_at: Mapped[datetime] = _time(False, default=True)
    delivered_at: Mapped[datetime | None] = _time()
    ended_at: Mapped[datetime | None] = _time()


# The provider's answer to one attempt of one delivery (D9): when, the closed outcome class,
# the adapter's closed provider code, events_received and the provider trace ID. The trace ID
# is never returned by a route or written to a log.
# SELECT attempt, occurred_at, outcome, provider_code, events_received
# FROM public.conversion_acknowledgements
# WHERE delivery_id = '00000000-0000-0000-0000-00000000000b'::uuid
# ORDER BY attempt LIMIT 20;
class ConversionAcknowledgement(Base):
    __tablename__ = "conversion_acknowledgements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "delivery_id"],
            [
                "conversion_deliveries.agency_id",
                "conversion_deliveries.client_id",
                "conversion_deliveries.id",
            ],
        ),
        UniqueConstraint("delivery_id", "attempt", name="uq_conversion_acknowledgements_attempt"),
        CheckConstraint(f"outcome IN ({_values(OUTCOMES)})", name="valid_outcome"),
        CheckConstraint(
            "attempt >= 1 AND (events_received IS NULL OR events_received >= 0)",
            name="valid_counts",
        ),
        CheckConstraint(
            "provider_code IS NULL OR provider_code ~ '^[a-z0-9_]{1,32}$'", name="valid_code"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    delivery_id: Mapped[UUID] = mapped_column(Uuid)
    attempt: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = _time(False, default=True)
    outcome: Mapped[str] = mapped_column(String(24))
    provider_code: Mapped[str | None] = mapped_column(String(32))
    events_received: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(64))
