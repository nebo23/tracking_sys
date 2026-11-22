"""Booking events, booking state and CRM stage changes without a database (specification 015-D).

D-068 decisions E2 to E6. The Cal.com bodies follow the documented webhook structure; every value
is synthetic. derive_state must give the same booking for every delivery order (T-52).
"""

import itertools
from datetime import UTC, datetime

import pytest
from integration_senders import FORBIDDEN, booking_event, calcom, deal_event

from app.integrations.bookings import (
    Event,
    Invalid,
    Unsupported,
    derive_state,
    parse_calcom,
    parse_contract,
)
from app.integrations.deals import parse_deal

TOKEN = "sbj_" + "S" * 43


def test_calcom_events_keep_only_booking_fields():
    # T-54: names, emails, phones, answers, notes and meeting links never leave the parser.
    event = parse_calcom(calcom("BOOKING_CREATED", "uid-1", subject_token=TOKEN))
    assert (event.kind, event.ref, event.previous_ref, event.event_type_ref) == (
        "created",
        "uid-1",
        None,
        "501",
    )
    assert event.occurred_at == datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    assert event.start_at == datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    assert event.subject_token == TOKEN
    assert not any(value in repr(event) for value in FORBIDDEN)
    moved = parse_calcom(calcom("BOOKING_RESCHEDULED", "uid-2", previous="uid-1"))
    assert (moved.kind, moved.previous_ref) == ("rescheduled", "uid-1")
    ended = parse_calcom(calcom("MEETING_ENDED", "uid-2"))
    assert ended.kind == "completed"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"triggerEvent": "BOOKING_PAID", "payload": {"uid": "x"}}, Unsupported),
        ({"triggerEvent": "BOOKING_NO_SHOW_UPDATED", "payload": {}}, Unsupported),
        ({"triggerEvent": "BOOKING_CREATED"}, Invalid),
        ({"triggerEvent": "BOOKING_CREATED", "createdAt": "now", "payload": {"uid": "x"}}, Invalid),
        (
            {
                "triggerEvent": "BOOKING_RESCHEDULED",
                "createdAt": "2026-11-10T09:00:00Z",
                "payload": {"uid": "x"},
            },
            Invalid,
        ),  # a reschedule without the previous ID
        (
            {
                "triggerEvent": "BOOKING_CREATED",
                "createdAt": "2026-11-10T09:00:00Z",
                "payload": {"uid": "bad uid with spaces"},
            },
            Invalid,
        ),
    ],
)
def test_calcom_refusals(body, error):
    with pytest.raises(error):
        parse_calcom(body)


def test_invalid_subject_tokens_are_dropped():
    assert (
        parse_calcom(calcom("BOOKING_CREATED", "uid-3", subject_token="short")).subject_token
        is None
    )
    assert (
        parse_contract(booking_event("created", "b-1", subject_token=TOKEN)).subject_token == TOKEN
    )


def _events():
    return [
        parse_calcom(calcom("BOOKING_CREATED", "a", created_at="2026-11-10T09:00:00Z")),
        parse_calcom(
            calcom(
                "BOOKING_RESCHEDULED",
                "b",
                previous="a",
                created_at="2026-11-10T10:00:00Z",
                start="2026-11-13T10:00:00Z",
            )
        ),
        # Cal.com may also cancel the old ID of a reschedule; it never cancels the booking.
        parse_calcom(calcom("BOOKING_CANCELLED", "a", created_at="2026-11-10T10:00:01Z")),
        parse_calcom(
            calcom(
                "BOOKING_CANCELLED",
                "b",
                created_at="2026-11-10T11:00:00Z",
                start="2026-11-13T10:00:00Z",
            )
        ),
    ]


def test_state_is_the_same_for_every_order():
    # T-51, T-52: one booking, rescheduled once, then cancelled, whatever the delivery order.
    expected = derive_state(_events())
    assert (expected.status, expected.current_ref, expected.reschedule_count) == (
        "cancelled",
        "b",
        1,
    )
    assert expected.start_at == datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
    for order in itertools.permutations(_events()):
        assert derive_state(order) == expected


def test_cancelling_a_superseded_id_keeps_the_booking():
    events = _events()[:3]
    assert derive_state(events).status == "scheduled"
    for order in itertools.permutations(events):
        assert derive_state(order).status == "scheduled"


def test_reschedule_before_creation_and_chains():
    moment = datetime(2026, 11, 10, tzinfo=UTC)
    chain = [
        Event("rescheduled", "c", "b", None, moment.replace(hour=12), None, None),
        Event("rescheduled", "b", "a", None, moment.replace(hour=11), None, None),
        Event("created", "a", None, None, moment.replace(hour=10), None, None),
    ]
    state = derive_state(chain)
    assert (state.current_ref, state.reschedule_count, state.status) == ("c", 2, "scheduled")
    assert derive_state(chain[:1]).current_ref == "c"


def test_deal_stage_changes():
    change = parse_deal(
        deal_event("D-1", "won", amount="1500.00", currency="EGP", payment_reference="700000001")
    )
    assert (change.deal_ref, change.pipeline, change.stage) == ("D-1", "sales", "won")
    assert change.amount.minor == 150_000 and change.payment_reference == "700000001"
    with pytest.raises(Unsupported):
        parse_deal({"type": "deal.created", "deal": {}})
    for bad in (
        deal_event("D-2", "won", amount="15.001", currency="EGP"),
        deal_event("D-3", "won", amount="15.00", currency="XYZ"),
        deal_event("D-4", "buyer@example.test"),
        deal_event("D-5", "won", payment_reference="+20 100 000 0742"),
        deal_event("D-6", "won", occurred_at="2026-11-10T09:00:00"),
        {"type": "deal.stage_changed", "occurred_at": "2026-11-10T09:00:00Z"},
    ):
        with pytest.raises(Invalid):
            parse_deal(bad)
