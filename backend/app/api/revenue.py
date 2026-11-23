"""Client revenue routes (specification 015, D-067 decisions D8 to D11).

015-A: readers with finance:read (browser users with financial access, or read keys with their
financial grant) read the client's ledger, derived on each read by the 007-A calculation over
the stored evidence. Verified and declared amounts are kept apart, and amounts in different
currencies are never added. No answer carries a delivery ID, a content digest, an actor, an
intake ID or another client's data.

007-B (D-075 J8, J9): finance readers page through the stored movement journal and the
reconciliation queue; Owner and Admin sessions acknowledge or reopen an issue, which changes
no evidence or amount. Reads fail closed while the persisted projection is behind.

015-C: Owner and Admin sessions preview and commit transaction CSV files and declare single
transactions with a reason, each commit and declaration audited. Declarations are unverified
manual_declaration evidence; files are never kept.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ConfigDict, Field

from app.advertising.currencies import decimal_text
from app.api.dependencies import BrowserDep, RawBody, ReaderDep, SessionDep
from app.api.schemas import Input, Output
from app.declarations import ParsedFile
from app.services.access import resolve_scope
from app.services.declarations import DeclarationService
from app.services.ledger_review import ReconciliationService, reconciliation_view
from app.services.ledger_store import movements_page, require_current
from app.services.revenue import client_ledger, load_rows, revenue_view

router = APIRouter(tags=["Revenue"])


class VerifiedTotal(Output):
    currency: str
    captured: str
    refunded: str
    charged_back: str
    reversed: str
    corrected: str
    net: str


class LedgerEntry(Output):
    operation_id: str
    kind: str
    amount: str
    effective_at: datetime


class LedgerTransaction(Output):
    operation_id: str
    source_account_id: str
    currency: str
    effective_at: datetime
    net: str
    entries: list[LedgerEntry]


class VerifiedRevenue(Output):
    totals: list[VerifiedTotal]
    transactions: list[LedgerTransaction]


class DeclaredTotal(Output):
    currency: str
    sales: str
    refunds: str


class DeclaredItem(Output):
    operation_id: str
    kind: str
    amount: str
    currency: str
    effective_at: datetime
    parent_operation_id: str | None
    intake: str | None
    reason: str | None
    source_reference: str | None


class DeclaredRevenue(Output):
    totals: list[DeclaredTotal]
    items: list[DeclaredItem]


class PendingAdjustment(Output):
    operation_id: str
    kind: str
    parent_operation_id: str
    amount: str
    currency: str
    effective_at: datetime
    reason: str | None


class ReconciliationEntry(Output):
    operation_id: str
    reason: str


class RevenueReport(Output):
    verified: VerifiedRevenue
    declared: DeclaredRevenue
    pending: list[PendingAdjustment]
    reconciliation: list[ReconciliationEntry]
    truncated: bool


# The client's ledger (D11): verified totals and transactions, declared (unverified) items and
# totals, pending adjustments and reconciliation items, newest first and bounded.
@router.get("/agencies/{agency_id}/clients/{client_id}/revenue", response_model=RevenueReport)
def read_revenue(
    agency_id: UUID, client_id: UUID, session: SessionDep, principal: ReaderDep
) -> RevenueReport:
    resolve_scope(session, principal, agency_id, client_id, "finance:read")
    ledger = client_ledger(session, agency_id, client_id)
    return RevenueReport.model_validate(revenue_view(ledger, agency_id, client_id))


# --- 015-C: CSV imports and manual declarations (D8 to D10) -------------------------------

ImportId = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
CSV_BODY = {
    "required": True,
    "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
}


class RowStatus(Output):
    row: int
    status: Literal["valid", "rejected"]
    errors: list[str]


class ImportPreview(Output):
    import_id: str
    total_rows: int
    valid_rows: int
    rejected_rows: int
    rows: list[RowStatus]


class ImportRecord(Output):
    id: UUID
    import_id: str
    total_rows: int
    stored_rows: int
    duplicate_rows: int
    rejected_rows: int
    committed_at: datetime


class ImportCommit(Output):
    import_: ImportRecord = Field(alias="import", serialization_alias="import")
    rows: list[RowStatus] | None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DeclarationInput(Input):
    operation_id: Annotated[str, Field(min_length=1, max_length=128)]
    kind: Literal["sale", "refund"]
    amount: Annotated[str, Field(min_length=1, max_length=40)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    effective_at: Annotated[str, Field(min_length=10, max_length=40)]
    parent_operation_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    source_reference: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    reason: Annotated[str, Field(min_length=1, max_length=1100)] | None = None


class DeclarationView(Output):
    operation_id: str
    kind: str
    amount: str
    currency: str
    effective_at: datetime
    parent_operation_id: str | None
    source_reference: str | None
    reason: str | None


class DeclarationResult(Output):
    status: Literal["stored", "duplicate"]
    declaration: DeclarationView


def _rows(parsed: ParsedFile) -> list[RowStatus]:
    return [
        RowStatus(row=row.row, status=row.status, errors=list(row.errors)) for row in parsed.rows
    ]


def _record(record) -> ImportRecord:
    return ImportRecord(
        id=record.id,
        import_id=record.file_digest,
        total_rows=record.total_rows,
        stored_rows=record.stored_rows,
        duplicate_rows=record.duplicate_rows,
        rejected_rows=record.rejected_rows,
        committed_at=record.committed_at,
    )


def _declarations(session, browser) -> DeclarationService:
    return DeclarationService(session, browser.user.id)


IMPORTS = "/agencies/{agency_id}/clients/{client_id}/revenue-imports"


# Validate a transaction CSV file (at most 2 MiB and 10,000 rows) and report each row; nothing
# is stored. The import ID is the SHA-256 of the file.
@router.post(
    IMPORTS + "/preview", response_model=ImportPreview, openapi_extra={"requestBody": CSV_BODY}
)
def preview_import(
    agency_id: UUID, client_id: UUID, session: SessionDep, browser: BrowserDep, body: RawBody
) -> ImportPreview:
    parsed = _declarations(session, browser).preview(agency_id, client_id, body)
    return ImportPreview(
        import_id=parsed.digest,
        total_rows=len(parsed.rows),
        valid_rows=len(parsed.valid),
        rejected_rows=len(parsed.rows) - len(parsed.valid),
        rows=_rows(parsed),
    )


# Store the valid rows of the same file once, as unverified declarations; a repeated commit of
# the same import ID returns the existing record with 200 and stores nothing.
@router.post(
    IMPORTS + "/{import_id}",
    status_code=201,
    response_model=ImportCommit,
    response_model_by_alias=True,
    responses={200: {"model": ImportCommit, "description": "Repeated commit; nothing stored."}},
    openapi_extra={"requestBody": CSV_BODY},
)
def commit_import(
    agency_id: UUID,
    client_id: UUID,
    import_id: ImportId,
    response: Response,
    session: SessionDep,
    browser: BrowserDep,
    body: RawBody,
) -> ImportCommit:
    result = _declarations(session, browser).commit(agency_id, client_id, import_id, body)
    if not result.created:
        response.status_code = 200
    rows = _rows(result.parsed) if result.parsed is not None else None
    return ImportCommit(import_=_record(result.record), rows=rows)


# Declare one sale or refund with a reason; it stays unverified (D9).
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/revenue-declarations",
    status_code=201,
    response_model=DeclarationResult,
)
def declare_revenue(
    agency_id: UUID,
    client_id: UUID,
    data: DeclarationInput,
    session: SessionDep,
    browser: BrowserDep,
) -> DeclarationResult:
    item, status = _declarations(session, browser).declare(agency_id, client_id, data.model_dump())
    return DeclarationResult(
        status=status,
        declaration=DeclarationView(
            operation_id=item.operation_id,
            kind=item.kind.value,
            amount=decimal_text(item.amount.minor, item.amount.currency.exponent),
            currency=item.amount.currency.code,
            effective_at=item.effective_at,
            parent_operation_id=item.parent_operation_id,
            source_reference=item.source_reference,
            reason=item.reason,
        ),
    )


# --- 007-B: persisted movements and the reconciliation queue (D-075 J8, J9) ---------------


class ReviewInput(Input):
    operation_id: UUID
    expected_financial_revision: Annotated[int, Field(ge=0)]
    action: Literal["acknowledge", "reopen"]
    reason_code: Literal[
        "provider_contacted",
        "awaiting_evidence",
        "confirmed_duplicate",
        "reviewed_no_action",
        "new_information",
    ]


# The stored movement journal of the published generation, in keyset pages bound to it.
@router.get("/agencies/{agency_id}/clients/{client_id}/revenue/movements")
def read_revenue_movements(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    after: Annotated[int, Query(ge=0)] = 0,
    generation: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    resolve_scope(session, principal, agency_id, client_id, "finance:read")
    rows = load_rows(session, agency_id, client_id)
    state = require_current(session, agency_id, client_id, rows)
    body = movements_page(session, state, after=after, generation=generation, limit=limit)
    resolve_scope(session, principal, agency_id, client_id, "finance:read")
    return JSONResponse(jsonable_encoder(body), headers={"Cache-Control": "no-store"})


# Open reconciliation, pending and held items with their latest review (J9).
@router.get("/agencies/{agency_id}/clients/{client_id}/revenue/reconciliation")
def read_revenue_reconciliation(
    agency_id: UUID, client_id: UUID, session: SessionDep, principal: ReaderDep
) -> JSONResponse:
    resolve_scope(session, principal, agency_id, client_id, "finance:read")
    body = reconciliation_view(session, agency_id, client_id)
    resolve_scope(session, principal, agency_id, client_id, "finance:read")
    return JSONResponse(jsonable_encoder(body), headers={"Cache-Control": "no-store"})


# Owner/Admin acknowledge or reopen of one issue; idempotent by operation ID, audited.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/revenue/reconciliation/{issue_id}/actions",
    status_code=201,
)
def review_revenue_issue(
    agency_id: UUID,
    client_id: UUID,
    issue_id: UUID,
    data: ReviewInput,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = ReconciliationService(session, browser.user.id).review(
        agency_id, client_id, issue_id, **data.model_dump()
    )
    return JSONResponse(result, status)
