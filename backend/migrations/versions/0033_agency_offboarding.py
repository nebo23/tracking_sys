"""Agency offboarding: export, purge record and the guarded purge function

Revision ID: 0033_agency_offboarding
Revises: 0032_report_delivery
Created: 2026-11-28

Specification 017-B (D-098, decisions D5, D7, D8, D9 and D12;
specs/017-saas-lifecycle/design-017b.md section 2). Adds agency_exports (one offboarding export
of an agency: pending while it is built, ready, failed or revoked; at most one open per
agency), agency_export_parts (the sealed parts of a ready export's ZIP, at most 8 MiB each)
and agency_purges (one record per closed agency: the copied closure times, the export summary,
the offboarding, teardown and purge times, the state and the deleted row counts), and the
function purge_agency_batch(agency uuid, budget integer).

Existing tables: agencies gains purged_at (only for a closed agency); a connection may be
disconnected with reason agency_closed and a report export revoked with reason agency_closed;
audit_events accepts the two new actions and the new resource.

The function is SECURITY DEFINER, owned by the migration role and executable by
tracking_lifecycle only. It refuses an agency unless it is closed with a completed offboarding
and settled teardowns, and deletes at most budget rows per call from every table that carries
agency_id or client_id, children first, except agency_plan_assignments and agency_purges.
tracking_app may read and insert the new tables, update only the state, outcome and download
columns of an export and the state, offboarding end and export summary of a purge record, and
delete export parts. tracking_lifecycle may read the state of a purge record and the expiry of
an export, and delete export parts. The downgrade refuses every stored row: an export, a part,
a purge record, a purged agency, a connection or report export with the reason agency_closed,
or a new audit value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0033_agency_offboarding"
down_revision: str | Sequence[str] | None = "0032_report_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPORTS = "agency_exports"
PARTS = "agency_export_parts"
PURGES = "agency_purges"
TABLES = (PARTS, EXPORTS, PURGES)  # children first
FUNCTION = "purge_agency_batch(uuid, integer)"
MAX_PARTS = 64
PART_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 512 * 1024 * 1024
MAX_EXPORT_ROWS = 2_000_000
MAX_BUDGET = 10_000
EXPORT_STATE = (
    "(status = 'pending' AND error_code IS NULL AND ready_at IS NULL AND revoked_at IS NULL "
    "AND part_count IS NULL AND byte_size IS NULL AND row_count IS NULL AND row_counts IS NULL "
    "AND manifest_sha256 IS NULL) "
    "OR (status = 'ready' AND error_code IS NULL AND ready_at IS NOT NULL AND revoked_at IS NULL "
    "AND part_count IS NOT NULL AND byte_size IS NOT NULL AND row_count IS NOT NULL "
    "AND row_counts IS NOT NULL AND manifest_sha256 IS NOT NULL) "
    "OR (status = 'failed' AND error_code IS NOT NULL AND ready_at IS NULL AND revoked_at IS NULL "
    "AND part_count IS NULL) "
    "OR (status = 'revoked' AND error_code IS NULL AND revoked_at IS NOT NULL)"
)
PURGE_PROGRESS = (
    "(state = 'offboarding' AND offboarding_completed_at IS NULL AND teardown_settled_at IS NULL "
    "AND purge_started_at IS NULL AND purge_completed_at IS NULL) "
    "OR (state = 'waiting' AND offboarding_completed_at IS NOT NULL "
    "AND teardown_settled_at IS NULL AND purge_started_at IS NULL AND purge_completed_at IS NULL) "
    "OR (state = 'purging' AND offboarding_completed_at IS NOT NULL "
    "AND teardown_settled_at IS NOT NULL AND purge_started_at IS NOT NULL "
    "AND purge_completed_at IS NULL) "
    "OR (state = 'purged' AND offboarding_completed_at IS NOT NULL "
    "AND teardown_settled_at IS NOT NULL AND purge_started_at IS NOT NULL "
    "AND purge_completed_at IS NOT NULL)"
)
NEW_ACTIONS = ("agency.export_requested", "agency.export_revoked")
NEW_RESOURCES = ("agency_export",)
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
    "'plan.created', 'plan.default_set', 'report_export.created', 'report_export.revoked', "
    "'report_schedule.created', 'report_schedule.updated', 'report_schedule.deleted', "
    "'branding.updated'"
)
PREVIOUS_RESOURCES = (
    "'agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule', 'whatsapp_number', 'identity_subject', 'revenue_issue', "
    "'revenue_association', 'attribution_model', 'plan', 'plan_assignment', 'agency_closure', "
    "'report_export', 'report_schedule', 'agency_branding'"
)
PREVIOUS_REASONS = (
    "'credential_expired', 'provider_revoked', 'user_requested', 'deauthorized', "
    "'deletion_requested', 'authorization_lost', 'operator_purged'"
)
PREVIOUS_REVOCATIONS = (
    "'manual', 'erasure', 'disconnection', 'connection_purged', 'client_archived'"
)

# The purge order (design-017b.md section 1.2): every table that carries agency_id or
# client_id, children first, with the predicate that reaches the agency's rows through an
# index. v_clients holds the agency's client IDs; p_agency is the agency.
CLIENTS = "client_id = ANY (v_clients)"
AGENCY = "agency_id = p_agency"


def _via(column: str, parent: str, scope: str) -> str:
    return f"{column} IN (SELECT id FROM public.{parent} WHERE {scope})"


PURGE = (
    (PARTS, _via("export_id", EXPORTS, AGENCY)),
    (EXPORTS, AGENCY),
    ("report_export_contents", _via("export_id", "report_exports", AGENCY)),
    ("report_exports", AGENCY),
    ("report_schedule_recipients", AGENCY),
    ("report_schedules", AGENCY),
    ("agency_branding", AGENCY),
    ("agency_closures", AGENCY),
    ("attribution_credit_changes", CLIENTS),
    ("attribution_allocations", _via("run_id", "attribution_runs", CLIENTS)),
    ("attribution_runs", CLIENTS),
    ("attribution_conversions", CLIENTS),
    ("attribution_model_versions", CLIENTS),
    ("attribution_consumer_state", CLIENTS),
    ("revenue_identity_bindings", CLIENTS),
    ("ledger_reconciliation_actions", CLIENTS),
    ("ledger_transactions", CLIENTS),
    ("ledger_movements", CLIENTS),
    ("ledger_receipts", CLIENTS),
    ("ledger_projection_state", CLIENTS),
    ("identity_erasure_holds", CLIENTS),
    ("identity_changes", CLIENTS),
    ("identity_feed_state", CLIENTS),
    ("identity_handoffs", CLIENTS),
    ("identity_links", _via("collection_subject_id", "collection_subjects", CLIENTS)),
    ("identity_assertion_receipts", CLIENTS),
    ("identity_assertions", CLIENTS),
    ("identity_keys", CLIENTS),
    ("identity_merges", CLIENTS),
    ("identity_subjects", CLIENTS),
    ("identity_key_secrets", CLIENTS),
    ("whatsapp_messages", CLIENTS),
    ("whatsapp_numbers", AGENCY),
    ("crm_deals", CLIENTS),
    ("crm_stage_rules", CLIENTS),
    ("booking_events", _via("source_id", "integration_sources", AGENCY)),
    ("bookings", CLIENTS),
    ("integration_deliveries", _via("source_id", "integration_sources", AGENCY)),
    ("integration_source_secrets", _via("source_id", "integration_sources", AGENCY)),
    ("integration_sources", AGENCY),
    ("revenue_imports", CLIENTS),
    ("payment_callback_diagnostics", CLIENTS),
    ("payment_source_secrets", _via("source_id", "payment_sources", AGENCY)),
    ("payment_sources", AGENCY),
    ("revenue_evidence", CLIENTS),
    ("conversion_acknowledgements", _via("delivery_id", "conversion_deliveries", AGENCY)),
    ("conversion_deliveries", AGENCY),
    ("conversion_destinations", AGENCY),
    ("ad_spend_facts", _via("connection_id", "connector_connections", AGENCY)),
    ("ad_objects", _via("connection_id", "connector_connections", AGENCY)),
    ("ad_accounts", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_records", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_usage_records", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_checkpoints", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_sync_runs", AGENCY),
    ("connector_token_secrets", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_oauth_transactions", CLIENTS),
    ("connector_connections", AGENCY),
    ("deletion_tombstones", CLIENTS),
    ("deletion_requests", CLIENTS),
    ("event_diagnostics", CLIENTS),
    ("collected_events", CLIENTS),
    ("managed_links", CLIENTS),
    ("link_domains", AGENCY),
    ("link_destination_origins", CLIENTS),
    ("link_utm_templates", CLIENTS),
    ("link_content_references", CLIENTS),
    ("link_campaigns", CLIENTS),
    ("consent_records", _via("subject_id", "collection_subjects", CLIENTS)),
    ("collection_subjects", CLIENTS),
    ("collection_forms", CLIENTS),
    ("ingestion_source_secrets", _via("source_id", "ingestion_sources", AGENCY)),
    ("ingestion_sources", AGENCY),
    ("audit_events", AGENCY),
    ("service_client_grants", AGENCY),
    ("invitation_client_grants", AGENCY),
    ("service_credentials", AGENCY),
    ("agency_invitations", AGENCY),
    ("client_grants", AGENCY),
    ("agency_memberships", AGENCY),
    ("client_workspaces", AGENCY),
)
# Tables that reference themselves: their rows are deleted leaves first.
SELF_REFERENCES = {"identity_merges": "reverses_id", "identity_subjects": "merged_into_id"}

RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {EXPORTS}, {PARTS}, {PURGES} TO tracking_app",
    "GRANT UPDATE (status, error_code, ready_at, revoked_at, part_count, byte_size, row_count, "
    f"row_counts, manifest_sha256, download_count, last_downloaded_at) ON {EXPORTS} "
    "TO tracking_app",
    f"GRANT DELETE ON {PARTS} TO tracking_app",
    f"GRANT UPDATE (state, offboarding_completed_at, export_summary) ON {PURGES} TO tracking_app",
)
LIFECYCLE_GRANTS = (
    f"GRANT SELECT (agency_id, state) ON {PURGES} TO tracking_lifecycle",
    f"GRANT SELECT (id, expires_at) ON {EXPORTS} TO tracking_lifecycle",
    f"GRANT SELECT (export_id) ON {PARTS} TO tracking_lifecycle",
    f"GRANT DELETE ON {PARTS} TO tracking_lifecycle",
    f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO tracking_lifecycle",
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


def _exports() -> None:
    op.create_table(
        EXPORTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        _time("requested_at", nullable=False, default=True),
        _time("ready_at"),
        _time("revoked_at"),
        _time("expires_at", nullable=False),
        sa.Column("part_count", sa.SmallInteger(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("row_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("download_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _time("last_downloaded_at"),
        _check(EXPORTS, "valid_status", "status IN ('pending', 'ready', 'failed', 'revoked')"),
        _check(
            EXPORTS,
            "valid_error",
            "error_code IS NULL OR error_code IN "
            "('export_too_large', 'closure_completed', 'build_failed')",
        ),
        _check(EXPORTS, "state", EXPORT_STATE),
        _check(
            EXPORTS,
            "lifetime",
            "expires_at > requested_at AND expires_at <= requested_at + interval '7 days'",
        ),
        _check(
            EXPORTS,
            "times",
            "(ready_at IS NULL OR ready_at >= requested_at) "
            "AND (revoked_at IS NULL OR revoked_at >= requested_at)",
        ),
        _check(
            EXPORTS,
            "valid_part_count",
            f"part_count IS NULL OR part_count BETWEEN 1 AND {MAX_PARTS}",
        ),
        _check(
            EXPORTS,
            "valid_byte_size",
            f"byte_size IS NULL OR byte_size BETWEEN 1 AND {MAX_EXPORT_BYTES}",
        ),
        _check(
            EXPORTS,
            "valid_row_count",
            f"row_count IS NULL OR row_count BETWEEN 0 AND {MAX_EXPORT_ROWS}",
        ),
        _check(
            EXPORTS,
            "row_counts_object",
            "row_counts IS NULL OR jsonb_typeof(row_counts) = 'object'",
        ),
        _check(
            EXPORTS,
            "valid_manifest",
            "manifest_sha256 IS NULL OR manifest_sha256 ~ '^[0-9a-f]{64}$'",
        ),
        _check(
            EXPORTS,
            "downloads",
            "download_count >= 0 AND (download_count = 0 OR last_downloaded_at IS NOT NULL)",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f(f"fk_{EXPORTS}_agency_id_agencies")
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "requested_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=f"fk_{EXPORTS}_requested_by_agency_memberships",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{EXPORTS}")),
        sa.UniqueConstraint("agency_id", "id", name=f"uq_{EXPORTS}_scope"),
    )
    op.create_index(
        f"uq_{EXPORTS}_open",
        EXPORTS,
        ["agency_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'ready')"),
    )
    op.create_index(f"ix_{EXPORTS}_agency", EXPORTS, ["agency_id", "requested_at"])
    op.create_index(
        f"ix_{EXPORTS}_pending",
        EXPORTS,
        ["requested_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(f"ix_{EXPORTS}_expires_at", EXPORTS, ["expires_at"])


def _parts() -> None:
    op.create_table(
        PARTS,
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("part", sa.SmallInteger(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=False),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("alg", sa.String(length=32), nullable=False),
        sa.Column("aad_version", sa.SmallInteger(), nullable=False),
        _time("created_at", nullable=False, default=True),
        _check(PARTS, "valid_part", f"part BETWEEN 1 AND {MAX_PARTS}"),
        _check(PARTS, "valid_kek_id", "kek_id ~ '^[a-z0-9][a-z0-9-]{0,31}$'"),
        _check(
            PARTS,
            "key_material",
            "octet_length(wrap_nonce) = 12 AND octet_length(nonce) = 12 "
            "AND octet_length(wrapped_dek) = 48",
        ),
        _check(
            PARTS,
            "ciphertext_size",
            f"octet_length(ciphertext) BETWEEN 17 AND {PART_BYTES + 16}",
        ),
        _check(PARTS, "valid_format", "alg = 'A256GCM-ENV-v1' AND aad_version = 1"),
        sa.ForeignKeyConstraint(
            ["agency_id", "export_id"],
            [f"{EXPORTS}.agency_id", f"{EXPORTS}.id"],
            name=f"fk_{PARTS}_{EXPORTS}",
        ),
        sa.PrimaryKeyConstraint("export_id", "part", name=op.f(f"pk_{PARTS}")),
    )


def _purges() -> None:
    op.create_table(
        PURGES,
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        _time("closure_requested_at", nullable=False),
        _time("closes_at", nullable=False),
        _time("closure_completed_at", nullable=False),
        sa.Column(
            "export_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _time("offboarding_started_at", nullable=False, default=True),
        _time("offboarding_completed_at"),
        _time("teardown_settled_at"),
        _time("purge_started_at"),
        _time("purge_completed_at"),
        sa.Column(
            "deleted_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _check(PURGES, "valid_state", "state IN ('offboarding', 'waiting', 'purging', 'purged')"),
        _check(
            PURGES,
            "closure_times",
            "closes_at > closure_requested_at AND closure_completed_at >= closes_at",
        ),
        _check(PURGES, "progress", PURGE_PROGRESS),
        _check(PURGES, "summary_object", "jsonb_typeof(export_summary) = 'object'"),
        _check(PURGES, "counts_object", "jsonb_typeof(deleted_counts) = 'object'"),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name=op.f(f"fk_{PURGES}_agency_id_agencies")
        ),
        sa.PrimaryKeyConstraint("agency_id", name=op.f(f"pk_{PURGES}")),
    )
    op.create_index(
        f"ix_{PURGES}_open", PURGES, ["state"], postgresql_where=sa.text("state <> 'purged'")
    )


def _counted(table: str, indent: str) -> str:
    lines = (
        "GET DIAGNOSTICS v_count = ROW_COUNT;",
        "IF v_count > 0 THEN",
        f"    v_deleted := v_deleted || jsonb_build_object('{table}', "
        f"v_count + coalesce((v_deleted ->> '{table}')::integer, 0));",
        "    v_left := v_left - v_count;",
        "END IF;",
    )
    return "".join(f"{indent}{line}\n" for line in lines)


def _step(table: str, path: str) -> str:
    column = SELF_REFERENCES.get(table)
    if column is None:
        return (
            f"        DELETE FROM public.{table} WHERE ctid = ANY (ARRAY(\n"
            f"            SELECT ctid FROM public.{table} WHERE {path} LIMIT v_left));\n"
            + _counted(table, " " * 8)
        )
    # Leaves first: a row is deleted only when no remaining row of the table references it,
    # so a batch never breaks the self-reference. Rows that form no leaf (a cycle, which the
    # merge rules exclude) are deleted together in one statement.
    leaf = (
        f"NOT EXISTS (SELECT 1 FROM public.{table} r WHERE r.agency_id = t.agency_id "
        f"AND r.client_id = t.client_id AND r.{column} = t.id)"
    )
    return (
        "        LOOP\n"
        f"            DELETE FROM public.{table} WHERE ctid = ANY (ARRAY(\n"
        f"                SELECT t.ctid FROM public.{table} t WHERE t.{path} AND {leaf}\n"
        "                LIMIT v_left));\n"
        + _counted(table, " " * 12)
        + "            EXIT WHEN v_count = 0 OR v_left <= 0;\n"
        "        END LOOP;\n"
        "        IF v_left > 0 THEN\n"
        f"            DELETE FROM public.{table} WHERE {path};\n"
        + _counted(table, " " * 12)
        + "        END IF;\n"
    )


def _function() -> str:
    # A spent budget ends the call after any step, the last one included: a step that used
    # the whole budget may have left rows behind, so only a walk with budget to spare after
    # every step proves that each step emptied its table.
    steps = []
    for table, path in PURGE:
        steps.append(_step(table, path))
        steps.append("        IF v_left <= 0 THEN EXIT steps; END IF;\n")
    return f"""
