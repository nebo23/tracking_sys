"""Minimal structured application logs without configuration or exception payloads."""

import json
import logging
from datetime import UTC, datetime


# Allowlist formatter: emit only a UTC timestamp, level, the event message, and an optional
# sanitized reason code. Arguments, exception tracebacks, and other record fields are omitted
# so configuration values, tokens, and personal data are not written by default.
class JsonFormatter(logging.Formatter):
    # Called by the handler for each record; returns one JSON line.
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        if hasattr(record, "reason"):
            entry["reason"] = record.reason
        return json.dumps(entry)


# Return the shared "tracking" logger, attaching the JSON stream handler only once so repeated
# application factories in one process do not duplicate lines. propagate=False keeps records
# away from root handlers that could use a less restrictive format.
def configure_logging() -> logging.Logger:
    logger = logging.getLogger("tracking")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
