"""The billing of an agency for its Owners and Admins (017-C, D-103 D6, D8, D9 and D11).

Design-017c.md section 7. Owners act and Owners and Admins read, in an active agency; every other
role, agency or credential is refused with the uniform access denial. Billing must be allowed
(TRACKING_BILLING_ENABLED and a current paddle.billing rule), otherwise every call answers 503
billing_unavailable. A call to Paddle runs under the agency row lock that every agency mutation
takes first, so concurrent checkouts of one agency are serialized; a provider failure answers 503
billing_provider_unavailable and the request transaction rolls back, so nothing changes. Paddle's
refusals of a change (past due, locked within 30 minutes of a renewal, a pending scheduled change,
the hourly limit of immediate charges) answer 409 change_not_allowed.

The checkout is bound to the agency through its transaction ID (D6). Plan changes apply only when
Paddle's subscription.updated event arrives, never from this answer (D8). An invoice address is
fetched at request time and is never stored or logged (D11). Nothing here logs or returns a
card, a provider secret, a name or an email.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.paddle import PaddleClient, ProviderError
from app.config import Settings
from app.models import (
    AgencyMembership,
    AgencySubscription,
    BillingCheckout,
    BillingPayment,
    BillingPrice,
    SaasPlan,
)
from app.services import billing, plans
from app.services.tenancy import AccessDenied, Role, TenancyService

logger = logging.getLogger("tracking")
CHECKOUT_LIFETIME = timedelta(hours=24)
RENEWAL_LOCK = timedelta(minutes=30)
CANCELABLE = ("active", "trialing", "past_due")
# Paddle's refusals of a change of the subscription itself (V-8, V-9).
CHANGE_REFUSALS = frozenset(
    {"past_due", "subscription_locked", "pending_change", "change_limit", "subscription_canceled"}
)
T = TypeVar("T")


def offered_prices(session: Session) -> list[tuple[BillingPrice, SaasPlan]]:
    rows = session.execute(
        select(BillingPrice, SaasPlan)
        .join(SaasPlan, SaasPlan.id == BillingPrice.plan_id)
        .where(BillingPrice.offered.is_(True))
        .order_by(SaasPlan.key, BillingPrice.billing_interval, BillingPrice.amount_cents)
    )
    return [(price, plan) for price, plan in rows]


def plan_limits(plan: SaasPlan) -> dict[str, int | None]:
    return {name: getattr(plan, column) for name, column in plans.COLUMNS.items()}


def _locked_soon(subscription: AgencySubscription, now: datetime) -> bool:
    billed = subscription.next_billed_at
    return billed is not None and now >= billed - RENEWAL_LOCK


class BillingOwnerService(TenancyService):
    def __init__(
        self,
        session: Session,
        actor_user_id: UUID,
        settings: Settings,
        provider: PaddleClient | None,
    ) -> None:
        super().__init__(session, actor_user_id)
        self.settings, self.provider = settings, provider

    def _now(self) -> datetime:
        return billing.database_now(self.session)

    def _allowed(self) -> PaddleClient:
        billing.require_billing(self.settings, self._now().date())
        if self.provider is None:
            raise billing.BillingRefused("billing_unavailable", 503)
        return self.provider

    def _owner(self, agency_id: UUID, *, write: bool) -> AgencyMembership:
        member = self._membership(agency_id, write=write)
        if member.role != Role.OWNER:
            raise AccessDenied()
        return member

    def _call(self, call: Callable[[], T]) -> T:
        try:
            return call()
        except ProviderError as error:
            logger.warning("billing_provider_failed", extra={"billing_code": error.code})
            if error.code in CHANGE_REFUSALS:
                raise billing.BillingRefused("change_not_allowed", 409) from None
            raise billing.BillingRefused("billing_provider_unavailable", 503) from None

    def _primary(self, agency_id: UUID, *, lock: bool = False) -> AgencySubscription:
        subscription = billing.primary_subscription(self.session, agency_id)
        if subscription is None:
            raise billing.BillingRefused("not_subscribed", 409)
        if lock:
            self.session.refresh(subscription, with_for_update=True)
        return subscription

    def _offered(self, price_id: UUID) -> BillingPrice:
        price = self.session.get(BillingPrice, price_id, populate_existing=True)
        if price is None or not price.offered:
            raise billing.BillingRefused("price_not_offered", 409)
        return price

    # The offered prices for any signed-in user, with what Paddle.js needs (section 7).
    def prices(self) -> dict[str, Any]:
        self._allowed()
        self._active_user(self.actor_user_id)
        return {
            "environment": self.settings.billing_paddle_environment,
            "client_token": self.settings.billing_paddle_client_token or None,
            "prices": offered_prices(self.session),
        }

    # The agency's standing, plan, primary subscription and last payment (Owners and Admins).
    def view(self, agency_id: UUID) -> dict[str, Any]:
        self._allowed()
        self._manager(agency_id)
        standing = billing.standing_of(self.session, agency_id)
        if standing is None:
            raise AccessDenied()
        subscription = billing.primary_subscription(self.session, agency_id)
        price = None
        if subscription is not None and subscription.price_id is not None:
            price = self.session.get(BillingPrice, subscription.price_id)
        payment = self.session.scalar(
            select(BillingPayment)
            .where(BillingPayment.agency_id == agency_id)
            .order_by(BillingPayment.created_at.desc(), BillingPayment.id.desc())
            .limit(1)
        )
        return {
            "standing": standing,
            "plan": plans.current_plan(self.session, agency_id).plan,
            "subscription": subscription,
            "price": price,
            "payment": payment,
        }

    # D6: one open checkout per agency under the agency lock; the same price returns the open
    # checkout, another price or an expired one is replaced. Returns (checkout, created).
    def checkout(self, agency_id: UUID, price_id: UUID) -> tuple[BillingCheckout, bool]:
        provider = self._allowed()
        member = self._owner(agency_id, write=True)
        now = self._now()
        price = self._offered(price_id)
        live = self.session.scalar(
            select(AgencySubscription.id).where(
                AgencySubscription.agency_id == agency_id, AgencySubscription.status != "canceled"
            )
        )
        if live is not None:
            raise billing.BillingRefused("already_subscribed", 409)
        current = self.session.scalar(
            select(BillingCheckout)
            .where(BillingCheckout.agency_id == agency_id, BillingCheckout.status == "open")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is not None:
            if current.expires_at > now and current.price_id == price.id:
                return current, False
            current.status = "expired"
            self.session.flush()
        standing = billing.standing_of(self.session, agency_id)
        customer = None if standing is None else standing.provider_customer_id
        checkout_id = uuid4()
        transaction = self._call(
            lambda: provider.create_transaction(
                price.provider_price_id,
                customer,
                {"agency_id": str(agency_id), "checkout_id": str(checkout_id)},
            )
        )
        row = BillingCheckout(
            id=checkout_id,
            agency_id=agency_id,
            price_id=price.id,
            requested_by_membership_id=member.id,
            provider_transaction_id=transaction,
            status="open",
            created_at=now,
            expires_at=now + CHECKOUT_LIFETIME,
        )
        self.session.add(row)
        self._audit(agency_id, "billing.checkout_created", "billing_checkout", row.id)
        return row, True

    # D8: a preview changes nothing; a request is charged or credited by Paddle and the limits
    # follow its subscription.updated event. A lower amount of the same interval is a
    # downgrade, credited on the next bill; anything else is charged at once.
    def change(self, agency_id: UUID, price_id: UUID, *, preview: bool) -> dict[str, Any]:
        provider = self._allowed()
        self._owner(agency_id, write=True)
        subscription = self._primary(agency_id)
        now = self._now()
        if (
            subscription.status != "active"
            or subscription.scheduled_action is not None
            or _locked_soon(subscription, now)
            or subscription.price_id is None
        ):
            raise billing.BillingRefused("change_not_allowed", 409)
        price = self._offered(price_id)
        current = self.session.get(BillingPrice, subscription.price_id)
        assert current is not None
        if price.id == current.id:
            raise billing.BillingRefused("same_price", 409)
        downgrade = (
            price.billing_interval == current.billing_interval
            and price.amount_cents < current.amount_cents
        )
        mode = "prorated_next_billing_period" if downgrade else "prorated_immediately"
        target = subscription.provider_subscription_id
        if preview:
            result = self._call(
                lambda: provider.preview_update(target, price.provider_price_id, mode)
            )
            return {"proration": mode, "preview": result}
        self._call(lambda: provider.update_items(target, price.provider_price_id, mode))
        self._audit(
            agency_id, "billing.plan_change_requested", "agency_subscription", subscription.id
        )
        return {"proration": mode, "preview": None}

    # D9: cancel at the end of the paid period. An already scheduled cancellation is answered
    # without a call.
    def cancel(self, agency_id: UUID) -> tuple[str | None, datetime | None]:
        provider = self._allowed()
        self._owner(agency_id, write=True)
        subscription = self._primary(agency_id, lock=True)
        if subscription.status not in CANCELABLE:
            raise billing.BillingRefused("change_not_allowed", 409)
        if subscription.scheduled_action == "cancel":
            return subscription.scheduled_action, subscription.scheduled_at
        if _locked_soon(subscription, self._now()):
            raise billing.BillingRefused("change_not_allowed", 409)
        snapshot = self._call(
            lambda: provider.cancel(subscription.provider_subscription_id, immediately=False)
        )
        subscription.cancel_origin = "owner"
        self._audit(agency_id, "billing.cancel_scheduled", "agency_subscription", subscription.id)
        return snapshot.scheduled_action, snapshot.scheduled_at

    # D9: undo the scheduled cancellation before it takes effect.
    def undo_cancel(self, agency_id: UUID) -> None:
        provider = self._allowed()
        self._owner(agency_id, write=True)
        subscription = self._primary(agency_id, lock=True)
        if subscription.scheduled_action != "cancel" and subscription.cancel_origin is None:
            raise billing.BillingRefused("no_scheduled_cancel", 409)
        self._call(lambda: provider.remove_scheduled_change(subscription.provider_subscription_id))
        subscription.cancel_origin = None
        self._audit(agency_id, "billing.cancel_removed", "agency_subscription", subscription.id)

    # D9 (V-10): the transaction for Paddle.js to update the payment method.
    def payment_method(self, agency_id: UUID) -> str:
        provider = self._allowed()
        self._owner(agency_id, write=False)
        subscription = self._primary(agency_id)
        if subscription.status not in CANCELABLE:
            raise billing.BillingRefused("change_not_allowed", 409)
        return self._call(
            lambda: provider.payment_method_transaction(subscription.provider_subscription_id)
        )

    def payments(self, agency_id: UUID, *, limit: int, offset: int) -> list[BillingPayment]:
        self._allowed()
        self._manager(agency_id)
        return list(
            self.session.scalars(
                select(BillingPayment)
                .where(BillingPayment.agency_id == agency_id)
                .order_by(BillingPayment.created_at.desc(), BillingPayment.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    # D11: Paddle's temporary invoice address of a completed, non-zero payment; a payment of
    # another agency is refused like a missing one.
    def invoice(self, agency_id: UUID, payment_id: UUID) -> str:
        provider = self._allowed()
        self._manager(agency_id)
        payment = self.session.get(BillingPayment, payment_id)
        if payment is None or payment.agency_id != agency_id:
            raise AccessDenied()
        if not invoice_available(payment):
            raise billing.BillingRefused("invoice_unavailable", 409)
        return self._call(lambda: provider.invoice_url(payment.provider_transaction_id))


def invoice_available(payment: BillingPayment) -> bool:
    return payment.status == "completed" and payment.total_cents > 0
