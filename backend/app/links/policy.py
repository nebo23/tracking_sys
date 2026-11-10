"""Managed-link destination, hostname, slug, and UTM rules (specification 005-B, D-033).

Pure functions: nothing here reads the database, the network, or the request. Validation never
fetches a destination; it checks the submitted text against the client's registered origins
and the reviewed rules of design section 4. Failures raise LinkRuleError with a closed reason
code, never echoing the rejected value. Pattern checks for email addresses and card numbers
recognize known forms only; they do not establish general personal-data detection.
"""

import ipaddress
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from app.collection.contract import CAMPAIGN_PARAMETERS, CLICK_PARAMETERS, has_prohibited_value
from app.privacy.collection import contains_card_number

UTM_PARAMETERS = CAMPAIGN_PARAMETERS
LINK_PARAMETER = "ts_link"
MAX_URL = 2048
MAX_QUERY_NAMES = 20
CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
CAMPAIGN_CODE = CODE
CONTENT_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
QUERY_NAME = re.compile(r"[a-z0-9_]{1,64}")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_PRINTABLE = re.compile(r"[\x21-\x7e]+")
_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
# Encoded characters that make a path or value ambiguous after decoding: slash, backslash,
# dot, percent (double encoding), and every control character.
_AMBIGUOUS = re.compile(r"%(?:2[EeFf5]|5[Cc]|[01][0-9A-Fa-f]|7[Ff])")
_DOT_SEGMENT = re.compile(r"(?:^|/)\.{1,2}(?:/|$)")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})
# Short paths a link slug must not shadow, now or in a later specification.
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "app",
        "assets",
        "auth",
        "collect",
        "docs",
        "health",
        "help",
        "login",
        "logout",
        "openapi",
        "redoc",
        "static",
        "status",
        "support",
        "tracker",
        "webhooks",
        "www",
    }
)
# Name suffixes of private, local, or special-use networks. RFC 2606 "test" and "example"
# names stay allowed: they never resolve publicly and the synthetic fixtures use them.
INTERNAL_SUFFIXES = (
    "localhost",
    "local",
    "internal",
    "intranet",
    "lan",
    "home.arpa",
    "corp",
    "private",
    "arpa",
    "onion",
    "invalid",
)
# Static query names that would carry credentials, signatures, sessions, or person or customer
# identifiers. Static names are reviewed configuration, so detection errs toward refusing.
_SENSITIVE_NAME_TOKENS = frozenset(
    {
        "token",
        "sig",
        "signature",
        "key",
        "apikey",
        "auth",
        "session",
        "sid",
        "secret",
        "password",
        "passwd",
        "pwd",
        "email",
        "mail",
        "phone",
        "tel",
        "user",
        "uid",
        "customer",
        "account",
        "credential",
        "otp",
        "card",
    }
)


class LinkRuleError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Origin:
    scheme: str
    hostname: str
    port: int | None

    # Canonical text: scheme://host with the port only when it is not the scheme default.
    @property
    def text(self) -> str:
        return f"{self.scheme}://{self.authority}"

    @property
    def authority(self) -> str:
        return self.hostname if self.port is None else f"{self.hostname}:{self.port}"


@dataclass(frozen=True)
class Destination:
    origin: Origin
    path: str
    static: tuple[tuple[str, str], ...]
    utm: dict[str, str]


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        return False
    return True


# Canonical lowercase ASCII (IDNA) hostname with at least two labels; no IP literal, wildcard,
# trailing dot, or private or special-use suffix.
def canonical_hostname(host: str) -> str:
    if not isinstance(host, str) or not host or len(host) > 253 or host.endswith("."):
        raise LinkRuleError("invalid_hostname")
    if _is_ip(host) or "*" in host:
        raise LinkRuleError("invalid_hostname")
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise LinkRuleError("invalid_hostname") from error
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or len(labels) < 2 or not all(_LABEL.fullmatch(x) for x in labels):
        raise LinkRuleError("invalid_hostname")
    if labels[-1].isdigit():
        raise LinkRuleError("invalid_hostname")
    if any(ascii_host == item or ascii_host.endswith("." + item) for item in INTERNAL_SUFFIXES):
        raise LinkRuleError("internal_hostname")
    return ascii_host


