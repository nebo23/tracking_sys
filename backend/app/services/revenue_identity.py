"""Sale-to-person association and financial unlinking (specification 007-C, D-075 J10, J5, J6).

A trusted association assertion from a client-granted ingest key names one sale by its full
transaction key (source account and sale operation; an operation ID alone is never enough) and
a 006 identity assertion that the same live credential submitted. It links only while that
assertion still has an unambiguous, open owned segment, identity_link and attribution are both
currently granted on its collection subject, and the sale is verified in the current ledger;
an absent sale stays pending. Nothing is ever matched on amount, time, campaign, browser
purchase references or a payment ID alone. A conflicting owner never transfers a sale: the new
revision is ambiguous and needs review. Every change appends a revision; no financial evidence
or amount is touched. The acknowledgement is generic and reveals no person or match history.

Lock order: the client privacy lock, then the client revenue lock (as the joint design orders
them); identity removal paths hold only the privacy lock and never take the revenue lock.

F1 (J6): withdrawal of identity_link or attribution, erasure and expiry clear every identifying
pointer and the retry material of every revision that names the person or its collection
subject, in the transaction that removes the identity evidence.

Customer qualification (D13, J5): a person is a customer while a current association names a
verified capture in the ledger, rechecked on every read (segment, consent and ledger); a full
refund changes money, not the historical purchase fact.
"""

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.identity.segments import ConsentMark, current_period, grant_periods
from app.models import (
    CollectionSubject,
    IdentityAssertion,
    IdentityLink,
    LedgerTransaction,
    RevenueIdentityBinding,
    StoredConsentRecord,
)
from app.privacy.consent import ConsentState, Purpose
from app.services.tenancy import AccessDenied, TenancyService

DETACH_REASONS = ("mistaken_association", "customer_request", "data_correction")
F1_REASONS = {"withdrawn": "withdrawn", "erased": "erased", "expired": "expired"}


