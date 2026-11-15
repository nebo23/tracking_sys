"""Connector connection lifecycle: OAuth transactions, connections, sealed tokens, runs, records

Revision ID: 0009_connector_runtime
Revises: 0008_links_tracker
Created: 2026-11-15

Specification 009-A (D-048). Adds five client-scoped tables. Every reference to another
connector row is a composite (agency_id, client_id, id) foreign key, so a transaction, secret,
run, or record can never point at another client's connection. tracking_app may insert rows
and update only the columns each lifecycle transition writes (see the 009-A design): the
connection's status, generation, outcome, timing, and provider account reference (cleared by
the disconnect purge); a token secret's status, revocation outcome, and sealed material
(cleared on destruction, rewrapped on KEK rotation); a run's state; and a record's observed
values. The runtime cannot delete transactions, connections, secrets, or runs; it may delete
only provider records, for the disconnect purge. tracking_lifecycle deletes connector OAuth
transactions one day after consumption or expiry. The downgrade refuses populated 009 state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0009_connector_runtime"
down_revision: str | Sequence[str] | None = "0008_links_tracker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLIENT = ["client_workspaces.agency_id", "client_workspaces.id"]
MEMBERSHIP = ["agency_memberships.agency_id", "agency_memberships.id"]
CONNECTION = [
    "connector_connections.agency_id",
    "connector_connections.client_id",
    "connector_connections.id",
]
# Children before parents.
TABLES = (
    "connector_records",
    "connector_sync_runs",
    "connector_token_secrets",
    "connector_oauth_transactions",
    "connector_connections",
)
PREVIOUS_ACTIONS = (
    "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
    "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
    "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
    "'credential.created', 'credential.revoked', 'source.created', 'source.updated', "
    "'source.secret_rotated', 'form.updated', 'deletion.requested', "
    "'campaign.created', 'campaign.updated', 'content.created', 'content.updated', "
    "'template.created', 'template.updated', 'origin.created', 'origin.updated', "
    "'domain.created', 'domain.updated', 'domain.challenge_issued', 'domain.checked', "
    "'link.created', 'link.updated')"
)
NEW_ACTIONS = ("connector.connected", "connector.reconnected", "connector.disconnect_requested")
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'connection')"
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    "GRANT UPDATE (consumed_at) ON connector_oauth_transactions TO tracking_app",
    "GRANT UPDATE (external_account_id, account_label, status, status_reason, generation, "
    "granted_scopes, connected_at, last_successful_sync_at, disconnect_requested_at, "
    "purge_due_at, disconnected_at, revocation_status, destruction_status, purge_status, "
    "teardown_attempts, teardown_lease_until, updated_at) ON connector_connections TO tracking_app",
    "GRANT UPDATE (status, revocation, kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext, "
    "destroyed_at) ON connector_token_secrets TO tracking_app",
    "GRANT UPDATE (status, attempt, lease_expires_at, error_kind, started_at, finished_at) "
    "ON connector_sync_runs TO tracking_app",
    "GRANT UPDATE (connection_generation, observed_at, metrics, fetched_at) "
    "ON connector_records TO tracking_app",
    "GRANT DELETE ON connector_records TO tracking_app",
)
MATERIAL = ("kek_id", "wrap_nonce", "wrapped_dek", "nonce", "ciphertext")


def _scope() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


def _client(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id"], CLIENT, name=op.f(f"fk_{table}_agency_id_client_workspaces")
    )


def _connection(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", "connection_id"],
        CONNECTION,
        name=op.f(f"fk_{table}_agency_id_connector_connections"),
    )


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _time(name: str, *, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def upgrade() -> None:
    table = "connector_connections"
    op.create_table(
        table,
        *_scope(),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=128), nullable=True),
        sa.Column("account_label", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column("status_reason", sa.String(length=24), nullable=True),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "granted_scopes",
            postgresql.ARRAY(sa.String(length=100)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        _time("created_at", nullable=False, default=True),
        _time("updated_at", nullable=False, default=True),
        _time("connected_at", nullable=False, default=True),
        _time("last_successful_sync_at"),
        _time("disconnect_requested_at"),
        _time("purge_due_at"),
        _time("disconnected_at"),
        sa.Column("revocation_status", sa.String(length=16), nullable=True),
        sa.Column("destruction_status", sa.String(length=16), nullable=True),
        sa.Column("purge_status", sa.String(length=16), nullable=True),
        sa.Column("teardown_attempts", sa.Integer(), server_default="0", nullable=False),
        _time("teardown_lease_until"),
        _check(table, "valid_provider", "provider IN ('synthetic')"),
        _check(
            table,
            "valid_status",
            "status IN ('active', 'reconnect_required', 'disconnecting', 'disconnected')",
        ),
        _check(
            table,
            "valid_reason",
            "status_reason IS NULL OR status_reason IN "
            "('credential_expired', 'provider_revoked', 'user_requested')",
        ),
        _check(
            table,
            "valid_outcomes",
            "(revocation_status IS NULL OR revocation_status IN "
            "('pending', 'done', 'unsupported', 'failed')) "
            "AND (destruction_status IS NULL OR destruction_status IN ('pending', 'done')) "
            "AND (purge_status IS NULL OR purge_status IN ('pending', 'done'))",
        ),
        _check(table, "valid_counters", "generation >= 1 AND teardown_attempts >= 0"),
        _check(
            table,
            "teardown_state",
            "(status IN ('disconnecting', 'disconnected')) = "
            "(disconnect_requested_at IS NOT NULL AND purge_due_at IS NOT NULL "
            "AND revocation_status IS NOT NULL AND destruction_status IS NOT NULL "
            "AND purge_status IS NOT NULL)",
        ),
        _check(
            table,
            "disconnected_state",
            "(status = 'disconnected') = (disconnected_at IS NOT NULL) "
            "AND (status <> 'disconnected' OR (external_account_id IS NULL "
            "AND account_label IS NULL AND destruction_status = 'done' "
            "AND purge_status = 'done' AND revocation_status <> 'pending'))",
        ),
        _check(
            table,
            "account_present",
            "status = 'disconnected' OR external_account_id IS NOT NULL",
        ),
        _client(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            MEMBERSHIP,
            name=op.f("fk_connector_connections_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_connections")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_connector_connections_scope"),
    )
    op.create_index(
        "uq_connector_connections_live_account",
        table,
        ["client_id", "provider", "external_account_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'disconnected'"),
    )
    op.create_index("ix_connector_connections_agency_client", table, ["agency_id", "client_id"])
    op.create_index(
        "ix_connector_connections_disconnecting",
        table,
        ["purge_due_at"],
        postgresql_where=sa.text("status = 'disconnecting'"),
    )

    table = "connector_oauth_transactions"
    op.create_table(
        table,
        *_scope(),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("expected_generation", sa.Integer(), nullable=True),
        sa.Column("initiator_membership_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("binding_digest", sa.String(length=64), nullable=False),
        _time("created_at", nullable=False, default=True),
        _time("expires_at", nullable=False),
        _time("consumed_at"),
        _check(table, "valid_purpose", "purpose IN ('connect', 'reconnect')"),
        _check(
            table,
            "reconnect_target",
            "(purpose = 'connect' AND connection_id IS NULL AND expected_generation IS NULL) "
            "OR (purpose = 'reconnect' AND connection_id IS NOT NULL "
            "AND expected_generation IS NOT NULL)",
        ),
        _check(table, "state_digest", "state_digest ~ '^[0-9a-f]{64}$'"),
        _check(table, "binding_digest", "binding_digest ~ '^[0-9a-f]{64}$'"),
        _client(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "initiator_membership_id"],
            MEMBERSHIP,
            name=op.f("fk_connector_oauth_transactions_agency_id_agency_memberships"),
        ),
        _connection(table),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_oauth_transactions")),
        sa.UniqueConstraint(
            "state_digest", name=op.f("uq_connector_oauth_transactions_state_digest")
        ),
    )

    table = "connector_token_secrets"
    material_null = " AND ".join(f"{name} IS NULL" for name in MATERIAL)
    material_set = " AND ".join(f"{name} IS NOT NULL" for name in MATERIAL)
    op.create_table(
        table,
        *_scope(),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("alg", sa.String(length=32), nullable=False),
        sa.Column("aad_version", sa.SmallInteger(), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=True),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=True),
        sa.Column("nonce", sa.LargeBinary(), nullable=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("revocation", sa.String(length=16), nullable=True),
        _time("provider_expires_at"),
        _time("last_refreshed_at"),
        _time("created_at", nullable=False, default=True),
        _time("destroyed_at"),
        _check(table, "valid_kind", "kind IN ('access_token', 'refresh_token')"),
        _check(table, "positive_version", "version >= 1"),
        _check(
            table, "valid_status", "status IN ('active', 'refresh_due', 'revoked', 'destroyed')"
        ),
        _check(
            table,
            "valid_revocation",
            "revocation IS NULL OR revocation IN ('done', 'unsupported', 'failed', 'not_required')",
        ),
        _check(
            table,
            "material_state",
            f"(status = 'destroyed' AND destroyed_at IS NOT NULL AND {material_null}) "
            f"OR (status <> 'destroyed' AND destroyed_at IS NULL AND {material_set})",
        ),
        _connection(table),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_token_secrets")),
        sa.UniqueConstraint(
            "connection_id", "kind", "version", name="uq_connector_token_secrets_version"
        ),
    )
    op.create_index(
        "uq_connector_token_secrets_live",
        table,
        ["connection_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status <> 'destroyed'"),
    )

    table = "connector_sync_runs"
    op.create_table(
        table,
        *_scope(),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("connection_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_kind", sa.String(length=32), nullable=True),
        _time("lease_expires_at"),
        _time("created_at", nullable=False, default=True),
        _time("started_at"),
        _time("finished_at"),
        _check(
            table,
            "valid_status",
            "status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
        ),
        _check(
            table,
            "valid_error_kind",
            "error_kind IS NULL OR error_kind IN ('unauthorized', 'forbidden', 'rate_limited', "
            "'retryable', 'permanent', 'budget_exhausted', 'fenced', 'client_inactive', "
            "'connection_inactive')",
        ),
        _check(table, "valid_attempt", "attempt >= 0 AND connection_generation >= 1"),
        _connection(table),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_sync_runs")),
    )
    op.create_index(
        "uq_connector_sync_runs_open",
        table,
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_connector_sync_runs_queued",
        table,
        ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    table = "connector_records"
    op.create_table(
        table,
        *_scope(),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("connection_generation", sa.Integer(), nullable=False),
        sa.Column("provider_object_id", sa.String(length=128), nullable=False),
        _time("observed_at", nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _time("fetched_at", nullable=False, default=True),
        _check(table, "object_metrics", "jsonb_typeof(metrics) = 'object'"),
        _check(table, "bounded_metrics", "length(metrics::text) <= 4096"),
        _connection(table),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_records")),
        sa.UniqueConstraint(
            "connection_id", "provider_object_id", name="uq_connector_records_object"
        ),
    )

    op.drop_constraint(op.f("ck_audit_events_valid_action"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_valid_action"), "audit_events", ACTIONS)
    op.drop_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", RESOURCES)
    for statement in RUNTIME_GRANTS:
        op.execute(statement)
    op.execute("GRANT SELECT, DELETE ON connector_oauth_transactions TO tracking_lifecycle")


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(
        sa.text(f"LOCK TABLE {', '.join(TABLES)}, audit_events IN ACCESS EXCLUSIVE MODE")
    )
    populated = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
    actions = ", ".join(f"'{item}'" for item in NEW_ACTIONS)
    if connection.execute(
        sa.text(
            f"SELECT {populated} OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
        )
    ).scalar_one():
        raise RuntimeError("Refuse to remove populated connector state; use a forward fix.")
    op.execute("REVOKE SELECT, DELETE ON connector_oauth_transactions FROM tracking_lifecycle")
    op.drop_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_resource"), "audit_events", PREVIOUS_RESOURCES
    )
    op.drop_constraint(op.f("ck_audit_events_valid_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_action"), "audit_events", PREVIOUS_ACTIONS
    )
    for table in TABLES:
        op.drop_table(table)
