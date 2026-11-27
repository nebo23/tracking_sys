"""Funnel report: tracked visits beside stored credit (specification 016-B, D-089 decision D8).

Four stages per group (campaign, content or link) and for the client, each with its basis:

- tracked visits: a consenting visitor's landing page view that arrived through a managed link
  (the event carries the link ID and is not marked), counted on its UTC received date. The
  redirect itself stores nothing (005). A group whose reference no managed link of the client
  carries has unsupported visits, never 0; direct and unknown credit never has visits.
- credited leads, credited sales and credited revenue: the stored credit of the published
  generation on the UTC conversion date, as in the attribution report (sale values only with
  finance:read).

No rate between stages is reported: visits count page views of consenting visitors, while
leads and sales are credited conversions, so a later stage is not a subset of an earlier one.
The client totals hold every stored page view, those that arrived through a managed link, the
lead and sale conversions (associated and unassociated) and the verified net of the persisted
ledger.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any
from uuid import UUID

from app.reporting.common import ReportError, amount, compare_fractions, compare_values, share
from app.reporting.credit import (
    MAX_GROUPS,
    NOT_READY,
    AttributionContext,
    CountRow,
    CreditRow,
    GroupKey,
    GroupMeta,
    LedgerTotal,
    Values,
    check_currencies,
    groups,
    leads_block,
    meta_cells,
    order,
    recipients,
    sales_block,
)

GROUP_BYS = ("campaign", "content", "link")
BASES = {
    "visits": "received_date",
    "leads": "conversion_date",
    "sales": "conversion_date",
    "revenue": "conversion_date",
}


@dataclass(frozen=True)
class VisitInputs:
    """Tracked visits per (period, reference) and the page view totals per period."""

    groups: Mapping[tuple[str, str | None], int]
    totals: Mapping[str, tuple[int, int]]  # period -> (page views, link page views)
    supported: frozenset[str | None]  # references that a managed link of the client carries


def _visits(key: GroupKey, visits: VisitInputs, label: str = "current") -> dict[str, Any]:
    recipient, ref = key
    if recipient != "campaign" or ref not in visits.supported:
        return {"state": "unsupported", "count": None}
    return {"state": "available", "count": int(visits.groups.get((label, ref), 0))}


def _total_values(
    credit: Sequence[CreditRow], counts: Sequence[CountRow], version_id: UUID, label: str
) -> Values:
    result = Values()
    for item in recipients(credit, counts, version_id, label).values():
        for key, entry in item.sales.items():
            mine = result.sales.setdefault(key, [0, Fraction(0), 0, 0])
            for index in range(4):
                mine[index] += entry[index]
        result.leads[0] += item.leads[0]
        result.leads[1] += item.leads[1]
    return result


def _totals(
    context: AttributionContext,
    version_id: UUID | None,
    labels: Sequence[str],
    credit: Sequence[CreditRow],
    recipient_counts: Sequence[CountRow],
    visits: VisitInputs,
    ledger_state: str,
    ledger: Sequence[LedgerTotal],
    finance: bool,
) -> list[dict[str, Any]]:
    ready = version_id is not None and context.ready()
    result = []
    for label in labels:
        page_views, link_page_views = visits.totals.get(label, (0, 0))
        item: dict[str, Any] = {
            "period": label,
            "page_views": page_views,
            "link_page_views": link_page_views,
        }
        if not ready:
            item["leads"] = {"state": "not_ready", "credited_leads": None, "lead_conversions": None}
            item["sales"] = {
                "state": "not_ready" if finance else "permission_unavailable",
                "ledger": ledger_state if finance else None,
                "items": None,
            }
            result.append(item)
            continue
        values = _total_values(credit, recipient_counts, version_id, label)
        item["leads"] = {
            "state": "available",
            "credited_leads": share(values.leads[0]),
            "lead_conversions": int(values.leads[1]),
        }
        if not finance:
            item["sales"] = {"state": "permission_unavailable", "ledger": None, "items": None}
            result.append(item)
            continue
        booked = {
            (entry.currency, entry.exponent): entry.net_minor
            for entry in ledger
            if entry.period == label
        }
        keys = sorted(set(values.sales) | set(booked))
        sales = []
        for code, exponent in keys:
            entry = values.sales.get((code, exponent), [0, Fraction(0), 0, 0])
            net = booked.get((code, exponent))
            sales.append(
                {
                    "currency": code,
                    "exponent": exponent,
                    "credited_sales": share(entry[1]),
                    "credited_revenue": amount(int(entry[0]), exponent),
                    "sale_conversions": int(entry[2]),
                    "associated": int(entry[2] - entry[3]),
                    "unassociated": int(entry[3]),
                    "ledger_net": None
                    if ledger_state != "available"
                    else amount(int(net or 0), exponent),
                }
            )
        item["sales"] = {"state": "available", "ledger": ledger_state, "items": sales}
        result.append(item)
    return result


def _comparison(
    context: AttributionContext,
    version_id: UUID | None,
    credit: Sequence[CreditRow],
    recipient_counts: Sequence[CountRow],
    visits: VisitInputs,
    finance: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now_views, then_views = (
        visits.totals.get("current", (0, 0)),
        visits.totals.get("previous", (0, 0)),
    )
    for index, metric in enumerate(("page_views", "link_page_views")):
        rows.append(
            {
                "metric": metric,
                "currency": None,
                "exponent": None,
                "current_value": now_views[index],
                "previous_value": then_views[index],
                **compare_values(now_views[index], then_views[index], None),
            }
        )
    if version_id is None or not context.ready():
        return rows
    blocked = context.blocked()
    current = _total_values(credit, recipient_counts, version_id, "current")
    previous = _total_values(credit, recipient_counts, version_id, "previous")
    rows.append(
        {
            "metric": "credited_leads",
            "currency": None,
            "exponent": None,
            "current_value": share(current.leads[0]),
            "previous_value": share(previous.leads[0]),
            **compare_fractions(current.leads[0], previous.leads[0], blocked),
        }
    )
    if finance:
        for code, exponent in sorted(set(current.sales) | set(previous.sales)):
            mine = current.sales.get((code, exponent), [0, Fraction(0), 0, 0])
            theirs = previous.sales.get((code, exponent), [0, Fraction(0), 0, 0])
            money = compare_values(int(mine[0]), int(theirs[0]), blocked)
            if money["difference"] is not None:
                money["difference"] = amount(money["difference"], exponent)
            rows.append(
                {
                    "metric": "credited_revenue",
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
                    "currency": code,
                    "exponent": exponent,
                    "current_value": share(mine[1]),
                    "previous_value": share(theirs[1]),
                    **compare_fractions(mine[1], theirs[1], blocked),
                }
            )
    return rows


@dataclass
class FunnelReport:
    body: dict[str, Any]
    total_rows: int
    rows: Callable[[], Iterator[dict[str, Any]]]


def funnel_keys(
    credit: Sequence[CreditRow],
    counts: Sequence[CountRow],
    visits: VisitInputs,
    version_id: UUID | None,
    group_by: str,
    ready: bool,
) -> tuple[dict[GroupKey, Values], list[GroupKey]]:
    found = groups(credit, counts, version_id, "current", group_by) if ready else {}
    keys = {key for key, item in found.items() if item.nonzero}
    keys |= {("campaign", ref) for (label, ref) in visits.groups if label == "current"}
    if len(keys) > MAX_GROUPS:
        raise ReportError("report_too_large", 422)
    return found, sorted(keys, key=order)


def funnel_report(
    context: AttributionContext,
    group_by: str,
    labels: Sequence[str],
    credit: Sequence[CreditRow],
    counts: Sequence[CountRow],
    recipient_counts: Sequence[CountRow],
    visits: VisitInputs,
    ledger_state: str,
    ledger: Sequence[LedgerTotal],
    meta: GroupMeta,
    finance: bool,
) -> FunnelReport:
    if group_by not in GROUP_BYS:
        raise ReportError("validation_failed", 422)
    check_currencies([*credit, *counts, *recipient_counts, *ledger])
    version_id = None if context.version is None else UUID(str(context.version["id"]))
    ready = version_id is not None and context.ready()
    found, keys = funnel_keys(credit, counts, visits, version_id, group_by, ready)
    body = {
        "group_by": group_by,
        "bases": dict(BASES),
        "model_version": None if context.version is None else dict(context.version),
        "attribution": context.block(),
        "finance": "available" if finance else "permission_unavailable",
        "values": {
            "state": "available" if ready else "not_ready",
            "reason": None if ready else NOT_READY,
        },
        "totals": _totals(
            context,
            version_id,
            labels,
            credit,
            recipient_counts,
            visits,
            ledger_state,
            ledger,
            finance,
        ),
        "comparison": _comparison(context, version_id, credit, recipient_counts, visits, finance)
        if "previous" in labels
        else None,
    }

    def rows() -> Iterator[dict[str, Any]]:
        for key in keys:
            values = found.get(key, Values())
            yield {
                **meta_cells(key, group_by, meta),
                "visits": _visits(key, visits),
                "leads": leads_block(values) if ready else None,
                "sales": sales_block(values, finance) if ready else None,
            }

    return FunnelReport(body, len(keys), rows)
