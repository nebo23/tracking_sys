"""Revenue import records for transaction CSV commits

Revision ID: 0022_revenue_imports
Revises: 0021_payment_sources
Created: 2026-11-21

Specification 015-C (D-067 decisions D8, D9, D14 and D15; design in
specs/015-business-integrations/design-015a.md section 5). Adds revenue_imports: one row per
committed transaction CSV file of one client, with the file's SHA-256 digest (unique per client,
which makes a repeated commit a no-op) and its row counts; the file itself is never kept. Audit
events accept the revenue_import.committed and revenue.declared actions and the revenue_import
and revenue_evidence resources. tracking_app may insert and read import records; the lifecycle
role may delete them 13 months (395 days) after the commit and read only their keys and times.
The downgrade refuses any import record, any declared evidence and any new audit action.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0022_revenue_imports"
down_revision: str | Sequence[str] | None = "0021_payment_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "revenue_imports"
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
    "'payment_source.updated', 'payment_source.secret_replaced')"
)
NEW_ACTIONS = ("revenue_import.committed", "revenue.declared")
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'revenue_import', 'revenue_evidence')"
RUNTIME_GRANTS = (f"GRANT SELECT, INSERT ON {TABLE} TO tracking_app",)
LIFECYCLE_GRANTS = (
    f"GRANT SELECT (id, committed_at) ON {TABLE} TO tracking_lifecycle",
    f"GRANT DELETE ON {TABLE} TO tracking_lifecycle",
)


def _check(name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{TABLE}_{name}"))


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    _replace_check("audit_events", "valid_action", ACTIONS)
    _replace_check("audit_events", "valid_resource", RESOURCES)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("file_digest", sa.String(length=64), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("stored_rows", sa.Integer(), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("committed_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        _check("valid_digest", "file_digest ~ '^[0-9a-f]{64}$'"),
        _check(
            "valid_counts",
            "total_rows BETWEEN 1 AND 10000 AND stored_rows >= 0 AND duplicate_rows >= 0 "
            "AND rejected_rows >= 0 AND stored_rows + duplicate_rows + rejected_rows = total_rows",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name=op.f(f"fk_{TABLE}_agency_id_client_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "committed_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f(f"fk_{TABLE}_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint("client_id", "file_digest", name="uq_revenue_imports_file"),
    )
    op.create_index("ix_revenue_imports_committed_at", TABLE, ["committed_at"])
    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (TABLE, "revenue_evidence", "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{item}'" for item in NEW_ACTIONS)
    populated = connection.execute(
        sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {TABLE})"
            " OR EXISTS (SELECT 1 FROM revenue_evidence "
            "WHERE intake IN ('csv_import', 'manual_entry'))"
            f" OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
            " OR EXISTS (SELECT 1 FROM audit_events "
            "WHERE resource_type IN ('revenue_import', 'revenue_evidence'))"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove revenue import state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    op.drop_table(TABLE)
    _replace_check("audit_events", "valid_resource", PREVIOUS_RESOURCES)
    _replace_check("audit_events", "valid_action", PREVIOUS_ACTIONS)
