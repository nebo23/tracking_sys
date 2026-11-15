"""Run one bounded connector worker pass: python -m app.connector_worker."""

import json

from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.services.connectors import build_providers, process_connectors


# Command-line entry point (specification 009-A, D-048): load validated settings, run at most
# one bounded batch of disconnect teardowns and then of sync runs, print only outcome counts,
# and dispose of the engine. It is not a scheduler: the synthetic 72-hour teardown target is
# met only if the command is invoked within it. Queue and scheduling choices remain Q-009.
def main() -> None:
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        print(json.dumps(process_connectors(engine, settings, build_providers(settings))))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
