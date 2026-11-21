"""Persisted revenue evidence (specification 015-A, D-067 decisions D2, D11 and D14).

revenue_evidence is the append-only receipt log of 007-A Evidence records of one client, with
the intake provenance (a Paymob source, a CSV import or a manual entry) and a content digest for
the exact-redelivery rule. The ledger is never stored: app.services.revenue derives it with
calculate() over the client's records in receipt order on each read. tracking_app may insert and
read only; nothing updates or deletes a record, and evidence is kept for the life of the client
workspace (D14). No column holds card, billing, shipping or customer data (D6). Reference queries
below are manual read-only diagnostics for an authorized operator; replace the synthetic literals
before use.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])
KINDS = ("sale", "refund", "chargeback", "chargeback_reversal", "correction")
CLASSES = (
    "confirmed_capture",
    "confirmed_settlement",
    "confirmed_adjustment",
    "audited_correction",
    "manual_declaration",
    "purchase_signal",
)
INTAKES = ("paymob", "csv_import", "manual_entry")
# The evidence classes 007-A allows for each operation kind (app.ledger.calculation).
ALLOWED_CLASSES = (
    "(kind = 'sale' AND classification IN ('confirmed_capture', 'confirmed_settlement', "
    "'manual_declaration', 'purchase_signal')) "
    "OR (kind IN ('refund', 'chargeback', 'chargeback_reversal') "
    "AND classification IN ('confirmed_adjustment', 'manual_declaration')) "
    "OR (kind = 'correction' AND classification = 'audited_correction')"
)


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


# One received 007-A Evidence record of one client, in receipt order (received_at from the
# database clock under the client's revenue lock, then sequence). An exact redelivery (same
# source account, delivery ID and content digest) is stored once; a reused delivery ID with other
# content is a second row that 007-A reports as delivery_id_reused.
# SELECT received_at, sequence, intake, operation_id, kind, classification, currency,
#        amount_minor, effective_at, parent_operation_id
# FROM public.revenue_evidence
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY received_at, sequence LIMIT 100;
class RevenueEvidence(Base):
    __tablename__ = "revenue_evidence"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint(
            "client_id",
            "source_account_id",
            "delivery_id",
            "content_digest",
            name="uq_revenue_evidence_delivery",
        ),
        UniqueConstraint("sequence", name="uq_revenue_evidence_sequence"),
        Index("ix_revenue_evidence_receipt", "client_id", "received_at", "sequence"),
        CheckConstraint(f"kind IN ({_values(KINDS)})", name="valid_kind"),
        CheckConstraint(ALLOWED_CLASSES, name="valid_classification"),
        CheckConstraint(f"intake IN ({_values(INTAKES)})", name="valid_intake"),
        CheckConstraint("(intake = 'manual_entry') = (intake_id IS NULL)", name="intake_reference"),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$' AND currency_exponent BETWEEN 0 AND 8", name="valid_currency"
        ),
        CheckConstraint(
            "(kind = 'correction' AND amount_minor <> 0) OR amount_minor > 0",
            name="valid_amount",
        ),
        CheckConstraint(
            "(kind = 'sale') = (parent_operation_id IS NULL) "
            "AND (parent_operation_id IS NULL OR parent_operation_id <> operation_id)",
            name="valid_parent",
        ),
        CheckConstraint(
            "length(delivery_id) BETWEEN 1 AND 256 AND length(source_account_id) BETWEEN 1 AND 256 "
            "AND length(operation_id) BETWEEN 1 AND 256 "
            "AND (parent_operation_id IS NULL OR length(parent_operation_id) BETWEEN 1 AND 256) "
            "AND (reason IS NULL OR length(reason) BETWEEN 1 AND 1024) "
            "AND (actor IS NULL OR length(actor) BETWEEN 1 AND 256) "
            "AND (source_reference IS NULL OR length(source_reference) BETWEEN 1 AND 256)",
            name="valid_text",
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="valid_digest"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    delivery_id: Mapped[str] = mapped_column(String(256))
    source_account_id: Mapped[str] = mapped_column(String(256))
    operation_id: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(24))
    classification: Mapped[str] = mapped_column(String(24))
    currency: Mapped[str] = mapped_column(String(3))
    currency_exponent: Mapped[int] = mapped_column(SmallInteger)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parent_operation_id: Mapped[str | None] = mapped_column(String(256))
    reason: Mapped[str | None] = mapped_column(String(1024))
    actor: Mapped[str | None] = mapped_column(String(256))
    source_reference: Mapped[str | None] = mapped_column(String(256))
    intake: Mapped[str] = mapped_column(String(16))
    intake_id: Mapped[UUID | None] = mapped_column(Uuid)
    content_digest: Mapped[str] = mapped_column(String(64))
