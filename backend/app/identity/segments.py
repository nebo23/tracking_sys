"""Identity-consent periods, segment intervals and event classes (design section 4.4, R006-27).

Pure functions over plain values; the services load rows under the client privacy lock and
pass them here, so the same rules decide assignment for reads, erasure classification, the
change feed and lifecycle expiry.

- A grant period of identity_link is the uninterrupted interval in which the latest record of
  the purpose grants it: a grant received before the previous grant expired extends the
  period; a denial, withdrawal or an expiry ends it (J1, current_state semantics: a grant whose
  expires_at <= now is expired).
- An owned segment covers (start, end): start is the adopted provisional prefix start
  (R006-27) or otherwise the assertion receipt; end is the exclusive closure, or the end of
  the grant period in which it was asserted, whichever comes first. Both bounds are strict, so
  an event received at a boundary timestamp is unassigned.
- An event is assigned to owner X only when its receipt time lies in an owned segment of X and
  its client-claimed occurred_at lies in an owned segment of the same original owner on the
  same subject (the two-time rule). An event carrying the R006-24 exclusion marker is never
  assigned to anyone.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

EventClass = Literal["confirmed", "excluded", "unresolved"]


@dataclass(frozen=True)
class ConsentMark:
    received_at: datetime
    granted: bool
    expires_at: datetime | None


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime | None  # exclusive; None while the grant is current

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment and (self.end is None or moment < self.end)


@dataclass(frozen=True)
class Segment:
    status: Literal["active", "ambiguous", "neutral"]
    owner: UUID | None  # the original owner of an owned segment
    candidates: frozenset[UUID]
    start: datetime  # effective start (provisional prefix or assertion receipt)
    end: datetime | None  # effective exclusive end; None while open

    def covers(self, moment: datetime) -> bool:
        return self.start < moment and (self.end is None or moment < self.end)


@dataclass(frozen=True)
class EventTimes:
    received_at: datetime
    occurred_at: datetime
    excluded: bool = False


def grant_periods(marks: Iterable[ConsentMark], now: datetime) -> list[Period]:
    """The uninterrupted identity_link grant periods, in receipt order."""
    periods: list[Period] = []
    start: datetime | None = None
    expiry: datetime | None = None
    for mark in sorted(marks, key=lambda item: item.received_at):
        if start is not None and expiry is not None and expiry <= mark.received_at:
            periods.append(Period(start, expiry))
            start = None
        if mark.granted:
            if start is None:
                start = mark.received_at
            expiry = mark.expires_at
        elif start is not None:
            periods.append(Period(start, mark.received_at))
            start = None
    if start is not None:
        if expiry is not None and expiry <= now:
            periods.append(Period(start, expiry))
        else:
            periods.append(Period(start, None))
    return periods


def current_period(periods: Sequence[Period], now: datetime) -> Period | None:
    if periods and periods[-1].end is None and periods[-1].start <= now:
        return periods[-1]
    return None


def period_end(periods: Sequence[Period], asserted_at: datetime) -> datetime | None:
    """The end of the grant period that contains asserted_at (None while it is current)."""
    for period in periods:
        if period.contains(asserted_at):
            return period.end
    return asserted_at


def effective_end(
    eligible_until: datetime | None, periods: Sequence[Period], asserted_at: datetime
) -> datetime | None:
    ended = period_end(periods, asserted_at)
    if eligible_until is None:
        return ended
    if ended is None:
        return eligible_until
    return min(eligible_until, ended)


def owner_of(event: EventTimes, segments: Sequence[Segment]) -> UUID | None:
    """The original owner the two-time rule assigns the event to, or None."""
    if event.excluded:
        return None
    owners = {
        segment.owner
        for segment in segments
        if segment.status == "active" and segment.covers(event.received_at)
    }
    if len(owners) != 1:
        return None
    (owner,) = owners
    if any(
        segment.status == "active" and segment.owner == owner and segment.covers(event.occurred_at)
        for segment in segments
    ):
        return owner
    return None


def classify(event: EventTimes, segments: Sequence[Segment], person: UUID) -> EventClass:
    """The class of one event for one original person (design section 4.4)."""
    owner = owner_of(event, segments)
    if owner == person:
        return "confirmed"
    if owner is not None:
        return "excluded"
    for segment in segments:
        if segment.status == "active":
            continue
        if not (segment.covers(event.received_at) and segment.covers(event.occurred_at)):
            continue
        if segment.status == "neutral" or person not in segment.candidates:
            return "excluded"
    return "unresolved"
