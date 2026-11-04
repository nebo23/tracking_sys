"""Form-telemetry and URL minimization contract (specification 003-B, cases M4-M5)."""

import pytest

from app.privacy.collection import (
    FormField,
    contains_card_number,
    minimize_url,
    never_collect_reason,
    sanitize_submission,
)

CARD = "4111 1111 1111 1111"  # a published test card number that passes the Luhn check
SECRET = "Synthetic secret 123!"


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        (FormField("pw", input_type="password"), "never_collect_type"),
        (FormField("token", input_type="hidden"), "never_collect_type"),
        (FormField("current", autocomplete="current-password"), "never_collect_autocomplete"),
        (FormField("fresh", autocomplete="section-a new-password"), "never_collect_autocomplete"),
        (FormField("code", autocomplete="one-time-code"), "never_collect_autocomplete"),
        (FormField("number", autocomplete="billing cc-number"), "never_collect_autocomplete"),
        (FormField("check", autocomplete="cc-csc"), "never_collect_autocomplete"),
        (FormField("cardNumber"), "sensitive_field_name"),
        (FormField("field_7", label="Card security code"), "sensitive_field_name"),
        (FormField("x", element_id="user-pin"), "sensitive_field_name"),
        (FormField("CVV"), "sensitive_field_name"),
        (FormField("amount", in_payment_frame=True), "payment_frame"),
    ],
)
def test_m4_password_card_and_code_fields_are_never_collected(item, reason):
    assert never_collect_reason(item) == reason


@pytest.mark.parametrize("name", ["email", "full_name", "pincode", "shipping", "company"])
def test_ordinary_fields_pass_the_never_collect_rules(name):
    assert never_collect_reason(FormField(name)) is None


def test_m5_submission_keeps_only_mapped_safe_values_and_counts_reasons():
    fields = [
        FormField("email", input_type="email"),
        FormField("message", input_type="textarea"),
        FormField("password", input_type="password"),
        FormField("cc", autocomplete="cc-number"),
        FormField("note"),
    ]
    values = {
        "email": "lead@example.test",
        "message": f"Please charge {CARD} today",
        "password": SECRET,
        "cc": CARD,
        "note": "unmapped text",
        "injected": SECRET,
    }
    mapping = {"email": "lead.contact", "message": "lead.contact", "password": "lead.contact"}
    result = sanitize_submission(fields, values, mapping)
    assert result.values == {"email": "lead@example.test"}
    assert result.dropped == {
        "never_collect_autocomplete": 1,
        "never_collect_type": 1,
        "payment_card_number": 1,
        "unknown_field": 1,
        "unmapped_field": 1,
    }
    assert SECRET not in repr(result) and "4111" not in repr(result)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (CARD, True),
        ("4111-1111-1111-1111", True),
        ("4111111111111112", False),  # fails the Luhn check
        ("Order 123456789012", False),  # 12 digits
        ("Call +20 100 000 0000", False),
        (CARD + " 123", True),  # followed by a security code
        (CARD + " 12/27", True),  # followed by an expiry date
        ("12 27 " + CARD, True),  # preceded by other digit groups
        ("41111111111111111111", False),  # 20 contiguous digits are not a card number
    ],
)
def test_card_number_detection(text, expected):
    assert contains_card_number(text) is expected


def test_urls_keep_only_campaign_and_click_parameters():
    url, removed = minimize_url(
        "https://user:pass@shop.example.test:8443/landing?utm_source=ads&gclid=abc"
        "&email=lead%40example.test&token=xyz#section"
    )
    assert url == "https://shop.example.test:8443/landing?utm_source=ads&gclid=abc"
    assert removed == 4
