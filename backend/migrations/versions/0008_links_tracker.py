"""Managed links, campaign provenance, custom domains, and event link references

Revision ID: 0008_links_tracker
Revises: 0007_event_collection
Created: 2026-11-10

Specification 005 (D-033, decision packet D2/D3). Adds six client-scoped tables and the
nullable, same-client collected_events.link_id. tracking_app may insert the new rows and update
only their reviewed mutable columns: issued link provenance, slugs, hostnames, codes, and scope
keys are never updatable, and no new table can be deleted from by the runtime, so slugs and
hostnames are never recycled. An event upgrade may carry its validated link reference.
tracking_lifecycle receives nothing new: link configuration is kept for the workspace lifetime
and event link references leave with their events. The downgrade refuses populated 005 state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0008_links_tracker"
down_revision: str | Sequence[str] | None = "0007_event_collection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLIENT = ["client_workspaces.agency_id", "client_workspaces.id"]
TABLES = (
    "managed_links",
    "link_domains",
    "link_destination_origins",
    "link_utm_templates",
    "link_content_references",
    "link_campaigns",
)
FAILURE_CODES = (
    "ownership_missing",
    "routing_mismatch",
    "address_not_allowed",
    "tls_invalid",
    "challenge_expired",
    "verification_unavailable",
    "host_conflict",
)
PREVIOUS_ACTIONS = (
    "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
    "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
    "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
    "'credential.created', 'credential.revoked', 'source.created', 'source.updated', "
    "'source.secret_rotated', 'form.updated', 'deletion.requested')"
)
NEW_ACTIONS = (
    "campaign.created",
    "campaign.updated",
    "content.created",
    "content.updated",
    "template.created",
    "template.updated",
    "origin.created",
    "origin.updated",
    "domain.created",
    "domain.updated",
    "domain.challenge_issued",
    "domain.checked",
    "link.created",
    "link.updated",
)
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request')"
)
NEW_RESOURCES = (
    "campaign",
    "content_reference",
    "utm_template",
    "destination_origin",
    "domain",
    "link",
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_RESOURCES) + ")"
RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    "GRANT UPDATE (label, status, updated_at) ON link_campaigns TO tracking_app",
    "GRANT UPDATE (platform_label, status, updated_at) ON link_content_references TO tracking_app",
    "GRANT UPDATE (parameters, revision, status, updated_at) ON link_utm_templates TO tracking_app",
    "GRANT UPDATE (query_names, status, updated_at) ON link_destination_origins TO tracking_app",
    "GRANT UPDATE (status, challenge_digest, challenge_expires_at, challenge_generation, "
    "verified_at, verification_expires_at, certificate_expires_at, last_checked_at, "
    "failure_code, version, updated_at) ON link_domains TO tracking_app",
    "GRANT UPDATE (status, expires_at, updated_at) ON managed_links TO tracking_app",
    "GRANT UPDATE (link_id) ON collected_events TO tracking_app",
)


def _timestamps(*, nullable: tuple[str, ...] = ()) -> list[sa.Column]:
    columns = [
        sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
        for name in ("created_at", "updated_at")
    ]
    columns += [sa.Column(name, sa.DateTime(timezone=True), nullable=True) for name in nullable]
    return columns


def _base(table: str) -> list:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


def _keys(table: str) -> list:
    return [
        sa.ForeignKeyConstraint(
            ["agency_id", "client_id"], CLIENT, name=op.f(f"fk_{table}_agency_id_client_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name=f"uq_{table}_scope"),
    ]


def _status(table: str, values: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"status IN ({values})", name=op.f(f"ck_{table}_valid_status"))


def _scoped(column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", column],
        [f"{target}.agency_id", f"{target}.client_id", f"{target}.id"],
        name=op.f(f"fk_managed_links_agency_id_{target}"),
    )


def upgrade() -> None:
    op.create_table(
        "link_campaigns",
        *_base("link_campaigns"),
        sa.Column("public_code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "length(btrim(label)) > 0", name=op.f("ck_link_campaigns_label_not_blank")
        ),
        sa.CheckConstraint(
            "public_code ~ '^[A-Za-z0-9_.-]{1,64}$'", name=op.f("ck_link_campaigns_valid_code")
        ),
        _status("link_campaigns", "'active', 'archived'"),
        *_keys("link_campaigns"),
        sa.UniqueConstraint("client_id", "public_code", name="uq_link_campaigns_client_code"),
    )
    op.create_table(
        "link_content_references",
        *_base("link_content_references"),
        sa.Column("external_code", sa.String(length=128), nullable=False),
        sa.Column("platform_label", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "platform_label IS NULL OR length(btrim(platform_label)) > 0",
            name=op.f("ck_link_content_references_label_not_blank"),
        ),
        sa.CheckConstraint(
            "external_code ~ '^[A-Za-z0-9_.:-]{1,128}$'",
            name=op.f("ck_link_content_references_valid_code"),
        ),
        _status("link_content_references", "'active', 'archived'"),
        *_keys("link_content_references"),
        sa.UniqueConstraint(
            "client_id", "external_code", name="uq_link_content_references_client_code"
        ),
    )
    op.create_table(
        "link_utm_templates",
        *_base("link_utm_templates"),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "length(btrim(name)) > 0", name=op.f("ck_link_utm_templates_name_not_blank")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(parameters) = 'object'",
            name=op.f("ck_link_utm_templates_object_parameters"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_link_utm_templates_positive_revision")),
        _status("link_utm_templates", "'active', 'archived'"),
        *_keys("link_utm_templates"),
        sa.UniqueConstraint("client_id", "name", name="uq_link_utm_templates_client_name"),
    )
    op.create_table(
        "link_destination_origins",
        *_base("link_destination_origins"),
        sa.Column("origin", sa.String(length=200), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column(
            "query_names",
            postgresql.ARRAY(sa.String(length=64)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "cardinality(query_names) <= 20",
            name=op.f("ck_link_destination_origins_bounded_query_names"),
        ),
        _status("link_destination_origins", "'active', 'disabled'"),
        *_keys("link_destination_origins"),
        sa.UniqueConstraint(
            "client_id", "origin", name="uq_link_destination_origins_client_origin"
        ),
    )
    op.create_index(
        "ix_link_destination_origins_hostname", "link_destination_origins", ["hostname"]
    )
    failure_codes = ", ".join(f"'{code}'" for code in FAILURE_CODES)
    op.create_table(
        "link_domains",
        *_base("link_domains"),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("challenge_digest", sa.String(length=64), nullable=True),
        sa.Column("challenge_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_code", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(
            nullable=(
                "challenge_expires_at",
                "verified_at",
                "verification_expires_at",
                "certificate_expires_at",
                "last_checked_at",
            )
        ),
        sa.CheckConstraint(
            "challenge_digest IS NULL OR challenge_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_link_domains_challenge_digest"),
        ),
        sa.CheckConstraint(
            "challenge_generation >= 0 AND version >= 1",
            name=op.f("ck_link_domains_valid_counters"),
        ),
        sa.CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({failure_codes})",
            name=op.f("ck_link_domains_valid_failure_code"),
        ),
        _status("link_domains", "'pending', 'verified', 'disabled'"),
        sa.CheckConstraint(
            "status <> 'verified' OR (verified_at IS NOT NULL "
            "AND verification_expires_at IS NOT NULL)",
            name=op.f("ck_link_domains_verified_state"),
        ),
        *_keys("link_domains"),
        sa.UniqueConstraint("hostname", name="uq_link_domains_hostname"),
    )
    op.create_table(
        "managed_links",
        *_base("managed_links"),
        sa.Column("domain_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("origin_id", sa.Uuid(), nullable=False),
        sa.Column("destination", sa.String(length=2048), nullable=False),
        sa.Column("utm", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("content_reference_id", sa.Uuid(), nullable=True),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("template_revision", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        *_timestamps(nullable=("expires_at",)),
        sa.CheckConstraint(
            "jsonb_typeof(utm) = 'object'", name=op.f("ck_managed_links_object_utm")
        ),
        sa.CheckConstraint(
            "(template_id IS NULL) = (template_revision IS NULL)",
            name=op.f("ck_managed_links_template_revision"),
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9-]{2,63}$'", name=op.f("ck_managed_links_valid_slug")
        ),
        _status("managed_links", "'active', 'disabled'"),
        *_keys("managed_links"),
        _scoped("domain_id", "link_domains"),
        _scoped("origin_id", "link_destination_origins"),
        _scoped("campaign_id", "link_campaigns"),
        _scoped("content_reference_id", "link_content_references"),
        _scoped("template_id", "link_utm_templates"),
        sa.UniqueConstraint("domain_id", "slug", name="uq_managed_links_domain_slug"),
    )
    op.create_index(
        "uq_managed_links_platform_slug",
        "managed_links",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("domain_id IS NULL"),
    )
    op.create_index(
        "ix_managed_links_client_created", "managed_links", ["client_id", "created_at", "id"]
    )
    op.add_column("collected_events", sa.Column("link_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_collected_events_agency_id_managed_links"),
        "collected_events",
        "managed_links",
        ["agency_id", "client_id", "link_id"],
        ["agency_id", "client_id", "id"],
    )
    op.create_index("ix_collected_events_link_id", "collected_events", ["link_id"])
    op.drop_constraint(op.f("ck_audit_events_valid_action"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_valid_action"), "audit_events", ACTIONS)
    op.drop_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", RESOURCES)
    for statement in RUNTIME_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"LOCK TABLE {', '.join(TABLES)}, collected_events, audit_events "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    populated = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
    actions = ", ".join(f"'{item}'" for item in NEW_ACTIONS)
    if connection.execute(
        sa.text(
            f"SELECT {populated} "
            "OR EXISTS (SELECT 1 FROM collected_events WHERE link_id IS NOT NULL) "
            f"OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
        )
    ).scalar_one():
        raise RuntimeError("Refuse to remove populated managed-link state; use a forward fix.")
    op.execute("REVOKE UPDATE (link_id) ON collected_events FROM tracking_app")
    op.drop_constraint(op.f("ck_audit_events_valid_resource"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_resource"), "audit_events", PREVIOUS_RESOURCES
    )
    op.drop_constraint(op.f("ck_audit_events_valid_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_valid_action"), "audit_events", PREVIOUS_ACTIONS
    )
    op.drop_index("ix_collected_events_link_id", table_name="collected_events")
    op.drop_constraint(
        op.f("fk_collected_events_agency_id_managed_links"), "collected_events", type_="foreignkey"
    )
    op.drop_column("collected_events", "link_id")
    for table in TABLES:
        op.drop_table(table)
