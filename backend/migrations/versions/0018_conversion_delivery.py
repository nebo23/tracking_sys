"""Conversion delivery: destinations, the delivery outbox and acknowledgements

Revision ID: 0018_conversion_delivery
Revises: 0017_ad_spend
Created: 2026-11-21

Specification 014-B (D-064 decisions D6 to D10, D13 and D14; design in
specs/014-ad-spend-capi/design-014.md). Adds three client-scoped tables whose references are
composite (agency_id, client_id, ...) keys: conversion_destinations (one per delivery
connection, disabled by default), conversion_deliveries (one per destination and verified sale,
unique on a deterministic event ID, with the consent basis, the closed state and reason, the
attempt fence and a sealed payload present exactly until the delivery ends) and
conversion_acknowledgements (one per attempt). Audit events accept the destination and delivery
actions. Connections, webhook deliveries and data deletion requests accept the provider
synthetic_meta_capi. tracking_app may insert and update only the state, schedule, value,
payload and time columns, and may never delete; tracking_lifecycle may delete ended deliveries
and their acknowledgements and read only the columns that needs. The downgrade refuses
populated 014-B state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0018_conversion_delivery"
down_revision: str | Sequence[str] | None = "0017_ad_spend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKED = ("connector_connections", "connector_webhook_deliveries", "connector_deletion_requests")
UNCHECKED = ("connector_oauth_transactions", "connector_usage_records")
PROVIDERS = (
    "provider IN ('synthetic', 'synthetic_instagram', 'instagram', 'synthetic_youtube', "
    "'youtube', 'synthetic_meta_ads'"
)
OLD_PROVIDERS = PROVIDERS + ")"
NEW_PROVIDERS = PROVIDERS + ", 'synthetic_meta_capi')"
PREVIOUS_ACTIONS = (
    "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
    "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
    "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
    "'credential.created', 'credential.revoked', 'source.created', 'source.updated', "
    "'source.secret_rotated', 'form.updated', 'deletion.requested', "
    "'campaign.created', 'campaign.updated', 'content.created', 'content.updated', "
    "'template.created', 'template.updated', 'origin.created', 'origin.updated', "
    "'domain.created', 'domain.updated', 'domain.challenge_issued', 'domain.checked', "
    "'link.created', 'link.updated', 'connector.connected', 'connector.reconnected', "
    "'connector.disconnect_requested')"
)
NEW_ACTIONS = (
    "destination.created",
    "destination.updated",
    "delivery.requeued",
    "delivery.dismissed",
)
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'destination', 'delivery')"
CONNECTION = [
    "connector_connections.agency_id",
    "connector_connections.client_id",
    "connector_connections.id",
]
MEMBERSHIP = ["agency_memberships.agency_id", "agency_memberships.id"]
STATUSES = (
    "queued",
    "sending",
    "delivered",
    "blocked",
    "cancelled",
    "expired",
    "rejected",
    "undeliverable",
    "dismissed",
)
ENDED = ("delivered", "blocked", "cancelled", "expired", "undeliverable", "dismissed")
REASONS = (
    "consent_unknown",
    "consent_denied",
    "consent_withdrawn",
    "consent_expired",
    "subject_deleted",
    "subject_unknown",
    "subject_objected",
    "no_consent_after_deletion",
    "replay_before_deletion",
    "destination_disabled",
    "connection_ended",
    "sale_reversed",
    "deadline_passed",
    "permission_missing",
    "dataset_unavailable",
    "invalid_parameter",
    "invalid_event",
    "retries_exhausted",
    "retryable",
    "rate_limited",
    "count_mismatch",
    "invalid_token",
)
ACTION_SOURCES = (
    "email",
    "website",
    "phone_call",
    "chat",
    "physical_store",
    "system_generated",
    "business_messaging",
    "other",
)
OUTCOMES = (
    "accepted",
    "count_mismatch",
    "retryable",
    "rate_limited",
    "unauthorized",
    "configuration",
    "payload",
)
MATERIAL = ("kek_id", "wrap_nonce", "wrapped_dek", "nonce", "ciphertext")
EVENT_NAME = "^[A-Za-z][A-Za-z0-9_]{0,39}$"
TEST_CODE = "^[A-Za-z0-9]{1,32}$"
# Children before parents.
TABLES = ("conversion_acknowledgements", "conversion_deliveries", "conversion_destinations")
DELIVERY_UPDATES = (
    "value_minor",
    "status",
    "reason",
    "rejection_class",
    "attempts",
    "retries",
    "requeues",
    "not_before",
    "lease_expires_at",
    *MATERIAL,
    "updated_at",
    "delivered_at",
    "ended_at",
)
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    "GRANT UPDATE (event_name, test_event_code, enabled, updated_at) "
    "ON conversion_destinations TO tracking_app",
    f"GRANT UPDATE ({', '.join(DELIVERY_UPDATES)}) ON conversion_deliveries TO tracking_app",
)
LIFECYCLE_GRANTS = (
    "GRANT SELECT (id, ended_at) ON conversion_deliveries TO tracking_lifecycle",
    "GRANT DELETE ON conversion_deliveries TO tracking_lifecycle",
    "GRANT SELECT (id, delivery_id) ON conversion_acknowledgements TO tracking_lifecycle",
    "GRANT DELETE ON conversion_acknowledgements TO tracking_lifecycle",
)


def _values(items: Sequence[str]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def _scope() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _time(name: str, *, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    for table in CHECKED:
        _replace_check(table, "valid_provider", NEW_PROVIDERS)
    _replace_check("audit_events", "valid_action", ACTIONS)
    _replace_check("audit_events", "valid_resource", RESOURCES)

    table = "conversion_destinations"
    op.create_table(
        table,
        *_scope(),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("event_name", sa.String(length=40), server_default="Purchase", nullable=False),
        sa.Column("test_event_code", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        _time("created_at", nullable=False, default=True),
        _time("updated_at", nullable=False, default=True),
        _check(table, "valid_event_name", f"event_name ~ '{EVENT_NAME}'"),
        _check(
            table, "valid_test_code", f"test_event_code IS NULL OR test_event_code ~ '{TEST_CODE}'"
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "connection_id"],
            CONNECTION,
            name=op.f(f"fk_{table}_agency_id_connector_connections"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            MEMBERSHIP,
            name=op.f(f"fk_{table}_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(
            "agency_id", "client_id", "id", name="uq_conversion_destinations_scope"
        ),
        sa.UniqueConstraint("connection_id", name="uq_conversion_destinations_connection"),
    )

    table = "conversion_deliveries"
    op.create_table(
        table,
        *_scope(),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_name", sa.String(length=40), nullable=False),
        sa.Column("action_source", sa.String(length=24), nullable=False),
        _time("event_time", nullable=False),
        _time("deadline", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("currency_exponent", sa.SmallInteger(), nullable=False),
        sa.Column("value_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("rejection_class", sa.String(length=16), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retries", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requeues", sa.SmallInteger(), server_default="0", nullable=False),
        _time("not_before"),
        _time("lease_expires_at"),
        sa.Column("consent_basis", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=True),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=True),
        sa.Column("nonce", sa.LargeBinary(), nullable=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        _time("created_at", nullable=False, default=True),
        _time("updated_at", nullable=False, default=True),
        _time("delivered_at"),
        _time("ended_at"),
        _check(table, "valid_status", f"status IN ({_values(STATUSES)})"),
        _check(table, "valid_reason", f"reason IS NULL OR reason IN ({_values(REASONS)})"),
        _check(table, "valid_source", f"action_source IN ({_values(ACTION_SOURCES)})"),
        _check(
            table,
            "valid_rejection",
            "(rejection_class IS NULL OR rejection_class IN ('configuration', 'payload')) "
            "AND (status <> 'rejected' OR rejection_class IS NOT NULL) "
            "AND (rejection_class IS NULL OR status IN ('rejected', 'dismissed'))",
        ),
        _check(
            table,
            "ended_state",
            f"(status IN ({_values(ENDED)})) <= (ended_at IS NOT NULL) "
            "AND (status IN ('queued', 'sending')) <= (ended_at IS NULL) "
            "AND (status <> 'rejected' OR (rejection_class = 'payload') = (ended_at IS NOT NULL))",
        ),
        _check(
            table,
            "payload_state",
            "(ended_at IS NULL AND "
            + " AND ".join(f"{name} IS NOT NULL" for name in MATERIAL)
            + ") OR (ended_at IS NOT NULL AND "
            + " AND ".join(f"{name} IS NULL" for name in MATERIAL)
            + ")",
        ),
        _check(
            table,
            "delivery_times",
            "(status = 'delivered') = (delivered_at IS NOT NULL) "
            "AND (status <> 'sending' OR lease_expires_at IS NOT NULL)",
        ),
        _check(
            table,
            "valid_event",
            "event_id ~ '^[0-9a-f]{64}$' AND currency ~ '^[A-Z]{3}$' "
            f"AND event_name ~ '{EVENT_NAME}' AND deadline > event_time",
        ),
        _check(
            table,
            "valid_counters",
            "value_minor > 0 AND currency_exponent BETWEEN 0 AND 8 AND attempts >= 0 "
            "AND retries >= 0 AND requeues BETWEEN 0 AND 3",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "destination_id"],
            [
                "conversion_destinations.agency_id",
                "conversion_destinations.client_id",
                "conversion_destinations.id",
            ],
            name=op.f(f"fk_{table}_agency_id_conversion_destinations"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "connection_id"],
            CONNECTION,
            name=op.f(f"fk_{table}_agency_id_connector_connections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_conversion_deliveries_scope"),
        sa.UniqueConstraint("destination_id", "event_id", name="uq_conversion_deliveries_event"),
    )
    op.create_index(
        "ix_conversion_deliveries_open",
        table,
        ["created_at"],
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "ix_conversion_deliveries_ended",
        table,
        ["ended_at"],
        postgresql_where=sa.text("ended_at IS NOT NULL"),
    )

    table = "conversion_acknowledgements"
    op.create_table(
        table,
        *_scope(),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        _time("occurred_at", nullable=False, default=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("provider_code", sa.String(length=32), nullable=True),
        sa.Column("events_received", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        _check(table, "valid_outcome", f"outcome IN ({_values(OUTCOMES)})"),
        _check(
            table,
            "valid_counts",
            "attempt >= 1 AND (events_received IS NULL OR events_received >= 0)",
        ),
        _check(table, "valid_code", "provider_code IS NULL OR provider_code ~ '^[a-z0-9_]{1,32}$'"),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "delivery_id"],
            [
                "conversion_deliveries.agency_id",
                "conversion_deliveries.client_id",
                "conversion_deliveries.id",
            ],
            name=op.f(f"fk_{table}_agency_id_conversion_deliveries"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(
            "delivery_id", "attempt", name="uq_conversion_acknowledgements_attempt"
        ),
    )

    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, *CHECKED, *UNCHECKED, "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{item}'" for item in NEW_ACTIONS)
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
            + " OR "
            + " OR ".join(
                f"EXISTS (SELECT 1 FROM {table} WHERE provider = 'synthetic_meta_capi')"
                for table in CHECKED + UNCHECKED
            )
            + f" OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove populated delivery state; use a forward fix.")
    for table in TABLES:
        op.drop_table(table)
    _replace_check("audit_events", "valid_resource", PREVIOUS_RESOURCES)
    _replace_check("audit_events", "valid_action", PREVIOUS_ACTIONS)
    for table in CHECKED:
        _replace_check(table, "valid_provider", OLD_PROVIDERS)
