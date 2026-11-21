"""CRM stage rules and deals (specification 015-D, D-068 decisions E5, E6, E9 and E10).

A deal is the latest known stage of one CRM deal of one client, received through a signed
webhook source. A stage change never becomes revenue (E6): only an Owner or Admin's approved
won or lost rule for a pipeline and stage gives the deal an outcome, and a won deal is linked to
a sale only when its payment reference matches a verified ledger sale of the same client, which
the read checks against the ledger each time. No row holds a contact, a name or a note.
tracking_lifecycle deletes deals 395 days after their last update (E9); rules stay until deleted
with the workspace. Reference queries below are manual read-only diagnostics for an authorized
operator; replace the synthetic literals before use.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])


# One approved stage rule of one client: a pipeline and stage that count as won or lost.
# SELECT pipeline, stage, outcome, status FROM public.crm_stage_rules
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY pipeline, stage;
class CrmStageRule(Base):
    __tablename__ = "crm_stage_rules"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        UniqueConstraint("client_id", "pipeline", "stage", name="uq_crm_stage_rules_stage"),
        CheckConstraint("outcome IN ('won', 'lost')", name="valid_outcome"),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
        CheckConstraint(
            "length(pipeline) BETWEEN 1 AND 128 AND length(stage) BETWEEN 1 AND 128",
            name="valid_names",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    pipeline: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# The latest known stage of one deal of one source, with an optional amount and payment reference.
# SELECT deal_ref, pipeline, stage, stage_at, updated_at FROM public.crm_deals
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY updated_at DESC LIMIT 100;
class CrmDeal(Base):
    __tablename__ = "crm_deals"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "source_id"],
            [
                "integration_sources.agency_id",
                "integration_sources.client_id",
                "integration_sources.id",
            ],
        ),
        UniqueConstraint("source_id", "deal_ref", name="uq_crm_deals_deal"),
        Index("ix_crm_deals_client_updated", "client_id", "updated_at"),
        CheckConstraint(
            "length(deal_ref) BETWEEN 1 AND 128 AND length(pipeline) BETWEEN 1 AND 128 "
            "AND length(stage) BETWEEN 1 AND 128 "
            "AND (previous_stage IS NULL OR length(previous_stage) BETWEEN 1 AND 128) "
            "AND (payment_reference IS NULL OR length(payment_reference) BETWEEN 1 AND 128)",
            name="valid_text",
        ),
        CheckConstraint(
            "(amount_minor IS NULL) = (currency IS NULL) "
            "AND (currency IS NULL) = (currency_exponent IS NULL) "
            "AND (amount_minor IS NULL OR amount_minor > 0) "
            "AND (currency IS NULL OR currency ~ '^[A-Z]{3}$')",
            name="valid_amount",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    deal_ref: Mapped[str] = mapped_column(String(128))
    pipeline: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(128))
    previous_stage: Mapped[str | None] = mapped_column(String(128))
    stage_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    currency_exponent: Mapped[int | None] = mapped_column(SmallInteger)
    payment_reference: Mapped[str | None] = mapped_column(String(128))
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
