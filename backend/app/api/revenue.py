"""Client revenue routes (specification 015, D-067 decisions D8 to D11).

015-A: readers with finance:read (browser users with financial access, or read keys with their
financial grant) read the client's ledger, derived on each read by the 007-A calculation over
the stored evidence. Verified and declared amounts are kept apart, and amounts in different
currencies are never added. No answer carries a delivery ID, a content digest, an actor, an
intake ID or another client's data.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import ReaderDep, SessionDep
from app.api.schemas import Output
from app.services.access import resolve_scope
from app.services.revenue import client_ledger, revenue_view

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
