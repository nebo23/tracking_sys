"""Return on advertising spend, an in-memory contract (specification 014-C, D-064 decision D11).

roas_report answers one client, one spend connection, a period of account-local dates and one
008-A model version. It returns rows per ad, rolled up per ad set and campaign:

- Spend: the period's stored spend facts of the connection, per currency. A refused fact or a
  day outside the coverage makes the row's spend "incomplete"; a fact still within its 28-day
  re-read makes it "provisional".
- Revenue: for each run of the model version whose sale instant falls in the period on the
  account's local calendar (conversion-date basis), each allocation whose touch carries Meta's
  dynamic URL parameters (V-18): source "meta", campaign_ref equal to the ad's campaign ID and
  content_ref equal to the ad ID, is credited to that ad. Credit of any other touch, or for an
  ad of another account, is unmatched and reported separately per currency. Names never join.
- Value: ROAS is credited revenue divided by spend, both in minor units of one currency, as an
  exact fraction and a 4-decimal string, only when spend is above zero. Zero spend has no value
  (zero_spend), never an infinite or very large number; spend or credit in more than one
  currency has no value (currency_mismatch). Spend above zero with no credit gives 0.
- Labels: every row names its model, version, window, period, currency and basis.

Runs of another model version or another client are refused; models are never added together
and amounts are never converted. There is no route; read routes and reports belong to 016.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.advertising.currencies import EXPONENTS
from app.attribution import AttributionInputError, AttributionModel, AttributionRun, ModelVersion
from app.ledger import Currency, Money

BASIS = "conversion_date"
META_SOURCE = "meta"
Level = Literal["ad", "adset", "campaign"]
SpendState = Literal["complete", "provisional", "incomplete"]
STATE_ORDER = {"complete": 0, "provisional": 1, "incomplete": 2}


@dataclass(frozen=True)
class SpendFactView:
    """One stored spend fact as the contract reads it (ad_spend_facts)."""

    ad_id: str
    adset_id: str | None
    campaign_id: str | None
    spend_date: date
    currency: str | None
    spend_minor: int | None
    refusal: str | None
    provisional_until: datetime


@dataclass(frozen=True)
class Period:
    """Account-local dates since..until, both inclusive."""

    since: date
    until: date

    def __post_init__(self) -> None:
        if self.until < self.since:
            raise AttributionInputError("invalid_period")

    def __contains__(self, day: object) -> bool:
        return isinstance(day, date) and self.since <= day <= self.until

    def days(self) -> tuple[date, ...]:
        count = (self.until - self.since).days + 1
        return tuple(self.since + timedelta(days=offset) for offset in range(count))


@dataclass(frozen=True)
class RoasRow:
    level: Level
    object_id: str
    campaign_id: str | None
    adset_id: str | None
    model: AttributionModel
    model_version: str
    window: timedelta
    period: Period
    basis: str
    currency: str | None
    spend: Money | None
    credited: Money | None
    roas: Fraction | None
    roas_text: str | None
    reason: Literal["zero_spend", "currency_mismatch"] | None
    spend_state: SpendState


@dataclass(frozen=True)
class RoasReport:
    connection_id: UUID
    model_version: ModelVersion
    period: Period
    zone: str
    basis: str
    rows: tuple[RoasRow, ...]
    unmatched: tuple[Money, ...]


def _money(minor: int, code: str) -> Money:
    return Money(minor, Currency(code, EXPONENTS.get(code, 2)))


def _text(value: Fraction) -> str:
    quotient = Decimal(value.numerator) / Decimal(value.denominator)
    return str(quotient.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))


# The latest revision of each conversion, refusing another model version or client.
def _latest(
    runs: Iterable[AttributionRun], version: ModelVersion, agency_id: UUID, client_id: UUID
) -> list[AttributionRun]:
    latest: dict[tuple, AttributionRun] = {}
    for run in runs:
        if not isinstance(run, AttributionRun):
            raise AttributionInputError("invalid_run")
        if run.model_version != version:
            raise AttributionInputError("model_version_mismatch")
        conversion = run.conversion
        if (conversion.agency_id, conversion.client_id) != (agency_id, client_id):
            raise AttributionInputError("foreign_run")
        known = latest.get(conversion.key)
        if known is None or run.revision > known.revision:
            latest[conversion.key] = run
    return [latest[key] for key in sorted(latest)]


@dataclass
class _Totals:
    spend: dict[str, int]
    credit: dict[str, int]
    state: SpendState

    def merge(self, other: "_Totals") -> None:
        for code, minor in other.spend.items():
            self.spend[code] = self.spend.get(code, 0) + minor
        for code, minor in other.credit.items():
            self.credit[code] = self.credit.get(code, 0) + minor
        if STATE_ORDER[other.state] > STATE_ORDER[self.state]:
            self.state = other.state


def _row(
    level: Level,
    object_id: str,
    parents: tuple[str | None, str | None],
    totals: _Totals,
    version: ModelVersion,
    period: Period,
) -> RoasRow:
    spend_codes = {code for code, minor in totals.spend.items()}
    credit_codes = {code for code, minor in totals.credit.items() if minor}
    codes = spend_codes | credit_codes
    currency = next(iter(codes)) if len(codes) == 1 else None
    spend = _money(totals.spend[currency], currency) if currency in totals.spend else None
    credited = _money(totals.credit.get(currency, 0), currency) if currency is not None else None
    spent = sum(totals.spend.values())
    reason: Literal["zero_spend", "currency_mismatch"] | None = None
    value: Fraction | None = None
    if len(codes) > 1:
        reason = "currency_mismatch"
    elif not spent:
        reason = "zero_spend"
    else:
        assert currency is not None and spend is not None and credited is not None
        value = Fraction(credited.minor, spend.minor)
    return RoasRow(
        level,
        object_id,
        parents[0],
        parents[1],
        version.model,
        version.version_id,
        version.window,
        period,
        BASIS,
        currency,
        spend,
        credited,
        value,
        None if value is None else _text(value),
        reason,
        totals.state,
    )


def roas_report(
    facts: Iterable[SpendFactView],
    runs: Iterable[AttributionRun],
    *,
    agency_id: UUID,
    client_id: UUID,
    connection_id: UUID,
    period: Period,
    zone: str,
    model_version: ModelVersion,
    as_of: datetime,
    covered: tuple[date, date] | None = None,
    objects: Mapping[str, tuple[str, str | None]] | None = None,
) -> RoasReport:
    """ROAS rows for one connection, period, zone and model version (see the module docstring).

    covered is the first and last complete account-local date of the daily stream; a day of the
    period outside it makes the spend incomplete. objects maps ad IDs of the connection to their
    (campaign ID, ad set ID), so an ad with credit but no spend in the period still has a row.
    """
    local = ZoneInfo(zone)
    ads: dict[str, tuple[str | None, str | None]] = dict(objects or {})
    per_ad: dict[str, _Totals] = {}

    def totals(ad: str) -> _Totals:
        return per_ad.setdefault(ad, _Totals({}, {}, "complete"))

    uncovered = covered is None or any(not covered[0] <= day <= covered[1] for day in period.days())
    for fact in facts:
        ads.setdefault(fact.ad_id, (fact.campaign_id, fact.adset_id))
        if fact.spend_date not in period:
            continue
        entry = totals(fact.ad_id)
        if fact.refusal is not None or fact.spend_minor is None or fact.currency is None:
            entry.state = "incomplete"
            continue
        entry.spend[fact.currency] = entry.spend.get(fact.currency, 0) + fact.spend_minor
        if fact.provisional_until > as_of and entry.state == "complete":
            entry.state = "provisional"
    unmatched: dict[str, int] = defaultdict(int)
    for run in _latest(runs, model_version, agency_id, client_id):
        instant = run.sale.effective_at if run.sale is not None else run.conversion.instant
        if instant.astimezone(local).date() not in period:
            continue
        for allocation in run.allocations:
            if allocation.amount is None:
                continue
            amount, touch = allocation.amount, allocation.touch
            ad = touch.content_ref if touch is not None else None
            matched = (
                touch is not None
                and touch.source == META_SOURCE
                and ad in ads
                and touch.campaign_ref is not None
                and touch.campaign_ref == ads[ad][0]
            )
            if not matched:
                unmatched[amount.currency.code] += amount.minor
                continue
            entry = totals(ad)
            code = amount.currency.code
            entry.credit[code] = entry.credit.get(code, 0) + amount.minor
    if uncovered:
        for entry in per_ad.values():
            entry.state = "incomplete"
    rows: list[RoasRow] = []
    adsets: dict[str, _Totals] = {}
    campaigns: dict[str, _Totals] = {}
    adset_parent: dict[str, str | None] = {}
    for ad, entry in sorted(per_ad.items()):
        campaign, adset = ads.get(ad, (None, None))
        rows.append(_row("ad", ad, (campaign, adset), entry, model_version, period))
        if adset is not None:
            adsets.setdefault(adset, _Totals({}, {}, "complete")).merge(entry)
            adset_parent[adset] = campaign
        if campaign is not None:
            campaigns.setdefault(campaign, _Totals({}, {}, "complete")).merge(entry)
    for adset, entry in sorted(adsets.items()):
        rows.append(_row("adset", adset, (adset_parent[adset], None), entry, model_version, period))
    for campaign, entry in sorted(campaigns.items()):
        rows.append(_row("campaign", campaign, (None, None), entry, model_version, period))
    return RoasReport(
        connection_id,
        model_version,
        period,
        zone,
        BASIS,
        tuple(rows),
        tuple(_money(minor, code) for code, minor in sorted(unmatched.items()) if minor),
    )


def facts_from_rows(rows: Iterable[object]) -> tuple[SpendFactView, ...]:
    """SpendFactView values of stored ad_spend_facts rows."""
    return tuple(
        SpendFactView(
            row.ad_id,  # type: ignore[attr-defined]
            row.adset_id,  # type: ignore[attr-defined]
            row.campaign_id,  # type: ignore[attr-defined]
            row.spend_date,  # type: ignore[attr-defined]
            row.currency,  # type: ignore[attr-defined]
            row.spend_minor,  # type: ignore[attr-defined]
            row.refusal,  # type: ignore[attr-defined]
            row.provisional_until,  # type: ignore[attr-defined]
        )
        for row in rows
    )


__all__ = [
    "BASIS",
    "Period",
    "RoasReport",
    "RoasRow",
    "SpendFactView",
    "facts_from_rows",
    "roas_report",
]
