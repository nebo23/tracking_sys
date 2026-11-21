"""Connector connection lifecycle and synchronization state (specification 009, D-048, D-049).

Every table is scoped by agency and client, and every reference to a connection is the
composite (agency_id, client_id, id) key, so a transaction, secret, run, or record can never
point at another client's connection. Two clients may each connect the same external account;
their connections share no token, run, or record. Token rows are the TokenSecretReference
contract of D-025: the material columns are NULL exactly when the row is destroyed.
Reference queries below are manual read-only diagnostics for an authorized operator; replace
the synthetic literals before use. Sealed material and transaction digests are omitted.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
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

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])
MEMBERSHIP = ["agency_memberships.agency_id", "agency_memberships.id"]
CONNECTION_FK = (
    ["agency_id", "client_id", "connection_id"],
    [
        "connector_connections.agency_id",
        "connector_connections.client_id",
        "connector_connections.id",
    ],
)
MATERIAL = ("kek_id", "wrap_nonce", "wrapped_dek", "nonce", "ciphertext")
PROVIDERS = (
    "provider IN ('synthetic', 'synthetic_instagram', 'instagram', 'synthetic_youtube', "
    "'youtube', 'synthetic_meta_ads', 'synthetic_meta_capi', 'meta_ads', 'meta_capi')"
)
# 011-A (D8): media product types of Instagram and YouTube.
PRODUCT_TYPES = (
    "product_type IS NULL OR product_type IN ('FEED', 'REELS', 'STORY', 'SHORTS', "
    "'VIDEO_ON_DEMAND', 'LIVE_STREAM', 'UNSPECIFIED')"
)


def _time(nullable: bool = True, *, default: bool = False) -> Any:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now() if default else None,
        nullable=nullable,
    )


# One client's authorization of one provider account. The generation increases whenever
# credentials stop being usable (terminal failure, reconnect, disconnect); every worker write
# requires the generation its run was queued under. A disconnected row keeps only its outcome.
# SELECT id, provider, status, status_reason, connected_at, last_successful_sync_at,
#        revocation_status, destruction_status, purge_status, purge_due_at, disconnected_at
# FROM public.connector_connections
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at, id LIMIT 100;
class ConnectorConnection(Base):
    __tablename__ = "connector_connections"
    __table_args__ = (
        UniqueConstraint("agency_id", "client_id", "id", name="uq_connector_connections_scope"),
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(["agency_id", "created_by_membership_id"], MEMBERSHIP),
        ForeignKeyConstraint(["deletion_request_id"], ["connector_deletion_requests.id"]),
        CheckConstraint(PROVIDERS, name="valid_provider"),
        CheckConstraint(
            "status IN ('active', 'reconnect_required', 'disconnecting', 'disconnected')",
            name="valid_status",
        ),
        CheckConstraint(
            "status_reason IS NULL OR status_reason IN "
            "('credential_expired', 'provider_revoked', 'user_requested', 'deauthorized', "
            "'deletion_requested', 'authorization_lost', 'operator_purged')",
            name="valid_reason",
        ),
        CheckConstraint(
            "(revocation_status IS NULL OR revocation_status IN "
            "('pending', 'done', 'unsupported', 'failed', 'shared')) "
            "AND (destruction_status IS NULL OR destruction_status IN ('pending', 'done')) "
            "AND (purge_status IS NULL OR purge_status IN ('pending', 'done'))",
            name="valid_outcomes",
        ),
        CheckConstraint("generation >= 1 AND teardown_attempts >= 0", name="valid_counters"),
        CheckConstraint(
            "(status IN ('disconnecting', 'disconnected')) = "
            "(disconnect_requested_at IS NOT NULL AND purge_due_at IS NOT NULL "
            "AND revocation_status IS NOT NULL AND destruction_status IS NOT NULL "
            "AND purge_status IS NOT NULL)",
            name="teardown_state",
        ),
        CheckConstraint(
            "(status = 'disconnected') = (disconnected_at IS NOT NULL) "
            "AND (status <> 'disconnected' OR (external_account_id IS NULL "
            "AND account_label IS NULL AND destruction_status = 'done' "
            "AND purge_status = 'done' AND revocation_status <> 'pending'))",
            name="disconnected_state",
        ),
        CheckConstraint(
            "status = 'disconnected' OR external_account_id IS NOT NULL", name="account_present"
        ),
        CheckConstraint(
            "(status = 'reconnect_required') = (reconnect_required_since IS NOT NULL)",
            name="reconnect_since",
        ),
        CheckConstraint(
            "(agent_approved_at IS NULL) = (agent_disclosure IS NULL)", name="agent_approval"
        ),
        Index(
            "uq_connector_connections_live_account",
            "client_id",
            "provider",
            "external_account_id",
            unique=True,
            postgresql_where=text("status <> 'disconnected'"),
        ),
        Index("ix_connector_connections_agency_client", "agency_id", "client_id"),
        Index(
            "ix_connector_connections_disconnecting",
            "purge_due_at",
            postgresql_where=text("status = 'disconnecting'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(32))
    external_account_id: Mapped[str | None] = mapped_column(String(128))
    account_label: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), server_default="active")
    status_reason: Mapped[str | None] = mapped_column(String(24))
    generation: Mapped[int] = mapped_column(Integer, server_default="1")
    granted_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), server_default=text("'{}'::varchar[]")
    )
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = _time(False, default=True)
    updated_at: Mapped[datetime] = _time(False, default=True)
    connected_at: Mapped[datetime] = _time(False, default=True)
    last_successful_sync_at: Mapped[datetime | None] = _time()
    disconnect_requested_at: Mapped[datetime | None] = _time()
    purge_due_at: Mapped[datetime | None] = _time()
    disconnected_at: Mapped[datetime | None] = _time()
    revocation_status: Mapped[str | None] = mapped_column(String(16))
    destruction_status: Mapped[str | None] = mapped_column(String(16))
    purge_status: Mapped[str | None] = mapped_column(String(16))
    teardown_attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    teardown_lease_until: Mapped[datetime | None] = _time()
    # Provider account kind reported at connect or reconnect (009-C); cleared by the purge.
    account_kind: Mapped[str | None] = mapped_column(String(32))
    # 010-A: the data deletion request that started this connection's disconnect, if any.
    deletion_request_id: Mapped[UUID | None] = mapped_column(Uuid)
    # 011-A (D6): when the connection began to require reconnection, which starts its grace
    # period; set exactly while the status is reconnect_required.
    reconnect_required_since: Mapped[datetime | None] = _time()
    # 011-A (D11): when the label was last refreshed from the provider, for providers whose
    # labels are cleared after a period without refresh; NULL otherwise.
    account_label_refreshed_at: Mapped[datetime | None] = _time()
    # 011-A (D4, F1): the provider-reported end of the grant's refresh token.
    grant_expires_at: Mapped[datetime | None] = _time()
    # 011-A (D13): when the connect or latest reconnect approved the agency and the client's
    # members as agents, and the disclosure version approved. Kept after a disconnect.
    agent_approved_at: Mapped[datetime | None] = _time()
    agent_disclosure: Mapped[str | None] = mapped_column(String(64))
    # 014-A (D4): the day zone of the connection's account, for providers whose days follow
    # each account; cleared by the purge.
    day_zone: Mapped[str | None] = mapped_column(String(64))


# Single-use connect or reconnect authorization bound to the initiating membership, client,
# and browser session. A reconnect also records the connection and the generation it expects;
# a callback for a connection that moved on is refused. Neither the state nor the PKCE
# verifier is stored: only digests, and the verifier is derived from the raw state.
# SELECT id, purpose, connection_id, expected_generation, created_at, expires_at, consumed_at
# FROM public.connector_oauth_transactions
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
#   AND created_at >= now() - interval '1 day'
# ORDER BY created_at DESC, id LIMIT 100;
class ConnectorOAuthTransaction(Base):
    __tablename__ = "connector_oauth_transactions"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(["agency_id", "initiator_membership_id"], MEMBERSHIP),
        ForeignKeyConstraint(*CONNECTION_FK),
        CheckConstraint("purpose IN ('connect', 'reconnect')", name="valid_purpose"),
        CheckConstraint(
            "(purpose = 'connect' AND connection_id IS NULL AND expected_generation IS NULL) "
            "OR (purpose = 'reconnect' AND connection_id IS NOT NULL "
            "AND expected_generation IS NOT NULL)",
            name="reconnect_target",
        ),
        CheckConstraint("state_digest ~ '^[0-9a-f]{64}$'", name="state_digest"),
        CheckConstraint("binding_digest ~ '^[0-9a-f]{64}$'", name="binding_digest"),
        CheckConstraint(
            "(agent_approved_at IS NULL) = (agent_disclosure IS NULL)", name="agent_approval"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID | None] = mapped_column(Uuid)
    expected_generation: Mapped[int | None] = mapped_column(Integer)
    initiator_membership_id: Mapped[UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(16))
    state_digest: Mapped[str] = mapped_column(String(64), unique=True)
    binding_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _time(False, default=True)
    expires_at: Mapped[datetime] = _time(False)
    consumed_at: Mapped[datetime | None] = _time()
    # 011-A (D13): the agent approval the request carried, copied to the connection.
    agent_approved_at: Mapped[datetime | None] = _time()
    agent_disclosure: Mapped[str | None] = mapped_column(String(64))
    # 014 (D2): the ad account or dataset the connect request named, checked after the exchange.
    requested_account: Mapped[str | None] = mapped_column(String(32))


# Sealed access or refresh token versions of one connection (TokenSecretReference, D-025).
# At most one version per kind is not destroyed. revocation records the provider outcome
# separately from local destruction.
# SELECT id, connection_id, kind, version, status, revocation, provider_expires_at,
#        created_at, destroyed_at
# FROM public.connector_token_secrets
# WHERE connection_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY kind, version DESC LIMIT 20;
class ConnectorTokenSecret(Base):
    __tablename__ = "connector_token_secrets"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        UniqueConstraint(
            "connection_id", "kind", "version", name="uq_connector_token_secrets_version"
        ),
        CheckConstraint("kind IN ('access_token', 'refresh_token')", name="valid_kind"),
        CheckConstraint("version >= 1", name="positive_version"),
        CheckConstraint(
            "status IN ('active', 'refresh_due', 'revoked', 'destroyed')", name="valid_status"
        ),
        CheckConstraint(
            "revocation IS NULL OR revocation IN "
            "('done', 'unsupported', 'failed', 'not_required', 'shared')",
            name="valid_revocation",
        ),
        CheckConstraint(
            "(status = 'destroyed' AND destroyed_at IS NOT NULL AND "
            + " AND ".join(f"{name} IS NULL" for name in MATERIAL)
            + ") OR (status <> 'destroyed' AND destroyed_at IS NULL AND "
            + " AND ".join(f"{name} IS NOT NULL" for name in MATERIAL)
            + ")",
            name="material_state",
        ),
        Index(
            "uq_connector_token_secrets_live",
            "connection_id",
            "kind",
            unique=True,
            postgresql_where=text("status <> 'destroyed'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer)
    alg: Mapped[str] = mapped_column(String(32))
    aad_version: Mapped[int] = mapped_column(SmallInteger)
    kek_id: Mapped[str | None] = mapped_column(String(32))
    wrap_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    revocation: Mapped[str | None] = mapped_column(String(16))
    provider_expires_at: Mapped[datetime | None] = _time()
    last_refreshed_at: Mapped[datetime | None] = _time()
    created_at: Mapped[datetime] = _time(False, default=True)
    destroyed_at: Mapped[datetime | None] = _time()


# One synchronization of a connection under the generation it was queued with: an incremental
# read from the stream's watermark or a backfill of older history (009-B). At most one run per
# connection is queued or running. A deferred run is queued again with not_before, and its
# last deferral reason in error_kind; retries counts rate-limit and retryable deferrals.
# SELECT id, connection_id, connection_generation, kind, status, attempt, retries, pages,
#        error_kind, not_before, created_at, started_at, finished_at
# FROM public.connector_sync_runs
# WHERE connection_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY created_at DESC, id LIMIT 20;
class ConnectorSyncRun(Base):
    __tablename__ = "connector_sync_runs"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        UniqueConstraint(
            "agency_id", "client_id", "connection_id", "id", name="uq_connector_sync_runs_scope"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="valid_status",
        ),
        CheckConstraint(
            "error_kind IS NULL OR error_kind IN ('unauthorized', 'forbidden', 'rate_limited', "
            "'retryable', 'permanent', 'budget_exhausted', 'fenced', 'client_inactive', "
            "'connection_inactive')",
            name="valid_error_kind",
        ),
        CheckConstraint("attempt >= 0 AND connection_generation >= 1", name="valid_attempt"),
        CheckConstraint("kind IN ('incremental', 'backfill')", name="valid_kind"),
        CheckConstraint("retries >= 0 AND pages >= 0", name="valid_progress"),
        CheckConstraint(
            "window_since IS NULL OR window_until IS NULL OR window_since < window_until",
            name="valid_window",
        ),
        Index(
            "uq_connector_sync_runs_open",
            "connection_id",
            "stream",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index(
            "ix_connector_sync_runs_queued",
            "created_at",
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    connection_generation: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    attempt: Mapped[int] = mapped_column(Integer, server_default="0")
    error_kind: Mapped[str | None] = mapped_column(String(32))
    lease_expires_at: Mapped[datetime | None] = _time()
    created_at: Mapped[datetime] = _time(False, default=True)
    started_at: Mapped[datetime | None] = _time()
    finished_at: Mapped[datetime | None] = _time()
    kind: Mapped[str] = mapped_column(String(16), server_default="incremental")
    window_since: Mapped[datetime | None] = _time()
    window_until: Mapped[datetime | None] = _time()
    not_before: Mapped[datetime | None] = _time()
    retries: Mapped[int] = mapped_column(Integer, server_default="0")
    pages: Mapped[int] = mapped_column(Integer, server_default="0")
    # 010-A: the stream this run reads; one open run per connection and stream.
    stream: Mapped[str] = mapped_column(String(32), server_default="objects")


# Synchronization position and coverage of one stream of a connection (009-B). cursor is the
# provider's opaque position of the next page of run_id's window; it advances in the same
# transaction as the records of the page before it. covered_from and complete_through bound
# the history known to be complete; they move only when a run stores its last page. Deleted by
# the disconnect purge.
# SELECT stream, run_id, covered_from, complete_through, updated_at
# FROM public.connector_checkpoints
# WHERE connection_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY stream LIMIT 20;
class ConnectorCheckpoint(Base):
    __tablename__ = "connector_checkpoints"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        ForeignKeyConstraint(["run_id"], ["connector_sync_runs.id"]),
        UniqueConstraint("connection_id", "stream", name="uq_connector_checkpoints_stream"),
        CheckConstraint("length(cursor) <= 512", name="bounded_cursor"),
        CheckConstraint(
            "covered_from IS NULL OR complete_through IS NULL OR covered_from <= complete_through",
            name="valid_coverage",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    stream: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[UUID | None] = mapped_column(Uuid)
    cursor: Mapped[str | None] = mapped_column(String(512))
    covered_from: Mapped[datetime | None] = _time()
    complete_through: Mapped[datetime | None] = _time()
    updated_at: Mapped[datetime] = _time(False, default=True)


# One provider data call (009-B, D-049 decision D15), reserved before the call and settled with
# its outcome afterwards, including failed and retried calls. quantity is in the provider's
# cost unit; period is the UTC day the budgets count against. No provider data is stored.
# 011-A (D10): for a provider with quota buckets, each call has one row per bucket it touches,
# and period is the bucket's local day; bucket is NULL for providers without buckets.
# SELECT operation, unit, quantity, outcome, period, occurred_at, settled_at
# FROM public.connector_usage_records
# WHERE connection_id = '00000000-0000-0000-0000-000000000009'::uuid
#   AND period = DATE '2026-11-17'
# ORDER BY occurred_at, id LIMIT 100;
class ConnectorUsageRecord(Base):
    __tablename__ = "connector_usage_records"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        ForeignKeyConstraint(["run_id"], ["connector_sync_runs.id"]),
        CheckConstraint("operation IN ('fetch', 'refresh', 'confirm')", name="valid_operation"),
        CheckConstraint(
            "outcome IN ('reserved', 'ok', 'unauthorized', 'forbidden', 'rate_limited', "
            "'retryable', 'permanent', 'budget_exhausted')",
            name="valid_outcome",
        ),
        CheckConstraint("quantity > 0 AND attempt >= 1", name="valid_quantity"),
        Index("ix_connector_usage_records_connection_period", "connection_id", "period"),
        Index("ix_connector_usage_records_provider_period", "provider", "period"),
        Index("ix_connector_usage_records_bucket_period", "provider", "bucket", "period"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    attempt: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(16))
    unit: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(16), server_default="reserved")
    period: Mapped[date] = mapped_column(Date)
    occurred_at: Mapped[datetime] = _time(False, default=True)
    settled_at: Mapped[datetime | None] = _time()
    bucket: Mapped[str | None] = mapped_column(String(32))


# Provider data of one connection: one row per provider object with its latest observed
# synthetic metrics, the run that stored them, and the adapter version that read them (009-C
# provenance). Deleted by the disconnect purge.
# SELECT provider_object_id, observed_at, fetched_at
# FROM public.connector_records
# WHERE connection_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY provider_object_id LIMIT 100;
class ConnectorRecord(Base):
    __tablename__ = "connector_records"
    __table_args__ = (
        ForeignKeyConstraint(*CONNECTION_FK),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "connection_id", "source_run_id"],
            [
                "connector_sync_runs.agency_id",
                "connector_sync_runs.client_id",
                "connector_sync_runs.connection_id",
                "connector_sync_runs.id",
            ],
        ),
        UniqueConstraint(
            "connection_id", "stream", "provider_object_id", name="uq_connector_records_object"
        ),
        CheckConstraint("jsonb_typeof(metrics) = 'object'", name="object_metrics"),
        CheckConstraint("length(metrics::text) <= 4096", name="bounded_metrics"),
        CheckConstraint("jsonb_typeof(unavailable) = 'object'", name="object_unavailable"),
        CheckConstraint("length(unavailable::text) <= 2048", name="bounded_unavailable"),
        CheckConstraint(PRODUCT_TYPES, name="valid_product_type"),
        CheckConstraint("jsonb_typeof(attributes) = 'object'", name="object_attributes"),
        CheckConstraint("length(attributes::text) <= 1024", name="bounded_attributes"),
        CheckConstraint(
            "attributes = '{}'::jsonb OR attributes_refreshed_at IS NOT NULL",
            name="attributes_refreshed",
        ),
        Index("ix_connector_records_observed", "observed_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(Uuid)
    connection_generation: Mapped[int] = mapped_column(Integer)
    provider_object_id: Mapped[str] = mapped_column(String(128))
    observed_at: Mapped[datetime] = _time(False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = _time(False, default=True)
    source_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    adapter_version: Mapped[str | None] = mapped_column(String(32))
    # 010-A (D-053 decisions D6 and D7): the stream, the media product type, and the closed
    # reason for each metric the provider did not report.
    stream: Mapped[str] = mapped_column(String(32), server_default="objects")
    product_type: Mapped[str | None] = mapped_column(String(16))
    unavailable: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # 011-A (D9, D11): allow-listed attributes with their refresh time, cleared after a period
    # without refresh, and the end of the provisional period of a lifetime total.
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    attributes_refreshed_at: Mapped[datetime | None] = _time()
    provisional_until: Mapped[datetime | None] = _time()


# A verified provider webhook delivery, kept only to recognize a repeated delivery (009-D,
# D-049 decision D19). It is not tenant-scoped, because one delivery may concern connections of
# several clients; it holds a SHA-256 digest of the provider's event ID and the number of
# connections notified, never the payload or the account. Deleted 7 days after receipt.
# SELECT provider, received_at, notified
# FROM public.connector_webhook_deliveries
# WHERE received_at >= now() - interval '1 day'
# ORDER BY received_at DESC, id LIMIT 100;
class ConnectorWebhookDelivery(Base):
    __tablename__ = "connector_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("provider", "event_digest", name="uq_connector_webhook_deliveries_event"),
        CheckConstraint(PROVIDERS, name="valid_provider"),
        CheckConstraint("event_digest ~ '^[0-9a-f]{64}$'", name="event_digest"),
        CheckConstraint("notified >= 0", name="valid_notified"),
        Index("ix_connector_webhook_deliveries_received", "received_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32))
    event_digest: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = _time(False, default=True)
    notified: Mapped[int] = mapped_column(Integer, server_default="0")


# A provider data deletion request (010-A, D-053 decision D5). It keeps no account or tenant
# data: only the provider, the random confirmation code the provider shows to its user, the
# receipt time, how many connections it started to disconnect, and when all of them finished.
# SELECT provider, received_at, connections, completed_at
# FROM public.connector_deletion_requests
# WHERE confirmation_code = 'SYNTHETICCODE0000000000000000000';
class ConnectorDeletionRequest(Base):
    __tablename__ = "connector_deletion_requests"
    __table_args__ = (
        CheckConstraint(PROVIDERS, name="valid_provider"),
        CheckConstraint("confirmation_code ~ '^[A-Za-z0-9_-]{16,64}$'", name="valid_code"),
        CheckConstraint("connections >= 0", name="valid_connections"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32))
    confirmation_code: Mapped[str] = mapped_column(String(64), unique=True)
    received_at: Mapped[datetime] = _time(False, default=True)
    connections: Mapped[int] = mapped_column(Integer, server_default="0")
    completed_at: Mapped[datetime | None] = _time()
