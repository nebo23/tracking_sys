"""Argument checks of python -m app.agency_offboarding and python -m app.offboarding_worker.

Specification 017-B (D-098 D11, OV16): run needs --confirm, and invalid arguments exit with 2
before any database is reached.
"""

from uuid import uuid4

import pytest

from app import agency_offboarding, offboarding_worker

AGENCY = str(uuid4())


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("The command must not connect before its arguments are valid.")

    monkeypatch.setattr(agency_offboarding, "create_database_engine", refuse)
    monkeypatch.setattr(offboarding_worker, "create_database_engine", refuse)


def test_run_requires_confirm(capsys):
    with pytest.raises(SystemExit) as exit_info:
        agency_offboarding.main(["run", "--agency", AGENCY])
    assert exit_info.value.code == 2
    assert "--confirm is required" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["status"],
        ["status", "--agency", "not-a-uuid"],
        ["run", "--confirm"],
        ["run", "--agency", "not-a-uuid", "--confirm"],
        ["status", "--agency", AGENCY, "--confirm"],
        ["purge", "--agency", AGENCY],
        [],
    ],
)
def test_invalid_arguments_exit_before_connecting(argv):
    with pytest.raises(SystemExit) as exit_info:
        agency_offboarding.main(argv)
    assert exit_info.value.code == 2


@pytest.mark.parametrize("limit", ["0", "51", "-1", "x"])
def test_worker_limit_is_bounded(limit):
    with pytest.raises(SystemExit) as exit_info:
        offboarding_worker.main(["--limit", limit])
    assert exit_info.value.code == 2
