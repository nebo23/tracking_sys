"""Shared synthetic setup for the 017-C billing tests (D-103; design-017c.md section 14).

A billing lab binds the authenticated world to an application whose settings enable billing
with synthetic Paddle credentials, an in-memory Paddle-shaped server (tests/paddle_api.py) as
its provider, the operator command and the worker. Nothing here reaches Paddle; every value is
synthetic.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from paddle_api import API_KEY, CLIENT_TOKEN, WEBHOOK_SECRET, PaddleApi
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import agency_billing, billing_worker
from app.billing.paddle import PaddleClient
from app.config import Settings
from app.models import AgencyBilling, AgencyPlanAssignment, SaasPlan


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


def make_billing_lab(world, api, **changes: Any) -> BillingLab:
    return BillingLab(world, api, PaddleApi(), billing_config(api.config, **changes))
