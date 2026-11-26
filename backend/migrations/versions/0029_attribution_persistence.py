"""Persisted attribution: model versions, conversions, runs, allocations, credit changes

Revision ID: 0029_attribution_persistence
Revises: 0028_revenue_identity
Created: 2026-11-25

Specification 008-B (D-079, decisions D6, D9, D12 and D13;
specs/008-attribution-engine/design-008b.md section 2). Adds attribution_model_versions (per
client, immutable apart from the default flag, retirement and the idempotency record),
attribution_conversions (one verified sale or trusted lead with one owner, superseded instead of
mutated), attribution_runs (immutable revisions of one conversion under one model version),
attribution_allocations (one row per eligible touch or one unknown row), attribution_credit_changes
(the signed reporting ledger) and attribution_consumer_state (one row per client: the published
generation, its checkpoint and the unit of work in progress). Shares are exact numerators and
denominators and amounts stay in original-currency minor units. Rows hold identity person IDs,
collected event IDs and managed link IDs only, never a contact value, token or raw identifier.

tracking_app may insert and read every table and update only the publication and scrub columns;
it can never rewrite a share, amount, currency, provenance, revision or cause, and deletes
nothing. tracking_lifecycle may read, scrub, discard the rows of a failed staging generation and
maintain the consumer state while it applies identity expiry. Audit events accept the three
model administration actions and the attribution_model resource. The downgrade refuses any
stored attribution row or new audit value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0029_attribution_persistence"
down_revision: str | Sequence[str] | None = "0028_revenue_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONS = "attribution_model_versions"
CONVERSIONS = "attribution_conversions"
RUNS = "attribution_runs"
ALLOCATIONS = "attribution_allocations"
CHANGES = "attribution_credit_changes"
STATE = "attribution_consumer_state"
TABLES = (CHANGES, ALLOCATIONS, RUNS, CONVERSIONS, VERSIONS, STATE)  # children first
# The consumer state is derived bookkeeping (a removal path creates it to order its scrub
# against a worker); without any attribution row it holds nothing to preserve.
DATA_TABLES = TABLES[:-1]
NEW_ACTIONS = (
    "attribution.model_created",
    "attribution.model_default_set",
    "attribution.model_retired",
)
NEW_RESOURCE = "attribution_model"

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

CONVERSION_PUBLICATION = "status, superseded_generation, superseded_at, superseded_reason"
CONVERSION_SCRUB = "owner_person_id, lead_event_id, slot_key, conversion_key, scrubbed_at"
STATE_COLUMNS = (
    "version, generation, status, ledger_generation, receipt_ordinal, identity_seq, "
    "model_set_digest, unit_kind, staging_generation, target_ledger_generation, "
    "target_receipt_ordinal, target_identity_seq, target_model_set_digest, unit_started_at, "
    "progress_key, sweep_after_key, scrub_epoch, failure_code, published_at, updated_at"
)
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {VERSIONS}, {CONVERSIONS}, {RUNS}, {ALLOCATIONS}, {CHANGES}, "
    f"{STATE} TO tracking_app",
    f"GRANT UPDATE (is_default, status, retired_at, operations) ON {VERSIONS} TO tracking_app",
    f"GRANT UPDATE ({CONVERSION_PUBLICATION}, recheck_at, binding_id, {CONVERSION_SCRUB}) "
    f"ON {CONVERSIONS} TO tracking_app",
    f"GRANT UPDATE (excluded_touchpoint_ids) ON {RUNS} TO tracking_app",
    f"GRANT UPDATE (touchpoint_id, occurred_at) ON {ALLOCATIONS} TO tracking_app",
    f"GRANT UPDATE (touchpoint_id) ON {CHANGES} TO tracking_app",
    f"GRANT UPDATE ({STATE_COLUMNS}) ON {STATE} TO tracking_app",
)
LIFECYCLE_GRANTS = (
    f"GRANT SELECT ON {VERSIONS}, {CONVERSIONS}, {RUNS}, {ALLOCATIONS}, {CHANGES}, {STATE} "
    "TO tracking_lifecycle",
    f"GRANT INSERT ON {STATE} TO tracking_lifecycle",
    f"GRANT UPDATE ({STATE_COLUMNS}) ON {STATE} TO tracking_lifecycle",
    f"GRANT UPDATE ({CONVERSION_PUBLICATION}, {CONVERSION_SCRUB}) ON {CONVERSIONS} "
    "TO tracking_lifecycle",
    f"GRANT UPDATE (excluded_touchpoint_ids) ON {RUNS} TO tracking_lifecycle",
    f"GRANT UPDATE (touchpoint_id, occurred_at) ON {ALLOCATIONS} TO tracking_lifecycle",
    f"GRANT UPDATE (touchpoint_id) ON {CHANGES} TO tracking_lifecycle",
    f"GRANT DELETE ON {CONVERSIONS}, {RUNS}, {ALLOCATIONS}, {CHANGES} TO tracking_lifecycle",
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _swap(name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_audit_events_{name}"), "audit_events", type_="check")
    op.create_check_constraint(op.f(f"ck_audit_events_{name}"), "audit_events", condition)


def _time(name: str, *, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def _client_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id"],
        ["client_workspaces.agency_id", "client_workspaces.id"],
        name=op.f(f"fk_{table}_agency_id_client_workspaces"),
    )


def _scoped_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", column],
        [f"{target}.agency_id", f"{target}.client_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}"[:63],
    )


def _scope() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


def _base_actions() -> str:
    return (
        "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
        "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
        "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
        "'credential.created', 'credential.revoked', 'source.created', 'source.updated', "
        "'source.secret_rotated', 'form.updated', 'deletion.requested', "
        "'campaign.created', 'campaign.updated', 'content.created', 'content.updated', "
        "'template.created', 'template.updated', 'origin.created', 'origin.updated', "
        "'domain.created', 'domain.updated', 'domain.challenge_issued', 'domain.checked', "
        "'link.created', 'link.updated', 'connector.connected', 'connector.reconnected', "
        "'connector.disconnect_requested', 'destination.created', 'destination.updated', "
        "'delivery.requeued', 'delivery.dismissed', 'payment_source.created', "
        "'payment_source.updated', 'payment_source.secret_replaced', "
        "'revenue_import.committed', 'revenue.declared', 'integration.created', "
        "'integration.updated', 'integration.secret_replaced', 'crm_rule.created', "
        "'crm_rule.updated', 'whatsapp_number.created', 'whatsapp_number.updated', "
        "'identity.merged', 'identity.unmerged', 'identity.erased', 'identity.erasure_resolved', "
        "'revenue.reconciliation_reviewed', 'revenue.association_detached')"
    )


def _actions(extended: bool) -> str:
    base = _base_actions()
    if not extended:
        return base
    return base[:-1] + "".join(f", '{action}'" for action in NEW_ACTIONS) + ")"


RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule', 'whatsapp_number', 'identity_subject', 'revenue_issue', "
    "'revenue_association')"
)
NEW_RESOURCES = RESOURCES[:-1] + f", '{NEW_RESOURCE}')"


def _versions() -> None:
    table = VERSIONS
    op.create_table(
        table,
        *_scope(),
        sa.Column("version_key", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=16), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("rules", sa.String(length=16), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=True),
        sa.Column(
            "operations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _time("created_at", default=True),
        _time("retired_at", nullable=True),
        _check(table, "valid_model", f"model IN ({MODELS})"),
        _check(
            table,
            "valid_version_key",
            "version_key ~ '^(first_click|last_click|linear)_[0-9]{1,2}d_v[0-9]{1,6}$'",
        ),
        _check(
            table,
            "window",
            "window_seconds BETWEEN 86400 AND 7776000 AND window_seconds % 86400 = 0",
        ),
        _check(table, "valid_rules", "rules = '008-A.1'"),
        _check(table, "valid_status", "status IN ('active', 'retired')"),
        _check(table, "retirement", "(status = 'retired') = (retired_at IS NOT NULL)"),
        _check(table, "default_active", "NOT is_default OR status = 'active'"),
        _check(table, "operations", "jsonb_typeof(operations) = 'array'"),
        _client_fk(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f(f"fk_{table}_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name=f"uq_{table}_scope"),
        sa.UniqueConstraint("client_id", "version_key", name=f"uq_{table}_key"),
    )
    op.create_index(
        f"uq_{table}_default",
        table,
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index(
        f"uq_{table}_active_definition",
        table,
        ["client_id", "model", "window_seconds"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def _conversions() -> None:
    table = CONVERSIONS
    op.create_table(
        table,
        *_scope(),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("slot_key", sa.String(length=64), nullable=False),
        sa.Column("conversion_key", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=True),
        sa.Column("association_id", sa.Uuid(), nullable=True),
        sa.Column("binding_id", sa.Uuid(), nullable=True),
        sa.Column("source_account_id", sa.String(length=256), nullable=True),
        sa.Column("sale_operation_id", sa.String(length=256), nullable=True),
        sa.Column("lead_event_id", sa.Uuid(), nullable=True),
        _time("effective_at"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("superseded_generation", sa.BigInteger(), nullable=True),
        _time("superseded_at", nullable=True),
        sa.Column("superseded_reason", sa.String(length=24), nullable=True),
        _time("scrubbed_at", nullable=True),
        _time("recheck_at", nullable=True),
        _time("created_at", default=True),
        _check(table, "valid_kind", "kind IN ('sale', 'lead')"),
        _check(table, "valid_status", "status IN ('active', 'superseded')"),
        _check(
            table,
            "valid_superseded_reason",
            f"superseded_reason IS NULL OR superseded_reason IN ({SUPERSEDED_REASONS})",
        ),
        _check(table, "slot_key", f"slot_key {HEX64}"),
        _check(
            table,
            "conversion_key",
            "conversion_key ~ '^([0-9a-f]{64}[.][1-9][0-9]{0,8}|scrubbed[.][0-9a-f-]{36})$'",
        ),
        _check(table, "positive_generation", "generation >= 1"),
        _check(
            table,
            "kind_shape",
            "(kind = 'sale' AND source_account_id IS NOT NULL AND sale_operation_id IS NOT NULL "
            "AND lead_event_id IS NULL) OR (kind = 'lead' AND source_account_id IS NULL "
            "AND sale_operation_id IS NULL AND association_id IS NULL AND binding_id IS NULL)",
        ),
        _check(
            table,
            "lead_identity",
            "kind <> 'lead' OR scrubbed_at IS NOT NULL "
            "OR (lead_event_id IS NOT NULL AND owner_person_id IS NOT NULL)",
        ),
        _check(
            table,
            "supersession",
            "(superseded_generation IS NULL) = (superseded_at IS NULL) "
            "AND (superseded_at IS NULL) = (superseded_reason IS NULL) "
            "AND (status = 'active' OR superseded_generation IS NOT NULL) "
            "AND (superseded_generation IS NULL OR superseded_generation >= generation)",
        ),
        # D9: a scrubbed conversion keeps no person, lead event or person-derived key.
        _check(
            table,
            "scrubbed_minimal",
            "scrubbed_at IS NULL OR (owner_person_id IS NULL AND lead_event_id IS NULL "
            "AND conversion_key LIKE 'scrubbed.%')",
        ),
        _client_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name=f"uq_{table}_scope"),
        sa.UniqueConstraint("client_id", "conversion_key", name=f"uq_{table}_key"),
    )
    op.create_index(
        f"uq_{table}_open_slot",
        table,
        ["client_id", "slot_key"],
        unique=True,
        postgresql_where=sa.text("superseded_generation IS NULL"),
    )
    op.create_index(
        f"ix_{table}_owner",
        table,
        ["client_id", "owner_person_id"],
        postgresql_where=sa.text("owner_person_id IS NOT NULL"),
    )
    op.create_index(
        f"ix_{table}_lead_event",
        table,
        ["client_id", "lead_event_id"],
        postgresql_where=sa.text("lead_event_id IS NOT NULL"),
    )
    op.create_index(
        f"ix_{table}_recheck",
        table,
        ["client_id", "recheck_at"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(f"ix_{table}_generation", table, ["client_id", "generation"])


def _runs() -> None:
    table = RUNS
    op.create_table(
        table,
        *_scope(),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("conversion_id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("basis", sa.String(length=24), nullable=True),
        sa.Column("causes", postgresql.ARRAY(sa.String(length=24)), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("currency_exponent", sa.SmallInteger(), nullable=True),
        sa.Column("verified_net_minor", sa.BigInteger(), nullable=True),
        _time("window_start", nullable=True),
        _time("window_end", nullable=True),
        sa.Column("ledger_generation", sa.BigInteger(), nullable=True),
        sa.Column("receipt_ordinal", sa.BigInteger(), nullable=True),
        sa.Column("identity_seq", sa.BigInteger(), nullable=False),
        sa.Column(
            "excluded_touchpoint_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column(
            "excluded_reasons",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "touch_bound_exceeded", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        _time("recorded_at", default=True),
        _check(table, "valid_status", f"status IN ({RUN_STATUSES})"),
        _check(table, "valid_basis", f"basis IS NULL OR basis IN ({BASES})"),
        _check(
            table,
            "valid_causes",
            f"cardinality(causes) >= 1 AND causes <@ ARRAY[{CAUSES}]::varchar[]",
        ),
        _check(
            table,
            "valid_excluded",
            f"excluded_reasons <@ ARRAY[{EXCLUSIONS}]::varchar[] "
            "AND cardinality(excluded_reasons) = cardinality(excluded_touchpoint_ids)",
        ),
        _check(table, "positions", "revision >= 1 AND generation >= 1"),
        _check(
            table,
            "closing_shape",
            "(status = 'superseded') = (basis IS NULL) "
            "AND (status = 'superseded') = (window_end IS NULL) "
            "AND (window_start IS NULL) = (window_end IS NULL) "
            "AND (window_start IS NULL OR window_start <= window_end)",
        ),
        _check(
            table,
            "valid_currency",
            "(currency IS NULL) = (currency_exponent IS NULL) AND (currency IS NULL "
            "OR (currency ~ '^[A-Z]{3}$' AND currency_exponent BETWEEN 0 AND 8))",
        ),
        _check(
            table,
            "net",
            "verified_net_minor IS NULL OR (verified_net_minor >= 0 AND currency IS NOT NULL)",
        ),
        _check(
            table,
            "watermarks",
            "(ledger_generation IS NULL) = (receipt_ordinal IS NULL) "
            "AND (ledger_generation IS NULL OR (ledger_generation >= 1 AND receipt_ordinal >= 0)) "
            "AND identity_seq >= 0",
        ),
        _client_fk(table),
        _scoped_fk(table, "conversion_id", CONVERSIONS),
        _scoped_fk(table, "model_version_id", VERSIONS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name=f"uq_{table}_scope"),
        sa.UniqueConstraint(
            "client_id",
            "conversion_id",
            "model_version_id",
            "revision",
            name=f"uq_{table}_revision",
        ),
    )
    op.create_index(f"ix_{table}_generation", table, ["client_id", "generation"])
    op.create_index(
        f"ix_{table}_excluded_touchpoints",
        table,
        ["excluded_touchpoint_ids"],
        postgresql_using="gin",
    )


def _allocations() -> None:
    table = ALLOCATIONS
    op.create_table(
        table,
        *_scope(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("credited", sa.Boolean(), nullable=False),
        sa.Column("recipient", sa.String(length=8), nullable=False),
        sa.Column("basis", sa.String(length=24), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("share_numerator", sa.BigInteger(), nullable=False),
        sa.Column("share_denominator", sa.BigInteger(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("touchpoint_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_class", sa.String(length=24), nullable=True),
        _time("occurred_at", nullable=True),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("campaign_ref", sa.String(length=256), nullable=True),
        sa.Column("content_ref", sa.String(length=256), nullable=True),
        sa.Column("link_ref", sa.Uuid(), nullable=True),
        _check(table, "valid_recipient", f"recipient IN ({RECIPIENTS})"),
        _check(table, "valid_basis", f"basis IN ({BASES})"),
        _check(
            table,
            "valid_evidence_class",
            f"evidence_class IS NULL OR evidence_class IN ({EVIDENCE_CLASSES})",
        ),
        _check(table, "valid_source", f"source IS NULL OR source IN ({SOURCES})"),
        _check(
            table,
            "positions",
            "ordinal >= 1 AND position >= 0 AND share_numerator >= 0 AND share_denominator > 0 "
            "AND (amount_minor IS NULL OR amount_minor >= 0)",
        ),
        _check(table, "credited", "credited = (share_numerator > 0)"),
        _check(table, "uncredited_amount", "credited OR amount_minor IS NULL"),
        _check(
            table,
            "touch_shape",
            "(recipient = 'unknown') = (position = 0) AND (recipient <> 'unknown' "
            "OR (touchpoint_id IS NULL AND evidence_class IS NULL AND occurred_at IS NULL "
            "AND source IS NULL AND campaign_ref IS NULL AND content_ref IS NULL "
            "AND link_ref IS NULL)) AND (recipient = 'unknown' OR evidence_class IS NOT NULL)",
        ),
        _client_fk(table),
        _scoped_fk(table, "run_id", RUNS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("run_id", "ordinal", name=f"uq_{table}_ordinal"),
    )
    op.create_index(
        f"ix_{table}_touchpoint",
        table,
        ["client_id", "touchpoint_id"],
        postgresql_where=sa.text("touchpoint_id IS NOT NULL"),
    )


def _changes() -> None:
    table = CHANGES
    op.create_table(
        table,
        *_scope(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("conversion_kind", sa.String(length=8), nullable=False),
        _time("effective_at"),
        sa.Column("recipient", sa.String(length=8), nullable=False),
        sa.Column("touchpoint_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("campaign_ref", sa.String(length=256), nullable=True),
        sa.Column("content_ref", sa.String(length=256), nullable=True),
        sa.Column("link_ref", sa.Uuid(), nullable=True),
        sa.Column("delta_share_numerator", sa.BigInteger(), nullable=False),
        sa.Column("delta_share_denominator", sa.BigInteger(), nullable=False),
        sa.Column("delta_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("currency_exponent", sa.SmallInteger(), nullable=True),
        _time("recorded_at", default=True),
        _check(table, "valid_kind", "conversion_kind IN ('sale', 'lead')"),
        _check(table, "valid_recipient", f"recipient IN ({RECIPIENTS})"),
        _check(table, "valid_source", f"source IS NULL OR source IN ({SOURCES})"),
        _check(
            table, "positions", "ordinal >= 1 AND generation >= 1 AND delta_share_denominator > 0"
        ),
        _check(
            table,
            "money_shape",
            "(conversion_kind = 'sale') = (delta_minor IS NOT NULL) "
            "AND (delta_minor IS NULL) = (currency IS NULL) "
            "AND (currency IS NULL) = (currency_exponent IS NULL) "
            "AND (currency IS NULL OR (currency ~ '^[A-Z]{3}$' "
            "AND currency_exponent BETWEEN 0 AND 8))",
        ),
        _check(table, "nonzero", "delta_share_numerator <> 0 OR coalesce(delta_minor, 0) <> 0"),
        _client_fk(table),
        _scoped_fk(table, "run_id", RUNS),
        _scoped_fk(table, "model_version_id", VERSIONS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("run_id", "ordinal", name=f"uq_{table}_ordinal"),
    )
    op.create_index(
        f"ix_{table}_reporting", table, ["client_id", "model_version_id", "effective_at"]
    )
    op.create_index(f"ix_{table}_generation", table, ["client_id", "generation"])
    op.create_index(
        f"ix_{table}_touchpoint",
        table,
        ["client_id", "touchpoint_id"],
        postgresql_where=sa.text("touchpoint_id IS NOT NULL"),
    )


def _state() -> None:
    table = STATE
    op.create_table(
        table,
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="building", nullable=False),
        sa.Column("ledger_generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("receipt_ordinal", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("identity_seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("model_set_digest", sa.String(length=64), nullable=True),
        sa.Column("unit_kind", sa.String(length=16), nullable=True),
        sa.Column("staging_generation", sa.BigInteger(), nullable=True),
        sa.Column("target_ledger_generation", sa.BigInteger(), nullable=True),
        sa.Column("target_receipt_ordinal", sa.BigInteger(), nullable=True),
        sa.Column("target_identity_seq", sa.BigInteger(), nullable=True),
        sa.Column("target_model_set_digest", sa.String(length=64), nullable=True),
        _time("unit_started_at", nullable=True),
        sa.Column("progress_key", sa.String(length=64), nullable=True),
        sa.Column("sweep_after_key", sa.String(length=64), nullable=True),
        sa.Column("scrub_epoch", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("failure_code", sa.String(length=40), nullable=True),
        _time("published_at", nullable=True),
        _time("updated_at", default=True),
        _time("created_at", default=True),
        _check(table, "valid_status", "status IN ('ready', 'building', 'failed')"),
        _check(
            table, "valid_unit_kind", "unit_kind IS NULL OR unit_kind IN ('incremental', 'rebuild')"
        ),
        _check(
            table, "valid_failure", "failure_code IS NULL OR failure_code ~ '^[a-z][a-z_]{0,39}$'"
        ),
        _check(table, "ready_generation", "status <> 'ready' OR generation >= 1"),
        _check(table, "failure", "(status = 'failed') = (failure_code IS NOT NULL)"),
        _check(
            table,
            "staging",
            "(unit_kind IS NOT DISTINCT FROM 'rebuild') = (staging_generation IS NOT NULL) "
            "AND (unit_kind IS DISTINCT FROM 'rebuild' OR status <> 'ready') "
            "AND (staging_generation IS NULL OR staging_generation > generation)",
        ),
        _check(
            table,
            "unit",
            "(unit_kind IS NULL) = (target_ledger_generation IS NULL) "
            "AND (unit_kind IS NULL) = (target_receipt_ordinal IS NULL) "
            "AND (unit_kind IS NULL) = (target_identity_seq IS NULL) "
            "AND (unit_kind IS NULL) = (target_model_set_digest IS NULL) "
            "AND (unit_kind IS NULL) = (unit_started_at IS NULL) "
            "AND (unit_kind IS NOT NULL OR progress_key IS NULL)",
        ),
        _check(
            table,
            "counters",
            "version >= 0 AND generation >= 0 AND ledger_generation >= 0 "
            "AND receipt_ordinal >= 0 AND identity_seq >= 0 AND scrub_epoch >= 0",
        ),
        _check(
            table,
            "digests",
            f"(model_set_digest IS NULL OR model_set_digest {HEX64}) "
            f"AND (target_model_set_digest IS NULL OR target_model_set_digest {HEX64}) "
            f"AND (progress_key IS NULL OR progress_key {HEX64}) "
            f"AND (sweep_after_key IS NULL OR sweep_after_key {HEX64})",
        ),
        _client_fk(table),
        sa.PrimaryKeyConstraint("client_id", name=op.f(f"pk_{table}")),
    )


def upgrade() -> None:
    _swap("valid_action", _actions(True))
    _swap("valid_resource", NEW_RESOURCES)
    _versions()
    _conversions()
    _runs()
    _allocations()
    _changes()
    _state()
    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{action}'" for action in NEW_ACTIONS)
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in DATA_TABLES)
            + f" OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
            + f" OR EXISTS (SELECT 1 FROM audit_events WHERE resource_type = '{NEW_RESOURCE}')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove persisted attribution state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    for table in TABLES:
        op.drop_table(table)
    _swap("valid_resource", RESOURCES)
    _swap("valid_action", _actions(False))
