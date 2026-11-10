"""EventEnvelope v1 rules of specification 004 (D-027) without a database."""

import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.collection.contract import (
    CAMPAIGN_PARAMETERS,
    CLICK_PARAMETERS,
    Envelope,
    FormDefinition,
    Rejected,
    check_occurred_at,
    fingerprint,
    is_exact_origin,
    minimize_page_url,
    minimize_payload,
    origin_only,
    parse_payload,
    sanitize_form,
    sign_webhook,
    traffic_label,
    verify_webhook,
)
from app.collection.keys import TombstoneKeyring
from app.config import Settings
from app.privacy.consent import Purpose

NOW = datetime(2030, 1, 1, 12, 0, 1, tzinfo=UTC)
TOKEN = "sbj_" + "A" * 43
CARD = "4111 1111 1111 1111"
ANALYTICS = {Purpose.ANALYTICS}
BOTH = {Purpose.ANALYTICS, Purpose.ATTRIBUTION}
FORM = FormDefinition.model_validate(
    {
        "fields": [
            {"name": "plan", "data_class": "form.option", "options": ["basic", "pro"]},
            {"name": "promo", "data_class": "form.code"},
            {"name": "seats", "data_class": "form.quantity", "input_type": "number"},
            {"name": "card_number", "data_class": "form.code"},
            {"name": "secret", "data_class": "form.code", "input_type": "password"},
            {"name": "otp", "data_class": "form.code", "autocomplete": "one-time-code"},
        ]
    }
)


def envelope(**changes) -> Envelope:
    data = {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "event_type": "page_view",
        "occurred_at": NOW.isoformat(),
        "subject_token": TOKEN,
        "payload": {"url": "https://shop.example.test/offer?utm_source=demo"},
        **changes,
    }
    return Envelope.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"event_type": "custom"},
        {"occurred_at": "2030-01-01T12:00:00"},
        {"subject_token": "user@example.test"},
        {"unexpected": True},
        {"internal": "yes"},
    ],
)
def test_envelope_rejects_unknown_versions_types_naive_times_and_extra_fields(change):
    with pytest.raises(ValidationError):
        envelope(**change)


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("page_view", {"url": "https://a.test/", "title": "Extra field"}),
        ("purchase_signal", {"external_ref": "o-1", "amount_minor": "100", "currency": "USD"}),
        ("purchase_signal", {"external_ref": "o-1", "amount_minor": True, "currency": "USD"}),
        ("purchase_signal", {"external_ref": "o 1", "amount_minor": 1, "currency": "USD"}),
        ("lead_signal", {"action": "Book Call"}),
        ("form_submit", {"url": "https://a.test/", "form_key": "f", "fields": {"x": 1.5}}),
        ("page_view", {"url": "x" * 2049}),
    ],
)
def test_payload_schemas_are_strict(event_type, payload):
    with pytest.raises(Rejected, match="invalid_payload"):
        parse_payload(envelope(event_type=event_type, payload=payload))


def test_occurred_at_window_uses_receipt_time():
    check_occurred_at(NOW - timedelta(days=7), NOW)
    check_occurred_at(NOW + timedelta(minutes=5), NOW)
    for value in (NOW - timedelta(days=7, seconds=1), NOW + timedelta(minutes=5, seconds=1)):
        with pytest.raises(Rejected, match="occurred_at_out_of_range"):
            check_occurred_at(value, NOW)


def test_campaign_parameters_need_analytics_and_click_identifiers_also_attribution():
    url = "https://user:pw@Shop.example.test:8443/p?utm_source=a&gclid=g&fbclid=f&q=x#frag"
    kept, dropped = minimize_page_url(url, ANALYTICS)
    assert kept == "https://shop.example.test:8443/p?utm_source=a"
    assert dropped == {"click_identifier": 2, "url_component": 3}
    kept, dropped = minimize_page_url(url, BOTH)
    assert kept == "https://shop.example.test:8443/p?utm_source=a&gclid=g&fbclid=f"
    assert dropped == {"url_component": 3}
    assert minimize_page_url(url, {Purpose.ATTRIBUTION})[0] == "https://shop.example.test:8443/p"
    assert CAMPAIGN_PARAMETERS.isdisjoint(CLICK_PARAMETERS)


