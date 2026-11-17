"""Instagram-shaped synthetic provider for local development and tests (specification 010-A, D-053).

It reproduces the shapes the official Meta documentation describes for the Instagram API with
Instagram Login (entry review section 1), never the live service: business and creator
accounts, no PKCE, one long-lived access token of 60 days that the provider refreshes itself
(no refresh token), no revocation endpoint, three streams (daily account insights, feed and
reels media with lifetime insights, and stories), metrics that differ by media product type,
empty data and minimum-audience thresholds instead of zero values, and Meta-style signed
requests for the deauthorize and data deletion callbacks. Metric names are the provisional D2
catalog; the feasibility check of 010-B confirms them against a real test account.

State lives in its own SQLite file, shared by the API and the worker, through the storage of
the 009 synthetic provider. The data set is deterministic and anchored at a fixed date, so no
result depends on the wall clock. Behaviors set through set_behavior are test controls.
"""

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from app.connectors.contracts import (
    Capability,
    ErrorKind,
    MetricSpec,
    ProviderError,
    ProviderPage,
    ProviderRecord,
    RevocationOutcome,
    SignedRequest,
    StreamSpec,
    TokenGrant,
    WebhookDelivery,
    WebhookRejected,
)
from app.connectors.synthetic import (
    ACCOUNT_KINDS,
    CODE_SECONDS,
    FETCH_OUTCOMES,
    OBSERVED_AT,
    SyntheticProvider,
    _digest,
    _now,
)

AUTHORIZE_URL = "https://synthetic-instagram.invalid/oauth/authorize"
DAY = timedelta(days=1)
LONG_LIVED_SECONDS = 60 * 24 * 3600
CURSOR_PREFIX = "sig_cursor_"
# A signed request older than this, or issued in the future beyond the skew, is refused.
SIGNED_REQUEST_MAX_AGE = timedelta(hours=1)
SIGNED_REQUEST_SKEW = timedelta(minutes=5)
FOLLOWER_THRESHOLD = 100
STORY_VIEWER_THRESHOLD = 5

