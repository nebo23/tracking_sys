"""Typed, bounded CSV serialization of a report result (specification 016-A, D-072 D8 to D10).

A CSV file holds the same complete filtered result as the JSON report under the same revision,
without pagination, in one fixed long-form schema (COLUMNS). Every record has a row type:
metadata, status, total, comparison or value. Each column has one cell type, and every cell is
checked before it is written:

- token: a closed code (states, reasons, metric names, streams), starting with a letter or digit
  and limited to letters, digits and _ . : | / + -;
- date and timestamp: canonical ISO dates and UTC instants generated from date objects;
- zone: a name from the IANA time zone database;
- identifier: an approved opaque identifier written as "id:" followed by the identifier, so no
  identifier cell can start with a spreadsheet formula character, whatever it contains;
- integer, number and amount: generated from validated numbers (integers, finite floats, or
  canonical decimal text of an exact amount); a signed negative amount stays a number.

Names, titles, captions, URLs, reasons entered by people, actors, payloads and personal
identifiers have no column. An unexpected type is refused instead of being converted with str().
The standard library writer quotes every cell and ends records with CRLF. The file is built in
memory and refused whole when it would exceed MAX_ROWS records after the header or MAX_BYTES
encoded bytes including the header; no partial file is produced. This protects the file as
generated; it makes no claim about a file after arbitrary spreadsheet edits.
"""

import csv
import math
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.reporting.common import ReportError
from app.reporting.periods import valid_zone

MAX_ROWS = 5_000
MAX_BYTES = 2 * 1024 * 1024
FILENAMES = {
    "social": "report-social.csv",
    "spend": "report-spend.csv",
    "revenue": "report-revenue.csv",
}
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:|/+-]{0,127}")
DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

ROW_TYPES = frozenset({"metadata", "status", "total", "comparison", "value"})
COLUMNS: tuple[tuple[str, str], ...] = (
    ("row_type", "token"),
    ("family", "token"),
    ("period", "token"),
    ("period_start", "date"),
    ("period_end", "date"),
    ("day_zone", "zone"),
    ("basis", "token"),
    ("source", "token"),
    ("metric", "token"),
    ("unit", "token"),
    ("metric_class", "token"),
    ("currency", "token"),
    ("exponent", "integer"),
    ("date", "date"),
    ("definition_since", "date"),
    ("object_id", "identifier"),
    ("product_type", "token"),
    ("published_at", "timestamp"),
    ("fetched_at", "timestamp"),
    ("timestamp", "timestamp"),
    ("value", "number"),
    ("value_minor", "integer"),
    ("current_value", "number"),
    ("previous_value", "number"),
    ("percent_change", "number"),
    ("comparable", "boolean"),
    ("availability", "token"),
    ("status", "token"),
    ("previous_status", "token"),
    ("reason", "token"),
    ("provisional", "boolean"),
    ("expected_count", "integer"),
    ("available_count", "integer"),
    ("missing_count", "integer"),
    ("unsupported_count", "integer"),
    ("not_synced_count", "integer"),
    ("detail", "token"),
)
NAMES = tuple(name for name, _ in COLUMNS)
KINDS = dict(COLUMNS)


class ExportRefused(TypeError):
    """A cell of an unexpected type or form; the export is refused, never coerced."""


