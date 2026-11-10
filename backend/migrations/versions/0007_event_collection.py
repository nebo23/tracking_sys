"""Event collection, consent, and erasure

Revision ID: 0007_event_collection
Revises: 0006_account_closure
Created: 2026-11-10

Specification 004 (D-027 decisions 2 and 8). Adds the nine client-scoped collection tables,
the immutable service_credentials.kind (existing keys become "read"), and the audit actions of
source, form, and erasure administration. tracking_app receives only the listed table and
column privileges: consent records and tombstones are never updated, and deletion is limited
to the erasure stores. Its table-wide UPDATE on service_credentials narrows to status and
updated_at, the only columns any code changes, so a key's kind cannot change. tracking_lifecycle
may read and delete expired events, counters, retired secrets, and inactive subjects with their
consent records; it cannot reach tombstones, deletion requests, sources, or forms. The
downgrade refuses populated 004 state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0007_event_collection"
down_revision: str | Sequence[str] | None = "0006_account_closure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLIENT = ["client_workspaces.agency_id", "client_workspaces.id"]
SUBJECT = [
    "collection_subjects.agency_id",
    "collection_subjects.client_id",
    "collection_subjects.id",
]
SOURCE = ["ingestion_sources.agency_id", "ingestion_sources.client_id", "ingestion_sources.id"]
HEX64 = "~ '^[0-9a-f]{64}$'"
TABLES = (
    "deletion_tombstones",
    "deletion_requests",
    "event_diagnostics",
    "collected_events",
    "consent_records",
    "collection_subjects",
    "collection_forms",
    "ingestion_source_secrets",
    "ingestion_sources",
)
PREVIOUS_ACTIONS = (
    "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
    "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
    "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
    "'credential.created', 'credential.revoked')"
)
NEW_ACTIONS = ("source.created", "source.updated", "source.secret_rotated", "form.updated")
NEW_ACTIONS += ("deletion.requested",)
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'source', 'form', 'deletion_request')"
RUNTIME_GRANTS = (
    "GRANT SELECT, INSERT ON ingestion_sources, ingestion_source_secrets, collection_forms, "
    "collection_subjects, consent_records, collected_events, event_diagnostics, "
    "deletion_requests, deletion_tombstones TO tracking_app",
    "GRANT UPDATE (name, status, allowed_origins, notice_sha256, updated_at) "
    "ON ingestion_sources TO tracking_app",
    "GRANT UPDATE (retires_at) ON ingestion_source_secrets TO tracking_app",
    "GRANT UPDATE (version, fields, status, updated_at) ON collection_forms TO tracking_app",
    "GRANT UPDATE (last_activity_at) ON collection_subjects TO tracking_app",
    "GRANT UPDATE (channel, source_id, credential_id, trust_rank, occurred_at, "
    "last_received_at, revision, payload, fingerprint, consent_basis, traffic_label, "
    "policy_version, conflict_count, last_conflict_at) ON collected_events TO tracking_app",
    "GRANT UPDATE (count) ON event_diagnostics TO tracking_app",
    "GRANT UPDATE (status, completed_at, target_outcomes) ON deletion_requests TO tracking_app",
    "GRANT DELETE ON collection_subjects, consent_records, collected_events TO tracking_app",
    "REVOKE UPDATE ON service_credentials FROM tracking_app",
    "GRANT UPDATE (status, updated_at) ON service_credentials TO tracking_app",
)
LIFECYCLE_TABLES = (
    "collected_events, event_diagnostics, ingestion_source_secrets, consent_records, "
    "collection_subjects"
)


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _scope() -> list[sa.Column]:
    return [
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


def _client_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id"], CLIENT, name=op.f(f"fk_{table}_agency_id_client_workspaces")
    )


def upgrade() -> None:
    op.create_table(
        "ingestion_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("creator_membership_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=True),
        sa.Column("allowed_origins", postgresql.ARRAY(sa.String(length=200)), nullable=True),
        sa.Column("notice_sha256", sa.String(length=64), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "kind <> 'browser' OR (public_key IS NOT NULL AND notice_sha256 IS NOT NULL "
            "AND allowed_origins IS NOT NULL AND cardinality(allowed_origins) BETWEEN 1 AND 10)",
            name=op.f("ck_ingestion_sources_browser_configuration"),
        ),
        sa.CheckConstraint(
            "kind <> 'webhook' OR (public_key IS NULL AND notice_sha256 IS NULL "
            "AND allowed_origins IS NULL)",
            name=op.f("ck_ingestion_sources_webhook_configuration"),
        ),
        sa.CheckConstraint(
            "kind IN ('browser', 'webhook')", name=op.f("ck_ingestion_sources_valid_kind")
        ),
        sa.CheckConstraint(
            f"notice_sha256 {HEX64}", name=op.f("ck_ingestion_sources_notice_digest")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')", name=op.f("ck_ingestion_sources_valid_status")
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0", name=op.f("ck_ingestion_sources_name_not_blank")
        ),
        _client_fk("ingestion_sources"),
        sa.ForeignKeyConstraint(
            ["agency_id", "creator_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f("fk_ingestion_sources_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_sources")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_ingestion_sources_scope"),
        sa.UniqueConstraint("public_key", name=op.f("uq_ingestion_sources_public_key")),
    )
    op.create_index(
        "ix_ingestion_sources_agency_client", "ingestion_sources", ["agency_id", "client_id"]
    )
    op.create_table(
        "ingestion_source_secrets",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=False),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        _timestamp("created_at"),
        _timestamp("retires_at", nullable=True),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_ingestion_source_secrets_positive_version")
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "source_id"],
            SOURCE,
            name=op.f("fk_ingestion_source_secrets_agency_id_ingestion_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_source_secrets")),
        sa.UniqueConstraint("source_id", "version", name="uq_ingestion_source_secrets_version"),
    )
    op.create_table(
        "collection_forms",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("form_key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "form_key ~ '^[a-z0-9_-]{1,100}$'", name=op.f("ck_collection_forms_valid_form_key")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')", name=op.f("ck_collection_forms_valid_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_collection_forms_positive_version")),
        _client_fk("collection_forms"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_forms")),
        sa.UniqueConstraint("client_id", "form_key", name="uq_collection_forms_client_form"),
    )
    op.create_table(
        "collection_subjects",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        _timestamp("created_at"),
        _timestamp("last_activity_at"),
        sa.CheckConstraint(
            f"token_digest {HEX64}", name=op.f("ck_collection_subjects_token_digest")
        ),
        _client_fk("collection_subjects"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_subjects")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_collection_subjects_scope"),
        sa.UniqueConstraint("token_digest", name=op.f("uq_collection_subjects_token_digest")),
    )
    op.create_index(
        "ix_collection_subjects_client_activity",
        "collection_subjects",
        ["client_id", "last_activity_at"],
    )
    op.create_table(
        "consent_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("jurisdiction_profile", sa.String(length=8), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("notice_sha256", sa.String(length=64), nullable=False),
        _timestamp("received_at"),
        _timestamp("captured_at", nullable=True),
        _timestamp("expires_at", nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "jurisdiction_profile = 'J1'", name=op.f("ck_consent_records_enabled_profile")
        ),
        sa.CheckConstraint(f"notice_sha256 {HEX64}", name=op.f("ck_consent_records_notice_digest")),
        sa.CheckConstraint(
            "purpose IN ('analytics.first_party', 'attribution', 'identity_link', "
            "'ads.measurement', 'ads.personalization', 'sale_or_share')",
            name=op.f("ck_consent_records_valid_purpose"),
        ),
        sa.CheckConstraint(
            "source <> 'gpc' OR (state <> 'granted' AND purpose IN "
            "('sale_or_share', 'ads.measurement', 'ads.personalization'))",
            name=op.f("ck_consent_records_gpc_denies_only"),
        ),
        sa.CheckConstraint(
            "source IN ('tracker_banner', 'external_cmp', 'gpc', 'api', 'admin_import')",
            name=op.f("ck_consent_records_valid_source"),
        ),
        sa.CheckConstraint(
            "state IN ('granted', 'denied', 'withdrawn')",
            name=op.f("ck_consent_records_valid_state"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "subject_id"],
            SUBJECT,
            name=op.f("fk_consent_records_agency_id_collection_subjects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_records")),
    )
    op.create_index(
        "ix_consent_records_subject_purpose",
        "consent_records",
        ["subject_id", "purpose", "received_at", "id"],
    )
    op.create_table(
        "collected_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("trust_rank", sa.SmallInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _timestamp("first_received_at"),
        _timestamp("last_received_at"),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("consent_basis", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("traffic_label", sa.String(length=16), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("conflict_count", sa.Integer(), server_default="0", nullable=False),
        _timestamp("last_conflict_at", nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(channel = 'server' AND credential_id IS NOT NULL AND source_id IS NULL "
            "AND trust_rank = 2) OR (channel = 'webhook' AND source_id IS NOT NULL "
            "AND credential_id IS NULL AND trust_rank = 2) OR (channel = 'browser' "
            "AND source_id IS NOT NULL AND credential_id IS NULL AND trust_rank = 1)",
            name=op.f("ck_collected_events_valid_channel"),
        ),
        sa.CheckConstraint(
            "event_type IN ('page_view', 'link_click', 'form_submit', 'lead_signal', "
            "'purchase_signal')",
            name=op.f("ck_collected_events_valid_event_type"),
        ),
        sa.CheckConstraint(f"fingerprint {HEX64}", name=op.f("ck_collected_events_fingerprint")),
        sa.CheckConstraint(
            "traffic_label IN ('unclassified', 'bot_suspected', 'internal')",
            name=op.f("ck_collected_events_valid_traffic_label"),
        ),
        sa.CheckConstraint(
            "revision >= 1 AND conflict_count >= 0",
            name=op.f("ck_collected_events_valid_counters"),
        ),
        _client_fk("collected_events"),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "subject_id"],
            SUBJECT,
            name=op.f("fk_collected_events_agency_id_collection_subjects"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "source_id"],
            SOURCE,
            name=op.f("fk_collected_events_agency_id_ingestion_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "credential_id"],
            ["service_credentials.agency_id", "service_credentials.id"],
            name=op.f("fk_collected_events_agency_id_service_credentials"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collected_events")),
        sa.UniqueConstraint("client_id", "event_id", name="uq_collected_events_client_event"),
    )
    op.create_index(
        "ix_collected_events_client_received",
        "collected_events",
        ["client_id", "first_received_at", "id"],
    )
    op.create_index("ix_collected_events_expires_at", "collected_events", ["expires_at"])
    op.create_index("ix_collected_events_subject_id", "collected_events", ["subject_id"])
    op.create_table(
        "event_diagnostics",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "channel IN ('browser', 'server', 'webhook', 'consent', 'erasure')",
            name=op.f("ck_event_diagnostics_valid_channel"),
        ),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'duplicate', 'conflict', 'upgraded', 'rejected', "
            "'suppressed', 'minimized')",
            name=op.f("ck_event_diagnostics_valid_outcome"),
        ),
        sa.CheckConstraint(
            "reason ~ '^[a-z_]{1,40}$'", name=op.f("ck_event_diagnostics_valid_reason")
        ),
        sa.CheckConstraint("count >= 0", name=op.f("ck_event_diagnostics_nonnegative_count")),
        _client_fk("event_diagnostics"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_diagnostics")),
        sa.UniqueConstraint(
            "client_id", "day", "channel", "outcome", "reason", name="uq_event_diagnostics_key"
        ),
    )
    op.create_index("ix_event_diagnostics_day", "event_diagnostics", ["day"])
    op.create_table(
        "deletion_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("requester_kind", sa.String(length=24), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("scope_kind", sa.String(length=16), server_default="subject", nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("objected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _timestamp("received_at"),
        _timestamp("completed_at", nullable=True),
        sa.Column(
            "target_outcomes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(requester_kind = 'agency_admin') = (requested_by_user_id IS NOT NULL)",
            name=op.f("ck_deletion_requests_requester_user"),
        ),
        sa.CheckConstraint(
            "requester_kind IN ('agency_admin', 'data_subject')",
            name=op.f("ck_deletion_requests_valid_requester"),
        ),
        sa.CheckConstraint("scope_kind = 'subject'", name=op.f("ck_deletion_requests_valid_scope")),
        sa.CheckConstraint(
            "status IN ('received', 'verifying', 'accepted', 'rejected', "
            "'paused_for_clarification', 'on_hold', 'in_progress', 'completed', "
            "'partially_completed', 'verified')",
            name=op.f("ck_deletion_requests_valid_status"),
        ),
        _client_fk("deletion_requests"),
        sa.ForeignKeyConstraint(
            ["agency_id", "requested_by_user_id"],
            ["agency_memberships.agency_id", "agency_memberships.user_id"],
            name=op.f("fk_deletion_requests_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deletion_requests")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_deletion_requests_scope"),
    )
    op.create_index(
        "ix_deletion_requests_client_received",
        "deletion_requests",
        ["client_id", "received_at", "id"],
    )
    op.create_table(
        "deletion_tombstones",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope(),
        sa.Column("deletion_request_id", sa.Uuid(), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), server_default="subject", nullable=False),
        sa.Column("match_type", sa.String(length=16), nullable=False),
        sa.Column("match_key", sa.LargeBinary(), nullable=False),
        sa.Column("match_key_id", sa.String(length=32), nullable=False),
        _timestamp("effective_at"),
        sa.Column("objected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "match_type IN ('subject_token', 'event_id')",
            name=op.f("ck_deletion_tombstones_valid_match_type"),
        ),
        sa.CheckConstraint(
            "scope_kind = 'subject'", name=op.f("ck_deletion_tombstones_valid_scope")
        ),
        sa.CheckConstraint(
            "octet_length(match_key) = 32", name=op.f("ck_deletion_tombstones_match_key_length")
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "deletion_request_id"],
            ["deletion_requests.agency_id", "deletion_requests.client_id", "deletion_requests.id"],
            name=op.f("fk_deletion_tombstones_agency_id_deletion_requests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deletion_tombstones")),
    )
    op.create_index(
        "ix_deletion_tombstones_match",
        "deletion_tombstones",
        ["client_id", "match_type", "match_key"],
    )
    op.add_column(
        "service_credentials",
        sa.Column("kind", sa.String(length=16), server_default="read", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_service_credentials_valid_kind"),
        "service_credentials",
        "kind IN ('read', 'ingest')",
    )
    op.drop_constraint(op.f("ck_audit_events_valid_action"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_valid_action"), "audit_events", ACTIONS)
    op.drop_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", RESOURCES)
    for statement in RUNTIME_GRANTS:
        op.execute(statement)
    op.execute(f"GRANT SELECT, DELETE ON {LIFECYCLE_TABLES} TO tracking_lifecycle")


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"LOCK TABLE {', '.join(TABLES)}, service_credentials, audit_events "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    populated = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
    actions = ", ".join(f"'{item}'" for item in NEW_ACTIONS)
    if connection.execute(
        sa.text(
            f"SELECT {populated} "
            "OR EXISTS (SELECT 1 FROM service_credentials WHERE kind <> 'read') "
            f"OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
        )
    ).scalar_one():
        raise RuntimeError("Refuse to remove populated event collection state; use a forward fix.")
    op.execute(f"REVOKE SELECT, DELETE ON {LIFECYCLE_TABLES} FROM tracking_lifecycle")
    op.execute("REVOKE UPDATE (status, updated_at) ON service_credentials FROM tracking_app")
    op.execute("GRANT UPDATE ON service_credentials TO tracking_app")
    op.drop_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_resource"), "audit_events", PREVIOUS_RESOURCES
    )
    op.drop_constraint(op.f("ck_audit_events_valid_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_action"), "audit_events", PREVIOUS_ACTIONS
    )
    op.drop_constraint(
        op.f("ck_service_credentials_valid_kind"), "service_credentials", type_="check"
    )
    op.drop_column("service_credentials", "kind")
    for table in TABLES:
        op.drop_table(table)
