"""Platform operator administration of billing: python -m app.agency_billing.

Specification 017-C (D-103, decision D12; specs/017-saas-lifecycle/design-017c.md section 9).
The platform operator registers and retires prices, reads an agency's billing, grants
complimentary periods (for example a bank transfer or a partner), ends them, extends trials and
lists standings. There is no web interface: the command runs outside the agency roles, as
tracking_app with the application settings. Every change needs --confirm and allowed billing
(TRACKING_BILLING_ENABLED and a current paddle.billing rule), takes the agency's row lock or the
plan lock, and writes an audit event whose actor is the platform operator.

Usage:
  python -m app.agency_billing prices
  python -m app.agency_billing register-price --plan K --price-id pri_... --amount-cents N
      --interval month|year [--replaces pri_...] --confirm
  python -m app.agency_billing retire-price --price-id pri_... --confirm
  python -m app.agency_billing status --agency <uuid>
  python -m app.agency_billing grant --agency <uuid> --plan K [--until <ISO time>] --confirm
  python -m app.agency_billing end-grant --agency <uuid> --confirm
  python -m app.agency_billing extend-trial --agency <uuid> --days N --confirm
  python -m app.agency_billing agencies [--standing S] [--held-days N] [--after <uuid>]
      [--limit N]

Output is one JSON document with IDs, plan keys, amounts, closed codes and times only: never an
agency or client name, a person, an email, a token or a secret. A refusal prints
{"error": code} and exits with 1.
"""

import argparse
import json
import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agency_plans import PLAN_LOCK_KEY, PLAN_LOCK_NAMESPACE
from app.billing.paddle import PaddleClient, ProviderError, build_billing_provider
from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.models import (
    Agency,
    AgencyBilling,
    AgencySubscription,
    AuditEvent,
    BillingAction,
    BillingCheckout,
    BillingPayment,
    BillingPrice,
    SaasPlan,
)
from app.models.billing import INTERVALS, MAX_AMOUNT_CENTS, STANDINGS
from app.services import billing, plans

PRICE_ID = re.compile(r"pri_[a-z0-9]{26}")
PLAN_KEY = re.compile(r"[a-z][a-z0-9_-]{1,31}")
CHANGES = frozenset({"register-price", "retire-price", "grant", "end-grant", "extend-trial"})
LISTINGS = frozenset({"prices", "status", "agencies"})


class Refused(Exception):
    """A refusal with a closed code, printed as {"error": code} and any detail."""

    def __init__(self, code: str, **detail: Any) -> None:
        self.code, self.detail = code, detail
        super().__init__(code)


def _price_id(value: str) -> str:
    if not PRICE_ID.fullmatch(value):
        raise argparse.ArgumentTypeError("use Paddle's price ID (pri_ and 26 characters)")
    return value


def _key(value: str) -> str:
    if not PLAN_KEY.fullmatch(value):
        raise argparse.ArgumentTypeError("use 2-32 lowercase letters, digits, - or _")
    return value


def _bounded(low: int, high: int):  # noqa: ANN202
    def parse(value: str) -> int:
        if not value.isascii() or not value.isdigit() or not low <= int(value) <= high:
            raise argparse.ArgumentTypeError(f"use {low}-{high}")
        return int(value)

    return parse


