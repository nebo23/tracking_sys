"""Advertising spend reports (specification 016-A, D-072 decisions D4 to D8).

One spend connection, account-local dates (start inclusive, end exclusive) and one approved
level (ad, ad set or campaign). Rows group the current period's valid facts by the complete key
(level object ID, currency), including a missing object ID at the level, so one object reported
in two currencies has two rows (R010). Totals are per original currency; amounts in different
currencies are never added and no exchange rate is applied. Refused facts are counted, never
valued. The report never divides or allocates client revenue across ads: ROAS stays a 016-B
dependency.

A total is complete only when the ad_daily coverage holds the whole period, no fact of the
period was refused and every fact uses the account's current day zone. A period without any
fact is reported as no_spend_facts with an empty totals list, never as a zero total.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.advertising.currencies import EXPONENTS
from app.reporting.common import ReportError, amount, compare_values
from app.reporting.periods import Period

LEVELS = ("ad", "adset", "campaign")
KEYS = {"ad": "ad_id", "adset": "adset_id", "campaign": "campaign_id"}
REFUSALS = ("unparseable_amount", "unsupported_currency")
DAILY_STREAM = "ad_daily"
# The freshness window the Meta spend adapters declare (014-A, freshness_hours).
FRESHNESS_HOURS = 48
METRICS = ("spend", "impressions", "clicks")


@dataclass(frozen=True)
class SpendFactInput:
    ad_id: str
    adset_id: str | None
    campaign_id: str | None
    spend_date: date
    time_zone: str
    currency: str | None
    spend_minor: int | None
    impressions: int
    clicks: int
    refusal: str | None
    provisional_until: datetime


@dataclass(frozen=True)
class SpendInputs:
    connection_id: UUID
    provider: str
    status: str
    generation: int
    adapter_available: bool
    adapter_version: str | None
    zone: str | None
    account: Mapping[str, Any] | None
    covered_from: date | None
    complete_through: date | None  # the last complete account-local date
    in_progress: bool
    last_success_at: datetime | None
    sync: Mapping[str, Any]
    connection_last_success: datetime | None
    facts: Sequence[SpendFactInput]
    source_rows: int
    digest: str


@dataclass
class SpendResult:
    level: str
    day_zone: str | None
    totals: list[dict[str, Any]]
    comparison: list[dict[str, Any]] | None
    source_status: dict[str, Any]
    total_rows: int
    rows: Any
    semantic: dict[str, Any] = field(default_factory=dict)


def _exponent(currency: str) -> int:
    exponent = EXPONENTS.get(currency)
    if exponent is None:
        raise ReportError("unsupported_currency", 409)
    return exponent


def _coverage(inputs: SpendInputs, period: Period) -> str:
    first, last = inputs.covered_from, inputs.complete_through
    if first is None or last is None or inputs.zone is None:
        return "not_synced"
    final = period.end - timedelta(days=1)
    if first <= period.start and final <= last:
        return "complete"
    overlap = first <= final and period.start <= last
    return "partial" if overlap else "not_synced"


class _Period:
    """The facts of one period, aggregated by currency and by (object key, currency)."""

    def __init__(self, inputs: SpendInputs, period: Period, level: str, now: datetime) -> None:
        self.period, self.now = period, now
        key_name = KEYS[level]
        self.totals: dict[str, dict[str, Any]] = {}
        self.groups: dict[tuple[str, str], dict[str, Any]] = {}
        self.refused = dict.fromkeys(REFUSALS, 0)
        self.provisional: set[date] = set()
        self.zones: set[str] = set()
        self.facts = 0
        for fact in inputs.facts:
            if not period.contains(fact.spend_date):
                continue
            self.facts += 1
            self.zones.add(fact.time_zone)
            if fact.provisional_until > now:
                self.provisional.add(fact.spend_date)
            if fact.refusal is not None or fact.spend_minor is None or fact.currency is None:
                reason = fact.refusal if fact.refusal in REFUSALS else "unparseable_amount"
                self.refused[reason] += 1
                continue
            _exponent(fact.currency)
            total = self.totals.setdefault(
                fact.currency,
                {
                    "spend_minor": 0,
                    "impressions": 0,
                    "clicks": 0,
                    "days": set(),
                    "provisional": False,
                },
            )
            total["spend_minor"] += fact.spend_minor
            total["impressions"] += fact.impressions
            total["clicks"] += fact.clicks
            total["days"].add(fact.spend_date)
            total["provisional"] = total["provisional"] or fact.provisional_until > now
            key = getattr(fact, key_name) or ""
            group = self.groups.setdefault(
                (key, fact.currency),
                {
                    "spend_minor": 0,
                    "impressions": 0,
                    "clicks": 0,
                    "days": set(),
                    "provisional": False,
                },
            )
            group["spend_minor"] += fact.spend_minor
            group["impressions"] += fact.impressions
            group["clicks"] += fact.clicks
            group["days"].add(fact.spend_date)
            group["provisional"] = group["provisional"] or fact.provisional_until > now


def _status(inputs: SpendInputs, aggregate: _Period) -> tuple[str, str | None]:
    if inputs.in_progress:
        return "partial", "sync_in_progress"
    coverage = _coverage(inputs, aggregate.period)
    if coverage != "complete":
        return "partial", "coverage_incomplete"
    if any(aggregate.refused.values()):
        return "partial", "refused_facts"
    if inputs.zone is not None and aggregate.zones - {inputs.zone}:
        return "partial", "time_zone_changed"
    return "complete", None


def _totals(inputs: SpendInputs, aggregate: _Period, label: str) -> list[dict[str, Any]]:
    status, reason = _status(inputs, aggregate)
    items = []
    for currency, values in sorted(aggregate.totals.items()):
        exponent = _exponent(currency)
        items.append(
            {
                "period": label,
                "currency": currency,
                "exponent": exponent,
                "spend": amount(int(values["spend_minor"]), exponent),
                "impressions": values["impressions"],
                "clicks": values["clicks"],
                "days_with_spend": len(values["days"]),
                "provisional": bool(values["provisional"]),
                "status": status,
                "reason": reason,
            }
        )
    return items


def _period_status(inputs: SpendInputs, aggregate: _Period, label: str) -> dict[str, Any]:
    status, reason = _status(inputs, aggregate)
    return {
        "period": label,
        "start": aggregate.period.start,
        "end": aggregate.period.end,
        "coverage": _coverage(inputs, aggregate.period),
        "facts": aggregate.facts,
        "valued_facts": aggregate.facts - sum(aggregate.refused.values()),
        "refused": dict(aggregate.refused),
        "provisional_dates": sorted(aggregate.provisional),
        "fact_zones": sorted(aggregate.zones),
        "status": status if aggregate.facts else "unavailable",
        "reason": reason if aggregate.facts else "no_spend_facts",
    }


def _freshness(inputs: SpendInputs, now: datetime) -> str:
    if inputs.last_success_at is None:
        return "never_synced"
    window = timedelta(hours=FRESHNESS_HOURS)
    return "stale" if now - inputs.last_success_at > window else "fresh"


def _comparison(
    inputs: SpendInputs, current: _Period, previous: _Period, now: datetime
) -> list[dict[str, Any]]:
    rows = []
    blocked = None
    current_status, _ = _status(inputs, current)
    previous_status, _ = _status(inputs, previous)
    if inputs.in_progress:
        blocked = "sync_in_progress"
    elif "partial" in (current_status, previous_status):
        blocked = "partial"
    elif current.provisional or previous.provisional:
        blocked = "provisional"
    elif _freshness(inputs, now) != "fresh":
        blocked = "stale"
    for currency in sorted(set(current.totals) | set(previous.totals)):
        exponent = _exponent(currency)
        mine = current.totals.get(currency)
        theirs = previous.totals.get(currency)
        reason = blocked or (None if mine is not None and theirs is not None else "no_spend_facts")
        for metric in METRICS:
            column = "spend_minor" if metric == "spend" else metric
            now_value = None if mine is None else int(mine[column])
            then_value = None if theirs is None else int(theirs[column])
            result = compare_values(now_value, then_value, reason)
            if metric == "spend":
                result["difference"] = (
                    None if result["difference"] is None else amount(result["difference"], exponent)
                )
            rows.append(
                {
                    "currency": currency,
                    "exponent": exponent,
                    "metric": metric,
                    "current_value": now_value
                    if metric != "spend" or now_value is None
                    else amount(now_value, exponent),
                    "previous_value": then_value
                    if metric != "spend" or then_value is None
                    else amount(then_value, exponent),
                    **result,
                }
            )
    return rows


def spend_report(
    inputs: SpendInputs,
    level: str,
    period: Period,
    previous: Period | None,
    now: datetime,
) -> SpendResult:
    if level not in LEVELS:
        raise ReportError("invalid_level", 422)
    current = _Period(inputs, period, level, now)
    totals = _totals(inputs, current, "current")
    periods = [_period_status(inputs, current, "current")]
    comparison = None
    before = None
    if previous is not None:
        before = _Period(inputs, previous, level, now)
        totals += _totals(inputs, before, "previous")
        periods.append(_period_status(inputs, before, "previous"))
        comparison = _comparison(inputs, current, before, now)
    ordered = sorted(current.groups)

    def rows() -> Iterator[dict[str, Any]]:
        for key, currency in ordered:
            values = current.groups[key, currency]
            exponent = _exponent(currency)
            yield {
                "object_id": key or None,
                "currency": currency,
                "exponent": exponent,
                "spend": amount(int(values["spend_minor"]), exponent),
                "impressions": values["impressions"],
                "clicks": values["clicks"],
                "days_with_spend": len(values["days"]),
                "provisional": bool(values["provisional"]),
            }

    account = inputs.account
    source = {
        "provider": inputs.provider,
        "adapter_state": "available" if inputs.adapter_available else "unavailable",
        "adapter_version": inputs.adapter_version,
        "connection_status": inputs.status,
        "connection_last_successful_sync_at": inputs.connection_last_success,
        "account": None if account is None else dict(account),
        "stream": {
            "stream": DAILY_STREAM,
            "covered_from": inputs.covered_from,
            "complete_through": inputs.complete_through,
            "sync": {
                "state": inputs.sync.get("state", "idle"),
                "reason": inputs.sync.get("reason"),
                "in_progress": inputs.in_progress,
            },
            "freshness": {
                "state": _freshness(inputs, now),
                "freshness_hours": FRESHNESS_HOURS,
                "last_stream_success_at": inputs.last_success_at,
            },
        },
        "periods": periods,
        "source_rows": inputs.source_rows,
    }
    semantic = {
        "provisional": [sorted(current.provisional)]
        + ([sorted(before.provisional)] if before is not None else []),
        "freshness": _freshness(inputs, now),
        "sync": dict(inputs.sync),
    }
    return SpendResult(
        level=level,
        day_zone=inputs.zone,
        totals=totals,
        comparison=comparison,
        source_status=source,
        total_rows=len(ordered),
        rows=rows,
        semantic=semantic,
    )
