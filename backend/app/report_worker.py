"""Run one bounded pass of scheduled reports: python -m app.report_worker.

Specification 016-C (D-095 decision D10). The pass claims due schedules of active agencies and
clients with FOR UPDATE SKIP LOCKED, moves each to its next slot, builds its export with the
owner's permissions, queues a report_ready email for every recipient who may read it and
records the outcome. It prints counts only (due, built, notified, skipped, failed, paused),
never a name, figure, token or file content. It is not a scheduler: production scheduling is
decided in specification 020. The mail worker delivers the queued messages.
"""

import argparse
import json
from collections.abc import Sequence

from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.services.connectors import build_providers
from app.services.report_schedules import run_pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.report_worker",
        description="Run one bounded pass of scheduled reports.",
    )
    parser.add_argument("--limit", type=int, default=25, help="Schedules per pass (1-100).")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100.")
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        print(json.dumps(run_pass(engine, settings, build_providers(settings), limit=args.limit)))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
