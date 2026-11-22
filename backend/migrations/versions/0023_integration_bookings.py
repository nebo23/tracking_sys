"""Integration sources, deliveries and bookings

Revision ID: 0023_integration_bookings
Revises: 0022_revenue_imports
Created: 2026-11-21

Specification 015-D (D-068 decisions E2 to E5, E9, E10 and E12; design in
specs/015-business-integrations/design-015b.md). Adds integration_sources (a client's Cal.com or
signed webhook source with the public key of its callback URL), integration_source_secrets (the
signing secret sealed under the D-025 keyring; a replaced version retires 24 hours later),
integration_deliveries (one row per verified delivery: a digest of the body, unique per source,
its receipt time and a closed outcome), bookings (one booking chain with its derived state and an
optional link to a collection subject, cleared when the subject is erased) and booking_events
(the minimal events of each chain; a later event that connects two chains moves the events
of the later chain into the earlier one and marks it merged). Audit events accept the
integration actions and the integration_source resource. tracking_app may insert and read,
and update only the columns a state change needs; tracking_lifecycle may delete retired
secrets, deliveries after 30 days and bookings 395 days after their last update, reading only
their keys and times. Amended in place under D-070 (review finding R002): tracking_lifecycle may
also read a booking's client and subject and clear its subject_id and linked_at together, so
that the expiry of a linked subject detaches the booking before the subject is deleted; it may
not change any other booking column. Also under D-070 (review finding R006), bookings and
booking_events carry the source whose deliveries created them, and a chain is looked up within
its source only: two signed webhook sources of one client may both use a booking ID such as
booking-1 without touching each other's bookings. The downgrade
refuses any integration or booking state and any new audit action.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0023_integration_bookings"
down_revision: str | Sequence[str] | None = "0022_revenue_imports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Children before parents.
TABLES = (
    "booking_events",
    "bookings",
    "integration_deliveries",
    "integration_source_secrets",
    "integration_sources",
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
    "'link.created', 'link.updated', 'connector.connected', 'connector.reconnected', "
    "'connector.disconnect_requested', 'destination.created', 'destination.updated', "
    "'delivery.requeued', 'delivery.dismissed', 'payment_source.created', "
    "'payment_source.updated', 'payment_source.secret_replaced', "
    "'revenue_import.committed', 'revenue.declared')"
)
NEW_ACTIONS = ("integration.created", "integration.updated", "integration.secret_replaced")
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'integration_source')"
KINDS = "'cal_com', 'signed_webhook'"
OUTCOMES = "'applied', 'duplicate', 'ignored', 'invalid'"
REASONS = (
    "'unsupported_event', 'invalid_booking', 'invalid_deal', 'merged', "
    "'subject_unknown', 'consent_missing', 'linked'"
)
STATUSES = "'requested', 'scheduled', 'cancelled', 'rejected', 'completed', 'merged'"
EVENT_KINDS = "'requested', 'created', 'rescheduled', 'cancelled', 'rejected', 'completed'"
PUBLIC_KEY = "^isk_[A-Za-z0-9_-]{43}$"
SOURCE = [
    "integration_sources.agency_id",
    "integration_sources.client_id",
    "integration_sources.id",
]
BOOKING_UPDATES = (
    "status",
    "event_type_ref",
    "start_at",
    "end_at",
    "reschedule_count",
    "subject_id",
    "linked_at",
    "updated_at",
)
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    "GRANT UPDATE (name, status, updated_at) ON integration_sources TO tracking_app",
    "GRANT UPDATE (retires_at) ON integration_source_secrets TO tracking_app",
    f"GRANT UPDATE ({', '.join(BOOKING_UPDATES)}) ON bookings TO tracking_app",
    "GRANT UPDATE (booking_id) ON booking_events TO tracking_app",
)
LIFECYCLE_GRANTS = (
    "GRANT SELECT (id, retires_at) ON integration_source_secrets TO tracking_lifecycle",
    "GRANT DELETE ON integration_source_secrets TO tracking_lifecycle",
    "GRANT SELECT (id, received_at) ON integration_deliveries TO tracking_lifecycle",
    "GRANT DELETE ON integration_deliveries TO tracking_lifecycle",
    "GRANT SELECT (id, updated_at, client_id, subject_id) ON bookings TO tracking_lifecycle",
    "GRANT UPDATE (subject_id, linked_at) ON bookings TO tracking_lifecycle",
    "GRANT DELETE ON bookings TO tracking_lifecycle",
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _scope() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


def _time(name: str, *, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def _client(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id"],
        ["client_workspaces.agency_id", "client_workspaces.id"],
        name=op.f(f"fk_{table}_agency_id_client_workspaces"),
    )


def _source(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", "source_id"],
        SOURCE,
        name=op.f(f"fk_{table}_agency_id_integration_sources"),
    )


def upgrade() -> None:
    _replace_check("audit_events", "valid_action", ACTIONS)
    _replace_check("audit_events", "valid_resource", RESOURCES)

    table = "integration_sources"
    op.create_table(
        table,
        *_scope(),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        _time("created_at", default=True),
        _time("updated_at", default=True),
        _check(table, "valid_kind", f"kind IN ({KINDS})"),
        _check(table, "valid_status", "status IN ('active', 'disabled')"),
        _check(table, "valid_name", "length(btrim(name)) BETWEEN 1 AND 200"),
        _check(table, "valid_public_key", f"public_key ~ '{PUBLIC_KEY}'"),
        _client(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f(f"fk_{table}_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_integration_sources_scope"),
        sa.UniqueConstraint("public_key", name="uq_integration_sources_public_key"),
    )
    op.create_index("ix_integration_sources_agency_client", table, ["agency_id", "client_id"])

    table = "integration_source_secrets"
    op.create_table(
        table,
        *_scope(),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=False),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        _time("created_at", default=True),
        _time("retires_at", nullable=True),
        _check(table, "positive_version", "version >= 1"),
        _source(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("source_id", "version", name="uq_integration_source_secrets_version"),
    )

    table = "integration_deliveries"
    op.create_table(
        table,
        *_scope(),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_digest", sa.String(length=64), nullable=False),
        _time("received_at"),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        _check(table, "valid_outcome", f"outcome IN ({OUTCOMES})"),
        _check(table, "valid_reason", f"reason IS NULL OR reason IN ({REASONS})"),
        _check(table, "valid_digest", "delivery_digest ~ '^[0-9a-f]{64}$'"),
        _source(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(
            "source_id", "delivery_digest", name="uq_integration_deliveries_digest"
        ),
    )
    op.create_index("ix_integration_deliveries_received_at", table, ["received_at"])

    table = "bookings"
    op.create_table(
        table,
        *_scope(),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("event_type_ref", sa.String(length=128), nullable=True),
        _time("start_at", nullable=True),
        _time("end_at", nullable=True),
        sa.Column("reschedule_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        _time("linked_at", nullable=True),
        _time("first_received_at"),
        _time("updated_at"),
        _check(table, "valid_provider", f"provider IN ({KINDS})"),
        _check(table, "valid_status", f"status IN ({STATUSES})"),
        _check(table, "valid_reschedules", "reschedule_count >= 0"),
        _check(table, "valid_link", "(subject_id IS NULL) = (linked_at IS NULL)"),
        _client(table),
        _source(table),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["collection_subjects.id"],
            name=op.f(f"fk_{table}_subject_id_collection_subjects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_bookings_scope"),
    )
    op.create_index("ix_bookings_client_updated", table, ["client_id", "updated_at"])

    table = "booking_events"
    op.create_table(
        table,
        *_scope(),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref", sa.String(length=128), nullable=False),
        sa.Column("previous_ref", sa.String(length=128), nullable=True),
        sa.Column("event_type_ref", sa.String(length=128), nullable=True),
        _time("occurred_at"),
        _time("start_at", nullable=True),
        _time("end_at", nullable=True),
        _check(table, "valid_kind", f"kind IN ({EVENT_KINDS})"),
        _check(table, "valid_provider", f"provider IN ({KINDS})"),
        _check(
            table,
            "valid_reschedule",
            "(kind = 'rescheduled') = (previous_ref IS NOT NULL) "
            "AND (previous_ref IS NULL OR previous_ref <> ref)",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "booking_id"],
            ["bookings.agency_id", "bookings.client_id", "bookings.id"],
            name=op.f(f"fk_{table}_agency_id_bookings"),
            ondelete="CASCADE",
        ),
        _source(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(
            "booking_id", "kind", "ref", "occurred_at", name="uq_booking_events_event"
        ),
    )
    # Chain lookups by a booking ID and by a previous ID, within one source (R006).
    op.create_index("ix_booking_events_source_ref", table, ["source_id", "ref"])
    op.create_index("ix_booking_events_source_previous", table, ["source_id", "previous_ref"])

    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{item}'" for item in NEW_ACTIONS)
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
            + f" OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
            + " OR EXISTS (SELECT 1 FROM audit_events WHERE resource_type = 'integration_source')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove integration state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    for table in TABLES:
        op.drop_table(table)
    _replace_check("audit_events", "valid_resource", PREVIOUS_RESOURCES)
    _replace_check("audit_events", "valid_action", PREVIOUS_ACTIONS)
