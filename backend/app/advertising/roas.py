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
and amounts are never converted. roas_report has no route.

roas_from_credit (016-B, D-089 D7) applies the same row rules and roll-up to stored credit that
the caller aggregated over the account-local period: credit matches an ad when its content
reference is an ad ID of the connection and its campaign reference equals that ad's campaign
ID. The traffic source is not stored, so it is not tested. Leads are rolled up beside revenue,
and the cost per lead is the spend divided by the credited leads, an exact fraction of minor
units with a decimal text in the spend currency; it is null with zero_leads, zero_spend or
currency_mismatch. The 016-B ROAS report is built on it.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.advertising.currencies import EXPONENTS
from app.attribution import AttributionInputError, AttributionModel, AttributionRun, ModelVersion
from app.ledger import Currency, Money
from app.reporting.common import fraction_text

BASIS = "conversion_date"
META_SOURCE = "meta"
Level = Literal["ad", "adset", "campaign", "account"]
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
    leads: Fraction = field(default_factory=Fraction)  # credited leads (roas_from_credit)

    def merge(self, other: "_Totals") -> None:
        for code, minor in other.spend.items():
            self.spend[code] = self.spend.get(code, 0) + minor
        for code, minor in other.credit.items():
            self.credit[code] = self.credit.get(code, 0) + minor
        self.leads += other.leads
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


def _spend(
    facts: Iterable[SpendFactView],
    period: Period,
    as_of: datetime,
    ads: dict[str, tuple[str | None, str | None]],
    totals: Callable[[str], _Totals],
) -> None:
    """Add the period's valid spend of each ad; a refused fact makes it incomplete."""
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


def matched_ad(
    campaign_ref: str | None,
    content_ref: str | None,
    ads: Mapping[str, tuple[str | None, str | None]],
) -> str | None:
    """The ad a credit belongs to: its content reference is an ad ID of the connection and its
    campaign reference is that ad's campaign ID; None otherwise (unmatched)."""
    if content_ref is None or content_ref not in ads or campaign_ref is None:
        return None
    return content_ref if campaign_ref == ads[content_ref][0] else None


def _uncovered(period: Period, covered: tuple[date, date] | None) -> bool:
    return covered is None or any(not covered[0] <= day <= covered[1] for day in period.days())


def _rollup(
    per_ad: Mapping[str, _Totals],
    ads: Mapping[str, tuple[str | None, str | None]],
    version: ModelVersion,
    period: Period,
) -> list[tuple[RoasRow, _Totals]]:
    """Rows per ad, then per ad set and campaign, with the totals behind each row."""
    rows: list[tuple[RoasRow, _Totals]] = []
    adsets: dict[str, _Totals] = {}
    campaigns: dict[str, _Totals] = {}
    adset_parent: dict[str, str | None] = {}
    for ad, entry in sorted(per_ad.items()):
        campaign, adset = ads.get(ad, (None, None))
        rows.append((_row("ad", ad, (campaign, adset), entry, version, period), entry))
        if adset is not None:
            adsets.setdefault(adset, _Totals({}, {}, "complete")).merge(entry)
            adset_parent[adset] = campaign
        if campaign is not None:
            campaigns.setdefault(campaign, _Totals({}, {}, "complete")).merge(entry)
    for adset, entry in sorted(adsets.items()):
        rows.append(
            (_row("adset", adset, (adset_parent[adset], None), entry, version, period), entry)
        )
    for campaign, entry in sorted(campaigns.items()):
        rows.append((_row("campaign", campaign, (None, None), entry, version, period), entry))
    return rows


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

    _spend(facts, period, as_of, ads, totals)
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
                and matched_ad(touch.campaign_ref, ad, ads) is not None
            )
            if not matched:
                unmatched[amount.currency.code] += amount.minor
                continue
            entry = totals(ad)
            code = amount.currency.code
            entry.credit[code] = entry.credit.get(code, 0) + amount.minor
    if _uncovered(period, covered):
        for entry in per_ad.values():
            entry.state = "incomplete"
    rows = [row for row, _ in _rollup(per_ad, ads, model_version, period)]
    return RoasReport(
        connection_id,
        model_version,
        period,
        zone,
        BASIS,
        tuple(rows),
        tuple(_money(minor, code) for code, minor in sorted(unmatched.items()) if minor),
    )


