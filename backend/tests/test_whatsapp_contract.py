"""WhatsApp signature, parsing and minimization without a database (specification 015-E).

D-068 decisions E7 and E8; every value is synthetic and comes from tests/whatsapp_sender.py.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest
from whatsapp_sender import APP_SECRET, FORBIDDEN, message, notification, signed

from app.integrations.whatsapp import (
    _EARLIEST_SECONDS,
    _LATEST_SECONDS,
    EARLIEST,
    LATEST,
    Unverifiable,
    _moment,
    messages,
    verify,
)


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


def test_malformed_items_never_raise_and_keep_their_siblings():
    # R009: list, object, null and number source types, out-of-range timestamps (a twelve-digit
    # value raised in datetime.fromtimestamp), a referral that is not an object, items without a
    # usable ID and items that are not objects are each read on their own; valid messages before
    # and after them are kept in order.
    good_first, good_last = message(), message()
    shapes = []
    for value in ([], {}, None, 5, ["ad"], {"type": "ad"}):
        item = message()
        item["referral"]["source_type"] = value
        shapes.append(item)
    timed = [message(timestamp=value) for value in (999_999_999_999, 4_102_444_800, 1)]
    flat = message()
    flat["referral"] = ["not", "an", "object"]
    anonymous = message()
    del anonymous["id"]
    long_id = dict(message(), id="w" * 513)
    body = notification(
        "1001",
        good_first,
        *shapes,
        *timed,
        flat,
        anonymous,
        long_id,
        "not an object",
        7,
        None,
        good_last,
    )
    items = list(messages(body))
    expected = 1 + len(shapes) + len(timed) + 1 + 1
    assert len(items) == expected
    assert items[0].source_type == "ad" and items[-1].source_type == "ad"
    assert [item.source_type for item in items[1 : 1 + len(shapes)]] == ["other"] * len(shapes)
    assert [item.message_at for item in items[1 + len(shapes) : -2]] == [None, None, None]
    assert items[-2].has_referral is False  # a referral that is not an object
    digests = {item.digest for item in items}
    assert len(digests) == expected


def test_message_times_are_bounded_before_conversion():
    # R009: the conversion uses arithmetic within 2015-2099, never the platform's time functions.
    assert _moment(str(_EARLIEST_SECONDS)) == EARLIEST
    assert _moment(_LATEST_SECONDS - 1) == LATEST - timedelta(seconds=1)
    for value in (_EARLIEST_SECONDS - 1, _LATEST_SECONDS, "999999999999", "1" * 13, -5, 1.5):
        assert _moment(value) is None, value
    assert _moment(1_763_000_000) == datetime.fromtimestamp(1_763_000_000, UTC)


def test_statuses_and_other_objects_yield_nothing():
    assert list(messages(notification("1001", statuses=True))) == []
    assert list(messages({"object": "page", "entry": []})) == []
    assert list(messages({"object": "whatsapp_business_account", "entry": "x"})) == []
    bad_number = notification("1001", message())
    bad_number["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "+201000"
    assert list(messages(bad_number)) == []
    old = notification("1001", message(timestamp=10))
    assert next(messages(old)).message_at is None