def _token(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ExportRefused("token")
    return value


def _date(value: object) -> str:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ExportRefused("date")
    text = value.isoformat()
    if not DATE_TEXT.fullmatch(text):
        raise ExportRefused("date")
    return text


def _timestamp(value: object) -> str:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ExportRefused("timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _zone(value: object) -> str:
    if not isinstance(value, str) or not valid_zone(value) or not value[:1].isalpha():
        raise ExportRefused("zone")
    return value


def _identifier(value: object) -> str:
    if isinstance(value, UUID):
        return f"id:{value}"
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ExportRefused("identifier")
    return f"id:{value}"


def _integer(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExportRefused("integer")
    return str(value)


def _number(value: object) -> str:
    if isinstance(value, bool):
        raise ExportRefused("number")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExportRefused("number")
        text = repr(value)
        if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?(?:e[+-][0-9]+)?", text):
            raise ExportRefused("number")
        return text
    if isinstance(value, str) and DECIMAL.fullmatch(value):
        return value
    raise ExportRefused("number")


def _boolean(value: object) -> str:
    if not isinstance(value, bool):
        raise ExportRefused("boolean")
    return "true" if value else "false"


WRITERS = {
    "token": _token,
    "date": _date,
    "timestamp": _timestamp,
    "zone": _zone,
    "identifier": _identifier,
    "integer": _integer,
    "number": _number,
    "boolean": _boolean,
}


def cell(column: str, value: object) -> str:
    if value is None:
        return ""
    kind = KINDS.get(column)
    if kind is None:
        raise ExportRefused("column")
    return WRITERS[kind](value)


def record(values: Mapping[str, object]) -> list[str]:
    unknown = set(values) - set(NAMES)
    if unknown:
        raise ExportRefused("column")
    if values.get("row_type") not in ROW_TYPES:
        raise ExportRefused("row_type")
    return [cell(name, values.get(name)) for name in NAMES]


class _Sink:
    """A write target for csv.writer that counts encoded bytes and stops at the bound."""

    def __init__(self, limit: int) -> None:
        self.limit, self.size, self.chunks = limit, 0, []

    def write(self, text: str) -> int:
        data = text.encode("utf-8")
        self.size += len(data)
        if self.size > self.limit:
            raise ReportError("export_too_large", 422)
        self.chunks.append(data)
        return len(text)


class CsvBuilder:
    """Collects records, then encodes them once within the row and byte bounds."""

    def __init__(self, family: str, common: Mapping[str, object]) -> None:
        self.family = family
        self.common = dict(common)
        self.records: list[list[str]] = []

    def add(self, row_type: str, **values: object) -> None:
        if len(self.records) >= MAX_ROWS:
            raise ReportError("export_too_large", 422)
        self.records.append(
            record({"row_type": row_type, "family": self.family, **self.common, **values})
        )

    def reserve(self, more: int) -> None:
        if len(self.records) + more > MAX_ROWS:
            raise ReportError("export_too_large", 422)

    def encode(self) -> bytes:
        if len(self.records) > MAX_ROWS:
            raise ReportError("export_too_large", 422)
        sink = _Sink(MAX_BYTES)
        writer = csv.writer(sink, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(NAMES)
        writer.writerows(self.records)
        return b"".join(sink.chunks)


# --- report mappers ---------------------------------------------------------------------------


def _period_cells(body: Mapping[str, Any], label: str) -> dict[str, object]:
    key = "period" if label == "current" else "comparison_period"
    period = body.get(key) or {}
    return {"period": label, "period_start": period.get("start"), "period_end": period.get("end")}


def _metadata(builder: CsvBuilder, body: Mapping[str, Any], extra: Iterable[tuple]) -> None:
    builder.add("metadata", metric="contract_version", detail=body["contract_version"])
    builder.add("metadata", metric="revision", object_id=body["revision"])
    builder.add("metadata", metric="generated_at", timestamp=body["generated_at"])
    builder.add("metadata", metric="client_id", object_id=body["client_id"])
    if body.get("connection_id") is not None:
        builder.add("metadata", metric="connection_id", object_id=body["connection_id"])
    builder.add(
        "metadata",
        metric="compare",
        detail="previous" if body.get("comparison_period") else "none",
    )
    for key, column, value in extra:
        if value is not None:
            builder.add("metadata", metric=key, **{column: value})


def _dependencies(builder: CsvBuilder, dependencies: Iterable[Mapping[str, Any]]) -> None:
    for item in dependencies:
        builder.add(
            "status",
            source="dependencies",
            metric=item["capability"],
            status=item["state"],
            detail="|".join(item["requires"]),
        )


def _amount_cells(value: Mapping[str, Any] | None) -> dict[str, object]:
    if value is None:
        return {}
    return {"value": value["decimal"], "value_minor": value["minor"]}


def social_csv(
    body: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], total_rows: int
) -> bytes:
    common = {"day_zone": body["day_zone"], "basis": body["basis"]}
    builder = CsvBuilder("social", common)
    source = body["source_status"]
    _metadata(
        builder,
        body,
        (
            ("catalog_version", "detail", body["catalog_version"]),
            ("view", "detail", body["view"]),
            ("provider", "detail", source["provider"]),
            ("adapter_state", "detail", source["adapter_state"]),
            ("adapter_version", "detail", source["adapter_version"]),
            ("connection_status", "detail", source["connection_status"]),
            (
                "connection_last_successful_sync_at",
                "timestamp",
                source["connection_last_successful_sync_at"],
            ),
            ("source_rows", "value", source["source_rows"]),
            ("publication_unknown", "value", source.get("publication_unknown")),
        ),
    )
    for item in source["excluded_metrics"]:
        builder.add(
            "status",
            source=item["stream"],
            metric=item["metric"],
            availability="unsupported",
            reason=item["reason"],
        )
    for stream in source["streams"]:
        name = stream["stream"]
        coverage = stream["coverage"]
        for label in ("current", "previous"):
            if label in coverage:
                builder.add(
                    "status",
                    **_period_cells(body, label),
                    source=name,
                    metric="coverage",
                    status=coverage[label],
                )
        builder.add(
            "status", source=name, metric="covered_from", timestamp=coverage["covered_from"]
        )
        builder.add(
            "status", source=name, metric="complete_through", timestamp=coverage["complete_through"]
        )
        freshness = stream["freshness"]
        builder.add(
            "status",
            source=name,
            metric="freshness",
            status=freshness["state"],
            value=freshness["freshness_hours"],
            unit="hours",
            timestamp=freshness["last_stream_success_at"],
        )
        builder.add(
            "status", source=name, metric="fetched_from", timestamp=freshness["fetched_from"]
        )
        builder.add(
            "status", source=name, metric="fetched_through", timestamp=freshness["fetched_through"]
        )
        sync = stream["sync"]
        builder.add(
            "status",
            source=name,
            metric="sync",
            status=sync["state"],
            reason=sync["reason"],
            detail="in_progress" if sync["in_progress"] else "idle",
        )
        builder.add(
            "status",
            source=name,
            metric="provisional_delay_hours",
            value=stream["provisional_delay_hours"],
            unit="hours",
        )
    _dependencies(builder, body["dependencies"])
    for total in body["totals"]:
        builder.add(
            "total",
            **_period_cells(body, total["period"]),
            source=total["stream"],
            metric=total["metric"],
            unit=total["unit"],
            metric_class=total["metric_class"],
            value=total["value"],
            status=total["status"],
            reason=total["reason"],
            provisional=total["provisional"],
            definition_since=total["definition_since"],
            expected_count=total.get("expected_days", total.get("contents")),
            available_count=total.get("available_days", total.get("available_contents")),
            missing_count=total.get("missing_days", total.get("missing_contents")),
            unsupported_count=total.get("unsupported_days", total.get("unsupported_contents")),
            not_synced_count=total.get("not_synced_days"),
            fetched_at=total.get("fetched_through"),
        )
    for item in body.get("comparison") or ():
        builder.add(
            "comparison",
            source=item["stream"],
            metric=item["metric"],
            unit=item["unit"],
            current_value=item["current_value"],
            previous_value=item["previous_value"],
            value=item["difference"],
            percent_change=item["percent_change"],
            comparable=item["comparable"],
            reason=item["reason"],
            status=item["current_status"],
            previous_status=item["previous_status"],
        )
    builder.reserve(total_rows)
    for row in rows:
        builder.add(
            "value",
            **_period_cells(body, "current"),
            source=row["stream"],
            metric=row["metric"],
            unit=row["unit"],
            metric_class=row["metric_class"],
            date=row.get("date", row.get("published_date")),
            object_id=row.get("content_id"),
            product_type=row.get("product_type"),
            published_at=row.get("published_at"),
            fetched_at=row.get("fetched_at"),
            value=row["value"],
            availability=row["availability"],
            reason=row["reason"],
            provisional=row["provisional"],
            definition_since=row["definition_since"],
        )
    return builder.encode()


def spend_csv(body: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], total_rows: int) -> bytes:
    common = {"day_zone": body["day_zone"], "basis": body["basis"]}
    builder = CsvBuilder("spend", common)
    source = body["source_status"]
    account = source.get("account") or {}
    _metadata(
        builder,
        body,
        (
            ("level", "detail", body["level"]),
            ("provider", "detail", source["provider"]),
            ("adapter_state", "detail", source["adapter_state"]),
            ("adapter_version", "detail", source["adapter_version"]),
            ("connection_status", "detail", source["connection_status"]),
            (
                "connection_last_successful_sync_at",
                "timestamp",
                source["connection_last_successful_sync_at"],
            ),
            ("account_currency", "currency", account.get("currency")),
            ("account_previous_currency", "currency", account.get("previous_currency")),
            ("account_currency_changed_at", "timestamp", account.get("currency_changed_at")),
            ("account_previous_time_zone", "detail", account.get("previous_time_zone")),
            ("account_time_zone_changed_at", "timestamp", account.get("time_zone_changed_at")),
            ("source_rows", "value", source["source_rows"]),
        ),
    )
    stream = source["stream"]
    builder.add(
        "status", source=stream["stream"], metric="covered_from", date=stream["covered_from"]
    )
    builder.add(
        "status",
        source=stream["stream"],
        metric="complete_through",
        date=stream["complete_through"],
    )
    freshness = stream["freshness"]
    builder.add(
        "status",
        source=stream["stream"],
        metric="freshness",
        status=freshness["state"],
        value=freshness["freshness_hours"],
        unit="hours",
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
            source="ad_daily",
            metric="period",
            status=period["status"],
            reason=period["reason"],
            detail=period["coverage"],
            expected_count=period["facts"],
            available_count=period["valued_facts"],
        )
        for reason, count in period["refused"].items():
            builder.add(
                "status", **cells, source="ad_daily", metric="refused", reason=reason, value=count
            )
        for day in period["provisional_dates"]:
            builder.add(
                "status",
                **cells,
                source="ad_daily",
                metric="provisional_date",
                date=day,
                provisional=True,
            )
        for zone in period["fact_zones"]:
            builder.add("status", **cells, source="ad_daily", metric="fact_zone", detail=zone)
    _dependencies(builder, body["dependencies"])
    for total in body["totals"]:
        cells = {
            **_period_cells(body, total["period"]),
            "currency": total["currency"],
            "exponent": total["exponent"],
            "status": total["status"],
            "reason": total["reason"],
            "provisional": total["provisional"],
            "available_count": total["days_with_spend"],
        }
        builder.add("total", **cells, metric="spend", unit="money", **_amount_cells(total["spend"]))
        builder.add(
            "total", **cells, metric="impressions", unit="count", value=total["impressions"]
        )
        builder.add("total", **cells, metric="clicks", unit="count", value=total["clicks"])
    for item in body.get("comparison") or ():
        money = item["metric"] == "spend"
        builder.add(
            "comparison",
            currency=item["currency"],
            exponent=item["exponent"],
            metric=item["metric"],
            unit="money" if money else "count",
            current_value=item["current_value"]["decimal"]
            if money and item["current_value"] is not None
            else item["current_value"],
            previous_value=item["previous_value"]["decimal"]
            if money and item["previous_value"] is not None
            else item["previous_value"],
            **(_amount_cells(item["difference"]) if money else {"value": item["difference"]}),
            percent_change=item["percent_change"],
            comparable=item["comparable"],
            reason=item["reason"],
        )
    builder.reserve(total_rows * 3)
    for row in rows:
        cells = {
            **_period_cells(body, "current"),
            "source": f"level:{body['level']}",
            "object_id": row["object_id"],
            "currency": row["currency"],
            "exponent": row["exponent"],
            "provisional": row["provisional"],
            "available_count": row["days_with_spend"],
        }
        builder.add("value", **cells, metric="spend", unit="money", **_amount_cells(row["spend"]))
        builder.add("value", **cells, metric="impressions", unit="count", value=row["impressions"])
        builder.add("value", **cells, metric="clicks", unit="count", value=row["clicks"])
    return builder.encode()


def revenue_csv(
    body: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], total_rows: int
) -> bytes:
    common = {"day_zone": body["day_zone"], "basis": body["basis"]}
    builder = CsvBuilder("revenue", common)
    unresolved = body["unresolved"]
    _metadata(
        builder,
        body,
        (
            ("external_completeness", "detail", unresolved["external_completeness"]),
            ("evidence_rows", "value", unresolved["evidence_rows"]),
            ("evidence_limit", "value", unresolved["evidence_limit"]),
        ),
    )
    scope = unresolved["scope"]
    builder.add(
        "status", source="unresolved", metric="pending", value=unresolved["pending"], detail=scope
    )
    for reason, count in unresolved["pending_reasons"].items():
        builder.add(
            "status",
            source="unresolved",
            metric="pending",
            reason=reason,
            value=count,
            detail=scope,
        )
    builder.add(
        "status", source="unresolved", metric="held", value=unresolved["held"], detail=scope
    )
    builder.add(
        "status",
        source="unresolved",
        metric="reconciliation",
        value=unresolved["reconciliation"],
        detail=scope,
    )
    for reason, count in unresolved["reconciliation_reasons"].items():
        builder.add(
            "status",
            source="unresolved",
            metric="reconciliation",
            reason=reason,
            value=count,
            detail=scope,
        )
    _dependencies(builder, body["dependencies"])
    for total in body["totals"]:
        cells = {
            **_period_cells(body, total["period"]),
            "source": total["block"],
            "currency": total["currency"],
            "exponent": total["exponent"],
            "unit": "money",
            "status": "complete",
            "available_count": total.get("postings", total.get("items")),
        }
        metrics = (
            ("captured", "refunded", "charged_back", "reversed", "corrected", "net")
            if total["block"] == "verified"
            else ("sales", "refunds")
        )
        for metric in metrics:
            builder.add("total", **cells, metric=metric, **_amount_cells(total[metric]))
    for item in body.get("comparison") or ():
        builder.add(
            "comparison",
            source=item["block"],
            currency=item["currency"],
            exponent=item["exponent"],
            metric=item["metric"],
            unit="money",
            current_value=item["current_value"]["decimal"],
            previous_value=item["previous_value"]["decimal"],
            **_amount_cells(item["difference"]),
            percent_change=item["percent_change"],
            comparable=item["comparable"],
            reason=item["reason"],
        )
    builder.reserve(total_rows)
    for row in rows:
        builder.add(
            "value",
            **_period_cells(body, "current"),
            source=row["block"],
            currency=row["currency"],
            exponent=row["exponent"],
            date=row["date"],
            metric=row["kind"],
            unit="money",
            available_count=row["postings"],
            **_amount_cells(row["amount"]),
        )
    return builder.encode()


SERIALIZERS = {"social": social_csv, "spend": spend_csv, "revenue": revenue_csv}


def report_csv(
    body: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], total_rows: int
) -> bytes:
    try:
        return SERIALIZERS[body["family"]](body, rows, total_rows)
    except ExportRefused as error:
        raise ReportError("export_refused", 500) from error
