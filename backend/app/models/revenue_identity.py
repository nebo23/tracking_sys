"""Sale-to-person association revisions (specification 007-C, D-075 decision J10).

One row per revision of the association between a verified sale (client, source account and
sale operation) and the person a trusted, consented 006 assertion names. No raw identifier,
token, handoff, merge root or amount is stored. F1 (J6) clears the identifying pointers and the
request's retry material of every revision of a withdrawn, erased or expired person, leaving a
non-identifying unlinked record. Reference queries below are manual read-only diagnostics for
an authorized operator; replace the synthetic literals before use.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# SELECT association_id, revision, source_account_id, sale_operation_id, state, reason,
#        received_at, closed_at
# FROM public.revenue_identity_bindings
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY received_at DESC, revision DESC LIMIT 100;
class RevenueIdentityBinding(Base):
    __tablename__ = "revenue_identity_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["agency_id", "credential_id"],
            ["service_credentials.agency_id", "service_credentials.id"],
        ),
        ForeignKeyConstraint(
            ["agency_id", "actor_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "assertion_ref"],
            [
                "identity_assertions.agency_id",
                "identity_assertions.client_id",
                "identity_assertions.id",
            ],
            name="fk_revenue_bindings_assertion",
        ),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "collection_subject_id"],
            [
                "collection_subjects.agency_id",
                "collection_subjects.client_id",
                "collection_subjects.id",
            ],
            name="fk_revenue_bindings_collection_subject",
        ),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "owner_subject_id"],
            [
                "identity_subjects.agency_id",
                "identity_subjects.client_id",
                "identity_subjects.id",
            ],
            name="fk_revenue_bindings_owner",
        ),
        UniqueConstraint(
            "client_id", "association_id", "revision", name="uq_revenue_identity_bindings_revision"
        ),
        UniqueConstraint("client_id", "request_id", name="uq_revenue_identity_bindings_request"),
        Index(
            "ix_revenue_identity_bindings_sale",
            "client_id",
            "source_account_id",
            "sale_operation_id",
        ),
        Index("ix_revenue_identity_bindings_owner", "owner_subject_id"),
        Index("ix_revenue_identity_bindings_subject", "collection_subject_id"),
        CheckConstraint(
            "state IN ('pending', 'active', 'ambiguous', 'detached', 'unlinked')",
            name="valid_state",
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN ('withdrawn', 'erased', 'expired', "
            "'detached_by_manager', 'conflicting_owner', 'attribution_withdrawn')",
            name="valid_reason",
        ),
        CheckConstraint(
            "detach_reason IS NULL OR detach_reason IN ('mistaken_association', "
            "'customer_request', 'data_correction')",
            name="valid_detach_reason",
        ),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="fingerprint",
        ),
        CheckConstraint(
            "(state = 'detached') = "
            "(actor_membership_id IS NOT NULL AND detach_reason IS NOT NULL)",
            name="origin",
        ),
        CheckConstraint(
            "state <> 'unlinked' OR (request_id IS NULL AND request_fingerprint IS NULL "
            "AND assertion_ref IS NULL AND collection_subject_id IS NULL "
            "AND owner_subject_id IS NULL AND cardinality(key_ids) = 0 AND reason IS NOT NULL)",
            name="unlinked_minimal",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    association_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[UUID | None] = mapped_column(Uuid)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_account_id: Mapped[str] = mapped_column(String(256))
    sale_operation_id: Mapped[str] = mapped_column(String(256))
    credential_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_membership_id: Mapped[UUID | None] = mapped_column(Uuid)
    assertion_ref: Mapped[UUID | None] = mapped_column(Uuid)
    collection_subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    owner_subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    key_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'::uuid[]"))
    state: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(32))
    detach_reason: Mapped[str | None] = mapped_column(String(32))
    expected_revision: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
