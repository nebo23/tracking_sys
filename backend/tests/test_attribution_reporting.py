"""016-B attribution reporting, pure parts (D-089, BV03, BV06, BV09 and BV18).

Exact fraction sums and their half-even text, the groups with direct and unknown credit kept
apart, comparisons and reconciliation states, and the typed, bounded CSV with the id: prefix.
Nothing here reads a database; every value is synthetic.
"""

import csv
import io
from datetime import UTC, date, datetime
from fractions import Fraction
from uuid import uuid4

import pytest

from app.reporting.common import ReportError, compare_fractions, fraction_text, share
from app.reporting.credit import (
    AttributionContext,
    CountRow,
    CreditRow,
    GroupMeta,
    LedgerTotal,
    attribution_report,
    reconciliation_block,
)
from app.reporting.credit_csv import attribution_csv
from app.reporting.csv_export import COLUMNS_016B, MAX_ROWS, CsvBuilder

V = uuid4()
VERSION = {
    "id": str(V),
    "version_key": "linear_30d_v1",
    "model": "linear",
    "window_days": 30,
    "rules": "008-A.1",
    "is_default": True,
    "status": "active",
    "created_at": "2026-11-26T00:00:00+00:00",
    "retired_at": None,
}


def context(state: str = "caught_up", generation: int = 1) -> AttributionContext:
    return AttributionContext(
        state=state,
        generation=generation,
        published_at=None,
        failure_code=None,
        unit=None,
        consumer={"ledger_generation": 1, "receipt_ordinal": 1, "identity_seq": 0},
        current={
            "ledger": "available",
            "ledger_generation": 1,
            "receipt_ordinal": 1,
            "identity_seq": 0,
        },
        versions=(VERSION,),
        version=VERSION,
    )


def credit(recipient, ref, value, minor=None, *, kind="sale", currency="EGP", period="current"):
    sale = kind == "sale"
    return CreditRow(
        V,
        period,
        recipient,
        ref,
        kind,
        currency if sale else None,
        2 if sale else None,
        Fraction(value),
        minor if sale else None,
    )


def count(recipient, ref, conversions, *, kind="sale", currency="EGP", period="current"):
    sale = kind == "sale"
    return CountRow(
        V,
        period,
        recipient,
        ref,
        kind,
        currency if sale else None,
        2 if sale else None,
        conversions,
    )


def report(
    rows,
    counts=(),
    totals=(),
    *,
    state="caught_up",
    generation=1,
    finance=True,
    labels=("current",),
    ledger=(),
    ledger_state="available",
    group_by="campaign",
):
    return attribution_report(
        context(state, generation),
        group_by,
        "groups",
        labels,
        list(rows),
        list(counts),
        list(totals),
        ledger_state,
        list(ledger),
        GroupMeta(),
        finance,
    )


def test_exact_fractions_and_half_even_text():
    assert fraction_text(Fraction(1, 3)) == "0.3333"
    assert fraction_text(Fraction(2, 3)) == "0.6667"
    assert fraction_text(Fraction(1, 32)) == "0.0312"  # 0.03125: the even neighbour
    assert fraction_text(Fraction(3, 32)) == "0.0938"  # 0.09375: rounds up to the even 8
    assert fraction_text(Fraction(-1, 32)) == "-0.0312"
    assert fraction_text(Fraction(5)) == "5.0000"
    assert (
        fraction_text(Fraction(1, 200), 2) == "0.00"
        and fraction_text(Fraction(3, 200), 2) == "0.02"
    )
    assert share(Fraction(2, 4)) == {"numerator": 1, "denominator": 2, "decimal": "0.5000"}
    assert sum([Fraction(1, 3)] * 3) == 1
    change = compare_fractions(Fraction(1, 3), Fraction(1, 6), None)
    assert (change["percent_change"], change["difference"]["decimal"]) == ("100.00", "0.1667")
    zero = compare_fractions(Fraction(1, 3), Fraction(0), None)
    assert (zero["percent_change"], zero["reason"], zero["comparable"]) == (
        None,
        "zero_baseline",
        True,
    )
    blocked = compare_fractions(Fraction(1), Fraction(1), "attribution_behind")
    assert (blocked["difference"], blocked["comparable"]) == (None, False)


def test_groups_keep_direct_and_unknown_apart():
    rows = [
        credit("campaign", "spring", Fraction(1, 2), 5_000),
        credit("campaign", "spring", Fraction(1, 3), 1_000),  # another denominator, summed exactly
        credit("campaign", None, Fraction(1, 3), 1_000),
        credit("campaign", "gone", Fraction(1, 2), 2_000),
        credit("campaign", "gone", Fraction(-1, 2), -2_000),  # credit that nets to nothing
        credit("direct", None, 1, 4_000),
        credit("unknown", None, 1, 2_500),
        credit("campaign", "spring", 1, kind="lead"),
    ]
    counts = [count("campaign", "spring", 2), count("unknown", None, 1)]
    built = report(rows, counts)
    found = list(built.rows())
    assert [(row["recipient"], row["group_ref"]) for row in found] == [
        ("campaign", "spring"),
        ("campaign", None),
        ("direct", None),
        ("unknown", None),
    ]
    spring = found[0]
    (item,) = spring["sales"]["items"]
    assert item["credited_sales"] == {"numerator": 5, "denominator": 6, "decimal": "0.8333"}
    assert item["credited_revenue"] == {"minor": 6_000, "decimal": "60.00"}
    assert item["conversions"] == 2
    assert spring["leads"] == {"credited_leads": share(Fraction(1)), "conversions": 0}
    assert found[2]["registered"] is None and found[0]["registered"] is False
    # Without finance the sale values disappear, lead credit stays.
    hidden = list(report(rows, counts, finance=False).rows())
    assert {row["sales"]["state"] for row in hidden} == {"permission_unavailable"}
    assert "EGP" not in str(hidden)
    # Before the first publication nothing is computed and every value is null.
    empty = report(rows, counts, generation=0)
    assert empty.total_rows == 0 and empty.body["values"]["reason"] == "attribution_not_ready"
    assert empty.body["totals"]["sales"]["items"] is None


