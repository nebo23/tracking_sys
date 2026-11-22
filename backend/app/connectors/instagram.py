"""Instagram API with Instagram Login adapter (specification 010-C, D-053, D-054, D-055).

The live adapter for Instagram professional accounts (business and creator). Every shape it
reads was observed with the owner's development app and test account in 010-B (2026-11-17;
see specs/010-instagram/evidence.md) or is documented by Meta:

- Authorization through www.instagram.com/oauth/authorize without PKCE (D3), a code exchange
  answered flat or in a "data" array, a long-lived exchange of about 60 days, and GET /me for
  the account. The connection's account reference is the app-scoped ID ("id"), which Meta's
  signed deauthorize and deletion requests name; data reads use the professional account ID
  ("user_id"). Every granted permission is recorded, including ones that were not requested.
- The long-lived token refreshes itself (refresh_mode "self"); there is no revocation endpoint.
- Streams (D6): daily account insights (the eleven D2 metrics in one total_value read per UTC
  day, up to 729 days back; the page cursor names the read's first day and the next day itself,
  so a read resumed after a UTC midnight continues with the next day instead of shifting a
  numeric offset onto a newly computed day list, review finding R011), feed posts and reels with
  lifetime insights (up to 730 days back),
  and the live stories, all re-read every run while they are live. Each media item is asked
  only for the D2/D-054 metrics of its product type, so a metric the product type does not
  offer is reported as unsupported by the catalog and never requested.
- Absent values are never zero (D7): follows_and_unfollows is "below_threshold" for accounts
  under 100 followers, and every other empty or refused metric is "not_returned".
- Limits (D8): Graph throttling codes defer the run, and so does an x-app-usage figure of 90%
  or more, before Meta throttles; the per-connection daily allocation remains the safety cap.
- Graph errors map to runtime kinds: 190 or HTTP 401 unauthorized, 10, 200-299 or HTTP 403
  forbidden, 4/17/32/613/80001/80002 or HTTP 429 rate limited, 1/2 or HTTP 5xx retryable,
  anything else permanent.
- Deauthorize and data deletion callbacks carry Meta's signed_request (HMAC-SHA256 of the
  encoded payload with the app secret), verified in constant time before the payload is read.

The adapter is registered only when it is enabled and configured and the meta.platform_data and
instagram.login_api rules in app.privacy.providers are current (see build_providers). Until
App Review and Advanced Access (010-D), Meta's development mode limits authorization to people
with a role on the app, and live use stays with owner-authorized test accounts.
"""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

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

GRAPH_VERSION = "v27.0"
AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
CODE_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
SCOPES = ("instagram_business_basic", "instagram_business_manage_insights")
TIMEOUT = 20
FOLLOWER_THRESHOLD = 100
RECENT_DAYS = 7
MEDIA_PAGE = 10
MAX_CURSOR = 512
# Meta signs a deletion request when it is made and may deliver it later; an authentic request
# is honored for a day, and a replay only repeats a disconnect that has already started.
SIGNED_REQUEST_MAX_AGE = timedelta(hours=24)
SIGNED_REQUEST_SKEW = timedelta(minutes=5)
USAGE_PAUSE = 90
THROTTLE_WAIT = 900
ACCOUNT_KINDS = {"BUSINESS": "business", "MEDIA_CREATOR": "creator", "CREATOR": "creator"}
UNAUTHORIZED_CODES = {190}
RATE_CODES = {4, 17, 32, 613, 80001, 80002}
RETRYABLE_CODES = {1, 2}

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
# D2 as amended by D-054; the 010-B answers matched it for feed posts, reels, and stories.
MEDIA_METRICS = (
    MetricSpec("reach", "count", streams=MEDIA, product_types=("FEED", "REELS", "STORY")),
    MetricSpec("views", "count", streams=MEDIA, product_types=("FEED", "REELS", "STORY")),
    MetricSpec("likes", "count", streams=("media",), product_types=FEED_REELS),
    MetricSpec("comments", "count", streams=("media",), product_types=FEED_REELS),
    MetricSpec("saved", "count", streams=("media",), product_types=FEED_REELS),
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
    provider="instagram",
    version=f"instagram-login-{GRAPH_VERSION}",
    pkce=None,
    refresh=True,
    revocation_scope="unsupported",
    scopes=SCOPES,
    metrics=ACCOUNT_METRICS + MEDIA_METRICS,
    stream="account",
    history_days=729,
    overlap_days=2,
    # One unit is one page: one account day, one media page with its items' insights, or the
    # live stories with theirs. Meta has no fixed daily quota for this API (D8).
    cost_unit="page",
    daily_quota=None,
    freshness_hours=24,
    webhooks=False,
    refresh_mode="self",
    refresh_min_age_hours=24,
    refresh_before_days=7,
    streams=(
        StreamSpec("account", None, history_days=729, overlap_days=2),
        StreamSpec("media", None, history_days=730, overlap_days=2),
        StreamSpec("stories", 2, history_days=1, overlap_days=0),
    ),
    data_delay_hours=48,
    signed_requests=True,
)
DAY_CURSOR = "day:"


