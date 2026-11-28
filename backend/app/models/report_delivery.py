"""Retained exports, report schedules and agency branding (specification 016-C, D-095).

A retained export is one report CSV of one client, sealed under the token keyring in its own
content row, available for at most 7 days and revoked at once by its creator, a manager, an
erasure, a disconnection or the archival of its client (D2-D7). A schedule builds one report of
a client on a daily, weekly or monthly slot with its owner's permissions and notifies member
recipients (D8-D10). An agency branding profile holds the name its clients see, an accent color
and an optional PNG logo (D11).

Export rows hold identifiers, closed codes, dates, counts and times; the CSV exists only as
AES-GCM ciphertext. Schedule rows hold a manager-entered name, closed codes and references.
Reference queries below are manual read-only diagnostics for an authorized operator; replace
the synthetic literals before use.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

FAMILIES = ("social", "spend", "revenue", "attribution", "roas", "funnel")
CONNECTION_FAMILIES = ("social", "spend", "roas")
EXPORT_STATUSES = ("pending", "ready", "revoked", "discarded")
REVOCATION_REASONS = (
    "manual",
    "erasure",
    "disconnection",
    "connection_purged",
    "client_archived",
    # 017-B (D-098 D6): the offboarding of a closed agency revokes its exports.
    "agency_closed",
)
PAUSE_REASONS = ("manual", "owner_access_lost", "repeated_failures")
RUN_ERRORS = (
    "report_changed",
    "report_too_large",
    "source_unavailable",
    "source_not_ready",
    "not_configured",
    "export_limit_reached",
    "export_refused",
    "build_failed",
)
MAX_EXPORT_BYTES = 2 * 1024 * 1024
MAX_LOGO_BYTES = 256 * 1024
NAME_RULE = "length(btrim(name)) > 0 AND name !~ '[[:cntrl:]]'"


def _listed(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _time(nullable: bool = True, *, default: bool = False) -> Any:
    return mapped_column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=func.now() if default else None,
    )


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


# One retained export (D2-D7). pending reserves a place among the client's 50 while the CSV is
# built; ready is stored and downloadable; revoked was ready and lost its content; discarded
# never became ready. Only ready and revoked rows are ever listed.
# SELECT id, family, status, revoked_reason, created_at, stored_at, expires_at, row_count,
#        byte_size, download_count
# FROM public.report_exports
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at DESC, id DESC LIMIT 50;
class ReportExport(Base):
    __tablename__ = "report_exports"
    __table_args__ = (
        UniqueConstraint("agency_id", "client_id", "id", name="uq_report_exports_scope"),
        ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name="fk_report_exports_client_workspaces",
        ),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "connection_id"],
            [
                "connector_connections.agency_id",
                "connector_connections.client_id",
                "connector_connections.id",
            ],
            name="fk_report_exports_connector_connections",
        ),
        ForeignKeyConstraint(
            ["agency_id", "requested_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name="fk_report_exports_requested_by_agency_memberships",
        ),
        Index("ix_report_exports_listing", "agency_id", "client_id", "created_at", "id"),
        Index(
            "ix_report_exports_open_connection",
            "client_id",
            "connection_id",
            postgresql_where=text("status IN ('pending', 'ready')"),
        ),
        Index("ix_report_exports_expires_at", "expires_at"),
        Index(
            "ix_report_exports_schedule_id",
            "schedule_id",
            postgresql_where=text("schedule_id IS NOT NULL"),
        ),
        CheckConstraint(_listed("family", FAMILIES), name="valid_family"),
        CheckConstraint("jsonb_typeof(parameters) = 'object'", name="parameters_object"),
        CheckConstraint(
            f"({_listed('family', CONNECTION_FAMILIES)}) = (connection_id IS NOT NULL)",
            name="connection_family",
        ),
        CheckConstraint(
            "period_end > period_start AND period_end - period_start <= 31", name="valid_period"
        ),
        CheckConstraint("source IN ('manual', 'schedule')", name="valid_source"),
        CheckConstraint("source = 'schedule' OR schedule_id IS NULL", name="schedule_source"),
        CheckConstraint(_listed("status", EXPORT_STATUSES), name="valid_status"),
        CheckConstraint(
            f"revoked_reason IS NULL OR {_listed('revoked_reason', REVOCATION_REASONS)}",
            name="valid_revoked_reason",
        ),
        CheckConstraint(EXPORT_STATE, name="state"),
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + interval '7 days'",
            name="lifetime",
        ),
        CheckConstraint(
            "row_count IS NULL OR row_count BETWEEN 0 AND 5000", name="valid_row_count"
        ),
        CheckConstraint(
            f"byte_size IS NULL OR byte_size BETWEEN 1 AND {MAX_EXPORT_BYTES}",
            name="valid_byte_size",
        ),
        CheckConstraint(
            "report_revision IS NULL OR report_revision ~ '^[0-9a-f]{64}$'",
            name="valid_revision",
        ),
        CheckConstraint(
            "download_count >= 0 AND (download_count = 0 OR last_downloaded_at IS NOT NULL)",
            name="downloads",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    family: Mapped[str] = mapped_column(String(16))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    connection_id: Mapped[UUID | None] = mapped_column(Uuid)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    includes_financials: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(16))
    schedule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("report_schedules.id", ondelete="SET NULL")
    )
    requested_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    revoked_at: Mapped[datetime | None] = _time()
    revoked_reason: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = _time(False, default=True)
    stored_at: Mapped[datetime | None] = _time()
    expires_at: Mapped[datetime] = _time(False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    report_revision: Mapped[str | None] = mapped_column(String(64))
    download_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_downloaded_at: Mapped[datetime | None] = _time()


# The sealed CSV of one ready export (D4): AES-GCM under a fresh data key wrapped by the token
# keyring, bound to the export, its agency and its client. Deleted at revocation and expiry.
# SELECT export_id, kek_id, alg, aad_version, octet_length(ciphertext) AS sealed_bytes
# FROM public.report_export_contents
# WHERE export_id = '00000000-0000-0000-0000-000000000004'::uuid;
class ReportExportContent(Base):
    __tablename__ = "report_export_contents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "export_id"],
            ["report_exports.agency_id", "report_exports.client_id", "report_exports.id"],
            name="fk_report_export_contents_report_exports",
        ),
        CheckConstraint("kek_id ~ '^[a-z0-9][a-z0-9-]{0,31}$'", name="valid_kek_id"),
        CheckConstraint(
            "octet_length(wrap_nonce) = 12 AND octet_length(nonce) = 12 "
            "AND octet_length(wrapped_dek) = 48",
            name="key_material",
        ),
        CheckConstraint(
            f"octet_length(ciphertext) BETWEEN 17 AND {MAX_EXPORT_BYTES + 16}",
            name="ciphertext_size",
        ),
        CheckConstraint("alg = 'A256GCM-ENV-v1' AND aad_version = 1", name="valid_format"),
    )

    export_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    kek_id: Mapped[str] = mapped_column(String(32))
    wrap_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    alg: Mapped[str] = mapped_column(String(32))
    aad_version: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = _time(False, default=True)


# One schedule of one report of a client (D8-D10). The worker claims it when next_run_at is due
# and moves it to its next slot; it runs with the owner membership's permissions.
# SELECT id, family, cadence, weekday, hour, time_zone, status, pause_reason, next_run_at,
#        last_run_at, last_outcome, last_error_code, consecutive_failures
# FROM public.report_schedules
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at, id;
class ReportSchedule(Base):
    __tablename__ = "report_schedules"
    __table_args__ = (
        UniqueConstraint("agency_id", "client_id", "id", name="uq_report_schedules_scope"),
        ForeignKeyConstraint(
            ["agency_id", "client_id"],
            ["client_workspaces.agency_id", "client_workspaces.id"],
            name="fk_report_schedules_client_workspaces",
        ),
        ForeignKeyConstraint(
            ["agency_id", "owner_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name="fk_report_schedules_owner_agency_memberships",
        ),
        Index("ix_report_schedules_due", "next_run_at", postgresql_where=text("status = 'active'")),
        Index("ix_report_schedules_client", "agency_id", "client_id", "created_at"),
        CheckConstraint(NAME_RULE, name="valid_name"),
        CheckConstraint(_listed("family", FAMILIES), name="valid_family"),
        CheckConstraint("jsonb_typeof(parameters) = 'object'", name="parameters_object"),
        CheckConstraint(
            "NOT sale_values OR family IN ('attribution', 'funnel')", name="sale_values_family"
        ),
        CheckConstraint("cadence IN ('daily', 'weekly', 'monthly')", name="valid_cadence"),
        CheckConstraint(
            "(cadence = 'weekly') = (weekday IS NOT NULL) "
            "AND (weekday IS NULL OR weekday BETWEEN 1 AND 7)",
            name="valid_weekday",
        ),
        CheckConstraint("hour BETWEEN 0 AND 23", name="valid_hour"),
        CheckConstraint("length(time_zone) BETWEEN 1 AND 64", name="valid_time_zone"),
        CheckConstraint("status IN ('active', 'paused')", name="valid_status"),
        CheckConstraint(
            f"(status = 'paused') = (pause_reason IS NOT NULL) "
            f"AND (pause_reason IS NULL OR {_listed('pause_reason', PAUSE_REASONS)})",
            name="valid_pause",
        ),
        CheckConstraint("status = 'paused' OR next_run_at IS NOT NULL", name="active_slot"),
        CheckConstraint(
            "last_outcome IS NULL OR last_outcome IN ('built', 'failed')", name="valid_outcome"
        ),
        CheckConstraint(
            f"(last_outcome = 'failed') = (last_error_code IS NOT NULL) "
            f"AND (last_error_code IS NULL OR {_listed('last_error_code', RUN_ERRORS)})",
            name="valid_error",
        ),
        CheckConstraint("last_notified >= 0 AND last_skipped >= 0", name="valid_counts"),
        CheckConstraint("consecutive_failures BETWEEN 0 AND 3", name="valid_failures"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(100))
    family: Mapped[str] = mapped_column(String(16))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sale_values: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    compare: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    cadence: Mapped[str] = mapped_column(String(8))
    weekday: Mapped[int | None] = mapped_column(SmallInteger)
    hour: Mapped[int] = mapped_column(SmallInteger)
    time_zone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(8), server_default="active")
    pause_reason: Mapped[str | None] = mapped_column(String(24))
    owner_membership_id: Mapped[UUID] = mapped_column(Uuid)
    next_run_at: Mapped[datetime | None] = _time()
    last_run_at: Mapped[datetime | None] = _time()
    last_outcome: Mapped[str | None] = mapped_column(String(16))
    last_error_code: Mapped[str | None] = mapped_column(String(32))
    last_notified: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_skipped: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    consecutive_failures: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    created_at: Mapped[datetime] = _time(False, default=True)
    updated_at: Mapped[datetime] = _time(False, default=True)


# One member recipient of a schedule (D9); at most 20 per schedule.
# SELECT membership_id, created_at FROM public.report_schedule_recipients
# WHERE schedule_id = '00000000-0000-0000-0000-000000000005'::uuid ORDER BY membership_id;
class ReportScheduleRecipient(Base):
    __tablename__ = "report_schedule_recipients"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "client_id", "schedule_id"],
            ["report_schedules.agency_id", "report_schedules.client_id", "report_schedules.id"],
            name="fk_report_schedule_recipients_report_schedules",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["agency_id", "membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name="fk_report_schedule_recipients_agency_memberships",
        ),
        Index("ix_report_schedule_recipients_membership", "agency_id", "membership_id"),
    )

    schedule_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    membership_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = _time(False, default=True)


# One agency's branding profile (D11): the name its clients see, an accent color and an
# optional PNG logo of at most 256 KiB and 1024 by 1024 pixels.
# SELECT agency_id, display_name, accent_color, logo_width, logo_height,
#        octet_length(logo) AS logo_bytes, updated_at
# FROM public.agency_branding WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid;
class AgencyBranding(Base):
    __tablename__ = "agency_branding"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "updated_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name="fk_agency_branding_updated_by_agency_memberships",
        ),
        CheckConstraint(NAME_RULE.replace("name", "display_name"), name="valid_display_name"),
        CheckConstraint("accent_color ~ '^#[0-9A-F]{6}$'", name="valid_accent_color"),
        CheckConstraint(
            f"logo IS NULL OR octet_length(logo) BETWEEN 67 AND {MAX_LOGO_BYTES}",
            name="logo_size",
        ),
        CheckConstraint(
            "(logo IS NULL) = (logo_width IS NULL) AND (logo IS NULL) = (logo_height IS NULL) "
            "AND (logo_width IS NULL OR logo_width BETWEEN 1 AND 1024) "
            "AND (logo_height IS NULL OR logo_height BETWEEN 1 AND 1024)",
            name="logo_dimensions",
        ),
    )

    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    accent_color: Mapped[str] = mapped_column(String(7))
    logo: Mapped[bytes | None] = mapped_column(LargeBinary)
    logo_width: Mapped[int | None] = mapped_column(SmallInteger)
    logo_height: Mapped[int | None] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = _time(False, default=True)
    updated_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
