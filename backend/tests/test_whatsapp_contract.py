"""WhatsApp signature, parsing and minimization without a database (specification 015-E).

D-068 decisions E7 and E8; every value is synthetic and comes from tests/whatsapp_sender.py.
"""

import hashlib
import hmac
from datetime import UTC, datetime

import pytest
from whatsapp_sender import APP_SECRET, FORBIDDEN, message, notification, signed

from app.integrations.whatsapp import Unverifiable, messages, verify


def test_signature_is_verified_in_constant_time():
    raw, headers = signed(notification("1001", message()))
    assert (
        verify(raw, headers["x-hub-signature-256"], APP_SECRET)["object"]
        == "whatsapp_business_account"
    )
    upper = "sha256=" + headers["x-hub-signature-256"].removeprefix("sha256=").upper()
    assert verify(raw, upper, APP_SECRET)
    for header, secret in (
        (None, APP_SECRET),
        ("", APP_SECRET),
        (headers["x-hub-signature-256"].removeprefix("sha256="), APP_SECRET),  # no prefix
        ("sha256=" + "0" * 64, APP_SECRET),
        (headers["x-hub-signature-256"], "OTHER-SECRET-0000000"),
        (headers["x-hub-signature-256"], ""),
    ):
        with pytest.raises(Unverifiable):
            verify(raw, header, secret)
    # A correctly signed body nested beyond the decoder's depth is unverifiable, not an error.
    nested = b"[" * 30_000 + b"]" * 30_000
    signature = hmac.new(APP_SECRET.encode(), nested, hashlib.sha256).hexdigest()
    with pytest.raises(Unverifiable):
        verify(nested, f"sha256={signature}", APP_SECRET)


def test_messages_keep_only_the_referral():
    # T-61, T-62: the referral's source type and ad ID and the click-ID presence; nothing else.
    body = notification(
        "1001",
        message(),
        message(referral=False),
        message(source_type="post", click_id=False, ad_id="not-digits"),
        message(source_type="story"),
    )
    items = list(messages(body))
    assert [(m.has_referral, m.source_type, m.source_id, m.click_id_present) for m in items] == [
        (True, "ad", "120210000000853", True),
        (False, None, None, False),
        (True, "post", None, False),
        (True, "other", "120210000000853", True),
    ]
    assert all(m.phone_number_id == "1001" and len(m.digest) == 64 for m in items)
    assert items[0].message_at == datetime.fromtimestamp(1_763_000_000, UTC)
    assert items[0].digest != hashlib.sha256(b"").hexdigest()
    for value in FORBIDDEN:
        assert value not in repr(items), value


def test_statuses_and_other_objects_yield_nothing():
    assert list(messages(notification("1001", statuses=True))) == []
    assert list(messages({"object": "page", "entry": []})) == []
    assert list(messages({"object": "whatsapp_business_account", "entry": "x"})) == []
    bad_number = notification("1001", message())
    bad_number["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "+201000"
    assert list(messages(bad_number)) == []
    old = notification("1001", message(timestamp=10))
    assert next(messages(old)).message_at is None