def _until(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use an ISO 8601 time with its offset") from error
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError("use an ISO 8601 time with its offset")
    return moment


def _audit(
    session: Session,
    action: str,
    resource_type: str,
    resource_id: UUID,
    agency_id: UUID | None = None,
) -> None:
    session.flush()
    session.add(
        AuditEvent(
            id=uuid4(),
            agency_id=agency_id,
            actor_kind="platform_operator",
            actor_user_id=None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )
    session.flush()


def _plan(session: Session, key: str) -> SaasPlan:
    plan = session.scalar(select(SaasPlan).where(SaasPlan.key == key))
    if plan is None:
        raise Refused("plan_not_found")
    if plan.key == plans.HOLD_PLAN:
        raise Refused("reserved_plan")
    return plan


def _price_view(price: BillingPrice, plan_key: str) -> dict[str, Any]:
    return {
        "id": str(price.id),
        "plan": plan_key,
        "provider_price_id": price.provider_price_id,
        "amount_cents": price.amount_cents,
        "currency": price.currency,
        "interval": price.billing_interval,
        "offered": price.offered,
        "registered_at": billing.iso(price.registered_at),
        "retired_at": billing.iso(price.retired_at),
    }


def list_prices(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(BillingPrice, SaasPlan.key)
        .join(SaasPlan, SaasPlan.id == BillingPrice.plan_id)
        .order_by(BillingPrice.registered_at, BillingPrice.id)
    )
    return [_price_view(price, key) for price, key in rows]


def _locked_price(session: Session, provider_price_id: str) -> BillingPrice | None:
    return session.scalar(
        select(BillingPrice)
        .where(BillingPrice.provider_price_id == provider_price_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


# Register a Paddle price against a plan (D3). Paddle's own price must be active, in USD, of
# the same amount and of a one-month or one-year cycle. --replaces retires the offered price of
# the same plan and interval in the same transaction; without it, an offered price refuses.
def register_price(
    session: Session,
    provider: PaddleClient,
    *,
    plan_key: str,
    price_id: str,
    amount_cents: int,
    interval: str,
    replaces: str | None,
) -> dict[str, Any]:
    plan = _plan(session, plan_key)
    try:
        snapshot = provider.get_price(price_id)
    except ProviderError as error:
        raise Refused("provider_unavailable", provider_code=error.code) from None
    for field, matches in (
        ("status", snapshot.status == "active"),
        ("currency", snapshot.currency == "USD"),
        ("amount", snapshot.amount_cents == amount_cents),
        ("interval", snapshot.interval == interval and snapshot.frequency == 1),
    ):
        if not matches:
            raise Refused("price_mismatch", field=field)
    session.execute(select(func.pg_advisory_xact_lock(PLAN_LOCK_NAMESPACE, PLAN_LOCK_KEY)))
    if session.scalar(select(BillingPrice.id).where(BillingPrice.provider_price_id == price_id)):
        raise Refused("price_exists")
    offered = session.scalar(
        select(BillingPrice)
        .where(
            BillingPrice.plan_id == plan.id,
            BillingPrice.billing_interval == interval,
            BillingPrice.offered.is_(True),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = billing.database_now(session)
    if offered is not None:
        if replaces != offered.provider_price_id:
            raise Refused("price_offered", price_id=offered.provider_price_id)
        offered.offered, offered.retired_at = False, now
        _audit(session, "billing_price.retired", "billing_price", offered.id)
    elif replaces is not None:
        raise Refused("price_not_found")
    price = BillingPrice(
        id=uuid4(),
        plan_id=plan.id,
        provider="paddle",
        provider_price_id=price_id,
        currency="USD",
        amount_cents=amount_cents,
        billing_interval=interval,
        offered=True,
    )
    session.add(price)
    session.flush()
    _audit(session, "billing_price.registered", "billing_price", price.id)
    session.refresh(price)
    return _price_view(price, plan.key)


def retire_price(session: Session, *, price_id: str) -> dict[str, Any]:
    price = _locked_price(session, price_id)
    if price is None:
        raise Refused("price_not_found")
    if not price.offered:
        raise Refused("price_retired")
    price.offered, price.retired_at = False, billing.database_now(session)
    _audit(session, "billing_price.retired", "billing_price", price.id)
    key = session.scalar(select(SaasPlan.key).where(SaasPlan.id == price.plan_id))
    return _price_view(price, str(key))


def _standing_view(item: AgencyBilling, plan_key: str | None = None) -> dict[str, Any]:
    view: dict[str, Any] = {
        "agency_id": str(item.agency_id),
        "standing": item.standing,
        "reason": item.reason,
        "trial_ends_at": billing.iso(item.trial_ends_at),
        "trial_reminded_at": billing.iso(item.trial_reminded_at),
        "grant_ends_at": billing.iso(item.grant_ends_at),
        "hold_started_at": billing.iso(item.hold_started_at),
        "hold_notified_at": billing.iso(item.hold_notified_at),
        "version": item.version,
    }
    if plan_key is not None:
        view["plan"] = plan_key
    return view


def _locked(session: Session, agency_id: UUID) -> tuple[Agency, AgencyBilling]:
    agency = billing.lock_agency(session, agency_id)
    item = None if agency is None else billing.standing_of(session, agency_id)
    if agency is None or (item is None and agency.purged_at is None):
        raise Refused("agency_not_found")
    if agency.status == "closed" or item is None:
        raise Refused("agency_closed")
    return agency, item


def _plan_key(session: Session, agency_id: UUID) -> str:
    return plans.current_plan(session, agency_id).plan.key


def grant(session: Session, *, agency_id: UUID, plan_key: str, until: datetime | None):
    _, item = _locked(session, agency_id)
    plan = _plan(session, plan_key)
    now = billing.database_now(session)
    if until is not None and until <= now:
        raise Refused("invalid_until")
    billing.grant(session, item, plan, until, now)
    _audit(session, "billing.granted", "agency_billing", agency_id, agency_id)
    return _standing_view(item, _plan_key(session, agency_id))


def end_grant(session: Session, *, agency_id: UUID) -> dict[str, Any]:
    _, item = _locked(session, agency_id)
    if (item.standing, item.reason) != billing.GRANTED:
        raise Refused("not_granted", standing=item.standing)
    billing.end_grant(session, item, billing.database_now(session))
    _audit(session, "billing.grant_ended", "agency_billing", agency_id, agency_id)
    return _standing_view(item, _plan_key(session, agency_id))


def extend_trial(session: Session, *, agency_id: UUID, days: int) -> dict[str, Any]:
    _, item = _locked(session, agency_id)
    if item.standing != "trialing":
        raise Refused("not_trialing", standing=item.standing)
    billing.extend_trial(item, days, billing.database_now(session))
    _audit(session, "billing.trial_extended", "agency_billing", agency_id, agency_id)
    return _standing_view(item, _plan_key(session, agency_id))


def _subscription_view(item: AgencySubscription) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "provider_subscription_id": item.provider_subscription_id,
        "status": item.status,
        "price_id": None if item.price_id is None else str(item.price_id),
        "provider_price_id": item.provider_price_id,
        "current_period_ends_at": billing.iso(item.current_period_ends_at),
        "next_billed_at": billing.iso(item.next_billed_at),
        "scheduled_action": item.scheduled_action,
        "scheduled_at": billing.iso(item.scheduled_at),
        "cancel_origin": item.cancel_origin,
        "duplicate": item.duplicate,
        "last_event_at": billing.iso(item.last_event_at),
        "reconciled_at": billing.iso(item.reconciled_at),
    }


# The operator's view of one agency (D12): IDs, codes, amounts and times only.
def status(session: Session, *, agency_id: UUID) -> dict[str, Any]:
    agency = session.get(Agency, agency_id, populate_existing=True)
    if agency is None:
        raise Refused("agency_not_found")
    item = billing.standing_of(session, agency_id)
    subscriptions = session.scalars(
        select(AgencySubscription)
        .where(AgencySubscription.agency_id == agency_id)
        .order_by(AgencySubscription.created_at, AgencySubscription.id)
    )
    checkouts = session.scalars(
        select(BillingCheckout)
        .where(BillingCheckout.agency_id == agency_id)
        .order_by(BillingCheckout.created_at.desc(), BillingCheckout.id.desc())
        .limit(5)
    )
    actions = session.scalars(
        select(BillingAction)
        .where(BillingAction.agency_id == agency_id, BillingAction.status != "done")
        .order_by(BillingAction.created_at, BillingAction.id)
    )
    payment = session.scalar(
        select(BillingPayment)
        .where(BillingPayment.agency_id == agency_id)
        .order_by(BillingPayment.created_at.desc(), BillingPayment.id.desc())
        .limit(1)
    )
    return {
        "agency_id": str(agency_id),
        "status": agency.status,
        "billing": None if item is None else _standing_view(item, _plan_key(session, agency_id)),
        "subscriptions": [_subscription_view(row) for row in subscriptions],
        "checkouts": [
            {
                "id": str(row.id),
                "provider_transaction_id": row.provider_transaction_id,
                "status": row.status,
                "created_at": billing.iso(row.created_at),
                "expires_at": billing.iso(row.expires_at),
            }
            for row in checkouts
        ],
        "actions": [
            {
                "id": str(row.id),
                "action": row.action,
                "status": row.status,
                "attempts": row.attempts,
                "next_attempt_at": billing.iso(row.next_attempt_at),
                "last_error": row.last_error,
            }
            for row in actions
        ],
        "last_payment": None
        if payment is None
        else {
            "provider_transaction_id": payment.provider_transaction_id,
            "status": payment.status,
            "currency": payment.currency,
            "total_cents": payment.total_cents,
            "billed_at": billing.iso(payment.billed_at),
        },
    }


def list_agencies(
    session: Session,
    *,
    standing: str | None = None,
    held_days: int | None = None,
    after: UUID | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    now = billing.database_now(session)
    query = select(AgencyBilling).order_by(AgencyBilling.agency_id).limit(limit)
    if standing is not None:
        query = query.where(AgencyBilling.standing == standing)
    if held_days is not None:
        query = query.where(
            AgencyBilling.standing == "hold",
            AgencyBilling.hold_started_at <= now - timedelta(days=held_days),
        )
    if after is not None:
        query = query.where(AgencyBilling.agency_id > after)
    rows = list(session.scalars(query))
    views = []
    for row in rows:
        view = _standing_view(row, _plan_key(session, row.agency_id))
        if row.hold_started_at is not None:
            view["held_days"] = (now - row.hold_started_at).days
        views.append(view)
    following = str(rows[-1].agency_id) if len(rows) == limit else None
    return {"agencies": views, "next_after": following}


# Run one subcommand in its own transaction and return (exit code, JSON-ready result). Listings
# read one REPEATABLE READ snapshot; changes run under READ COMMITTED with their locks and need
# allowed billing.
def run(
    engine: Engine,
    settings: Settings,
    command: str,
    provider: PaddleClient | None = None,
    **options: Any,
) -> tuple[int, Any]:
    try:
        if command in LISTINGS:
            with engine.connect() as raw:
                connection = raw.execution_options(
                    isolation_level="REPEATABLE READ", postgresql_readonly=True
                )
                with Session(bind=connection) as session, session.begin():
                    if command == "prices":
                        return 0, list_prices(session)
                    if command == "status":
                        return 0, status(session, agency_id=options["agency"])
                    return 0, list_agencies(
                        session,
                        standing=options.get("standing"),
                        held_days=options.get("held_days"),
                        after=options.get("after"),
                        limit=options.get("limit", 100),
                    )
        with Session(engine, expire_on_commit=False) as session, session.begin():
            billing.require_billing(settings, billing.database_now(session).date())
            if command == "register-price":
                if provider is None:
                    raise Refused("billing_unavailable")
                return 0, register_price(
                    session,
                    provider,
                    plan_key=options["plan"],
                    price_id=options["price_id"],
                    amount_cents=options["amount_cents"],
                    interval=options["interval"],
                    replaces=options.get("replaces"),
                )
            if command == "retire-price":
                return 0, retire_price(session, price_id=options["price_id"])
            if command == "grant":
                return 0, grant(
                    session,
                    agency_id=options["agency"],
                    plan_key=options["plan"],
                    until=options.get("until"),
                )
            if command == "end-grant":
                return 0, end_grant(session, agency_id=options["agency"])
            if command == "extend-trial":
                return 0, extend_trial(session, agency_id=options["agency"], days=options["days"])
        raise ValueError("Unknown command.")
    except Refused as refusal:
        return 1, {"error": refusal.code, **refusal.detail}
    except billing.BillingRefused as refusal:
        return 1, {"error": refusal.code}
    except plans.PlanUnavailable:
        return 1, {"error": plans.PlanUnavailable.code}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="python -m app.agency_billing",
        description="Administer platform billing (platform operator).",
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("prices", help="List every registered price.")
    register = commands.add_parser("register-price", help="Register a Paddle price of a plan.")
    register.add_argument("--plan", required=True, type=_key)
    register.add_argument("--price-id", required=True, type=_price_id)
    register.add_argument(
        "--amount-cents", required=True, type=_bounded(1, MAX_AMOUNT_CENTS), metavar="N"
    )
    register.add_argument("--interval", required=True, choices=INTERVALS)
    register.add_argument("--replaces", type=_price_id, metavar="pri_...")
    retire = commands.add_parser("retire-price", help="Stop offering a price.")
    retire.add_argument("--price-id", required=True, type=_price_id)
    state = commands.add_parser("status", help="Show an agency's billing.")
    state.add_argument("--agency", required=True, type=UUID)
    give = commands.add_parser("grant", help="Grant a complimentary period on a plan.")
    give.add_argument("--agency", required=True, type=UUID)
    give.add_argument("--plan", required=True, type=_key)
    give.add_argument("--until", type=_until, metavar="ISO-TIME")
    end = commands.add_parser("end-grant", help="End an operator grant now.")
    end.add_argument("--agency", required=True, type=UUID)
    extend = commands.add_parser("extend-trial", help="Extend an agency's trial.")
    extend.add_argument("--agency", required=True, type=UUID)
    extend.add_argument("--days", required=True, type=_bounded(1, 30), metavar="1-30")
    listing = commands.add_parser("agencies", help="List billing standings.")
    listing.add_argument("--standing", choices=STANDINGS)
    listing.add_argument("--held-days", type=_bounded(0, 3650), metavar="N")
    listing.add_argument("--after", type=UUID)
    listing.add_argument("--limit", type=_bounded(1, 500), default=100, metavar="1-500")
    for name in CHANGES:
        commands.choices[name].add_argument("--confirm", action="store_true", help="Required.")
    return root


def options_of(args: argparse.Namespace) -> dict[str, Any]:
    names = (
        "agency",
        "plan",
        "price_id",
        "amount_cents",
        "interval",
        "replaces",
        "until",
        "days",
        "standing",
        "held_days",
        "after",
        "limit",
    )
    return {name: getattr(args, name) for name in names if hasattr(args, name)}


def main(argv: Sequence[str] | None = None) -> int:
    root = parser()
    args = root.parse_args(argv)
    if args.command in CHANGES and not args.confirm:
        root.error(f"--confirm is required to {args.command.replace('-', ' ')}.")
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        code, result = run(
            engine, settings, args.command, build_billing_provider(settings), **options_of(args)
        )
    finally:
        engine.dispose()
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
