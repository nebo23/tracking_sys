"""Operator view and run of a closed agency's offboarding: python -m app.agency_offboarding.

Specification 017-B (D-098 decision D11; design-017b.md section 7).

Usage:
  python -m app.agency_offboarding status --agency <uuid>
  python -m app.agency_offboarding run --agency <uuid> --confirm

status reads, as tracking_app, the agency's status, its closure times, its export summary, its
purge record with the deleted row counts, and its connections counted by state. run handles
one closed agency at once, for example when a teardown seems stuck because no worker runs: the
offboarding if it is not done, one teardown pass over the agency's connections (each teardown
keeps its 72-hour deadline), then the purge batches as tracking_lifecycle until the agency is
purged or a teardown is still within its deadline. run needs --confirm (otherwise argparse
exits with 2 before connecting) and TRACKING_LIFECYCLE_PASSWORD, like the lifecycle runner.

Output is one JSON document with identifiers, closed codes, counts and times only: never an
agency or client name, a person, an email, a token or a figure. A refusal prints
{"error": code} and exits with 1.
"""

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import LifecycleSettings, Settings
from app.connectors.contracts import ConnectorProvider
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.models import Agency, AgencyPurge
from app.services import agency_offboarding, agency_purge
from app.services.connectors import build_providers, run_teardowns

TEARDOWN_BATCH = 100


class Refused(Exception):
    """A refusal with a closed code, printed as {"error": code} and any detail."""

    def __init__(self, code: str, **detail: Any) -> None:
        self.code, self.detail = code, detail
        super().__init__(code)


def status(engine: Engine, agency_id: UUID) -> dict[str, Any]:
    with Session(engine) as session:
        view = agency_offboarding.status(session, agency_id)
    if view is None:
        raise Refused("agency_not_found")
    return view


def _teardowns(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    agency_id: UUID,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    while True:
        result = run_teardowns(
            engine, settings, registry, limit=TEARDOWN_BATCH, agency_id=agency_id
        )
        for name, value in result.items():
            counts[name] = counts.get(name, 0) + value
        if not result.get("disconnected"):
            return counts


def run(
    engine: Engine,
    lifecycle_engine: Engine,
    settings: Settings,
    budget: int,
    registry: Mapping[str, ConnectorProvider],
    agency_id: UUID,
) -> dict[str, Any]:
    with Session(engine) as session:
        agency = session.get(Agency, agency_id)
        if agency is None:
            raise Refused("agency_not_found")
        if agency.status != "closed":
            raise Refused("agency_not_closed", status=agency.status)
        purge = session.get(AgencyPurge, agency_id)
        state = None if purge is None else purge.state
    if state in (None, "offboarding"):
        counts = agency_offboarding.offboard_agency(engine, settings, agency_id)
        offboarding: dict[str, Any] = (
            {"state": "busy"} if counts is None else {"state": "completed", **dict(counts)}
        )
    else:
        offboarding = {"state": "already_completed"}
    teardown = _teardowns(engine, settings, registry, agency_id)
    with lifecycle_engine.connect() as connection:
        rows, outcome = agency_purge.purge_agency(connection, agency_id, budget, None)
    with Session(engine) as session:
        record = session.scalar(select(AgencyPurge.state).where(AgencyPurge.agency_id == agency_id))
    return {
        "agency_id": str(agency_id),
        "offboarding": offboarding,
        "teardown": teardown,
        "purge": {"outcome": outcome, "state": record, "deleted_rows": rows},
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="python -m app.agency_offboarding",
        description="Show or run the offboarding and purge of one closed agency.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    show = commands.add_parser("status", help="Show the offboarding and purge state.")
    show.add_argument("--agency", required=True, type=UUID)
    act = commands.add_parser("run", help="Run the pending steps of one closed agency now.")
    act.add_argument("--agency", required=True, type=UUID)
    act.add_argument("--confirm", action="store_true", help="Required.")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    root = parser()
    args = root.parse_args(argv)
    if args.command == "run" and not args.confirm:
        root.error("--confirm is required to run the offboarding and purge of an agency.")
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        if args.command == "status":
            code, result = 0, status(engine, args.agency)
        else:
            lifecycle = LifecycleSettings()
            lifecycle_engine = create_database_engine(lifecycle, pool_size=1)
            try:
                code, result = (
                    0,
                    run(
                        engine,
                        lifecycle_engine,
                        settings,
                        lifecycle.lifecycle_batch_size,
                        build_providers(settings),
                        args.agency,
                    ),
                )
            finally:
                lifecycle_engine.dispose()
    except Refused as refusal:
        code, result = 1, {"error": refusal.code, **refusal.detail}
    finally:
        engine.dispose()
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
