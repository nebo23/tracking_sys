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

from fastapi import APIRouter, BackgroundTasks, Path, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ConfigDict, Field

from app.advertising.currencies import decimal_text
from app.api.dependencies import BrowserDep, IngestDep, RawBody, ReaderDep, SessionDep
from app.api.schemas import Input, Output
from app.declarations import ParsedFile
from app.services.access import resolve_scope
from app.services.auth import enforce_rate_limit
from app.services.collection import lock_client
from app.services.declarations import DeclarationService
from app.services.ledger_review import ReconciliationService, reconciliation_view
from app.services.ledger_store import is_behind, movements_page, published_state, run_catch_up
from app.services.revenue import client_ledger, revenue_view
from app.services.revenue_identity import AssociationAdmin, AssociationRequest, associate

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


# A projection left behind by a deferred commit catches up after the response, outside the
# agency lock and in its own transactions (D-076, R0607-11); the request has committed by then.
def schedule_catch_up(
    request: Request, background: BackgroundTasks, session, agency_id: UUID, client_id: UUID
) -> None:
    if is_behind(session, agency_id, client_id):
        background.add_task(run_catch_up, request.app.state.engine, agency_id, client_id)


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
    request: Request,
    response: Response,
    background: BackgroundTasks,
    session: SessionDep,
    browser: BrowserDep,
    body: RawBody,
) -> ImportCommit:
    result = _declarations(session, browser).commit(agency_id, client_id, import_id, body)
    if not result.created:
        response.status_code = 200
    schedule_catch_up(request, background, session, agency_id, client_id)
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
    request: Request,
    background: BackgroundTasks,
    session: SessionDep,
    browser: BrowserDep,
) -> DeclarationResult:
    item, status = _declarations(session, browser).declare(agency_id, client_id, data.model_dump())
    schedule_catch_up(request, background, session, agency_id, client_id)
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
    state = published_state(session, agency_id, client_id)
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


# --- 007-C: sale-to-person association (D-075 J10) ----------------------------------------


class AssociationInput(Input):
    request_id: UUID
    source_account_id: Annotated[str, Field(min_length=1, max_length=256)]
    sale_operation_id: Annotated[str, Field(min_length=1, max_length=256)]
    assertion_id: UUID
    expected_revision: Annotated[int | None, Field(ge=0)] = None


class DetachInput(Input):
    operation_id: UUID
    expected_revision: Annotated[int, Field(ge=1)]
    reason_code: Literal["mistaken_association", "customer_request", "data_correction"]


ASSOCIATION_STATUS = {
    "accepted": 201,
    "duplicate": 200,
    "conflict": 409,
    "revision_conflict": 409,
    "proof_invalid": 422,
}


# A trusted association assertion from a client-granted ingest key. The answer is generic: it
# never says whether the sale exists, who holds it or whether it was linked.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/revenue/identity-associations", status_code=201
)
def create_revenue_association(
    agency_id: UUID,
    client_id: UUID,
    data: AssociationInput,
    request: Request,
    session: SessionDep,
    principal: IngestDep,
) -> JSONResponse:
    settings = request.app.state.settings
    enforce_rate_limit(
        request.app.state.security_engine,
        settings,
        "ingest-key",
        str(principal.identifier),
        limit=settings.ingest_trusted_per_minute,
        period=60,
    )
    resolve_scope(session, principal, agency_id, client_id, "events:write")

    def lock() -> datetime:
        now = lock_client(session, client_id)
        resolve_scope(session, principal, agency_id, client_id, "events:write")
        return now

    status, http = associate(
        session,
        agency_id,
        client_id,
        principal.identifier,
        AssociationRequest(**data.model_dump()),
        lock=lock,
    )
    if status in {"accepted", "duplicate", "conflict"}:
        return JSONResponse({"status": status, "request_id": str(data.request_id)}, http)
    return JSONResponse({"status": "rejected", "reason": status}, http)


# Owner/Admin detachment of a mistaken association; audited, idempotent and versioned.
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/revenue/identity-associations/{association_id}/detach",
    status_code=201,
)
def detach_revenue_association(
    agency_id: UUID,
    client_id: UUID,
    association_id: UUID,
    data: DetachInput,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = AssociationAdmin(session, browser.user.id).detach(
        agency_id, client_id, association_id, **data.model_dump()
    )
    return JSONResponse(result, status)
