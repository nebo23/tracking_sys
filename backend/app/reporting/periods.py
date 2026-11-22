"""Source-native calendar periods (specification 016-A, D-072 decision D4).

A period is a run of calendar dates: start inclusive and end exclusive, at most 31 days. Each
report family uses its source's own day: Instagram UTC, YouTube America/Los_Angeles, advertising
the stored account zone and revenue UTC. A date is never rebucketed into another zone, because
the stored daily aggregates cannot be divided. The UTC bounds of a period come from calendar
arithmetic in the zone (local midnight to local midnight), not from multiples of 86,400 seconds,
so a 23-hour or 25-hour daylight-saving day stays one date.

The previous period ends at start and has the same number of calendar days. Dates are limited
to 2000-01-01 through 2100-01-01 so that the previous period and every bound stay representable.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from app.reporting.common import ReportError

MAX_DAYS = 31
EARLIEST = date(2000, 1, 1)
LATEST = date(2100, 1, 1)
UTC_ZONE = "UTC"


@dataclass(frozen=True, order=True)
class Period:
    start: date
    end: date  # exclusive

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or isinstance(self.start, datetime):
            raise ReportError("invalid_period", 422)
        if not isinstance(self.end, date) or isinstance(self.end, datetime):
            raise ReportError("invalid_period", 422)
        if not EARLIEST <= self.start < self.end <= LATEST:
            raise ReportError("invalid_period", 422)
        if (self.end - self.start).days > MAX_DAYS:
            raise ReportError("invalid_period", 422)

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range(self.days)]

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end

    # The period of equal length that ends where this one starts.
    def previous(self) -> "Period":
        return Period(self.start - timedelta(days=self.days), self.start)

    # The UTC instants of local midnight at start and at end in the zone.
    def bounds(self, zone: str) -> tuple[datetime, datetime]:
        local = load_zone(zone)
        return local_midnight(self.start, local), local_midnight(self.end, local)

    def as_dict(self) -> dict[str, object]:
        return {"start": self.start, "end": self.end, "days": self.days}


def local_midnight(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time(), zone).astimezone(UTC)


# The calendar date of an instant in the zone.
def local_date(instant: datetime, zone: str) -> date:
    return instant.astimezone(load_zone(zone)).date()


# A zone name from the IANA database; anything else is refused rather than guessed.
def load_zone(name: object) -> ZoneInfo:
    if not isinstance(name, str) or not valid_zone(name):
        raise ReportError("invalid_zone", 422)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:  # pragma: no cover - guarded above
        raise ReportError("invalid_zone", 422) from error


_ZONES: frozenset[str] | None = None


def valid_zone(name: str) -> bool:
    global _ZONES
    if _ZONES is None:
        _ZONES = frozenset(available_timezones()) | {UTC_ZONE}
    return name in _ZONES


# The requested period, with the optional previous period for compare=previous.
def requested(start: date, end: date, compare: bool) -> tuple[Period, Period | None]:
    period = Period(start, end)
    return period, (period.previous() if compare else None)