class AssociationError(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


def association_id(client_id: UUID, source_account_id: str, sale_operation_id: str) -> UUID:
    raw = json.dumps(["association:v1", str(client_id), source_account_id, sale_operation_id])
    return UUID(hashlib.sha256(raw.encode()).hexdigest()[:32])


def _current(session: Session, client_id: UUID, association: UUID) -> RevenueIdentityBinding | None:
    return session.scalar(
        select(RevenueIdentityBinding)
        .where(
            RevenueIdentityBinding.client_id == client_id,
            RevenueIdentityBinding.association_id == association,
        )
        .order_by(RevenueIdentityBinding.revision.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _verified_sale(
    session: Session, agency_id: UUID, client_id: UUID, source_account_id: str, sale: str
) -> bool:
    """Whether the current published ledger holds the sale as a verified transaction."""
    from app.services.ledger_store import published_state

    state = published_state(session, agency_id, client_id)
    if state is None:
        return False
    return (
        session.scalar(
            select(LedgerTransaction.id).where(
                LedgerTransaction.client_id == client_id,
                LedgerTransaction.generation == state.generation,
                LedgerTransaction.source_account_id == source_account_id,
                LedgerTransaction.operation_id == sale,
            )
        )
        is not None
    )


def _segment_ok(
    session: Session, assertion: IdentityAssertion, now: datetime
) -> IdentityLink | None:
    """The assertion's owned link while it is unambiguous and consented (J10).

    A segment that ended normally, for example when another person signed in on the same
    device, keeps its owner (D-076, R0607-10): the association is removed only by withdrawal,
    erasure, expiry, ambiguity or a review action, never because the segment is closed.
    """
    from app.services.collection import consent_view
    from app.services.identity import identity_consent

    link = session.scalar(
        select(IdentityLink).where(
            IdentityLink.assertion_ref == assertion.id, IdentityLink.status == "active"
        )
    )
    if link is None or link.subject_id is None:
        return None
    consent = identity_consent(session, link.collection_subject_id, now)
    if consent.grant_record_id is None:
        return None
    subject = session.get(CollectionSubject, link.collection_subject_id)
    if consent_view(session, subject, now).states[Purpose.ATTRIBUTION] is not ConsentState.GRANTED:
        return None
    return link


def _attribution_start(session: Session, subject_id: UUID, now: datetime) -> datetime | None:
    """The start of the subject's current uninterrupted attribution grant, if any."""
    rows = session.scalars(
        select(StoredConsentRecord)
        .where(
            StoredConsentRecord.subject_id == subject_id,
            StoredConsentRecord.purpose == Purpose.ATTRIBUTION.value,
        )
        .order_by(StoredConsentRecord.received_at, StoredConsentRecord.id)
    )
    periods = grant_periods(
        (ConsentMark(row.received_at, row.state == "granted", row.expires_at) for row in rows),
        now,
    )
    period = current_period(periods, now)
    return period.start if period is not None else None


@dataclass(frozen=True)
class AssociationRequest:
    request_id: UUID
    source_account_id: str
    sale_operation_id: str
    assertion_id: UUID
    expected_revision: int | None


def associate(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    credential_id: UUID,
    request: AssociationRequest,
    *,
    lock: Callable[[], datetime],
) -> tuple[str, int]:
    from app.services.revenue import lock_revenue

    now = lock()  # client privacy lock, database clock and live sender scope
    lock_revenue(session, client_id)
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                str(request.request_id),
                request.source_account_id,
                request.sale_operation_id,
                str(request.assertion_id),
                request.expected_revision,
                str(credential_id),
            ]
        ).encode()
    ).hexdigest()
    recorded = session.scalar(
        select(RevenueIdentityBinding).where(
            RevenueIdentityBinding.client_id == client_id,
            RevenueIdentityBinding.request_id == request.request_id,
        )
    )
    if recorded is not None:
        if recorded.request_fingerprint != fingerprint:
            return "conflict", 409
        return "duplicate", 200
    assertion = session.scalar(
        select(IdentityAssertion).where(
            IdentityAssertion.client_id == client_id,
            IdentityAssertion.assertion_id == request.assertion_id,
        )
    )
    link = None
    if (
        assertion is not None
        and assertion.credential_id == credential_id
        and assertion.outcome in {"linked", "contested_identifier"}
        and assertion.subject_id is not None
    ):
        link = _segment_ok(session, assertion, now)
    if link is not None:
        # New proof for the current attribution grant: an assertion received before a
        # withdrawal never restores an association after a new grant (F1, R0607-05).
        start = _attribution_start(session, link.collection_subject_id, now)
        if start is None or assertion.received_at < start:
            link = None
    if link is None:
        # The answer is the generic acknowledgement: it never says whether the identifier was
        # erased, objected to, contested or withdrawn, or whose assertion it was (R0607-06).
        return "accepted", 201
    key = association_id(client_id, request.source_account_id, request.sale_operation_id)
    current = _current(session, client_id, key)
    live = (
        current is not None
        and current.closed_at is None
        and current.state in {"active", "pending", "ambiguous"}
    )
    expected = request.expected_revision or 0
    # Only a live association is versioned against the request: an unlinked or detached one
    # accepts a request that does not know it, so erasure history stays hidden (R0607-06).
    if expected != (current.revision if current else 0) and (live or expected != 0):
        return "revision_conflict", 409
    if live and current.state == "ambiguous":
        # A conflict is resolved by review only: no request, the challenger's included, makes
        # itself the owner (R0607-04).
        return "accepted", 201
    owner = link.subject_id
    if current is not None and current.state in {"active", "pending"} and current.closed_at is None:
        if current.owner_subject_id == owner:
            return "accepted", 201  # the same person already holds the association
    verified = _verified_sale(
        session, agency_id, client_id, request.source_account_id, request.sale_operation_id
    )
    state, reason = ("active" if verified else "pending"), None
    if (
        current is not None
        and current.closed_at is None
        and current.state in {"active", "pending", "ambiguous"}
        and current.owner_subject_id not in (None, owner)
    ):
        state, reason = "ambiguous", "conflicting_owner"
    if current is not None and current.closed_at is None:
        current.closed_at = now
    session.add(
        RevenueIdentityBinding(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            association_id=key,
            revision=(current.revision if current else 0) + 1,
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            source_account_id=request.source_account_id,
            sale_operation_id=request.sale_operation_id,
            credential_id=credential_id,
            assertion_ref=assertion.id,
            collection_subject_id=link.collection_subject_id,
            owner_subject_id=owner,
            key_ids=list(link.key_ids or []),
            state=state,
            reason=reason,
            expected_revision=request.expected_revision,
            received_at=now,
        )
    )
    session.flush()
    return "accepted", 201


