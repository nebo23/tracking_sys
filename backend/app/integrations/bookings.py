"""Booking events and booking state (specification 015-D, D-068 decisions E2 to E5).

Pure functions only: no database and no network. parse_calcom reads a verified Cal.com webhook
body (sources W-1 to W-4 of the second-round entry review) and parse_contract the bookings of the
provider-neutral signed webhook contract. Both keep only the booking ID, the previous ID of a
reschedule, the event type, the schedule, the occurrence time and an optional pseudonymous
subject token; names, emails, phones, answers, notes and meeting links never leave this module.

derive_state computes a booking chain's state from its minimal events, so every delivery order
of the same events gives the same booking (T-52). The current booking ID is the last ID of the
reschedule chain; only events about the current ID decide the status, so a cancellation of an
ID that was rescheduled away is ignored. A booking is never revenue (E3).
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

CALCOM_TRIGGERS = {
    "BOOKING_CREATED": "created",
    "BOOKING_REQUESTED": "requested",
    "BOOKING_RESCHEDULED": "rescheduled",
    "BOOKING_CANCELLED": "cancelled",
    "BOOKING_REJECTED": "rejected",
    "MEETING_ENDED": "completed",
}
CONTRACT_TYPES = {f"booking.{kind}": kind for kind in set(CALCOM_TRIGGERS.values())}
STATUS = {
    "requested": "requested",
    "created": "scheduled",
    "rescheduled": "scheduled",
    "cancelled": "cancelled",
    "rejected": "rejected",
    "completed": "completed",
}
# Ties at one occurrence time resolve towards the later stage of a booking's life.
RANK = {
    "requested": 0,
    "created": 1,
    "rescheduled": 2,
    "rejected": 3,
    "cancelled": 4,
    "completed": 5,
}
SUBJECT_FIELD = "ts_subject"
SUBJECT_TOKEN = re.compile(r"sbj_[A-Za-z0-9_-]{43}")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}")


class Unsupported(ValueError):
    """A verified delivery whose event is outside the mapped set; it stores nothing."""


class Invalid(ValueError):
    """A verified delivery whose booking fields cannot be read; it stores nothing."""


@dataclass(frozen=True)
class Event:
    kind: str
    ref: str
    previous_ref: str | None
    event_type_ref: str | None
    occurred_at: datetime
    start_at: datetime | None
    end_at: datetime | None
    subject_token: str | None = None  # used once for the link; never stored


@dataclass(frozen=True)
class State:
    status: str
    current_ref: str
    event_type_ref: str | None
    start_at: datetime | None
    end_at: datetime | None
    reschedule_count: int


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(UTC)


def _ref(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        value = str(value)
    return value if isinstance(value, str) and REF.fullmatch(value) else None


def _token(value: Any) -> str | None:
    return value if isinstance(value, str) and SUBJECT_TOKEN.fullmatch(value) else None


def _event(
    kind: str, item: Mapping[str, Any], fields: Mapping[str, str], occurred: Any, token: Any
) -> Event:
    ref = _ref(item.get(fields["ref"]))
    previous = _ref(item.get(fields["previous"])) if kind == "rescheduled" else None
    occurred_at = _time(occurred)
    if ref is None or occurred_at is None or (kind == "rescheduled") != (previous is not None):
        raise Invalid("invalid_booking")
    if previous == ref:
        raise Invalid("invalid_booking")
    start, end = item.get(fields["start"]), item.get(fields["end"])
    start_at = _time(start) if start is not None else None
    end_at = _time(end) if end is not None else None
    if (start is not None and start_at is None) or (end is not None and end_at is None):
        raise Invalid("invalid_booking")
    event_type = item.get(fields["event_type"])
    return Event(
        kind,
        ref,
        previous,
        _ref(event_type) if event_type is not None else None,
        occurred_at,
        start_at,
        end_at,
        _token(token),
    )


CALCOM_FIELDS = {
    "ref": "uid",
    "previous": "rescheduleUid",
    "start": "startTime",
    "end": "endTime",
    "event_type": "eventTypeId",
}
CONTRACT_FIELDS = {
    "ref": "id",
    "previous": "previous_id",
    "start": "start_at",
    "end": "end_at",
    "event_type": "event_type",
}


# A verified Cal.com body. MEETING_ENDED uses a flat payload (W-2); every other trigger nests the
# booking in payload. The subject token comes from the hidden booking field ts_subject (W-4).
def parse_calcom(body: Mapping[str, Any]) -> Event:
    trigger = body.get("triggerEvent")
    if trigger not in CALCOM_TRIGGERS:
        raise Unsupported("unsupported_event")
    kind = CALCOM_TRIGGERS[trigger]
    item = body if kind == "completed" else body.get("payload")
    if not isinstance(item, Mapping):
        raise Invalid("invalid_booking")
    responses = item.get("responses")
    token = None
    if isinstance(responses, Mapping):
        field = responses.get(SUBJECT_FIELD)
        token = field.get("value") if isinstance(field, Mapping) else field
    occurred = body.get("createdAt") or item.get("createdAt")
    return _event(kind, item, CALCOM_FIELDS, occurred, token)


# A booking of the signed webhook contract: {"type": "booking.<kind>", "id", "occurred_at",
# "booking": {"id", "previous_id"?, "event_type"?, "start_at"?, "end_at"?, "subject_token"?}}.
def parse_contract(body: Mapping[str, Any]) -> Event:
    kind = CONTRACT_TYPES.get(body.get("type"))
    item = body.get("booking")
    if kind is None:
        raise Unsupported("unsupported_event")
    if not isinstance(item, Mapping):
        raise Invalid("invalid_booking")
    return _event(kind, item, CONTRACT_FIELDS, body.get("occurred_at"), item.get("subject_token"))


def _order(event: Event) -> tuple:
    return (event.occurred_at, RANK[event.kind], event.ref)


# The state of one chain from all its events, independent of their order (T-52).
def derive_state(events: Iterable[Event]) -> State:
    items = sorted(events, key=_order)
    if not items:
        raise ValueError("A booking has at least one event.")
    successor = {}
    for event in items:
        if event.kind == "rescheduled" and event.previous_ref is not None:
            successor.setdefault(event.previous_ref, event.ref)
    targets = set(successor.values())
    starts = [event.ref for event in items if event.ref not in targets]
    current = starts[0] if starts else items[0].ref
    seen = {current}
    while current in successor and successor[current] not in seen:
        current = successor[current]
        seen.add(current)
    relevant = [event for event in items if event.ref == current]
    latest = relevant[-1] if relevant else items[-1]
    scheduled = [event for event in relevant if event.start_at is not None] or [
        event for event in items if event.start_at is not None
    ]
    timing = scheduled[-1] if scheduled else None
    typed = [event for event in items if event.event_type_ref is not None]
    return State(
        STATUS[latest.kind],
        current,
        typed[-1].event_type_ref if typed else None,
        timing.start_at if timing else None,
        timing.end_at if timing else None,
        len({event.ref for event in items if event.kind == "rescheduled"}),
    )
