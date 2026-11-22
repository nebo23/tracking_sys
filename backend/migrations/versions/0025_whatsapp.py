"""WhatsApp numbers and referral messages

Revision ID: 0025_whatsapp
Revises: 0024_crm_deals
Created: 2026-11-21

Specification 015-E (D-068 decisions E7 to E10 and E12; design in
specs/015-business-integrations/design-015b.md). Adds whatsapp_numbers (a client's claim to a
WhatsApp Business phone number ID) and whatsapp_messages (one row per inbound message with only
its Click-to-WhatsApp referral: the source type, the ad ID and whether a click ID was present,
keyed by a SHA-256 of the message ID). No column holds a phone number, name, sender ID, text or
click ID. Audit events accept the whatsapp_number actions and resource. tracking_app may insert
and read, and update a number's name, status, verification time and update time;
tracking_lifecycle may delete messages 395 days after receipt. The downgrade refuses any number,
message or new audit action.

Amended in place under D-070 (review finding R004): an agency's registration is a pending claim
that routes nothing, a platform operator verifies one claim per number (verified_at), and only a
verified binding (active or disabled) is unique per phone number ID, so a first claim by another
agency cannot capture the number or block its owner. A client holds at most one unrevoked claim
per number.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0025_whatsapp"
down_revision: str | Sequence[str] | None = "0024_crm_deals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("whatsapp_messages", "whatsapp_numbers")
# D-070 claim states: pending (claimed, routes nothing), active and disabled (verified by the
# platform operator), revoked (ended by the operator).
STATUSES = "'pending', 'active', 'disabled', 'revoked'"
VERIFIED = "status IN ('active', 'disabled')"
VERIFICATION = (
    "(status = 'pending' AND verified_at IS NULL) "
    "OR (status IN ('active', 'disabled') AND verified_at IS NOT NULL) "
    "OR status = 'revoked'"
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
    "'revenue_import.committed', 'revenue.declared', 'integration.created', "
    "'integration.updated', 'integration.secret_replaced', 'crm_rule.created', "
    "'crm_rule.updated')"
)
NEW_ACTIONS = ("whatsapp_number.created", "whatsapp_number.updated")
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'whatsapp_number')"
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    "GRANT UPDATE (name, status, verified_at, updated_at) ON whatsapp_numbers TO tracking_app",
)
LIFECYCLE_GRANTS = (
    "GRANT SELECT (id, received_at) ON whatsapp_messages TO tracking_lifecycle",
    "GRANT DELETE ON whatsapp_messages TO tracking_lifecycle",
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _time(name: str, *, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def upgrade() -> None:
    _replace_check("audit_events", "valid_action", ACTIONS)
    _replace_check("audit_events", "valid_resource", RESOURCES)

    table = "whatsapp_numbers"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("phone_number_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        _time("created_at", default=True),
        _time("updated_at", default=True),
        _time("verified_at", nullable=True),
        _check(table, "valid_phone_number_id", "phone_number_id ~ '^[1-9][0-9]{0,31}$'"),
        _check(table, "valid_status", f"status IN ({STATUSES})"),
        _check(table, "valid_verification", VERIFICATION),
        _check(table, "valid_name", "length(btrim(name)) BETWEEN 1 AND 200"),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name=op.f(f"fk_{table}_agency_id_client_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f(f"fk_{table}_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_whatsapp_numbers_scope"),
    )
    # One verified binding per number; one unrevoked claim per client and number (D-070).
    op.create_index(
        "uq_whatsapp_numbers_verified",
        table,
        ["phone_number_id"],
        unique=True,
        postgresql_where=sa.text(VERIFIED),
    )
    op.create_index(
        "uq_whatsapp_numbers_claim",
        table,
        ["client_id", "phone_number_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'revoked'"),
    )

    table = "whatsapp_messages"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("number_id", sa.Uuid(), nullable=False),
        sa.Column("message_digest", sa.String(length=64), nullable=False),
        _time("message_at", nullable=True),
        _time("received_at"),
        sa.Column("has_referral", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.String(length=8), nullable=True),
        sa.Column("source_id", sa.String(length=32), nullable=True),
        sa.Column(
            "click_id_present", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        _check(table, "valid_digest", "message_digest ~ '^[0-9a-f]{64}$'"),
        _check(
            table,
            "valid_referral",
            "(has_referral = false AND source_type IS NULL AND source_id IS NULL "
            "AND click_id_present = false) OR (has_referral = true AND source_type IN "
            "('ad', 'post', 'other') AND (source_id IS NULL OR source_id ~ '^[1-9][0-9]{0,31}$'))",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "number_id"],
            ["whatsapp_numbers.agency_id", "whatsapp_numbers.client_id", "whatsapp_numbers.id"],
            name=op.f(f"fk_{table}_agency_id_whatsapp_numbers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("message_digest", name="uq_whatsapp_messages_digest"),
    )
    op.create_index("ix_whatsapp_messages_client_received", table, ["client_id", "received_at"])

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
            + " OR EXISTS (SELECT 1 FROM audit_events WHERE resource_type = 'whatsapp_number')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove WhatsApp state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    for table in TABLES:
        op.drop_table(table)
    _replace_check("audit_events", "valid_resource", PREVIOUS_RESOURCES)
    _replace_check("audit_events", "valid_action", PREVIOUS_ACTIONS)
