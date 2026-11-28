"""The offboarding export of a closing agency (specification 017-B, D-098 D2 to D5).

During the closing period an active Owner requests one ZIP of every client's first-party data,
until 24 hours before the closing time, with the reauthentication of account closure (D2, D3).
The request replaces the open export and is audited. The offboarding worker builds it in the
background (design-017b.md section 3.3):

1. claim: a pending export of a closing agency, under a session advisory lock on the export, so
   two workers never build it twice;
2. snapshots: each client's catalog tables are read in one REPEATABLE READ READ ONLY
   transaction and written as JSON Lines members of a ZIP in a temporary file, with the bounds
   of D5 checked as it grows (2,000,000 rows, 512 MiB);
3. checks: the ZIP is reopened and every member's row count and SHA-256 compared with the
   manifest before anything is stored;
4. store: under the agency row lock, which the closure completion also takes first, the export
   becomes ready with its parts sealed under the token keyring (at most 8 MiB each, bound to
   the agency, the export and the part number) only while the agency is still closing and the
   export still pending.

A download resolves the Owner again, needs a ready, unexpired export of a closing agency, counts
the download, and streams the parts from one REPEATABLE READ snapshot opened before the answer
starts. The catalog is an allowlist (D4): a column is exported only when it is listed below, and
EXCLUDED_COLUMNS names every other column of an exported table. Provider-sourced data, secrets,
keys, digests, tokens, the audit log, erasure records, diagnostics and processing state are not
exported. Nothing here logs or returns a name, a figure or file content.
"""

import hashlib
import json
import logging
import os
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import IO, Any
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from sqlalchemy import Engine, delete, func, insert, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base
from app.models import (
    Agency,
    AgencyClosure,
    AgencyExport,
    AgencyExportPart,
    AuthSession,
    ClientWorkspace,
    User,
)
from app.privacy.token_secrets import (
    LocalKeyring,
    SealedSecret,
    SecretContext,
    open_bytes,
    seal_bytes,
)
from app.security import now_utc
from app.services.agency_closure import ClosureRefused, ClosureService, open_closure
from app.services.auth import AuthService
from app.services.collection import client_lock_key

logger = logging.getLogger("tracking")
# The request window ends 24 hours before the closing time (D2); the file lives 7 days (D5).
WINDOW_CUTOFF = timedelta(hours=24)
LIFETIME = timedelta(days=7)
# Development bounds and the part size (D5); tests change them through this module.
PART_BYTES = 8 * 1024 * 1024
MAX_ROWS = 2_000_000
MAX_BYTES = 512 * 1024 * 1024
ROW_BATCH = 1_000
# Session advisory lock of an export build, in the two-key space: (namespace, export key).
LOCK_NAMESPACE = 17017
FORMAT, FORMAT_VERSION = "tracking-agency-export", 1
MANIFEST = "manifest.json"
FILENAME = "agency-export.zip"

