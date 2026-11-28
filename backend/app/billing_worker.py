"""Run one bounded billing pass: python -m app.billing_worker.

Specification 017-C (D-103 decisions D4, D5, D10, D11 and D7; design-017c.md section 8). As
tracking_app, the pass ends trials and operator grants that are due (each agency under its row
lock, a busy agency waits for the next pass), and queues the link-only trial_ending and
billing_hold messages for the agencies' active, verified Owners; the mail worker delivers them.
While billing is not allowed (TRACKING_BILLING_ENABLED off or the paddle.billing rule not
current) it prints {"status": "disabled"} and changes nothing. It prints counts only, never a
name, an email, a figure or a secret. It is not a scheduler: production scheduling is decided
in specification 020.
"""

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.billing.paddle import PaddleClient, build_billing_provider
from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.services import billing


def run_pass(
    engine: Engine,
    settings: Settings,
    provider: PaddleClient | None,
    *,
    limit: int = 25,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One bounded pass; `now` (the database clock by default) lets tests move time."""
    if not 1 <= limit <= 100:
        raise ValueError("The billing batch size must be between 1 and 100.")
    with Session(engine) as session:
        moment = now or billing.database_now(session)
    if not billing.billing_allowed(settings, moment.date()):
        return {"status": "disabled"}
    ended = billing.end_trials_and_grants(engine, moment, limit)
    return {
        "status": "completed",
        **ended,
        "messages": billing.send_messages(engine, settings, moment, limit),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.billing_worker",
        description="Run one bounded pass of platform billing.",
    )
    parser.add_argument("--limit", type=int, default=25, help="Items per step (1-100).")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100.")
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        result = run_pass(engine, settings, build_billing_provider(settings), limit=args.limit)
        print(json.dumps(result))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
