"""EventEnvelope v1 and the pure admission rules of specification 004 (D-027).

Nothing here touches the database. The admission service (app.services.collection) calls these
functions inside its transaction, after the client lock and the consent decision, so field
minimization can depend on the purposes the subject has granted. Values removed here are
counted by closed reason codes and never returned, logged, or stored.
"""

import hashlib
import hmac
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
)

from app.privacy.collection import (
    DEFAULT_URL_PARAMETERS,
    FormField,
    contains_card_number,
    minimize_url,
    sanitize_submission,
)
from app.privacy.consent import Purpose

POLICY_VERSION = "004.1"
MAX_TEXT = 2048
MAX_FORM_FIELDS = 32
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_LATENESS = timedelta(days=7)
WEBHOOK_WINDOW_SECONDS = 300
BOT_RULES_VERSION = "bots-v1"

EventType = Literal["page_view", "link_click", "form_submit", "lead_signal", "purchase_signal"]
EVENT_TYPES: tuple[str, ...] = (
    "page_view",
    "link_click",
    "form_submit",
    "lead_signal",
    "purchase_signal",
)
# Purposes each event type needs under J1 (design section 4). No 004 event is "necessary".
REQUIRED_PURPOSES: dict[str, frozenset[Purpose]] = {
    "page_view": frozenset({Purpose.ANALYTICS}),
    "link_click": frozenset({Purpose.ANALYTICS}),
    "form_submit": frozenset({Purpose.ANALYTICS}),
    "lead_signal": frozenset({Purpose.ATTRIBUTION}),
    "purchase_signal": frozenset({Purpose.ATTRIBUTION}),
}
# Campaign descriptors are kept with analytics consent; per-click identifiers identify one ad
# click and are kept only when attribution is also granted (D-027 decision 4).
CAMPAIGN_PARAMETERS = frozenset(name for name in DEFAULT_URL_PARAMETERS if name.startswith("utm_"))
CLICK_PARAMETERS = DEFAULT_URL_PARAMETERS - CAMPAIGN_PARAMETERS
FIELD_CLASSES = ("form.option", "form.code", "form.quantity")
TRUST_RANK = {"browser": 1, "server": 2, "webhook": 2}

SubjectToken = Annotated[str, Field(pattern=r"^sbj_[A-Za-z0-9_-]{43}$")]
Text = Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]
_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_EMAIL_LIKE = re.compile(r"[^/@\s]+@[^/@\s]+\.[^/@\s]+")
# Bot heuristics (BOT_RULES_VERSION): common crawler and automation user-agent tokens. A label,
# never a claim of complete detection; changing the list needs a new version.
_BOT_AGENT = re.compile(
    r"bot|crawl|spider|slurp|headless|phantomjs|puppeteer|playwright|selenium|"
    r"python-requests|python-urllib|curl/|wget/|httpclient|okhttp|go-http-client|"
    r"lighthouse|pagespeed|preview",
    re.IGNORECASE,
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


# EventEnvelope v1. The server adds tenancy, receipt times, trust, consent basis, labels,
# revision and fingerprint; a sender cannot set them.
class Envelope(Strict):
    schema_version: Literal[1]
    event_id: UUID
    event_type: EventType
    occurred_at: AwareDatetime
    subject_token: SubjectToken
    internal: StrictBool = False
    payload: dict[str, Any]


class PageView(Strict):
    url: Text
    referrer_origin: Text | None = None


class LinkClick(Strict):
    url: Text
    link_url: Text


class FormSubmit(Strict):
    url: Text
    form_key: Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,100}$")]
    fields: dict[
        Annotated[str, Field(min_length=1, max_length=100)],
        Annotated[str, Field(max_length=MAX_TEXT)] | StrictInt,
    ] = Field(default_factory=dict, max_length=MAX_FORM_FIELDS)


class LeadSignal(Strict):
    action: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]
    url: Text | None = None