# The catalog of D4 (design-017b.md section 3.2): each exported table with its exported
# columns, in the order of the client folder. A column is exported only when it is listed.
CATALOG: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "client_workspaces",
        (
            "agency_id",
            "name",
            "status",
            "id",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "link_campaigns",
        (
            "id",
            "agency_id",
            "client_id",
            "public_code",
            "label",
            "status",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "link_content_references",
        (
            "id",
            "agency_id",
            "client_id",
            "external_code",
            "platform_label",
            "status",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "link_utm_templates",
        (
            "id",
            "agency_id",
            "client_id",
            "name",
            "parameters",
            "revision",
            "status",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "link_destination_origins",
        (
            "id",
            "agency_id",
            "client_id",
            "origin",
            "hostname",
            "query_names",
            "status",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "link_domains",
        (
            "id",
            "agency_id",
            "client_id",
            "hostname",
            "status",
            "challenge_generation",
            "failure_code",
            "version",
            "created_at",
            "updated_at",
            "challenge_expires_at",
            "verified_at",
            "verification_expires_at",
            "certificate_expires_at",
            "last_checked_at",
        ),
    ),
    (
        "managed_links",
        (
            "id",
            "agency_id",
            "client_id",
            "domain_id",
            "slug",
            "origin_id",
            "destination",
            "utm",
            "target_url",
            "campaign_id",
            "content_reference_id",
            "template_id",
            "template_revision",
            "status",
            "created_at",
            "updated_at",
            "expires_at",
        ),
    ),
    (
        "collection_forms",
        (
            "id",
            "agency_id",
            "client_id",
            "form_key",
            "version",
            "fields",
            "status",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "ingestion_sources",
        (
            "id",
            "agency_id",
            "client_id",
            "creator_membership_id",
            "kind",
            "name",
            "status",
            "allowed_origins",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "collection_subjects",
        (
            "id",
            "agency_id",
            "client_id",
            "created_at",
            "last_activity_at",
            "issuance_channel",
            "identity_floor_at",
            "identity_shared_at",
        ),
    ),
    (
        "collected_events",
        (
            "id",
            "agency_id",
            "client_id",
            "event_id",
            "event_type",
            "subject_id",
            "channel",
            "source_id",
            "credential_id",
            "trust_rank",
            "occurred_at",
            "first_received_at",
            "last_received_at",
            "revision",
            "payload",
            "consent_basis",
            "traffic_label",
            "policy_version",
            "conflict_count",
            "last_conflict_at",
            "expires_at",
            "link_id",
            "identity_excluded_at",
        ),
    ),
    (
        "consent_records",
        (
            "id",
            "agency_id",
            "client_id",
            "subject_id",
            "purpose",
            "state",
            "source",
            "jurisdiction_profile",
            "policy_version",
            "received_at",
            "captured_at",
            "expires_at",
            "supersedes_id",
        ),
    ),
    (
        "identity_subjects",
        (
            "id",
            "agency_id",
            "client_id",
            "status",
            "merged_into_id",
            "version",
            "journey_revision",
            "created_at",
            "updated_at",
            "last_evidence_at",
        ),
    ),
    (
        "identity_links",
        (
            "id",
            "agency_id",
            "client_id",
            "collection_subject_id",
            "status",
            "subject_id",
            "candidate_ids",
            "assertion_ref",
            "asserted_at",
            "eligible_from",
            "provisional_from",
            "eligible_until",
            "closed_reason",
            "merge_id",
            "original_owner_ids",
            "key_ids",
            "grant_started_at",
        ),
    ),
    (
        "identity_merges",
        (
            "id",
            "agency_id",
            "client_id",
            "operation_id",
            "kind",
            "survivor_id",
            "merged_id",
            "reverses_id",
            "status",
            "closed_reason",
            "survivor_version_before",
            "merged_version_before",
            "survivor_version_after",
            "merged_version_after",
            "result",
            "actor_membership_id",
            "reason_code",
            "created_at",
            "ended_at",
        ),
    ),
    (
        "revenue_evidence",
        (
            "id",
            "sequence",
            "agency_id",
            "client_id",
            "delivery_id",
            "source_account_id",
            "operation_id",
            "kind",
            "classification",
            "currency",
            "currency_exponent",
            "amount_minor",
            "effective_at",
            "received_at",
            "parent_operation_id",
            "reason",
            "actor",
            "source_reference",
            "intake",
            "intake_id",
        ),
    ),
    (
        "ledger_receipts",
        (
            "id",
            "agency_id",
            "client_id",
            "generation",
            "receipt_ordinal",
            "evidence_id",
            "evidence_sequence",
            "outcome",
            "closing_states",
            "created_at",
        ),
    ),
    (
        "ledger_movements",
        (
            "id",
            "agency_id",
            "client_id",
            "generation",
            "movement_sequence",
            "receipt_id",
            "source_account_id",
            "transaction_id",
            "operation_id",
            "kind",
            "direction",
            "amount_minor",
            "currency",
            "currency_exponent",
            "effective_at",
            "trigger_evidence_id",
            "reason",
        ),
    ),
    (
        "ledger_transactions",
        (
            "id",
            "agency_id",
            "client_id",
            "generation",
            "source_account_id",
            "operation_id",
            "currency",
            "currency_exponent",
            "sale_effective_at",
            "captured",
            "refunded",
            "charged_back",
            "reversed",
            "corrected",
            "net",
            "entries",
            "evidence_ids",
            "financial_revision",
            "updated_at",
        ),
    ),
    (
        "ledger_reconciliation_actions",
        (
            "id",
            "agency_id",
            "client_id",
            "operation_id",
            "issue_id",
            "issue_version",
            "evidence_ids",
            "action",
            "reason_code",
            "actor_membership_id",
            "created_at",
        ),
    ),
    (
        "revenue_identity_bindings",
        (
            "id",
            "agency_id",
            "client_id",
            "association_id",
            "revision",
            "request_id",
            "source_account_id",
            "sale_operation_id",
            "credential_id",
            "actor_membership_id",
            "assertion_ref",
            "collection_subject_id",
            "owner_subject_id",
            "key_ids",
            "state",
            "reason",
            "detach_reason",
            "expected_revision",
            "received_at",
            "closed_at",
        ),
    ),
    (
        "payment_sources",
        (
            "id",
            "agency_id",
            "client_id",
            "provider",
            "region",
            "name",
            "status",
            "live_integration_ids",
            "created_by_membership_id",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "integration_sources",
        (
            "id",
            "agency_id",
            "client_id",
            "kind",
            "name",
            "status",
            "created_by_membership_id",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "bookings",
        (
            "id",
            "agency_id",
            "client_id",
            "source_id",
            "provider",
            "status",
            "event_type_ref",
            "start_at",
            "end_at",
            "reschedule_count",
            "subject_id",
            "linked_at",
            "first_received_at",
            "updated_at",
        ),
    ),
    (
        "booking_events",
        (
            "id",
            "agency_id",
            "client_id",
            "booking_id",
            "source_id",
            "provider",
            "kind",
            "ref",
            "previous_ref",
            "event_type_ref",
            "occurred_at",
            "start_at",
            "end_at",
        ),
    ),
    (
        "crm_stage_rules",
        (
            "id",
            "agency_id",
            "client_id",
            "pipeline",
            "stage",
            "outcome",
            "status",
            "created_by_membership_id",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "crm_deals",
        (
            "id",
            "agency_id",
            "client_id",
            "source_id",
            "deal_ref",
            "pipeline",
            "stage",
            "previous_stage",
            "stage_at",
            "amount_minor",
            "currency",
            "currency_exponent",
            "amount_at",
            "payment_reference",
            "payment_reference_at",
            "first_received_at",
            "updated_at",
        ),
    ),
    (
        "whatsapp_numbers",
        (
            "id",
            "agency_id",
            "client_id",
            "phone_number_id",
            "name",
            "status",
            "created_by_membership_id",
            "created_at",
            "updated_at",
            "verified_at",
        ),
    ),
    (
        "whatsapp_messages",
        (
            "id",
            "agency_id",
            "client_id",
            "number_id",
            "message_at",
            "received_at",
            "has_referral",
            "source_type",
            "source_id",
            "click_id_present",
        ),
    ),
    (
        "attribution_model_versions",
        (
            "id",
            "agency_id",
            "client_id",
            "version_key",
            "model",
            "window_seconds",
            "rules",
            "is_default",
            "status",
            "created_by_membership_id",
            "operations",
            "created_at",
            "retired_at",
        ),
    ),
    (
        "attribution_conversions",
        (
            "id",
            "agency_id",
            "client_id",
            "generation",
            "kind",
            "owner_person_id",
            "association_id",
            "binding_id",
            "source_account_id",
            "sale_operation_id",
            "lead_event_id",
            "effective_at",
            "status",
            "superseded_generation",
            "superseded_at",
            "superseded_reason",
            "scrubbed_at",
            "recheck_at",
            "created_at",
        ),
    ),
    (
        "attribution_runs",
        (
            "id",
            "agency_id",
            "client_id",
            "generation",
            "conversion_id",
            "model_version_id",
            "revision",
            "status",
            "basis",
            "causes",
            "currency",
            "currency_exponent",
            "verified_net_minor",
            "window_start",
            "window_end",
            "ledger_generation",
            "receipt_ordinal",
            "identity_seq",
            "excluded_touchpoint_ids",
            "excluded_reasons",
            "touch_bound_exceeded",
            "recorded_at",
        ),
    ),
    (
        "attribution_allocations",
        (
            "id",
            "agency_id",
            "client_id",
            "run_id",
            "ordinal",
            "credited",
            "recipient",
            "basis",
            "position",
            "share_numerator",
            "share_denominator",
            "amount_minor",
            "touchpoint_id",
            "evidence_class",
            "occurred_at",
            "source",
            "campaign_ref",
            "content_ref",
            "link_ref",
        ),
    ),
    (
        "attribution_credit_changes",
        (
            "id",
            "agency_id",
            "client_id",
            "run_id",
            "model_version_id",
            "generation",
            "ordinal",
            "conversion_kind",
            "effective_at",
            "recipient",
            "touchpoint_id",
            "source",
            "campaign_ref",
            "content_ref",
            "link_ref",
            "delta_share_numerator",
            "delta_share_denominator",
            "delta_minor",
            "currency",
            "currency_exponent",
            "recorded_at",
        ),
    ),
    (
        "report_schedules",
        (
            "id",
            "agency_id",
            "client_id",
            "name",
            "family",
            "parameters",
            "sale_values",
            "compare",
            "cadence",
            "weekday",
            "hour",
            "time_zone",
            "status",
            "pause_reason",
            "owner_membership_id",
            "next_run_at",
            "last_run_at",
            "last_outcome",
            "last_error_code",
            "last_notified",
            "last_skipped",
            "consecutive_failures",
            "created_at",
            "updated_at",
        ),
    ),
    (
        "report_schedule_recipients",
        (
            "schedule_id",
            "membership_id",
            "agency_id",
            "client_id",
            "created_at",
        ),
    ),
)
EXCLUDED_COLUMNS: dict[str, tuple[str, ...]] = {
    "link_domains": ("challenge_digest",),
    "ingestion_sources": (
        "public_key",
        "notice_sha256",
    ),
    "collection_subjects": ("token_digest",),
    "collected_events": ("fingerprint",),
    "consent_records": ("notice_sha256",),
    "identity_merges": ("fingerprint",),
    "revenue_evidence": ("content_digest",),
    "ledger_receipts": (
        "input_digest",
        "previous_digest",
        "receipt_digest",
    ),
    "ledger_reconciliation_actions": (
        "issue_fingerprint",
        "request_fingerprint",
    ),
    "revenue_identity_bindings": ("request_fingerprint",),
    "payment_sources": ("public_key",),
    "integration_sources": ("public_key",),
    "whatsapp_messages": ("message_digest",),
    "attribution_conversions": (
        "slot_key",
        "conversion_key",
    ),
}


class TooLarge(Exception):
    """The export passed a bound of D5."""


class BuildFailed(Exception):
    """The ZIP failed its checks before storing."""


# Test hook: called after the checks and before the store transaction.
def _no_hook(export_id: UUID) -> None:
    return None


before_store: Callable[[UUID], None] = _no_hook


def seal_context(agency_id: UUID, export_id: UUID, part: int) -> SecretContext:
    """The envelope binding of one part: its agency, its export and its part number."""
    return SecretContext(agency_id, export_id, export_id, export_id, "agency_export", part)


def window_end(closure: AgencyClosure | None) -> datetime | None:
    return None if closure is None else closure.closes_at - WINDOW_CUTOFF


def latest(session: Session, agency_id: UUID, *, lock: bool = False) -> AgencyExport | None:
    query = (
        select(AgencyExport)
        .where(AgencyExport.agency_id == agency_id)
        .order_by(AgencyExport.requested_at.desc(), AgencyExport.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


# Revoke the agency's open export (pending or ready) and delete its parts at once; returns its
# ID, or None when no export was open. Used by a new request and by a cancellation.
def revoke_open(session: Session, agency_id: UUID) -> UUID | None:
    revoked = session.execute(
        update(AgencyExport)
        .where(AgencyExport.agency_id == agency_id, AgencyExport.status.in_(("pending", "ready")))
        .values(status="revoked", revoked_at=func.now())
        .returning(AgencyExport.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if revoked is not None:
        session.execute(
            delete(AgencyExportPart)
            .where(AgencyExportPart.export_id == revoked)
            .execution_options(synchronize_session=False)
        )
    return revoked


class AgencyExportService(ClosureService):
    """The export routes of an agency's active Owners; the request session commits."""

    def request(
        self,
        agency_id: UUID,
        *,
        password: str | None,
        user: User,
        auth_session: AuthSession,
        now: datetime | None = None,
    ) -> AgencyExport:
        agency, member = self._closure_owner(agency_id, write=True)
        if agency.status != "closing":
            raise ClosureRefused("agency_not_closing", 409)
        closure = open_closure(self.session, agency_id, lock=True)
        if closure is None:
            raise ClosureRefused("agency_not_closing", 409)
        if (now or now_utc()) >= closure.closes_at - WINDOW_CUTOFF:
            raise ClosureRefused("export_window_ended", 409)
        if self.settings.token_keys() is None:
            raise ClosureRefused("not_configured", 503)
        AuthService(self.session, self.settings).reauthenticate(user, auth_session, password)
        replaced = revoke_open(self.session, agency_id)
        if replaced is not None:
            self._audit(agency_id, "agency.export_revoked", "agency_export", replaced)
        item = AgencyExport(
            id=uuid4(),
            agency_id=agency_id,
            requested_by_membership_id=member.id,
            status="pending",
            requested_at=func.now(),
            expires_at=func.now() + LIFETIME,
        )
        self.session.add(item)
        self.session.flush()
        self._audit(agency_id, "agency.export_requested", "agency_export", item.id)
        self.session.refresh(item)
        return item

    # The latest export and the open closure, for an active Owner while active or closing.
    def read(
        self, agency_id: UUID
    ) -> tuple[Agency, AgencyClosure | None, AgencyExport | None, datetime]:
        agency, _ = self._closure_owner(agency_id, write=False)
        clock = self.session.scalar(select(func.now()))
        assert clock is not None
        return agency, open_closure(self.session, agency_id), latest(self.session, agency_id), clock

    # Resolve the Owner again, require a ready, unexpired export of a closing agency and count
    # the download; the caller streams the parts (open_stream) before the session commits.
    def open_download(self, agency_id: UUID) -> AgencyExport:
        agency, _ = self._closure_owner(agency_id, write=False)
        if agency.status != "closing":
            raise ClosureRefused("agency_not_closing", 409)
        item = latest(self.session, agency_id)
        if item is None:
            raise ClosureRefused("export_not_found", 404)
        if item.status == "pending":
            raise ClosureRefused("export_not_ready", 409)
        if self.settings.token_keys() is None:
            raise ClosureRefused("not_configured", 503)
        counted = self.session.execute(
            update(AgencyExport)
            .where(
                AgencyExport.id == item.id,
                AgencyExport.agency_id == agency_id,
                AgencyExport.status == "ready",
                AgencyExport.expires_at > func.now(),
            )
            .values(download_count=AgencyExport.download_count + 1, last_downloaded_at=func.now())
            .returning(AgencyExport.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if counted is None:
            raise ClosureRefused("export_gone", 410)
        return item


# One REPEATABLE READ READ ONLY snapshot that checks the export again and then yields its parts
# in order, each opened for exactly its agency, export and part number. The check runs before
# the answer starts; a revocation committed afterwards does not cut the stream short.
def open_stream(engine: Engine, keyring: LocalKeyring, item: AgencyExport) -> Iterator[bytes]:
    connection = engine.connect().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True
    )
    try:
        ready = connection.execute(
            select(AgencyExport.part_count).where(
                AgencyExport.id == item.id,
                AgencyExport.agency_id == item.agency_id,
                AgencyExport.status == "ready",
            )
        ).scalar_one_or_none()
        parts = list(
            connection.execute(
                select(AgencyExportPart.part)
                .where(AgencyExportPart.export_id == item.id)
                .order_by(AgencyExportPart.part)
            ).scalars()
        )
        if ready is None or parts != list(range(1, ready + 1)):
            raise ClosureRefused("export_gone", 410)
    except BaseException:
        connection.close()
        raise

    def stream() -> Iterator[bytes]:
        try:
            for number in parts:
                row = connection.execute(
                    select(AgencyExportPart).where(
                        AgencyExportPart.export_id == item.id, AgencyExportPart.part == number
                    )
                ).one()
                sealed = SealedSecret(
                    row.kek_id,
                    row.wrap_nonce,
                    row.wrapped_dek,
                    row.nonce,
                    row.ciphertext,
                    row.alg,
                    row.aad_version,
                )
                try:
                    yield open_bytes(keyring, sealed, seal_context(item.agency_id, item.id, number))
                except (InvalidTag, KeyError, ValueError):
                    logger.warning("agency_export_unreadable")
                    return
        finally:
            connection.close()

    return stream()


def _value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _value(item) for key, item in value.items()}
    return value


def _line(row: Any, columns: tuple[str, ...]) -> bytes:
    record = {name: _value(row[index]) for index, name in enumerate(columns)}
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def _size(handle: IO[bytes]) -> int:
    return os.fstat(handle.fileno()).st_size


# Rows of one catalog table of one client, by primary key, from a server-side cursor.
def _rows(connection: Any, table_name: str, columns: tuple[str, ...], client_id: UUID) -> Any:
    table = Base.metadata.tables[table_name]
    scope = table.c.id if table_name == "client_workspaces" else table.c.client_id
    query = (
        select(*(table.c[name] for name in columns))
        .where(scope == client_id)
        .order_by(*table.primary_key.columns)
    )
    return connection.execution_options(stream_results=True, yield_per=ROW_BATCH).execute(query)


def _schema_version(engine: Engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


# Write the ZIP of every client of the agency into `handle`; returns the manifest's file list
# and its bytes. Raises TooLarge as soon as a bound of D5 is passed.
def write_zip(
    engine: Engine, handle: IO[bytes], agency_id: UUID, export_id: UUID
) -> tuple[list[dict[str, Any]], bytes]:
    with Session(engine) as session:
        clients = list(
            session.scalars(
                select(ClientWorkspace.id)
                .where(ClientWorkspace.agency_id == agency_id)
                .order_by(ClientWorkspace.id)
            )
        )
    files: list[dict[str, Any]] = []
    total = 0
    with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for client_id in clients:
            with engine.connect() as raw:
                connection = raw.execution_options(
                    isolation_level="REPEATABLE READ", postgresql_readonly=True
                )
                with connection.begin():
                    for table_name, columns in CATALOG:
                        path = f"clients/{client_id}/{table_name}.jsonl"
                        digest, rows, written = hashlib.sha256(), 0, 0
                        with archive.open(path, "w", force_zip64=True) as member:
                            for row in _rows(connection, table_name, columns, client_id):
                                line = _line(row, columns)
                                member.write(line)
                                digest.update(line)
                                rows += 1
                                written += len(line)
                                total += 1
                                if total > MAX_ROWS:
                                    raise TooLarge()
                                if rows % ROW_BATCH == 0 and _size(handle) > MAX_BYTES:
                                    raise TooLarge()
                        if _size(handle) > MAX_BYTES:
                            raise TooLarge()
                        files.append(
                            {
                                "path": path,
                                "rows": rows,
                                "bytes": written,
                                "sha256": digest.hexdigest(),
                            }
                        )
        manifest = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "schema_version": _schema_version(engine),
            "agency_id": str(agency_id),
            "export_id": str(export_id),
            "created_at": now_utc().isoformat(),
            "total_rows": total,
            "files": files,
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode() + b"\n"
        archive.writestr(MANIFEST, manifest_bytes)
    if _size(handle) > MAX_BYTES:
        raise TooLarge()
    return files, manifest_bytes


# The checks before storing (D5): the ZIP opens, no member is damaged, the members are exactly
# the manifest's files and the manifest, and every member's rows and SHA-256 match it.
def check_zip(handle: IO[bytes], files: list[dict[str, Any]], manifest_bytes: bytes) -> int:
    handle.seek(0)
    size = _size(handle)
    if not 0 < size <= MAX_BYTES:
        raise BuildFailed()
    with zipfile.ZipFile(handle) as archive:
        if archive.testzip() is not None:
            raise BuildFailed()
        expected = sorted([item["path"] for item in files] + [MANIFEST])
        if sorted(archive.namelist()) != expected or archive.read(MANIFEST) != manifest_bytes:
            raise BuildFailed()
        manifest = json.loads(manifest_bytes)
        if manifest["files"] != files or manifest["total_rows"] > MAX_ROWS:
            raise BuildFailed()
        for item in files:
            digest, rows = hashlib.sha256(), 0
            with archive.open(item["path"]) as member:
                for chunk in iter(lambda member=member: member.read(1024 * 1024), b""):
                    digest.update(chunk)
                    rows += chunk.count(b"\n")
            if (digest.hexdigest(), rows) != (item["sha256"], item["rows"]):
                raise BuildFailed()
    return size


def _fail(engine: Engine, export_id: UUID, code: str) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(AgencyExport)
            .where(AgencyExport.id == export_id, AgencyExport.status == "pending")
            .values(status="failed", error_code=code)
            .execution_options(synchronize_session=False)
        )


# The store transaction: under the agency row lock, only a pending export of a closing agency
# becomes ready, with its sealed parts. Returns the outcome code.
def _store(
    engine: Engine,
    keyring: LocalKeyring,
    handle: IO[bytes],
    agency_id: UUID,
    export_id: UUID,
    files: list[dict[str, Any]],
    manifest_bytes: bytes,
    size: int,
) -> str:
    with Session(engine) as session, session.begin():
        status = session.scalar(
            select(Agency.status).where(Agency.id == agency_id).with_for_update()
        )
        if status != "closing":
            session.execute(
                update(AgencyExport)
                .where(AgencyExport.id == export_id, AgencyExport.status == "pending")
                .values(status="failed", error_code="closure_completed")
                .execution_options(synchronize_session=False)
            )
            return "discarded"
        pending = session.scalar(
            select(AgencyExport.id)
            .where(AgencyExport.id == export_id, AgencyExport.status == "pending")
            .with_for_update()
        )
        if pending is None:
            return "superseded"
        handle.seek(0)
        number = 0
        while chunk := handle.read(PART_BYTES):
            number += 1
            sealed = seal_bytes(keyring, chunk, seal_context(agency_id, export_id, number))
            session.execute(
                insert(AgencyExportPart).values(
                    export_id=export_id,
                    part=number,
                    agency_id=agency_id,
                    kek_id=sealed.kek_id,
                    wrap_nonce=sealed.wrap_nonce,
                    wrapped_dek=sealed.wrapped_dek,
                    nonce=sealed.nonce,
                    ciphertext=sealed.ciphertext,
                    alg=sealed.algorithm,
                    aad_version=sealed.aad_version,
                )
            )
        session.execute(
            update(AgencyExport)
            .where(AgencyExport.id == export_id)
            .values(
                status="ready",
                ready_at=func.now(),
                part_count=number,
                byte_size=size,
                row_count=sum(item["rows"] for item in files),
                row_counts={item["path"]: item["rows"] for item in files},
                manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            )
            .execution_options(synchronize_session=False)
        )
        return "built"


# Build one pending export; returns its outcome: built, failed, discarded or superseded.
def build_export(engine: Engine, keyring: LocalKeyring, export_id: UUID, agency_id: UUID) -> str:
    with Session(engine) as session, session.begin():
        status = session.scalar(select(Agency.status).where(Agency.id == agency_id))
        if status != "closing":
            session.execute(
                update(AgencyExport)
                .where(AgencyExport.id == export_id, AgencyExport.status == "pending")
                .values(status="failed", error_code="closure_completed")
                .execution_options(synchronize_session=False)
            )
            return "discarded"
    with tempfile.TemporaryFile() as handle:
        try:
            files, manifest_bytes = write_zip(engine, handle, agency_id, export_id)
            size = check_zip(handle, files, manifest_bytes)
        except TooLarge:
            _fail(engine, export_id, "export_too_large")
            return "failed"
        before_store(export_id)
        return _store(engine, keyring, handle, agency_id, export_id, files, manifest_bytes, size)


def build_pending(engine: Engine, settings: Settings, *, limit: int = 5) -> dict[str, int]:
    """One bounded pass over pending exports, oldest first; counts only."""
    counts = dict.fromkeys(("built", "failed", "discarded", "superseded", "skipped"), 0)
    with Session(engine) as session:
        pending = list(
            session.execute(
                select(AgencyExport.id, AgencyExport.agency_id)
                .where(AgencyExport.status == "pending")
                .order_by(AgencyExport.requested_at, AgencyExport.id)
                .limit(limit)
            )
        )
    if not pending:
        return counts
    keyring = settings.token_keys()
    if keyring is None:
        counts["skipped"] = len(pending)
        return counts
    for export_id, agency_id in pending:
        with engine.connect() as lock:
            key = client_lock_key(export_id)
            held = lock.execute(select(func.pg_try_advisory_lock(LOCK_NAMESPACE, key))).scalar_one()
            lock.commit()
            if not held:
                counts["skipped"] += 1
                continue
            try:
                outcome = build_export(engine, keyring, export_id, agency_id)
            except (SQLAlchemyError, OSError, BuildFailed, zipfile.BadZipFile):
                logger.warning("agency_export_failed")
                _fail(engine, export_id, "build_failed")
                outcome = "failed"
            finally:
                lock.execute(select(func.pg_advisory_unlock(LOCK_NAMESPACE, key)))
                lock.commit()
        counts[outcome] += 1
    return counts
