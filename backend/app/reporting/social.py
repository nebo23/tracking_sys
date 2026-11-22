"""Social reports over stored Instagram and YouTube facts (specification 016-A, D-072 D3 to D6).

Two views of one connection:

- daily: the daily stream (Instagram account insights by UTC day, YouTube channel_daily by
  Pacific day). Every reportable metric has one row per requested date: the stored value, or an
  explicit state when there is none. A date with no record inside the stream's proven coverage
  is missing (no_record); outside it, not_synced. Additive counts total within the period; a
  total with absent dates is a labeled partial subtotal, and a total without any value is null.
  Unique-audience metrics and averages never total.
- content_cohort: content published on the requested native dates (Instagram media and stories
  by their publication time, YouTube videos by the published_at attribute of the videos stream)
  with the latest stored lifetime values (basis published_cohort_lifetime). The values are what
  the content earned up to its fetch time, not during the period, so a cohort is never compared
  with a previous period. Cohort totals sum lifetime counts only.

Availability (available, missing, unsupported, not_synced), coverage, freshness and provisional
status stay independent. A value is provisional while it is inside its stream's data delay or
before its own provisional end. Freshness is the stream's own latest successful synchronization
against the family's freshness window; the connection-level success time is reported only
under that label. A definition change inside a period makes its total unavailable
(definition_changed), and inside the two compared periods it blocks the comparison.
"""

import math
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.reporting.catalog import (
    CATALOG_VERSION,
    Entry,
    Family,
    excluded_entries,
    view_entries,
)
from app.reporting.common import ReportError, compare_values
from app.reporting.periods import Period, load_zone, local_date, local_midnight

VIEWS = ("daily", "content_cohort")
MAX_METRICS = 25
DAY = timedelta(days=1)


@dataclass(frozen=True)
class SocialRecord:
    stream: str
    object_id: str
    observed_at: datetime | None
    fetched_at: datetime | None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    unavailable: Mapping[str, str] = field(default_factory=dict)
    product_type: str | None = None
    provisional_until: datetime | None = None
    published_at: datetime | None = None  # content views only
    present: bool = True  # False for a cohort video without a stored totals record


@dataclass(frozen=True)
class StreamState:
    stream: str
    covered_from: datetime | None = None
    complete_through: datetime | None = None
    in_progress: bool = False  # the checkpoint holds a cursor: a run is between pages
    last_success_at: datetime | None = None  # the stream's latest successful run
    sync: Mapping[str, Any] = field(default_factory=lambda: {"state": "idle", "reason": None})


@dataclass(frozen=True)
class SocialInputs:
    family: Family
    connection_id: UUID
    provider: str
    status: str
    generation: int
    adapter_available: bool
    adapter_version: str | None
    connection_last_success: datetime | None
    streams: Mapping[str, StreamState]
    records: Sequence[SocialRecord]
    source_rows: int
    digest: str
    publication_unknown: int = 0


@dataclass(frozen=True)
class Cell:
    value: int | float | None
    availability: str
    reason: str | None
    provisional: bool
    record: SocialRecord | None


@dataclass
class SocialResult:
    view: str
    day_zone: str
    basis: str
    totals: list[dict[str, Any]]
    comparison: list[dict[str, Any]] | None
    source_status: dict[str, Any]
    total_rows: int
    rows: Any  # a callable returning an iterator of rows in order
    semantic: dict[str, Any]


# The selected metrics of a view: all reportable ones, or the requested names, each of which
# must be a reportable metric of the view's streams.
def select_entries(family: Family, view: str, metrics: Sequence[str] | None) -> tuple[Entry, ...]:
    if view not in VIEWS:
        raise ReportError("invalid_view", 422)
    entries = view_entries(family, "daily" if view == "daily" else "content")
    if metrics is None:
        return entries
    names = list(metrics)
    if not names or len(names) > MAX_METRICS or len(set(names)) != len(names):
        raise ReportError("unsupported_metric", 422)
    known = {item.metric for item in entries}
    if any(name not in known for name in names):
        raise ReportError("unsupported_metric", 422)
    wanted = set(names)
    return tuple(item for item in entries if item.metric in wanted)


def _number(value: object, entry: Entry) -> int | float | None:
    if isinstance(value, bool):
        return None
    if entry.summable:
        return value if isinstance(value, int) and value >= 0 else None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and math.isfinite(value) and value >= 0:
        return value
    return None


