"""Attribution credit reports over stored 008-B credit (specification 016-B, D-089 D2 to D6).

The reporting service reads, in one snapshot, the consumer state and status of a client's
stored attribution, its model versions and the credit changes of the published generation,
aggregated in SQL by period, model version, recipient class, grouped reference, kind, currency
and share denominator. This module adds the shares exactly (fractions.Fraction, never floating
point), keeps money in original-currency minor units, and builds the attribution report:

- groups: one row per group with its credited revenue and credited sales per currency (sale
  values only with finance:read), its credited leads and the conversions holding credit in it.
  Direct and unknown credit are rows of their own; campaign credit without the grouped
  reference is a campaign row without a reference.
- models: the same groups under every active model version side by side, never added up.

Every report names its model version, basis (the conversion date, UTC dates) and freshness.
Before the first publication every value is null with attribution_not_ready; while the
consumer is behind, rebuilding or failed, values come from the published generation, labeled,
and no comparison percentage is authoritative. The reconciliation compares credited revenue
with the persisted ledger's verified net per currency. Nothing here names a person, a touch,
an event, a title or a label.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any
from uuid import UUID

from app.reporting.common import (
    ReportError,
    amount,
    compare_fractions,
    compare_values,
    share,
)

RECIPIENTS = ("campaign", "direct", "unknown")
RECIPIENT_ORDER = {name: index for index, name in enumerate(RECIPIENTS)}
GROUP_BYS = ("campaign", "content", "link", "recipient")
PERIODS = ("current", "previous")
BASIS = "conversion_date"
NOT_READY = "attribution_not_ready"
MAX_GROUPS = 10_000  # groups per report (D10)


@dataclass(frozen=True)
class CreditRow:
    """One aggregated SQL row of stored credit changes (section 2 of the design note)."""

    version_id: UUID
    period: str
    recipient: str
    ref: str | None
    kind: str
    currency: str | None
    exponent: int | None
    share: Fraction
    minor: int | None


@dataclass(frozen=True)
class CountRow:
    """Conversions whose latest revision credits a group (or a recipient class) in a period."""

    version_id: UUID
    period: str
    recipient: str
    ref: str | None
    kind: str
    currency: str | None
    exponent: int | None
    conversions: int
    unassociated: int = 0


@dataclass(frozen=True)
class LedgerTotal:
    period: str
    currency: str
    exponent: int
    net_minor: int


@dataclass(frozen=True)
class GroupMeta:
    """Registered flags and social content pointers of the grouped references."""

    registered: Mapping[str, bool] = field(default_factory=dict)
    pointers: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)


@dataclass(frozen=True)
class AttributionContext:
    """The stored attribution of one client as read in the report snapshot."""

    state: str  # caught_up, behind, rebuilding or failed
    generation: int  # the published generation; 0 before the first publication
    published_at: datetime | None
    failure_code: str | None
    unit: str | None
    consumer: Mapping[str, Any]
    current: Mapping[str, Any]
    versions: tuple[Mapping[str, Any], ...]  # every version view, in creation order
    version: Mapping[str, Any] | None  # the selected version (None for the models view)

    @property
    def active(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(item for item in self.versions if item["status"] == "active")

    def ready(self, models: bool = False) -> bool:
        if self.generation <= 0:
            return False
        return bool(self.active) if models else self.version is not None

    # The reason a comparison or reconciliation is not authoritative, or None.
    def blocked(self, models: bool = False) -> str | None:
        if not self.ready(models):
            return NOT_READY
        return None if self.state == "caught_up" else f"attribution_{self.state}"

    def block(self, models: bool = False) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": None if self.ready(models) else NOT_READY,
            "published_generation": self.generation,
            "published_at": self.published_at,
            "failure_code": self.failure_code,
            "unit": self.unit,
            "consumer": dict(self.consumer),
            "current": dict(self.current),
        }


@dataclass
class Values:
    """Exact credit of one group or recipient class: sales per (currency, exponent) as
    [minor, share, conversions, unassociated] and leads as [share, conversions]."""

    sales: dict[tuple[str, int], list] = field(default_factory=dict)
    leads: list = field(default_factory=lambda: [Fraction(0), 0])

    def add_credit(self, row: CreditRow) -> None:
        if row.kind == "sale":
            entry = self._sale(row.currency, row.exponent)
            entry[0] += row.minor or 0
            entry[1] += row.share
        else:
            self.leads[0] += row.share

    def add_count(self, row: CountRow) -> None:
        if row.kind == "sale":
            entry = self._sale(row.currency, row.exponent)
            entry[2] += row.conversions
            entry[3] += row.unassociated
        else:
            self.leads[1] += row.conversions

    def _sale(self, currency: str | None, exponent: int | None) -> list:
        if currency is None or exponent is None:
            raise ReportError("currency_exponent_conflict", 409)
        return self.sales.setdefault((currency, exponent), [0, Fraction(0), 0, 0])

    @property
    def nonzero(self) -> bool:
        return bool(self.leads[0] or self.leads[1]) or any(
            entry[0] or entry[1] or entry[2] for entry in self.sales.values()
        )


def check_currencies(items: Iterable[Any]) -> None:
    """Refuse one currency code with two exponents (never added by code)."""
    known: dict[str, int] = {}
    for item in items:
        code, exponent = getattr(item, "currency", None), getattr(item, "exponent", None)
        if code is None:
            continue
        if known.setdefault(code, exponent) != exponent:
            raise ReportError("currency_exponent_conflict", 409)


GroupKey = tuple[str, str | None]


def group_key(row: CreditRow | CountRow, group_by: str) -> GroupKey:
    if group_by == "recipient" or row.recipient != "campaign":
        return row.recipient, None
    return row.recipient, row.ref


def order(key: GroupKey) -> tuple:
    recipient, ref = key
    return RECIPIENT_ORDER[recipient], ref is None, ref or ""


def groups(
    credit: Iterable[CreditRow],
    counts: Iterable[CountRow],
    version_id: UUID,
    period: str,
    group_by: str,
) -> dict[GroupKey, Values]:
    found: dict[GroupKey, Values] = {}
    for row in credit:
        if row.version_id == version_id and row.period == period:
            found.setdefault(group_key(row, group_by), Values()).add_credit(row)
    for row in counts:
        if row.version_id == version_id and row.period == period:
            found.setdefault(group_key(row, group_by), Values()).add_count(row)
    return found


def recipients(
    credit: Iterable[CreditRow],
    counts: Iterable[CountRow],
    version_id: UUID,
    period: str,
) -> dict[str, Values]:
    """Totals per recipient class; counts are distinct conversions per class (one class per
    revision), so the class counts add up to the total count."""
    found = {name: Values() for name in RECIPIENTS}
    for row in credit:
        if row.version_id == version_id and row.period == period:
            found[row.recipient].add_credit(row)
    for row in counts:
        if row.version_id == version_id and row.period == period:
            found[row.recipient].add_count(row)
    return found


def group_refs(credit: Iterable[CreditRow], group_by: str) -> tuple[str, ...]:
    """The grouped references that need a registered flag (and, for content, a pointer)."""
    if group_by == "recipient":
        return ()
    return tuple(
        sorted({row.ref for row in credit if row.recipient == "campaign" and row.ref is not None})
    )


def _total(values: Iterable[Values]) -> Values:
    result = Values()
    for item in values:
        for key, entry in item.sales.items():
            mine = result.sales.setdefault(key, [0, Fraction(0), 0, 0])
            for index in range(4):
                mine[index] += entry[index]
        result.leads[0] += item.leads[0]
        result.leads[1] += item.leads[1]
    return result


def sale_items(values: Values) -> list[dict[str, Any]]:
    return [
        {
            "currency": code,
            "exponent": exponent,
            "credited_revenue": amount(int(entry[0]), exponent),
            "credited_sales": share(entry[1]),
            "conversions": int(entry[2]),
        }
        for (code, exponent), entry in sorted(values.sales.items())
        if entry[0] or entry[1] or entry[2]
    ]


def sales_block(values: Values, finance: bool) -> dict[str, Any]:
    if not finance:
        return {"state": "permission_unavailable", "items": None}
    return {"state": "available", "items": sale_items(values)}


def leads_block(values: Values) -> dict[str, Any]:
    return {"credited_leads": share(values.leads[0]), "conversions": int(values.leads[1])}


def _currencies(credit: Iterable[CreditRow], version_id: UUID) -> list[tuple[str, int]]:
    return sorted(
        {
            (row.currency, row.exponent)
            for row in credit
            if row.version_id == version_id and row.kind == "sale" and row.currency is not None
        }
    )


def totals_block(
    context: AttributionContext,
    credit: Sequence[CreditRow],
    counts: Sequence[CountRow],
    version_id: UUID | None,
    labels: Sequence[str],
    finance: bool,
    models: bool = False,
) -> dict[str, Any]:
    if version_id is None or not context.ready(models):
        reason = NOT_READY
        sales_state = "not_ready" if finance else "permission_unavailable"
        return {
            "sales": {"state": sales_state, "reason": reason, "items": None},
            "leads": {"state": "not_ready", "reason": reason, "items": None},
        }
    currencies = _currencies(credit, version_id)
    sales, leads = [], []
    for label in labels:
        classes = recipients(credit, counts, version_id, label)
        overall = _total(classes.values())
        for recipient, values in (("all", overall), *classes.items()):
            leads.append({"period": label, "recipient": recipient, **leads_block(values)})
            for code, exponent in currencies:
                entry = values.sales.get((code, exponent), [0, Fraction(0), 0, 0])
                sales.append(
                    {
                        "period": label,
                        "currency": code,
                        "exponent": exponent,
                        "recipient": recipient,
                        "credited_revenue": amount(int(entry[0]), exponent),
                        "credited_sales": share(entry[1]),
                        "conversions": int(entry[2]),
                    }
                )
    sale_part = (
        {"state": "available", "reason": None, "items": sales}
        if finance
        else {"state": "permission_unavailable", "reason": None, "items": None}
    )
    return {"sales": sale_part, "leads": {"state": "available", "reason": None, "items": leads}}


def reconciliation_block(
    context: AttributionContext,
    credit: Sequence[CreditRow],
    version_id: UUID | None,
    labels: Sequence[str],
    ledger_state: str,
    ledger: Sequence[LedgerTotal],
    finance: bool,
    models: bool = False,
) -> dict[str, Any]:
    if not finance:
        return {"state": "permission_unavailable", "reason": None, "ledger": None, "items": None}
    if version_id is None or not context.ready(models):
        return {"state": "not_ready", "reason": NOT_READY, "ledger": ledger_state, "items": None}
    if ledger_state == "unavailable":
        return {
            "state": "unavailable",
            "reason": "ledger_unavailable",
            "ledger": ledger_state,
            "items": None,
        }
    check_currencies([*credit, *ledger])
    behind = context.blocked(models)
    items = []
    for label in labels:
        credited: dict[tuple[str, int], int] = {}
        for row in credit:
            if row.version_id == version_id and row.period == label and row.kind == "sale":
                key = (row.currency, row.exponent)
                credited[key] = credited.get(key, 0) + (row.minor or 0)
        booked = {
            (item.currency, item.exponent): item.net_minor
            for item in ledger
            if item.period == label
        }
        for code, exponent in sorted(set(credited) | set(booked)):
            mine, theirs = credited.get((code, exponent), 0), booked.get((code, exponent), 0)
            difference = mine - theirs
            reason = None if difference == 0 else (behind or "unexplained_difference")
            items.append(
                {
                    "period": label,
                    "currency": code,
                    "exponent": exponent,
                    "credited_revenue": amount(mine, exponent),
                    "ledger_net": amount(theirs, exponent),
                    "difference": amount(difference, exponent),
                    "state": "reconciled" if difference == 0 else "difference",
                    "reason": reason,
                }
            )
    return {"state": "available", "reason": None, "ledger": ledger_state, "items": items}


def comparison_rows(
    context: AttributionContext,
    credit: Sequence[CreditRow],
    counts: Sequence[CountRow],
    version_id: UUID | None,
    finance: bool,
) -> list[dict[str, Any]]:
    """Totals of the current period against the previous one (all recipient classes)."""
    if version_id is None or not context.ready():
        return []
    blocked = context.blocked()
    current = _total(recipients(credit, counts, version_id, "current").values())
    previous = _total(recipients(credit, counts, version_id, "previous").values())
    rows: list[dict[str, Any]] = []
    if finance:
        for code, exponent in _currencies(credit, version_id):
            mine = current.sales.get((code, exponent), [0, Fraction(0), 0, 0])
            theirs = previous.sales.get((code, exponent), [0, Fraction(0), 0, 0])
            money = compare_values(int(mine[0]), int(theirs[0]), blocked)
            if money["difference"] is not None:
                money["difference"] = amount(money["difference"], exponent)
            rows.append(
                {
                    "metric": "credited_revenue",
                    "kind": "sale",
                    "currency": code,
                    "exponent": exponent,
                    "current_value": amount(int(mine[0]), exponent),
                    "previous_value": amount(int(theirs[0]), exponent),
                    **money,
                }
            )
            rows.append(
                {
                    "metric": "credited_sales",
                    "kind": "sale",
                    "currency": code,
                    "exponent": exponent,
                    "current_value": share(mine[1]),
                    "previous_value": share(theirs[1]),
                    **compare_fractions(mine[1], theirs[1], blocked),
                }
            )
            rows.append(
                {
                    "metric": "sale_conversions",
                    "kind": "sale",
                    "currency": code,
                    "exponent": exponent,
                    "current_value": int(mine[2]),
                    "previous_value": int(theirs[2]),
                    **compare_values(int(mine[2]), int(theirs[2]), blocked),
                }
            )
    rows.append(
        {
            "metric": "credited_leads",
            "kind": "lead",
            "currency": None,
            "exponent": None,
            "current_value": share(current.leads[0]),
            "previous_value": share(previous.leads[0]),
            **compare_fractions(current.leads[0], previous.leads[0], blocked),
        }
    )
    rows.append(
        {
            "metric": "lead_conversions",
            "kind": "lead",
            "currency": None,
            "exponent": None,
            "current_value": int(current.leads[1]),
            "previous_value": int(previous.leads[1]),
            **compare_values(int(current.leads[1]), int(previous.leads[1]), blocked),
        }
    )
    return rows


def meta_cells(key: GroupKey, group_by: str, meta: GroupMeta) -> dict[str, Any]:
    recipient, ref = key
    named = group_by != "recipient" and recipient == "campaign" and ref is not None
    pointers = None
    if group_by == "content" and recipient == "campaign":
        pointers = [dict(item) for item in meta.pointers.get(ref, ())] if ref is not None else []
    return {
        "recipient": recipient,
        "group_ref": ref,
        "registered": bool(meta.registered.get(ref, False)) if named else None,
        "content_items": pointers,
    }


@dataclass
class CreditReport:
    body: dict[str, Any]
    total_rows: int
    rows: Callable[[], Iterator[dict[str, Any]]]


def attribution_report(
    context: AttributionContext,
    group_by: str,
    view: str,
    labels: Sequence[str],
    credit: Sequence[CreditRow],
    counts: Sequence[CountRow],
    recipient_counts: Sequence[CountRow],
    ledger_state: str,
    ledger: Sequence[LedgerTotal],
    meta: GroupMeta,
    finance: bool,
) -> CreditReport:
    if group_by not in GROUP_BYS:
        raise ReportError("validation_failed", 422)
    check_currencies([*credit, *counts, *recipient_counts, *ledger])
    models = view == "models"
    compare = "previous" in labels
    if not models:
        version_id = None if context.version is None else UUID(str(context.version["id"]))
        ready = version_id is not None and context.ready()
        found = groups(credit, counts, version_id, "current", group_by) if ready else {}
        keys = sorted((key for key, item in found.items() if item.nonzero), key=order)
        body = {
            "view": "groups",
            "group_by": group_by,
            "model_version": None if context.version is None else dict(context.version),
            "model_versions": None,
            "attribution": context.block(),
            "finance": "available" if finance else "permission_unavailable",
            "values": {
                "state": "available" if ready else "not_ready",
                "reason": None if ready else NOT_READY,
            },
            "totals": totals_block(context, credit, recipient_counts, version_id, labels, finance),
            "model_totals": None,
            "reconciliation": reconciliation_block(
                context, credit, version_id, labels, ledger_state, ledger, finance
            ),
            "model_reconciliation": None,
            "comparison": (
                comparison_rows(context, credit, recipient_counts, version_id, finance)
                if compare
                else None
            ),
        }

        def rows() -> Iterator[dict[str, Any]]:
            for key in keys:
                values = found[key]
                yield {
                    **meta_cells(key, group_by, meta),
                    "sales": sales_block(values, finance),
                    "leads": leads_block(values),
                    "models": None,
                }

        return CreditReport(body, len(keys), rows)

    active = context.active
    ready = context.ready(models=True)
    ids = [UUID(str(item["id"])) for item in active]
    per_version = {
        version_id: (groups(credit, counts, version_id, "current", group_by) if ready else {})
        for version_id in ids
    }
    union = sorted(
        {key for found in per_version.values() for key, item in found.items() if item.nonzero},
        key=order,
    )
    body = {
        "view": "models",
        "group_by": group_by,
        "model_version": None,
        "model_versions": [dict(item) for item in active],
        "attribution": context.block(models=True),
        "finance": "available" if finance else "permission_unavailable",
        "values": {
            "state": "available" if ready else "not_ready",
            "reason": None if ready else NOT_READY,
        },
        "totals": None,
        "model_totals": [
            {
                "model_version_id": version_id,
                **totals_block(
                    context, credit, recipient_counts, version_id, labels, finance, True
                ),
            }
            for version_id in ids
        ],
        "reconciliation": None,
        "model_reconciliation": [
            {
                "model_version_id": version_id,
                **reconciliation_block(
                    context, credit, version_id, labels, ledger_state, ledger, finance, True
                ),
            }
            for version_id in ids
        ],
        "comparison": None,
    }

    def model_rows() -> Iterator[dict[str, Any]]:
        for key in union:
            yield {
                **meta_cells(key, group_by, meta),
                "sales": None,
                "leads": None,
                "models": [
                    {
                        "model_version_id": version_id,
                        "sales": sales_block(per_version[version_id].get(key, Values()), finance),
                        "leads": leads_block(per_version[version_id].get(key, Values())),
                    }
                    for version_id in ids
                ],
            }

    return CreditReport(body, len(union), model_rows)
