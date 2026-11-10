"""Run one bounded retention pass for ended credential state: python -m app.lifecycle."""

import json

from app.config import LifecycleSettings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.services.lifecycle import run_lifecycle


# Command-line entry point (specification 003-A3, D-024): connect as tracking_lifecycle, delete
# rows past their approved periods in bounded batches, clean development mail captures, and
# print counts and status codes only. It is not a scheduler; run it manually or from an
# operating-system scheduler. A concurrent run exits without deleting anything.
def main() -> None:
    configure_logging()
    settings = LifecycleSettings()
    engine = create_database_engine(settings, pool_size=1)
    try:
        print(json.dumps(run_lifecycle(engine, settings)))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
