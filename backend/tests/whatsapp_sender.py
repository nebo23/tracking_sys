"""Synthetic WhatsApp Cloud API notifications for tests (specification 015-E, D-068 E13).

Bodies follow the documented messages webhook (second-round entry review W-6 and W-7): the
whatsapp_business_account object, entries with messages changes, metadata with the phone number
ID, contacts with a profile name, wa_id and user_id, and messages with sender fields, text and an
optional Click-to-WhatsApp referral. They are signed with HMAC-SHA256 of the raw body under a test
app secret in X-Hub-Signature-256. Every value is synthetic; nothing opens a network connection.
"""

import hashlib
import hmac
import json
from itertools import count
from typing import Any

APP_SECRET = "SYNTHETIC-META-APP-SECRET-0001"
VERIFY_TOKEN = "SYNTHETIC-VERIFY-TOKEN-0001"
PHONE = "201000000853"
NAME = "Synthetic Customer"
USER_ID = "EG.synthetic-user-0853"
TEXT = "Synthetic private message 853"
HEADLINE = "Synthetic ad headline 853"
AD_BODY = "Synthetic ad body 853"
MEDIA_URL = "https://media.example.test/ad-853.jpg"
CLICK_ID = "synthetic-ctwa-clid-0853"
FORBIDDEN = (PHONE, NAME, USER_ID, TEXT, HEADLINE, AD_BODY, MEDIA_URL, CLICK_ID)
_ids = count(1)


def message(
    *,
    referral: bool = True,
    source_type: str = "ad",
    ad_id: str = "120210000000853",
    click_id: bool = True,
    timestamp: int = 1_763_000_000,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "from": PHONE,
        "from_user_id": USER_ID,
        "id": f"wamid.SYNTHETIC{next(_ids):06d}",
        "timestamp": str(timestamp),
        "type": "text",
        "text": {"body": TEXT},
    }
    if referral:
        item["referral"] = {
            "source_url": "https://fb.me/synthetic",
            "source_id": ad_id,
            "source_type": source_type,
            "body": AD_BODY,
            "headline": HEADLINE,
            "media_type": "image",
            "image_url": MEDIA_URL,
            "welcome_message": {"text": "Synthetic greeting"},
        }
        if click_id:
            item["referral"]["ctwa_clid"] = CLICK_ID
    return item


def notification(phone_number_id: str, *messages: dict[str, Any], statuses: bool = False) -> dict:
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "+20 100 000 0001",
            "phone_number_id": phone_number_id,
        },
        "contacts": [{"profile": {"name": NAME}, "wa_id": PHONE, "user_id": USER_ID}],
    }
    if statuses:
        value["statuses"] = [{"id": "wamid.STATUS", "status": "delivered", "recipient_id": PHONE}]
    else:
        value["messages"] = list(messages)
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "102290129340398", "changes": [{"value": value, "field": "messages"}]}],
    }


def signed(body: dict[str, Any], secret: str = APP_SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-hub-signature-256": f"sha256={signature}", "content-type": "application/json"}
