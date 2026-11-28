"""Shared synthetic setup for the 017-C billing tests (D-103; design-017c.md section 14).

A billing lab binds the authenticated world to an application whose settings enable billing
with synthetic Paddle credentials, an in-memory Paddle-shaped server (tests/paddle_api.py) as
its provider, the operator command and the worker. Nothing here reaches Paddle; every value is
synthetic.
"""

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from paddle_api import API_KEY, CLIENT_TOKEN, WEBHOOK_SECRET, PaddleApi, created, event, signed
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import agency_billing, billing_worker
from app.billing.paddle import PaddleClient
from app.config import Settings
from app.models import AgencyBilling, AgencyMembership, AgencyPlanAssignment, SaasPlan


def billing_config(config: Settings, **changes: Any) -> Settings:
    values = {
        "billing_enabled": True,
        "billing_paddle_api_key": SecretStr(API_KEY),
        "billing_paddle_webhook_secret": SecretStr(WEBHOOK_SECRET),
        "billing_paddle_client_token": CLIENT_TOKEN,
        **changes,
    }
    return Settings(_env_file=None, **(config.model_dump() | values))


def standing(db, agency: UUID) -> AgencyBilling | None:
    with Session(db.migration) as session:
        row = session.get(AgencyBilling, agency)
        if row is not None:
            session.expunge(row)
        return row


def current_plan(db, agency: UUID) -> tuple[str, int, str, str]:
    with Session(db.migration) as session:
        key, revision, by, reason = session.execute(
            select(
                SaasPlan.key,
                AgencyPlanAssignment.revision,
                AgencyPlanAssignment.assigned_by,
                AgencyPlanAssignment.reason,
            )
            .join(SaasPlan, SaasPlan.id == AgencyPlanAssignment.plan_id)
            .where(AgencyPlanAssignment.agency_id == agency)
            .order_by(AgencyPlanAssignment.revision.desc())
            .limit(1)
        ).one()
        return key, revision, by, reason


# Make an agency's standing a trial that ends at `ends` (synthetic time travel in the database).
def set_trial(db, agency: UUID, ends: datetime) -> None:
    with db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE agency_billing SET standing = 'trialing', reason = 'new_agency', "
                "trial_ends_at = :ends, trial_reminded_at = NULL, hold_started_at = NULL, "
                "hold_notified_at = NULL, grant_ends_at = NULL WHERE agency_id = :a"
            ),
            {"a": agency, "ends": ends},
        )


@dataclass
class BillingLab:
    w: Any
    api: Any
    paddle: PaddleApi
    config: Settings
    clients: dict[str, Any] = field(default_factory=dict)

    @property
    def provider(self) -> PaddleClient:
        return PaddleClient(API_KEY, "sandbox", self.paddle)

    # A browser client of a billing-enabled application, signed in as a world user.
    def browser(self, name: str, config: Settings | None = None):
        client = self.api.new_client(config or self.config)
        client.app.state.billing_provider = self.provider
        self.api.login(client, f"{name}@example.test")
        return client

    def command(self, command: str, **options: Any) -> tuple[int, Any]:
        return agency_billing.run(self.w.db.runtime, self.config, command, self.provider, **options)

    def worker(self, now: datetime | None = None, **options: Any) -> dict[str, Any]:
        return billing_worker.run_pass(
            self.w.db.runtime, self.config, self.provider, now=now, **options
        )

    # An unauthenticated client of the billing-enabled application (the webhook's caller).
    def hook(self):
        if "hook" not in self.clients:
            client = self.api.new_client(self.config)
            client.app.state.billing_provider = self.provider
            self.clients["hook"] = client
        return self.clients["hook"]

    # Deliver a payload as Paddle does, signed with the destination secret; header=False sends
    # no signature, a string replaces it.
    def deliver(
        self,
        payload: dict | bytes,
        *,
        secret: str = WEBHOOK_SECRET,
        ts: int | None = None,
        header: str | bool | None = None,
    ):
        body, signature = signed(payload, secret, ts)
        headers = {"Content-Type": "application/json"}
        if header is not False:
            headers["Paddle-Signature"] = signature if header is None else str(header)
        return self.hook().post("/billing/paddle/webhook", content=body, headers=headers)

    def delivered(self, payload: dict) -> None:
        response = self.deliver(payload)
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "received"}

    # A checkout as the owner route records it (P4): the Paddle transaction with our IDs in
    # custom_data, and the open checkout row of the agency.
    def open_checkout(self, agency: UUID, price: dict) -> tuple[UUID, str]:
        checkout_id = uuid4()
        transaction = self.provider.create_transaction(
            price["provider_price_id"],
            None,
            {"agency_id": str(agency), "checkout_id": str(checkout_id)},
        )
        with self.w.db.migration.begin() as connection:
            connection.execute(
                text(
                    "UPDATE billing_checkouts SET status = 'expired' "
                    "WHERE agency_id = :a AND status = 'open'"
                ),
                {"a": agency},
            )
            connection.execute(
                text(
                    "INSERT INTO billing_checkouts (id, agency_id, price_id, "
                    "requested_by_membership_id, provider_transaction_id, expires_at) VALUES "
                    "(:id, :a, :p, :m, :t, now() + interval '24 hours')"
                ),
                {
                    "id": checkout_id,
                    "a": agency,
                    "p": price["id"],
                    "m": owner_membership(self.w.db, agency),
                    "t": transaction,
                },
            )
        return checkout_id, transaction

    # The buyer pays the checkout and Paddle sends its events in the documented order (V-6):
    # transaction.paid, subscription.created, subscription.activated, transaction.completed.
    def pay(self, transaction: str, start: datetime | None = None) -> dict:
        subscription = self.paddle.pay(transaction)
        moment = start or datetime.now().astimezone()
        entity = self.paddle.transactions[transaction]
        paid = copy.deepcopy(entity)
        paid["status"] = "paid"
        for index, payload in enumerate(
            (
                event("transaction.paid", paid, occurred_at=moment),
                created(subscription, transaction, occurred_at=moment + timedelta(seconds=1)),
                event(
                    "subscription.activated",
                    subscription,
                    occurred_at=moment + timedelta(seconds=2),
                ),
                event("transaction.completed", entity, occurred_at=moment + timedelta(seconds=3)),
            )
        ):
            assert index < 4
            self.delivered(payload)
        return subscription

    def subscribe(self, agency: UUID, price: dict, start: datetime | None = None) -> dict:
        _, transaction = self.open_checkout(agency, price)
        return self.pay(transaction, start)

    # Register an offered price of a plan through the operator command; returns its view.
    def price(self, plan: str = "development", amount: int = 2900, interval: str = "month"):
        price_id = self.paddle.add_price(amount, interval)
        code, view = self.command(
            "register-price",
            plan=plan,
            price_id=price_id,
            amount_cents=amount,
            interval=interval,
        )
        assert code == 0, view
        return view


def owner_membership(db, agency: UUID) -> UUID:
    with Session(db.migration) as session:
        return session.scalar(
            select(AgencyMembership.id).where(
                AgencyMembership.agency_id == agency, AgencyMembership.role == "owner"
            )
        )


def database_now(db) -> datetime:
    with Session(db.migration) as session:
        return session.scalar(select(func.now()))


def make_billing_lab(world, api, **changes: Any) -> BillingLab:
    return BillingLab(world, api, PaddleApi(), billing_config(api.config, **changes))
