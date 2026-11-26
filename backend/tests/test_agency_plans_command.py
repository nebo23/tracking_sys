"""Argument checks of python -m app.agency_plans (017-A, D7); no database is reached."""

import argparse
from uuid import uuid4

import pytest

from app import agency_plans

AGENCY = str(uuid4())
LIMITS = [
    "--clients",
    "5",
    "--seats",
    "unlimited",
    "--connections",
    "0",
    "--managed-links",
    "500",
    "--tracked-events",
    "100000",
]


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("The command must not connect before its arguments are valid.")

    monkeypatch.setattr(agency_plans, "create_database_engine", refuse)


@pytest.mark.parametrize(
    "argv",
    [
        ["create-plan", "--key", "growth", "--name", "Growth", *LIMITS, "--reason", "new_offer"],
        ["set-default", "--plan", "growth"],
        ["assign", "--agency", AGENCY, "--plan", "growth", "--reason", "plan_change"],
        ["suspend", "--agency", AGENCY],
        ["reactivate", "--agency", AGENCY],
    ],
)
def test_every_change_requires_confirm(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        agency_plans.main(argv)
    assert exit_info.value.code == 2
    assert "--confirm is required" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["create-plan", "--key", "growth", "--name", "Growth", *LIMITS[:-2], "--reason", "x"],
        ["create-plan", "--key", "Growth", "--name", "Growth", *LIMITS, "--reason", "new_offer"],
        ["create-plan", "--key", "growth", "--name", " ", *LIMITS, "--reason", "new_offer"],
        ["assign", "--agency", "not-a-uuid", "--plan", "growth", "--reason", "plan_change"],
        ["assign", "--agency", AGENCY, "--plan", "growth", "--reason", "upgrade"],
        ["agencies", "--limit", "0"],
        ["agencies", "--limit", "501"],
        ["unknown"],
    ],
)
def test_invalid_arguments_are_refused_before_any_connection(argv):
    with pytest.raises(SystemExit) as exit_info:
        agency_plans.main([*argv, "--confirm"] if argv[0] != "agencies" else argv)
    assert exit_info.value.code == 2


def test_limit_values():
    assert agency_plans._limit("unlimited") is None
    assert agency_plans._limit("0") == 0
    assert agency_plans._limit("1000000000") == 1_000_000_000
    for value in ("-1", "1000000001", "1.5", "", "five", "\uff11"):
        with pytest.raises(argparse.ArgumentTypeError):
            agency_plans._limit(value)


def test_plan_keys():
    for value in ("dev", "agency-pro", "a_1", "x" * 32):
        assert agency_plans._key(value) == value
    for value in ("d", "Dev", "1dev", "dev plan", "x" * 33, "dev!"):
        with pytest.raises(argparse.ArgumentTypeError):
            agency_plans._key(value)


def test_options_map_the_limit_flags_to_their_columns():
    args = agency_plans.parser().parse_args(
        ["create-plan", "--key", "growth", "--name", "Growth", *LIMITS, "--reason", "new_offer"]
    )
    assert agency_plans.options_of(args) == {
        "key": "growth",
        "name": "Growth",
        "reason": "new_offer",
        "limits": {
            "clients_limit": 5,
            "seats_limit": None,
            "connections_limit": 0,
            "managed_links_limit": 500,
            "tracked_events_limit": 100000,
        },
    }
