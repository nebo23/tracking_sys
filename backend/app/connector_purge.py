"""Operator purge of every connection of one provider: python -m app.connector_purge.

Specification 011-C (D-060, entry review section 4.2). When the API access of a provider ends
(termination or suspension of the YouTube API Services, P-2 section 24.3), every connection of
that provider is disconnected with reason operator_purged and torn down at once: each
outstanding token is revoked where the adapter is still registered, the sealed material is
destroyed and the provider data are purged. The teardown deadline is the time of the purge,
also for teardowns already under way, so that a revocation that cannot be made no longer
delays the deletion. Turning the adapter's setting off is the kill switch that stops further
connects and reads; the purge then completes without revoking.

Usage: python -m app.connector_purge --provider youtube --confirm
Only outcome counts are printed, never an account, label or token.
"""

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.contracts import ConnectorProvider
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.models import ConnectorConnection
from app.security import now_utc
from app.services.connectors import LIVE, build_providers, run_teardowns, start_disconnect

PURGEABLE = ("youtube", "synthetic_youtube")
BATCH = 100


# Start the disconnect of every live connection of the provider, and bring forward the
# deadline of its teardowns already under way, both to the time of the purge; then run
# teardowns until a pass completes none. Returns outcome counts: stopped (live connections
# disconnected), expedited (teardowns under way), the teardown outcomes, and remaining (the
# provider's connections still disconnecting because a running worker holds their teardown,
# which that worker or a repeated purge completes).
def purge_provider(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    provider: str,
    now: datetime | None = None,
) -> dict[str, int]:
    moment = now or now_utc()
    counts = {"stopped": 0, "expedited": 0}
    with Session(engine) as session, session.begin():
        targets = session.scalars(
            select(ConnectorConnection)
            .where(
                ConnectorConnection.provider == provider,
                ConnectorConnection.status.in_((*LIVE, "disconnecting")),
            )
            .order_by(ConnectorConnection.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for connection in targets:
            if connection.status == "disconnecting":
                counts["expedited"] += 1
            else:
                start_disconnect(session, settings, connection, "operator_purged", moment)
                counts["stopped"] += 1
            # A deadline only moves earlier, so no teardown waits for a revocation.
            due = connection.purge_due_at
            connection.purge_due_at = moment if due is None else min(due, moment)
    while True:
        result = run_teardowns(engine, settings, registry, limit=BATCH, now=now)
        for name, value in result.items():
            counts[name] = counts.get(name, 0) + value
        if not result.get("disconnected"):
            break
    with Session(engine) as session:
        remaining = session.scalar(
            select(func.count())
            .select_from(ConnectorConnection)
            .where(
                ConnectorConnection.provider == provider,
                ConnectorConnection.status == "disconnecting",
            )
        )
    if remaining:
        counts["remaining"] = remaining
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.connector_purge",
        description="Disconnect and purge every connection of one provider.",
    )
    parser.add_argument("--provider", required=True, choices=PURGEABLE)
    parser.add_argument("--confirm", action="store_true", help="Required to act.")
    args = parser.parse_args(argv)
    if not args.confirm:
        parser.error("--confirm is required: every connection of the provider is purged.")
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        print(
            json.dumps(purge_provider(engine, settings, build_providers(settings), args.provider))
        )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
