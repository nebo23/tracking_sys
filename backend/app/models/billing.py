"""Platform billing of agencies (specification 017-C, D-103; design-017c.md section 3).

The platform's own subscriptions, separate from agency-client revenue (015): a price catalog
registered by the platform operator against the 017-A plans, one standing per agency, the
agency's Paddle subscriptions, its checkouts, the verified webhook events, the payments and
adjustments Paddle reports, and the provider actions of an agency closure. The standing acts
only through plan assignments (D5). Subscriptions, payments and adjustments stay after the
purge of a closed agency as financial records; the standing, checkouts, events and actions
are purged (D10).

Rows hold provider IDs, closed codes, amounts in cents, currencies and times only: never a
name, email, address, card or payment-method detail, invoice address, API key, webhook secret
or signature. Reference queries below are manual read-only diagnostics for an authorized
operator; replace the synthetic literals before use.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

PROVIDERS = ("paddle",)
INTERVALS = ("month", "year")
STANDINGS = ("complimentary", "trialing", "subscribed", "past_due", "hold")
STANDING_REASONS = {
    "complimentary": ("migration", "billing_disabled", "operator_grant"),
    "trialing": ("new_agency",),
    "subscribed": ("subscription_active", "payment_recovered"),
    "past_due": ("payment_failed",),
    "hold": ("trial_ended", "grant_ended", "subscription_canceled", "subscription_paused"),
}
SUBSCRIPTION_STATUSES = ("trialing", "active", "past_due", "paused", "canceled")
SCHEDULED_ACTIONS = ("cancel", "pause", "resume")
CANCEL_ORIGINS = ("owner", "closure", "provider")
CHECKOUT_STATUSES = ("open", "completed", "expired")
EVENT_SOURCES = ("webhook", "reconciliation")
EVENT_OUTCOMES = ("applied", "stale", "ignored", "unmatched")
EVENT_ERRORS = (
    "unknown_price",
    "unsupported_items",
    "binding_conflict",
    "invalid_payload",
    "agency_closed",
)
PAYMENT_STATUSES = ("draft", "ready", "billed", "paid", "completed", "canceled", "past_due")
PAYMENT_ORIGINS = (
    "api",
    "subscription_charge",
    "subscription_payment_method_change",
    "subscription_recurring",
    "subscription_update",
    "web",
)
ADJUSTMENT_ACTIONS = (
    "credit",
    "refund",
    "chargeback",
    "chargeback_reverse",
    "chargeback_warning",
    "chargeback_warning_reverse",
    "credit_reverse",
)
ADJUSTMENT_STATUSES = ("pending_approval", "approved", "rejected", "reversed")
# Each provider action has one reason (D10).
ACTION_REASONS = {
    "cancel_next_period": "closure_requested",
    "remove_scheduled_cancel": "closure_cancelled",
    "cancel_now": "closure_completed",
}
ACTION_STATUSES = ("pending", "done", "failed", "skipped")
MAX_AMOUNT_CENTS = 100_000_000
CHECKOUT_LIFETIME = "24 hours"
PRIMARY = "NOT duplicate AND status <> 'canceled'"


def listed(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


# A Paddle ID: its prefix, an underscore and 26 lowercase letters or digits (V-6, V-12).
def paddle_id(column: str, prefix: str, *, nullable: bool = False) -> str:
    rule = column + " ~ '^" + prefix + "_[a-z0-9]{26}$'"
    return f"{column} IS NULL OR {rule}" if nullable else rule


def _time(*, nullable: bool = True, default: bool = False) -> Any:
    return mapped_column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=func.now() if default else None,
    )


# One registered price of a plan (D3). Immutable apart from the offer state; retirement is
# final. A plan has at most one offered monthly and one offered annual price.
# SELECT id, plan_id, provider_price_id, currency, amount_cents, billing_interval, offered,
#        registered_at, retired_at
# FROM public.billing_prices ORDER BY registered_at, id;
class BillingPrice(Base):
    __tablename__ = "billing_prices"
    __table_args__ = (
        UniqueConstraint("provider", "provider_price_id", name="uq_billing_prices_provider_price"),
        Index(
            "uq_billing_prices_offered",
            "plan_id",
            "billing_interval",
            unique=True,
            postgresql_where=text("offered"),
        ),
        Index("ix_billing_prices_plan_id", "plan_id"),
        CheckConstraint(listed("provider", PROVIDERS), name="valid_provider"),
        CheckConstraint(paddle_id("provider_price_id", "pri"), name="valid_price_id"),
        CheckConstraint("currency = 'USD'", name="valid_currency"),
        CheckConstraint(f"amount_cents BETWEEN 1 AND {MAX_AMOUNT_CENTS}", name="valid_amount"),
        CheckConstraint(listed("billing_interval", INTERVALS), name="valid_interval"),
        CheckConstraint(
            "offered = (retired_at IS NULL) "
            "AND (retired_at IS NULL OR retired_at >= registered_at)",
            name="retirement",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("saas_plans.id"))
    provider: Mapped[str] = mapped_column(String(16))
    provider_price_id: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    billing_interval: Mapped[str] = mapped_column(String(8))
    offered: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    registered_at: Mapped[datetime] = _time(nullable=False, default=True)
    retired_at: Mapped[datetime | None] = _time()


# The billing standing of one agency (D5): it acts only through the agency's plan assignments.
# SELECT agency_id, standing, reason, trial_ends_at, trial_reminded_at, grant_ends_at,
#        hold_started_at, hold_notified_at, version, updated_at
# FROM public.agency_billing WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid;
class AgencyBilling(Base):
    __tablename__ = "agency_billing"
    __table_args__ = (
        Index(
            "ix_agency_billing_trial",
            "trial_ends_at",
            postgresql_where=text("standing = 'trialing'"),
        ),
        Index(
            "ix_agency_billing_grant",
            "grant_ends_at",
            postgresql_where=text("grant_ends_at IS NOT NULL"),
        ),
        Index(
            "ix_agency_billing_hold",
            "hold_started_at",
            postgresql_where=text("standing = 'hold'"),
        ),
        CheckConstraint(listed("standing", STANDINGS), name="valid_standing"),
        CheckConstraint(
            " OR ".join(
                f"(standing = '{standing}' AND {listed('reason', reasons)})"
                for standing, reasons in STANDING_REASONS.items()
            ),
            name="reason_matches",
        ),
        CheckConstraint(
            "(standing <> 'trialing' OR trial_ends_at IS NOT NULL) "
            "AND (trial_reminded_at IS NULL OR trial_ends_at IS NOT NULL)",
            name="trial",
        ),
        CheckConstraint(
            "(standing = 'hold') = (hold_started_at IS NOT NULL) "
            "AND (hold_notified_at IS NULL OR hold_started_at IS NOT NULL)",
            name="hold",
        ),
        CheckConstraint(
            "grant_ends_at IS NULL OR (standing = 'complimentary' AND reason = 'operator_grant')",
            name="grant",
        ),
        CheckConstraint(
            paddle_id("provider_customer_id", "ctm", nullable=True), name="valid_customer_id"
        ),
        CheckConstraint("version >= 1", name="positive_version"),
    )

    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"), primary_key=True)
    standing: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(24))
    trial_ends_at: Mapped[datetime | None] = _time()
    trial_reminded_at: Mapped[datetime | None] = _time()
    grant_ends_at: Mapped[datetime | None] = _time()
    hold_started_at: Mapped[datetime | None] = _time()
    hold_notified_at: Mapped[datetime | None] = _time()
    provider_customer_id: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = _time(nullable=False, default=True)
    updated_at: Mapped[datetime] = _time(nullable=False, default=True)


# One Paddle subscription of an agency; kept after the purge as a financial record (D10). At
# most one primary subscription of an agency has not ended; a second one is a duplicate.
# SELECT id, provider_subscription_id, status, price_id, current_period_ends_at,
#        next_billed_at, scheduled_action, scheduled_at, cancel_origin, duplicate,
#        last_event_at, reconciled_at
# FROM public.agency_subscriptions
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid ORDER BY created_at, id;
class AgencySubscription(Base):
    __tablename__ = "agency_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_subscription_id",
            name="uq_agency_subscriptions_provider_subscription",
        ),
        UniqueConstraint("agency_id", "id", name="uq_agency_subscriptions_scope"),
        Index(
            "uq_agency_subscriptions_primary",
            "agency_id",
            unique=True,
            postgresql_where=text(PRIMARY),
        ),
        Index("ix_agency_subscriptions_agency", "agency_id", "created_at"),
        Index(
            "ix_agency_subscriptions_reconcile",
            "reconciled_at",
            postgresql_where=text("status <> 'canceled'"),
        ),
        CheckConstraint(listed("provider", PROVIDERS), name="valid_provider"),
        CheckConstraint(paddle_id("provider_subscription_id", "sub"), name="valid_subscription_id"),
        CheckConstraint(
            paddle_id("provider_transaction_id", "txn", nullable=True),
            name="valid_transaction_id",
        ),
        CheckConstraint(
            paddle_id("provider_price_id", "pri", nullable=True), name="valid_price_id"
        ),
        CheckConstraint(listed("status", SUBSCRIPTION_STATUSES), name="valid_status"),
        CheckConstraint(
            f"scheduled_action IS NULL OR {listed('scheduled_action', SCHEDULED_ACTIONS)}",
            name="valid_scheduled_action",
        ),
        CheckConstraint("(scheduled_action IS NULL) = (scheduled_at IS NULL)", name="scheduled"),
        CheckConstraint(
            f"cancel_origin IS NULL OR {listed('cancel_origin', CANCEL_ORIGINS)}",
            name="valid_cancel_origin",
        ),
        CheckConstraint(
            "current_period_ends_at IS NULL OR current_period_starts_at IS NULL "
            "OR current_period_ends_at >= current_period_starts_at",
            name="period",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    provider: Mapped[str] = mapped_column(String(16))
    provider_subscription_id: Mapped[str] = mapped_column(String(32))
    provider_transaction_id: Mapped[str | None] = mapped_column(String(32))
    price_id: Mapped[UUID | None] = mapped_column(ForeignKey("billing_prices.id"))
    provider_price_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    current_period_starts_at: Mapped[datetime | None] = _time()
    current_period_ends_at: Mapped[datetime | None] = _time()
    next_billed_at: Mapped[datetime | None] = _time()
    scheduled_action: Mapped[str | None] = mapped_column(String(8))
    scheduled_at: Mapped[datetime | None] = _time()
    cancel_origin: Mapped[str | None] = mapped_column(String(16))
    canceled_at: Mapped[datetime | None] = _time()
    duplicate: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    last_event_at: Mapped[datetime] = _time(nullable=False)
    reconciled_at: Mapped[datetime | None] = _time()
    created_at: Mapped[datetime] = _time(nullable=False, default=True)
    updated_at: Mapped[datetime] = _time(nullable=False, default=True)


# One checkout of an agency (D6): the Paddle transaction that Paddle.js opens. At most one is
# open per agency; a checkout lives 24 hours.
# SELECT id, price_id, requested_by_membership_id, provider_transaction_id, status, created_at,
#        expires_at, completed_at
# FROM public.billing_checkouts
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid ORDER BY created_at DESC;
class BillingCheckout(Base):
    __tablename__ = "billing_checkouts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "requested_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name="fk_billing_checkouts_requested_by_agency_memberships",
        ),
        UniqueConstraint(
            "provider_transaction_id", name="uq_billing_checkouts_provider_transaction"
        ),
        Index(
            "uq_billing_checkouts_open",
            "agency_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_billing_checkouts_agency", "agency_id", "created_at"),
        Index("ix_billing_checkouts_expires_at", "expires_at"),
        CheckConstraint(paddle_id("provider_transaction_id", "txn"), name="valid_transaction_id"),
        CheckConstraint(listed("status", CHECKOUT_STATUSES), name="valid_status"),
        CheckConstraint(
            "expires_at > created_at "
            f"AND expires_at <= created_at + interval '{CHECKOUT_LIFETIME}'",
            name="lifetime",
        ),
        CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)", name="completion"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    price_id: Mapped[UUID] = mapped_column(ForeignKey("billing_prices.id"))
    requested_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    provider_transaction_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), server_default="open")
    created_at: Mapped[datetime] = _time(nullable=False, default=True)
    expires_at: Mapped[datetime] = _time(nullable=False)
    completed_at: Mapped[datetime | None] = _time()


# One verified Paddle event, or one reconciliation, stored once by its event ID (D7). Only
# allowlisted fields are kept (design section 5.3).
# SELECT provider_event_id, source, event_type, occurred_at, received_at, outcome, error_code,
#        provider_subscription_id, provider_transaction_id
# FROM public.billing_events WHERE outcome = 'unmatched' ORDER BY received_at DESC LIMIT 100;
class BillingEvent(Base):
    __tablename__ = "billing_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "subscription_id"],
            ["agency_subscriptions.agency_id", "agency_subscriptions.id"],
            name="fk_billing_events_agency_subscriptions",
        ),
        UniqueConstraint("provider", "provider_event_id", name="uq_billing_events_provider_event"),
        Index("ix_billing_events_received_at", "received_at"),
        Index("ix_billing_events_agency", "agency_id", "occurred_at"),
        Index(
            "ix_billing_events_unmatched",
            "received_at",
            postgresql_where=text("outcome = 'unmatched'"),
        ),
        CheckConstraint(listed("provider", PROVIDERS), name="valid_provider"),
        CheckConstraint(
            "(source = 'webhook' AND provider_event_id ~ '^evt_[a-z0-9]{26}$') "
            "OR (source = 'reconciliation' AND provider_event_id ~ '^rec_[0-9a-f]{32}$')",
            name="valid_event_id",
        ),
        CheckConstraint("event_type ~ '^[a-z_]{1,24}[.][a-z_]{1,23}$'", name="valid_event_type"),
        CheckConstraint(listed("outcome", EVENT_OUTCOMES), name="valid_outcome"),
        CheckConstraint(
            f"error_code IS NULL OR {listed('error_code', EVENT_ERRORS)}", name="valid_error"
        ),
        CheckConstraint(
            "(outcome <> 'unmatched' OR agency_id IS NULL) "
            "AND (outcome NOT IN ('applied', 'stale') OR agency_id IS NOT NULL)",
            name="agency",
        ),
        CheckConstraint(
            paddle_id("provider_subscription_id", "sub", nullable=True),
            name="valid_subscription_id",
        ),
        CheckConstraint(
            paddle_id("provider_transaction_id", "txn", nullable=True),
            name="valid_transaction_id",
        ),
        CheckConstraint("jsonb_typeof(fields) = 'object'", name="fields_object"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(16))
    provider_event_id: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(48))
    occurred_at: Mapped[datetime] = _time(nullable=False)
    received_at: Mapped[datetime] = _time(nullable=False, default=True)
    agency_id: Mapped[UUID | None] = mapped_column(ForeignKey("agencies.id"))
    subscription_id: Mapped[UUID | None] = mapped_column(Uuid)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(32))
    provider_transaction_id: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(32))
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


# One Paddle transaction of an agency (D11); kept after the purge as a financial record.
# SELECT provider_transaction_id, status, origin, currency, subtotal_cents, tax_cents,
#        total_cents, billed_at, invoice_number
# FROM public.billing_payments
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid ORDER BY created_at DESC;
class BillingPayment(Base):
    __tablename__ = "billing_payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "subscription_id"],
            ["agency_subscriptions.agency_id", "agency_subscriptions.id"],
            name="fk_billing_payments_agency_subscriptions",
        ),
        UniqueConstraint(
            "provider_transaction_id", name="uq_billing_payments_provider_transaction"
        ),
        UniqueConstraint("agency_id", "id", name="uq_billing_payments_scope"),
        Index("ix_billing_payments_agency", "agency_id", "created_at", "id"),
        CheckConstraint(paddle_id("provider_transaction_id", "txn"), name="valid_transaction_id"),
        CheckConstraint(listed("status", PAYMENT_STATUSES), name="valid_status"),
        CheckConstraint(
            f"origin IS NULL OR {listed('origin', PAYMENT_ORIGINS)}", name="valid_origin"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="valid_currency"),
        CheckConstraint(
            "subtotal_cents >= 0 AND tax_cents >= 0 AND total_cents >= 0", name="amounts"
        ),
        CheckConstraint(
            "invoice_number IS NULL OR invoice_number ~ '^[A-Za-z0-9-]{1,64}$'",
            name="valid_invoice_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    subscription_id: Mapped[UUID | None] = mapped_column(Uuid)
    provider_transaction_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    origin: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3))
    subtotal_cents: Mapped[int] = mapped_column(BigInteger)
    tax_cents: Mapped[int] = mapped_column(BigInteger)
    total_cents: Mapped[int] = mapped_column(BigInteger)
    billed_at: Mapped[datetime | None] = _time()
    invoice_number: Mapped[str | None] = mapped_column(String(64))
    last_event_at: Mapped[datetime] = _time(nullable=False)
    created_at: Mapped[datetime] = _time(nullable=False, default=True)
    updated_at: Mapped[datetime] = _time(nullable=False, default=True)


# One Paddle adjustment (a refund, credit or chargeback) of an agency's transaction (D11);
# kept after the purge. It never changes a standing (D9).
# SELECT provider_adjustment_id, provider_transaction_id, action, status, currency,
#        total_cents
# FROM public.billing_adjustments
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid ORDER BY created_at DESC;
class BillingAdjustment(Base):
    __tablename__ = "billing_adjustments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "payment_id"],
            ["billing_payments.agency_id", "billing_payments.id"],
            name="fk_billing_adjustments_billing_payments",
        ),
        UniqueConstraint(
            "provider_adjustment_id", name="uq_billing_adjustments_provider_adjustment"
        ),
        Index("ix_billing_adjustments_payment", "agency_id", "payment_id"),
        Index("ix_billing_adjustments_transaction", "provider_transaction_id"),
        CheckConstraint(paddle_id("provider_adjustment_id", "adj"), name="valid_adjustment_id"),
        CheckConstraint(paddle_id("provider_transaction_id", "txn"), name="valid_transaction_id"),
        CheckConstraint(listed("action", ADJUSTMENT_ACTIONS), name="valid_action"),
        CheckConstraint(listed("status", ADJUSTMENT_STATUSES), name="valid_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="valid_currency"),
        CheckConstraint("total_cents >= 0", name="amount"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    payment_id: Mapped[UUID | None] = mapped_column(Uuid)
    provider_adjustment_id: Mapped[str] = mapped_column(String(32))
    provider_transaction_id: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    currency: Mapped[str] = mapped_column(String(3))
    total_cents: Mapped[int] = mapped_column(BigInteger)
    last_event_at: Mapped[datetime] = _time(nullable=False)
    created_at: Mapped[datetime] = _time(nullable=False, default=True)
    updated_at: Mapped[datetime] = _time(nullable=False, default=True)


# One provider action of an agency closure (D10), executed by the billing worker with bounded
# retries, never inside the closure's own transaction.
# SELECT id, subscription_id, action, reason, status, attempts, next_attempt_at, last_error,
#        created_at, completed_at
# FROM public.billing_actions
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid ORDER BY created_at, id;
class BillingAction(Base):
    __tablename__ = "billing_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "subscription_id"],
            ["agency_subscriptions.agency_id", "agency_subscriptions.id"],
            name="fk_billing_actions_agency_subscriptions",
        ),
        Index(
            "ix_billing_actions_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_billing_actions_subscription",
            "subscription_id",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_billing_actions_agency", "agency_id", "created_at"),
        CheckConstraint(
            " OR ".join(
                f"(action = '{action}' AND reason = '{reason}')"
                for action, reason in ACTION_REASONS.items()
            ),
            name="valid_action",
        ),
        CheckConstraint(listed("status", ACTION_STATUSES), name="valid_status"),
        CheckConstraint("attempts BETWEEN 0 AND 20", name="attempts"),
        CheckConstraint("(status = 'pending') = (completed_at IS NULL)", name="completion"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(ForeignKey("agencies.id"))
    subscription_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = _time(nullable=False, default=True)
    last_error: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _time(nullable=False, default=True)
    completed_at: Mapped[datetime | None] = _time()
