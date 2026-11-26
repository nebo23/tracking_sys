"""Reconciliation queue and audited review actions (specification 007-B, D-075 decision J9).

Finance readers see every open reconciliation item, pending adjustment and held Paymob refund
of the current calculation, each with a stable issue ID, the evidence it rests on and the
latest review decision. An Owner or Admin may acknowledge or reopen an issue: the action is
idempotent by operation ID, bound to the financial revision the reviewer saw (a stale revision
is refused) and audited. A review never accepts contradictory evidence, forges a parent, erases
a receipt, turns a manual declaration into verified revenue or removes the issue from the
unresolved counts: it records that someone looked, nothing more.
"""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LedgerReconciliationAction
from app.services.ledger_store import LedgerConflict, issues
from app.services.revenue import client_ledger, lock_revenue
from app.services.tenancy import TenancyService

REASON_CODES = (
    "provider_contacted",
    "awaiting_evidence",
    "confirmed_duplicate",
    "reviewed_no_action",
    "new_information",
)


def _latest(session: Session, client_id: UUID) -> dict[UUID, LedgerReconciliationAction]:
    latest: dict[UUID, LedgerReconciliationAction] = {}
    for row in session.scalars(
        select(LedgerReconciliationAction)
        .where(LedgerReconciliationAction.client_id == client_id)
        .order_by(LedgerReconciliationAction.created_at, LedgerReconciliationAction.id)
    ):
        latest[row.issue_id] = row
    return latest


def reconciliation_view(session: Session, agency_id: UUID, client_id: UUID) -> dict[str, Any]:
    """The open issues of the current calculation (the caller authorized finance:read)."""
    ledger = client_ledger(session, agency_id, client_id)
    found = issues(ledger, client_id)
    latest = _latest(session, client_id)
    items = []
    for issue in found:
        review = latest.get(issue.issue_id)
        items.append(
            {
                "issue_id": str(issue.issue_id),
                "kind": issue.kind,
                "reason": issue.reason,
                "source_account_id": issue.source_account_id,
                "operation_id": issue.operation_id,
                "evidence_ids": [str(item) for item in issue.evidence_ids],
                "unresolved": True,
                "review": None
                if review is None
                else {
                    "action": review.action,
                    "reason_code": review.reason_code,
                    "reviewed_at": review.created_at,
                    "issue_version": review.issue_version,
                    # A review of earlier evidence does not cover evidence received since.
                    "current": review.issue_fingerprint == issue.fingerprint,
                },
            }
        )
    return {
        "generation": ledger.generation,
        "financial_revision": ledger.financial_revision,
        "unresolved_count": len(found),
        "issues": items,
    }


class ReconciliationService(TenancyService):
    def review(
        self,
        agency_id: UUID,
        client_id: UUID,
        issue_id: UUID,
        *,
        operation_id: UUID,
        expected_financial_revision: int,
        action: str,
        reason_code: str,
    ) -> tuple[dict[str, Any], int]:
        if action not in {"acknowledge", "reopen"} or reason_code not in REASON_CODES:
            raise ValueError("Unknown action or reason code.")
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        # The review time is the clock read under the revenue lock, so serialized reviews are
        # ordered as they were decided, not by transaction start (R0607-17).
        decided_at = lock_revenue(self.session, client_id)
        fingerprint = hashlib.sha256(
            json.dumps(
                [str(issue_id), expected_financial_revision, action, reason_code, str(actor.id)]
            ).encode()
        ).hexdigest()
        recorded = self.session.scalar(
            select(LedgerReconciliationAction).where(
                LedgerReconciliationAction.client_id == client_id,
                LedgerReconciliationAction.operation_id == operation_id,
            )
        )
        if recorded is not None:
            if recorded.request_fingerprint != fingerprint:
                raise LedgerConflict("operation_conflict")
            return self._result(recorded), 200
        ledger = client_ledger(self.session, agency_id, client_id)
        if ledger.financial_revision != expected_financial_revision:
            raise LedgerConflict("financial_revision_changed")
        issue = next(
            (item for item in issues(ledger, client_id) if item.issue_id == issue_id), None
        )
        if issue is None:
            raise LedgerConflict("issue_not_found", 404)
        row = LedgerReconciliationAction(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            operation_id=operation_id,
            issue_id=issue_id,
            issue_fingerprint=issue.fingerprint,
            issue_version=expected_financial_revision,
            evidence_ids=list(issue.evidence_ids),
            action=action,
            reason_code=reason_code,
            actor_membership_id=actor.id,
            request_fingerprint=fingerprint,
            created_at=decided_at,
        )
        self.session.add(row)
        self.session.flush()
        self._audit(
            agency_id, "revenue.reconciliation_reviewed", "revenue_issue", issue_id, client_id
        )
        self.session.refresh(row)
        return self._result(row), 201

    @staticmethod
    def _result(row: LedgerReconciliationAction) -> dict[str, Any]:
        return {
            "issue_id": str(row.issue_id),
            "action": row.action,
            "reason_code": row.reason_code,
            "issue_version": row.issue_version,
            "reviewed_at": row.created_at.isoformat(),
        }
