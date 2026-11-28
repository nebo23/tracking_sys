"""Paddle webhook events of platform billing (specification 017-C, D-103 D6, D7, D9 and D11).

Design-017c.md section 5. A verified event is resolved to an agency without a lock (a stored
subscription, payment or checkout), then applied under the agency row lock in the request's
transaction, with no outbound call, within Paddle's five seconds:

- Each event ID is stored once: a repeated delivery changes nothing and is answered like the
  first. An event older than the last one applied to the same subscription, payment or
  adjustment is stored stale and not applied; Paddle does not guarantee the order (V-5).
- A subscription is bound to its agency only through the checkout's transaction ID, which
  subscription.created carries (D6, V-6); custom_data must agree when present, otherwise the
  event stays unmatched (binding_conflict). Earlier events of the subscription that arrived
  before it was bound are stored unmatched with their allowlisted fields; at binding the newest
  of them that is later than the binding event is applied and the others are marked stale. A
  second live subscription of an agency is flagged a duplicate and changes no standing.
- Transactions record or update the agency's payments and complete their checkout; adjustments
  record refunds, credits and chargebacks. Neither changes a standing (D9, D11).
- An event of an unknown subscription or transaction is stored unmatched and listed for the
  operator; any other event type is stored ignored.

Only allowlisted fields are stored (IDs, statuses, amounts, currencies and times). Platform
billing never writes revenue evidence, the ledger or a 015 payment source. Nothing here logs or
returns a name, an email, a signature or a body.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.billing.paddle import (
    AdjustmentSnapshot,
    Event,
    InvalidPayload,
    ProviderError,
    SubscriptionSnapshot,
    TransactionSnapshot,
    adjustment_of,
    subscription_of,
    transaction_of,
)
from app.models import (
    Agency,
    AgencySubscription,
    BillingAdjustment,
    BillingCheckout,
    BillingEvent,
    BillingPayment,
    BillingPrice,
)
from app.services import billing

logger = logging.getLogger("tracking")
PROVIDER = "paddle"
SUBSCRIPTION_EVENTS = frozenset(
    f"subscription.{name}"
    for name in (
        "created",
        "activated",
        "updated",
        "trialing",
        "past_due",
        "paused",
        "resumed",
        "canceled",
    )
)
TRANSACTION_EVENTS = frozenset(
    f"transaction.{name}" for name in ("completed", "paid", "payment_failed")
)
ADJUSTMENT_EVENTS = frozenset({"adjustment.created", "adjustment.updated"})
Snapshot = SubscriptionSnapshot | TransactionSnapshot | AdjustmentSnapshot


@dataclass(frozen=True)
class Resolution:
    agency_id: UUID | None
    checkout: BillingCheckout | None = None
    conflict: bool = False


@dataclass(frozen=True)
class Applied:
    outcome: str
    error: str | None
    subscription: AgencySubscription | None


def _kind(event_type: str) -> str | None:
    if event_type in SUBSCRIPTION_EVENTS:
        return "subscription"
    if event_type in TRANSACTION_EVENTS:
        return "transaction"
    if event_type in ADJUSTMENT_EVENTS:
        return "adjustment"
    return None


PARSERS: dict[str, Callable[[Any], Snapshot]] = {
    "subscription": subscription_of,
    "transaction": transaction_of,
    "adjustment": adjustment_of,
}


def _subscription(session: Session, provider_id: str | None, *, lock: bool = False):
    if provider_id is None:
        return None
    query = select(AgencySubscription).where(
        AgencySubscription.provider == PROVIDER,
        AgencySubscription.provider_subscription_id == provider_id,
    )
    if lock:
        query = query.with_for_update()
    return session.scalar(query.execution_options(populate_existing=True))


def _payment(session: Session, transaction_id: str | None, *, lock: bool = False):
    if transaction_id is None:
        return None
    query = select(BillingPayment).where(BillingPayment.provider_transaction_id == transaction_id)
    if lock:
        query = query.with_for_update()
    return session.scalar(query.execution_options(populate_existing=True))


def _checkout(session: Session, transaction_id: str | None) -> BillingCheckout | None:
    if transaction_id is None:
        return None
    return session.scalar(
        select(BillingCheckout)
        .where(BillingCheckout.provider_transaction_id == transaction_id)
        .execution_options(populate_existing=True)
    )


def registered_price(session: Session, provider_price_id: str | None) -> BillingPrice | None:
    if provider_price_id is None:
        return None
    return session.scalar(
        select(BillingPrice).where(
            BillingPrice.provider == PROVIDER, BillingPrice.provider_price_id == provider_price_id
        )
    )


# custom_data must agree with the checkout found by its transaction ID (D6).
def _conflicts(snapshot: SubscriptionSnapshot | TransactionSnapshot, checkout) -> bool:  # noqa: ANN001
    agency, checkout_id = snapshot.custom_agency, snapshot.custom_checkout
    return (agency is not None and agency != checkout.agency_id) or (
        checkout_id is not None and checkout_id != checkout.id
    )


def _through_checkout(session: Session, snapshot, transaction_id: str | None) -> Resolution:  # noqa: ANN001
    checkout = _checkout(session, transaction_id)
    if checkout is None:
        return Resolution(None)
    if _conflicts(snapshot, checkout):
        return Resolution(None, conflict=True)
    return Resolution(checkout.agency_id, checkout)


def resolve(session: Session, kind: str, snapshot: Snapshot) -> Resolution:
    if isinstance(snapshot, SubscriptionSnapshot):
        stored = _subscription(session, snapshot.id)
        if stored is not None:
            return Resolution(stored.agency_id)
        return _through_checkout(session, snapshot, snapshot.transaction_id)
    if isinstance(snapshot, TransactionSnapshot):
        payment = _payment(session, snapshot.id)
        if payment is not None:
            return Resolution(payment.agency_id, _checkout(session, snapshot.id))
        found = _through_checkout(session, snapshot, snapshot.id)
        if found.agency_id is not None or found.conflict:
            return found
        stored = _subscription(session, snapshot.subscription_id)
        return Resolution(None if stored is None else stored.agency_id)
    payment = _payment(session, snapshot.transaction_id)
    if payment is not None:
        return Resolution(payment.agency_id)
    stored = _subscription(session, snapshot.subscription_id)
    return Resolution(None if stored is None else stored.agency_id)


def _provider_ids(snapshot: Snapshot) -> tuple[str | None, str | None]:
    if isinstance(snapshot, SubscriptionSnapshot):
        return snapshot.id, snapshot.transaction_id
    if isinstance(snapshot, TransactionSnapshot):
        return snapshot.subscription_id, snapshot.id
    return snapshot.subscription_id, snapshot.transaction_id


# Store an event that belongs to no agency (unmatched or ignored) once by its ID; returns
# "duplicate" when it was already stored.
def _record_unscoped(
    session: Session,
    event: Event,
    source: str,
    outcome: str,
    error: str | None,
    snapshot: Snapshot | None,
) -> str:
    subscription_id, transaction_id = (None, None) if snapshot is None else _provider_ids(snapshot)
    stored = session.scalar(
        insert(BillingEvent)
        .values(
            id=uuid4(),
            provider=PROVIDER,
            provider_event_id=event.event_id,
            source=source,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            provider_subscription_id=subscription_id,
            provider_transaction_id=transaction_id,
            outcome=outcome,
            error_code=error,
            fields={} if snapshot is None else snapshot.fields(),
        )
        .on_conflict_do_nothing(index_elements=["provider", "provider_event_id"])
        .returning(BillingEvent.id)
    )
    if stored is None:
        return "duplicate"
    if outcome == "unmatched":
        logger.info("billing_event_unmatched")
    return outcome


def _stored(session: Session, event_id: str) -> bool:
    return (
        session.scalar(
            select(BillingEvent.id).where(
                BillingEvent.provider == PROVIDER, BillingEvent.provider_event_id == event_id
            )
        )
        is not None
    )


def copy_subscription(
    row: AgencySubscription,
    snapshot: SubscriptionSnapshot,
    price: BillingPrice | None,
    occurred_at: datetime,
    now: datetime,
) -> None:
    row.status = snapshot.status
    row.price_id = None if price is None else price.id
    row.provider_price_id = snapshot.price_id
    row.current_period_starts_at = snapshot.period_starts_at
    row.current_period_ends_at = snapshot.period_ends_at
    row.next_billed_at = snapshot.next_billed_at
    row.scheduled_action, row.scheduled_at = snapshot.scheduled_action, snapshot.scheduled_at
    # The origin is kept as our own calls set it; a cancellation scheduled outside the
    # application (Paddle's dashboard) is the provider's.
    if snapshot.scheduled_action == "cancel" and row.cancel_origin is None:
        row.cancel_origin = "provider"
    row.canceled_at = snapshot.canceled_at
    row.last_event_at = occurred_at
    row.updated_at = now


def _price_error(snapshot: SubscriptionSnapshot, price: BillingPrice | None) -> str | None:
    if snapshot.item_count != 1:
        return "unsupported_items"
    if price is None:
        return "unknown_price"
    return None


def record_customer(session: Session, agency_id: UUID, customer_id: str | None) -> None:
    item = billing.standing_of(session, agency_id)
    if item is not None and customer_id is not None and item.provider_customer_id is None:
        item.provider_customer_id = customer_id


# At binding, the newest earlier-stored snapshot of the subscription that is later than the
# binding event is applied; the other unmatched events of it are superseded (stale).
def _replay_unmatched(
    session: Session, agency: Agency, row: AgencySubscription, now: datetime
) -> None:
    waiting = session.scalars(
        select(BillingEvent)
        .where(
            BillingEvent.provider == PROVIDER,
            BillingEvent.outcome == "unmatched",
            BillingEvent.error_code.is_(None),
            BillingEvent.provider_subscription_id == row.provider_subscription_id,
            BillingEvent.event_type.in_(SUBSCRIPTION_EVENTS),
        )
        .order_by(BillingEvent.occurred_at.desc(), BillingEvent.id.desc())
        .with_for_update()
    ).all()
    applied = False
    for item in waiting:
        item.agency_id, item.subscription_id, item.outcome = agency.id, row.id, "stale"
        if applied or item.occurred_at < row.last_event_at:
            continue
        try:
            snapshot = SubscriptionSnapshot.from_fields(row.provider_subscription_id, item.fields)
        except InvalidPayload:
            item.outcome, item.error_code = "ignored", "invalid_payload"
            continue
        price = registered_price(session, snapshot.price_id) if snapshot.item_count == 1 else None
        copy_subscription(row, snapshot, price, item.occurred_at, now)
        item.outcome, item.error_code, applied = "applied", _price_error(snapshot, price), True
    session.flush()


def _apply_subscription(
    session: Session,
    agency: Agency,
    event: Event,
    snapshot: SubscriptionSnapshot,
    resolution: Resolution,
    now: datetime,
) -> Applied:
    row = _subscription(session, snapshot.id, lock=True)
    price = registered_price(session, snapshot.price_id) if snapshot.item_count == 1 else None
    error = _price_error(snapshot, price)
    if row is None:
        checkout = resolution.checkout
        if checkout is None or checkout.agency_id != agency.id:
            return Applied("unmatched", None, None)
        row = AgencySubscription(
            id=uuid4(),
            agency_id=agency.id,
            provider=PROVIDER,
            provider_subscription_id=snapshot.id,
            provider_transaction_id=snapshot.transaction_id,
            duplicate=billing.primary_subscription(session, agency.id) is not None,
            created_at=now,
        )
        copy_subscription(row, snapshot, price, event.occurred_at, now)
        session.add(row)
        session.flush()
        if checkout.status == "open":
            checkout.status, checkout.completed_at = "completed", now
        _replay_unmatched(session, agency, row, now)
    elif event.occurred_at < row.last_event_at:
        return Applied("stale", None, row)
    else:
        copy_subscription(row, snapshot, price, event.occurred_at, now)
    record_customer(session, agency.id, snapshot.customer_id)
    session.flush()
    if agency.status == "closed":
        error = error or "agency_closed"
    billing.follow_subscription(session, agency, billing.standing_of(session, agency.id), row, now)
    return Applied("applied", error, row)


def _apply_transaction(
    session: Session,
    agency: Agency,
    event: Event,
    snapshot: TransactionSnapshot,
    resolution: Resolution,
    now: datetime,
) -> Applied:
    payment = _payment(session, snapshot.id, lock=True)
    subscription = _subscription(session, snapshot.subscription_id)
    if subscription is not None and subscription.agency_id != agency.id:
        subscription = None
    if payment is None:
        payment = BillingPayment(
            id=uuid4(), agency_id=agency.id, provider_transaction_id=snapshot.id, created_at=now
        )
        session.add(payment)
    elif event.occurred_at < payment.last_event_at:
        return Applied("stale", None, subscription)
    if subscription is not None:
        payment.subscription_id = subscription.id
    payment.status, payment.origin, payment.currency = (
        snapshot.status,
        snapshot.origin,
        snapshot.currency,
    )
    payment.subtotal_cents, payment.tax_cents, payment.total_cents = (
        snapshot.subtotal,
        snapshot.tax,
        snapshot.total,
    )
    payment.billed_at, payment.invoice_number = snapshot.billed_at, snapshot.invoice_number
    payment.last_event_at, payment.updated_at = event.occurred_at, now
    session.flush()
    # An adjustment that arrived before its transaction is linked now.
    session.execute(
        update(BillingAdjustment)
        .where(
            BillingAdjustment.agency_id == agency.id,
            BillingAdjustment.provider_transaction_id == snapshot.id,
            BillingAdjustment.payment_id.is_(None),
        )
        .values(payment_id=payment.id)
        .execution_options(synchronize_session=False)
    )
    checkout = resolution.checkout or _checkout(session, snapshot.id)
    if (
        checkout is not None
        and checkout.agency_id == agency.id
        and checkout.status == "open"
        and snapshot.status in ("paid", "completed")
    ):
        checkout.status, checkout.completed_at = "completed", now
    return Applied("applied", None, subscription)


def _apply_adjustment(
    session: Session,
    agency: Agency,
    event: Event,
    snapshot: AdjustmentSnapshot,
    resolution: Resolution,
    now: datetime,
) -> Applied:
    row = session.scalar(
        select(BillingAdjustment)
        .where(BillingAdjustment.provider_adjustment_id == snapshot.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    payment = _payment(session, snapshot.transaction_id)
    payment_id = payment.id if payment is not None and payment.agency_id == agency.id else None
    subscription = _subscription(session, snapshot.subscription_id)
    if subscription is not None and subscription.agency_id != agency.id:
        subscription = None
    if row is None:
        row = BillingAdjustment(
            id=uuid4(),
            agency_id=agency.id,
            provider_adjustment_id=snapshot.id,
            provider_transaction_id=snapshot.transaction_id,
            action=snapshot.action,
            created_at=now,
        )
        session.add(row)
    elif event.occurred_at < row.last_event_at:
        return Applied("stale", None, subscription)
    if row.payment_id is None:
        row.payment_id = payment_id
    row.status, row.currency, row.total_cents = snapshot.status, snapshot.currency, snapshot.total
    row.last_event_at, row.updated_at = event.occurred_at, now
    session.flush()
    return Applied("applied", None, subscription)


APPLY: dict[str, Callable[..., Applied]] = {
    "subscription": _apply_subscription,
    "transaction": _apply_transaction,
    "adjustment": _apply_adjustment,
}


# Store one verified event once and apply it (design section 5.2). Returns the outcome:
# applied, stale, ignored, unmatched, or duplicate for an event already stored.
def receive_event(session: Session, event: Event, *, source: str = "webhook") -> str:
    kind = _kind(event.event_type)
    if kind is None:
        return _record_unscoped(session, event, source, "ignored", None, None)
    try:
        snapshot = PARSERS[kind](event.data)
    except (ProviderError, InvalidPayload):
        return _record_unscoped(session, event, source, "ignored", "invalid_payload", None)
    found = resolve(session, kind, snapshot)
    if found.agency_id is None:
        error = "binding_conflict" if found.conflict else None
        return _record_unscoped(session, event, source, "unmatched", error, snapshot)
    agency = billing.lock_agency(session, found.agency_id)
    if agency is None or _stored(session, event.event_id):
        return "duplicate"
    # Under the agency lock, a concurrent event may have bound the subscription meanwhile.
    found = resolve(session, kind, snapshot)
    if found.agency_id != agency.id:
        return _record_unscoped(session, event, source, "unmatched", "binding_conflict", snapshot)
    result = APPLY[kind](session, agency, event, snapshot, found, billing.database_now(session))
    if result.outcome == "unmatched":
        return _record_unscoped(session, event, source, "unmatched", None, snapshot)
    subscription_id, transaction_id = _provider_ids(snapshot)
    session.add(
        BillingEvent(
            id=uuid4(),
            provider=PROVIDER,
            provider_event_id=event.event_id,
            source=source,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            agency_id=agency.id,
            subscription_id=None if result.subscription is None else result.subscription.id,
            provider_subscription_id=subscription_id,
            provider_transaction_id=transaction_id,
            outcome=result.outcome,
            error_code=result.error,
            fields=snapshot.fields(),
        )
    )
    session.flush()
    return result.outcome
