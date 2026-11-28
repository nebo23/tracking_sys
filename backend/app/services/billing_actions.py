"""Closure actions and reconciliation of platform billing (017-C, D-103 D7 and D10).

Design-017c.md sections 8 and 10. An agency closure never calls Paddle in its own transaction;
it records provider actions that the billing worker executes with bounded retries:

- the closure request schedules the cancellation of every subscription that has not ended at the
  end of its paid period, unless a cancellation is already scheduled (an Owner's own is kept);
- the closure's cancellation skips a period-end cancellation that was never claimed and removes
  one that the closure scheduled or was executing, but never an Owner's earlier cancellation;
- the closure's completion (app.services.agency_lifecycle, as tracking_lifecycle) cancels every
  subscription that has not ended at once, duplicates included, without an automatic refund.

The worker settles at most one action of a subscription at a time: a claim (an attempt and a
short lease) is committed before the call, and the result is recorded under the agency lock
afterwards. A canceled subscription answers skipped; other failures retry after 5, 10, 20, 40,
80, 160 and 320 minutes, and the eighth failure is failed for the operator. The purge of a closed
agency waits while one of its actions is pending (0034).

Reconciliation reads each subscription that has not ended and was not reconciled in the last 24
hours, in a bounded batch, and applies a difference from the stored state as a reconciliation
event, timed at the start of the read, so a newer webhook wins (stale). Nothing here logs or
returns a name, an email or a secret.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, insert, literal_column, nulls_first, or_, select, tuple_
from sqlalchemy.orm import Session, aliased

from app.billing.paddle import PaddleClient, ProviderError, SubscriptionSnapshot
from app.models import AgencySubscription, AuditEvent, BillingAction, BillingEvent
from app.services import billing
from app.services.billing_events import (
    PROVIDER,
    copy_subscription,
    record_customer,
    registered_price,
)

logger = logging.getLogger("tracking")
LIVE = ("trialing", "active", "past_due")
LEASE = timedelta(minutes=5)
FIRST_RETRY = timedelta(minutes=5)
MAX_ATTEMPTS = 8
RECONCILE_AFTER = timedelta(hours=24)
ACTION_OUTCOMES = ("done", "skipped", "retried", "failed")
RECONCILE_OUTCOMES = ("checked", "corrected", "failed")


def _action(agency_id: UUID, subscription_id: UUID, action: str) -> BillingAction:
    return BillingAction(
        id=uuid4(),
        agency_id=agency_id,
        subscription_id=subscription_id,
        action=action,
        reason={
            "cancel_next_period": "closure_requested",
            "remove_scheduled_cancel": "closure_cancelled",
            "cancel_now": "closure_completed",
        }[action],
    )


# In the closure request's transaction (agency locked): a period-end cancellation of every
# subscription that has not ended and has no cancellation scheduled. Returns the number queued.
def queue_closure_request(session: Session, agency_id: UUID) -> int:
    subscriptions = session.scalars(
        select(AgencySubscription).where(
            AgencySubscription.agency_id == agency_id,
            AgencySubscription.status.in_(LIVE),
            or_(
                AgencySubscription.scheduled_action.is_(None),
                AgencySubscription.scheduled_action != "cancel",
            ),
            AgencySubscription.cancel_origin.is_(None),
        )
    ).all()
    for subscription in subscriptions:
        session.add(_action(agency_id, subscription.id, "cancel_next_period"))
    session.flush()
    return len(subscriptions)


# In the closure cancellation's transaction (agency locked): skip what was never claimed, and
# remove what the closure scheduled or was executing. Returns the number of removals queued.
def queue_closure_cancellation(session: Session, agency_id: UUID, now: datetime) -> int:
    pending = session.scalars(
        select(BillingAction)
        .where(
            BillingAction.agency_id == agency_id,
            BillingAction.action == "cancel_next_period",
            BillingAction.status == "pending",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    claimed = set()
    for action in pending:
        if action.attempts == 0:
            action.status, action.last_error, action.completed_at = (
                "skipped",
                "closure_cancelled",
                now,
            )
        else:
            claimed.add(action.subscription_id)
    removals = session.scalars(
        select(AgencySubscription.id).where(
            AgencySubscription.agency_id == agency_id,
            AgencySubscription.status != "canceled",
            or_(
                AgencySubscription.cancel_origin == "closure",
                AgencySubscription.id.in_(list(claimed)),
            ),
        )
    ).all()
    for subscription_id in removals:
        session.add(_action(agency_id, subscription_id, "remove_scheduled_cancel"))
    session.flush()
    return len(removals)


# In the closure completion's transaction, as tracking_lifecycle (agency locked): cancel at once
# every subscription of the agency that has not ended. Returns the number queued.
def queue_closure_completion(connection: Any, agency_id: UUID) -> int:
    chosen = select(
        func.gen_random_uuid(),
        AgencySubscription.agency_id,
        AgencySubscription.id,
        literal_column("'cancel_now'"),
        literal_column("'closure_completed'"),
    ).where(AgencySubscription.agency_id == agency_id, AgencySubscription.status != "canceled")
    return connection.execute(
        insert(BillingAction).from_select(
            ["id", "agency_id", "subscription_id", "action", "reason"], chosen
        )
    ).rowcount


def _skip_reason(
    session: Session, action: BillingAction, subscription: AgencySubscription
) -> str | None:
    if subscription.status == "canceled":
        return "subscription_canceled"
    if action.action == "cancel_next_period":
        # The closure completed meanwhile: its immediate cancellation supersedes this one.
        superseded = session.scalar(
            select(BillingAction.id).where(
                BillingAction.subscription_id == subscription.id,
                BillingAction.action == "cancel_now",
                BillingAction.status == "pending",
            )
        )
        if superseded is not None:
            return "superseded"
        if subscription.scheduled_action == "cancel" or subscription.cancel_origin is not None:
            return "already_scheduled"
        if subscription.status == "paused":
            return "not_applicable"
    if action.action == "remove_scheduled_cancel" and subscription.cancel_origin != "closure":
        return "not_closure"
    return None


def _call(provider: PaddleClient, kind: str, subscription_id: str) -> str | None:
    try:
        if kind == "cancel_next_period":
            provider.cancel(subscription_id, immediately=False)
        elif kind == "remove_scheduled_cancel":
            provider.remove_scheduled_change(subscription_id)
        else:
            try:
                provider.cancel(subscription_id, immediately=True)
            except ProviderError as error:
                if error.code != "pending_change":
                    raise
                provider.remove_scheduled_change(subscription_id)
                provider.cancel(subscription_id, immediately=True)
    except ProviderError as error:
        return error.code
    return None


def _run_action(engine: Engine, provider: PaddleClient, action_id: UUID, now: datetime) -> str:
    with Session(engine) as session, session.begin():
        action = session.scalar(
            select(BillingAction)
            .where(BillingAction.id == action_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if action is None or action.status != "pending" or action.next_attempt_at > now:
            return "busy"
        subscription = session.get(AgencySubscription, action.subscription_id)
        assert subscription is not None
        skipped = _skip_reason(session, action, subscription)
        if skipped is not None:
            action.status, action.last_error, action.completed_at = "skipped", skipped, now
            return "skipped"
        action.attempts += 1
        action.next_attempt_at = now + LEASE
        kind, target, agency_id = (
            action.action,
            subscription.provider_subscription_id,
            action.agency_id,
        )
    error = _call(provider, kind, target)
    with Session(engine) as session, session.begin():
        billing.lock_agency(session, agency_id)
        action = session.get(BillingAction, action_id, with_for_update=True, populate_existing=True)
        assert action is not None
        subscription = session.get(
            AgencySubscription, action.subscription_id, with_for_update=True, populate_existing=True
        )
        assert subscription is not None
        if error is None:
            action.status, action.last_error, action.completed_at = "done", None, now
            if kind == "cancel_next_period":
                subscription.cancel_origin = "closure"
            elif kind == "remove_scheduled_cancel":
                subscription.cancel_origin = None
            return "done"
        if error == "subscription_canceled" or (
            kind == "cancel_next_period" and error == "pending_change"
        ):
            action.status, action.last_error, action.completed_at = "skipped", error, now
            return "skipped"
        logger.warning("billing_provider_failed", extra={"billing_code": error})
        action.last_error = error
        if action.attempts >= MAX_ATTEMPTS:
            action.status, action.completed_at = "failed", now
            logger.warning("billing_action_failed")
            return "failed"
        action.next_attempt_at = now + FIRST_RETRY * 2 ** (action.attempts - 1)
        return "retried"


# Worker step 2: due pending actions, oldest first, at most one per subscription.
def run_actions(
    engine: Engine, provider: PaddleClient, now: datetime, limit: int
) -> dict[str, int]:
    older = aliased(BillingAction)
    waiting = (
        select(older.id)
        .where(
            older.subscription_id == BillingAction.subscription_id,
            older.status == "pending",
            tuple_(older.created_at, older.id) < tuple_(BillingAction.created_at, BillingAction.id),
        )
        .exists()
    )
    with Session(engine) as session:
        due = list(
            session.scalars(
                select(BillingAction.id)
                .where(
                    BillingAction.status == "pending",
                    BillingAction.next_attempt_at <= now,
                    ~waiting,
                )
                .order_by(BillingAction.created_at, BillingAction.id)
                .limit(limit)
            )
        )
    outcomes: Counter = Counter()
    for action_id in due:
        outcome = _run_action(engine, provider, action_id, now)
        if outcome != "busy":
            outcomes[outcome] += 1
    return billing.counts(outcomes, ACTION_OUTCOMES)


def _differs(row: AgencySubscription, snapshot: SubscriptionSnapshot) -> bool:
    return (
        row.status,
        row.provider_price_id,
        row.current_period_ends_at,
        row.next_billed_at,
        row.scheduled_action,
        row.scheduled_at,
        row.canceled_at,
    ) != (
        snapshot.status,
        snapshot.price_id,
        snapshot.period_ends_at,
        snapshot.next_billed_at,
        snapshot.scheduled_action,
        snapshot.scheduled_at,
        snapshot.canceled_at,
    )


# Apply one read of a subscription (design section 8, step 3) under the agency lock: a
# difference becomes a reconciliation event, stale when a webhook applied later was newer.
# Returns "checked", "corrected" or "busy".
def reconcile_one(
    engine: Engine,
    subscription_id: UUID,
    snapshot: SubscriptionSnapshot,
    read_at: datetime,
    *,
    audit: bool = False,
) -> str:
    with Session(engine) as session, session.begin():
        row = session.get(AgencySubscription, subscription_id)
        assert row is not None
        agency = billing.lock_agency(session, row.agency_id, skip_locked=True)
        if agency is None:
            return "busy"
        row = session.get(
            AgencySubscription, subscription_id, with_for_update=True, populate_existing=True
        )
        assert row is not None
        now = billing.database_now(session)
        outcome = "checked"
        if _differs(row, snapshot):
            stale = read_at < row.last_event_at
            if not stale:
                price = (
                    registered_price(session, snapshot.price_id)
                    if snapshot.item_count == 1
                    else None
                )
                copy_subscription(row, snapshot, price, read_at, now)
                record_customer(session, agency.id, snapshot.customer_id)
                session.flush()
                billing.follow_subscription(
                    session, agency, billing.standing_of(session, agency.id), row, now
                )
                outcome = "corrected"
                if audit:
                    session.add(
                        AuditEvent(
                            id=uuid4(),
                            agency_id=agency.id,
                            actor_kind="platform_operator",
                            actor_user_id=None,
                            action="billing.reconciled",
                            resource_type="agency_subscription",
                            resource_id=row.id,
                        )
                    )
            session.add(
                BillingEvent(
                    id=uuid4(),
                    provider=PROVIDER,
                    provider_event_id=f"rec_{uuid4().hex}",
                    source="reconciliation",
                    event_type="subscription.reconciled",
                    occurred_at=read_at,
                    agency_id=agency.id,
                    subscription_id=row.id,
                    provider_subscription_id=row.provider_subscription_id,
                    outcome="stale" if stale else "applied",
                    fields=snapshot.fields(),
                )
            )
        row.reconciled_at = now
        return outcome


# Worker step 3 and the reconcile subcommand: subscriptions that have not ended, oldest
# reconciliation first; with an agency, every one of its subscriptions regardless of the window.
def run_reconciliation(
    engine: Engine,
    provider: PaddleClient,
    now: datetime,
    limit: int,
    *,
    agency_id: UUID | None = None,
    audit: bool = False,
) -> dict[str, int]:
    query = select(AgencySubscription.id, AgencySubscription.provider_subscription_id).where(
        AgencySubscription.status != "canceled"
    )
    if agency_id is not None:
        query = query.where(AgencySubscription.agency_id == agency_id)
    else:
        query = query.where(
            or_(
                AgencySubscription.reconciled_at.is_(None),
                AgencySubscription.reconciled_at < now - RECONCILE_AFTER,
            )
        )
    with Session(engine) as session:
        chosen = session.execute(
            query.order_by(
                nulls_first(AgencySubscription.reconciled_at), AgencySubscription.id
            ).limit(limit)
        ).all()
    outcomes: Counter = Counter()
    for subscription_id, provider_id in chosen:
        with Session(engine) as session:
            read_at = billing.database_now(session)
        try:
            snapshot = provider.get_subscription(provider_id)
        except ProviderError as error:
            logger.warning("billing_provider_failed", extra={"billing_code": error.code})
            outcomes["failed"] += 1
            continue
        outcome = reconcile_one(engine, subscription_id, snapshot, read_at, audit=audit)
        if outcome == "busy":
            continue
        outcomes["checked"] += 1
        if outcome == "corrected":
            outcomes["corrected"] += 1
    return billing.counts(outcomes, RECONCILE_OUTCOMES)