def _provisional(record: SocialRecord, delay_hours: int, now: datetime) -> bool:
    if record.provisional_until is not None and now < record.provisional_until:
        return True
    return (
        bool(delay_hours)
        and record.observed_at is not None
        and (now - record.observed_at < timedelta(hours=delay_hours))
    )


def _value_cell(record: SocialRecord, entry: Entry, delay: int, now: datetime) -> Cell:
    provisional = record.present and _provisional(record, delay, now)
    if not record.present:
        return Cell(None, "missing", "no_record", False, record)
    if not entry.offered(record.product_type):
        reason = "product_type_unknown" if record.product_type is None else "product_type"
        return Cell(None, "unsupported", reason, False, record)
    raw = record.metrics.get(entry.metric)
    if raw is None:
        reason = record.unavailable.get(entry.metric) or "not_returned"
        return Cell(None, "missing", reason, provisional, record)
    value = _number(raw, entry)
    if value is None:
        return Cell(None, "missing", "invalid_value", provisional, record)
    return Cell(value, "available", None, provisional, record)


def _freshness(state: StreamState | None, hours: int, now: datetime) -> str:
    if state is None or state.last_success_at is None:
        return "never_synced"
    return "stale" if now - state.last_success_at > timedelta(hours=hours) else "fresh"


def _dominant(cells: Sequence[Cell]) -> str:
    states = {cell.availability for cell in cells}
    if states == {"not_synced"}:
        return "not_synced"
    if states == {"unsupported"}:
        return "unsupported"
    return "missing"


# --- daily view ---------------------------------------------------------------------------


class _Daily:
    def __init__(self, inputs: SocialInputs, entries: Sequence[Entry], now: datetime) -> None:
        self.inputs, self.entries, self.now = inputs, entries, now
        self.family = inputs.family
        self.zone = self.family.day_zone
        self.local = load_zone(self.zone)
        self.stream = self.family.daily_stream
        self.state = inputs.streams.get(self.stream)
        self.delay = self.family.delay_hours(self.stream)
        self.by_date: dict[date, list[SocialRecord]] = defaultdict(list)
        for record in inputs.records:
            if record.stream == self.stream and record.observed_at is not None:
                self.by_date[local_date(record.observed_at, self.zone)].append(record)

    def covered(self, day: date) -> bool:
        state = self.state
        if state is None or state.covered_from is None or state.complete_through is None:
            return False
        start = local_midnight(day, self.local)
        end = local_midnight(day + DAY, self.local)
        return state.covered_from <= start and end <= state.complete_through

    def cell(self, day: date, entry: Entry) -> Cell:
        records = self.by_date.get(day, [])
        if len(records) > 1:
            return Cell(None, "missing", "conflicting_records", False, None)
        if records:
            return _value_cell(records[0], entry, self.delay, self.now)
        if self.covered(day):
            return Cell(None, "missing", "no_record", False, None)
        return Cell(None, "not_synced", "outside_coverage", False, None)

    def coverage_state(self, period: Period) -> str:
        if self.state is None or self.state.complete_through is None:
            return "not_synced"
        covered = sum(1 for day in period.dates() if self.covered(day))
        if covered == period.days:
            return "complete"
        return "partial" if covered else "not_synced"

    def total(self, entry: Entry, period: Period, label: str) -> dict[str, Any]:
        cells = [self.cell(day, entry) for day in period.dates()]
        available = [cell for cell in cells if cell.availability == "available"]
        counts = {
            "expected_days": len(cells),
            "available_days": len(available),
            "missing_days": sum(1 for cell in cells if cell.availability == "missing"),
            "unsupported_days": sum(1 for cell in cells if cell.availability == "unsupported"),
            "not_synced_days": sum(1 for cell in cells if cell.availability == "not_synced"),
        }
        changed = entry.changes_within(period)
        value: int | None = None
        if changed:
            status, reason = "unavailable", "definition_changed"
        elif not entry.summable:
            status, reason = "unavailable", "non_additive"
        elif not available:
            status, reason = "unavailable", _dominant(cells)
        else:
            value = sum(int(cell.value) for cell in available)  # type: ignore[arg-type]
            complete = len(available) == len(cells)
            status, reason = ("complete", None) if complete else ("partial", "incomplete_days")
        return {
            "period": label,
            "stream": entry.stream,
            "metric": entry.metric,
            "unit": entry.unit,
            "metric_class": entry.metric_class.value,
            "value": value,
            "status": status,
            "reason": reason,
            "provisional": any(cell.provisional for cell in available),
            "definition_since": None if changed else entry.definition_since(period.end - DAY),
            **counts,
        }

    def rows(self, period: Period) -> Iterator[dict[str, Any]]:
        for entry in self.entries:
            for day in period.dates():
                cell = self.cell(day, entry)
                record = cell.record
                yield {
                    "stream": entry.stream,
                    "metric": entry.metric,
                    "unit": entry.unit,
                    "metric_class": entry.metric_class.value,
                    "date": day,
                    "value": cell.value,
                    "availability": cell.availability,
                    "reason": cell.reason,
                    "provisional": cell.provisional,
                    "definition_since": entry.definition_since(day),
                    "fetched_at": None if record is None else record.fetched_at,
                }

    def provisional_keys(self, periods: Sequence[Period]) -> list[str]:
        keys = []
        for period in periods:
            for day in period.dates():
                for record in self.by_date.get(day, []):
                    if _provisional(record, self.delay, self.now):
                        keys.append(f"{record.stream}:{record.object_id}")
        return sorted(set(keys))