@dataclass(frozen=True)
class CreditTotal:
    """Stored credit of one model version over an account-local period (016-B), aggregated by
    campaign reference, content reference, kind and currency: a sale total holds its minor
    units and its credited share, a lead total its credited share (currency None)."""

    campaign_ref: str | None
    content_ref: str | None
    kind: Literal["sale", "lead"]
    currency: str | None
    minor: int
    share: Fraction


@dataclass(frozen=True)
class CreditRoasRow:
    row: RoasRow
    leads: Fraction
    cost_per_lead: Fraction | None  # spend minor units per credited lead
    cost_per_lead_text: str | None
    cost_per_lead_reason: Literal["zero_leads", "zero_spend", "currency_mismatch"] | None


@dataclass(frozen=True)
class CreditRoasReport:
    report: RoasReport
    rows: tuple[CreditRoasRow, ...]  # aligned with report.rows
    total: CreditRoasRow  # level account: every ad of the connection
    unmatched_leads: Fraction


def _cost_per_lead(row: RoasRow, leads: Fraction) -> CreditRoasRow:
    if row.reason == "currency_mismatch":
        return CreditRoasRow(row, leads, None, None, "currency_mismatch")
    if row.spend is None or row.spend.minor == 0:
        return CreditRoasRow(row, leads, None, None, "zero_spend")
    if leads == 0:
        return CreditRoasRow(row, leads, None, None, "zero_leads")
    value = Fraction(row.spend.minor) / leads
    exponent = row.spend.currency.exponent
    return CreditRoasRow(row, leads, value, fraction_text(value / 10**exponent, exponent), None)


def roas_from_credit(
    facts: Iterable[SpendFactView],
    credit: Iterable[CreditTotal],
    *,
    connection_id: UUID,
    period: Period,
    zone: str,
    model_version: ModelVersion,
    as_of: datetime,
    covered: tuple[date, date] | None = None,
    objects: Mapping[str, tuple[str, str | None]] | None = None,
) -> CreditRoasReport:
    """ROAS and cost per lead from stored credit with the roas_report rules (016-B, D-089 D7).

    credit is the stored credit of model_version whose conversion instant falls in the period on
    the account's local calendar, aggregated by the caller; facts, covered and objects are as
    for roas_report. Credit that netted to nothing (it moved to another reference) adds no row.
    """
    ads: dict[str, tuple[str | None, str | None]] = dict(objects or {})
    per_ad: dict[str, _Totals] = {}

    def totals(ad: str) -> _Totals:
        return per_ad.setdefault(ad, _Totals({}, {}, "complete"))

    _spend(facts, period, as_of, ads, totals)
    unmatched: dict[str, int] = defaultdict(int)
    unmatched_leads = Fraction(0)
    for item in credit:
        if item.minor == 0 and item.share == 0:
            continue
        ad = matched_ad(item.campaign_ref, item.content_ref, ads)
        if ad is None:
            if item.kind == "sale" and item.currency is not None:
                unmatched[item.currency] += item.minor
            else:
                unmatched_leads += item.share
            continue
        entry = totals(ad)
        if item.kind == "sale" and item.currency is not None:
            entry.credit[item.currency] = entry.credit.get(item.currency, 0) + item.minor
        else:
            entry.leads += item.share
    uncovered = _uncovered(period, covered)
    if uncovered:
        for entry in per_ad.values():
            entry.state = "incomplete"
    pairs = _rollup(per_ad, ads, model_version, period)
    account = _Totals({}, {}, "incomplete" if uncovered else "complete")
    for entry in per_ad.values():
        account.merge(entry)
    total = _row("account", str(connection_id), (None, None), account, model_version, period)
    report = RoasReport(
        connection_id,
        model_version,
        period,
        zone,
        BASIS,
        tuple(row for row, _ in pairs),
        tuple(_money(minor, code) for code, minor in sorted(unmatched.items()) if minor),
    )
    return CreditRoasReport(
        report,
        tuple(_cost_per_lead(row, entry.leads) for row, entry in pairs),
        _cost_per_lead(total, account.leads),
        unmatched_leads,
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
    "CreditRoasReport",
    "CreditRoasRow",
    "CreditTotal",
    "Period",
    "RoasReport",
    "RoasRow",
    "SpendFactView",
    "facts_from_rows",
    "matched_ad",
    "roas_from_credit",
    "roas_report",
]
