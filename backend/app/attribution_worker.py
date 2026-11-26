"""Run one bounded attribution pass: python -m app.attribution_worker."""

import json

from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.services.attribution_store import run_pass


# Command-line entry point (specification 008-B, D-079 decisions D7 and D11): load validated
# settings, run one bounded pass per active client (at most 2,000 conversions per client, in
# transactions of at most 200), print only outcome counts and dispose of the engine. A client
# whose published ledger is not ready is skipped as ledger_unavailable and nothing changes for
# it. It is not a long-running scheduler: stored attribution is as fresh as the last
# invocation, and readers answer attribution_stale in between. Production scheduling and
# process supervision are decided in 020.
def main() -> None:
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        print(json.dumps(run_pass(engine)))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
