"""Typed, bounded CSV of the 016-B reports (specification 016-B, D-089 decision D10).

The attribution, ROAS and funnel reports share the fixed long-form schema COLUMNS_016B and the
typed cell writers, row and byte bounds of the 016-A export (csv_export). A CSV file holds the
same complete result as the JSON report under the same revision, without pagination. Every
reference that can come from a URL (campaign, content and link references, ad and content IDs)
is an identifier cell with the "id:" prefix, so no cell can start a spreadsheet formula. No
name, label, title, person ID, touchpoint ID or event ID has a column.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from app.reporting.csv_export import COLUMNS_016B, CsvBuilder, _dependencies, _period_cells


def _builder(body: Mapping[str, Any], level: str | None) -> CsvBuilder:
    common = {
        "view": body.get("view"),
        "day_zone": body["day_zone"],
        "basis": body["basis"],
        "level": level,
    }
    return CsvBuilder(body["family"], common, COLUMNS_016B)


def _version(item: Mapping[str, Any]) -> dict[str, object]:
    return {
        "model_version_id": str(item["id"]),
        "model_version": item["version_key"],
        "model": item["model"],
        "model_status": item["status"],
    }


def _metadata(builder: CsvBuilder, body: Mapping[str, Any]) -> None:
    builder.add("metadata", metric="contract_version", detail=body["contract_version"])
    for label in ("current", "previous"):
        if label == "current" or body.get("comparison_period") is not None:
            builder.add("metadata", metric="report_period", **_period_cells(body, label))
    builder.add("metadata", metric="revision", object_id=body["revision"])
    builder.add("metadata", metric="generated_at", timestamp=body["generated_at"])
    builder.add("metadata", metric="client_id", object_id=body["client_id"])
    if body.get("connection_id") is not None:
        builder.add("metadata", metric="connection_id", connection_id=body["connection_id"])
    builder.add(
        "metadata",
        metric="compare",
        detail="previous" if body.get("comparison_period") else "none",
    )
    builder.add("metadata", metric="finance", detail=body["finance"])
    values = body["values"]
    builder.add("metadata", metric="values", status=values["state"], reason=values["reason"])
    versions = (
        [body["model_version"]]
        if body.get("model_version") is not None
        else list(body.get("model_versions") or ())
    )
    for item in versions:
        builder.add(
            "metadata",
            metric="model_version",
            **_version(item),
            detail="default" if item["is_default"] else "not_default",
        )


def _freshness(builder: CsvBuilder, block: Mapping[str, Any]) -> None:
    builder.add(
        "status",
        source="attribution",
        metric="state",
        status=block["state"],
        reason=block["reason"],
        detail=block["unit"],
    )
    builder.add(
        "status",
        source="attribution",
        metric="published_generation",
        count=block["published_generation"],
        timestamp=block["published_at"],
    )
    if block["failure_code"] is not None:
        builder.add(
            "status", source="attribution", metric="failure_code", reason=block["failure_code"]
        )
    builder.add("status", source="current", metric="ledger", status=block["current"]["ledger"])
    for name in ("ledger_generation", "receipt_ordinal", "identity_seq"):
        builder.add("status", source="consumer", metric=name, count=block["consumer"][name])
        builder.add("status", source="current", metric=name, count=block["current"][name])


def money(value: Mapping[str, Any] | None) -> dict[str, object]:
    if value is None:
        return {}
    return {"value": value["decimal"], "value_minor": value["minor"]}


def ratio(value: Mapping[str, Any] | None) -> dict[str, object]:
    if value is None:
        return {}
    return {
        "value": value["decimal"],
        "numerator": value["numerator"],
        "denominator": value["denominator"],
    }


def _number(value: Any) -> object:
    if isinstance(value, Mapping):
        return value["decimal"]
    return value


def _difference(value: Any) -> dict[str, object]:
    if isinstance(value, Mapping):
        return money(value) if "minor" in value else ratio(value)
    return {} if value is None else {"value": value}


def comparison(builder: CsvBuilder, items: Iterable[Mapping[str, Any]], source: str) -> None:
    for item in items:
        builder.add(
            "comparison",
            source=item.get("kind") or source,
            metric=item["metric"],
            currency=item.get("currency"),
            exponent=item.get("exponent"),
            current_value=_number(item["current_value"]),
            previous_value=_number(item["previous_value"]),
            **_difference(item["difference"]),
            percent_change=item["percent_change"],
            comparable=item["comparable"],
            reason=item["reason"],
        )


def _totals(
    builder: CsvBuilder,
    body: Mapping[str, Any],
    totals: Mapping[str, Any],
    version: Mapping[str, object],
) -> None:
    sales, leads = totals["sales"], totals["leads"]
    if sales["items"] is None:
        builder.add(
            "total",
            **version,
            source="sales",
            metric="sales",
            status=sales["state"],
            reason=sales["reason"],
        )
    for item in sales["items"] or ():
        cells = {
            **_period_cells(body, item["period"]),
            **version,
            "source": "sales",
            "recipient": item["recipient"],
            "currency": item["currency"],
            "exponent": item["exponent"],
        }
        builder.add(
            "total",
            **cells,
            metric="credited_revenue",
            unit="money",
            **money(item["credited_revenue"]),
        )
        builder.add(
            "total", **cells, metric="credited_sales", unit="share", **ratio(item["credited_sales"])
        )
        builder.add(
            "total", **cells, metric="sale_conversions", unit="count", count=item["conversions"]
        )
    if leads["items"] is None:
        builder.add(
            "total",
            **version,
            source="leads",
            metric="leads",
            status=leads["state"],
            reason=leads["reason"],
        )
    for item in leads["items"] or ():
        cells = {
            **_period_cells(body, item["period"]),
            **version,
            "source": "leads",
            "recipient": item["recipient"],
        }
        builder.add(
            "total", **cells, metric="credited_leads", unit="share", **ratio(item["credited_leads"])
        )
        builder.add(
            "total", **cells, metric="lead_conversions", unit="count", count=item["conversions"]
        )


def reconciliation(
    builder: CsvBuilder,
    body: Mapping[str, Any],
    block: Mapping[str, Any],
    version: Mapping[str, object],
) -> None:
    builder.add(
        "status",
        **version,
        source="reconciliation",
        metric="reconciliation",
        status=block["state"],
        reason=block["reason"],
        detail=block["ledger"],
    )
    for item in block["items"] or ():
        cells = {
            **_period_cells(body, item["period"]),
            **version,
            "source": "reconciliation",
            "currency": item["currency"],
            "exponent": item["exponent"],
            "unit": "money",
            "status": item["state"],
            "reason": item["reason"],
        }
        for metric in ("credited_revenue", "ledger_net", "difference"):
            builder.add("total", **cells, metric=metric, **money(item[metric]))


def credit_values(
    builder: CsvBuilder,
    cells: Mapping[str, object],
    sales: Mapping[str, Any] | None,
    leads: Mapping[str, Any] | None,
) -> None:
    if sales is not None:
        if sales["items"] is None:
            builder.add("value", **cells, metric="sales", status=sales["state"])
        for item in sales["items"] or ():
            money_cells = {**cells, "currency": item["currency"], "exponent": item["exponent"]}
            builder.add(
                "value",
                **money_cells,
                metric="credited_revenue",
                unit="money",
                **money(item["credited_revenue"]),
            )
            builder.add(
                "value",
                **money_cells,
                metric="credited_sales",
                unit="share",
                **ratio(item["credited_sales"]),
            )
            builder.add(
                "value",
                **money_cells,
                metric="sale_conversions",
                unit="count",
                count=item["conversions"],
            )
    if leads is not None:
        builder.add(
            "value",
            **cells,
            metric="credited_leads",
            unit="share",
            **ratio(leads["credited_leads"]),
        )
        builder.add(
            "value", **cells, metric="lead_conversions", unit="count", count=leads["conversions"]
        )


def group_cells(body: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, object]:
    return {
        **_period_cells(body, "current"),
        "recipient": row["recipient"],
        "group_ref": row["group_ref"],
        "registered": row["registered"],
    }


def attribution_csv(
    body: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], total_rows: int
) -> bytes:
    builder = _builder(body, body["group_by"])
    _metadata(builder, body)
    _freshness(builder, body["attribution"])
    _dependencies(builder, body["dependencies"])
    if body["totals"] is not None:
        _totals(builder, body, body["totals"], {})
        reconciliation(builder, body, body["reconciliation"], {})
    for item in body.get("model_totals") or ():
        _totals(builder, body, item, {"model_version_id": item["model_version_id"]})
    for item in body.get("model_reconciliation") or ():
        reconciliation(builder, body, item, {"model_version_id": item["model_version_id"]})
    comparison(builder, body.get("comparison") or (), "attribution")
    builder.reserve(total_rows)
    for row in rows:
        cells = group_cells(body, row)
        if row["models"] is None:
            credit_values(builder, cells, row["sales"], row["leads"])
        else:
            for entry in row["models"]:
                credit_values(
                    builder,
                    {**cells, "model_version_id": entry["model_version_id"]},
                    entry["sales"],
                    entry["leads"],
                )
        for item in row["content_items"] or ():
            builder.add(
                "value",
                **cells,
                metric="content_item",
                connection_id=item["connection_id"],
                object_id=item["content_id"],
                source=item["provider"],
                detail=item["stream"],
            )
    return builder.encode()


def _date(value: Any) -> str | None:
    return None if value is None else str(value)


def _spend_source(builder: CsvBuilder, body: Mapping[str, Any]) -> None:
    source = body["spend_source"]
    builder.add("status", source="spend", metric="provider", detail=source["provider"])
    builder.add("status", source="spend", metric="adapter_state", status=source["adapter_state"])
    builder.add(
        "status", source="spend", metric="connection_status", status=source["connection_status"]
    )
    account = source.get("account") or {}
    if account:
        builder.add(
            "status", source="spend", metric="account_currency", currency=account["currency"]
        )
    stream = source["stream"]
    builder.add(
        "status",
        source=stream["stream"],
        metric="coverage",
        detail=_date(stream["covered_from"]),
        reason=None,
        availability=None,
    )
    builder.add(
        "status",
        source=stream["stream"],
        metric="complete_through",
        detail=_date(stream["complete_through"]),
    )
    freshness = stream["freshness"]
    builder.add(
        "status",
        source=stream["stream"],
        metric="freshness",
        status=freshness["state"],
        timestamp=freshness["last_stream_success_at"],
    )
    sync = stream["sync"]
    builder.add(
        "status",
        source=stream["stream"],
        metric="sync",
        status=sync["state"],
        reason=sync["reason"],
        detail="in_progress" if sync["in_progress"] else "idle",
    )
    for period in source["periods"]:
        cells = _period_cells(body, period["period"])
        builder.add(
            "status",
            **cells,
            source=stream["stream"],
            metric="period",
            status=period["status"],
            reason=period["reason"],
            detail=period["coverage"],
            count=period["facts"],
        )
        for reason, number in period["refused"].items():
            builder.add(
                "status",
                **cells,
                source=stream["stream"],
                metric="refused",
                reason=reason,
                count=number,
            )


def roas_values(
    builder: CsvBuilder, row_type: str, cells: Mapping[str, object], item: Mapping[str, Any]
) -> None:
    values = {
        **cells,
        "level": item["level"],
        "object_id": item["object_id"],
        "campaign_id": item["campaign_id"],
        "adset_id": item["adset_id"],
        "currency": item["currency"],
        "exponent": item["exponent"],
        "availability": item["spend_state"],
    }
    builder.add(row_type, **values, metric="spend", unit="money", **money(item["spend"]))
    builder.add(
        row_type,
        **values,
        metric="credited_revenue",
        unit="money",
        **money(item["credited_revenue"]),
    )
    builder.add(
        row_type,
        **values,
        metric="roas",
        unit="ratio",
        **ratio(item["roas"]),
        reason=item["roas_reason"],
    )
    builder.add(
        row_type, **values, metric="credited_leads", unit="share", **ratio(item["credited_leads"])
    )
    builder.add(
        row_type,
        **values,
        metric="cost_per_lead",
        unit="money_per_lead",
        **ratio(item["cost_per_lead"]),
        reason=item["cost_per_lead_reason"],
    )


def roas_csv(body: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], total_rows: int) -> bytes:
    builder = _builder(body, body["level"])
    _metadata(builder, body)
    _freshness(builder, body["attribution"])
    _spend_source(builder, body)
    _dependencies(builder, body["dependencies"])
    for item in body["totals"]:
        roas_values(builder, "total", _period_cells(body, item["period"]), item)
    for item in body.get("unmatched") or ():
        builder.add(
            "total",
            **_period_cells(body, item["period"]),
            source="unmatched",
            metric="credited_revenue",
            unit="money",
            currency=item["currency"],
            exponent=item["exponent"],
            **money(item["credited_revenue"]),
        )
    for item in body.get("unmatched_leads") or ():
        builder.add(
            "total",
            **_period_cells(body, item["period"]),
            source="unmatched",
            metric="credited_leads",
            unit="share",
            **ratio(item["credited_leads"]),
        )
    comparison(builder, body.get("comparison") or (), "account")
    builder.reserve(total_rows * 5)
    for row in rows:
        roas_values(builder, "value", _period_cells(body, "current"), row)
    return builder.encode()


SERIALIZERS = {"attribution": attribution_csv, "roas": roas_csv}
