"""WhatsApp Cloud API notifications: signature, parsing and minimization (015-E, D-068 E7, E8).

Pure functions only: no database and no network. verify reads the X-Hub-Signature-256 header,
an HMAC-SHA256 of the raw body under the Meta app secret prefixed with sha256= (second-round
entry review W-6), and compares it in constant time. messages reads the inbound messages of a
verified whatsapp_business_account body (W-7) and keeps, for each, a digest of its message ID,
its timestamp and only its Click-to-WhatsApp referral: the source type, the ad ID and whether a
click ID was present. Phone numbers, names, sender IDs, text, ad copy, media URLs and click IDs
never leave this module. Status notifications carry no message and yield nothing.

Every item of a signed batch is read on its own (review finding R009): a value of an unexpected
type or range in one message never raises, so a malformed message cannot make the route answer
500 and discard its valid siblings, nor make Meta retry an otherwise handled batch for days. A
source type that is not a known string is kept as other, a timestamp outside 2015-2099 is
unknown, and a message without a usable ID is skipped. The parser has no database access, so
storage failures still surface as errors in the caller.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

SIGNATURE = re.compile(r"sha256=([0-9a-fA-F]{64})")
DIGITS = re.compile(r"[1-9][0-9]{0,31}")
SOURCE_TYPES = frozenset({"ad", "post"})
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
EARLIEST = datetime(2015, 1, 1, tzinfo=UTC)
LATEST = datetime(2100, 1, 1, tzinfo=UTC)
# Message times as Unix seconds, bounded before any conversion: datetime.fromtimestamp raises
# OverflowError, OSError or ValueError for large values depending on the platform.
_EARLIEST_SECONDS = int((EARLIEST - EPOCH).total_seconds())
_LATEST_SECONDS = int((LATEST - EPOCH).total_seconds())


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
    seconds = int(text)
    if not _EARLIEST_SECONDS <= seconds < _LATEST_SECONDS:
        return None
    return EPOCH + timedelta(seconds=seconds)


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
    click = referral.get("ctwa_clid")
    return Message(
        phone_number_id,
        digest,
        moment,
        True,
        source if isinstance(source, str) and source in SOURCE_TYPES else "other",
        _digits(referral.get("source_id")),
        isinstance(click, str) and bool(click),
    )


# One message of a batch, or None when it cannot be read. The reading above raises for no input;
# the narrow guard keeps a future parsing error confined to its own message. It never covers
# storage, which happens in the caller after parsing.
def _read(phone_number_id: str, item: Any) -> Message | None:
    if not isinstance(item, Mapping):
        return None
    try:
        return _message(phone_number_id, item)
    except (TypeError, ValueError, OverflowError):
        return None


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
                if (message := _read(number, item)) is not None:
                    yield message
