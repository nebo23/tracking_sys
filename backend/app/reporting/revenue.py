"""Recorded-revenue activity reports (specification 016-A, D-072 decision D5).

The input is the client's complete 007-A calculation over every stored evidence record, with
the D-070 held Paymob refunds kept out, exactly as the 015-A ledger read derives it; dates are
never filtered before the calculation, because an earlier sale or a later receipt can change
which postings are valid. The report then selects the final verified transactions' signed
entries whose effective time falls on the requested UTC dates: a sale of 100 in January and its
refund of 20 in February give +100 in January and -20 in February, as known at the current
read. A later receipt can change a reread; this is not an immutable accounting close.

Verified activity and unverified declarations stay in separate blocks, per original currency,
with no exchange rate. One currency code with two exponents is refused
(currency_exponent_conflict), never added by code. Pending, held and reconciliation counts
describe the whole client calculation (scope all_evidence). Zero postings mean zero recorded
verified activity in the bounded evidence set, not proof that every external payment has been
imported (external_completeness unknown). The prefix journal is never evaluated.
"""

from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date
from typing import Any

from app.ledger import Currency, LedgerCalculation, LedgerInputError, OperationKind
from app.reporting.common import MAX_EVIDENCE_ROWS, ReportError, amount, compare_values
from app.reporting.periods import Period

VERIFIED_METRICS = ("captured", "refunded", "charged_back", "reversed", "corrected", "net")
DECLARED_METRICS = ("sales", "refunds")
KIND_ORDER = {kind.value: index for index, kind in enumerate(OperationKind)}


@dataclass(frozen=True)
class RevenueInputs:
    calculation: LedgerCalculation
    held: Sequence[Any]  # held Paymob refunds (D-070), Evidence records
    evidence_rows: int
    digest: str
    agency_id: Any
    client_id: Any


@dataclass
class RevenueResult:
    totals: list[dict[str, Any]]
    comparison: list[dict[str, Any]] | None
    unresolved: dict[str, Any]
    total_rows: int
    rows: Any
    semantic: dict[str, Any] = field(default_factory=dict)


def _utc_date(value: Any) -> date:
    return value.astimezone(UTC).date()


def _register(currencies: dict[str, Currency], currency: Currency) -> None:
    known = currencies.get(currency.code)
    if known is not None and known != currency:
        raise ReportError("currency_exponent_conflict", 409)
    currencies[currency.code] = currency


class _Activity:
    """Verified signed entries and declared items of one client, by date."""

    def __init__(self, inputs: RevenueInputs) -> None:
        calculation = inputs.calculation
        try:
            calculation.totals(inputs.agency_id, inputs.client_id)
        except LedgerInputError as error:
            raise ReportError("currency_exponent_conflict", 409) from error
        self.verified_currencies: dict[str, Currency] = {}
        self.declared_currencies: dict[str, Currency] = {}
        # (currency, date, kind) -> [signed minor sum, postings]
        self.verified: dict[tuple[str, date, str], list[int]] = {}
        self.declared: dict[tuple[str, date, str], list[int]] = {}
        for transaction in calculation.transactions:
            scope = transaction.scope
            if scope.agency_id != inputs.agency_id or scope.client_id != inputs.client_id:
                continue
            _register(self.verified_currencies, transaction.currency)
            for entry in transaction.entries:
                if entry.amount.currency != transaction.currency:
                    raise ReportError("currency_exponent_conflict", 409)
                key = (transaction.currency.code, _utc_date(entry.effective_at), entry.kind.value)
                bucket = self.verified.setdefault(key, [0, 0])
                bucket[0] += entry.amount.minor
                bucket[1] += 1
        for item in calculation.unverified:
            if item.agency_id != inputs.agency_id or item.client_id != inputs.client_id:
                continue
            if item.kind not in (OperationKind.SALE, OperationKind.REFUND):
                raise ReportError("unsupported_declaration", 409)
            _register(self.declared_currencies, item.amount.currency)
            key = (item.amount.currency.code, _utc_date(item.effective_at), item.kind.value)
            bucket = self.declared.setdefault(key, [0, 0])
            bucket[0] += item.amount.minor
            bucket[1] += 1

    def verified_totals(self, period: Period) -> dict[str, dict[str, int]]:
        totals = {
            code: dict.fromkeys(VERIFIED_METRICS + ("postings",), 0)
            for code in self.verified_currencies
        }
        for (code, day, kind), (minor, count) in self.verified.items():
            if not period.contains(day):
                continue
            bucket = totals[code]
            bucket["postings"] += count
            bucket["net"] += minor
            if kind == OperationKind.SALE.value:
                bucket["captured"] += minor
            elif kind == OperationKind.REFUND.value:
                bucket["refunded"] -= minor
            elif kind == OperationKind.CHARGEBACK.value:
                bucket["charged_back"] -= minor
            elif kind == OperationKind.CHARGEBACK_REVERSAL.value:
                bucket["reversed"] += minor
            else:
                bucket["corrected"] += minor
        return totals

    def declared_totals(self, period: Period) -> dict[str, dict[str, int]]:
        totals = {code: {"sales": 0, "refunds": 0, "items": 0} for code in self.declared_currencies}
        for (code, day, kind), (minor, count) in self.declared.items():
            if not period.contains(day):
                continue
            bucket = totals[code]
            bucket["items"] += count
            bucket["sales" if kind == OperationKind.SALE.value else "refunds"] += minor
        return totals