CREATE FUNCTION public.purge_agency_batch(p_agency uuid, p_budget integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_status text;
    v_purge public.{PURGES}%ROWTYPE;
    v_clients uuid[];
    v_left integer := p_budget;
    v_count integer;
    v_done boolean := false;
    v_deleted jsonb := '{{}}'::jsonb;
BEGIN
    IF p_budget IS NULL OR p_budget < 1 OR p_budget > {MAX_BUDGET} THEN
        RAISE EXCEPTION 'invalid_budget' USING ERRCODE = 'P0001';
    END IF;
    SELECT status INTO v_status FROM public.agencies WHERE id = p_agency FOR UPDATE;
    IF v_status IS DISTINCT FROM 'closed' THEN
        RAISE EXCEPTION 'agency_not_closed' USING ERRCODE = 'P0001';
    END IF;
    SELECT * INTO v_purge FROM public.{PURGES} WHERE agency_id = p_agency FOR UPDATE;
    IF NOT FOUND OR v_purge.offboarding_completed_at IS NULL OR EXISTS (
            SELECT 1 FROM public.connector_connections
            WHERE agency_id = p_agency AND status IN ('active', 'reconnect_required')) THEN
        RAISE EXCEPTION 'offboarding_not_completed' USING ERRCODE = 'P0001';
    END IF;
    IF v_purge.state = 'purged' THEN
        RETURN jsonb_build_object('state', 'purged', 'deleted', '{{}}'::jsonb);
    END IF;
    IF v_purge.state = 'waiting' THEN
        IF EXISTS (
                SELECT 1 FROM public.connector_connections
                WHERE agency_id = p_agency AND status = 'disconnecting'
                  AND purge_due_at > now()) THEN
            RAISE EXCEPTION 'teardown_pending' USING ERRCODE = 'P0001';
        END IF;
        UPDATE public.{PURGES} SET state = 'purging', teardown_settled_at = now(),
            purge_started_at = now() WHERE agency_id = p_agency;
    END IF;
    v_clients := ARRAY(SELECT id FROM public.client_workspaces WHERE agency_id = p_agency);
    <<steps>>
    BEGIN
{"".join(steps)}        v_done := true;
    END steps;
    UPDATE public.{PURGES} SET deleted_counts = (
        SELECT coalesce(jsonb_object_agg(item.key, item.total), '{{}}'::jsonb)
        FROM (
            SELECT entry.key, sum(entry.value::bigint) AS total
            FROM (
                SELECT key, value FROM jsonb_each_text(deleted_counts)
                UNION ALL
                SELECT key, value FROM jsonb_each_text(v_deleted)
            ) AS entry
            GROUP BY entry.key
        ) AS item
    ) WHERE agency_id = p_agency;
    IF NOT v_done THEN
        RETURN jsonb_build_object('state', 'purging', 'deleted', v_deleted);
    END IF;
    UPDATE public.agencies SET name = 'Closed agency ' || p_agency::text, purged_at = now(),
        updated_at = now() WHERE id = p_agency;
    UPDATE public.{PURGES} SET state = 'purged', purge_completed_at = now()
        WHERE agency_id = p_agency;
    RETURN jsonb_build_object('state', 'purged', 'deleted', v_deleted);
END;
$$
"""


def upgrade() -> None:
    op.add_column("agencies", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_agencies_purged"), "agencies", "purged_at IS NULL OR status = 'closed'"
    )
    _swap(
        "connector_connections",
        "valid_reason",
        f"status_reason IS NULL OR status_reason IN ({PREVIOUS_REASONS}, 'agency_closed')",
    )
    _swap(
        "report_exports",
        "valid_revoked_reason",
        f"revoked_reason IS NULL OR revoked_reason IN ({PREVIOUS_REVOCATIONS}, 'agency_closed')",
    )
    _swap("audit_events", "valid_action", _listed("action", PREVIOUS_ACTIONS, NEW_ACTIONS))
    _swap(
        "audit_events",
        "valid_resource",
        _listed("resource_type", PREVIOUS_RESOURCES, NEW_RESOURCES),
    )
    _exports()
    _parts()
    _purges()
    op.execute(_function())
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, "agencies", "connector_connections", "report_exports", "audit_events"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{action}'" for action in NEW_ACTIONS)
    resources = ", ".join(f"'{resource}'" for resource in NEW_RESOURCES)
    stored = (
        *(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES),
        "EXISTS (SELECT 1 FROM agencies WHERE purged_at IS NOT NULL)",
        "EXISTS (SELECT 1 FROM connector_connections WHERE status_reason = 'agency_closed')",
        "EXISTS (SELECT 1 FROM report_exports WHERE revoked_reason = 'agency_closed')",
        f"EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}) "
        f"OR resource_type IN ({resources}))",
    )
    populated = connection.execute(sa.text("SELECT " + " OR ".join(stored))).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove stored offboarding state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    op.execute(f"DROP FUNCTION {FUNCTION}")
    for table in TABLES:
        op.drop_table(table)
    _swap("audit_events", "valid_resource", f"resource_type IN ({PREVIOUS_RESOURCES})")
    _swap("audit_events", "valid_action", f"action IN ({PREVIOUS_ACTIONS})")
    _swap(
        "report_exports",
        "valid_revoked_reason",
        f"revoked_reason IS NULL OR revoked_reason IN ({PREVIOUS_REVOCATIONS})",
    )
    _swap(
        "connector_connections",
        "valid_reason",
        f"status_reason IS NULL OR status_reason IN ({PREVIOUS_REASONS})",
    )
    op.drop_constraint(op.f("ck_agencies_purged"), "agencies", type_="check")
    op.drop_column("agencies", "purged_at")
