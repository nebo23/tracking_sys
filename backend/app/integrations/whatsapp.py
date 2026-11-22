"""WhatsApp Cloud API notifications: signature, parsing and minimization (015-E, D-068 E7, E8).

Pure functions only: no database and no network. verify reads the X-Hub-Signature-256 header,
an HMAC-SHA256 of the raw body under the Meta app secret prefixed with sha256= (second-round
entry review W-6), and compares it in constant time. messages reads the inbound messages of a
verified whatsapp_business_account body (W-7) and keeps, for each, a digest of its message ID,
its timestamp and only its Click-to-WhatsApp referral: the source type, the ad ID and whether a
click ID was present. Phone numbers, names, sender IDs, text, ad copy, media URLs and click IDs
never leave this module. Status notifications carry no message and yield nothing.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

SIGNATURE = re.compile(r"sha256=([0-9a-fA-F]{64})")
DIGITS = re.compile(r"[1-9][0-9]{0,31}")
SOURCE_TYPES = frozenset({"ad", "post"})
EARLIEST = datetime(2015, 1, 1, tzinfo=UTC)


class Unverifiable(ValueError):
    """The notification cannot be verified; the route answers 401 and stores nothing."""


@dataclass(frozen=True)
class Message:
    phone_number_id: str
    digest: str  # SHA-256 of the provider's message ID
    message_at: datetime | None
    has_referral: bool
    source_type: str | None
    source_id: str | None
    click_id_present: bool


def verify(body: bytes, header: str | None, app_secret: str) -> Mapping[str, Any]:
    match = SIGNATURE.fullmatch(header or "")
    if match is None or not app_secret:
        raise Unverifiable("missing_signature")
    computed = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest().encode()
    if not hmac.compare_digest(computed, match.group(1).lower().encode()):
        raise Unverifiable("invalid_signature")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise Unverifiable("invalid_body") from error
    if not isinstance(payload, dict):
        raise Unverifiable("invalid_body")
    return payload


def _digits(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return value if isinstance(value, str) and DIGITS.fullmatch(value) else None


def _moment(value: Any) -> datetime | None:
    text = _digits(value)
    if text is None or len(text) > 12:
        return None
    moment = datetime.fromtimestamp(int(text), UTC)
    return moment if moment >= EARLIEST else None


def _message(phone_number_id: str, item: Mapping[str, Any]) -> Message | None:
    identifier = item.get("id")
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 512:
        return None
    referral = item.get("referral")
    digest = hashlib.sha256(identifier.encode()).hexdigest()
    moment = _moment(item.get("timestamp"))
    if not isinstance(referral, Mapping):
        return Message(phone_number_id, digest, moment, False, None, None, False)
    source = referral.get("source_type")
    return Message(
        phone_number_id,
        digest,
        moment,
        True,
        source if source in SOURCE_TYPES else "other",
        _digits(referral.get("source_id")),
        isinstance(referral.get("ctwa_clid"), str) and bool(referral.get("ctwa_clid")),
    )


# The inbound messages of a verified body, per phone number ID. Anything that is not a
# whatsapp_business_account messages change is skipped.
def messages(payload: Mapping[str, Any]) -> Iterator[Message]:
    if payload.get("object") != "whatsapp_business_account":
        return
    entries = payload.get("entry")
    for entry in entries if isinstance(entries, list) else ():
        changes = entry.get("changes") if isinstance(entry, Mapping) else None
        for change in changes if isinstance(changes, list) else ():
            if not isinstance(change, Mapping) or change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, Mapping):
                continue
            metadata = value.get("metadata")
            number = (
                _digits(metadata.get("phone_number_id")) if isinstance(metadata, Mapping) else None
            )
            items = value.get("messages")
            if number is None or not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, Mapping) and (message := _message(number, item)) is not None:
                    yield message