def _verified_rows(activity: _Activity, period: Period, label: str) -> list[dict[str, Any]]:
    items = []
    for code, values in sorted(activity.verified_totals(period).items()):
        exponent = activity.verified_currencies[code].exponent
        items.append(
            {
                "block": "verified",
                "period": label,
                "currency": code,
                "exponent": exponent,
                **{metric: amount(values[metric], exponent) for metric in VERIFIED_METRICS},
                "postings": values["postings"],
            }
        )
    return items


def _declared_rows(activity: _Activity, period: Period, label: str) -> list[dict[str, Any]]:
    items = []
    for code, values in sorted(activity.declared_totals(period).items()):
        exponent = activity.declared_currencies[code].exponent
        items.append(
            {
                "block": "declared",
                "period": label,
                "currency": code,
                "exponent": exponent,
                "sales": amount(values["sales"], exponent),
                "refunds": amount(values["refunds"], exponent),
                "items": values["items"],
            }
        )
    return items


def _comparison(activity: _Activity, period: Period, previous: Period) -> list[dict[str, Any]]:
    rows = []
    blocks = (
        ("verified", VERIFIED_METRICS, activity.verified_totals, activity.verified_currencies),
        ("declared", DECLARED_METRICS, activity.declared_totals, activity.declared_currencies),
    )
    for block, metrics, totals, currencies in blocks:
        current, before = totals(period), totals(previous)
        for code in sorted(currencies):
            exponent = currencies[code].exponent
            for metric in metrics:
                now_value, then_value = current[code][metric], before[code][metric]
                result = compare_values(now_value, then_value, None)
                difference = result.pop("difference")
                rows.append(
                    {
                        "block": block,
                        "currency": code,
                        "exponent": exponent,
                        "metric": metric,
                        "current_value": amount(now_value, exponent),
                        "previous_value": amount(then_value, exponent),
                        "difference": None if difference is None else amount(difference, exponent),
                        **result,
                    }
                )
    return rows


def _unresolved(inputs: RevenueInputs) -> dict[str, Any]:
    calculation = inputs.calculation
    pending = Counter(item.status_reason or "pending" for item in calculation.pending)
    pending["parent_order_mismatch"] += len(inputs.held)
    reconciliation = Counter(item.reason.value for item in calculation.reconciliation)
    return {
        "scope": "all_evidence",
        "pending": sum(pending.values()),
        "pending_reasons": dict(sorted((k, v) for k, v in pending.items() if v)),
        "held": len(inputs.held),
        "reconciliation": len(calculation.reconciliation),
        "reconciliation_reasons": dict(sorted(reconciliation.items())),
        "evidence_rows": inputs.evidence_rows,
        "evidence_limit": MAX_EVIDENCE_ROWS,
        "external_completeness": "unknown",
    }


def revenue_report(inputs: RevenueInputs, period: Period, previous: Period | None) -> RevenueResult:
    activity = _Activity(inputs)
    totals = _verified_rows(activity, period, "current") + _declared_rows(
        activity, period, "current"
    )
    comparison = None
    if previous is not None:
        totals += _verified_rows(activity, previous, "previous") + _declared_rows(
            activity, previous, "previous"
        )
        comparison = _comparison(activity, period, previous)
    keys = sorted(
        [("verified", *key) for key in activity.verified if period.contains(key[1])]
        + [("declared", *key) for key in activity.declared if period.contains(key[1])],
        key=lambda item: (item[0] != "verified", item[1], item[2], KIND_ORDER[item[3]]),
    )

    def rows() -> Iterator[dict[str, Any]]:
        for block, code, day, kind in keys:
            source = activity.verified if block == "verified" else activity.declared
            currencies = (
                activity.verified_currencies
                if block == "verified"
                else activity.declared_currencies
            )
            minor, count = source[code, day, kind]
            exponent = currencies[code].exponent
            yield {
                "block": block,
                "currency": code,
                "exponent": exponent,
                "date": day,
                "kind": kind,
                "amount": amount(minor, exponent),
                "postings": count,
            }

    return RevenueResult(
        totals=totals,
        comparison=comparison,
        unresolved=_unresolved(inputs),
        total_rows=len(keys),
        rows=rows,
    )
