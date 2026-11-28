"""The argument rules of python -m app.agency_billing (017-C, D-103 D12; part of BL18).

Unit cases without a database: every change needs --confirm, IDs and numbers are checked before
anything runs, and the parsed options reach the subcommand unchanged.
"""

from uuid import uuid4

import pytest

from app import agency_billing

PRICE = "pri_" + "a" * 26


def parse(*args):
    return agency_billing.parser().parse_args(list(args))


@pytest.mark.parametrize(
    "args",
    [
        ["grant", "--agency", str(uuid4()), "--plan", "development"],
        ["end-grant", "--agency", str(uuid4())],
        ["extend-trial", "--agency", str(uuid4()), "--days", "3"],
        ["retire-price", "--price-id", PRICE],
        ["register-price", "--plan", "pro", "--price-id", PRICE, "--amount-cents", "1"]
        + ["--interval", "month"],
    ],
)
def test_changes_require_confirm(args, capsys):
    with pytest.raises(SystemExit) as raised:
        agency_billing.main(args)
    assert raised.value.code == 2
    assert "--confirm is required" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["register-price", "--plan", "pro", "--price-id", "pri_short", "--amount-cents", "1"]
        + ["--interval", "month"],
        ["register-price", "--plan", "pro", "--price-id", PRICE, "--amount-cents", "0"]
        + ["--interval", "month"],
        ["register-price", "--plan", "pro", "--price-id", PRICE, "--amount-cents", "1"]
        + ["--interval", "week"],
        ["register-price", "--plan", "Pro!", "--price-id", PRICE, "--amount-cents", "1"]
        + ["--interval", "month"],
        ["extend-trial", "--agency", str(uuid4()), "--days", "31"],
        ["grant", "--agency", str(uuid4()), "--plan", "pro", "--until", "2026-12-01"],
        ["grant", "--agency", "not-a-uuid", "--plan", "pro"],
        ["agencies", "--standing", "unknown"],
        ["agencies", "--limit", "0"],
    ],
)
def test_invalid_arguments_are_refused(args):
    with pytest.raises(SystemExit) as raised:
        parse(*args)
    assert raised.value.code == 2


def test_parsed_options():
    agency = uuid4()
    args = parse(
        "grant", "--agency", str(agency), "--plan", "pro", "--until", "2027-01-01T00:00:00+00:00"
    )
    options = agency_billing.options_of(args)
    assert options["agency"] == agency and options["plan"] == "pro"
    assert options["until"].isoformat() == "2027-01-01T00:00:00+00:00"
    listing = agency_billing.options_of(
        parse("agencies", "--standing", "hold", "--held-days", "60")
    )
    assert (listing["standing"], listing["held_days"], listing["limit"]) == ("hold", 60, 100)
