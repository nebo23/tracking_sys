"""Persisted attribution (specification 008-B, D-079 decisions D6, D9, D12 and D13).

Every row is scoped by agency and client. Model versions are per client and immutable apart
from their default flag, retirement and the idempotency record of the administrative requests
that targeted them. A conversion is one verified sale or one trusted lead with one owner (the
owner's visible identity root, or none for an unassociated sale); an ownership change
supersedes it and opens a successor, so its slot, kind and owner never change. Runs are the
immutable revisions of one conversion under one model version, with their allocations (one row
per eligible touch, credited or not, or one unknown row) and their signed credit changes, which
form the reporting ledger. The consumer state records the published generation, its
checkpoint over the ledger journal and the identity feed, and the unit of work in progress.

Rows hold identity person IDs, collected event IDs (touchpoints and lead events) and managed
link IDs only: no contact value, subject token, raw identifier or secret. The scrub (D9) clears
the person, lead event and touchpoint references of the affected conversions and keeps shares,
amounts, currencies, reporting dates and the campaign, content, link and source provenance.
Reference queries below are manual read-only diagnostics for an authorized operator; replace
the synthetic literals before use.
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
MODELS = "'first_click', 'last_click', 'linear'"
BASES = "'campaign', 'direct_fallback', 'unknown_fallback'"
RECIPIENTS = "'campaign', 'direct', 'unknown'"
EVIDENCE_CLASSES = "'campaign_interaction', 'direct_visit'"
SOURCES = "'tracker', 'trusted_sender'"
RUN_STATUSES = "'complete', 'no_verified_revenue', 'net_out_of_range', 'superseded'"
CAUSES = (
    "'initial', 'revenue_changed', 'sale_time_changed', 'touches_changed', "
    "'evidence_changed', 'superseded'"
)
EXCLUSIONS = (
    "'conflicting_records', 'aggregate_evidence', 'association_not_assigned', "
    "'consent_not_granted', 'after_conversion', 'before_window', "
    "'direct_superseded_by_campaign'"
)
SUPERSEDED_REASONS = (
    "'owner_changed', 'sale_removed', 'sale_changed', 'lead_removed', 'lead_changed', 'scrubbed'"
)
HEX64 = "~ '^[0-9a-f]{64}$'"


def _scoped(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["agency_id", "client_id", column],
        [f"{target}.agency_id", f"{target}.client_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}"[:63],
    )


# One immutable model version of a client (D2, D3).
# SELECT id, version_key, model, window_seconds, rules, is_default, status, created_at,
#        retired_at
# FROM public.attribution_model_versions
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY created_at, id;
class AttributionModelVersion(Base):
    __tablename__ = "attribution_model_versions"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        UniqueConstraint(
            "agency_id", "client_id", "id", name="uq_attribution_model_versions_scope"
        ),
        UniqueConstraint("client_id", "version_key", name="uq_attribution_model_versions_key"),
        Index(
            "uq_attribution_model_versions_default",
            "client_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        Index(
            "uq_attribution_model_versions_active_definition",
            "client_id",
            "model",
            "window_seconds",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint(f"model IN ({MODELS})", name="valid_model"),
        CheckConstraint(
            "version_key ~ '^(first_click|last_click|linear)_[0-9]{1,2}d_v[0-9]{1,6}$'",
            name="valid_version_key",
        ),
        CheckConstraint(
            "window_seconds BETWEEN 86400 AND 7776000 AND window_seconds % 86400 = 0",
            name="window",
        ),
        CheckConstraint("rules = '008-A.1'", name="valid_rules"),
        CheckConstraint("status IN ('active', 'retired')", name="valid_status"),
        CheckConstraint("(status = 'retired') = (retired_at IS NOT NULL)", name="retirement"),
        CheckConstraint("NOT is_default OR status = 'active'", name="default_active"),
        CheckConstraint("jsonb_typeof(operations) = 'array'", name="operations"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    version_key: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(16))
    window_seconds: Mapped[int] = mapped_column(Integer)
    rules: Mapped[str] = mapped_column(String(16))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(16))
    created_by_membership_id: Mapped[UUID | None] = mapped_column(Uuid)
    operations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# One verified sale or trusted lead with one owner (D4). superseded_generation marks a
# supersession that is published (status 'superseded') or still staged by a rebuild.
# SELECT id, generation, kind, status, superseded_reason, effective_at, scrubbed_at
# FROM public.attribution_conversions
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at DESC, id LIMIT 100;
class AttributionConversion(Base):
    __tablename__ = "attribution_conversions"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_attribution_conversions_scope"),
        UniqueConstraint("client_id", "conversion_key", name="uq_attribution_conversions_key"),
        Index(
            "uq_attribution_conversions_open_slot",
            "client_id",
            "slot_key",
            unique=True,
            postgresql_where=text("superseded_generation IS NULL"),
        ),
        Index(
            "ix_attribution_conversions_owner",
            "client_id",
            "owner_person_id",
            postgresql_where=text("owner_person_id IS NOT NULL"),
        ),
        Index(
            "ix_attribution_conversions_lead_event",
            "client_id",
            "lead_event_id",
            postgresql_where=text("lead_event_id IS NOT NULL"),
        ),
        Index(
            "ix_attribution_conversions_recheck",
            "client_id",
            "recheck_at",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_attribution_conversions_generation", "client_id", "generation"),
        CheckConstraint("kind IN ('sale', 'lead')", name="valid_kind"),
        CheckConstraint("status IN ('active', 'superseded')", name="valid_status"),
        CheckConstraint(
            f"superseded_reason IS NULL OR superseded_reason IN ({SUPERSEDED_REASONS})",
            name="valid_superseded_reason",
        ),
        CheckConstraint(f"slot_key {HEX64}", name="slot_key"),
        CheckConstraint(
            "conversion_key ~ '^([0-9a-f]{64}[.][1-9][0-9]{0,8}|scrubbed[.][0-9a-f-]{36})$'",
            name="conversion_key",
        ),
        CheckConstraint("generation >= 1", name="positive_generation"),
        CheckConstraint(
            "(kind = 'sale' AND source_account_id IS NOT NULL AND sale_operation_id IS NOT NULL "
            "AND lead_event_id IS NULL) OR (kind = 'lead' AND source_account_id IS NULL "
            "AND sale_operation_id IS NULL AND association_id IS NULL AND binding_id IS NULL)",
            name="kind_shape",
        ),
        CheckConstraint(
            "kind <> 'lead' OR scrubbed_at IS NOT NULL "
            "OR (lead_event_id IS NOT NULL AND owner_person_id IS NOT NULL)",
            name="lead_identity",
        ),
        CheckConstraint(
            "(superseded_generation IS NULL) = (superseded_at IS NULL) "
            "AND (superseded_at IS NULL) = (superseded_reason IS NULL) "
            "AND (status = 'active' OR superseded_generation IS NOT NULL) "
            "AND (superseded_generation IS NULL OR superseded_generation >= generation)",
            name="supersession",
        ),
        # D9: a scrubbed conversion keeps no person, lead event or person-derived key.
        CheckConstraint(
            "scrubbed_at IS NULL OR (owner_person_id IS NULL AND lead_event_id IS NULL "
            "AND conversion_key LIKE 'scrubbed.%')",
            name="scrubbed_minimal",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(BigInteger)
    slot_key: Mapped[str] = mapped_column(String(64))
    conversion_key: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(8))
    owner_person_id: Mapped[UUID | None] = mapped_column(Uuid)
    association_id: Mapped[UUID | None] = mapped_column(Uuid)
    binding_id: Mapped[UUID | None] = mapped_column(Uuid)
    source_account_id: Mapped[str | None] = mapped_column(String(256))
    sale_operation_id: Mapped[str | None] = mapped_column(String(256))
    lead_event_id: Mapped[UUID | None] = mapped_column(Uuid)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    superseded_generation: Mapped[int | None] = mapped_column(BigInteger)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_reason: Mapped[str | None] = mapped_column(String(24))
    scrubbed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recheck_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# One immutable revision of one conversion under one model version (D5).
# SELECT conversion_id, model_version_id, revision, status, basis, causes, currency,
#        verified_net_minor, window_end, recorded_at
# FROM public.attribution_runs
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY recorded_at DESC, id LIMIT 100;
class AttributionRun(Base):
    __tablename__ = "attribution_runs"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("attribution_runs", "conversion_id", "attribution_conversions"),
        _scoped("attribution_runs", "model_version_id", "attribution_model_versions"),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_attribution_runs_scope"),
        UniqueConstraint(
            "client_id",
            "conversion_id",
            "model_version_id",
            "revision",
            name="uq_attribution_runs_revision",
        ),
        Index("ix_attribution_runs_generation", "client_id", "generation"),
        Index(
            "ix_attribution_runs_excluded_touchpoints",
            "excluded_touchpoint_ids",
            postgresql_using="gin",
        ),
        CheckConstraint(f"status IN ({RUN_STATUSES})", name="valid_status"),
        CheckConstraint(f"basis IS NULL OR basis IN ({BASES})", name="valid_basis"),
        CheckConstraint(
            f"cardinality(causes) >= 1 AND causes <@ ARRAY[{CAUSES}]::varchar[]",
            name="valid_causes",
        ),
        CheckConstraint(
            f"excluded_reasons <@ ARRAY[{EXCLUSIONS}]::varchar[] "
            "AND cardinality(excluded_reasons) = cardinality(excluded_touchpoint_ids)",
            name="valid_excluded",
        ),
        CheckConstraint("revision >= 1 AND generation >= 1", name="positions"),
        CheckConstraint(
            "(status = 'superseded') = (basis IS NULL) "
            "AND (status = 'superseded') = (window_end IS NULL) "
            "AND (window_start IS NULL) = (window_end IS NULL) "
            "AND (window_start IS NULL OR window_start <= window_end)",
            name="closing_shape",
        ),
        CheckConstraint(
            "(currency IS NULL) = (currency_exponent IS NULL) AND (currency IS NULL "
            "OR (currency ~ '^[A-Z]{3}$' AND currency_exponent BETWEEN 0 AND 8))",
            name="valid_currency",
        ),
        CheckConstraint(
            "verified_net_minor IS NULL OR (verified_net_minor >= 0 AND currency IS NOT NULL)",
            name="net",
        ),
        CheckConstraint(
            "(ledger_generation IS NULL) = (receipt_ordinal IS NULL) "
            "AND (ledger_generation IS NULL OR (ledger_generation >= 1 AND receipt_ordinal >= 0)) "
            "AND identity_seq >= 0",
            name="watermarks",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(BigInteger)
    conversion_id: Mapped[UUID] = mapped_column(Uuid)
    model_version_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    basis: Mapped[str | None] = mapped_column(String(24))
    causes: Mapped[list[str]] = mapped_column(ARRAY(String(24)))
    currency: Mapped[str | None] = mapped_column(String(3))
    currency_exponent: Mapped[int | None] = mapped_column(SmallInteger)
    verified_net_minor: Mapped[int | None] = mapped_column(BigInteger)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ledger_generation: Mapped[int | None] = mapped_column(BigInteger)
    receipt_ordinal: Mapped[int | None] = mapped_column(BigInteger)
    identity_seq: Mapped[int] = mapped_column(BigInteger)
    excluded_touchpoint_ids: Mapped[list[UUID | None]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    excluded_reasons: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), server_default=text("'{}'::varchar[]")
    )
    touch_bound_exceeded: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# The allocation rows of one run: every eligible touch in the engine's stable order (credited or
# not), or one unknown row.
# SELECT run_id, ordinal, credited, recipient, basis, position, share_numerator,
#        share_denominator, amount_minor, campaign_ref, content_ref, link_ref
# FROM public.attribution_allocations
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
#   AND run_id = '00000000-0000-0000-0000-000000000009'::uuid ORDER BY ordinal;
class AttributionAllocation(Base):
    __tablename__ = "attribution_allocations"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("attribution_allocations", "run_id", "attribution_runs"),
        UniqueConstraint("run_id", "ordinal", name="uq_attribution_allocations_ordinal"),
        Index(
            "ix_attribution_allocations_touchpoint",
            "client_id",
            "touchpoint_id",
            postgresql_where=text("touchpoint_id IS NOT NULL"),
        ),
        CheckConstraint(f"recipient IN ({RECIPIENTS})", name="valid_recipient"),
        CheckConstraint(f"basis IN ({BASES})", name="valid_basis"),
        CheckConstraint(
            f"evidence_class IS NULL OR evidence_class IN ({EVIDENCE_CLASSES})",
            name="valid_evidence_class",
        ),
        CheckConstraint(f"source IS NULL OR source IN ({SOURCES})", name="valid_source"),
        CheckConstraint(
            "ordinal >= 1 AND position >= 0 AND share_numerator >= 0 AND share_denominator > 0 "
            "AND (amount_minor IS NULL OR amount_minor >= 0)",
            name="positions",
        ),
        CheckConstraint("credited = (share_numerator > 0)", name="credited"),
        CheckConstraint("credited OR amount_minor IS NULL", name="uncredited_amount"),
        CheckConstraint(
            "(recipient = 'unknown') = (position = 0) AND (recipient <> 'unknown' "
            "OR (touchpoint_id IS NULL AND evidence_class IS NULL AND occurred_at IS NULL "
            "AND source IS NULL AND campaign_ref IS NULL AND content_ref IS NULL "
            "AND link_ref IS NULL)) AND (recipient = 'unknown' OR evidence_class IS NOT NULL)",
            name="touch_shape",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    ordinal: Mapped[int] = mapped_column(Integer)
    credited: Mapped[bool] = mapped_column(Boolean)
    recipient: Mapped[str] = mapped_column(String(8))
    basis: Mapped[str] = mapped_column(String(24))
    position: Mapped[int] = mapped_column(Integer)
    share_numerator: Mapped[int] = mapped_column(BigInteger)
    share_denominator: Mapped[int] = mapped_column(BigInteger)
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    touchpoint_id: Mapped[UUID | None] = mapped_column(Uuid)
    evidence_class: Mapped[str | None] = mapped_column(String(24))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(16))
    campaign_ref: Mapped[str | None] = mapped_column(String(256))
    content_ref: Mapped[str | None] = mapped_column(String(256))
    link_ref: Mapped[UUID | None] = mapped_column(Uuid)


# The signed credit changes of one run: the reporting ledger of a model version.
# SELECT model_version_id, effective_at, recipient, campaign_ref, delta_share_numerator,
#        delta_share_denominator, delta_minor, currency, recorded_at
# FROM public.attribution_credit_changes
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY recorded_at DESC, id LIMIT 100;
class AttributionCreditChange(Base):
    __tablename__ = "attribution_credit_changes"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("attribution_credit_changes", "run_id", "attribution_runs"),
        _scoped("attribution_credit_changes", "model_version_id", "attribution_model_versions"),
        UniqueConstraint("run_id", "ordinal", name="uq_attribution_credit_changes_ordinal"),
        Index(
            "ix_attribution_credit_changes_reporting",
            "client_id",
            "model_version_id",
            "effective_at",
        ),
        Index("ix_attribution_credit_changes_generation", "client_id", "generation"),
        Index(
            "ix_attribution_credit_changes_touchpoint",
            "client_id",
            "touchpoint_id",
            postgresql_where=text("touchpoint_id IS NOT NULL"),
        ),
        CheckConstraint("conversion_kind IN ('sale', 'lead')", name="valid_kind"),
        CheckConstraint(f"recipient IN ({RECIPIENTS})", name="valid_recipient"),
        CheckConstraint(f"source IS NULL OR source IN ({SOURCES})", name="valid_source"),
        CheckConstraint(
            "ordinal >= 1 AND generation >= 1 AND delta_share_denominator > 0",
            name="positions",
        ),
        CheckConstraint(
            "(conversion_kind = 'sale') = (delta_minor IS NOT NULL) "
            "AND (delta_minor IS NULL) = (currency IS NULL) "
            "AND (currency IS NULL) = (currency_exponent IS NULL) "
            "AND (currency IS NULL OR (currency ~ '^[A-Z]{3}$' "
            "AND currency_exponent BETWEEN 0 AND 8))",
            name="money_shape",
        ),
        CheckConstraint(
            "delta_share_numerator <> 0 OR coalesce(delta_minor, 0) <> 0", name="nonzero"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    model_version_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(BigInteger)
    ordinal: Mapped[int] = mapped_column(Integer)
    conversion_kind: Mapped[str] = mapped_column(String(8))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recipient: Mapped[str] = mapped_column(String(8))
    touchpoint_id: Mapped[UUID | None] = mapped_column(Uuid)
    source: Mapped[str | None] = mapped_column(String(16))
    campaign_ref: Mapped[str | None] = mapped_column(String(256))
    content_ref: Mapped[str | None] = mapped_column(String(256))
    link_ref: Mapped[UUID | None] = mapped_column(Uuid)
    delta_share_numerator: Mapped[int] = mapped_column(BigInteger)
    delta_share_denominator: Mapped[int] = mapped_column(BigInteger)
    delta_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    currency_exponent: Mapped[int | None] = mapped_column(SmallInteger)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# The consumer state of one client: the published generation and checkpoint, and the unit of
# work in progress. Every update increments version, the compare-and-swap token.
# SELECT client_id, version, generation, status, ledger_generation, receipt_ordinal,
#        identity_seq, unit_kind, staging_generation, failure_code, published_at
# FROM public.attribution_consumer_state
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid;
class AttributionConsumerState(Base):
    __tablename__ = "attribution_consumer_state"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        CheckConstraint("status IN ('ready', 'building', 'failed')", name="valid_status"),
        CheckConstraint(
            "unit_kind IS NULL OR unit_kind IN ('incremental', 'rebuild')", name="valid_unit_kind"
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z_]{0,39}$'", name="valid_failure"
        ),
        CheckConstraint("status <> 'ready' OR generation >= 1", name="ready_generation"),
        CheckConstraint("(status = 'failed') = (failure_code IS NOT NULL)", name="failure"),
        CheckConstraint(
            "(unit_kind IS NOT DISTINCT FROM 'rebuild') = (staging_generation IS NOT NULL) "
            "AND (unit_kind IS DISTINCT FROM 'rebuild' OR status <> 'ready') "
            "AND (staging_generation IS NULL OR staging_generation > generation)",
            name="staging",
        ),
        CheckConstraint(
            "(unit_kind IS NULL) = (target_ledger_generation IS NULL) "
            "AND (unit_kind IS NULL) = (target_receipt_ordinal IS NULL) "
            "AND (unit_kind IS NULL) = (target_identity_seq IS NULL) "
            "AND (unit_kind IS NULL) = (target_model_set_digest IS NULL) "
            "AND (unit_kind IS NULL) = (unit_started_at IS NULL) "
            "AND (unit_kind IS NOT NULL OR progress_key IS NULL)",
            name="unit",
        ),
        CheckConstraint(
            "version >= 0 AND generation >= 0 AND ledger_generation >= 0 "
            "AND receipt_ordinal >= 0 AND identity_seq >= 0 AND scrub_epoch >= 0",
            name="counters",
        ),
        CheckConstraint(
            f"(model_set_digest IS NULL OR model_set_digest {HEX64}) "
            f"AND (target_model_set_digest IS NULL OR target_model_set_digest {HEX64}) "
            f"AND (progress_key IS NULL OR progress_key {HEX64}) "
            f"AND (sweep_after_key IS NULL OR sweep_after_key {HEX64})",
            name="digests",
        ),
    )

    client_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")
    generation: Mapped[int] = mapped_column(BigInteger, server_default="0")
    status: Mapped[str] = mapped_column(String(16), server_default="building")
    ledger_generation: Mapped[int] = mapped_column(BigInteger, server_default="0")
    receipt_ordinal: Mapped[int] = mapped_column(BigInteger, server_default="0")
    identity_seq: Mapped[int] = mapped_column(BigInteger, server_default="0")
    model_set_digest: Mapped[str | None] = mapped_column(String(64))
    unit_kind: Mapped[str | None] = mapped_column(String(16))
    staging_generation: Mapped[int | None] = mapped_column(BigInteger)
    target_ledger_generation: Mapped[int | None] = mapped_column(BigInteger)
    target_receipt_ordinal: Mapped[int | None] = mapped_column(BigInteger)
    target_identity_seq: Mapped[int | None] = mapped_column(BigInteger)
    target_model_set_digest: Mapped[str | None] = mapped_column(String(64))
    unit_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_key: Mapped[str | None] = mapped_column(String(64))
    sweep_after_key: Mapped[str | None] = mapped_column(String(64))
    scrub_epoch: Mapped[int] = mapped_column(BigInteger, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
