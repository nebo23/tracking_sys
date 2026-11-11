"""Managed links, campaign provenance, and custom domains (specification 005-B, D-033).

Every table is scoped by agency and client through composite foreign keys, so a link can
never reference another client's campaign, content reference, template, origin, or domain.
Issued link provenance (slug, domain, destination, UTM snapshot, target, campaign, content,
template revision) is immutable: the runtime role may update only status and expiry. Rows are
never hard-deleted by the runtime, so slugs and hostnames are never recycled in 005.
Reference queries below are manual read-only diagnostics for an authorized operator; replace
the synthetic literals before use. Challenge digests are omitted.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.tenancy import Entity

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])
FAILURE_CODES = (
    "ownership_missing",
    "routing_mismatch",
    "address_not_allowed",
    "tls_invalid",
    "challenge_expired",
    "verification_unavailable",
    "host_conflict",
)


def _scope(table: str) -> UniqueConstraint:
    return UniqueConstraint("agency_id", "client_id", "id", name=f"uq_{table}_scope")


def _scoped_fk(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["agency_id", "client_id", column],
        [f"{table}.agency_id", f"{table}.client_id", f"{table}.id"],
    )


# Campaign of one client with an immutable public code (used as utm_id) and a display label.
# SELECT id, public_code, label, status, created_at
# FROM public.link_campaigns
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at, id LIMIT 100;
class LinkCampaign(Entity, Base):
    __tablename__ = "link_campaigns"
    __table_args__ = (
        _scope("link_campaigns"),
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("client_id", "public_code", name="uq_link_campaigns_client_code"),
        CheckConstraint("public_code ~ '^[A-Za-z0-9_.-]{1,64}$'", name="valid_code"),
        CheckConstraint("length(btrim(label)) > 0", name="label_not_blank"),
        CheckConstraint("status IN ('active', 'archived')", name="valid_status"),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    public_code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


# Opaque external reference to one piece of content (for example a post) with an optional
# platform label. It is not proof of access to that platform and holds no content body.
# SELECT id, external_code, platform_label, status, created_at
# FROM public.link_content_references
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at, id LIMIT 100;
class LinkContentReference(Entity, Base):
    __tablename__ = "link_content_references"
    __table_args__ = (
        _scope("link_content_references"),
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint(
            "client_id", "external_code", name="uq_link_content_references_client_code"
        ),
        CheckConstraint("external_code ~ '^[A-Za-z0-9_.:-]{1,128}$'", name="valid_code"),
        CheckConstraint(
            "platform_label IS NULL OR length(btrim(platform_label)) > 0", name="label_not_blank"
        ),
        CheckConstraint("status IN ('active', 'archived')", name="valid_status"),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    external_code: Mapped[str] = mapped_column(String(128))
    platform_label: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="active")


# Named UTM template; editing increases revision and never rewrites issued links.
# SELECT id, name, revision, status, updated_at
# FROM public.link_utm_templates
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY name LIMIT 100;
class LinkUtmTemplate(Entity, Base):
    __tablename__ = "link_utm_templates"
    __table_args__ = (
        _scope("link_utm_templates"),
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("client_id", "name", name="uq_link_utm_templates_client_name"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("jsonb_typeof(parameters) = 'object'", name="object_parameters"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("status IN ('active', 'archived')", name="valid_status"),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(100))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    status: Mapped[str] = mapped_column(String(16), server_default="active")


# Exact destination origin registered by the client's Owner/Admin, with its approved static
# query names. hostname is the canonical host, kept for the managed-host conflict checks.
# SELECT id, origin, query_names, status, created_at
# FROM public.link_destination_origins
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY origin LIMIT 100;
class LinkDestinationOrigin(Entity, Base):
    __tablename__ = "link_destination_origins"
    __table_args__ = (
        _scope("link_destination_origins"),
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("client_id", "origin", name="uq_link_destination_origins_client_origin"),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
        CheckConstraint("cardinality(query_names) <= 20", name="bounded_query_names"),
        Index("ix_link_destination_origins_hostname", "hostname"),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    origin: Mapped[str] = mapped_column(String(200))
    hostname: Mapped[str] = mapped_column(String(253))
    query_names: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), server_default=text("'{}'::varchar[]")
    )
    status: Mapped[str] = mapped_column(String(16), server_default="active")


# Custom short-link hostname reserved globally to one client. Verification proves the
# client's DNS control (TXT challenge), routing (CNAME to the service target), and a trusted
# certificate; it expires and is never inferred from certificate issuance.
# SELECT id, client_id, hostname, status, challenge_generation, challenge_expires_at,
#        verified_at, verification_expires_at, certificate_expires_at, failure_code, version
# FROM public.link_domains
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid ORDER BY hostname LIMIT 100;
class LinkDomain(Entity, Base):
    __tablename__ = "link_domains"
    __table_args__ = (
        _scope("link_domains"),
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("hostname", name="uq_link_domains_hostname"),
        CheckConstraint("status IN ('pending', 'verified', 'disabled')", name="valid_status"),
        CheckConstraint(
            "challenge_digest IS NULL OR challenge_digest ~ '^[0-9a-f]{64}$'",
            name="challenge_digest",
        ),
        CheckConstraint(
            "status <> 'verified' OR (verified_at IS NOT NULL "
            "AND verification_expires_at IS NOT NULL)",
            name="verified_state",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            + ", ".join(f"'{code}'" for code in FAILURE_CODES)
            + ")",
            name="valid_failure_code",
        ),
        CheckConstraint("challenge_generation >= 0 AND version >= 1", name="valid_counters"),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    hostname: Mapped[str] = mapped_column(String(253))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    challenge_digest: Mapped[str | None] = mapped_column(String(64))
    challenge_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    challenge_generation: Mapped[int] = mapped_column(Integer, server_default="0")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certificate_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, server_default="1")


# Managed short link. A null domain_id means the platform short-link host. The issued
# provenance columns are immutable; replacing provenance means issuing a new link.
# SELECT id, slug, domain_id, target_url, campaign_id, content_reference_id, status, expires_at
# FROM public.managed_links
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at, id LIMIT 100;
class ManagedLink(Entity, Base):
    __tablename__ = "managed_links"
    __table_args__ = (
        _scope("managed_links"),
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped_fk("domain_id", "link_domains"),
        _scoped_fk("origin_id", "link_destination_origins"),
        _scoped_fk("campaign_id", "link_campaigns"),
        _scoped_fk("content_reference_id", "link_content_references"),
        _scoped_fk("template_id", "link_utm_templates"),
        UniqueConstraint("domain_id", "slug", name="uq_managed_links_domain_slug"),
        Index(
            "uq_managed_links_platform_slug",
            "slug",
            unique=True,
            postgresql_where=text("domain_id IS NULL"),
        ),
        Index("ix_managed_links_client_created", "client_id", "created_at", "id"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{2,63}$'", name="valid_slug"),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
        CheckConstraint("jsonb_typeof(utm) = 'object'", name="object_utm"),
        CheckConstraint(
            "(template_id IS NULL) = (template_revision IS NULL)", name="template_revision"
        ),
    )
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    domain_id: Mapped[UUID | None] = mapped_column(Uuid)
    slug: Mapped[str] = mapped_column(String(64))
    origin_id: Mapped[UUID] = mapped_column(Uuid)
    destination: Mapped[str] = mapped_column(String(2048))
    utm: Mapped[dict[str, str]] = mapped_column(JSONB)
    target_url: Mapped[str] = mapped_column(String(2048))
    campaign_id: Mapped[UUID | None] = mapped_column(Uuid)
    content_reference_id: Mapped[UUID | None] = mapped_column(Uuid)
    template_id: Mapped[UUID | None] = mapped_column(Uuid)
    template_revision: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