@pytest.mark.parametrize(
    "url",
    [
        "https://a.test/users/someone@example.test/profile",
        "https://a.test/users/someone%40example.test",
        f"https://a.test/pay/{CARD.replace(' ', '-')}",
    ],
)
def test_identifiers_in_paths_reject_the_event(url):
    with pytest.raises(Rejected, match="url_identifier"):
        minimize_page_url(url, BOTH)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://a.test/", "https://a.test:99999/"])
def test_only_http_urls_are_accepted(url):
    with pytest.raises(Rejected, match="url_not_allowed"):
        minimize_page_url(url, BOTH)


def test_referrer_keeps_origin_only():
    assert origin_only("https://ref.example.test:444/path?q=1#x") == "https://ref.example.test:444"
    assert origin_only("http://[::1]:8000/a") == "http://[::1]:8000"


def test_forms_apply_never_collect_card_scan_and_class_rules():
    kept, dropped = sanitize_form(
        FORM,
        {
            "plan": "pro",
            "promo": "SPRING-24",
            "seats": 3,
            "card_number": "SAVE10",
            "secret": "hunter2hunter2",
            "otp": "123456",
            "message": "call me at someone@example.test",
            "unknown": "x",
        },
    )
    assert kept == {"plan": "pro", "promo": "SPRING-24", "seats": 3}
    assert dropped == {
        "sensitive_field_name": 1,
        "never_collect_type": 1,
        "never_collect_autocomplete": 1,
        "unknown_field": 2,
    }


@pytest.mark.parametrize(
    "values",
    [
        {"plan": "enterprise"},
        {"promo": CARD},
        {"promo": "has space"},
        {"seats": "3"},
        {"seats": 10**6 + 1},
    ],
)
def test_form_values_outside_their_class_are_dropped(values):
    kept, dropped = sanitize_form(FORM, values)
    assert kept == {}
    assert sum(dropped.values()) == 1


def test_a_card_number_in_a_code_field_is_dropped_by_the_scan():
    kept, dropped = sanitize_form(FORM, {"promo": "4111111111111111"})
    assert kept == {} and dropped == {"payment_card_number": 1}


@pytest.mark.parametrize(
    "fields",
    [
        [{"name": "a", "data_class": "form.option"}],
        [{"name": "a", "data_class": "form.code", "options": ["x"]}],
        [{"name": "a", "data_class": "contact.email"}],
        [{"name": "a", "data_class": "form.code"}, {"name": "a", "data_class": "form.code"}],
        [{"name": "a b", "data_class": "form.code"}],
    ],
)
def test_form_definitions_allow_only_004_classes(fields):
    with pytest.raises(ValidationError):
        FormDefinition.model_validate({"fields": fields})


def test_form_submit_needs_a_registered_form_and_purchase_keeps_claim_fields():
    parsed = parse_payload(
        envelope(
            event_type="form_submit",
            payload={"url": "https://a.test/f", "form_key": "lead", "fields": {"plan": "basic"}},
        )
    )
    with pytest.raises(Rejected, match="unknown_form"):
        minimize_payload(parsed, ANALYTICS, None)
    assert minimize_payload(parsed, ANALYTICS, FORM).payload == {
        "url": "https://a.test/f",
        "form_key": "lead",
        "fields": {"plan": "basic"},
    }
    purchase = parse_payload(
        envelope(
            event_type="purchase_signal",
            payload={"external_ref": "order-1", "amount_minor": 1999, "currency": "EGP"},
        )
    )
    assert minimize_payload(purchase, {Purpose.ATTRIBUTION}).payload == {
        "external_ref": "order-1",
        "amount_minor": 1999,
        "currency": "EGP",
    }


def test_fingerprint_is_canonical_and_excludes_transport():
    subject = uuid4()
    first = fingerprint("page_view", NOW, subject, {"b": 1, "a": [1, 2]}, False)
    shifted = NOW.astimezone(UTC).replace(tzinfo=UTC)
    assert first == fingerprint("page_view", shifted, subject, {"a": [1, 2], "b": 1}, False)
    assert first != fingerprint("page_view", NOW, subject, {"a": [1, 2], "b": 2}, False)
    assert first != fingerprint("page_view", NOW, uuid4(), {"a": [1, 2], "b": 1}, False)
    assert first != fingerprint("page_view", NOW, subject, {"a": [1, 2], "b": 1}, True)


