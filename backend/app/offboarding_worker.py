"""Run one bounded offboarding pass: python -m app.offboarding_worker.

Specification 017-B (D-098 decisions D5 and D6; design-017b.md sections 3.3 and 4). As
tracking_app, the pass first builds the pending offboarding exports of closing agencies (a ZIP
sealed in parts under the token keyring, stored only while the agency is still closing), then
offboards the agencies closed since the last pass: every live connection
is disconnected with reason agency_closed, so that the connector worker's teardown revokes its
tokens and purges its provider data; service keys, pending invitations and report exports are
revoked; and sources, destinations and WhatsApp numbers are disabled. It prints counts only,
never a name, a figure, a token or file content. It is not a scheduler: production scheduling
is decided in specification 020. The lifecycle runner purges the agency once its teardowns
have settled.
"""

import argparse
import json
from collections.abc import Sequence

from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.services.agency_exports import build_pending
from app.services.agency_offboarding import run_offboarding


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.offboarding_worker",
        description="Run one bounded pass of agency offboarding.",
    )
    parser.add_argument("--limit", type=int, default=10, help="Agencies per pass (1-50).")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50.")
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        result = {
            "exports": build_pending(engine, settings, limit=args.limit),
            "offboarding": run_offboarding(engine, settings, limit=args.limit),
        }
        print(json.dumps(result))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
