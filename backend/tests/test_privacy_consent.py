"""ConsentRecord and J1 evaluation contract (specification 003-B, cases C1-C3, C5)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.privacy.consent import (
    ConsentRecord,
    ConsentSource,
    ConsentState,
    Decision,
    Profile,
    Purpose,
    current_state,
    evaluate,
    google_consent_mode,
    require_all,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)
SUBJECT, NOTICE = "a" * 64, "b" * 64
AGENCY, CLIENT = uuid4(), uuid4()


def record(purpose, state, *, at=NOW, source=ConsentSource.TRACKER_BANNER, **values):
    fields = {
        "id": uuid4(),
        "agency_id": AGENCY,
        "client_id": CLIENT,
        "subject_ref": SUBJECT,
        "key_id": "client-key-1",
        "purpose": purpose,
        "state": state,
        "source": source,
        "jurisdiction_profile": Profile.STRICT_OPT_IN,
        "policy_version": "003-B.1",
        "notice_snapshot_hash": NOTICE,
        "received_at": at,
    }
    return ConsentRecord(**{**fields, **values})


@pytest.mark.parametrize("state", list(ConsentState))
def test_j1_allows_non_necessary_purposes_only_when_granted(state):
    for purpose in Purpose:
        decision = evaluate(purpose, state)
        if purpose is Purpose.NECESSARY:
            assert decision == Decision(True, "necessary")
        else:
            assert decision.allowed is (state is ConsentState.GRANTED)
            assert decision.reason == ("granted" if decision.allowed else f"consent_{state}")


def test_c1_unknown_consent_denies_storage_purposes():
    states = {}
    assert require_all([Purpose.ANALYTICS], states) == Decision(False, "consent_unknown")


def test_c2_granted_analytics_with_denied_ads_blocks_only_ad_delivery():
    records = [
        record(Purpose.ANALYTICS, ConsentState.GRANTED),
        record(Purpose.ADS_MEASUREMENT, ConsentState.DENIED),
    ]
    states = {p: current_state(records, p, NOW) for p in Purpose if p is not Purpose.NECESSARY}
    assert require_all([Purpose.ANALYTICS], states).allowed
    assert require_all([Purpose.ADS_MEASUREMENT], states) == Decision(False, "consent_denied")
    mode = google_consent_mode(states)
    assert mode["analytics_storage"] == "granted"
    assert mode["ad_storage"] == mode["ad_user_data"] == mode["ad_personalization"] == "denied"
    assert mode["security_storage"] == "granted"


def test_c3_withdrawal_after_grant_denies_at_the_delivery_check():
    records = [
        record(Purpose.ADS_MEASUREMENT, ConsentState.GRANTED, at=NOW - timedelta(hours=1)),
        record(Purpose.ADS_MEASUREMENT, ConsentState.WITHDRAWN, at=NOW),
    ]
    state = current_state(records, Purpose.ADS_MEASUREMENT, NOW)
    assert require_all([Purpose.ADS_MEASUREMENT], {Purpose.ADS_MEASUREMENT: state}) == Decision(
        False, "consent_withdrawn"
    )


def test_ordering_uses_server_receipt_not_client_capture_time():
    early_server = record(
        Purpose.ANALYTICS, ConsentState.DENIED, at=NOW, captured_at=NOW + timedelta(days=1)
    )
    later_server = record(Purpose.ANALYTICS, ConsentState.GRANTED, at=NOW + timedelta(seconds=1))
    assert current_state([later_server, early_server], Purpose.ANALYTICS, NOW) == (
        ConsentState.GRANTED
    )


def test_expired_grant_is_a_denial():
    records = [record(Purpose.ANALYTICS, ConsentState.GRANTED, expires_at=NOW)]
    assert current_state(records, Purpose.ANALYTICS, NOW) is ConsentState.EXPIRED
    assert evaluate(Purpose.ANALYTICS, ConsentState.EXPIRED) == Decision(False, "consent_expired")


def test_c5_gpc_signal_can_only_deny_sale_sharing_or_advertising():
    gpc = record(Purpose.SALE_OR_SHARE, ConsentState.DENIED, source=ConsentSource.GPC)
    granted = record(Purpose.SALE_OR_SHARE, ConsentState.GRANTED, at=NOW - timedelta(days=1))
    assert current_state([granted, gpc], Purpose.SALE_OR_SHARE, NOW) is ConsentState.DENIED
    with pytest.raises(ValueError):
        record(Purpose.SALE_OR_SHARE, ConsentState.GRANTED, source=ConsentSource.GPC)
    with pytest.raises(ValueError):
        record(Purpose.ANALYTICS, ConsentState.DENIED, source=ConsentSource.GPC)


@pytest.mark.parametrize(
    "values",
    [
        {"subject_ref": "person@example.test"},
        {"notice_snapshot_hash": "short"},
        {"purpose": Purpose.NECESSARY},
        {"state": ConsentState.UNKNOWN},
        {"received_at": datetime(2030, 1, 1)},
    ],
    ids=["raw-identifier", "notice-hash", "necessary", "unknown-state", "naive-time"],
)
def test_records_reject_raw_identifiers_and_invalid_states(values):
    base = {"purpose": Purpose.ANALYTICS, "state": ConsentState.GRANTED}
    purpose, state = values.pop("purpose", base["purpose"]), values.pop("state", base["state"])
    at = values.pop("received_at", NOW)
    with pytest.raises(ValueError):
        record(purpose, state, at=at, **values)


def test_only_the_strict_opt_in_profile_is_enabled():
    assert [profile.value for profile in Profile] == ["J1"]
    assert {source.value for source in ConsentSource}.isdisjoint(
        {"scroll", "form_submission", "banner_close"}
    )
