"""CRM stage rules and deals

Revision ID: 0024_crm_deals
Revises: 0023_integration_bookings
Created: 2026-11-21

Specification 015-D (D-068 decisions E5, E6, E9, E10 and E12; design in
specs/015-business-integrations/design-015b.md). Adds crm_stage_rules (a client's approved won or
lost stage of a pipeline) and crm_deals (the latest known stage of a deal received through a
signed webhook source, with an optional amount and payment reference). A stage change never
becomes revenue; the deal read checks a won deal's payment reference against the verified
ledger. Audit events accept the crm_rule actions and resource. tracking_app may insert and read,
and update only the rule outcome and status and the deal's stage columns; tracking_lifecycle may
delete deals 395 days after their last update. The downgrade refuses any rule, deal or new audit
action.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0024_crm_deals"
down_revision: str | Sequence[str] | None = "0023_integration_bookings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("crm_deals", "crm_stage_rules")
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
    "'integration.updated', 'integration.secret_replaced')"
)
NEW_ACTIONS = ("crm_rule.created", "crm_rule.updated")
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'crm_rule')"
DEAL_UPDATES = (
    "pipeline",
    "stage",
    "previous_stage",
    "stage_at",
    "amount_minor",
    "currency",
    "currency_exponent",
    "payment_reference",
    "updated_at",
)
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    "GRANT UPDATE (outcome, status, updated_at) ON crm_stage_rules TO tracking_app",
    f"GRANT UPDATE ({', '.join(DEAL_UPDATES)}) ON crm_deals TO tracking_app",
)
LIFECYCLE_GRANTS = (
    "GRANT SELECT (id, updated_at) ON crm_deals TO tracking_lifecycle",
    "GRANT DELETE ON crm_deals TO tracking_lifecycle",
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _client(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id"],
        ["client_workspaces.agency_id", "client_workspaces.id"],
        name=op.f(f"fk_{table}_agency_id_client_workspaces"),
    )


def upgrade() -> None:
    _replace_check("audit_events", "valid_action", ACTIONS)
    _replace_check("audit_events", "valid_resource", RESOURCES)

    table = "crm_stage_rules"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline", sa.String(length=128), nullable=False),
        sa.Column("stage", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _check(table, "valid_outcome", "outcome IN ('won', 'lost')"),
        _check(table, "valid_status", "status IN ('active', 'disabled')"),
        _check(
            table,
            "valid_names",
            "length(pipeline) BETWEEN 1 AND 128 AND length(stage) BETWEEN 1 AND 128",
        ),
        _client(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f(f"fk_{table}_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("client_id", "pipeline", "stage", name="uq_crm_stage_rules_stage"),
    )

    table = "crm_deals"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("deal_ref", sa.String(length=128), nullable=False),
        sa.Column("pipeline", sa.String(length=128), nullable=False),
        sa.Column("stage", sa.String(length=128), nullable=False),
        sa.Column("previous_stage", sa.String(length=128), nullable=True),
        sa.Column("stage_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("currency_exponent", sa.SmallInteger(), nullable=True),
        sa.Column("payment_reference", sa.String(length=128), nullable=True),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _check(
            table,
            "valid_text",
            "length(deal_ref) BETWEEN 1 AND 128 AND length(pipeline) BETWEEN 1 AND 128 "
            "AND length(stage) BETWEEN 1 AND 128 "
            "AND (previous_stage IS NULL OR length(previous_stage) BETWEEN 1 AND 128) "
            "AND (payment_reference IS NULL OR length(payment_reference) BETWEEN 1 AND 128)",
        ),
        _check(
            table,
            "valid_amount",
            "(amount_minor IS NULL) = (currency IS NULL) "
            "AND (currency IS NULL) = (currency_exponent IS NULL) "
            "AND (amount_minor IS NULL OR amount_minor > 0) "
            "AND (currency IS NULL OR currency ~ '^[A-Z]{3}$')",
        ),
        _client(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "source_id"],
            [
                "integration_sources.agency_id",
                "integration_sources.client_id",
                "integration_sources.id",
            ],
            name=op.f(f"fk_{table}_agency_id_integration_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("source_id", "deal_ref", name="uq_crm_deals_deal"),
    )
    op.create_index("ix_crm_deals_client_updated", table, ["client_id", "updated_at"])

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
            + " OR EXISTS (SELECT 1 FROM audit_events WHERE resource_type = 'crm_rule')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove CRM state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    for table in TABLES:
        op.drop_table(table)
    _replace_check("audit_events", "valid_resource", PREVIOUS_RESOURCES)
    _replace_check("audit_events", "valid_action", PREVIOUS_ACTIONS)