def _comparison_reason(
    entry: Entry,
    current: dict[str, Any],
    previous: dict[str, Any],
    period: Period,
    before: Period,
    freshness: str,
    in_progress: bool,
) -> str | None:
    if entry.changes_between(before.start, period.end):
        return "definition_changed"
    if not entry.summable:
        return "non_additive"
    if "unavailable" in (current["status"], previous["status"]):
        return "unavailable"
    if "partial" in (current["status"], previous["status"]):
        return "partial"
    if current["provisional"] or previous["provisional"]:
        return "provisional"
    if freshness != "fresh":
        return "stale"
    if in_progress:
        return "sync_in_progress"
    return None


def _stream_status(
    inputs: SocialInputs,
    stream: str,
    now: datetime,
    coverage: dict[str, str],
    records: Sequence[SocialRecord],
) -> dict[str, Any]:
    state = inputs.streams.get(stream)
    fetched = [record.fetched_at for record in records if record.fetched_at is not None]
    return {
        "stream": stream,
        "coverage": {
            "covered_from": None if state is None else state.covered_from,
            "complete_through": None if state is None else state.complete_through,
            **coverage,
        },
        "sync": {
            "state": "idle" if state is None else state.sync.get("state", "idle"),
            "reason": None if state is None else state.sync.get("reason"),
            "in_progress": bool(state and state.in_progress),
        },
        "freshness": {
            "state": _freshness(state, inputs.family.freshness_hours, now),
            "freshness_hours": inputs.family.freshness_hours,
            "last_stream_success_at": None if state is None else state.last_success_at,
            "fetched_from": min(fetched) if fetched else None,
            "fetched_through": max(fetched) if fetched else None,
        },
        "provisional_delay_hours": inputs.family.delay_hours(stream),
    }


def _source_status(inputs: SocialInputs, view: str) -> dict[str, Any]:
    return {
        "provider": inputs.provider,
        "family": inputs.family.name,
        "adapter_state": "available" if inputs.adapter_available else "unavailable",
        "adapter_version": inputs.adapter_version,
        "connection_status": inputs.status,
        "connection_last_successful_sync_at": inputs.connection_last_success,
        "catalog_version": CATALOG_VERSION,
        "excluded_metrics": excluded_entries(
            inputs.family, "daily" if view == "daily" else "content"
        ),
        "source_rows": inputs.source_rows,
    }


