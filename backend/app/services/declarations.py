"""Transaction CSV imports and manual declarations (specification 015-C, D-067 D8 to D10).

Owner and Admin sessions preview a transaction CSV file (validated, nothing stored), commit it
once by its import ID (the SHA-256 of the file) and declare single transactions with a reason.
Every stored row is unverified manual_declaration evidence (007-A A1) appended under the
client's revenue lock; it never enters verified totals and 014-B never enqueues it. The file is
never kept: an import record holds only its digest and counts, and tracking_lifecycle deletes it
13 months after the commit, while the evidence stays (D14). Each commit and declaration has an
audit event in the caller's transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.declarations import (
    SOURCE_ACCOUNT,
    Declaration,
    ParsedFile,
    file_digest,
    parse_csv,
    validate_declaration,
)
from app.ledger import Evidence, EvidenceClass
from app.models import RevenueEvidence, RevenueImport
from app.services.revenue import append_evidence, content_digest, lock_revenue
from app.services.tenancy import TenancyService


class DeclarationRefused(ValueError):
    """A refused file or declaration with a closed public code and HTTP status."""

    def __init__(self, code: str, status: int = 422) -> None:
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class CommitResult:
    record: RevenueImport
    parsed: ParsedFile | None  # None for a repeated commit, which validates nothing again
    created: bool


def _evidence(
    item: Declaration, agency_id: UUID, client_id: UUID, actor: UUID, received: datetime
) -> Evidence:
    return Evidence(
        delivery_id=item.delivery_id,
        agency_id=agency_id,
        client_id=client_id,
        source_account_id=SOURCE_ACCOUNT,
        operation_id=item.operation_id,
        kind=item.kind,
        classification=EvidenceClass.MANUAL_DECLARATION,
        amount=item.amount,
        effective_at=item.effective_at,
        received_at=received,
        parent_operation_id=item.parent_operation_id,
        reason=item.reason,
        actor=str(actor),
        source_reference=item.source_reference,
    )


class DeclarationService(TenancyService):
    def _now(self) -> datetime:
        return self.session.scalar(select(func.clock_timestamp()))

    def _parse(self, body: bytes, now: datetime) -> ParsedFile:
        from app.declarations import FileRefused

        try:
            return parse_csv(body, now)
        except FileRefused as refused:
            raise DeclarationRefused(refused.code) from refused

    # Validate a file and return the row results; nothing is stored (D8).
    def preview(self, agency_id: UUID, client_id: UUID, body: bytes) -> ParsedFile:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        return self._parse(body, self._now())

    # Store the valid rows of a file once (D8). A repeated commit of the same file for the same
    # client returns its import record and stores nothing.
    def commit(self, agency_id: UUID, client_id: UUID, import_id: str, body: bytes) -> CommitResult:
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        if file_digest(body) != import_id:
            raise DeclarationRefused("import_mismatch")
        received = lock_revenue(self.session, client_id)
        existing = self.session.scalar(
            select(RevenueImport).where(
                RevenueImport.client_id == client_id, RevenueImport.file_digest == import_id
            )
        )
        if existing is not None:
            return CommitResult(existing, None, False)
        parsed = self._parse(body, received)
        record_id = uuid4()
        stored = duplicate = 0
        for item in parsed.valid:
            outcome = append_evidence(
                self.session,
                _evidence(item, agency_id, client_id, self.actor_user_id, received),
                "csv_import",
                record_id,
            )
            stored += outcome == "stored"
            duplicate += outcome == "duplicate"
        self.session.execute(
            insert(RevenueImport)
            .values(
                id=record_id,
                agency_id=agency_id,
                client_id=client_id,
                file_digest=import_id,
                total_rows=len(parsed.rows),
                stored_rows=stored,
                duplicate_rows=duplicate,
                rejected_rows=len(parsed.rows) - len(parsed.valid),
                committed_by_membership_id=actor.id,
                committed_at=received,
            )
            .on_conflict_do_nothing(constraint="uq_revenue_imports_file")
        )
        record = self.session.get(RevenueImport, record_id)
        if record is None:  # a concurrent commit of the same file won; nothing is stored twice
            raise DeclarationRefused("state_conflict", 409)
        self._audit(agency_id, "revenue_import.committed", "revenue_import", record_id, client_id)
        return CommitResult(record, parsed, True)

    # Declare one transaction with a reason (D9). Returns the declaration and "stored", or
    # "duplicate" when the same declaration exists already.
    def declare(
        self, agency_id: UUID, client_id: UUID, values: dict[str, str | None]
    ) -> tuple[Declaration, Literal["stored", "duplicate"]]:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        received = lock_revenue(self.session, client_id)
        outcome = validate_declaration(values, received, reason_required=True)
        if not isinstance(outcome, Declaration):
            raise DeclarationRefused(outcome[0])
        item = _evidence(outcome, agency_id, client_id, self.actor_user_id, received)
        result = append_evidence(self.session, item, "manual_entry", None)
        row = self.session.scalar(
            select(RevenueEvidence.id).where(
                RevenueEvidence.client_id == client_id,
                RevenueEvidence.source_account_id == SOURCE_ACCOUNT,
                RevenueEvidence.delivery_id == item.delivery_id,
                RevenueEvidence.content_digest == content_digest(item),
            )
        )
        self._audit(agency_id, "revenue.declared", "revenue_evidence", row, client_id)
        return outcome, result
