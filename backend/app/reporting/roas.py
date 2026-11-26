"""ROAS and cost per lead from stored credit (specification 016-B, D-089 decision D7).

One spend connection, account-local dates and one level (ad, ad set or campaign). The rows
come from app.advertising.roas.roas_from_credit, which applies the 014-C row rules and roll-up
to the stored credit of the published generation, aggregated in SQL over the account-local
bounds of each period: spend on the account's local dates, credited revenue and credited
leads on the conversion date, no value for zero spend or mixed currencies, the spend states
complete, provisional and incomplete, and unmatched credit reported apart. The totals are the
same rules over every ad of the connection (level account). Before the first publication the
credit values are null with attribution_not_ready, never 0; spend stays as stored.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any
from uuid import UUID

from app.advertising import roas as contract
from app.attribution import AttributionModel, ModelVersion
from app.reporting.common import amount, compare_fractions, compare_values, share
from app.reporting.credit import NOT_READY, AttributionContext
from app.reporting.periods import Period
from app.reporting.spend import SpendInputs, SpendResult

LEVELS = ("ad", "adset", "campaign")
BLOCKING = ("sync_in_progress", "partial", "provisional", "stale")


def contract_period(period: Period) -> contract.Period:
    return contract.Period(period.start, period.end - timedelta(days=1))


def spend_facts(inputs: SpendInputs) -> tuple[contract.SpendFactView, ...]:
    return tuple(
        contract.SpendFactView(
            fact.ad_id,
            fact.adset_id,
            fact.campaign_id,
            fact.spend_date,
            fact.currency,
            fact.spend_minor,
            fact.refusal,
            fact.provisional_until,
        )
        for fact in inputs.facts
    )


def covered(inputs: SpendInputs) -> tuple[Any, Any] | None:
    if inputs.covered_from is None or inputs.complete_through is None:
        return None
    return inputs.covered_from, inputs.complete_through


def _exponent(row: contract.RoasRow) -> int | None:
    for money in (row.spend, row.credited):
        if money is not None:
            return money.currency.exponent
    return None


def row_view(item: contract.CreditRoasRow, ready: bool) -> dict[str, Any]:
    row = item.row
    exponent = _exponent(row)
    roas = None
    if ready and row.roas is not None:
        roas = {
            "numerator": row.roas.numerator,
            "denominator": row.roas.denominator,
            "decimal": row.roas_text,
        }
    cost = None
    if ready and item.cost_per_lead is not None:
        cost = {
            "numerator": item.cost_per_lead.numerator,
            "denominator": item.cost_per_lead.denominator,
            "decimal": item.cost_per_lead_text,
        }
    credited = (
        amount(row.credited.minor, row.credited.currency.exponent)
        if ready and row.credited is not None
        else None
    )
    return {
        "level": row.level,
        "object_id": row.object_id,
        "campaign_id": row.campaign_id,
        "adset_id": row.adset_id,
        "currency": row.currency,
        "exponent": exponent,
        "spend": None
        if row.spend is None
        else amount(row.spend.minor, row.spend.currency.exponent),
        "credited_revenue": credited,
        "roas": roas,
        "roas_reason": row.reason if ready else NOT_READY,
        "spend_state": row.spend_state,
        "credited_leads": share(item.leads) if ready else None,
        "cost_per_lead": cost,
        "cost_per_lead_reason": item.cost_per_lead_reason if ready else NOT_READY,
    }


@dataclass(frozen=True)
class RoasPeriod:
    label: str
    report: contract.CreditRoasReport


def _blocked(context: AttributionContext, spend: SpendResult) -> str | None:
    reason = context.blocked()
    if reason is not None:
        return reason
    reasons = {item["reason"] for item in spend.comparison or () if not item["comparable"]}
    return next((item for item in BLOCKING if item in reasons), None)


def _comparison(
    context: AttributionContext, spend: SpendResult, current: RoasPeriod, previous: RoasPeriod
) -> list[dict[str, Any]]:
    mine, theirs = current.report.total, previous.report.total
    blocked = _blocked(context, spend)
    if blocked is None and mine.row.currency != theirs.row.currency:
        blocked = "currency_mismatch"
    exponent = _exponent(mine.row) or _exponent(theirs.row)
    rows = []
    for metric, now_money, then_money in (
        ("spend", mine.row.spend, theirs.row.spend),
        ("credited_revenue", mine.row.credited, theirs.row.credited),
    ):
        now_value = None if now_money is None else now_money.minor
        then_value = None if then_money is None else then_money.minor
        known = now_value is not None and then_value is not None
        reason = blocked or (None if known else "no_value")
        result = compare_values(now_value, then_value, reason)
        if result["difference"] is not None and exponent is not None:
            result["difference"] = amount(result["difference"], exponent)
        rows.append(
            {
                "metric": metric,
                "currency": mine.row.currency or theirs.row.currency,
                "exponent": exponent,
                "current_value": None if now_value is None else amount(now_value, exponent),
                "previous_value": None if then_value is None else amount(then_value, exponent),
                **result,
            }
        )
    rows.append(
        {
            "metric": "credited_leads",
            "currency": None,
            "exponent": None,
            "current_value": share(mine.leads),
            "previous_value": share(theirs.leads),
            **compare_fractions(mine.leads, theirs.leads, context.blocked()),
        }
    )
    return rows


@dataclass
class RoasReportResult:
    body: dict[str, Any]
    total_rows: int
    rows: Callable[[], Iterator[dict[str, Any]]]


def roas_family(
    context: AttributionContext,
    inputs: SpendInputs,
    spend: SpendResult,
    level: str,
    periods: Sequence[tuple[str, Period]],
    credit: Mapping[str, Sequence[contract.CreditTotal]],
    version: ModelVersion | None,
    objects: Mapping[str, tuple[str, str | None]],
    connection_id: UUID,
    now: datetime,
) -> RoasReportResult:
    ready = version is not None and context.ready()
    engine_version = version or ModelVersion(
        "unavailable_1d_v1", AttributionModel.LINEAR, timedelta(days=1), "008-A.1"
    )
    built = []
    for label, period in periods:
        built.append(
            RoasPeriod(
                label,
                contract.roas_from_credit(
                    spend_facts(inputs),
                    credit.get(label, ()) if ready else (),
                    connection_id=connection_id,
                    period=contract_period(period),
                    zone=inputs.zone or "UTC",
                    model_version=engine_version,
                    as_of=now,
                    covered=covered(inputs),
                    objects=objects,
                ),
            )
        )
    current = built[0]
    rows = [row_view(item, ready) for item in current.report.rows if item.row.level == level]
    totals = [{"period": item.label, **row_view(item.report.total, ready)} for item in built]
    unmatched = [
        {
            "period": item.label,
            "currency": money.currency.code,
            "exponent": money.currency.exponent,
            "credited_revenue": amount(money.minor, money.currency.exponent),
        }
        for item in built
        for money in item.report.report.unmatched
    ]
    unmatched_leads = [
        {"period": item.label, "credited_leads": share(item.report.unmatched_leads)}
        for item in built
    ]
    body = {
        "level": level,
        "values": {
            "state": "available" if ready else "not_ready",
            "reason": None if ready else NOT_READY,
        },
        "attribution": context.block(),
        "finance": "available",
        "model_version": None if context.version is None else dict(context.version),
        "totals": totals,
        "unmatched": unmatched if ready else None,
        "unmatched_leads": unmatched_leads if ready else None,
        "comparison": _comparison(context, spend, built[0], built[1]) if len(built) > 1 else None,
        "spend_source": spend.source_status,
    }

    def page_rows() -> Iterator[dict[str, Any]]:
        yield from rows

    return RoasReportResult(body, len(rows), page_rows)


def credit_totals(rows: Sequence[Any]) -> dict[str, list[contract.CreditTotal]]:
    """Exact per-period credit of (campaign, content, kind, currency) from aggregated rows of
    (period, campaign_ref, content_ref, kind, currency, denominator, numerator, minor)."""
    found: dict[tuple, list] = {}
    for label, campaign, content, kind, currency, denominator, numerator, minor in rows:
        entry = found.setdefault((label, campaign, content, kind, currency), [0, Fraction(0)])
        entry[0] += int(minor or 0)
        entry[1] += Fraction(int(numerator), int(denominator))
    result: dict[str, list[contract.CreditTotal]] = {}
    for (label, campaign, content, kind, currency), (minor, value) in sorted(
        found.items(), key=lambda item: tuple("" if part is None else str(part) for part in item[0])
    ):
        result.setdefault(label, []).append(
            contract.CreditTotal(campaign, content, kind, currency, minor, value)
        )
    return result
