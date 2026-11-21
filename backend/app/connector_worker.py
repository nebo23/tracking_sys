"""Run one bounded connector worker pass: python -m app.connector_worker."""

import json

from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.services.connectors import build_providers, process_connectors
from app.services.delivery import run_deliveries


# Command-line entry point (specification 009, D-048 and D-049): load validated settings, run
# at most one bounded batch of disconnect teardowns, disconnect connections past their
# reconnect grace period and check the authorizations that are due (011-A, R011-13), queue the
# incremental runs that are due, run at most one bounded batch of sync runs, run at most one
# bounded batch of conversion deliveries (014-B, D-064 D9), print only outcome counts, and
# dispose of the engine. It is not a long-running scheduler: the synthetic 72-hour
# teardown target, the sync interval and the authorization check period are met only if the
# command is invoked within them. Production scheduling and process supervision are decided in
# 020 (D-049 decision D11).
def main() -> None:
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        registry = build_providers(settings)
        result = process_connectors(engine, settings, registry)
        result["delivery"] = run_deliveries(engine, settings, registry)
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
