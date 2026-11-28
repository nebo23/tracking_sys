"""The billing standing of agencies: trial, subscription, hold and grants (017-C, D-103).

Specification 017-C decisions D4, D5 and D12 (design-017c.md section 4). Every agency has one
standing in agency_billing, and the standing acts only through the agency's 017-A plan
assignments: a trial keeps the default plan, a subscription assigns the plan of its price, and a
hold assigns the seeded billing_hold plan, whose counted limits are zero, so the existing plan
checks refuse every new client, seat, connection and managed link while nothing else stops and
nothing is deleted. Every transition runs under the agency row lock and writes its assignment in
the same transaction; a transition that changes nothing writes nothing.

Billing is allowed only while TRACKING_BILLING_ENABLED is set and the paddle.billing provider
rule is current (D14). Otherwise the machinery is inert: a new agency is complimentary on the
default plan exactly as before, and no transition happens. An operator grant wins over the
subscription until it ends; a duplicate subscription and a closed agency never change a
standing. Nothing here logs or returns a name, an email or a secret.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Agency,
    AgencyBilling,
    AgencyMembership,
    AgencySubscription,
    BillingPrice,
    SaasPlan,
    User,
)
from app.privacy.providers import feature_allowed, rule
from app.services import plans
from app.services.mail import BillingNotice, queue_billing_mail

RULE = "paddle.billing"
TRIAL_REMINDER = timedelta(days=3)
HOLD_MESSAGE_LIFETIME = timedelta(days=7)
GRANTED = ("complimentary", "operator_grant")


class BillingRefused(Exception):
    """A refusal of a billing route or command with a closed code and HTTP status."""

    def __init__(self, code: str, status: int = 409) -> None:
        self.code, self.status = code, status
        super().__init__(code)


# Whether billing may run today: the setting is on and the Paddle rule is current (D14).
def billing_allowed(settings: Settings, today: date) -> bool:
    return settings.billing_enabled and feature_allowed(rule(RULE), today).allowed


def require_billing(settings: Settings, today: date) -> None:
    if not billing_allowed(settings, today):
        raise BillingRefused("billing_unavailable", 503)


def database_now(session: Session) -> datetime:
    moment = session.scalar(select(func.now()))
    assert moment is not None
    return moment


# The agency row locked FOR UPDATE, the lock every agency mutation takes first; None when the
# agency does not exist or, with skip_locked, is busy.
def lock_agency(session: Session, agency_id: UUID, *, skip_locked: bool = False) -> Agency | None:
    return session.scalar(
        select(Agency)
        .where(Agency.id == agency_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )


def standing_of(session: Session, agency_id: UUID) -> AgencyBilling | None:
    return session.get(AgencyBilling, agency_id, populate_existing=True)


def hold_plan(session: Session) -> SaasPlan:
    plan = session.scalar(select(SaasPlan).where(SaasPlan.key == plans.HOLD_PLAN))
    if plan is None:
        raise plans.PlanUnavailable()
    return plan


# The standing of a new agency, in the transaction that creates it (D4): a trial on the default
# plan while billing is allowed, otherwise complimentary, which changes nothing.
def record_new_agency(
    session: Session, settings: Settings | None, agency_id: UUID
) -> AgencyBilling:
    now = database_now(session)
    if settings is not None and billing_allowed(settings, now.date()):
        row = AgencyBilling(
            agency_id=agency_id,
            standing="trialing",
            reason="new_agency",
            trial_ends_at=now + timedelta(days=settings.billing_trial_days),
        )
    else:
        row = AgencyBilling(
            agency_id=agency_id, standing="complimentary", reason="billing_disabled"
        )
    session.add(row)
    session.flush()
    return row


@dataclass(frozen=True)
class Target:
    """A standing to reach and the plan it assigns; plan None keeps the current plan."""

    standing: str
    reason: str
    plan: SaasPlan | None = None
    assigned_by: str = "billing"
    assignment_reason: str = "subscription"
    grant_ends_at: datetime | None = None


def on_hold(session: Session, reason: str) -> Target:
    return Target("hold", reason, hold_plan(session), "billing", "billing_hold")


# Apply one transition to a locked agency's standing (design section 4). The plan assignment
# and the standing change in the caller's transaction; returns whether anything changed.
def apply(session: Session, billing: AgencyBilling, target: Target, now: datetime) -> bool:
    changed = False
    if target.plan is not None:
        current = plans.current_plan(session, billing.agency_id).plan
        if current.id != target.plan.id:
            plans.add_assignment(
                session,
                billing.agency_id,
                target.plan,
                assigned_by=target.assigned_by,
                reason=target.assignment_reason,
            )
            changed = True
    grant = target.grant_ends_at if (target.standing, target.reason) == GRANTED else None
    if (billing.standing, billing.reason, billing.grant_ends_at) != (
        target.standing,
        target.reason,
        grant,
    ):
        if target.standing != "hold":
            billing.hold_started_at = billing.hold_notified_at = None
        elif billing.standing != "hold":
            billing.hold_started_at, billing.hold_notified_at = now, None
        billing.standing, billing.reason, billing.grant_ends_at = (
            target.standing,
            target.reason,
            grant,
        )
        changed = True
    if changed:
        billing.version += 1
        billing.updated_at = now
        session.flush()
    return changed


# The agency's primary subscription that has not ended (at most one, by a partial unique
# index), or None.
def primary_subscription(session: Session, agency_id: UUID) -> AgencySubscription | None:
    return session.scalar(
        select(AgencySubscription)
        .where(
            AgencySubscription.agency_id == agency_id,
            AgencySubscription.duplicate.is_(False),
            AgencySubscription.status != "canceled",
        )
        .execution_options(populate_existing=True)
    )


def price_plan(session: Session, subscription: AgencySubscription) -> SaasPlan | None:
    if subscription.price_id is None:
        return None
    return session.scalar(
        select(SaasPlan)
        .join(BillingPrice, BillingPrice.plan_id == SaasPlan.id)
        .where(BillingPrice.id == subscription.price_id)
    )


# The standing a subscription gives (design section 4): active and trialing are subscribed on
# the plan of the price, past_due keeps the plan, paused and canceled hold. A price that is not
# registered keeps the current plan, but never leaves a paying agency on the hold plan.
def subscription_target(
    session: Session, billing: AgencyBilling, subscription: AgencySubscription | None
) -> Target:
    if subscription is None or subscription.status == "canceled":
        return on_hold(session, "subscription_canceled")
    if subscription.status == "paused":
        return on_hold(session, "subscription_paused")
    if subscription.status == "past_due":
        return Target("past_due", "payment_failed")
    plan = price_plan(session, subscription)
    if plan is None and plans.current_plan(session, billing.agency_id).plan.key == plans.HOLD_PLAN:
        plan = plans.default_plan(session)
    if billing.standing == "subscribed":
        reason = billing.reason
    elif billing.standing == "past_due":
        reason = "payment_recovered"
    else:
        reason = "subscription_active"
    return Target("subscribed", reason, plan)


# Follow the primary subscription under the agency lock, unless an operator grant is in force,
# the subscription is a duplicate, or the agency is closed (design section 4).
def follow_subscription(
    session: Session,
    agency: Agency,
    billing: AgencyBilling | None,
    subscription: AgencySubscription,
    now: datetime,
) -> bool:
    if billing is None or agency.status == "closed" or subscription.duplicate:
        return False
    if (billing.standing, billing.reason) == GRANTED:
        return False
    return apply(session, billing, subscription_target(session, billing, subscription), now)


# The end of an operator grant (worker or end-grant): the primary subscription decides, and
# without one the agency holds with reason grant_ended.
def end_grant(session: Session, billing: AgencyBilling, now: datetime) -> bool:
    subscription = primary_subscription(session, billing.agency_id)
    if subscription is None:
        target = on_hold(session, "grant_ended")
    else:
        target = subscription_target(session, billing, subscription)
    return apply(session, billing, target, now)


def grant(
    session: Session,
    billing: AgencyBilling,
    plan: SaasPlan,
    until: datetime | None,
    now: datetime,
) -> bool:
    target = Target(*GRANTED, plan, "platform_operator", "plan_change", until)
    return apply(session, billing, target, now)


def extend_trial(billing: AgencyBilling, days: int, now: datetime) -> None:
    assert billing.standing == "trialing" and billing.trial_ends_at is not None
    billing.trial_ends_at += timedelta(days=days)
    billing.trial_reminded_at = None
    billing.version += 1
    billing.updated_at = now


# The email addresses of an agency's active, verified Owners, the recipients of the billing
# messages (D11). Never logged or returned.
def owner_emails(session: Session, agency_id: UUID) -> list[str]:
    return list(
        session.scalars(
            select(User.email_normalized)
            .join(AgencyMembership, AgencyMembership.user_id == User.id)
            .where(
                AgencyMembership.agency_id == agency_id,
                AgencyMembership.role == "owner",
                AgencyMembership.status == "active",
                User.status == "active",
                User.email_verified_at.is_not(None),
            )
            .order_by(User.id)
        )
    )


def _due(session: Session, query, limit: int) -> list[UUID]:  # noqa: ANN001
    return list(session.scalars(query.order_by(AgencyBilling.agency_id).limit(limit)))


# Run `step` for each agency of `query` in its own transaction under the agency lock (SKIP
# LOCKED: a busy agency waits for the next pass); the step returns whether it changed the
# agency. Returns the number changed.
def for_each_agency(
    engine: Engine,
    query,  # noqa: ANN001
    limit: int,
    step: Callable[[Session, Agency, AgencyBilling], bool],
) -> int:
    with Session(engine) as session:
        agencies = _due(session, query, limit)
    changed = 0
    for agency_id in agencies:
        with Session(engine) as session, session.begin():
            agency = lock_agency(session, agency_id, skip_locked=True)
            if agency is None:
                continue
            billing = session.get(
                AgencyBilling, agency_id, with_for_update=True, populate_existing=True
            )
            if billing is not None and step(session, agency, billing):
                changed += 1
    return changed


# Worker step 1 (design section 8): trials that ended without a subscription go on hold, and
# operator grants that ended follow the subscription or hold.
def end_trials_and_grants(engine: Engine, now: datetime, limit: int) -> dict[str, int]:
    def trial(session: Session, agency: Agency, billing: AgencyBilling) -> bool:
        if billing.standing != "trialing" or billing.trial_ends_at is None:
            return False
        if billing.trial_ends_at > now or agency.status == "closed":
            return False
        return apply(session, billing, on_hold(session, "trial_ended"), now)

    def granted(session: Session, agency: Agency, billing: AgencyBilling) -> bool:
        if (billing.standing, billing.reason) != GRANTED or billing.grant_ends_at is None:
            return False
        if billing.grant_ends_at > now or agency.status == "closed":
            return False
        return end_grant(session, billing, now)

    # Only agencies that the step can change are selected: a closed agency waiting for its
    # purge would otherwise keep its place at the head of every batch (R017C-01).
    trials = (
        select(AgencyBilling.agency_id)
        .join(Agency, Agency.id == AgencyBilling.agency_id)
        .where(
            AgencyBilling.standing == "trialing",
            AgencyBilling.trial_ends_at <= now,
            Agency.status != "closed",
        )
    )
    grants = (
        select(AgencyBilling.agency_id)
        .join(Agency, Agency.id == AgencyBilling.agency_id)
        .where(
            AgencyBilling.grant_ends_at.is_not(None),
            AgencyBilling.grant_ends_at <= now,
            Agency.status != "closed",
        )
    )
    return {
        "trials_ended": for_each_agency(engine, trials, limit, trial),
        "grants_ended": for_each_agency(engine, grants, limit, granted),
    }


# Worker step 4 (design section 8): the link-only trial_ending reminder for trials ending within
# three days, and the billing_hold message for holds without one, to every active, verified
# Owner (D11). The time is recorded even when the agency has no such Owner.
def send_messages(engine: Engine, settings: Settings, now: datetime, limit: int) -> dict[str, int]:
    def reminder(session: Session, agency: Agency, billing: AgencyBilling) -> bool:
        ends = billing.trial_ends_at
        if billing.standing != "trialing" or ends is None or billing.trial_reminded_at:
            return False
        if not now < ends <= now + TRIAL_REMINDER or agency.status != "active":
            return False
        notice = BillingNotice("trial_ending", agency.id, ends, ends)
        for email in owner_emails(session, agency.id):
            queue_billing_mail(session, settings, email, notice)
        billing.trial_reminded_at = now
        return True

    def hold(session: Session, agency: Agency, billing: AgencyBilling) -> bool:
        if billing.standing != "hold" or billing.hold_notified_at is not None:
            return False
        if agency.status != "active":
            return False
        notice = BillingNotice("billing_hold", agency.id, None, now + HOLD_MESSAGE_LIFETIME)
        for email in owner_emails(session, agency.id):
            queue_billing_mail(session, settings, email, notice)
        billing.hold_notified_at = now
        return True

    # Only active agencies are selected: a suspended or closing agency on hold is never
    # notified and would otherwise keep its place at the head of every batch, so no other
    # agency would receive its message (R017C-01). It is notified once it is active again.
    reminders = (
        select(AgencyBilling.agency_id)
        .join(Agency, Agency.id == AgencyBilling.agency_id)
        .where(
            AgencyBilling.standing == "trialing",
            AgencyBilling.trial_reminded_at.is_(None),
            AgencyBilling.trial_ends_at > now,
            AgencyBilling.trial_ends_at <= now + TRIAL_REMINDER,
            Agency.status == "active",
        )
    )
    holds = (
        select(AgencyBilling.agency_id)
        .join(Agency, Agency.id == AgencyBilling.agency_id)
        .where(
            AgencyBilling.standing == "hold",
            AgencyBilling.hold_notified_at.is_(None),
            Agency.status == "active",
        )
    )
    return {
        "trial_ending": for_each_agency(engine, reminders, limit, reminder),
        "billing_hold": for_each_agency(engine, holds, limit, hold),
    }


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def counts(items: Counter, names: tuple[str, ...]) -> dict[str, int]:
    return {name: int(items[name]) for name in names}