def follow_link_owner(
    session: Session, client_id: UUID, assertion_ref: UUID, owner: UUID | None
) -> None:
    """An identity correction moves the live associations of an assertion with its segment:
    unmerge recomputes the owner from the original evidence, and a segment left ambiguous
    makes the association ambiguous for review (joint design section 3, R0607-15)."""
    values: dict[str, Any] = (
        {"owner_subject_id": owner}
        if owner is not None
        else {"owner_subject_id": None, "state": "ambiguous", "reason": "conflicting_owner"}
    )
    session.execute(
        update(RevenueIdentityBinding)
        .where(
            RevenueIdentityBinding.client_id == client_id,
            RevenueIdentityBinding.assertion_ref == assertion_ref,
            RevenueIdentityBinding.closed_at.is_(None),
            RevenueIdentityBinding.state.in_(["active", "pending"]),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )


def unlink(
    session: Session,
    client_id: UUID,
    reason: str,
    now: datetime,
    *,
    collection_subject_id: UUID | None = None,
    owner_subject_id: UUID | None = None,
    assertion_refs: Iterable[UUID] = (),
) -> int:
    """F1: clear every identifying pointer and retry material of the matching revisions."""
    conditions = []
    if collection_subject_id is not None:
        conditions.append(RevenueIdentityBinding.collection_subject_id == collection_subject_id)
    if owner_subject_id is not None:
        conditions.append(RevenueIdentityBinding.owner_subject_id == owner_subject_id)
    refs = list(assertion_refs)
    if refs:
        conditions.append(RevenueIdentityBinding.assertion_ref.in_(refs))
    if not conditions:
        return 0
    return session.execute(
        update(RevenueIdentityBinding)
        .where(RevenueIdentityBinding.client_id == client_id, or_(*conditions))
        .values(
            state="unlinked",
            reason=reason,
            closed_at=func.coalesce(RevenueIdentityBinding.closed_at, now),
            request_id=None,
            request_fingerprint=None,
            assertion_ref=None,
            collection_subject_id=None,
            owner_subject_id=None,
            key_ids=[],
        )
        .execution_options(synchronize_session=False)
    ).rowcount


def _qualifying(
    session: Session, agency_id: UUID | None, client_id: UUID, group: list[UUID], now: datetime
) -> list[RevenueIdentityBinding]:
    rows = list(
        session.scalars(
            select(RevenueIdentityBinding).where(
                RevenueIdentityBinding.client_id == client_id,
                RevenueIdentityBinding.closed_at.is_(None),
                RevenueIdentityBinding.state.in_(["active", "pending"]),
                RevenueIdentityBinding.owner_subject_id.in_(group),
            )
        )
    )
    if not rows:
        return []
    agency = agency_id or rows[0].agency_id
    found = []
    for row in rows:
        assertion = session.get(IdentityAssertion, row.assertion_ref) if row.assertion_ref else None
        if assertion is None:
            continue
        link = _segment_ok(session, assertion, now)
        if link is None or link.subject_id != row.owner_subject_id:
            continue
        if not _verified_sale(
            session, agency, client_id, row.source_account_id, row.sale_operation_id
        ):
            continue
        found.append(row)
    return found


def has_verified_purchase(session: Session, client_id: UUID, group: list[UUID]) -> bool:
    """Whether any person of the group has a currently associated verified capture. While the
    published ledger cannot be read, LedgerUnavailable propagates: the caller answers an
    explicit unavailable state, never "not a customer" (R0607-09)."""
    now = session.scalar(select(func.clock_timestamp()))
    return bool(_qualifying(session, None, client_id, group, now))


def person_revenue(
    session: Session, agency_id: UUID, client_id: UUID, group: list[UUID], now: datetime
) -> dict[str, Any]:
    """The verified sales currently associated with a person (both permissions checked by the
    caller); amounts in their original currency and minor units, never added across currencies."""
    from app.services.ledger_store import published_state

    state = published_state(session, agency_id, client_id)
    sales = []
    for row in _qualifying(session, agency_id, client_id, group, now):
        transaction = session.scalar(
            select(LedgerTransaction).where(
                LedgerTransaction.client_id == client_id,
                LedgerTransaction.generation == state.generation,
                LedgerTransaction.source_account_id == row.source_account_id,
                LedgerTransaction.operation_id == row.sale_operation_id,
            )
        )
        sales.append(
            {
                "association_id": str(row.association_id),
                "revision": row.revision,
                "source_account_id": row.source_account_id,
                "sale_operation_id": row.sale_operation_id,
                "currency": transaction.currency,
                "currency_exponent": transaction.currency_exponent,
                "sale_effective_at": transaction.sale_effective_at,
                "captured_minor": transaction.captured,
                "net_minor": transaction.net,
            }
        )
    return {
        "generation": state.generation if state else None,
        "financial_revision": state.financial_revision if state else 0,
        "customer_qualification": "customer" if sales else "not_customer",
        "sales": sales,
    }


class AssociationAdmin(TenancyService):
    """Owner/Admin detachment of a mistaken association; audited and idempotent."""

    def detach(
        self,
        agency_id: UUID,
        client_id: UUID,
        association: UUID,
        *,
        operation_id: UUID,
        expected_revision: int,
        reason_code: Literal["mistaken_association", "customer_request", "data_correction"],
    ) -> tuple[dict[str, Any], int]:
        from app.services.collection import lock_client

        if reason_code not in DETACH_REASONS:
            raise ValueError("Unknown reason code.")
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        now = lock_client(self.session, client_id)
        fingerprint = hashlib.sha256(
            json.dumps(
                ["detach", str(association), expected_revision, reason_code, str(actor.id)]
            ).encode()
        ).hexdigest()
        recorded = self.session.scalar(
            select(RevenueIdentityBinding).where(
                RevenueIdentityBinding.client_id == client_id,
                RevenueIdentityBinding.request_id == operation_id,
            )
        )
        if recorded is not None:
            if recorded.request_fingerprint != fingerprint:
                raise AssociationError("operation_conflict", 409)
            return {"association_id": str(association), "revision": recorded.revision}, 200
        current = _current(self.session, client_id, association)
        if current is None:
            raise AccessDenied()
        if current.revision != expected_revision:
            raise AssociationError("revision_conflict", 409)
        if current.state in {"detached", "unlinked"}:
            raise AssociationError("association_not_active", 409)
        current.closed_at = current.closed_at or now
        row = RevenueIdentityBinding(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            association_id=association,
            revision=current.revision + 1,
            request_id=operation_id,
            request_fingerprint=fingerprint,
            source_account_id=current.source_account_id,
            sale_operation_id=current.sale_operation_id,
            actor_membership_id=actor.id,
            state="detached",
            reason="detached_by_manager",
            detach_reason=reason_code,
            expected_revision=expected_revision,
            received_at=now,
        )
        self.session.add(row)
        self.session.flush()
        self._audit(
            agency_id, "revenue.association_detached", "revenue_association", association, client_id
        )
        return {"association_id": str(association), "revision": row.revision}, 201
