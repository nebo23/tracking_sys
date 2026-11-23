"""Specification 006 pure identity rules (D-075): normalizers, segments and matching R1-R5.

Synthetic values only: example.test addresses and fictional digit patterns.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.identity.matching import AssertedKey, decide
from app.identity.normalize import IdentifierRejected, canonical, check_method
from app.identity.segments import (
    ConsentMark,
    EventTimes,
    Segment,
    classify,
    current_period,
    effective_end,
    grant_periods,
    owner_of,
)

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("+20 10 0000 0101", "+201000000101"),
        ("0020 10 0000 0101", "+201000000101"),
        ("  +20 (10) 0000-0101 ", "+201000000101"),
    ],
)
def test_phone_v1_accepts_international_ascii_input(value, expected):
    assert canonical("phone", value).value == expected
    assert canonical("phone", value).normalizer == "phone:v1"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("010 0000 0101", "phone_country_required"),
        ("+20oops10 0000 0101", "identifier_invalid"),
        ("+20 10 0000 0101 ext 9", "identifier_invalid"),
        ("+" + chr(0x0662) + chr(0x0660) + " 10 0000 0101", "identifier_invalid"),
        ("+0020 10 0000 0101", "identifier_invalid"),
        (chr(0xA0) + "+20 10 0000 0101", "identifier_invalid"),
        ("\t+20 10 0000 0101", "identifier_invalid"),
        ("+20 1", "identifier_invalid"),
        ("+1 2345 6789 0123 4567", "identifier_invalid"),
    ],
)
def test_phone_v1_refuses_national_and_malformed_input(value, reason):
    with pytest.raises(IdentifierRejected) as caught:
        canonical("phone", value)
    assert caught.value.reason == reason


def test_email_and_reference_normalizers():
    assert canonical("email", "Mona@Example.Test").value == "mona@example.test"
    assert (
        canonical("email", "mona.example+promo@example.test").value
        != canonical("email", "mona.example@example.test").value
    )
    assert canonical("customer_ref", "cust-1042").value == "cust-1042"
    assert canonical("customer_ref", "Cust-1042").value != "cust-1042"
    for kind, value in (("email", "not-an-address"), ("customer_ref", "bad ref"), ("x", "v")):
        with pytest.raises(IdentifierRejected) as caught:
            canonical(kind, value)
        assert caught.value.reason == "identifier_invalid"


def test_methods_are_closed_per_kind():
    check_method("email", "email_code")
    check_method("customer_ref", "account_login")
    for kind, method in (("phone", "email_code"), ("email", "staff_verified"), ("email", "x")):
        with pytest.raises(IdentifierRejected) as caught:
            check_method(kind, method)
        assert caught.value.reason == "method_invalid"


def test_grant_periods_follow_renewal_expiry_and_withdrawal():
    marks = [
        ConsentMark(at(0), True, at(60)),
        ConsentMark(at(30), True, at(120)),  # renewed before expiry: one period
        ConsentMark(at(200), True, at(300)),  # after the expiry: a new period
        ConsentMark(at(250), False, None),  # withdrawal ends it
        ConsentMark(at(260), True, at(400)),
    ]
    periods = grant_periods(marks, at(270))
    assert [(p.start, p.end) for p in periods] == [
        (at(0), at(120)),
        (at(200), at(250)),
        (at(260), None),
    ]
    assert current_period(periods, at(270)).start == at(260)
    assert grant_periods(marks, at(400))[-1].end == at(400)
    assert current_period(grant_periods(marks, at(400)), at(400)) is None
    assert effective_end(None, periods, at(10)) == at(120)
    assert effective_end(at(50), periods, at(10)) == at(50)
    assert effective_end(None, periods, at(265)) is None


def sara_omar():
    """Design section 4.4: Sara 10:00-10:20 (provisional retracted), Omar from 10:20."""
    sara, omar = uuid4(), uuid4()
    segments = [
        Segment("active", sara, frozenset(), at(60), at(80)),
        Segment("active", omar, frozenset(), at(80), None),
    ]
    return sara, omar, segments


def test_two_time_rule_on_a_shared_device():
    sara, omar, segments = sara_omar()
    p1 = EventTimes(at(55), at(55))  # pre-identification on a shared subject
    p2 = EventTimes(at(65), at(65))
    p3 = EventTimes(at(80), at(80))  # boundary timestamp
    p4 = EventTimes(at(80.5), at(79.8))  # received in Omar's segment, claimed in Sara's
    p5 = EventTimes(at(85), at(85))
    p6 = EventTimes(at(86), at(56))  # claimed in pre-identification time
    assert [owner_of(item, segments) for item in (p1, p2, p3, p4, p5, p6)] == [
        None,
        sara,
        None,
        None,
        omar,
        None,
    ]
    assert classify(p2, segments, sara) == "confirmed"
    assert classify(p5, segments, sara) == "excluded"
    for item in (p1, p3, p4, p6):
        assert classify(item, segments, sara) == "unresolved"


def test_exclusion_marker_and_neutral_or_ambiguous_segments():
    sara, omar, segments = sara_omar()
    ali = uuid4()
    marked = EventTimes(at(65), at(65), excluded=True)
    assert owner_of(marked, segments) is None
    assert classify(marked, segments, sara) == "unresolved"
    later = [
        Segment("active", sara, frozenset(), at(60), at(80)),
        Segment("ambiguous", None, frozenset({omar, ali}), at(80), at(90)),
        Segment("neutral", None, frozenset(), at(90), None),
    ]
    inside = EventTimes(at(85), at(85))
    assert classify(inside, later, sara) == "excluded"
    assert classify(inside, later, omar) == "unresolved"
    assert classify(EventTimes(at(95), at(95)), later, omar) == "excluded"


def owned(index, kind, person, *, root=None, merge=None, owners=None):
    return AssertedKey(
        index,
        kind,
        "owned",
        owner=person,
        root=root or person,
        owners=frozenset(owners or {person}),
        merge_id=merge,
    )


def test_r1_r2_and_co_assertion():
    x = uuid4()
    assert (
        decide([AssertedKey(0, "email", "new")], root_holds_reference={}, edge_of={}).rule == "R1"
    )
    joined = decide(
        [owned(0, "email", x), AssertedKey(1, "customer_ref", "new")],
        root_holds_reference={x: False},
        edge_of={},
    )
    assert (joined.rule, joined.outcome, joined.person) == ("R2", "linked", x)


def test_r2p_phone_is_a_weak_anchor():
    x = uuid4()
    decision = decide(
        [owned(0, "phone", x), AssertedKey(1, "email", "new")],
        root_holds_reference={x: False},
        edge_of={},
    )
    assert (decision.rule, decision.create_new, decision.contest) == ("R2P", True, (0,))
    assert decision.outcome == "contested_identifier"
    another_phone = decide(
        [owned(0, "email", x), AssertedKey(1, "phone", "new")],
        root_holds_reference={x: False},
        edge_of={},
    )
    assert another_phone.rule == "R2"


def test_r3_customer_reference_decides_and_r4_abstains():
    x, y = uuid4(), uuid4()
    r3a = decide(
        [owned(0, "customer_ref", x), owned(1, "email", y)],
        root_holds_reference={x: True, y: False},
        edge_of={},
    )
    assert (r3a.rule, r3a.person, r3a.contest) == ("R3a", x, (1,))
    r3b = decide(
        [AssertedKey(0, "customer_ref", "new"), owned(1, "email", y)],
        root_holds_reference={y: True},
        edge_of={},
    )
    assert (r3b.rule, r3b.create_new, r3b.contest) == ("R3b", True, (1,))
    r4 = decide(
        [owned(0, "email", x), owned(1, "phone", y)],
        root_holds_reference={x: False, y: False},
        edge_of={},
    )
    assert r4.outcome == "ambiguous" and set(r4.candidates) == {x, y}
    undecidable = decide(
        [AssertedKey(0, "customer_ref", "new"), owned(1, "email", x), owned(2, "phone", y)],
        root_holds_reference={x: False, y: False},
        edge_of={},
    )
    assert undecidable.outcome == "ambiguous"


def test_r5_contested_keys_are_excluded():
    x, y = uuid4(), uuid4()
    contested = AssertedKey(0, "email", "contested", candidates=frozenset({x, y}))
    only = decide([contested], root_holds_reference={}, edge_of={})
    assert only.outcome == "ambiguous" and set(only.candidates) == {x, y}
    with_new = decide(
        [contested, AssertedKey(1, "phone", "new")], root_holds_reference={}, edge_of={}
    )
    assert with_new.rule == "R1"
    with_owned = decide([contested, owned(1, "phone", x)], root_holds_reference={}, edge_of={})
    assert (with_owned.rule, with_owned.person) == ("R2", x)


def test_merge_spanning_and_inherited_dependencies():
    s7, s8, edge = uuid4(), uuid4(), uuid4()
    spanning = decide(
        [
            owned(0, "email", s7),
            owned(1, "phone", s8, root=s7),
            AssertedKey(2, "customer_ref", "new"),
        ],
        root_holds_reference={s7: False},
        edge_of={s7: edge},
    )
    assert (spanning.person, spanning.merge_id) == (s7, edge)
    assert spanning.original_owners == {s7, s8}
    inherited = decide(
        [owned(0, "customer_ref", s7, merge=edge, owners={s7, s8})],
        root_holds_reference={s7: True},
        edge_of={s7: edge},
    )
    assert (inherited.person, inherited.merge_id, inherited.original_owners) == (
        s7,
        edge,
        {s7, s8},
    )
    control = decide([owned(0, "email", s7)], root_holds_reference={s7: True}, edge_of={s7: edge})
    assert (control.person, control.merge_id) == (s7, None)