def daily_report(
    inputs: SocialInputs,
    entries: Sequence[Entry],
    period: Period,
    previous: Period | None,
    now: datetime,
) -> SocialResult:
    view = _Daily(inputs, entries, now)
    totals = [view.total(entry, period, "current") for entry in entries]
    comparison = None
    previous_totals: list[dict[str, Any]] = []
    freshness = _freshness(view.state, inputs.family.freshness_hours, now)
    in_progress = bool(view.state and view.state.in_progress)
    if previous is not None:
        previous_totals = [view.total(entry, previous, "previous") for entry in entries]
        comparison = []
        for entry, current, before in zip(entries, totals, previous_totals, strict=True):
            reason = _comparison_reason(
                entry, current, before, period, previous, freshness, in_progress
            )
            comparison.append(
                {
                    "stream": entry.stream,
                    "metric": entry.metric,
                    "unit": entry.unit,
                    "current_value": current["value"],
                    "previous_value": before["value"],
                    "current_status": current["status"],
                    "previous_status": before["status"],
                    **compare_values(current["value"], before["value"], reason),
                }
            )
    coverage = {"current": view.coverage_state(period)}
    if previous is not None:
        coverage["previous"] = view.coverage_state(previous)
    in_period = [
        record
        for record in inputs.records
        if record.stream == view.stream
        and record.observed_at is not None
        and (
            period.contains(local_date(record.observed_at, view.zone))
            or (
                previous is not None
                and previous.contains(local_date(record.observed_at, view.zone))
            )
        )
    ]
    source = _source_status(inputs, "daily")
    source["streams"] = [_stream_status(inputs, view.stream, now, coverage, in_period)]
    periods = [period] + ([previous] if previous is not None else [])
    semantic = {
        "provisional": view.provisional_keys(periods),
        "freshness": {view.stream: freshness},
        "sync": {view.stream: dict(view.state.sync) if view.state else None},
    }
    return SocialResult(
        view="daily",
        day_zone=view.zone,
        basis="native_daily_activity",
        totals=totals + previous_totals,
        comparison=comparison,
        source_status=source,
        total_rows=len(entries) * period.days,
        rows=lambda: view.rows(period),
        semantic=semantic,
    )


# --- content cohort view -------------------------------------------------------------------


class _Cohort:
    def __init__(
        self, inputs: SocialInputs, entries: Sequence[Entry], period: Period, now: datetime
    ) -> None:
        self.inputs, self.entries, self.period, self.now = inputs, entries, period, now
        self.family = inputs.family
        self.zone = self.family.day_zone
        start, end = period.bounds(self.zone)
        streams = set(self.family.content_streams)
        self.contents = sorted(
            (
                record
                for record in inputs.records
                if record.stream in streams
                and record.published_at is not None
                and start <= record.published_at < end
            ),
            key=lambda record: (record.stream, record.object_id),
        )
        self.by_stream: dict[str, list[Entry]] = defaultdict(list)
        for entry in entries:
            self.by_stream[entry.stream].append(entry)

    def cell(self, record: SocialRecord, entry: Entry) -> Cell:
        return _value_cell(record, entry, self.family.delay_hours(record.stream), self.now)

    def definition_since(self, record: SocialRecord, entry: Entry) -> date | None:
        if record.observed_at is None:
            return None
        return entry.definition_since(local_date(record.observed_at, self.zone))

    # The state of a complete-listing stream on its own: not_synced before its first complete
    # read, partial while a read is between pages, complete otherwise.
    def listing(self, stream: str) -> str:
        state = self.inputs.streams.get(stream)
        if state is None or state.complete_through is None:
            return "not_synced"
        return "partial" if state.in_progress else "complete"

    # Whether the cohort's content inventory is proven: for Instagram, the stream's coverage
    # holds the whole period; for YouTube, both the videos listing and the totals read are
    # complete and every listed video has a known publication time.
    def inventory(self, stream: str) -> str:
        streams = self.inputs.streams
        if self.family.publication_stream is not None:
            states = [self.listing(self.family.publication_stream), self.listing(stream)]
            if "not_synced" in states:
                return "not_synced"
            if "partial" in states or self.inputs.publication_unknown:
                return "partial"
            return "complete"
        state = streams.get(stream)
        if state is None or state.complete_through is None or state.covered_from is None:
            return "not_synced"
        start, end = self.period.bounds(self.zone)
        complete = state.covered_from <= start and end <= state.complete_through
        return "complete" if complete and not state.in_progress else "partial"

    def total(self, entry: Entry) -> dict[str, Any]:
        records = [record for record in self.contents if record.stream == entry.stream]
        cells = [self.cell(record, entry) for record in records]
        applicable = [cell for cell in cells if cell.availability != "unsupported"]
        available = [cell for cell in cells if cell.availability == "available"]
        definitions = {
            self.definition_since(cell.record, entry) for cell in available if cell.record
        }
        fetched = [
            cell.record.fetched_at
            for cell in available
            if cell.record is not None and cell.record.fetched_at is not None
        ]
        inventory = self.inventory(entry.stream)
        value: int | None = None
        if not entry.summable:
            status, reason = "unavailable", "non_additive"
        elif not records:
            status, reason = "unavailable", "no_content"
        elif len(definitions) > 1:
            status, reason = "unavailable", "definition_changed"
        elif not available:
            status, reason = "unavailable", _dominant(cells)
        else:
            value = sum(int(cell.value) for cell in available)  # type: ignore[arg-type]
            if len(available) < len(applicable):
                status, reason = "partial", "incomplete_contents"
            elif inventory != "complete":
                status, reason = "partial", "inventory_unproven"
            else:
                status, reason = "complete", None
        return {
            "period": "current",
            "stream": entry.stream,
            "metric": entry.metric,
            "unit": entry.unit,
            "metric_class": entry.metric_class.value,
            "value": value,
            "status": status,
            "reason": reason,
            "provisional": any(cell.provisional for cell in available),
            "definition_since": next(iter(definitions)) if len(definitions) == 1 else None,
            "contents": len(records),
            "applicable_contents": len(applicable),
            "available_contents": len(available),
            "missing_contents": sum(1 for cell in cells if cell.availability == "missing"),
            "unsupported_contents": len(cells) - len(applicable),
            "fetched_from": min(fetched) if fetched else None,
            "fetched_through": max(fetched) if fetched else None,
        }

    def row_count(self) -> int:
        return sum(len(self.by_stream.get(record.stream, ())) for record in self.contents)

    def rows(self) -> Iterator[dict[str, Any]]:
        for record in self.contents:
            published = record.published_at
            for entry in self.by_stream.get(record.stream, ()):
                cell = self.cell(record, entry)
                yield {
                    "stream": record.stream,
                    "content_id": record.object_id,
                    "product_type": record.product_type,
                    "published_at": published,
                    "published_date": None
                    if published is None
                    else local_date(published, self.zone),
                    "metric": entry.metric,
                    "unit": entry.unit,
                    "metric_class": entry.metric_class.value,
                    "value": cell.value,
                    "availability": cell.availability,
                    "reason": cell.reason,
                    "provisional": cell.provisional,
                    "definition_since": self.definition_since(record, entry),
                    "observed_at": record.observed_at,
                    "fetched_at": record.fetched_at,
                }

    def provisional_keys(self) -> list[str]:
        return sorted(
            f"{record.stream}:{record.object_id}"
            for record in self.contents
            if record.present
            and _provisional(record, self.family.delay_hours(record.stream), self.now)
        )


