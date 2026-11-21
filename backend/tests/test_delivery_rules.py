"""Pure parts of 014-B conversion delivery (specification 014-B, D-064 decisions D6, D8, D9).

The fbc match key, the deadline, the refusal order at enqueue, the error classes and retry
delays, the delivery capability, and the synthetic receiver's validation, deduplication and
test events. No database and no network.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.attribution import SaleState
from app.connectors.contracts import ErrorKind, ProviderError
from app.connectors.synthetic_meta_capi import CAPABILITY, SyntheticMetaCapiProvider
from app.ledger import Currency, LedgerScope
from app.services.delivery import (
    MAX_VALUE_MINOR,
    ClickIdentifier,
    SaleCandidate,
    SyntheticJourney,
    _classify,
    deadline_of,
    fbc,
    match_key,
    refusal,
)

SALE = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
SCOPE = LedgerScope(UUID(int=1), UUID(int=2), "acct")
REF = "a" * 64
REDIRECT = "http://127.0.0.1:8000/connectors/oauth/callback"


def _click(offset_hours: float, fbclid: str = "IwAR0Click_-1") -> ClickIdentifier:
    return ClickIdentifier(fbclid, SALE - timedelta(hours=offset_hours), uuid4())


def _candidate(*, classes=("confirmed_capture",), net=1000, source="system_generated", clicks=None):
    journey = SyntheticJourney(
        "person", (REF,), tuple(clicks if clicks is not None else [_click(2)]), source
    )
    sale = SaleState(SCOPE, "sale-1", Currency("USD", 2), SALE, net)
    return SaleCandidate(SCOPE, "sale-1", sale, frozenset(classes), journey)


def test_fbc_uses_the_first_receipt_in_milliseconds_and_keeps_case():
    click = ClickIdentifier(
        "IwAR0AbC_dEf-9", datetime(2026, 11, 20, 8, 30, 15, 123456, tzinfo=UTC), uuid4()
    )
    assert fbc(click) == "fb.1.1795163415123.IwAR0AbC_dEf-9"
    assert match_key([_click(5), _click(1), _click(-1)], SALE).received_at == SALE - timedelta(
        hours=1
    )
    assert match_key([_click(-1)], SALE) is None


def test_deadline_is_the_age_limit_less_one_hour():
    assert deadline_of(SALE) == SALE + timedelta(days=6, hours=23)


@pytest.mark.parametrize(
    ("candidate", "now", "reason"),
    [
        (_candidate(classes=("purchase_signal",)), SALE, "not_verified"),
        (_candidate(classes=("confirmed_capture", "manual_declaration")), SALE, "not_verified"),
        (_candidate(classes=()), SALE, "not_verified"),
        (_candidate(net=0), SALE, "sale_reversed"),
        (_candidate(), SALE + timedelta(days=6, hours=23), "too_old"),
        (_candidate(net=MAX_VALUE_MINOR), SALE, "value_out_of_range"),
        (_candidate(source="app"), SALE, "unsupported_action_source"),
        (_candidate(clicks=[]), SALE, "no_match_key"),
        (_candidate(clicks=[_click(-0.5)]), SALE, "no_match_key"),
        (_candidate(source="website"), SALE, "provider_field_missing"),
        (_candidate(classes=("confirmed_settlement",)), SALE, None),
        (_candidate(source="physical_store"), SALE + timedelta(days=6), None),
    ],
)
def test_refusal_order(candidate, now, reason):
    assert refusal(candidate, now) == reason


def test_journey_and_click_validation():
    with pytest.raises(ValueError):
        ClickIdentifier("has space", SALE, uuid4())
    with pytest.raises(ValueError):
        ClickIdentifier("ok", SALE.replace(tzinfo=None), uuid4())
    with pytest.raises(ValueError):
        SyntheticJourney("person", ("raw-token",), ())
    click = _click(1)
    assert "IwAR" not in repr(click) and REF not in repr(_candidate().journey)


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (ProviderError(ErrorKind.UNAUTHORIZED, "graph_190"), ("unauthorized", "invalid_token")),
        (ProviderError(ErrorKind.FORBIDDEN, "graph_200"), ("configuration", "permission_missing")),
        (ProviderError(ErrorKind.RATE_LIMITED, "graph_4", 60), ("rate_limited", "rate_limited")),
        (ProviderError(ErrorKind.RETRYABLE, "http_500"), ("retryable", "retryable")),
        (
            ProviderError(ErrorKind.PERMANENT, "dataset_unavailable"),
            ("configuration", "dataset_unavailable"),
        ),
        (ProviderError(ErrorKind.PERMANENT, "graph_100"), ("payload", "invalid_parameter")),
        (ProviderError(ErrorKind.PERMANENT, "event_too_old"), ("payload", "invalid_parameter")),
    ],
)
def test_error_classes(error, outcome):
    assert _classify(error) == outcome


def test_delivery_capability_has_no_streams():
    assert CAPABILITY.delivery and CAPABILITY.named_account == "dataset"
    assert CAPABILITY.stream_specs() == () and CAPABILITY.primary_stream == ""
    assert CAPABILITY.scopes == ("ads_read",) and CAPABILITY.require_all_scopes


def _receiver(tmp_path, scopes=("ads_read",)):
    receiver = SyntheticMetaCapiProvider(tmp_path / "capi.sqlite3")
    receiver.define_dataset("880001")
    url = receiver.authorization_url(
        state="s", code_challenge=None, redirect_uri=REDIRECT, scopes=()
    )
    code = receiver.approve(url, ("880001",), scopes=scopes)
    token = receiver.exchange(code=code, code_verifier=None, redirect_uri=REDIRECT).access_token
    receiver.set_behavior("clock", SALE.isoformat())
    return receiver, token


def _event(**changes):
    event = {
        "event_name": "Purchase",
        "event_time": int((SALE - timedelta(hours=1)).timestamp()),
        "event_id": "e" * 64,
        "action_source": "system_generated",
        "user_data": {"fbc": "fb.1.1795163415123.IwAR0"},
        "custom_data": {"value": 12.5, "currency": "USD"},
    }
    event.update(changes)
    return event


@pytest.mark.parametrize(
    "event",
    [
        _event(action_source="website"),
        _event(action_source="website", event_source_url="https://shop.example.test/"),
        _event(custom_data={"currency": "USD"}),
        _event(custom_data={"value": 1, "currency": "usd"}),
        _event(user_data={}),
        _event(action_source="television"),
        _event(event_time="soon"),
    ],
)
def test_receiver_refuses_invalid_events(tmp_path, event):
    receiver, token = _receiver(tmp_path)
    with pytest.raises(ProviderError) as raised:
        receiver.send_event(token, dataset="880001", event=event, test_event_code=None)
    assert (raised.value.kind, raised.value.provider_code) == (ErrorKind.PERMANENT, "graph_100")


def test_receiver_age_limit_permission_and_dataset(tmp_path):
    receiver, token = _receiver(tmp_path)
    old = _event(event_time=int((SALE - timedelta(days=7, seconds=1)).timestamp()))
    with pytest.raises(ProviderError) as raised:
        receiver.send_event(token, dataset="880001", event=old, test_event_code=None)
    assert raised.value.provider_code == "event_too_old"
    with pytest.raises(ProviderError) as raised:
        receiver.send_event(token, dataset="880002", event=_event(), test_event_code=None)
    assert raised.value.kind is ErrorKind.FORBIDDEN
    (tmp_path / "unscoped").mkdir()
    unscoped, other = _receiver(tmp_path / "unscoped", scopes=())
    with pytest.raises(ProviderError) as raised:
        unscoped.send_event(other, dataset="880001", event=_event(), test_event_code=None)
    assert raised.value.kind is ErrorKind.FORBIDDEN
    receiver.remove_integration(token)
    with pytest.raises(ProviderError) as raised:
        receiver.send_event(token, dataset="880001", event=_event(), test_event_code=None)
    assert raised.value.kind is ErrorKind.UNAUTHORIZED


def test_receiver_deduplicates_within_48_hours_and_keeps_test_events_apart(tmp_path):
    receiver, token = _receiver(tmp_path)
    for _ in range(2):
        answer = receiver.send_event(token, dataset="880001", event=_event(), test_event_code=None)
        assert answer.events_received == 1 and answer.trace_id.startswith("SYN")
    receiver.send_event(token, dataset="880001", event=_event(), test_event_code="TEST1")
    assert len(receiver.received("880001")) == 2
    assert receiver.counted("880001") == [("Purchase", "e" * 64)]
    assert [item["test_event_code"] for item in receiver.received("880001", test=True)] == ["TEST1"]
    receiver.set_behavior("clock", (SALE + timedelta(hours=49)).isoformat())
    fresh = _event(event_time=int((SALE + timedelta(hours=48)).timestamp()))
    receiver.send_event(token, dataset="880001", event=fresh, test_event_code=None)
    assert len(receiver.counted("880001")) == 2


def test_receiver_failure_script(tmp_path):
    receiver, token = _receiver(tmp_path)
    receiver.set_behavior("retry_after", "120")
    receiver.set_behavior(
        "send_script",
        "server_error,throttled,invalid_token,permission,invalid_parameter,unknown_dataset,"
        "expired,wrong_count",
    )
    expected = [
        (ErrorKind.RETRYABLE, "http_500"),
        (ErrorKind.RATE_LIMITED, "graph_4"),
        (ErrorKind.UNAUTHORIZED, "graph_190"),
        (ErrorKind.FORBIDDEN, "graph_200"),
        (ErrorKind.PERMANENT, "graph_100"),
        (ErrorKind.PERMANENT, "dataset_unavailable"),
        (ErrorKind.PERMANENT, "event_too_old"),
    ]
    for kind, code in expected:
        with pytest.raises(ProviderError) as raised:
            receiver.send_event(token, dataset="880001", event=_event(), test_event_code=None)
        assert (raised.value.kind, raised.value.provider_code) == (kind, code)
        if kind is ErrorKind.RATE_LIMITED:
            assert raised.value.retry_after == 120
    answer = receiver.send_event(token, dataset="880001", event=_event(), test_event_code=None)
    assert answer.events_received == 0 and receiver.received("880001") == []
    assert (
        receiver.send_event(
            token, dataset="880001", event=_event(), test_event_code=None
        ).events_received
        == 1
    )
