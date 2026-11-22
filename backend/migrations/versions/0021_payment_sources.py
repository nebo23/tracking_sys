"""Paymob payment sources, sealed HMAC secrets and callback diagnostics

Revision ID: 0021_payment_sources
Revises: 0020_revenue_evidence
Created: 2026-11-21

Specification 015-B (D-067 decisions D3, D4, D12, D14 and D15; design in
specs/015-business-integrations/design-015a.md section 4). Adds payment_sources (one client's
Paymob source with the public key of its callback URL and the merchant's declared live
integration IDs, added in place under D-070 because a callback's is_live is unsigned),
payment_source_secrets (the merchant's
HMAC secret sealed under the D-025 keyring; a replaced version retires 24 hours later) and
payment_callback_diagnostics (one row per verified callback: a digest of the received signature,
the receipt time and a closed outcome). Audit events accept the payment_source actions and
resource. tracking_app may insert and read, update a source's name, status, live integration IDs
and update time and a secret's retirement time, and delete nothing; tracking_lifecycle may delete
retired secrets and diagnostics older than 30 days and read only their keys and times. The
downgrade refuses any payment source state, any Paymob evidence and any new audit action.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0021_payment_sources"
down_revision: str | Sequence[str] | None = "0020_revenue_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Children before parents.
TABLES = ("payment_callback_diagnostics", "payment_source_secrets", "payment_sources")
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
    "'delivery.requeued', 'delivery.dismissed')"
)
NEW_ACTIONS = ("payment_source.created", "payment_source.updated", "payment_source.secret_replaced")
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'payment_source')"
OUTCOMES = "'stored', 'duplicate', 'not_posted', 'unmapped', 'test_mode'"
REASONS = (
    "'authorization', 'failed', 'pending', 'card_token', 'unsupported_state', "
    "'unsupported_currency', 'invalid_time', 'invalid_amount', 'invalid_parent', "
    "'undeclared_integration'"
)
PUBLIC_KEY = "^ppk_[A-Za-z0-9_-]{43}$"
# D-070: 1 to 20 positive live integration IDs per source, without nulls.
LIVE_INTEGRATIONS = (
    "cardinality(live_integration_ids) BETWEEN 1 AND 20 "
    "AND array_position(live_integration_ids, NULL) IS NULL "
    "AND 0 < ALL (live_integration_ids)"
)
SOURCE = ["payment_sources.agency_id", "payment_sources.client_id", "payment_sources.id"]
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    "GRANT UPDATE (name, status, live_integration_ids, updated_at) ON payment_sources "
    "TO tracking_app",
    "GRANT UPDATE (retires_at) ON payment_source_secrets TO tracking_app",
)
LIFECYCLE_GRANTS = (
    "GRANT SELECT (id, retires_at) ON payment_source_secrets TO tracking_lifecycle",
    "GRANT DELETE ON payment_source_secrets TO tracking_lifecycle",
    "GRANT SELECT (id, received_at) ON payment_callback_diagnostics TO tracking_lifecycle",
    "GRANT DELETE ON payment_callback_diagnostics TO tracking_lifecycle",
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _scope(table: str) -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


def _source(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", "source_id"],
        SOURCE,
        name=op.f(f"fk_{table}_agency_id_payment_sources"),
    )


def upgrade() -> None:
    _replace_check("audit_events", "valid_action", ACTIONS)
    _replace_check("audit_events", "valid_resource", RESOURCES)

    table = "payment_sources"
    op.create_table(
        table,
        *_scope(table),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("region", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("live_integration_ids", sa.ARRAY(sa.BigInteger()), nullable=False),
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
        _check(table, "valid_provider", "provider = 'paymob'"),
        _check(table, "valid_region", "region = 'egypt'"),
        _check(table, "valid_status", "status IN ('active', 'disabled')"),
        _check(table, "valid_name", "length(btrim(name)) BETWEEN 1 AND 200"),
        _check(table, "valid_public_key", f"public_key ~ '{PUBLIC_KEY}'"),
        _check(table, "valid_live_integrations", LIVE_INTEGRATIONS),
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
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_payment_sources_scope"),
        sa.UniqueConstraint("public_key", name="uq_payment_sources_public_key"),
    )
    op.create_index("ix_payment_sources_agency_client", table, ["agency_id", "client_id"])

    table = "payment_source_secrets"
    op.create_table(
        table,
        *_scope(table),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=False),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("retires_at", sa.DateTime(timezone=True), nullable=True),
        _check(table, "positive_version", "version >= 1"),
        _source(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("source_id", "version", name="uq_payment_source_secrets_version"),
    )

    table = "payment_callback_diagnostics"
    op.create_table(
        table,
        *_scope(table),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_digest", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        _check(table, "valid_outcome", f"outcome IN ({OUTCOMES})"),
        _check(table, "valid_reason", f"reason IS NULL OR reason IN ({REASONS})"),
        _check(table, "valid_digest", "delivery_digest ~ '^[0-9a-f]{64}$'"),
        _source(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    )
    op.create_index("ix_payment_callback_diagnostics_received_at", table, ["received_at"])

    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, "revenue_evidence", "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{item}'" for item in NEW_ACTIONS)
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
            + " OR EXISTS (SELECT 1 FROM revenue_evidence WHERE intake = 'paymob')"
            + f" OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
            + " OR EXISTS (SELECT 1 FROM audit_events WHERE resource_type = 'payment_source')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove payment source state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    for table in TABLES:
        op.drop_table(table)
    _replace_check("audit_events", "valid_resource", PREVIOUS_RESOURCES)
    _replace_check("audit_events", "valid_action", PREVIOUS_ACTIONS)
