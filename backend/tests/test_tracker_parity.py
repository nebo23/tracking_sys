"""Server side of the tracker minimization parity fixtures (specification 005, M2).

packages/tracker-js/test/fixtures/parity.json is asserted by the tracker's Node tests and here,
so the browser minimizer and the 003/004 Python contracts cannot drift apart unnoticed.
"""

import json

import pytest

from app.collection.contract import (
    FormDefinition,
    Rejected,
    minimize_page_url,
    origin_only,
    sanitize_form,
)
from app.config import PROJECT_ROOT
from app.privacy.collection import FormField, contains_card_number, never_collect_reason
from app.privacy.consent import Purpose

FIXTURES = json.loads(
    (PROJECT_ROOT / "packages" / "tracker-js" / "test" / "fixtures" / "parity.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", FIXTURES["urls"], ids=lambda case: case["url"][:60])
def test_page_url_minimization_matches_the_shared_fixture(case):
    granted = {Purpose(purpose) for purpose in case["granted"]}
    if "rejected" in case:
        with pytest.raises(Rejected) as raised:
            minimize_page_url(case["url"], granted)
        assert raised.value.reason == case["rejected"]
    else:
        minimized, dropped = minimize_page_url(case["url"], granted)
        assert (minimized, dict(dropped)) == (case["expected"], case["dropped"])


def test_referrers_cards_fields_and_values_match_the_shared_fixture():
    for case in FIXTURES["referrers"]:
        if "rejected" in case:
            with pytest.raises(Rejected):
                origin_only(case["url"])
        else:
            assert origin_only(case["url"]) == case["expected"]
    assert len(FIXTURES["cards"]) >= 25
    for case in FIXTURES["cards"]:
        assert contains_card_number(case["text"]) is case["card"], case["text"]
    for case in FIXTURES["fields"]:
        assert never_collect_reason(FormField(**case["field"])) == case["reason"]
    for case in FIXTURES["values"]:
        if case["expected"] is None:
            continue
        definition = FormDefinition.model_validate({"fields": [case["field"]]})
        name = case["field"]["name"]
        kept, dropped = sanitize_form(definition, {name: case["expected"]})
        assert kept == {name: case["expected"]} and not dropped
