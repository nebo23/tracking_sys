"""Collection minimization for form telemetry and URLs (specification 003-B, D-025).

Form capture is an allowlist: a field is kept only when the client mapped it to an approved
data class, and never-collect rules drop it even then. The rules apply in the tracker (005)
and again at ingestion (004), regardless of tracker version. Results report dropped counts by
reason code only; dropped values are never returned, logged, or quarantined.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

NEVER_COLLECT_TYPES = frozenset({"password", "hidden"})
NEVER_COLLECT_AUTOCOMPLETE = frozenset({"current-password", "new-password", "one-time-code"})
# Name, id, or label tokens of password, card, card security code, and PIN fields. This is a
# second layer behind the type and autocomplete rules, so it errs toward dropping.
SENSITIVE_TOKENS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "passcode",
        "pin",
        "otp",
        "cvv",
        "cvv2",
        "cvc",
        "csc",
        "card",
        "cardnumber",
        "ccnum",
        "ccnumber",
        "creditcard",
        "securitycode",
    }
)
# Campaign and click parameters kept in collected URLs; every other query value and the
# fragment are dropped. Specification 005 reviews additions.
DEFAULT_URL_PARAMETERS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "gbraid",
        "wbraid",
        "fbclid",
        "msclkid",
        "ttclid",
        "li_fat_id",
        "twclid",
    }
)
# A run of digit groups joined by single spaces or hyphens.
_DIGIT_RUN = re.compile(r"\d+(?:[ -]\d+)*")


@dataclass(frozen=True)
class FormField:
    name: str
    input_type: str = "text"
    autocomplete: str = ""
    label: str = ""
    element_id: str = ""
    in_payment_frame: bool = False


@dataclass(frozen=True)
class SanitizedSubmission:
    values: dict[str, str]
    dropped: dict[str, int] = field(default_factory=dict)


# Lowercase tokens of an identifier or label: splits on non-alphanumerics and camelCase, and
# also keeps the joined form so "cardNumber" and "card_number" both yield "cardnumber".
def _tokens(text: str) -> set[str]:
    parts = [part.lower() for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", text) if part]
    return set(parts) | {"".join(parts)} if parts else set()


# The reason a field must never be collected, or None when the never-collect rules allow it.
def never_collect_reason(item: FormField) -> str | None:
    if item.in_payment_frame:
        return "payment_frame"
    if item.input_type.strip().lower() in NEVER_COLLECT_TYPES:
        return "never_collect_type"
    tokens = item.autocomplete.lower().split()
    if any(token in NEVER_COLLECT_AUTOCOMPLETE or token.startswith("cc-") for token in tokens):
        return "never_collect_autocomplete"
    if any(_tokens(text) & SENSITIVE_TOKENS for text in (item.name, item.element_id, item.label)):
        return "sensitive_field_name"
    return None


# Luhn check over the digits of a candidate card number.
def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, character in enumerate(reversed(digits)):
        value = int(character)
        if index % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


# True when free text contains a card number, as one typed into an ordinary field would be:
# 13-19 digits passing the Luhn check, formed by consecutive digit groups of a run (groups
# joined by single spaces or hyphens). Checking every group-aligned span keeps detection when
# the number is followed or preceded by other digits, such as a security code or expiry date.
def contains_card_number(value: str) -> bool:
    for run in _DIGIT_RUN.finditer(value):
        groups = re.split(r"[ -]", run.group())
        for start in range(len(groups)):
            digits = ""
            for group in groups[start:]:
                digits += group
                if len(digits) > 19:
                    break
                if len(digits) >= 13 and _luhn_valid(digits):
                    return True
    return False


# Apply the allowlist and never-collect rules to one submission. mapping names the client's
# approved data class for each collectable field; submitted keys without a descriptor are
# unknown and dropped.
def sanitize_submission(
    fields: Sequence[FormField], values: Mapping[str, str], mapping: Mapping[str, str]
) -> SanitizedSubmission:
    described = {item.name: item for item in fields}
    kept: dict[str, str] = {}
    dropped: Counter[str] = Counter()
    for name, value in values.items():
        item = described.get(name)
        if item is None:
            dropped["unknown_field"] += 1
            continue
        reason = never_collect_reason(item)
        if reason is None and not mapping.get(name):
            reason = "unmapped_field"
        if reason is None and contains_card_number(value):
            reason = "payment_card_number"
        if reason is None:
            kept[name] = value
        else:
            dropped[reason] += 1
    return SanitizedSubmission(kept, dict(sorted(dropped.items())))


# Keep a URL's scheme, host, port, path, and allowlisted query parameters; drop credentials,
# the fragment, and every other parameter. Returns the minimized URL and the dropped count.
def minimize_url(url: str, allowed: frozenset[str] = DEFAULT_URL_PARAMETERS) -> tuple[str, int]:
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(key, value) for key, value in pairs if key in allowed]
    netloc = parts.hostname or ""
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    minimized = urlunsplit((parts.scheme, netloc, parts.path, urlencode(kept), ""))
    removed = len(pairs) - len(kept) + int(bool(parts.fragment)) + int(bool(parts.username))
    return minimized, removed
