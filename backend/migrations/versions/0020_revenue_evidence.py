"""Revenue evidence: the append-only receipt log of 007-A evidence records

Revision ID: 0020_revenue_evidence
Revises: 0019_meta_providers
Created: 2026-11-21

Specification 015-A (D-067 decisions D2, D11, D14 and D15; design in
specs/015-business-integrations/design-015a.md). Adds revenue_evidence, one row per received
007-A Evidence record of one client with its intake provenance (a Paymob source, a CSV import or
a manual entry) and a content digest. An exact redelivery is stored once through the unique
(client, source account, delivery ID, content digest) key; the ledger is derived on read and
never stored. tracking_app may insert and read only, so evidence is never updated or deleted;
tracking_lifecycle has no access, because evidence is kept for the life of the client workspace
(D14). The downgrade refuses any stored evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0020_revenue_evidence"
down_revision: str | Sequence[str] | None = "0019_meta_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "revenue_evidence"
KINDS = "'sale', 'refund', 'chargeback', 'chargeback_reversal', 'correction'"
INTAKES = "'paymob', 'csv_import', 'manual_entry'"
ALLOWED_CLASSES = (
    "(kind = 'sale' AND classification IN ('confirmed_capture', 'confirmed_settlement', "
    "'manual_declaration', 'purchase_signal')) "
    "OR (kind IN ('refund', 'chargeback', 'chargeback_reversal') "
    "AND classification IN ('confirmed_adjustment', 'manual_declaration')) "
    "OR (kind = 'correction' AND classification = 'audited_correction')"
)
TEXT_LIMITS = (
    "length(delivery_id) BETWEEN 1 AND 256 AND length(source_account_id) BETWEEN 1 AND 256 "
    "AND length(operation_id) BETWEEN 1 AND 256 "
    "AND (parent_operation_id IS NULL OR length(parent_operation_id) BETWEEN 1 AND 256) "
    "AND (reason IS NULL OR length(reason) BETWEEN 1 AND 1024) "
    "AND (actor IS NULL OR length(actor) BETWEEN 1 AND 256) "
    "AND (source_reference IS NULL OR length(source_reference) BETWEEN 1 AND 256)"
)
RUNTIME_GRANTS = (f"GRANT SELECT, INSERT ON {TABLE} TO tracking_app",)


def _check(name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{TABLE}_{name}"))


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.String(length=256), nullable=False),
        sa.Column("source_account_id", sa.String(length=256), nullable=False),
        sa.Column("operation_id", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("currency_exponent", sa.SmallInteger(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parent_operation_id", sa.String(length=256), nullable=True),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column("actor", sa.String(length=256), nullable=True),
        sa.Column("source_reference", sa.String(length=256), nullable=True),
        sa.Column("intake", sa.String(length=16), nullable=False),
        sa.Column("intake_id", sa.Uuid(), nullable=True),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        _check("valid_kind", f"kind IN ({KINDS})"),
        _check("valid_classification", ALLOWED_CLASSES),
        _check("valid_intake", f"intake IN ({INTAKES})"),
        _check("intake_reference", "(intake = 'manual_entry') = (intake_id IS NULL)"),
        _check("valid_currency", "currency ~ '^[A-Z]{3}$' AND currency_exponent BETWEEN 0 AND 8"),
        _check("valid_amount", "(kind = 'correction' AND amount_minor <> 0) OR amount_minor > 0"),
        _check(
            "valid_parent",
            "(kind = 'sale') = (parent_operation_id IS NULL) "
            "AND (parent_operation_id IS NULL OR parent_operation_id <> operation_id)",
        ),
        _check("valid_text", TEXT_LIMITS),
        _check("valid_digest", "content_digest ~ '^[0-9a-f]{64}$'"),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name=op.f(f"fk_{TABLE}_agency_id_client_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint(
            "client_id",
            "source_account_id",
            "delivery_id",
            "content_digest",
            name="uq_revenue_evidence_delivery",
        ),
        sa.UniqueConstraint("sequence", name="uq_revenue_evidence_sequence"),
    )
    op.create_index("ix_revenue_evidence_receipt", TABLE, ["client_id", "received_at", "sequence"])
    for statement in RUNTIME_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {TABLE})")).scalar_one():
        raise RuntimeError("Refuse to remove stored revenue evidence; use a forward fix.")
    for statement in RUNTIME_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    op.drop_table(TABLE)
