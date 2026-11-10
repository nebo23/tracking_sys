"""Event collection, consent, and erasure state (specification 004, D-027).

Every table is scoped by agency and client through composite foreign keys, so a row can never
reference a subject, source, or request of another client. Consent records and tombstones are
never updated by the runtime; erasure deletes subject data and inserts tombstones atomically.
Reference queries below are manual read-only diagnostics for an authorized operator; replace
the synthetic literals before use. Token digests, sealed secrets, and match keys are omitted.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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
from app.models.tenancy import Entity

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])
HEX64 = "~ '^[0-9a-f]{64}$'"


# Configured intake source of one client: a browser source routed by a non-secret public key
# and limited to exact Origins, or a webhook source verified with a sealed signing secret.
# SELECT id, kind, name, status, allowed_origins, created_at
# FROM public.ingestion_sources
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at, id LIMIT 100;
class IngestionSource(Entity, Base):
    __tablename__ = "ingestion_sources"
    __table_args__ = (
        UniqueConstraint("agency_id", "client_id", "id", name="uq_ingestion_sources_scope"),
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "creator_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        CheckConstraint("kind IN ('browser', 'webhook')", name="valid_kind"),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "kind <> 'browser' OR (public_key IS NOT NULL AND notice_sha256 IS NOT NULL "
            "AND allowed_origins IS NOT NULL AND cardinality(allowed_origins) BETWEEN 1 AND 10)",
            name="browser_configuration",
        ),
        CheckConstraint(
            "kind <> 'webhook' OR (public_key IS NULL AND notice_sha256 IS NULL "
            "AND allowed_origins IS NULL)",
            name="webhook_configuration",
        ),
        CheckConstraint(f"notice_sha256 {HEX64}", name="notice_digest"),
        Index("ix_ingestion_sources_agency_client", "agency_id", "client_id"),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    creator_membership_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    public_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    allowed_origins: Mapped[list[str] | None] = mapped_column(ARRAY(String(200)))
    notice_sha256: Mapped[str | None] = mapped_column(String(64))


# Sealed webhook signing secret versions (token_secrets envelope under the D-025 keyring). The
# newest unretired version signs; a previous version stays valid until retires_at.
# SELECT id, source_id, version, kek_id, created_at, retires_at
# FROM public.ingestion_source_secrets
# WHERE source_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY version DESC LIMIT 2;
class IngestionSourceSecret(Base):
    __tablename__ = "ingestion_source_secrets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "source_id"],
            ["ingestion_sources.agency_id", "ingestion_sources.client_id", "ingestion_sources.id"],
        ),
        UniqueConstraint("source_id", "version", name="uq_ingestion_source_secrets_version"),
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


# Registered form of one client: field descriptors mapped to the 004 classes (form.option,
# form.code, form.quantity) with option lists. Unmapped fields are dropped at ingestion.
# SELECT id, form_key, version, status, updated_at
# FROM public.collection_forms
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY form_key LIMIT 100;
class CollectionForm(Entity, Base):
    __tablename__ = "collection_forms"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("client_id", "form_key", name="uq_collection_forms_client_form"),
        CheckConstraint("form_key ~ '^[a-z0-9_-]{1,100}$'", name="valid_form_key"),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
        CheckConstraint("version >= 1", name="positive_version"),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    form_key: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default="active")


# Opaque pseudonymous subject of one client, created only by an explicit consent grant. Only
# the SHA-256 digest of its sbj_ bearer token is stored.
# SELECT id, created_at, last_activity_at
# FROM public.collection_subjects
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY last_activity_at LIMIT 100;
class CollectionSubject(Base):
    __tablename__ = "collection_subjects"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_collection_subjects_scope"),
        CheckConstraint(f"token_digest {HEX64}", name="token_digest"),
        Index("ix_collection_subjects_client_activity", "client_id", "last_activity_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Append-only consent choice of one subject (the 003 ConsentRecord contract). received_at comes
# from the database clock and orders records; captured_at is the untrusted client time.
# SELECT id, purpose, state, source, policy_version, received_at, expires_at
# FROM public.consent_records
# WHERE subject_id = '00000000-0000-0000-0000-000000000010'::uuid
# ORDER BY received_at DESC, id DESC LIMIT 100;
class StoredConsentRecord(Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "subject_id"],
            [
                "collection_subjects.agency_id",
                "collection_subjects.client_id",
                "collection_subjects.id",
            ],
        ),
        CheckConstraint(
            "purpose IN ('analytics.first_party', 'attribution', 'identity_link', "
            "'ads.measurement', 'ads.personalization', 'sale_or_share')",
            name="valid_purpose",
        ),
        CheckConstraint("state IN ('granted', 'denied', 'withdrawn')", name="valid_state"),
        CheckConstraint(
            "source IN ('tracker_banner', 'external_cmp', 'gpc', 'api', 'admin_import')",
            name="valid_source",
        ),
        CheckConstraint("jurisdiction_profile = 'J1'", name="enabled_profile"),
        CheckConstraint(f"notice_sha256 {HEX64}", name="notice_digest"),
        CheckConstraint(
            "source <> 'gpc' OR (state <> 'granted' AND purpose IN "
            "('sale_or_share', 'ads.measurement', 'ads.personalization'))",
            name="gpc_denies_only",
        ),
        Index("ix_consent_records_subject_purpose", "subject_id", "purpose", "received_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32))
    jurisdiction_profile: Mapped[str] = mapped_column(String(8))
    policy_version: Mapped[str] = mapped_column(String(32))
    notice_sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid)


# One accepted event per client and sender event ID; the row is also the deduplication
# receipt. Upgrades replace the content and increase revision; conflicts only count. link_id is
# the optional same-client managed link the sender attributed the event to (005).
# SELECT id, event_id, event_type, channel, trust_rank, revision, first_received_at,
#        traffic_label, conflict_count
# FROM public.collected_events
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY first_received_at DESC, id DESC LIMIT 100;
class CollectedEvent(Base):
    __tablename__ = "collected_events"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "subject_id"],
            [
                "collection_subjects.agency_id",
                "collection_subjects.client_id",
                "collection_subjects.id",
            ],
        ),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "source_id"],
            ["ingestion_sources.agency_id", "ingestion_sources.client_id", "ingestion_sources.id"],
        ),
        ForeignKeyConstraint(
            ["agency_id", "credential_id"],
            ["service_credentials.agency_id", "service_credentials.id"],
        ),
        # Optional managed-link provenance (specification 005, D-033): a same-client link only.
        ForeignKeyConstraint(
            ["agency_id", "client_id", "link_id"],
            ["managed_links.agency_id", "managed_links.client_id", "managed_links.id"],
        ),
        UniqueConstraint("client_id", "event_id", name="uq_collected_events_client_event"),
        CheckConstraint(
            "event_type IN ('page_view', 'link_click', 'form_submit', 'lead_signal', "
            "'purchase_signal')",
            name="valid_event_type",
        ),
        CheckConstraint(
            "(channel = 'server' AND credential_id IS NOT NULL AND source_id IS NULL "
            "AND trust_rank = 2) OR (channel = 'webhook' AND source_id IS NOT NULL "
            "AND credential_id IS NULL AND trust_rank = 2) OR (channel = 'browser' "
            "AND source_id IS NOT NULL AND credential_id IS NULL AND trust_rank = 1)",
            name="valid_channel",
        ),
        CheckConstraint(
            "traffic_label IN ('unclassified', 'bot_suspected', 'internal')",
            name="valid_traffic_label",
        ),
        CheckConstraint(f"fingerprint {HEX64}", name="fingerprint"),
        CheckConstraint("revision >= 1 AND conflict_count >= 0", name="valid_counters"),
        Index("ix_collected_events_client_received", "client_id", "first_received_at", "id"),
        Index("ix_collected_events_subject_id", "subject_id"),
        Index("ix_collected_events_expires_at", "expires_at"),
        Index("ix_collected_events_link_id", "link_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    event_id: Mapped[UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[UUID | None] = mapped_column(Uuid)
    credential_id: Mapped[UUID | None] = mapped_column(Uuid)
    trust_rank: Mapped[int] = mapped_column(SmallInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    consent_basis: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    traffic_label: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[str] = mapped_column(String(32))
    conflict_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_conflict_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Validated, limited-trust link provenance; null for events without a link reference.
    link_id: Mapped[UUID | None] = mapped_column(Uuid)


# Daily outcome counters by channel and closed reason code; no subject, event ID, or content.
# SELECT day, channel, outcome, reason, count
# FROM public.event_diagnostics
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
#   AND day >= current_date - 7
# ORDER BY day, channel, outcome, reason LIMIT 500;
class EventDiagnostic(Base):
    __tablename__ = "event_diagnostics"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint(
            "client_id", "day", "channel", "outcome", "reason", name="uq_event_diagnostics_key"
        ),
        CheckConstraint(
            "channel IN ('browser', 'server', 'webhook', 'consent', 'erasure')",
            name="valid_channel",
        ),
        CheckConstraint(
            "outcome IN ('accepted', 'duplicate', 'conflict', 'upgraded', 'rejected', "
            "'suppressed', 'minimized')",
            name="valid_outcome",
        ),
        CheckConstraint("reason ~ '^[a-z_]{1,40}$'", name="valid_reason"),
        CheckConstraint("count >= 0", name="nonnegative_count"),
        Index("ix_event_diagnostics_day", "day"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    day: Mapped[date] = mapped_column(Date)
    channel: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(40))
    count: Mapped[int] = mapped_column(BigInteger)


# Erasure request of one client's subject (003 DeletionRequest) with per-store outcomes. It
# holds no identifier of the subject; the matching tombstones reference it.
# SELECT id, requester_kind, status, objected, received_at, completed_at, target_outcomes
# FROM public.deletion_requests
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY received_at DESC, id DESC LIMIT 100;
class SubjectDeletionRequest(Base):
    __tablename__ = "deletion_requests"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "requested_by_user_id"],
            ["agency_memberships.agency_id", "agency_memberships.user_id"],
        ),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_deletion_requests_scope"),
        CheckConstraint(
            "requester_kind IN ('agency_admin', 'data_subject')", name="valid_requester"
        ),
        CheckConstraint("scope_kind = 'subject'", name="valid_scope"),
        CheckConstraint(
            "status IN ('received', 'verifying', 'accepted', 'rejected', "
            "'paused_for_clarification', 'on_hold', 'in_progress', 'completed', "
            "'partially_completed', 'verified')",
            name="valid_status",
        ),
        CheckConstraint(
            "(requester_kind = 'agency_admin') = (requested_by_user_id IS NOT NULL)",
            name="requester_user",
        ),
        Index("ix_deletion_requests_client_received", "client_id", "received_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    requester_kind: Mapped[str] = mapped_column(String(24))
    requested_by_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    scope_kind: Mapped[str] = mapped_column(String(16), server_default="subject")
    status: Mapped[str] = mapped_column(String(32))
    objected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_outcomes: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )


# Keyed match value blocking a deleted subject token or a deleted event ID for the workspace
# lifetime (D-025, D-027). Insert-only for the runtime; unreachable by the lifecycle role.
# SELECT id, match_type, match_key_id, deletion_request_id, effective_at, objected
# FROM public.deletion_tombstones
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY effective_at DESC, id DESC LIMIT 100;
class StoredTombstone(Base):
    __tablename__ = "deletion_tombstones"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "deletion_request_id"],
            ["deletion_requests.agency_id", "deletion_requests.client_id", "deletion_requests.id"],
        ),
        CheckConstraint("scope_kind = 'subject'", name="valid_scope"),
        CheckConstraint("match_type IN ('subject_token', 'event_id')", name="valid_match_type"),
        CheckConstraint("octet_length(match_key) = 32", name="match_key_length"),
        Index("ix_deletion_tombstones_match", "client_id", "match_type", "match_key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    deletion_request_id: Mapped[UUID] = mapped_column(Uuid)
    scope_kind: Mapped[str] = mapped_column(String(16), server_default="subject")
    match_type: Mapped[str] = mapped_column(String(16))
    match_key: Mapped[bytes] = mapped_column(LargeBinary)
    match_key_id: Mapped[str] = mapped_column(String(32))
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    objected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
