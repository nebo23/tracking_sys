"""SaaS plans, plan assignments, agency closures and agreement records

Revision ID: 0031_saas_plans
Revises: 0030_reporting_indexes
Created: 2026-11-26

Specification 017-A (D-092, decisions D2, D3, D7, D8, D10 and D12;
specs/017-saas-lifecycle/design-017a.md section 2). Adds saas_plans (immutable plans apart
from the default flag, each limit nullable for unlimited, one default by partial unique index),
agency_plan_assignments (insert-only history; the current plan is the highest revision of an
agency), agency_closures (at most one open closure per agency; only the cancellation and
completion columns change) and user_agreements (one row per account, document and version).
Seeds the development plan with the D3 limits as the default and assigns it to every existing
agency.

Existing tables: agencies.status accepts closing and closed; oauth_transactions gains the
agreement versions a Google sign-in accepted at its start; audit_events gains actor_kind, so
the platform operator's changes are audited without a user, and accepts platform-level plan
events without an agency, the seven new actions and the three new resources.

tracking_app may read and insert the new tables, update only the default flag of a plan and
the cancellation columns of a closure; it deletes nothing. tracking_lifecycle may complete a
due closure (agency status and the closure's completion time only) and delete the agreements
of closed accounts. The downgrade refuses every stored row beyond the seed: an operator plan or
assignment, a closure, an agreement, a closing or closed agency, an agreement version in a
transaction, or a new audit value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0031_saas_plans"
down_revision: str | Sequence[str] | None = "0030_reporting_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLANS = "saas_plans"
ASSIGNMENTS = "agency_plan_assignments"
CLOSURES = "agency_closures"
AGREEMENTS = "user_agreements"
TABLES = (AGREEMENTS, CLOSURES, ASSIGNMENTS, PLANS)  # children first
LIMIT_COLUMNS = (
    "clients_limit",
    "seats_limit",
    "connections_limit",
    "managed_links_limit",
    "tracked_events_limit",
)
SEED = {
    "key": "development",
    "name": "Development",
    "clients_limit": 5,
    "seats_limit": 10,
    "connections_limit": 10,
    "managed_links_limit": 500,
    "tracked_events_limit": 100000,
}
NEW_ACTIONS = (
    "agency.plan_assigned",
    "agency.suspended",
    "agency.reactivated",
    "agency.closure_requested",
    "agency.closure_cancelled",
    "plan.created",
    "plan.default_set",
)
NEW_RESOURCES = ("plan", "plan_assignment", "agency_closure")
PREVIOUS_ACTIONS = (
    "'agency.created', 'agency.updated', 'client.created', 'client.updated', "
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
    "'revenue.reconciliation_reviewed', 'revenue.association_detached', "
    "'attribution.model_created', 'attribution.model_default_set', "
    "'attribution.model_retired'"
)
PREVIOUS_RESOURCES = (
    "'agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule', 'whatsapp_number', 'identity_subject', 'revenue_issue', "
    "'revenue_association', 'attribution_model'"
)
ACTOR_CHECK = (
    "(actor_kind = 'user' AND actor_user_id IS NOT NULL) "
    "OR (actor_kind = 'platform_operator' AND actor_user_id IS NULL)"
)
SCOPE_CHECK = (
    "agency_id IS NOT NULL OR (actor_kind = 'platform_operator' AND resource_type = 'plan')"
)
VERSION = "'^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$'"
OPEN = "cancelled_at IS NULL AND completed_at IS NULL"

RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {PLANS}, {ASSIGNMENTS}, {CLOSURES}, {AGREEMENTS} TO tracking_app",
    f"GRANT UPDATE (is_default) ON {PLANS} TO tracking_app",
    f"GRANT UPDATE (cancelled_at, cancelled_by_membership_id) ON {CLOSURES} TO tracking_app",
)
LIFECYCLE_GRANTS = (
    "GRANT SELECT (id, status) ON agencies TO tracking_lifecycle",
    "GRANT UPDATE (status, updated_at) ON agencies TO tracking_lifecycle",
    f"GRANT SELECT (id, agency_id, closes_at, cancelled_at, completed_at) ON {CLOSURES} "
    "TO tracking_lifecycle",
    f"GRANT UPDATE (completed_at) ON {CLOSURES} TO tracking_lifecycle",
    f"GRANT SELECT (id, user_id) ON {AGREEMENTS} TO tracking_lifecycle",
    f"GRANT DELETE ON {AGREEMENTS} TO tracking_lifecycle",
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _swap(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _listed(column: str, previous: str, new: Sequence[str]) -> str:
    extra = "".join(f", '{value}'" for value in new)
    return f"{column} IN ({previous}{extra})"


def _time(name: str, *, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def _plans() -> None:
    limits = " AND ".join(f"({name} IS NULL OR {name} >= 0)" for name in LIMIT_COLUMNS)
    op.create_table(
        PLANS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("clients_limit", sa.Integer(), nullable=True),
        sa.Column("seats_limit", sa.Integer(), nullable=True),
        sa.Column("connections_limit", sa.Integer(), nullable=True),
        sa.Column("managed_links_limit", sa.Integer(), nullable=True),
        sa.Column("tracked_events_limit", sa.BigInteger(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        _time("created_at", default=True),
        _check(PLANS, "valid_key", "key ~ '^[a-z][a-z0-9_-]{1,31}$'"),
        _check(PLANS, "name_not_blank", "length(btrim(name)) > 0"),
        _check(PLANS, "limits", limits),
        _check(
            PLANS, "valid_reason", "reason IN ('seed', 'new_offer', 'replacement', 'individual')"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PLANS}")),
        sa.UniqueConstraint("key", name=f"uq_{PLANS}_key"),
    )
    op.create_index(
        f"uq_{PLANS}_default",
        PLANS,
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def _assignments() -> None:
    op.create_table(
        ASSIGNMENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        _time("assigned_at", default=True),
        sa.Column("assigned_by", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        _check(ASSIGNMENTS, "positive_revision", "revision >= 1"),
        _check(ASSIGNMENTS, "valid_assigned_by", "assigned_by IN ('default', 'platform_operator')"),
        _check(
            ASSIGNMENTS,
            "valid_reason",
            "reason IN ('initial', 'new_agency', 'plan_change', 'correction')",
        ),
        _check(
            ASSIGNMENTS,
            "reason_matches",
            "(assigned_by = 'default') = (reason IN ('initial', 'new_agency'))",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f(f"fk_{ASSIGNMENTS}_agency_id_agencies")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], [f"{PLANS}.id"], name=op.f(f"fk_{ASSIGNMENTS}_plan_id_{PLANS}")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ASSIGNMENTS}")),
        sa.UniqueConstraint("agency_id", "revision", name=f"uq_{ASSIGNMENTS}_revision"),
    )
    op.create_index(f"ix_{ASSIGNMENTS}_plan_id", ASSIGNMENTS, ["plan_id"])


def _closures() -> None:
    op.create_table(
        CLOSURES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_membership_id", sa.Uuid(), nullable=False),
        _time("requested_at"),
        _time("closes_at"),
        _time("cancelled_at", nullable=True),
        sa.Column("cancelled_by_membership_id", sa.Uuid(), nullable=True),
        _time("completed_at", nullable=True),
        _check(CLOSURES, "grace_period", "closes_at > requested_at"),
        _check(
            CLOSURES,
            "cancellation",
            "(cancelled_at IS NULL) = (cancelled_by_membership_id IS NULL) "
            "AND (cancelled_at IS NULL "
            "OR (cancelled_at >= requested_at AND cancelled_at < closes_at))",
        ),
        _check(CLOSURES, "completion", "completed_at IS NULL OR completed_at >= closes_at"),
        _check(CLOSURES, "one_outcome", "cancelled_at IS NULL OR completed_at IS NULL"),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f(f"fk_{CLOSURES}_agency_id_agencies")
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "requested_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=f"fk_{CLOSURES}_requested_by_agency_memberships",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "cancelled_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=f"fk_{CLOSURES}_cancelled_by_agency_memberships",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{CLOSURES}")),
    )
    op.create_index(
        f"uq_{CLOSURES}_open", CLOSURES, ["agency_id"], unique=True, postgresql_where=sa.text(OPEN)
    )
    op.create_index(f"ix_{CLOSURES}_due", CLOSURES, ["closes_at"], postgresql_where=sa.text(OPEN))


def _agreements() -> None:
    op.create_table(
        AGREEMENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        _time("accepted_at", default=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        _check(AGREEMENTS, "valid_document", "document IN ('terms', 'privacy')"),
        _check(AGREEMENTS, "valid_version", f"version ~ {VERSION}"),
        _check(
            AGREEMENTS,
            "valid_channel",
            "channel IN ('registration', 'password_sign_in', 'google_sign_in')",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f(f"fk_{AGREEMENTS}_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{AGREEMENTS}")),
        sa.UniqueConstraint(
            "user_id", "document", "version", name=f"uq_{AGREEMENTS}_user_document_version"
        ),
    )


def _seed() -> None:
    columns = ", ".join(SEED)
    values = ", ".join(
        f"'{value}'" if isinstance(value, str) else str(value) for value in SEED.values()
    )
    op.execute(
        f"INSERT INTO {PLANS} (id, {columns}, is_default, reason) "
        f"VALUES (gen_random_uuid(), {values}, true, 'seed')"
    )
    op.execute(
        f"INSERT INTO {ASSIGNMENTS} (id, agency_id, plan_id, revision, assigned_by, reason) "
        f"SELECT gen_random_uuid(), a.id, p.id, 1, 'default', 'initial' "
        f"FROM agencies a CROSS JOIN {PLANS} p WHERE p.key = '{SEED['key']}'"
    )


def upgrade() -> None:
    _swap("agencies", "valid_status", "status IN ('active', 'suspended', 'closing', 'closed')")
    op.add_column(
        "oauth_transactions", sa.Column("terms_version", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "oauth_transactions", sa.Column("privacy_version", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "audit_events",
        sa.Column(
            "actor_kind", sa.String(length=20), server_default=sa.text("'user'"), nullable=False
        ),
    )
    op.alter_column("audit_events", "actor_user_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("audit_events", "agency_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(op.f("ck_audit_events_actor"), "audit_events", ACTOR_CHECK)
    op.create_check_constraint(op.f("ck_audit_events_scope"), "audit_events", SCOPE_CHECK)
    _swap("audit_events", "valid_action", _listed("action", PREVIOUS_ACTIONS, NEW_ACTIONS))
    _swap(
        "audit_events",
        "valid_resource",
        _listed("resource_type", PREVIOUS_RESOURCES, NEW_RESOURCES),
    )
    _plans()
    _assignments()
    _closures()
    _agreements()
    _seed()
    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, "agencies", "oauth_transactions", "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{action}'" for action in NEW_ACTIONS)
    resources = ", ".join(f"'{resource}'" for resource in NEW_RESOURCES)
    stored = (
        f"EXISTS (SELECT 1 FROM {PLANS} WHERE reason <> 'seed')",
        f"EXISTS (SELECT 1 FROM {ASSIGNMENTS} WHERE assigned_by <> 'default')",
        f"EXISTS (SELECT 1 FROM {CLOSURES})",
        f"EXISTS (SELECT 1 FROM {AGREEMENTS})",
        "EXISTS (SELECT 1 FROM agencies WHERE status IN ('closing', 'closed'))",
        "EXISTS (SELECT 1 FROM oauth_transactions "
        "WHERE terms_version IS NOT NULL OR privacy_version IS NOT NULL)",
        "EXISTS (SELECT 1 FROM audit_events WHERE actor_kind <> 'user' OR agency_id IS NULL "
        f"OR action IN ({actions}) OR resource_type IN ({resources}))",
    )
    populated = connection.execute(sa.text("SELECT " + " OR ".join(stored))).scalar_one()
    if populated:
        raise RuntimeError(
            "Refuse to remove stored plan, closure or agreement state; use a forward fix."
        )
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    for table in TABLES:
        op.drop_table(table)
    _swap("audit_events", "valid_resource", f"resource_type IN ({PREVIOUS_RESOURCES})")
    _swap("audit_events", "valid_action", f"action IN ({PREVIOUS_ACTIONS})")
    op.drop_constraint(op.f("ck_audit_events_scope"), "audit_events", type_="check")
    op.drop_constraint(op.f("ck_audit_events_actor"), "audit_events", type_="check")
    op.alter_column("audit_events", "agency_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("audit_events", "actor_user_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("audit_events", "actor_kind")
    op.drop_column("oauth_transactions", "privacy_version")
    op.drop_column("oauth_transactions", "terms_version")
    _swap("agencies", "valid_status", "status IN ('active', 'suspended')")