# An account-stream position (R011): "day:<first day>:<next day>", both ISO dates. The first day
# stays fixed for the whole read and is the start of its gapless coverage; the next day is the
# absolute day the next page reads.
def day_cursor(first: datetime, following: datetime) -> str:
    return f"{DAY_CURSOR}{first.date().isoformat()}:{following.date().isoformat()}"


def parse_day_cursor(cursor: str) -> tuple[datetime, datetime]:
    parts = cursor.removeprefix(DAY_CURSOR).split(":") if cursor.startswith(DAY_CURSOR) else []
    days = []
    for part in parts:
        try:
            day = date.fromisoformat(part)
        except ValueError:
            break
        if day.isoformat() == part:
            days.append(datetime(day.year, day.month, day.day, tzinfo=UTC))
    if len(parts) != 2 or len(days) != 2 or days[1] < days[0]:
        raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
    return days[0], days[1]


@dataclass
class Reply:
    status: int
    body: Any
    headers: Mapping[str, str] = field(default_factory=dict)


# Send one request. A network failure is a retryable provider error that carries neither the
# URL, which can hold a token, nor any provider message. Header names are lower-cased.
def http_send(method: str, url: str, form: Mapping[str, str] | None = None) -> Reply:
    data = None if form is None else urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(url, data=data, method=method)
    if form is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status, raw, headers = response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        status, raw, headers = error.code, error.read(), dict(error.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError(ErrorKind.RETRYABLE, "network") from None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = {}
    return Reply(status, body, {name.lower(): value for name, value in headers.items()})


Transport = Callable[[str, str, Mapping[str, str] | None], Reply]


def _error(reply: Reply) -> ProviderError:
    error = reply.body.get("error") if isinstance(reply.body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if reply.status == 401 or code in UNAUTHORIZED_CODES:
        return ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")
    if code in RATE_CODES or reply.status == 429:
        return ProviderError(ErrorKind.RATE_LIMITED, "rate_limited", THROTTLE_WAIT)
    if code == 10 or (isinstance(code, int) and 200 <= code <= 299) or reply.status == 403:
        return ProviderError(ErrorKind.FORBIDDEN, "permission")
    if reply.status >= 500 or code in RETRYABLE_CODES:
        return ProviderError(ErrorKind.RETRYABLE, "unavailable")
    named = isinstance(code, int) and not isinstance(code, bool)
    return ProviderError(ErrorKind.PERMANENT, f"graph_{code}" if named else "bad_request")


# The largest percentage in Meta's x-app-usage header, or None when it is absent or unreadable.
def app_usage(headers: Mapping[str, str]) -> float | None:
    try:
        data = json.loads(headers.get("x-app-usage", ""))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    figures = [
        value
        for value in data.values()
        if isinstance(value, int | float) and not isinstance(value, bool)
    ]
    return max(figures) if figures else None


# A flat answer, or the first element of the "data" array some Instagram answers use.
def _flat(body: Any) -> dict[str, Any]:
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        first = body["data"][0] if body["data"] else {}
        return first if isinstance(first, dict) else {}
    return body if isinstance(body, dict) else {}


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _day(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(UTC)
    except ValueError:
        return None


class InstagramProvider:
    capability = CAPABILITY

    # transport None sends real requests through http_send, looked up when each call is made.
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._app_id, self._app_secret = app_id, app_secret
        self._transport, self._clock = transport, clock

    def __repr__(self) -> str:
        return "InstagramProvider()"

    def _send(self, method: str, url: str, form: Mapping[str, str] | None = None) -> Reply:
        return (self._transport or http_send)(method, url, form)

    # One Graph read. A refused read raises its mapped error; an answered read whose app usage
    # reached USAGE_PAUSE percent defers the run before Meta starts throttling.
    def _get(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        reply = self._send("GET", f"{GRAPH}/{GRAPH_VERSION}/{path}?{query}")
        if reply.status >= 400 or not isinstance(reply.body, dict):
            raise _error(reply)
        usage = app_usage(reply.headers)
        if usage is not None and usage >= USAGE_PAUSE:
            raise ProviderError(ErrorKind.RATE_LIMITED, "app_usage", THROTTLE_WAIT)
        return reply.body

    # --- authorization ----------------------------------------------------------------------

    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None,
        redirect_uri: str,
        scopes: tuple[str, ...],
    ) -> str:
        query = {
            "client_id": self._app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(scopes),
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"

    def exchange(self, *, code: str, code_verifier: str | None, redirect_uri: str) -> TokenGrant:
        reply = self._send(
            "POST",
            CODE_URL,
            {
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code.removesuffix("#_"),
            },
        )
        payload = _flat(reply.body)
        short = payload.get("access_token")
        if reply.status >= 400 or not isinstance(short, str) or not short:
            error = _error(reply)
            if error.kind in {ErrorKind.UNAUTHORIZED, ErrorKind.FORBIDDEN, ErrorKind.PERMANENT}:
                error = ProviderError(ErrorKind.PERMANENT, "invalid_grant")
            raise error
        permissions = payload.get("permissions") or []
        if isinstance(permissions, str):
            permissions = permissions.split(",")
        if not isinstance(permissions, list):
            permissions = []
        scopes = tuple(sorted({str(item).strip() for item in permissions if str(item).strip()}))
        long_lived = self._send(
            "GET",
            f"{GRAPH}/access_token?"
            + urllib.parse.urlencode(
                {
                    "grant_type": "ig_exchange_token",
                    "client_secret": self._app_secret,
                    "access_token": short,
                }
            ),
        )
        body = long_lived.body if isinstance(long_lived.body, dict) else {}
        token = body.get("access_token")
        if long_lived.status >= 400 or not isinstance(token, str) or not token:
            raise _error(long_lived)
        expires = self._expiry(body)
        profile = _flat(
            self._get("me", {"fields": "id,user_id,username,account_type", "access_token": token})
        )
        account = profile.get("id")
        if isinstance(account, bool) or not isinstance(account, int | str):
            raise ProviderError(ErrorKind.PERMANENT, "no_account")
        if not 1 <= len(str(account)) <= 128:
            raise ProviderError(ErrorKind.PERMANENT, "no_account")
        username = profile.get("username")
        return TokenGrant(
            token,
            None,
            expires,
            scopes,
            str(account),
            username[:200] if isinstance(username, str) else None,
            ACCOUNT_KINDS.get(str(profile.get("account_type"))),
        )

    def _expiry(self, body: Mapping[str, Any]) -> datetime | None:
        seconds = body.get("expires_in")
        if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
            return self._clock() + timedelta(seconds=seconds)
        return None

    # The long-lived access token refreshes itself; the answer names no account or scopes, which
    # the runtime keeps from the connection.
    def refresh(self, refresh_token: str) -> TokenGrant:
        reply = self._send(
            "GET",
            f"{GRAPH}/refresh_access_token?"
            + urllib.parse.urlencode(
                {"grant_type": "ig_refresh_token", "access_token": refresh_token}
            ),
        )
        body = reply.body if isinstance(reply.body, dict) else {}
        token = body.get("access_token")
        if reply.status >= 400 or not isinstance(token, str) or not token:
            error = _error(reply)
            if error.kind is ErrorKind.PERMANENT:
                error = ProviderError(ErrorKind.UNAUTHORIZED, "invalid_grant")
            raise error
        return TokenGrant(token, None, self._expiry(body), (), "", None, None)

    # Meta documents no revocation endpoint for Instagram Login; the account owner removes the
    # app in Instagram's settings, which reaches the runtime through the deauthorize callback.
    def revoke(self, token: str, kind: str) -> RevocationOutcome:
        return "unsupported"

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, now: datetime
    ) -> WebhookDelivery:
        raise WebhookRejected("signature_invalid")

    # Meta's signed_request: base64url(HMAC-SHA256(app secret, encoded payload)).payload, with
    # the app-scoped user_id, the algorithm, and the issue time.
    def verify_signed_request(self, signed_request: str, now: datetime) -> SignedRequest:
        signature_part, _, payload_part = signed_request.partition(".")
        try:
            signature = _b64url_decode(signature_part)
        except (ValueError, TypeError):
            raise WebhookRejected("signature_invalid") from None
        expected = hmac.new(
            self._app_secret.encode(), payload_part.encode(), hashlib.sha256
        ).digest()
        if not self._app_secret or not payload_part or not hmac.compare_digest(signature, expected):
            raise WebhookRejected("signature_invalid")
        try:
            data = json.loads(_b64url_decode(payload_part))
            algorithm, issued, account = data["algorithm"], data["issued_at"], data["user_id"]
        except (ValueError, TypeError, KeyError):
            raise WebhookRejected("invalid_delivery") from None
        if (
            not isinstance(algorithm, str)
            or algorithm.upper() != "HMAC-SHA256"
            or isinstance(issued, bool)
            or not isinstance(issued, int)
            or isinstance(account, bool)
            or not isinstance(account, int | str)
            or not 1 <= len(str(account)) <= 128
        ):
            raise WebhookRejected("invalid_delivery")
        try:
            issued_at = datetime.fromtimestamp(issued, UTC)
        except (OverflowError, OSError, ValueError):
            raise WebhookRejected("invalid_delivery") from None
        if issued_at > now + SIGNED_REQUEST_SKEW or now - issued_at > SIGNED_REQUEST_MAX_AGE:
            raise WebhookRejected("signature_expired")
        return SignedRequest(str(account), issued_at)

    # --- reads ------------------------------------------------------------------------------

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
        now = self._clock()
        profile = _flat(
            self._get("me", {"fields": "user_id,followers_count", "access_token": access_token})
        )
        user = profile.get("user_id")
        if isinstance(user, bool) or not isinstance(user, int | str) or not str(user).isdigit():
            raise ProviderError(ErrorKind.PERMANENT, "no_account")
        oldest = now - timedelta(days=spec.history_days)
        end = min(until or now, now)
        if stream == "stories":
            # Stories are served only while they are live: every read covers the last day and
            # refreshes the values of each live story.
            return self._stories_page(access_token, str(user), oldest, end)
        start = max(since or now - timedelta(days=RECENT_DAYS), oldest)
        if stream == "account":
            followers = profile.get("followers_count")
            below = isinstance(followers, int) and followers < FOLLOWER_THRESHOLD
            return self._account_page(access_token, str(user), below, cursor, start, end, now)
        return self._media_page(access_token, str(user), cursor, start, end)

    # One complete UTC day per page, up to the start of the current day, with all account
    # metrics in one total_value read. The first page fixes the read's first day (the day of
    # `start`, never before the history limit); the cursor then carries that first day and the
    # absolute next day (R011). The history limit is recomputed from `now` on every page, so it
    # moves forward at each UTC midnight: the next day is still read when it is within the
    # limit, and when a long deferral has left it behind the limit, those days can no longer be
    # read and the read's gapless coverage restarts at the limit (covered_from), instead of
    # claiming days it never read. The end follows the latest complete day.
    def _account_page(
        self,
        token: str,
        user: str,
        below: bool,
        cursor: str | None,
        start: datetime,
        end: datetime,
        now: datetime,
    ) -> ProviderPage:
        oldest = _day(now - timedelta(days=self.capability.stream_spec("account").history_days))
        last = min(_day(end), _day(now))
        if cursor is None:
            first = day = _day(start)
        else:
            first, day = parse_day_cursor(cursor)
            if day < oldest:
                first = day = oldest
        if day >= last:
            return ProviderPage((), None, first, max(first, last))
        names = [spec.name for spec in self.capability.stream_metrics("account")]
        window = {
            "period": "day",
            "metric_type": "total_value",
            "since": str(int(day.timestamp())),
            "until": str(int((day + timedelta(days=1)).timestamp())),
            "access_token": token,
        }
        values, _ = self._metrics(f"{user}/insights", names, window)
        unavailable = {
            name: (
                "below_threshold" if below and name == "follows_and_unfollows" else "not_returned"
            )
            for name in names
            if name not in values
        }
        record = ProviderRecord(f"day-{day.date().isoformat()}", day, values, None, unavailable)
        after = day + timedelta(days=1)
        following = day_cursor(first, after) if after < last else None
        return ProviderPage((record,), following, first, last)

    # The values of the named metrics, and whether the combined read was refused. A refused
    # combined read is repeated metric by metric, and a refused metric is simply absent.
    def _metrics(
        self, path: str, names: list[str], params: Mapping[str, str]
    ) -> tuple[dict[str, int | float], bool]:
        try:
            return self._values(self._get(path, {**params, "metric": ",".join(names)})), False
        except ProviderError as error:
            if error.kind is not ErrorKind.PERMANENT or len(names) == 1:
                raise
        values: dict[str, int | float] = {}
        for name in names:
            try:
                values |= self._values(self._get(path, {**params, "metric": name}))
            except ProviderError as error:
                if error.kind is not ErrorKind.PERMANENT:
                    raise
        return values, True

    @staticmethod
    def _values(body: Mapping[str, Any]) -> dict[str, int | float]:
        values: dict[str, int | float] = {}
        entries = body.get("data")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            if isinstance(entry.get("total_value"), dict):
                value = entry["total_value"].get("value")
            else:
                points = entry.get("values")
                last = points[-1] if isinstance(points, list) and points else None
                value = last.get("value") if isinstance(last, dict) else None
            if isinstance(value, int | float) and not isinstance(value, bool):
                values[entry["name"]] = value
        return values

    # One media item with the lifetime insights of its product type. An item whose insights are
    # all refused (deleted meanwhile, or posted before the account became professional) is left
    # out of the page.
    def _item(
        self, token: str, item: Mapping[str, Any], product: str, stream: str
    ) -> ProviderRecord | None:
        observed = _timestamp(item.get("timestamp"))
        object_id = str(item.get("id", ""))
        if observed is None or not object_id.isdigit() or len(object_id) > 128:
            return None
        names = [
            spec.name
            for spec in self.capability.stream_metrics(stream)
            if spec.product_types is None or product in spec.product_types
        ]
        try:
            values, refused = self._metrics(f"{object_id}/insights", names, {"access_token": token})
        except ProviderError as error:
            if error.kind is ErrorKind.PERMANENT:
                return None
            raise
        if refused and not values:
            return None
        unavailable = {name: "not_returned" for name in names if name not in values}
        return ProviderRecord(object_id, observed, values, product, unavailable)

    # Feed posts and reels, newest first, MEDIA_PAGE per page with each item's lifetime
    # insights; paging stops at the first item older than the window.
    def _media_page(
        self, token: str, user: str, cursor: str | None, start: datetime, end: datetime
    ) -> ProviderPage:
        params = {
            "fields": "id,media_type,media_product_type,timestamp",
            "limit": str(MEDIA_PAGE),
            "access_token": token,
        }
        if cursor is not None:
            params["after"] = cursor
        body = self._get(f"{user}/media", params)
        records = []
        older = False
        items = body.get("data")
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            observed = _timestamp(item.get("timestamp"))
            if observed is None:
                continue
            if observed < start:
                older = True
                break
            product = item.get("media_product_type")
            if observed >= end or product not in FEED_REELS:
                continue
            record = self._item(token, item, product, "media")
            if record is not None:
                records.append(record)
        paging = body.get("paging") if isinstance(body.get("paging"), dict) else {}
        cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
        after = cursors.get("after") if paging.get("next") else None
        following = None
        if not older and isinstance(after, str) and after:
            if len(after) > MAX_CURSOR:
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
            following = after
        return ProviderPage(tuple(records), following, start, end)

    def _stories_page(self, token: str, user: str, start: datetime, end: datetime) -> ProviderPage:
        body = self._get(
            f"{user}/stories", {"fields": "id,media_type,timestamp", "access_token": token}
        )
        records = []
        items = body.get("data")
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            observed = _timestamp(item.get("timestamp"))
            if observed is None or not start <= observed < end:
                continue
            record = self._item(token, item, "STORY", "stories")
            if record is not None:
                records.append(record)
        return ProviderPage(tuple(records), None, start, end)


__all__ = ["CAPABILITY", "InstagramProvider", "Reply", "app_usage", "http_send"]