class PurchaseSignal(Strict):
    external_ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
    amount_minor: Annotated[StrictInt, Field(ge=0, le=10**12)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    url: Text | None = None


PAYLOADS: dict[str, type[Strict]] = {
    "page_view": PageView,
    "link_click": LinkClick,
    "form_submit": FormSubmit,
    "lead_signal": LeadSignal,
    "purchase_signal": PurchaseSignal,
}


# One registered form field. Only the three 004 classes may be mapped (D-027 decision 4);
# free text and contact identifiers wait for 006.
class FormFieldDefinition(Strict):
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")]
    input_type: Annotated[str, Field(min_length=1, max_length=32)] = "text"
    autocomplete: Annotated[str, Field(max_length=100)] = ""
    label: Annotated[str, Field(max_length=200)] = ""
    data_class: Literal["form.option", "form.code", "form.quantity"]
    options: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=100
    )

    @field_validator("options")
    @classmethod
    def unique_options(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Options must be unique.")
        return value


class FormDefinition(Strict):
    fields: list[FormFieldDefinition] = Field(min_length=1, max_length=MAX_FORM_FIELDS)

    @field_validator("fields")
    @classmethod
    def consistent(cls, value: list[FormFieldDefinition]) -> list[FormFieldDefinition]:
        if len({item.name for item in value}) != len(value):
            raise ValueError("Field names must be unique.")
        for item in value:
            if (item.data_class == "form.option") != bool(item.options):
                raise ValueError("Exactly the option fields list their options.")
        return value


# A rejection with a closed reason code; the event is not stored.
class Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class Minimized:
    payload: dict[str, Any]
    dropped: Counter[str] = field(default_factory=Counter)


# Validate the envelope's payload against its event type's schema.
def parse_payload(envelope: Envelope) -> Strict:
    try:
        return PAYLOADS[envelope.event_type].model_validate(envelope.payload)
    except ValidationError as error:
        raise Rejected("invalid_payload") from error


# Reject an occurred time outside +5 minutes / -7 days of the database receipt time.
def check_occurred_at(occurred_at: datetime, received_at: datetime) -> None:
    if not received_at - MAX_LATENESS <= occurred_at <= received_at + MAX_FUTURE_SKEW:
        raise Rejected("occurred_at_out_of_range")


def _http_parts(url: str):
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError as error:
        raise Rejected("url_not_allowed") from error
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise Rejected("url_not_allowed")
    return parts


# True when a decoded URL component carries a recognized prohibited value: an email-like value
# or a Luhn-valid card number (the 003 card rule). One further level of percent-decoding is
# also checked, so a double-encoded value cannot pass. This recognizes known patterns only; it
# is not general personal-data detection.
def _prohibited(decoded: str) -> bool:
    return any(
        _EMAIL_LIKE.search(text) or contains_card_number(text)
        for text in {decoded, unquote(decoded)}
    )


# Public name of the same rule for managed-link destinations (specification 005).
has_prohibited_value = _prohibited


# Minimize a page or link URL for the granted purposes: campaign parameters with analytics,
# click identifiers only with attribution as well. A path that carries a prohibited value
# rejects the event, because the page itself cannot be kept without it. An allowlisted query
# parameter whose value is prohibited is removed and counted as sensitive_query_value; an
# allowlisted name never makes its value safe (review observation on 004).
def minimize_page_url(url: str, granted: Iterable[Purpose]) -> tuple[str, Counter[str]]:
    granted = set(granted)
    parts = _http_parts(url)
    if _prohibited(unquote(parts.path)):
        raise Rejected("url_identifier")
    allowed: frozenset[str] = frozenset()
    if Purpose.ANALYTICS in granted:
        allowed |= CAMPAIGN_PARAMETERS
        if Purpose.ATTRIBUTION in granted:
            allowed |= CLICK_PARAMETERS
    dropped: Counter[str] = Counter()
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    clicks = sum(1 for key, _ in pairs if key in CLICK_PARAMETERS and key not in allowed)
    if clicks:
        dropped["click_identifier"] += clicks
    minimized, removed = minimize_url(url, allowed)
    if removed - clicks:
        dropped["url_component"] += removed - clicks
    kept = urlsplit(minimized)
    retained = parse_qsl(kept.query, keep_blank_values=True)
    safe = [(key, value) for key, value in retained if not _prohibited(value)]
    if len(safe) < len(retained):
        dropped["sensitive_query_value"] += len(retained) - len(safe)
        minimized = urlunsplit(kept._replace(query=urlencode(safe)))
    if len(minimized) > MAX_TEXT:
        raise Rejected("url_not_allowed")
    return minimized, dropped


# Scheme, host, and port of a referrer; nothing else is kept.
def origin_only(url: str) -> str:
    parts = _http_parts(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port is not None else "")


# Apply the 003 never-collect, mapping, and card-number rules with the stored descriptors, then
# keep only values valid for their 004 class. Returns kept values and dropped reason counts.
def sanitize_form(
    definition: FormDefinition, submitted: Mapping[str, str | int]
) -> tuple[dict[str, str | int], Counter[str]]:
    described = {item.name: item for item in definition.fields}
    descriptors = [
        FormField(item.name, item.input_type, item.autocomplete, item.label)
        for item in definition.fields
    ]
    mapping = {item.name: item.data_class for item in definition.fields}
    text_values = {name: str(value) for name, value in submitted.items()}
    result = sanitize_submission(descriptors, text_values, mapping)
    dropped: Counter[str] = Counter(result.dropped)
    kept: dict[str, str | int] = {}
    for name, value in result.values.items():
        item = described[name]
        if item.data_class == "form.option" and value in item.options:
            kept[name] = value
        elif item.data_class == "form.code" and _CODE.fullmatch(value):
            kept[name] = value
        elif (
            item.data_class == "form.quantity"
            and isinstance(submitted[name], int)
            and 0 <= int(submitted[name]) <= 10**6
        ):
            kept[name] = int(submitted[name])
        else:
            dropped["invalid_field_value"] += 1
    return kept, dropped


# Validate and minimize one payload for the subject's granted purposes. form is the stored
# definition for form_submit payloads (None otherwise).
def minimize_payload(
    parsed: Strict, granted: Iterable[Purpose], form: FormDefinition | None = None
) -> Minimized:
    granted = set(granted)
    result = Minimized({})

    def url(name: str, value: str | None) -> None:
        if value is None:
            return
        result.payload[name], dropped = minimize_page_url(value, granted)
        result.dropped.update(dropped)

    if isinstance(parsed, PageView):
        url("url", parsed.url)
        if parsed.referrer_origin is not None:
            result.payload["referrer_origin"] = origin_only(parsed.referrer_origin)
    elif isinstance(parsed, LinkClick):
        url("url", parsed.url)
        url("link_url", parsed.link_url)
    elif isinstance(parsed, FormSubmit):
        if form is None:
            raise Rejected("unknown_form")
        url("url", parsed.url)
        result.payload["form_key"] = parsed.form_key
        kept, dropped = sanitize_form(form, parsed.fields)
        result.payload["fields"] = kept
        result.dropped.update(dropped)
    elif isinstance(parsed, LeadSignal):
        result.payload["action"] = parsed.action
        url("url", parsed.url)
    elif isinstance(parsed, PurchaseSignal):
        result.payload.update(
            external_ref=parsed.external_ref,
            amount_minor=parsed.amount_minor,
            currency=parsed.currency,
        )
        url("url", parsed.url)
    return result


# SHA-256 over canonical JSON of the stored content; transport time and signatures excluded.
def fingerprint(
    event_type: str,
    occurred_at: datetime,
    subject_id: UUID,
    payload: Mapping[str, Any],
    internal: bool,
) -> str:
    document = {
        "schema_version": 1,
        "event_type": event_type,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "subject_id": str(subject_id),
        "payload": payload,
        "internal": internal,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


# An exact HTTP(S) browser origin: scheme, host, and optional port; no credentials, path,
# query, fragment, or wildcard (the same rule as the configured platform origins).
def is_exact_origin(origin: str) -> bool:
    try:
        parts = urlsplit(origin)
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        return False
    return (
        parts.scheme in {"http", "https"}
        and bool(parts.hostname)
        and not (parts.username or parts.password or parts.path or parts.query or parts.fragment)
        and "*" not in origin
        and len(origin) <= 200
    )


def traffic_label(channel: str, internal: bool, user_agent: str) -> str:
    if internal:
        return "internal"
    if channel == "browser" and _BOT_AGENT.search(user_agent or ""):
        return "bot_suspected"
    return "unclassified"


# Generic webhook signature: header "t=<unix seconds>,v1=<hex HMAC-SHA256>" over
# "<t>.<raw body>" with the source secret.
def sign_webhook(secret: str, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def parse_signature(header: str | None) -> tuple[int, str]:
    if not header or len(header) > 200:
        raise Rejected("signature_invalid")
    values = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
    timestamp, signature = values.get("t", ""), values.get("v1", "")
    valid_time = timestamp.isascii() and timestamp.isdigit() and len(timestamp) <= 12
    if not valid_time or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise Rejected("signature_invalid")
    return int(timestamp), signature


# Check the signature against the live secrets (newest first), then the time window. Runs
# before parsing. Each comparison is constant time; stopping at the first match reveals only
# which still-valid version signed, never secret material.
def verify_webhook(header: str | None, body: bytes, secrets: Iterable[str], now: datetime) -> None:
    timestamp, signature = parse_signature(header)
    if not any(
        hmac.compare_digest(sign_webhook(secret, timestamp, body), signature) for secret in secrets
    ):
        raise Rejected("signature_invalid")
    if abs(now.timestamp() - timestamp) > WEBHOOK_WINDOW_SECONDS:
        raise Rejected("signature_expired")