FEED_REELS = ("FEED", "REELS")
MEDIA = ("media", "stories")
ACCOUNT_METRICS = tuple(
    MetricSpec(name, "count", streams=("account",))
    for name in (
        "reach",
        "views",
        "accounts_engaged",
        "total_interactions",
        "likes",
        "comments",
        "shares",
        "saves",
        "replies",
        "follows_and_unfollows",
        "profile_links_taps",
    )
)
MEDIA_METRICS = (
    MetricSpec("reach", "count", streams=MEDIA, product_types=("FEED", "REELS", "STORY")),
    MetricSpec("views", "count", streams=MEDIA, product_types=("FEED", "REELS", "STORY")),
    MetricSpec("likes", "count", streams=("media",), product_types=FEED_REELS),
    MetricSpec("comments", "count", streams=("media",), product_types=FEED_REELS),
    MetricSpec("saved", "count", streams=("media",), product_types=FEED_REELS),
    # D-054: stories also report shares, interactions, profile visits and follows.
    MetricSpec("shares", "count", streams=MEDIA, product_types=("FEED", "REELS", "STORY")),
    MetricSpec(
        "total_interactions", "count", streams=MEDIA, product_types=("FEED", "REELS", "STORY")
    ),
    MetricSpec("profile_visits", "count", streams=MEDIA, product_types=("FEED", "STORY")),
    MetricSpec("follows", "count", streams=MEDIA, product_types=("FEED", "STORY")),
    MetricSpec(
        "ig_reels_avg_watch_time", "milliseconds", streams=("media",), product_types=("REELS",)
    ),
    MetricSpec(
        "ig_reels_video_view_total_time",
        "milliseconds",
        streams=("media",),
        product_types=("REELS",),
    ),
    MetricSpec("reels_skip_rate", "percent", streams=("media",), product_types=("REELS",)),
    MetricSpec("replies", "count", streams=("stories",), product_types=("STORY",)),
    MetricSpec("navigation", "count", streams=("stories",), product_types=("STORY",)),
)
CAPABILITY = Capability(
    provider="synthetic_instagram",
    version="synthetic-instagram-2",
    pkce=None,
    refresh=True,
    revocation_scope="unsupported",
    scopes=("instagram_business_basic", "instagram_business_manage_insights"),
    metrics=ACCOUNT_METRICS + MEDIA_METRICS,
    stream="account",
    cost_unit="synthetic_call",
    daily_quota=None,
    freshness_hours=24,
    refresh_mode="self",
    refresh_min_age_hours=24,
    refresh_before_days=7,
    streams=(
        StreamSpec("account", None, history_days=30, overlap_days=2),
        StreamSpec("media", None, history_days=730, overlap_days=2),
        StreamSpec("stories", 2, history_days=1, overlap_days=0),
    ),
    data_delay_hours=48,
    signed_requests=True,
)
NUMBERS = {
    "access_ttl": 0,
    "days": 0,
    "media": 0,
    "stories": 0,
    "page_size": 1,
    "recent_days": 1,
    "retry_after": 0,
    "followers": 0,
    "story_viewers": 0,
}
DEFAULTS = {
    "access_ttl": LONG_LIVED_SECONDS,
    "days": 3,
    "media": 4,
    "stories": 2,
    "page_size": 100,
    "recent_days": 3,
    "retry_after": 60,
    "followers": 250,
    "story_viewers": 40,
}
BEHAVIORS = {
    "exchange": {"ok", "retryable"},
    "refresh": {"ok", "invalid_grant", "retryable"},
    "fetch": FETCH_OUTCOMES,
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SyntheticInstagramProvider(SyntheticProvider):
    capability = CAPABILITY

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO behaviors (name, value) VALUES ('app_secret', ?)",
                (secrets.token_urlsafe(32),),
            )

    def __repr__(self) -> str:
        return "SyntheticInstagramProvider()"

    def _number(self, connection: sqlite3.Connection, name: str) -> int:
        row = connection.execute("SELECT value FROM behaviors WHERE name = ?", (name,)).fetchone()
        return int(row[0]) if row else DEFAULTS[name]

    def _ttl(self, connection: sqlite3.Connection) -> int:
        return self._number(connection, "access_ttl")

    # Test control: numbers of NUMBERS ("access_ttl" seconds, data set sizes, "followers" and
    # "story_viewers" for the thresholds), "omit_metric" (a metric name reported as empty data,
    # or ""), "fetch_script" as for the 009 provider, or a failure mode of BEHAVIORS.
    def set_behavior(self, name: str, value: str) -> None:
        if name in NUMBERS:
            if int(value) < NUMBERS[name]:
                raise ValueError("Synthetic number out of range.")
        elif name == "omit_metric":
            if value and value not in {spec.name for spec in self.capability.metrics}:
                raise ValueError("Unknown synthetic metric.")
        elif name == "fetch_script":
            for item in filter(None, value.split(",")):
                outcome, _, seconds = item.partition(":")
                if outcome not in FETCH_OUTCOMES or (seconds and not seconds.isdigit()):
                    raise ValueError("Unknown synthetic read outcome.")
        elif value not in BEHAVIORS.get(name, set()):
            raise ValueError("Unknown synthetic behavior.")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO behaviors (name, value) VALUES (?, ?) "
                "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                (name, value),
            )

    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None,
        redirect_uri: str,
        scopes: tuple[str, ...],
    ) -> str:
        query = {
            "response_type": "code",
            "client_id": "tracking-synthetic-instagram",
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    # Stand-in for Instagram's consent page: approve for one professional account.
    def approve(
        self,
        authorization_url: str,
        account: str,
        label: str | None = None,
        kind: str = "business",
    ) -> str:
        if kind not in ACCOUNT_KINDS:
            raise ValueError("Unknown synthetic account kind.")
        parts = urlsplit(authorization_url)
        if f"{parts.scheme}://{parts.netloc}{parts.path}" != AUTHORIZE_URL:
            raise ValueError("Not a synthetic Instagram authorization URL.")
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if "code_challenge" in query:
            raise ValueError("The synthetic Instagram provider offers no PKCE.")
        code = "sig_code_" + secrets.token_urlsafe(24)
        expires = (_now() + timedelta(seconds=CODE_SECONDS)).isoformat()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO codes (digest, challenge, redirect_uri, scopes, account, label, "
                "kind, expires_at) VALUES (?, '', ?, ?, ?, ?, ?, ?)",
                (
                    _digest(code),
                    query.get("redirect_uri", ""),
                    query.get("scope", "").replace(",", " "),
                    account,
                    label,
                    kind,
                    expires,
                ),
            )
        return code

    def exchange(self, *, code: str, code_verifier: str | None, redirect_uri: str) -> TokenGrant:
        error: ProviderError | None = None
        with self._transaction() as connection:
            if self._behavior(connection, "exchange") == "retryable":
                self._call(connection, "exchange", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "unavailable")
            else:
                row = connection.execute(
                    "SELECT redirect_uri, scopes, account, label, expires_at, used, kind "
                    "FROM codes WHERE digest = ?",
                    (_digest(code),),
                ).fetchone()
                valid = (
                    row is not None
                    and not row[5]
                    and datetime.fromisoformat(row[4]) > _now()
                    and row[0] == redirect_uri
                    and code_verifier is None
                )
                connection.execute("UPDATE codes SET used = 1 WHERE digest = ?", (_digest(code),))
                if not valid:
                    self._call(connection, "exchange", "invalid_grant")
                    error = ProviderError(ErrorKind.PERMANENT, "invalid_grant")
                else:
                    grant_id = connection.execute(
                        "INSERT INTO grants (account, label, kind, scopes) VALUES (?, ?, ?, ?)",
                        (row[2], row[3], row[6], row[1]),
                    ).lastrowid
                    access, expires = self._issue(
                        connection, grant_id, "access_token", self._ttl(connection)
                    )
                    self._call(connection, "exchange", "ok")
        if error is not None:
            raise error
        return TokenGrant(access, None, expires, tuple(row[1].split()), row[2], row[3], row[6])

    # Refresh the long-lived access token itself: an unexpired token of an unrevoked grant
    # yields a new token with a fresh lifetime. The previous token stays valid until its own
    # expiry, as the provider documents no revocation.
    def refresh(self, refresh_token: str) -> TokenGrant:
        error: ProviderError | None = None
        with self._transaction() as connection:
            behavior = self._behavior(connection, "refresh")
            found = self._grant(connection, refresh_token, "access_token")
            expired = (
                found is not None
                and found[2] is not None
                and datetime.fromisoformat(found[2]) <= _now()
            )
            if behavior == "retryable":
                self._call(connection, "refresh", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "unavailable")
            elif found is None or found[1] or expired or behavior == "invalid_grant":
                self._call(connection, "refresh", "invalid_grant")
                error = ProviderError(ErrorKind.UNAUTHORIZED, "invalid_grant")
            else:
                account, label, scopes, kind = connection.execute(
                    "SELECT account, label, scopes, kind FROM grants WHERE id = ?", (found[0],)
                ).fetchone()
                access, expires = self._issue(
                    connection, found[0], "access_token", self._ttl(connection)
                )
                self._call(connection, "refresh", "ok")
        if error is not None:
            raise error
        return TokenGrant(access, None, expires, tuple(scopes.split()), account, label, kind)

    # No revocation endpoint is documented; the owner removes access in Instagram's settings.
    def revoke(self, token: str, kind: str) -> RevocationOutcome:
        with self._transaction() as connection:
            self._call(connection, "revoke", "unsupported")
        return "unsupported"

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, now: datetime
    ) -> WebhookDelivery:
        raise WebhookRejected("signature_invalid")

    def _app_secret(self) -> str:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT value FROM behaviors WHERE name = 'app_secret'"
            ).fetchone()
        return row[0]

    # Test control standing in for Meta: a signed_request naming an account.
    def sign_request(self, account: str, issued_at: datetime, *, secret: str | None = None) -> str:
        payload = json.dumps(
            {
                "algorithm": "HMAC-SHA256",
                "issued_at": int(issued_at.timestamp()),
                "user_id": account,
            }
        ).encode()
        encoded = _b64url(payload)
        key = (secret or self._app_secret()).encode()
        signature = hmac.new(key, encoded.encode(), hashlib.sha256).digest()
        return f"{_b64url(signature)}.{encoded}"

    # Verify a signed_request: HMAC-SHA256 with the app secret over the encoded payload,
    # compared in constant time before the payload is read, then the declared algorithm, a
    # bounded issue time and the account ID.
    def verify_signed_request(self, signed_request: str, now: datetime) -> SignedRequest:
        signature_part, _, payload_part = signed_request.partition(".")
        try:
            signature = _unb64url(signature_part)
        except (ValueError, TypeError):
            raise WebhookRejected("signature_invalid") from None
        expected = hmac.new(
            self._app_secret().encode(), payload_part.encode(), hashlib.sha256
        ).digest()
        if not payload_part or not hmac.compare_digest(signature, expected):
            raise WebhookRejected("signature_invalid")
        try:
            data = json.loads(_unb64url(payload_part))
            algorithm, issued, account = data["algorithm"], data["issued_at"], data["user_id"]
        except (ValueError, TypeError, KeyError):
            raise WebhookRejected("invalid_delivery") from None
        if (
            algorithm != "HMAC-SHA256"
            or not isinstance(issued, int)
            or not isinstance(account, str)
            or not 1 <= len(account) <= 128
        ):
            raise WebhookRejected("invalid_delivery")
        issued_at = datetime.fromtimestamp(issued, UTC)
        if issued_at > now + SIGNED_REQUEST_SKEW or now - issued_at > SIGNED_REQUEST_MAX_AGE:
            raise WebhookRejected("signature_expired")
        return SignedRequest(account, issued_at)

    # The deterministic objects of a stream: (object ID, observed time, product type, metrics,
    # unavailable reasons).
    def _objects(
        self, connection: sqlite3.Connection, stream: str, account: str
    ) -> list[tuple[str, datetime, str | None, dict[str, int | float], dict[str, str]]]:
        omit = self._behavior(connection, "omit_metric")
        omit = "" if omit == "ok" else omit
        items: list[tuple[str, datetime, str | None, dict[str, int | float], dict[str, str]]] = []
        if stream == "account":
            followers = self._number(connection, "followers")
            for index in range(1, self._number(connection, "days") + 1):
                observed = OBSERVED_AT - (index - 1) * DAY
                metrics: dict[str, int | float] = {
                    spec.name: (position + 1) * 10 * index
                    for position, spec in enumerate(ACCOUNT_METRICS)
                }
                unavailable: dict[str, str] = {}
                if followers < FOLLOWER_THRESHOLD:
                    metrics.pop("follows_and_unfollows")
                    unavailable["follows_and_unfollows"] = "below_threshold"
                if omit in metrics:
                    metrics.pop(omit)
                    unavailable[omit] = "not_returned"
                day = observed.date().isoformat()
                items.append((f"{account}-day-{day}", observed, None, metrics, unavailable))
        elif stream == "media":
            for index in range(1, self._number(connection, "media") + 1):
                product = "REELS" if index % 2 == 0 else "FEED"
                metrics = {
                    spec.name: 7 * index + position
                    for position, spec in enumerate(MEDIA_METRICS)
                    if "media" in (spec.streams or ()) and product in (spec.product_types or ())
                }
                unavailable = {}
                if omit in metrics:
                    metrics.pop(omit)
                    unavailable[omit] = "not_returned"
                observed = OBSERVED_AT - (index - 1) * DAY
                items.append((f"{account}-media-{index}", observed, product, metrics, unavailable))
        elif stream == "stories":
            viewers = self._number(connection, "story_viewers")
            for index in range(1, self._number(connection, "stories") + 1):
                # Stories live within the anchor day, every 3 hours back from 20:00.
                observed = OBSERVED_AT + timedelta(hours=20) - (index - 1) * timedelta(hours=3)
                names = [
                    spec.name
                    for spec in MEDIA_METRICS
                    if "stories" in (spec.streams or ()) and "STORY" in (spec.product_types or ())
                ]
                if viewers < STORY_VIEWER_THRESHOLD:
                    metrics, unavailable = {}, dict.fromkeys(names, "below_threshold")
                else:
                    metrics = {name: viewers + position for position, name in enumerate(names)}
                    unavailable = {}
                    if omit in metrics:
                        metrics.pop(omit)
                        unavailable[omit] = "not_returned"
                items.append((f"{account}-story-{index}", observed, "STORY", metrics, unavailable))
        else:
            raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")
        return items

    def fetch_page(
        self,
        access_token: str,
        *,
        stream: str = "account",
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ProviderPage:
        spec = self.capability.stream_spec(stream)
        if spec is None:
            raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")
        offset = 0
        if cursor is not None:
            digits = cursor.removeprefix(CURSOR_PREFIX)
            if not cursor.startswith(CURSOR_PREFIX) or not digits.isdigit():
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
            offset = int(digits)
        error: ProviderError | None = None
        with self._transaction() as connection:
            behavior, retry_after = self._read_outcome(connection)
            found = self._grant(connection, access_token, "access_token")
            expired = (
                found is not None
                and found[2] is not None
                and datetime.fromisoformat(found[2]) <= _now()
            )
            detail = f"{stream}:{offset}"
            if behavior == "retryable":
                self._call(connection, "fetch", "retryable", detail)
                error = ProviderError(ErrorKind.RETRYABLE, "unavailable")
            elif behavior == "rate_limited":
                self._call(connection, "fetch", "rate_limited", detail)
                seconds = self._number(connection, "retry_after")
                error = ProviderError(
                    ErrorKind.RATE_LIMITED,
                    "too_many_calls",
                    seconds if retry_after is None else retry_after,
                )
            elif behavior == "permanent":
                self._call(connection, "fetch", "permanent", detail)
                error = ProviderError(ErrorKind.PERMANENT, "bad_request")
            elif found is None or found[1] or expired or behavior == "unauthorized":
                self._call(connection, "fetch", "unauthorized", detail)
                error = ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")
            elif behavior == "forbidden":
                self._call(connection, "fetch", "forbidden", detail)
                error = ProviderError(ErrorKind.FORBIDDEN, "missing_permission")
            else:
                account = connection.execute(
                    "SELECT account FROM grants WHERE id = ?", (found[0],)
                ).fetchone()[0]
                newest = OBSERVED_AT + DAY
                end = newest if until is None else min(until, newest)
                recent = self._number(connection, "recent_days")
                start = newest - recent * DAY if since is None else since
                start = max(start, newest - spec.history_days * DAY)
                size = self._number(connection, "page_size")
                items = [
                    item
                    for item in self._objects(connection, stream, account)
                    if start <= item[1] < end
                ]
                self._call(connection, "fetch", "ok", detail)
        if error is not None:
            raise error
        records = tuple(
            ProviderRecord(object_id, observed, metrics, product, unavailable)
            for object_id, observed, product, metrics, unavailable in items[offset : offset + size]
        )
        following = offset + size
        return ProviderPage(
            records,
            f"{CURSOR_PREFIX}{following}" if following < len(items) else None,
            start,
            end,
        )

    # Test inspection: (stream:offset, outcome) of each read in order.
    def stream_reads(self) -> list[tuple[str, str]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT detail, outcome FROM calls WHERE operation = 'fetch' ORDER BY seq"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]


__all__ = ["CAPABILITY", "SyntheticInstagramProvider"]