# A destination origin: HTTPS on the default port. Loopback HTTP(S) on any port is accepted only
# when development configuration explicitly allows it. No credentials, path, query, fragment.
def canonical_origin(text: str, *, allow_loopback: bool = False) -> Origin:
    if not isinstance(text, str) or len(text) > 200 or not _PRINTABLE.fullmatch(text):
        raise LinkRuleError("invalid_origin")
    if "\\" in text or "#" in text or "?" in text:
        raise LinkRuleError("invalid_origin")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as error:
        raise LinkRuleError("invalid_origin") from error
    if parts.username is not None or parts.password is not None or parts.path not in {"", "/"}:
        raise LinkRuleError("invalid_origin")
    host = parts.hostname or ""
    if allow_loopback and host in LOOPBACK_HOSTS and parts.scheme in {"http", "https"}:
        default = 443 if parts.scheme == "https" else 80
        return Origin(parts.scheme, host, None if port in {None, default} else port)
    if parts.scheme != "https":
        raise LinkRuleError("insecure_origin")
    if port not in {None, 443}:
        raise LinkRuleError("invalid_origin")
    if _is_ip(host):
        raise LinkRuleError("invalid_hostname")
    return Origin("https", canonical_hostname(host), None)


# Static query names configured for an origin: lowercase codes, not a UTM, click identifier, or
# the link parameter, and not a credential, signature, session, or person/customer identifier.
def validate_query_names(names: Iterable[str]) -> list[str]:
    result = list(names)
    if len(result) > MAX_QUERY_NAMES or len(set(result)) != len(result):
        raise LinkRuleError("invalid_query_names")
    for name in result:
        if not isinstance(name, str) or not QUERY_NAME.fullmatch(name):
            raise LinkRuleError("invalid_query_names")
        if name in UTM_PARAMETERS or name in CLICK_PARAMETERS or name == LINK_PARAMETER:
            raise LinkRuleError("reserved_query_name")
        tokens = set(name.split("_")) | {name.replace("_", "")}
        if tokens & _SENSITIVE_NAME_TOKENS or any(
            token in name for token in ("token", "secret", "passw", "email", "signature")
        ):
            raise LinkRuleError("sensitive_query_name")
    return result


def validate_code(value: str) -> str:
    if not isinstance(value, str) or not CODE.fullmatch(value) or contains_card_number(value):
        raise LinkRuleError("invalid_code")
    return value


# A UTM mapping: keys from the six existing utm_* names, values bounded codes (case kept).
def validate_utm(mapping: Mapping[str, str], *, required: bool = False) -> dict[str, str]:
    if not isinstance(mapping, Mapping) or (required and not mapping):
        raise LinkRuleError("invalid_utm")
    result: dict[str, str] = {}
    for key, value in mapping.items():
        if key not in UTM_PARAMETERS:
            raise LinkRuleError("invalid_utm")
        try:
            result[key] = validate_code(value)
        except LinkRuleError as error:
            raise LinkRuleError("invalid_utm") from error
    return dict(sorted(result.items()))


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG.fullmatch(slug) or slug in RESERVED_SLUGS:
        raise LinkRuleError("invalid_slug")
    return slug


# Split a destination URL against one registered origin and its static query names. The URL
# must be printable ASCII with well-formed, unambiguous percent-encoding, no credentials or
# fragment, an absolute path without dot segments, and only name=code query pairs whose names
# are configured static names or UTM names, each at most once. ts_link is reserved.
def _split_destination(url: str):
    if not isinstance(url, str) or len(url) > MAX_URL or not _PRINTABLE.fullmatch(url):
        raise LinkRuleError("invalid_destination")
    if "\\" in url or "#" in url or _PERCENT.search(url) or _AMBIGUOUS.search(url):
        raise LinkRuleError("invalid_destination")
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError as error:
        raise LinkRuleError("invalid_destination") from error
    if parts.username is not None or parts.password is not None or not parts.netloc:
        raise LinkRuleError("invalid_destination")
    return parts


# The canonical origin of a destination URL, used to find its registered origin.
def destination_origin(url: str, *, allow_loopback: bool = False) -> Origin:
    parts = _split_destination(url)
    return canonical_origin(f"{parts.scheme}://{parts.netloc}", allow_loopback=allow_loopback)


