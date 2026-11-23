"""Persisted revenue journal over revenue_evidence (specification 007-B, D-075 J7-J9).

Every row is scoped by agency and client. Receipts and movements are append-only for the
runtime (tracking_app may insert and read them, never update or delete them); a generation
groups one complete build of the journal, and only the generation published in
ledger_projection_state is current. ledger_transactions is the replaceable current projection
of each sale transaction. No column holds a person, an identity key or contact data. Reference
queries below are manual read-only diagnostics for an authorized operator; replace the
synthetic literals before use. Digests are omitted.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])


def _scoped(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["agency_id", "client_id", column],
        [f"{target}.agency_id", f"{target}.client_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}"[:63],
    )


# The published generation and cursors of one client's journal.
# SELECT client_id, generation, staging_generation, status, last_evidence_sequence,
#        receipt_ordinal, movement_sequence, financial_revision, updated_at
# FROM public.ledger_projection_state
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid;
class LedgerProjectionState(Base):
    __tablename__ = "ledger_projection_state"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        CheckConstraint("status IN ('building', 'ready', 'failed')", name="valid_status"),
        CheckConstraint("status <> 'ready' OR generation >= 1", name="ready_generation"),
        CheckConstraint(
            "generation >= 0 AND last_evidence_sequence >= 0 AND receipt_ordinal >= 0 "
            "AND movement_sequence >= 0 AND financial_revision >= 0",
            name="valid_counters",
        ),
        CheckConstraint("octet_length(receipt_digest) = 32", name="digest_length"),
        CheckConstraint(
            "staging_generation IS NULL OR staging_generation > generation", name="staging"
        ),
    )
    client_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(Integer, server_default="0")
    staging_generation: Mapped[int | None] = mapped_column(Integer)
    algorithm: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    last_evidence_sequence: Mapped[int] = mapped_column(BigInteger, server_default="0")
    receipt_ordinal: Mapped[int] = mapped_column(BigInteger, server_default="0")
    movement_sequence: Mapped[int] = mapped_column(BigInteger, server_default="0")
    receipt_digest: Mapped[bytes] = mapped_column(LargeBinary)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    financial_revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# One receipt position per stored evidence row and generation.
# SELECT generation, receipt_ordinal, evidence_id, evidence_sequence, outcome, created_at
# FROM public.ledger_receipts
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid AND generation = 1
# ORDER BY receipt_ordinal LIMIT 100;
class LedgerReceipt(Base):
    __tablename__ = "ledger_receipts"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("ledger_receipts", "evidence_id", "revenue_evidence"),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_ledger_receipts_scope"),
        UniqueConstraint(
            "client_id", "generation", "receipt_ordinal", name="uq_ledger_receipts_ordinal"
        ),
        UniqueConstraint(
            "client_id", "generation", "evidence_id", name="uq_ledger_receipts_evidence"
        ),
        CheckConstraint(
            "outcome IN ('posted', 'duplicate', 'pending', 'reconciliation', 'unverified', "
            "'excluded', 'held')",
            name="valid_outcome",
        ),
        CheckConstraint("generation >= 1 AND receipt_ordinal >= 1", name="positions"),
        CheckConstraint(
            "octet_length(input_digest) = 32 AND octet_length(previous_digest) = 32 "
            "AND octet_length(receipt_digest) = 32",
            name="digests",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(Integer)
    receipt_ordinal: Mapped[int] = mapped_column(BigInteger)
    evidence_id: Mapped[UUID] = mapped_column(Uuid)
    evidence_sequence: Mapped[int] = mapped_column(BigInteger)
    input_digest: Mapped[bytes] = mapped_column(LargeBinary)
    previous_digest: Mapped[bytes] = mapped_column(LargeBinary)
    receipt_digest: Mapped[bytes] = mapped_column(LargeBinary)
    outcome: Mapped[str] = mapped_column(String(16))
    closing_states: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# One immutable signed posting or release.
# SELECT generation, movement_sequence, source_account_id, transaction_id, operation_id, kind,
#        direction, amount_minor, currency, effective_at, reason
# FROM public.ledger_movements
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid AND generation = 1
# ORDER BY movement_sequence LIMIT 100;
class LedgerMovement(Base):
    __tablename__ = "ledger_movements"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("ledger_movements", "receipt_id", "ledger_receipts"),
        _scoped("ledger_movements", "trigger_evidence_id", "revenue_evidence"),
        UniqueConstraint(
            "client_id", "generation", "movement_sequence", name="uq_ledger_movements_sequence"
        ),
        Index(
            "ix_ledger_movements_transaction",
            "client_id",
            "generation",
            "source_account_id",
            "transaction_id",
        ),
        CheckConstraint(
            "kind IN ('sale', 'refund', 'chargeback', 'chargeback_reversal', 'correction')",
            name="valid_kind",
        ),
        CheckConstraint("direction IN ('posting', 'release')", name="valid_direction"),
        CheckConstraint("amount_minor <> 0", name="nonzero_amount"),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$' AND currency_exponent BETWEEN 0 AND 8", name="valid_currency"
        ),
        CheckConstraint("generation >= 1 AND movement_sequence >= 1", name="positions"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(Integer)
    movement_sequence: Mapped[int] = mapped_column(BigInteger)
    receipt_id: Mapped[UUID] = mapped_column(Uuid)
    source_account_id: Mapped[str] = mapped_column(String(256))
    transaction_id: Mapped[str] = mapped_column(String(256))
    operation_id: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(24))
    direction: Mapped[str] = mapped_column(String(8))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    currency_exponent: Mapped[int] = mapped_column(SmallInteger)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trigger_evidence_id: Mapped[UUID] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(String(32))


# The current projection of one sale transaction in one generation.
# SELECT source_account_id, operation_id, currency, sale_effective_at, captured, refunded,
#        charged_back, reversed, corrected, net, financial_revision
# FROM public.ledger_transactions
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid AND generation = 1
# ORDER BY sale_effective_at DESC LIMIT 100;
class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint(
            "client_id",
            "generation",
            "source_account_id",
            "operation_id",
            name="uq_ledger_transactions_key",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$' AND currency_exponent BETWEEN 0 AND 8", name="valid_currency"
        ),
        CheckConstraint(
            "net = captured - refunded - charged_back + reversed + corrected", name="net_total"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(Integer)
    source_account_id: Mapped[str] = mapped_column(String(256))
    operation_id: Mapped[str] = mapped_column(String(256))
    currency: Mapped[str] = mapped_column(String(3))
    currency_exponent: Mapped[int] = mapped_column(SmallInteger)
    sale_effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    captured: Mapped[int] = mapped_column(BigInteger)
    refunded: Mapped[int] = mapped_column(BigInteger)
    charged_back: Mapped[int] = mapped_column(BigInteger)
    reversed: Mapped[int] = mapped_column(BigInteger)
    corrected: Mapped[int] = mapped_column(BigInteger)
    net: Mapped[int] = mapped_column(BigInteger)
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    evidence_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    financial_revision: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# One audited acknowledge or reopen decision on a reconciliation issue (J9).
# SELECT operation_id, issue_id, issue_version, action, reason_code, actor_membership_id,
#        created_at
# FROM public.ledger_reconciliation_actions
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at DESC LIMIT 100;
class LedgerReconciliationAction(Base):
    __tablename__ = "ledger_reconciliation_actions"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "actor_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        UniqueConstraint("client_id", "operation_id", name="uq_ledger_actions_operation"),
        Index("ix_ledger_reconciliation_actions_issue", "client_id", "issue_id"),
        CheckConstraint("action IN ('acknowledge', 'reopen')", name="valid_action"),
        CheckConstraint(
            "reason_code IN ('provider_contacted', 'awaiting_evidence', 'confirmed_duplicate', "
            "'reviewed_no_action', 'new_information')",
            name="valid_reason",
        ),
        CheckConstraint(
            "issue_fingerprint ~ '^[0-9a-f]{64}$' AND request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="fingerprints",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    issue_id: Mapped[UUID] = mapped_column(Uuid)
    issue_fingerprint: Mapped[str] = mapped_column(String(64))
    issue_version: Mapped[int] = mapped_column(BigInteger)
    evidence_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    action: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(40))
    actor_membership_id: Mapped[UUID] = mapped_column(Uuid)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
