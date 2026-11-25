"""Sale-to-person association revisions

Revision ID: 0028_revenue_identity
Revises: 0027_ledger_persistence
Created: 2026-11-23

Specification 007-C (D-075, joint decision J10; specs/006-identity-journey/joint-design.md
sections 3 and 5). Adds revenue_identity_bindings: append-only revisions of the association
between one verified sale (client, source account, sale operation) and the person a trusted,
consented 006 identity assertion names. Each revision records the originating ingest
credential, the identity assertion, its collection subject, the original identity owner and the
key evidence, the server receipt time, its state and the revision it superseded. It stores no
raw identifier, subject token, handoff or merge root, and no amount: money stays in the ledger.

F1 (J6): withdrawal, erasure or expiry clears every identifying pointer and the request's
retry material on every revision of the person, keeping only a non-identifying record that the
association was unlinked. A replay of an erased or withdrawn request cannot restore a binding,
because a new association needs a new, valid assertion and current consent.

tracking_app may insert revisions, read them and update the closure and F1 columns;
tracking_lifecycle may apply F1 and close revisions when identity evidence expires. Audit events
accept revenue.association_detached and the revenue_association resource. The downgrade refuses
any stored revision or new audit action.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0028_revenue_identity"
down_revision: str | Sequence[str] | None = "0027_ledger_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "revenue_identity_bindings"
STATES = "'pending', 'active', 'ambiguous', 'detached', 'unlinked'"
REASONS = (
    "'withdrawn', 'erased', 'expired', 'detached_by_manager', 'conflicting_owner', "
    "'attribution_withdrawn'"
)
DETACH_REASONS = "'mistaken_association', 'customer_request', 'data_correction'"
NEW_ACTION = "revenue.association_detached"
NEW_RESOURCE = "revenue_association"
F1_COLUMNS = (
    "state, reason, closed_at, request_id, request_fingerprint, assertion_ref, "
    "collection_subject_id, owner_subject_id, key_ids"
)
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {TABLE} TO tracking_app",
    f"GRANT UPDATE ({F1_COLUMNS}) ON {TABLE} TO tracking_app",
)
LIFECYCLE_GRANTS = (
    f"GRANT SELECT ON {TABLE} TO tracking_lifecycle",
    f"GRANT UPDATE ({F1_COLUMNS}) ON {TABLE} TO tracking_lifecycle",
)


def _check(name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{TABLE}_{name}"))


def _swap(name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_audit_events_{name}"), "audit_events", type_="check")
    op.create_check_constraint(op.f(f"ck_audit_events_{name}"), "audit_events", condition)


def _actions(extended: bool) -> str:
    base = _base_actions()
    return base[:-1] + f", '{NEW_ACTION}')" if extended else base


def _base_actions() -> str:
    return (
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
        "'identity.merged', 'identity.unmerged', 'identity.erased', 'identity.erasure_resolved', "
        "'revenue.reconciliation_reviewed')"
    )


RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule', 'whatsapp_number', 'identity_subject', 'revenue_issue')"
)
NEW_RESOURCES = RESOURCES[:-1] + f", '{NEW_RESOURCE}')"


def upgrade() -> None:
    _swap("valid_action", _actions(True))
    _swap("valid_resource", NEW_RESOURCES)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("association_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("source_account_id", sa.String(length=256), nullable=False),
        sa.Column("sale_operation_id", sa.String(length=256), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=True),
        sa.Column("assertion_ref", sa.Uuid(), nullable=True),
        sa.Column("collection_subject_id", sa.Uuid(), nullable=True),
        sa.Column("owner_subject_id", sa.Uuid(), nullable=True),
        sa.Column(
            "key_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("detach_reason", sa.String(length=32), nullable=True),
        sa.Column("expected_revision", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        _check("valid_state", f"state IN ({STATES})"),
        _check("valid_reason", f"reason IS NULL OR reason IN ({REASONS})"),
        _check(
            "valid_detach_reason", f"detach_reason IS NULL OR detach_reason IN ({DETACH_REASONS})"
        ),
        _check("positive_revision", "revision >= 1"),
        _check(
            "fingerprint",
            "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
        ),
        _check(
            "origin",
            "(state = 'detached') = "
            "(actor_membership_id IS NOT NULL AND detach_reason IS NOT NULL)",
        ),
        # F1: an unlinked revision keeps no identifying pointer or retry material.
        _check(
            "unlinked_minimal",
            "state <> 'unlinked' OR (request_id IS NULL AND request_fingerprint IS NULL "
            "AND assertion_ref IS NULL AND collection_subject_id IS NULL "
            "AND owner_subject_id IS NULL AND cardinality(key_ids) = 0 AND reason IS NOT NULL)",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name=op.f(f"fk_{TABLE}_agency_id_client_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "credential_id"],
            ["service_credentials.agency_id", "service_credentials.id"],
            name=op.f(f"fk_{TABLE}_agency_id_service_credentials"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "actor_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f(f"fk_{TABLE}_agency_id_agency_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "assertion_ref"],
            [
                "identity_assertions.agency_id",
                "identity_assertions.client_id",
                "identity_assertions.id",
            ],
            name="fk_revenue_bindings_assertion",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "collection_subject_id"],
            [
                "collection_subjects.agency_id",
                "collection_subjects.client_id",
                "collection_subjects.id",
            ],
            name="fk_revenue_bindings_collection_subject",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "owner_subject_id"],
            ["identity_subjects.agency_id", "identity_subjects.client_id", "identity_subjects.id"],
            name="fk_revenue_bindings_owner",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint(
            "client_id", "association_id", "revision", name="uq_revenue_identity_bindings_revision"
        ),
        sa.UniqueConstraint("client_id", "request_id", name="uq_revenue_identity_bindings_request"),
    )
    op.create_index(
        "ix_revenue_identity_bindings_sale",
        TABLE,
        ["client_id", "source_account_id", "sale_operation_id"],
    )
    op.create_index("ix_revenue_identity_bindings_owner", TABLE, ["owner_subject_id"])
    op.create_index("ix_revenue_identity_bindings_subject", TABLE, ["collection_subject_id"])
    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (TABLE, "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    populated = connection.execute(
        sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {TABLE})"
            f" OR EXISTS (SELECT 1 FROM audit_events WHERE action = '{NEW_ACTION}')"
            f" OR EXISTS (SELECT 1 FROM audit_events WHERE resource_type = '{NEW_RESOURCE}')"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove sale associations; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    op.drop_table(TABLE)
    _swap("valid_resource", RESOURCES)
    _swap("valid_action", _actions(False))