def parse_destination(
    url: str, origin: Origin, query_names: Iterable[str], *, allow_loopback: bool = False
) -> Destination:
    parts = _split_destination(url)
    found = canonical_origin(f"{parts.scheme}://{parts.netloc}", allow_loopback=allow_loopback)
    if found != origin:
        raise LinkRuleError("origin_not_registered")
    path = parts.path or "/"
    if not path.startswith("/") or path.startswith("//") or _DOT_SEGMENT.search(path):
        raise LinkRuleError("invalid_destination")
    if "@" in path or has_prohibited_value(path):
        raise LinkRuleError("destination_identifier")
    allowed = set(query_names)
    static: list[tuple[str, str]] = []
    utm: dict[str, str] = {}
    seen: set[str] = set()
    for segment in parts.query.split("&") if parts.query else []:
        name, separator, value = segment.partition("=")
        if not separator or not QUERY_NAME.fullmatch(name) or name in seen:
            raise LinkRuleError("invalid_destination_query")
        seen.add(name)
        if name == LINK_PARAMETER:
            raise LinkRuleError("reserved_query_name")
        if name not in allowed and name not in UTM_PARAMETERS:
            raise LinkRuleError("query_name_not_allowed")
        try:
            validate_code(value)
        except LinkRuleError as error:
            raise LinkRuleError("invalid_destination_query") from error
        if name in UTM_PARAMETERS:
            utm[name] = value
        else:
            static.append((name, value))
    return Destination(origin, path, tuple(static), utm)


# Specified precedence: explicit link values > template > UTM values already in the stored
# destination. utm_id comes from the campaign's stable public code when no input set it.
def merge_utm(
    destination: Mapping[str, str],
    template: Mapping[str, str] | None,
    explicit: Mapping[str, str] | None,
    campaign_code: str | None,
) -> dict[str, str]:
    merged = {
        **validate_utm(destination),
        **validate_utm(template or {}),
        **validate_utm(explicit or {}),
    }
    if campaign_code is not None and "utm_id" not in merged:
        merged["utm_id"] = validate_code(campaign_code)
    return dict(sorted(merged.items()))


# The issued redirect target: static pairs in destination order, then UTM pairs by name, then
# the link's stable ts_link UUID. All values are codes, so encoding never changes them. The
# prohibited-value check covers the configured part only: a random UUID's hyphen-joined digit
# groups can form a Luhn-valid number by chance, and the generated reference is not customer
# data, so checking it would refuse valid links intermittently.
def compose_target(destination: Destination, utm: Mapping[str, str], link_id: UUID) -> str:
    configured = [*destination.static, *sorted(utm.items())]
    base = f"{destination.origin.text}{destination.path}"
    if has_prohibited_value(f"{base}?{urlencode(configured)}" if configured else base):
        raise LinkRuleError("invalid_destination")
    target = f"{base}?{urlencode([*configured, (LINK_PARAMETER, str(link_id))])}"
    if len(target) > MAX_URL:
        raise LinkRuleError("invalid_destination")
    return target


# Canonical authority of a Host header: lowercase host with an optional port, or None when the
# header is missing or malformed. Forwarded-host headers are never consulted.
def request_authority(header: str | None) -> tuple[str, int | None] | None:
    if not header or len(header) > 260 or not _PRINTABLE.fullmatch(header):
        return None
    try:
        parts = urlsplit(f"//{header}")
        port = parts.port
    except ValueError:
        return None
    if parts.username is not None or parts.path or not parts.hostname:
        return None
    return parts.hostname.rstrip("."), port


# Configured platform short-link authorities ("host" or "host:port"), canonical lowercase.
def platform_authorities(hosts: Iterable[str]) -> frozenset[tuple[str, int | None]]:
    result = set()
    for host in hosts:
        authority = request_authority(host)
        if authority is None:
            raise LinkRuleError("invalid_platform_host")
        result.add(authority)
    return frozenset(result)


# True when a target origin is served by the platform itself: one of the platform short-link
# authorities (exact host and port) or a managed custom hostname (any port). Such destinations
# would create redirect loops through managed links.
def is_managed_target(
    origin: Origin,
    platform: frozenset[tuple[str, int | None]],
    custom_hostnames: Iterable[str],
) -> bool:
    default = 443 if origin.scheme == "https" else 80
    port = origin.port if origin.port is not None else default
    for host, platform_port in platform:
        if host == origin.hostname and (platform_port or default) == port:
            return True
    return origin.hostname in set(custom_hostnames)
