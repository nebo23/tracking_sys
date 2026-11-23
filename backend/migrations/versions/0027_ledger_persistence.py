"""Persisted revenue receipts, movements, projections and reconciliation actions

Revision ID: 0027_ledger_persistence
Revises: 0026_identity_journey
Created: 2026-11-23

Specification 007-B (D-075, joint decisions J7-J9 and J11; specs/006-identity-journey/
joint-design.md sections 3 and 4). revenue_evidence stays the append-only source of financial
truth; this revision adds the persisted journal over it:

- ledger_projection_state: one row per client with the published generation, an optional
  staging generation, the algorithm, the status (building, ready, failed) and the cursors of
  the published generation (last evidence sequence, receipt ordinal, movement sequence, last
  receipt digest and receipt time, financial revision).
- ledger_receipts: one immutable position per stored evidence row and generation, including
  held, conflicting and unverified evidence, with the input, previous and receipt digests, the
  receipt's outcome and the closing states of the sale transactions it moved or changed.
- ledger_movements: the immutable signed postings and releases in minor units of their
  original currency, each with its receipt and trigger evidence; no person or identity key.
- ledger_transactions: the replaceable current projection of each sale transaction (totals in
  minor units, current entries and evidence references), updated with every receipt.
- ledger_reconciliation_actions: append-only, idempotent acknowledge and reopen decisions by an
  Owner or Admin; they never change evidence, amounts or unresolved counts.

revenue_evidence gains the scoped unique key that receipts, movements and actions reference.
Audit events accept revenue.reconciliation_reviewed and the revenue_issue resource.
tracking_app may insert receipts, movements, actions and the first projection state, update
the published cursors and replace transaction projections; it can never update or delete a
receipt or movement. Rebuilding and discarding a staging generation are operator tasks
(app.ledger_backfill, migration role). The lifecycle role has no access: financial rows follow
the workspace lifetime. The downgrade refuses any populated ledger table or new audit action.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0027_ledger_persistence"
down_revision: str | Sequence[str] | None = "0026_identity_journey"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "ledger_reconciliation_actions",
    "ledger_transactions",
    "ledger_movements",
    "ledger_receipts",
    "ledger_projection_state",
)
PREVIOUS_ACTIONS_TAIL = (
    "'identity.merged', 'identity.unmerged', 'identity.erased', 'identity.erasure_resolved')"
)
NEW_ACTION = "revenue.reconciliation_reviewed"
NEW_RESOURCE = "revenue_issue"
OUTCOMES = "'posted', 'duplicate', 'pending', 'reconciliation', 'unverified', 'excluded', 'held'"
REASON_CODES = (
    "'provider_contacted', 'awaiting_evidence', 'confirmed_duplicate', 'reviewed_no_action', "
    "'new_information'"
)
KINDS = "'sale', 'refund', 'chargeback', 'chargeback_reversal', 'correction'"
RUNTIME_GRANTS = (
    "GRANT SELECT, INSERT ON ledger_receipts, ledger_movements, ledger_reconciliation_actions "
    "TO tracking_app",
    "GRANT SELECT, INSERT, DELETE ON ledger_transactions TO tracking_app",
    "GRANT UPDATE (currency, currency_exponent, sale_effective_at, captured, refunded, "
    "charged_back, reversed, corrected, net, entries, evidence_ids, financial_revision, "
    "updated_at) ON ledger_transactions TO tracking_app",
    "GRANT SELECT, INSERT ON ledger_projection_state TO tracking_app",
    "GRANT UPDATE (last_evidence_sequence, receipt_ordinal, movement_sequence, receipt_digest, "
    "last_received_at, financial_revision, updated_at) ON ledger_projection_state "
    "TO tracking_app",
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


def _client_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id"],
        ["client_workspaces.agency_id", "client_workspaces.id"],
        name=op.f(f"fk_{table}_agency_id_client_workspaces"),
    )


def _scoped_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", column],
        [f"{target}.agency_id", f"{target}.client_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}"[:63],
    )


def _scope() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


ACTIONS_SQL = (
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
    "'crm_rule.updated', 'whatsapp_number.created', 'whatsapp_number.updated', "
    + PREVIOUS_ACTIONS_TAIL
)
NEW_ACTIONS_SQL = ACTIONS_SQL[:-1] + f", '{NEW_ACTION}')"
RESOURCES_SQL = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule', 'whatsapp_number', 'identity_subject')"
)
NEW_RESOURCES_SQL = RESOURCES_SQL[:-1] + f", '{NEW_RESOURCE}')"


def upgrade() -> None:
    _replace_check("audit_events", "valid_action", NEW_ACTIONS_SQL)
    _replace_check("audit_events", "valid_resource", NEW_RESOURCES_SQL)
    op.create_unique_constraint(
        "uq_revenue_evidence_scope", "revenue_evidence", ["agency_id", "client_id", "id"]
    )

    table = "ledger_projection_state"
    op.create_table(
        table,
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("staging_generation", sa.Integer(), nullable=True),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_evidence_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("receipt_ordinal", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("movement_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("receipt_digest", sa.LargeBinary(), nullable=False),
        _time("last_received_at", nullable=True),
        sa.Column("financial_revision", sa.BigInteger(), server_default="0", nullable=False),
        _time("updated_at", default=True),
        _check(table, "valid_status", "status IN ('building', 'ready', 'failed')"),
        _check(table, "ready_generation", "status <> 'ready' OR generation >= 1"),
        _check(
            table,
            "valid_counters",
            "generation >= 0 AND last_evidence_sequence >= 0 AND receipt_ordinal >= 0 "
            "AND movement_sequence >= 0 AND financial_revision >= 0",
        ),
        _check(table, "digest_length", "octet_length(receipt_digest) = 32"),
        _check(
            table,
            "staging",
            "staging_generation IS NULL OR staging_generation > generation",
        ),
        _client_fk(table),
        sa.PrimaryKeyConstraint("client_id", name=op.f(f"pk_{table}")),
    )

    table = "ledger_receipts"
    op.create_table(
        table,
        *_scope(),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("receipt_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_sequence", sa.BigInteger(), nullable=False),
        sa.Column("input_digest", sa.LargeBinary(), nullable=False),
        sa.Column("previous_digest", sa.LargeBinary(), nullable=False),
        sa.Column("receipt_digest", sa.LargeBinary(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column(
            "closing_states",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _time("created_at", default=True),
        _check(table, "valid_outcome", f"outcome IN ({OUTCOMES})"),
        _check(table, "positions", "generation >= 1 AND receipt_ordinal >= 1"),
        _check(
            table,
            "digests",
            "octet_length(input_digest) = 32 AND octet_length(previous_digest) = 32 "
            "AND octet_length(receipt_digest) = 32",
        ),
        _client_fk(table),
        _scoped_fk(table, "evidence_id", "revenue_evidence"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_ledger_receipts_scope"),
        sa.UniqueConstraint(
            "client_id", "generation", "receipt_ordinal", name="uq_ledger_receipts_ordinal"
        ),
        sa.UniqueConstraint(
            "client_id", "generation", "evidence_id", name="uq_ledger_receipts_evidence"
        ),
    )

    table = "ledger_movements"
    op.create_table(
        table,
        *_scope(),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("movement_sequence", sa.BigInteger(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.String(length=256), nullable=False),
        sa.Column("transaction_id", sa.String(length=256), nullable=False),
        sa.Column("operation_id", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("currency_exponent", sa.SmallInteger(), nullable=False),
        _time("effective_at"),
        sa.Column("trigger_evidence_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        _check(table, "valid_kind", f"kind IN ({KINDS})"),
        _check(table, "valid_direction", "direction IN ('posting', 'release')"),
        _check(table, "nonzero_amount", "amount_minor <> 0"),
        _check(
            table,
            "valid_currency",
            "currency ~ '^[A-Z]{3}$' AND currency_exponent BETWEEN 0 AND 8",
        ),
        _check(table, "positions", "generation >= 1 AND movement_sequence >= 1"),
        _client_fk(table),
        _scoped_fk(table, "receipt_id", "ledger_receipts"),
        _scoped_fk(table, "trigger_evidence_id", "revenue_evidence"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(
            "client_id", "generation", "movement_sequence", name="uq_ledger_movements_sequence"
        ),
    )
    op.create_index(
        "ix_ledger_movements_transaction",
        table,
        ["client_id", "generation", "source_account_id", "transaction_id"],
    )

    table = "ledger_transactions"
    op.create_table(
        table,
        *_scope(),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("source_account_id", sa.String(length=256), nullable=False),
        sa.Column("operation_id", sa.String(length=256), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("currency_exponent", sa.SmallInteger(), nullable=False),
        _time("sale_effective_at"),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in ("captured", "refunded", "charged_back", "reversed", "corrected", "net")
        ],
        sa.Column("entries", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "evidence_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("financial_revision", sa.BigInteger(), nullable=False),
        _time("updated_at", default=True),
        _check(
            table,
            "valid_currency",
            "currency ~ '^[A-Z]{3}$' AND currency_exponent BETWEEN 0 AND 8",
        ),
        _check(
            table,
            "net_total",
            "net = captured - refunded - charged_back + reversed + corrected",
        ),
        _client_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(
            "client_id",
            "generation",
            "source_account_id",
            "operation_id",
            name="uq_ledger_transactions_key",
        ),
    )

    table = "ledger_reconciliation_actions"
    op.create_table(
        table,
        *_scope(),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("issue_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("issue_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "evidence_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        _time("created_at", default=True),
        _check(table, "valid_action", "action IN ('acknowledge', 'reopen')"),
        _check(table, "valid_reason", f"reason_code IN ({REASON_CODES})"),
        _check(
            table,
            "fingerprints",
            "issue_fingerprint ~ '^[0-9a-f]{64}$' AND request_fingerprint ~ '^[0-9a-f]{64}$'",
        ),
        _client_fk(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "actor_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f(f"fk_{table}_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("client_id", "operation_id", name="uq_ledger_actions_operation"),
    )
    op.create_index("ix_ledger_reconciliation_actions_issue", table, ["client_id", "issue_id"])

    for statement in RUNTIME_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, "audit_events", "revenue_evidence"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
            + f" OR EXISTS (SELECT 1 FROM audit_events WHERE action = '{NEW_ACTION}')"
            + f" OR EXISTS (SELECT 1 FROM audit_events WHERE resource_type = '{NEW_RESOURCE}')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove persisted ledger state; use a forward fix.")
    for table in TABLES:
        op.drop_table(table)
    op.drop_constraint("uq_revenue_evidence_scope", "revenue_evidence", type_="unique")
    _replace_check("audit_events", "valid_resource", RESOURCES_SQL)
    _replace_check("audit_events", "valid_action", ACTIONS_SQL)
