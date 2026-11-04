"""Log allowlist (specification 003-A2): synthetic secrets never reach process output.

Cases M1-M3 of the specification 003 design. In-process checks use the application logger
directly; the server cases run a real uvicorn server in a child process, so uvicorn's own
logging configuration, error logger, access logger, and Python's last-resort path are exercised
as in production rather than through a helper in isolation.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from app.config import BACKEND_ROOT
from app.logging_config import configure_logging

SECRET = "synthetic-secret-value-7f3a91"


def entries(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_registered_event_keeps_permitted_codes(capsys):
    configure_logging().warning("readiness_failed", extra={"reason": "schema_mismatch"})
    [entry] = entries(capsys.readouterr().err)
    assert (entry["event"], entry["reason"], entry["level"]) == (
        "readiness_failed",
        "schema_mismatch",
        "WARNING",
    )


@pytest.mark.parametrize(
    ("emit", "rejection"),
    [
        (lambda logger: logger.info("user %s", SECRET), "positional_arguments"),
        (lambda logger: logger.info(f"login failed for {SECRET}"), "unregistered_event"),
        (
            lambda logger: logger.info("application_started", extra={"email": SECRET}),
            "unregistered_field",
        ),
        (
            lambda logger: logger.warning("readiness_failed", extra={"reason": SECRET}),
            "invalid_field_value",
        ),
    ],
    ids=["m1-positional-arguments", "m3-unregistered-event", "m3-field", "m3-field-value"],
)
def test_unregistered_application_records_are_rejected(capsys, emit, rejection):
    emit(configure_logging())
    output = capsys.readouterr().err
    assert SECRET not in output
    [entry] = entries(output)
    assert (entry["event"], entry["rejection"]) == ("log_event_rejected", rejection)


def test_exception_text_is_reduced_to_type_and_origin(capsys):
    logger = configure_logging()
    try:
        raise RuntimeError(f"token {SECRET}")
    except RuntimeError:
        logger.exception("database_operation_failed")
    output = capsys.readouterr().err
    assert SECRET not in output and "Traceback" not in output
    [entry] = entries(output)
    assert entry["event"] == "database_operation_failed"
    assert entry["exception_type"] == "builtins.RuntimeError"
    assert entry["exception_origin"].startswith("test_logging.py:")


# Child process: a real uvicorn server, with the application object built either by uvicorn
# after its logging configuration ("factory", as the documented CLI does) or before it
# ("instance"). One route raises an exception carrying the secret; the request also carries
# the secret in its query string; afterwards an application record with positional
# arguments and an unconfigured library logger record carry it too.
CHILD = textwrap.dedent(
    """
    import logging, socket, sys, threading, time, urllib.error, urllib.request
    import uvicorn
    from cryptography.fernet import Fernet
    from app.config import Settings
    from app.main import create_app

    order, secret = sys.argv[1], sys.argv[2]
    settings = Settings(
        _env_file=None, database_password="synthetic", auth_secret="ab" * 32,
        otp_secret="cd" * 32, mail_encryption_key=Fernet.generate_key().decode(),
    )

    def build():
        app = create_app(settings)
        def fail():
            raise RuntimeError("failure for " + secret)
        app.add_api_route("/synthetic-failure", fail)
        return app

    target = build if order == "factory" else build()
    server = uvicorn.Server(uvicorn.Config(target, factory=order == "factory", access_log=True))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise SystemExit("server did not start")
        time.sleep(0.05)
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/synthetic-failure?code={secret}", timeout=10
        )
    except urllib.error.HTTPError as error:
        print("status", error.code)
    logging.getLogger("tracking").info("user %s", secret)
    logging.getLogger("synthetic.library").warning("detail %s", secret)
    server.should_exit = True
    thread.join(10)
    """
)


@pytest.mark.parametrize("order", ["factory", "instance"])
def test_server_output_hides_exception_text_query_and_arguments(order):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("TRACKING_")}
    result = subprocess.run(
        [sys.executable, "-c", CHILD, order, SECRET],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0 and "status 500" in result.stdout
    assert SECRET not in result.stdout + result.stderr
    errors = entries(result.stderr)
    failure = [e for e in errors if e.get("template") == "Exception in ASGI application\n"]
    assert len(failure) == 1
    assert failure[0]["exception_type"] == "builtins.RuntimeError"
    assert failure[0]["exception_origin"].startswith("<string>:")
    events = {(e["event"], e.get("logger"), e.get("rejection")) for e in errors}
    assert ("log_event_rejected", None, "positional_arguments") in events
    assert ("library_record_suppressed", "synthetic.library", None) in events
    assert "Traceback" not in result.stderr
    access = [e for e in entries(result.stdout) if e.get("logger") == "uvicorn.access"]
    assert [e["template"] for e in access] == ['%s - "%s %s HTTP/%s" %d']
