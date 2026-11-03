"""Run one bounded local mail-delivery batch: python -m app.mail_worker."""

import json

from app.config import Settings
from app.database import create_database_engine
from app.services.mail import process_mail


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        print(json.dumps(process_mail(engine, settings)))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