def cohort_report(
    inputs: SocialInputs, entries: Sequence[Entry], period: Period, now: datetime
) -> SocialResult:
    view = _Cohort(inputs, entries, period, now)
    streams = sorted(view.family.content_streams)
    source = _source_status(inputs, "content_cohort")
    source["publication_unknown"] = inputs.publication_unknown
    source["streams"] = [
        _stream_status(
            inputs,
            stream,
            now,
            {"current": view.inventory(stream)},
            [record for record in view.contents if record.stream == stream],
        )
        for stream in streams
    ]
    if view.family.publication_stream is not None:
        publication = view.family.publication_stream
        source["streams"].append(
            _stream_status(inputs, publication, now, {"current": view.listing(publication)}, [])
        )
    semantic = {
        "provisional": view.provisional_keys(),
        "freshness": {item["stream"]: item["freshness"]["state"] for item in source["streams"]},
        "sync": {name: dict(state.sync) for name, state in sorted(inputs.streams.items())},
    }
    return SocialResult(
        view="content_cohort",
        day_zone=view.zone,
        basis="published_cohort_lifetime",
        totals=[view.total(entry) for entry in entries],
        comparison=None,
        source_status=source,
        total_rows=view.row_count(),
        rows=view.rows,
        semantic=semantic,
    )


def social_report(
    inputs: SocialInputs,
    view: str,
    period: Period,
    previous: Period | None,
    metrics: Sequence[str] | None,
    now: datetime,
) -> SocialResult:
    entries = select_entries(inputs.family, view, metrics)
    if view == "daily":
        return daily_report(inputs, entries, period, previous, now)
    if previous is not None:
        raise ReportError("comparison_unsupported", 422)
    return cohort_report(inputs, entries, period, now)
