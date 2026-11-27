"""Offboarding exports and purge records of closing and closed agencies (017-B, D-098).

An agency export is the ZIP of every client's first-party data that an Owner requests during
the closing period (D2-D5): pending while the worker builds it, ready, failed with a closed
code, or revoked; at most one is open per agency. Its ZIP exists only as sealed parts of at most
8 MiB under the token keyring, bound to the agency, the export and the part number. A purge
record is the one row that stays with a closed agency after its purge (D8): the copied closure
times, the export summary, the offboarding, teardown and purge times and the deleted row count
of each table; purge_agency_batch (migration 0033) writes its last two states.

Rows hold identifiers, closed codes, counts, digests and times only: no name, email, token,
figure or file content outside the sealed parts. Reference queries below are manual read-only
diagnostics for an authorized operator; replace the synthetic literals before use.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
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

EXPORT_STATUSES = ("pending", "ready", "failed", "revoked")
EXPORT_ERRORS = ("export_too_large", "closure_completed", "build_failed")
PURGE_STATES = ("offboarding", "waiting", "purging", "purged")
MAX_PARTS = 64
PART_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 512 * 1024 * 1024
MAX_EXPORT_ROWS = 2_000_000


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def _time(nullable: bool = True, *, default: bool = False) -> Any:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now() if default else None,
        nullable=nullable,
    )


# One offboarding export of an agency (D3, D5).
# SELECT id, status, error_code, requested_at, ready_at, revoked_at, expires_at, part_count,
#        byte_size, row_count, download_count, last_downloaded_at
# FROM public.agency_exports
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid ORDER BY requested_at DESC;
class AgencyExport(Base):
    __tablename__ = "agency_exports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "requested_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name="fk_agency_exports_requested_by_agency_memberships",
        ),
        UniqueConstraint("agency_id", "id", name="uq_agency_exports_scope"),
        Index(
            "uq_agency_exports_open",
            "agency_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'ready')"),
        ),
        Index("ix_agency_exports_agency", "agency_id", "requested_at"),
        Index(
            "ix_agency_exports_pending", "requested_at", postgresql_where=text("status = 'pending'")
        ),
        Index("ix_agency_exports_expires_at", "expires_at"),
        CheckConstraint(f"status IN ({_values(EXPORT_STATUSES)})", name="valid_status"),
        CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_values(EXPORT_ERRORS)})", name="valid_error"
        ),
        CheckConstraint(
            "(status = 'pending' AND error_code IS NULL AND ready_at IS NULL "
            "AND revoked_at IS NULL AND part_count IS NULL AND byte_size IS NULL "
            "AND row_count IS NULL AND row_counts IS NULL AND manifest_sha256 IS NULL) "
            "OR (status = 'ready' AND error_code IS NULL AND ready_at IS NOT NULL "
            "AND revoked_at IS NULL AND part_count IS NOT NULL AND byte_size IS NOT NULL "
            "AND row_count IS NOT NULL AND row_counts IS NOT NULL "
            "AND manifest_sha256 IS NOT NULL) "
            "OR (status = 'failed' AND error_code IS NOT NULL AND ready_at IS NULL "
            "AND revoked_at IS NULL AND part_count IS NULL) "
            "OR (status = 'revoked' AND error_code IS NULL AND revoked_at IS NOT NULL)",
            name="state",
        ),
        CheckConstraint(
            "expires_at > requested_at AND expires_at <= requested_at + interval '7 days'",
            name="lifetime",
        ),
        CheckConstraint(
            "(ready_at IS NULL OR ready_at >= requested_at) "
            "AND (revoked_at IS NULL OR revoked_at >= requested_at)",
            name="times",
        ),
        CheckConstraint(
            f"part_count IS NULL OR part_count BETWEEN 1 AND {MAX_PARTS}", name="valid_part_count"
        ),
        CheckConstraint(
            f"byte_size IS NULL OR byte_size BETWEEN 1 AND {MAX_EXPORT_BYTES}",
            name="valid_byte_size",
        ),
        CheckConstraint(
            f"row_count IS NULL OR row_count BETWEEN 0 AND {MAX_EXPORT_ROWS}",
            name="valid_row_count",
        ),
        CheckConstraint(
            "row_counts IS NULL OR jsonb_typeof(row_counts) = 'object'", name="row_counts_object"
        ),
        CheckConstraint(
            "manifest_sha256 IS NULL OR manifest_sha256 ~ '^[0-9a-f]{64}$'", name="valid_manifest"
        ),
        CheckConstraint(
            "download_count >= 0 AND (download_count = 0 OR last_downloaded_at IS NOT NULL)",
            name="downloads",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    requested_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    error_code: Mapped[str | None] = mapped_column(String(32))
    requested_at: Mapped[datetime] = _time(False, default=True)
    ready_at: Mapped[datetime | None] = _time()
    revoked_at: Mapped[datetime | None] = _time()
    expires_at: Mapped[datetime] = _time(False)
    part_count: Mapped[int | None] = mapped_column(SmallInteger)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    row_count: Mapped[int | None] = mapped_column(Integer)
    row_counts: Mapped[dict[str, int] | None] = mapped_column(JSONB)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    download_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_downloaded_at: Mapped[datetime | None] = _time()


# One sealed part of a ready export's ZIP; material columns are never selected for display.
# SELECT export_id, part, kek_id, octet_length(ciphertext) AS bytes, created_at
# FROM public.agency_export_parts
# WHERE export_id = '00000000-0000-0000-0000-00000000000e'::uuid ORDER BY part;
class AgencyExportPart(Base):
    __tablename__ = "agency_export_parts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "export_id"],
            ["agency_exports.agency_id", "agency_exports.id"],
            name="fk_agency_export_parts_agency_exports",
        ),
        CheckConstraint(f"part BETWEEN 1 AND {MAX_PARTS}", name="valid_part"),
        CheckConstraint("kek_id ~ '^[a-z0-9][a-z0-9-]{0,31}$'", name="valid_kek_id"),
        CheckConstraint(
            "octet_length(wrap_nonce) = 12 AND octet_length(nonce) = 12 "
            "AND octet_length(wrapped_dek) = 48",
            name="key_material",
        ),
        CheckConstraint(
            f"octet_length(ciphertext) BETWEEN 17 AND {PART_BYTES + 16}", name="ciphertext_size"
        ),
        CheckConstraint("alg = 'A256GCM-ENV-v1' AND aad_version = 1", name="valid_format"),
    )

    export_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    part: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    kek_id: Mapped[str] = mapped_column(String(32))
    wrap_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    alg: Mapped[str] = mapped_column(String(32))
    aad_version: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = _time(False, default=True)


# The purge record of a closed agency (D7, D8); it stays after the purge.
# SELECT agency_id, state, closure_requested_at, closes_at, closure_completed_at,
#        offboarding_started_at, offboarding_completed_at, teardown_settled_at,
#        purge_started_at, purge_completed_at, export_summary, deleted_counts
# FROM public.agency_purges
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid;
class AgencyPurge(Base):
    __tablename__ = "agency_purges"
    __table_args__ = (
        Index("ix_agency_purges_open", "state", postgresql_where=text("state <> 'purged'")),
        CheckConstraint(f"state IN ({_values(PURGE_STATES)})", name="valid_state"),
        CheckConstraint(
            "closes_at > closure_requested_at AND closure_completed_at >= closes_at",
            name="closure_times",
        ),
        CheckConstraint(
            "(state = 'offboarding' AND offboarding_completed_at IS NULL "
            "AND teardown_settled_at IS NULL AND purge_started_at IS NULL "
            "AND purge_completed_at IS NULL) "
            "OR (state = 'waiting' AND offboarding_completed_at IS NOT NULL "
            "AND teardown_settled_at IS NULL AND purge_started_at IS NULL "
            "AND purge_completed_at IS NULL) "
            "OR (state = 'purging' AND offboarding_completed_at IS NOT NULL "
            "AND teardown_settled_at IS NOT NULL AND purge_started_at IS NOT NULL "
            "AND purge_completed_at IS NULL) "
            "OR (state = 'purged' AND offboarding_completed_at IS NOT NULL "
            "AND teardown_settled_at IS NOT NULL AND purge_started_at IS NOT NULL "
            "AND purge_completed_at IS NOT NULL)",
            name="progress",
        ),
        CheckConstraint("jsonb_typeof(export_summary) = 'object'", name="summary_object"),
        CheckConstraint("jsonb_typeof(deleted_counts) = 'object'", name="counts_object"),
    )

    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    closure_requested_at: Mapped[datetime] = _time(False)
    closes_at: Mapped[datetime] = _time(False)
    closure_completed_at: Mapped[datetime] = _time(False)
    export_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    offboarding_started_at: Mapped[datetime] = _time(False, default=True)
    offboarding_completed_at: Mapped[datetime | None] = _time()
    teardown_settled_at: Mapped[datetime | None] = _time()
    purge_started_at: Mapped[datetime | None] = _time()
    purge_completed_at: Mapped[datetime | None] = _time()
    deleted_counts: Mapped[dict[str, int]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