def test_traffic_labels():
    assert traffic_label("browser", False, "Mozilla/5.0 Googlebot/2.1") == "bot_suspected"
    assert traffic_label("browser", False, "Mozilla/5.0 (Windows NT 10.0)") == "unclassified"
    assert traffic_label("server", False, "python-requests/2.0") == "unclassified"
    assert traffic_label("server", True, "") == "internal"


def test_webhook_signature_window_and_constant_secret_list():
    body = b'{"x":1}'
    stamp = int(NOW.timestamp())
    header = f"t={stamp},v1={sign_webhook('whsec_current', stamp, body)}"
    verify_webhook(header, body, ["whsec_old", "whsec_current"], NOW)
    for bad_header, bad_body, secrets, now, reason in [
        (header, body + b" ", ["whsec_current"], NOW, "signature_invalid"),
        (header, body, ["whsec_other"], NOW, "signature_invalid"),
        (header, body, ["whsec_current"], NOW + timedelta(seconds=301), "signature_expired"),
        (None, body, ["whsec_current"], NOW, "signature_invalid"),
        ("t=abc,v1=00", body, ["whsec_current"], NOW, "signature_invalid"),
        (f"t={chr(0xB2)},v1={'0' * 64}", body, ["whsec_current"], NOW, "signature_invalid"),
    ]:
        with pytest.raises(Rejected, match=reason):
            verify_webhook(bad_header, bad_body, secrets, now)


def test_exact_origins():
    assert is_exact_origin("https://shop.example.test")
    assert is_exact_origin("http://127.0.0.1:5173")
    for origin in ("https://shop.example.test/", "https://*.example.test", "ftp://a.test", "a"):
        assert not is_exact_origin(origin)


def test_tombstone_keyring_is_add_only_and_client_bound():
    old, new = "11" * 32, "22" * 32
    first = TombstoneKeyring.from_text(f"t1:{old}", "t1")
    rotated = TombstoneKeyring.from_text(f"t1:{old},t2:{new}", "t2")
    client = uuid4()
    sealed, key_id = first.seal(client, "event_id", "e-1")
    assert key_id == "t1" and sealed in rotated.candidates(client, "event_id", "e-1")
    assert rotated.seal(client, "event_id", "e-1")[1] == "t2"
    assert sealed not in rotated.candidates(uuid4(), "event_id", "e-1")
    assert "11" not in repr(rotated)
    for text, active in [(f"t1:{old}", "t2"), ("t1:00", "t1"), (f"t1:{old},t2:{old}", "t1")]:
        with pytest.raises(ValueError):
            TombstoneKeyring.from_text(text, active)


def keyed_settings(monkeypatch, **values) -> Settings:
    import os

    for name in list(os.environ):
        if name.startswith("TRACKING_"):
            monkeypatch.delenv(name)
    for name in ("TRACKING_AUTH_SECRET", "TRACKING_OTP_SECRET"):
        monkeypatch.setenv(name, ("ab" if "AUTH" in name else "cd") * 32)
    monkeypatch.setenv("TRACKING_MAIL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    return Settings(_env_file=None, database_password=SecretStr("synthetic"), **values)


def test_keyrings_are_optional_validated_and_independent(monkeypatch):
    unset = keyed_settings(monkeypatch)
    assert unset.token_keys() is None and unset.tombstone_keys() is None
    token = "k1:" + base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    configured = keyed_settings(
        monkeypatch,
        token_keyring=SecretStr(token),
        token_keyring_active="k1",
        tombstone_keyring=SecretStr("t1:" + "ef" * 32),
        tombstone_keyring_active="t1",
    )
    assert configured.token_keys().active == "k1"
    assert configured.tombstone_keys().active == "t1"
    for invalid in [
        {"tombstone_keyring": SecretStr("t1:" + "ab" * 32), "tombstone_keyring_active": "t1"},
        {"tombstone_keyring": SecretStr("t1:zz"), "tombstone_keyring_active": "t1"},
        {"token_keyring": SecretStr("k1:short"), "token_keyring_active": "k1"},
        {"token_keyring": SecretStr(token), "token_keyring_active": "missing"},
    ]:
        with pytest.raises(ValidationError):
            keyed_settings(monkeypatch, **invalid)
