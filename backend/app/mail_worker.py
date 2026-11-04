"""Run one bounded local mail-delivery batch: python -m app.mail_worker."""

import json

from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.services.mail import process_mail


# Command-line entry point: load validated settings, deliver at most one bounded batch of due
# outbox messages, print only delivered/failed counts, and dispose of the engine. It is not a
# scheduler or long-running service; run it again to process later messages. Library log
# records pass through the same allowlist formatter as the API.
def main() -> None:
    configure_logging()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        print(json.dumps(process_mail(engine, settings)))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
