"""Retained exports, report schedules and agency branding

Revision ID: 0032_report_delivery
Revises: 0031_saas_plans
Created: 2026-11-27

Specification 016-C (D-095, decision D12; specs/016-analytics-reporting/design-016c.md
section 2). Adds report_exports (one retained CSV export of one client: pending while it is
built, ready, revoked or discarded, at most 7 days), report_export_contents (the sealed CSV of a
ready export, deleted at revocation and expiry), report_schedules (one daily, weekly or monthly
report of a client run with its owner's permissions), report_schedule_recipients (member
recipients) and agency_branding (display name, accent color and optional PNG logo). Every
reference is scoped by agency and, where one applies, client.

Existing tables: mail_outbox accepts the purpose report_ready; audit_events accepts the six new
actions and the three new resources.

tracking_app may read and insert the new tables; on report_exports it updates only the state,
store and download columns and never deletes a row; it deletes export contents (revocation),
schedules and recipients, and updates schedules and the branding profile. tracking_lifecycle may
only read the expiry columns and delete exports and their contents. The downgrade refuses every
stored row: an export, a content, a schedule, a recipient, a branding profile, a report_ready
message or a new audit value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0032_report_delivery"
down_revision: str | Sequence[str] | None = "0031_saas_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPORTS = "report_exports"
CONTENTS = "report_export_contents"
SCHEDULES = "report_schedules"
RECIPIENTS = "report_schedule_recipients"
BRANDING = "agency_branding"
TABLES = (CONTENTS, EXPORTS, RECIPIENTS, SCHEDULES, BRANDING)  # children first
FAMILIES = "('social', 'spend', 'revenue', 'attribution', 'roas', 'funnel')"
CONNECTION_FAMILIES = "('social', 'spend', 'roas')"
REVOCATION_REASONS = (
    "('manual', 'erasure', 'disconnection', 'connection_purged', 'client_archived')"
)
PAUSE_REASONS = "('manual', 'owner_access_lost', 'repeated_failures')"
RUN_ERRORS = (
    "('report_changed', 'report_too_large', 'source_unavailable', 'source_not_ready', "
    "'not_configured', 'export_limit_reached', 'export_refused', 'build_failed')"
)
MAX_EXPORT_BYTES = 2 * 1024 * 1024
MAX_LOGO_BYTES = 256 * 1024
NAME_RULE = "length(btrim(name)) > 0 AND name !~ '[[:cntrl:]]'"
EXPORT_STATE = (
    "(status = 'pending' AND stored_at IS NULL AND revoked_at IS NULL AND revoked_reason IS NULL "
    "AND row_count IS NULL AND byte_size IS NULL AND report_revision IS NULL) "
    "OR (status = 'ready' AND stored_at IS NOT NULL AND revoked_at IS NULL "
    "AND revoked_reason IS NULL AND row_count IS NOT NULL AND byte_size IS NOT NULL "
    "AND report_revision IS NOT NULL) "
    "OR (status = 'revoked' AND stored_at IS NOT NULL AND revoked_at IS NOT NULL "
    "AND revoked_reason IS NOT NULL) "
    "OR (status = 'discarded' AND stored_at IS NULL AND revoked_at IS NOT NULL)"
)
NEW_ACTIONS = (
    "report_export.created",
    "report_export.revoked",
    "report_schedule.created",
    "report_schedule.updated",
    "report_schedule.deleted",
    "branding.updated",
)
NEW_RESOURCES = ("report_export", "report_schedule", "agency_branding")
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
    "'attribution.model_retired', 'agency.plan_assigned', 'agency.suspended', "
    "'agency.reactivated', 'agency.closure_requested', 'agency.closure_cancelled', "
    "'plan.created', 'plan.default_set'"
)
PREVIOUS_RESOURCES = (
    "'agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule', 'whatsapp_number', 'identity_subject', 'revenue_issue', "
    "'revenue_association', 'attribution_model', 'plan', 'plan_assignment', 'agency_closure'"
)
PREVIOUS_PURPOSES = "'verify', 'reset', 'invitation'"

RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {EXPORTS}, {CONTENTS}, {SCHEDULES}, {RECIPIENTS}, {BRANDING} "
    "TO tracking_app",
    f"GRANT UPDATE (status, revoked_at, revoked_reason, stored_at, row_count, byte_size, "
    f"report_revision, download_count, last_downloaded_at) ON {EXPORTS} TO tracking_app",
    f"GRANT DELETE ON {CONTENTS} TO tracking_app",
    f"GRANT UPDATE (name, parameters, sale_values, compare, cadence, weekday, hour, time_zone, "
    "status, pause_reason, owner_membership_id, next_run_at, last_run_at, last_outcome, "
    "last_error_code, last_notified, last_skipped, consecutive_failures, updated_at) "
    f"ON {SCHEDULES} TO tracking_app",
    f"GRANT DELETE ON {SCHEDULES}, {RECIPIENTS} TO tracking_app",
    f"GRANT UPDATE (display_name, accent_color, logo, logo_width, logo_height, updated_at, "
    f"updated_by_membership_id) ON {BRANDING} TO tracking_app",
)
LIFECYCLE_GRANTS = (
    f"GRANT SELECT (id, status, created_at, expires_at) ON {EXPORTS} TO tracking_lifecycle",
    f"GRANT DELETE ON {EXPORTS} TO tracking_lifecycle",
    f"GRANT SELECT (export_id) ON {CONTENTS} TO tracking_lifecycle",
    f"GRANT DELETE ON {CONTENTS} TO tracking_lifecycle",
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _swap(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _listed(column: str, previous: str, new: Sequence[str]) -> str:
    extra = "".join(f", '{value}'" for value in new)
    return f"{column} IN ({previous}{extra})"


def _time(name: str, *, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def _membership_fk(table: str, column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", column],
        ["agency_memberships.agency_id", "agency_memberships.id"],
        name=f"fk_{table}_{name}_agency_memberships",
    )


def _client_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id"],
        ["client_workspaces.agency_id", "client_workspaces.id"],
        name=f"fk_{table}_client_workspaces",
    )


def _schedules() -> None:
    op.create_table(
        SCHEDULES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("family", sa.String(length=16), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sale_values", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("compare", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cadence", sa.String(length=8), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=True),
        sa.Column("hour", sa.SmallInteger(), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="active", nullable=False),
        sa.Column("pause_reason", sa.String(length=24), nullable=True),
        sa.Column("owner_membership_id", sa.Uuid(), nullable=False),
        _time("next_run_at"),
        _time("last_run_at"),
        sa.Column("last_outcome", sa.String(length=16), nullable=True),
        sa.Column("last_error_code", sa.String(length=32), nullable=True),
        sa.Column("last_notified", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_skipped", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "consecutive_failures", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        _time("created_at", nullable=False, default=True),
        _time("updated_at", nullable=False, default=True),
        _check(SCHEDULES, "valid_name", NAME_RULE),
        _check(SCHEDULES, "valid_family", f"family IN {FAMILIES}"),
        _check(SCHEDULES, "parameters_object", "jsonb_typeof(parameters) = 'object'"),
        _check(
            SCHEDULES,
            "sale_values_family",
            "NOT sale_values OR family IN ('attribution', 'funnel')",
        ),
        _check(SCHEDULES, "valid_cadence", "cadence IN ('daily', 'weekly', 'monthly')"),
        _check(
            SCHEDULES,
            "valid_weekday",
            "(cadence = 'weekly') = (weekday IS NOT NULL) "
            "AND (weekday IS NULL OR weekday BETWEEN 1 AND 7)",
        ),
        _check(SCHEDULES, "valid_hour", "hour BETWEEN 0 AND 23"),
        _check(SCHEDULES, "valid_time_zone", "length(time_zone) BETWEEN 1 AND 64"),
        _check(SCHEDULES, "valid_status", "status IN ('active', 'paused')"),
        _check(
            SCHEDULES,
            "valid_pause",
            "(status = 'paused') = (pause_reason IS NOT NULL) "
            f"AND (pause_reason IS NULL OR pause_reason IN {PAUSE_REASONS})",
        ),
        _check(SCHEDULES, "active_slot", "status = 'paused' OR next_run_at IS NOT NULL"),
        _check(
            SCHEDULES,
            "valid_outcome",
            "last_outcome IS NULL OR last_outcome IN ('built', 'failed')",
        ),
        _check(
            SCHEDULES,
            "valid_error",
            "(last_outcome = 'failed') = (last_error_code IS NOT NULL) "
            f"AND (last_error_code IS NULL OR last_error_code IN {RUN_ERRORS})",
        ),
        _check(SCHEDULES, "valid_counts", "last_notified >= 0 AND last_skipped >= 0"),
        _check(SCHEDULES, "valid_failures", "consecutive_failures BETWEEN 0 AND 3"),
        _client_fk(SCHEDULES),
        _membership_fk(SCHEDULES, "owner_membership_id", "owner"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{SCHEDULES}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name=f"uq_{SCHEDULES}_scope"),
    )
    op.create_index(
        f"ix_{SCHEDULES}_due",
        SCHEDULES,
        ["next_run_at"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(f"ix_{SCHEDULES}_client", SCHEDULES, ["agency_id", "client_id", "created_at"])


def _recipients() -> None:
    op.create_table(
        RECIPIENTS,
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        _time("created_at", nullable=False, default=True),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "schedule_id"],
            [f"{SCHEDULES}.agency_id", f"{SCHEDULES}.client_id", f"{SCHEDULES}.id"],
            name=f"fk_{RECIPIENTS}_{SCHEDULES}",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=f"fk_{RECIPIENTS}_agency_memberships",
        ),
        sa.PrimaryKeyConstraint("schedule_id", "membership_id", name=op.f(f"pk_{RECIPIENTS}")),
    )
    op.create_index(f"ix_{RECIPIENTS}_membership", RECIPIENTS, ["agency_id", "membership_id"])


def _exports() -> None:
    op.create_table(
        EXPORTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("family", sa.String(length=16), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("includes_financials", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        _time("revoked_at"),
        sa.Column("revoked_reason", sa.String(length=24), nullable=True),
        _time("created_at", nullable=False, default=True),
        _time("stored_at"),
        _time("expires_at", nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("report_revision", sa.String(length=64), nullable=True),
        sa.Column("download_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _time("last_downloaded_at"),
        _check(EXPORTS, "valid_family", f"family IN {FAMILIES}"),
        _check(EXPORTS, "parameters_object", "jsonb_typeof(parameters) = 'object'"),
        _check(
            EXPORTS,
            "connection_family",
            f"(family IN {CONNECTION_FAMILIES}) = (connection_id IS NOT NULL)",
        ),
        _check(
            EXPORTS,
            "valid_period",
            "period_end > period_start AND period_end - period_start <= 31",
        ),
        _check(EXPORTS, "valid_source", "source IN ('manual', 'schedule')"),
        _check(EXPORTS, "schedule_source", "source = 'schedule' OR schedule_id IS NULL"),
        _check(EXPORTS, "valid_status", "status IN ('pending', 'ready', 'revoked', 'discarded')"),
        _check(
            EXPORTS,
            "valid_revoked_reason",
            f"revoked_reason IS NULL OR revoked_reason IN {REVOCATION_REASONS}",
        ),
        _check(EXPORTS, "state", EXPORT_STATE),
        _check(
            EXPORTS,
            "lifetime",
            "expires_at > created_at AND expires_at <= created_at + interval '7 days'",
        ),
        _check(EXPORTS, "valid_row_count", "row_count IS NULL OR row_count BETWEEN 0 AND 5000"),
        _check(
            EXPORTS,
            "valid_byte_size",
            f"byte_size IS NULL OR byte_size BETWEEN 1 AND {MAX_EXPORT_BYTES}",
        ),
        _check(
            EXPORTS,
            "valid_revision",
            "report_revision IS NULL OR report_revision ~ '^[0-9a-f]{64}$'",
        ),
        _check(
            EXPORTS,
            "downloads",
            "download_count >= 0 AND (download_count = 0 OR last_downloaded_at IS NOT NULL)",
        ),
        _client_fk(EXPORTS),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "connection_id"],
            [
                "connector_connections.agency_id",
                "connector_connections.client_id",
                "connector_connections.id",
            ],
            name=f"fk_{EXPORTS}_connector_connections",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            [f"{SCHEDULES}.id"],
            name=op.f(f"fk_{EXPORTS}_schedule_id_{SCHEDULES}"),
            ondelete="SET NULL",
        ),
        _membership_fk(EXPORTS, "requested_by_membership_id", "requested_by"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{EXPORTS}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name=f"uq_{EXPORTS}_scope"),
    )
    op.create_index(
        f"ix_{EXPORTS}_listing", EXPORTS, ["agency_id", "client_id", "created_at", "id"]
    )
    op.create_index(
        f"ix_{EXPORTS}_open_connection",
        EXPORTS,
        ["client_id", "connection_id"],
        postgresql_where=sa.text("status IN ('pending', 'ready')"),
    )
    op.create_index(f"ix_{EXPORTS}_expires_at", EXPORTS, ["expires_at"])
    op.create_index(
        f"ix_{EXPORTS}_schedule_id",
        EXPORTS,
        ["schedule_id"],
        postgresql_where=sa.text("schedule_id IS NOT NULL"),
    )


def _contents() -> None:
    op.create_table(
        CONTENTS,
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=False),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("alg", sa.String(length=32), nullable=False),
        sa.Column("aad_version", sa.SmallInteger(), nullable=False),
        _time("created_at", nullable=False, default=True),
        _check(CONTENTS, "valid_kek_id", "kek_id ~ '^[a-z0-9][a-z0-9-]{0,31}$'"),
        _check(
            CONTENTS,
            "key_material",
            "octet_length(wrap_nonce) = 12 AND octet_length(nonce) = 12 "
            "AND octet_length(wrapped_dek) = 48",
        ),
        _check(
            CONTENTS,
            "ciphertext_size",
            f"octet_length(ciphertext) BETWEEN 17 AND {MAX_EXPORT_BYTES + 16}",
        ),
        _check(CONTENTS, "valid_format", "alg = 'A256GCM-ENV-v1' AND aad_version = 1"),
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id", "export_id"],
            [f"{EXPORTS}.agency_id", f"{EXPORTS}.client_id", f"{EXPORTS}.id"],
            name=f"fk_{CONTENTS}_{EXPORTS}",
        ),
        sa.PrimaryKeyConstraint("export_id", name=op.f(f"pk_{CONTENTS}")),
    )


def _branding() -> None:
    op.create_table(
        BRANDING,
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("accent_color", sa.String(length=7), nullable=False),
        sa.Column("logo", sa.LargeBinary(), nullable=True),
        sa.Column("logo_width", sa.SmallInteger(), nullable=True),
        sa.Column("logo_height", sa.SmallInteger(), nullable=True),
        _time("updated_at", nullable=False, default=True),
        sa.Column("updated_by_membership_id", sa.Uuid(), nullable=False),
        _check(BRANDING, "valid_display_name", NAME_RULE.replace("name", "display_name")),
        _check(BRANDING, "valid_accent_color", "accent_color ~ '^#[0-9A-F]{6}$'"),
        _check(
            BRANDING,
            "logo_size",
            f"logo IS NULL OR octet_length(logo) BETWEEN 67 AND {MAX_LOGO_BYTES}",
        ),
        _check(
            BRANDING,
            "logo_dimensions",
            "(logo IS NULL) = (logo_width IS NULL) AND (logo IS NULL) = (logo_height IS NULL) "
            "AND (logo_width IS NULL OR logo_width BETWEEN 1 AND 1024) "
            "AND (logo_height IS NULL OR logo_height BETWEEN 1 AND 1024)",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f(f"fk_{BRANDING}_agency_id_agencies")
        ),
        _membership_fk(BRANDING, "updated_by_membership_id", "updated_by"),
        sa.PrimaryKeyConstraint("agency_id", name=op.f(f"pk_{BRANDING}")),
    )


def upgrade() -> None:
    _swap(
        "mail_outbox",
        "valid_purpose",
        f"purpose IN ({PREVIOUS_PURPOSES}, 'report_ready')",
    )
    _swap("audit_events", "valid_action", _listed("action", PREVIOUS_ACTIONS, NEW_ACTIONS))
    _swap(
        "audit_events",
        "valid_resource",
        _listed("resource_type", PREVIOUS_RESOURCES, NEW_RESOURCES),
    )
    _schedules()
    _recipients()
    _exports()
    _contents()
    _branding()
    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, "mail_outbox", "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{action}'" for action in NEW_ACTIONS)
    resources = ", ".join(f"'{resource}'" for resource in NEW_RESOURCES)
    stored = (
        *(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES),
        "EXISTS (SELECT 1 FROM mail_outbox WHERE purpose = 'report_ready')",
        f"EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}) "
        f"OR resource_type IN ({resources}))",
    )
    populated = connection.execute(sa.text("SELECT " + " OR ".join(stored))).scalar_one()
    if populated:
        raise RuntimeError(
            "Refuse to remove stored export, schedule or branding state; use a forward fix."
        )
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    for table in TABLES:
        op.drop_table(table)
    _swap("audit_events", "valid_resource", f"resource_type IN ({PREVIOUS_RESOURCES})")
    _swap("audit_events", "valid_action", f"action IN ({PREVIOUS_ACTIONS})")
    _swap("mail_outbox", "valid_purpose", f"purpose IN ({PREVIOUS_PURPOSES})")