def test_comparisons_are_exact_and_blocked_when_not_authoritative():
    rows = [
        credit("campaign", "spring", 1, 15_000),
        credit("campaign", "spring", 1, 10_000, period="previous"),
        credit("campaign", "spring", Fraction(1, 2), kind="lead"),
    ]
    totals = [count("campaign", None, 1), count("campaign", None, 1, period="previous")]
    labels = ("current", "previous")
    compared = {
        item["metric"]: item for item in report(rows, (), totals, labels=labels).body["comparison"]
    }
    assert compared["credited_revenue"]["percent_change"] == "50.00"
    assert compared["credited_leads"]["reason"] == "zero_baseline"
    assert compared["sale_conversions"]["percent_change"] == "0.00"
    for state in ("behind", "rebuilding", "failed"):
        blocked = report(rows, (), totals, labels=labels, state=state).body["comparison"]
        assert {item["reason"] for item in blocked} == {f"attribution_{state}"}
        assert {item["percent_change"] for item in blocked} == {None}
    assert report(rows, (), totals, labels=labels, generation=0).body["comparison"] == []


def test_reconciliation_states():
    rows = [credit("unknown", None, 1, 3_000), credit("campaign", "a", 1, 2_000, currency="USD")]
    ledger = [LedgerTotal("current", "EGP", 2, 3_000), LedgerTotal("current", "USD", 2, 2_500)]
    block = reconciliation_block(context(), rows, V, ("current",), "available", ledger, True)
    states = {item["currency"]: (item["state"], item["reason"]) for item in block["items"]}
    assert states == {"EGP": ("reconciled", None), "USD": ("difference", "unexplained_difference")}
    usd = [item for item in block["items"] if item["currency"] == "USD"][0]
    assert usd["difference"] == {"minor": -500, "decimal": "-5.00"}
    behind = reconciliation_block(
        context("behind"), rows, V, ("current",), "available", ledger, True
    )
    assert {item["reason"] for item in behind["items"]} == {None, "attribution_behind"}
    assert reconciliation_block(context(), rows, V, ("current",), "unavailable", [], True) == {
        "state": "unavailable",
        "reason": "ledger_unavailable",
        "ledger": "unavailable",
        "items": None,
    }
    assert (
        reconciliation_block(context(), rows, V, ("current",), "available", ledger, False)["state"]
        == "permission_unavailable"
    )
    assert (
        reconciliation_block(
            context(generation=0), rows, V, ("current",), "available", ledger, True
        )["state"]
        == "not_ready"
    )
    with pytest.raises(ReportError) as refused:
        reconciliation_block(
            context(),
            rows,
            V,
            ("current",),
            "available",
            [LedgerTotal("current", "EGP", 3, 1)],
            True,
        )
    assert refused.value.code == "currency_exponent_conflict"


def _body(built, **extra):
    return {
        "contract_version": "016b.1",
        "family": "attribution",
        "client_id": uuid4(),
        "period": {"start": date(2026, 12, 1), "end": date(2026, 12, 2), "days": 1},
        "comparison_period": None,
        "generated_at": datetime(2026, 11, 26, tzinfo=UTC),
        "revision": "a" * 64,
        "day_zone": "UTC",
        "basis": "conversion_date",
        "dependencies": [
            {"capability": "roas", "state": "available", "family": "roas", "requires": ["008"]}
        ],
        **built.body,
        **extra,
    }


def test_csv_identifier_prefix_and_record_bound():
    refs = ["=SUM(A1)", "+1", "-1", "@cmd", "spring"]
    built = report([credit("campaign", ref, 1, 100) for ref in refs])
    data = attribution_csv(_body(built), built.rows(), built.total_rows)
    cells = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
    groups = {row["group_ref"] for row in cells if row["group_ref"]}
    assert groups == {f"id:{ref}" for ref in refs}
    assert all(not value.startswith(("=", "+", "@")) for row in cells for value in row.values())
    assert list(cells[0]) == [name for name, _ in COLUMNS_016B]
    # Exactly MAX_ROWS records pass; one more is refused before anything is encoded.
    builder = CsvBuilder("attribution", {"day_zone": "UTC"}, COLUMNS_016B)
    for _ in range(MAX_ROWS):
        builder.add("value", metric="credited_leads", value="1.0000")
    assert builder.encode().count(b"\r\n") == MAX_ROWS + 1
    with pytest.raises(ReportError) as refused:
        builder.add("value", metric="credited_leads", value="1.0000")
    assert refused.value.code == "export_too_large"
    # The 2 MiB bound refuses the whole file.
    long = CsvBuilder("attribution", {"day_zone": "UTC"}, COLUMNS_016B)
    for index in range(MAX_ROWS):
        reference = f"{index:06d}" + "x" * 250
        long.add("value", metric="credited_leads", group_ref=reference, object_id=reference)
    with pytest.raises(ReportError) as too_large:
        long.encode()
    assert too_large.value.code == "export_too_large"
    # A not-ready report still exports its labels and states.
    empty = report([], generation=0)
    text = attribution_csv(_body(empty), empty.rows(), 0).decode("utf-8")
    assert "attribution_not_ready" in text and "EGP" not in text
