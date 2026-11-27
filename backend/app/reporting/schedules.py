"""Run slots and report periods of schedules (specification 016-C, D-095 decision D8).

A schedule runs at local hour:00 in its IANA time zone: every day (daily), on one ISO weekday
(weekly, 1 is Monday) or on the 1st of the month (monthly). The instant of a run on local date
D is datetime.combine(D, time(hour), zone) with fold=0 in UTC, so an hour that a daylight-saving
change skips runs at the instant of the change, and an hour that occurs twice runs at its first
occurrence. The run date D, not the instant, decides the period, so the rule never depends on
how a skipped hour is mapped:

- daily: D - 1 day to D;
- weekly: D - 7 days to D;
- monthly: the 1st of the previous month to D (28 to 31 days).

Periods are calendar dates (start inclusive, end exclusive); each report then applies its own
source-native days. A missed slot is never repeated: a run reports the latest slot at or before
the current time, and the next run is the first slot after it.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.reporting.common import ReportError
from app.reporting.periods import Period, load_zone

CADENCES = ("daily", "weekly", "monthly")
# The longest gap between two slots is one month; this bounds every search.
SEARCH_DAYS = 40


@dataclass(frozen=True)
class Timing:
    cadence: str
    weekday: int | None
    hour: int
    zone: str

    def __post_init__(self) -> None:
        if self.cadence not in CADENCES or not 0 <= self.hour <= 23:
            raise ReportError("invalid_schedule", 422)
        if (self.cadence == "weekly") != (self.weekday is not None):
            raise ReportError("invalid_schedule", 422)
        if self.weekday is not None and not 1 <= self.weekday <= 7:
            raise ReportError("invalid_schedule", 422)
        try:
            load_zone(self.zone)
        except ReportError as error:
            raise ReportError("invalid_time_zone", 422) from error

    def runs_on(self, day: date) -> bool:
        if self.cadence == "weekly":
            return day.isoweekday() == self.weekday
        if self.cadence == "monthly":
            return day.day == 1
        return True

    # The UTC instant of the run on local date `day`.
    def instant(self, day: date) -> datetime:
        return datetime.combine(day, time(self.hour), load_zone(self.zone)).astimezone(UTC)

    def _local_date(self, moment: datetime) -> date:
        return moment.astimezone(load_zone(self.zone)).date()

    # The first run (its local date and instant) strictly after `moment`.
    def next_after(self, moment: datetime) -> tuple[date, datetime]:
        day = self._local_date(moment) - timedelta(days=1)
        for _ in range(SEARCH_DAYS):
            if self.runs_on(day):
                slot = self.instant(day)
                if slot > moment:
                    return day, slot
            day += timedelta(days=1)
        raise RuntimeError("No run found within the search bound.")  # pragma: no cover

    # The latest run (its local date and instant) at or before `moment`.
    def latest_at(self, moment: datetime) -> tuple[date, datetime]:
        day = self._local_date(moment) + timedelta(days=1)
        for _ in range(SEARCH_DAYS):
            if self.runs_on(day):
                slot = self.instant(day)
                if slot <= moment:
                    return day, slot
            day -= timedelta(days=1)
        raise RuntimeError("No run found within the search bound.")  # pragma: no cover

    # The report period of the run on local date `day`.
    def period(self, day: date) -> Period:
        if self.cadence == "daily":
            return Period(day - timedelta(days=1), day)
        if self.cadence == "weekly":
            return Period(day - timedelta(days=7), day)
        previous = (day.replace(day=1) - timedelta(days=1)).replace(day=1)
        return Period(previous, day)
