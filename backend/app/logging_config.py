"""Allowlisted structured logs: registered application events and reduced library records."""

import json
import logging
import re
import sys
import traceback
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any, TextIO

# Registered application events for the "tracking" logger (specification 003-A2). Each event
# lists the extra fields it may carry, and each field has a closed set of permitted codes.
# Positional %-arguments, unregistered events, unregistered fields, and other values are
# rejected, so a log call cannot interpolate passwords, tokens, emails, or provider bodies.
# Adding an event, field, or code is a reviewed code change.
FIELD_CODES: dict[str, frozenset[str]] = {
    "reason": frozenset({"database_unavailable", "schema_unavailable", "schema_mismatch"}),
}
EVENTS: dict[str, frozenset[str]] = {
    "application_started": frozenset(),
    "application_stopped": frozenset(),
    "database_operation_failed": frozenset(),
    "readiness_failed": frozenset({"reason"}),
}

# Constant message templates of known library loggers (uvicorn 0.54). They are emitted without
# their arguments; every other library record is reduced to its logger name, level, and
# exception type. Request lines, exception text, and tracebacks are never written.
LIBRARY_TEMPLATES = frozenset(
    {
        "Started server process [%d]",
        "Finished server process [%d]",
        "Waiting for application startup.",
        "Application startup complete.",
        "Waiting for application shutdown.",
        "Application shutdown complete.",
        "Application startup failed. Exiting.",
        "Application shutdown failed. Exiting.",
        "Shutting down",
        "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
        "Uvicorn running on %s://[%s]:%d (Press CTRL+C to quit)",
        "Exception in ASGI application\n",
        "Exception in 'lifespan' protocol\n",
        '%s - "%s %s HTTP/%s" %d',
    }
)

APPLICATION_LOGGER = "tracking"
# Loggers whose handlers are configured outside this module (uvicorn's dictConfig).
LIBRARY_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
_STANDARD_ATTRIBUTES = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
_LOGGER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
_LEVEL_NAME = re.compile(r"[A-Z]{1,10}")


# Name a value's class by module and qualified name: code identifiers, never instance data.
def _type_name(kind: type) -> str:
    return f"{kind.__module__}.{kind.__qualname__}"


# Sanitized exception diagnostics: the exception class and the innermost frame's file name,
# line, and function. The exception message, arguments, locals, and full paths are omitted.
def _exception_fields(record: logging.LogRecord) -> dict[str, str]:
    fields: dict[str, str] = {}
    if record.exc_info and record.exc_info[0] is not None:
        kind, _, trace = record.exc_info
        fields["exception_type"] = _type_name(kind)
        frames = traceback.extract_tb(trace) if trace is not None else []
        if frames:
            last = frames[-1]
            fields["exception_origin"] = f"{PurePath(last.filename).name}:{last.lineno}:{last.name}"
    elif isinstance(record.msg, BaseException):
        fields["exception_type"] = _type_name(type(record.msg))
    return fields


# Allowlist formatter for every handler this module manages. Registered application events
# keep their name and permitted codes; anything else becomes log_event_rejected or a reduced
# library record. Formatting never raises; an unexpected failure emits log_format_failed.
class AllowlistFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname if _LEVEL_NAME.fullmatch(str(record.levelname)) else "UNKNOWN"
        try:
            name = record.name if isinstance(record.name, str) else ""
            if name == APPLICATION_LOGGER or name.startswith(APPLICATION_LOGGER + "."):
                fields = self._application(record)
            else:
                fields = self._library(record, name)
        except Exception:  # noqa: BLE001 - logging must not fail or echo the failure
            fields = {"event": "log_format_failed"}
        return json.dumps({"timestamp": datetime.now(UTC).isoformat(), "level": level, **fields})

    # Validate a "tracking" record against the event registry.
    @staticmethod
    def _application(record: logging.LogRecord) -> dict[str, Any]:
        def rejected(reason: str) -> dict[str, Any]:
            return {"event": "log_event_rejected", "rejection": reason}

        if record.args:
            return rejected("positional_arguments")
        if not isinstance(record.msg, str) or record.msg not in EVENTS:
            return rejected("unregistered_event")
        extras = {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRIBUTES}
        for field, value in extras.items():
            if field not in EVENTS[record.msg]:
                return rejected("unregistered_field")
            if not isinstance(value, str) or value not in FIELD_CODES[field]:
                return rejected("invalid_field_value")
        return {"event": record.msg, **extras, **_exception_fields(record)}

    # Reduce a third-party record to a constant template (if known) and diagnostics.
    @staticmethod
    def _library(record: logging.LogRecord, name: str) -> dict[str, Any]:
        known = isinstance(record.msg, str) and record.msg in LIBRARY_TEMPLATES
        fields: dict[str, Any] = {
            "event": "library_message" if known else "library_record_suppressed",
            "logger": name if len(name) <= 100 and _LOGGER_NAME.fullmatch(name) else "unnamed",
        }
        if known:
            fields["template"] = record.msg
        return {**fields, **_exception_fields(record)}


# Stream handler that writes to the current sys.stderr at emit time, like logging's own
# last-resort handler, so redirected or captured streams receive the sanitized output.
class CurrentStderrHandler(logging.StreamHandler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(AllowlistFormatter())

    @property  # type: ignore[override]
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, value: TextIO) -> None:
        pass


# Configure process logging and return the shared "tracking" logger. The application logger
# receives one allowlist handler and does not propagate. Every handler already attached to
# the root logger, any other existing logger, or uvicorn's loggers is switched to the
# allowlist formatter, and the root logger receives an allowlist handler if it has none, so
# unexpected library records cannot reach Python's unformatted last-resort output. Idempotent;
# create_app calls it, and the application lifespan calls it again because uvicorn may apply
# its own logging configuration after the application object was created.
def configure_logging() -> logging.Logger:
    logger = logging.getLogger(APPLICATION_LOGGER)
    if not any(isinstance(handler, CurrentStderrHandler) for handler in logger.handlers):
        logger.addHandler(CurrentStderrHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = AllowlistFormatter()
    root = logging.getLogger()
    known = [logging.getLogger(name) for name in LIBRARY_LOGGERS]
    existing = [
        item
        for item in logging.Logger.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    ]
    for target in {id(item): item for item in [root, *known, *existing]}.values():
        for handler in target.handlers:
            if not isinstance(handler, CurrentStderrHandler):
                handler.setFormatter(formatter)
    if not root.handlers:
        root.addHandler(CurrentStderrHandler())
    return logger
