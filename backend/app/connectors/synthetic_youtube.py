"""YouTube-shaped synthetic provider for local development and tests (specification 011-A).

It reproduces the shapes that the official Google documentation and the 011-B feasibility
evidence describe for the YouTube Data API v3 and the YouTube Analytics API, never the live
service:

- Authorization: the Google web server flow with offline access, consent on every connect and
  PKCE S256, which the Web client enforces (F2).
- Tokens: one-hour access tokens and a refresh token that is never rotated and expires 7 days
  after the consent while the project is in Testing (F1, F3).
- Revocation (G-1): revoking any token revokes every grant of the account.
- Partial consent: only the approved scopes are granted, together with any scope a live grant
  of the same account already holds (F1).
- Channels: one channel per account; an account with none or several is refused (F4).
- Data: Pacific days with 72-hour completeness and sparse day rows (F8, D-060), read with a
  cursor that keeps the read's first day (R011-15), an inventory of private, unlisted and
  public uploads served 50 per page (F5), and lowerCamelCase creatorContentType values (F9).
- Errors: the documented error kinds, including quotaExceeded (F14, YT-5).

State lives in its own SQLite file, shared by the API and the worker, through the storage of
the 009 synthetic provider. The data set is deterministic and placed by a test-controlled
clock, so no result depends on the wall clock; token lifetimes use the real clock. Behaviors
set through set_behavior are test controls.
"""

import secrets
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from app.connectors.contracts import (
    Capability,
    ErrorKind,
    MetricSpec,
    ProviderError,
    ProviderPage,
    ProviderRecord,
    QuotaBucket,
    RevocationOutcome,
    SignedRequest,
    StreamSpec,
    TokenGrant,
    WebhookDelivery,
    WebhookRejected,
)
from app.connectors.synthetic import CODE_SECONDS, FETCH_OUTCOMES, SyntheticProvider, _digest, _now
from app.connectors.synthetic import s256 as _s256

AUTHORIZE_URL = "https://synthetic-youtube.invalid/o/oauth2/v2/auth"
DATA_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
PACIFIC = "America/Los_Angeles"
ZONE = ZoneInfo(PACIFIC)
DATA, ANALYTICS = "youtube_data", "youtube_analytics"
DAY = timedelta(days=1)
# Documented latency (YT-12) and the D-060 completeness rule: a day is complete once it ended at
# least 72 hours before the read.
LATENCY = timedelta(hours=72)
# 90 days at connect (D9), 31 days per Analytics request window, 50 videos per page (F5).
CONNECT_DAYS = 90
WINDOW_DAYS = 31
PAGE_VIDEOS = 50
HISTORY_DAYS = 730
# Day records stay provisional while a later run may re-read them: 72 hours of latency, the
# 4-day re-read and one day, plus one hour for a 25-hour day (D9 as amended by D-060).
PROVISIONAL_HOURS = 193
ACCESS_SECONDS = 3600
REFRESH_SECONDS = 7 * 24 * 3600
CURSOR_PREFIX = "syt_cursor_"
CLOCK = datetime(2026, 11, 6, 20, 0, tzinfo=UTC)
# creatorContentType values as the Analytics API returns them (F9), mapped to the catalog's
# product types; a value not yet observed maps to UNSPECIFIED (D-060, D8).
CONTENT_TYPES = MappingProxyType(
    {
        "shorts": "SHORTS",
        "videoOnDemand": "VIDEO_ON_DEMAND",
        "creatorContentTypeUnspecified": "UNSPECIFIED",
    }
)
PRODUCT_TYPES = ("SHORTS", "VIDEO_ON_DEMAND", "LIVE_STREAM", "STORY", "UNSPECIFIED")
VIDEO_ATTRIBUTES = ("published_at", "duration", "privacy_status", "live_state")
# Dates on which YouTube changed how views count (entry review section 3.2 for the Analytics
# metric, YT-7 for the Data API public counters).
ANALYTICS_VIEW_CHANGES = (date(2025, 4, 30), date(2026, 8, 27), date(2026, 11, 16))
PUBLIC_VIEW_CHANGES = (date(2025, 3, 31), date(2026, 8, 27), date(2026, 11, 16))
ANALYTICS_STREAMS = ("channel_daily", "video_totals")


def _analytics(name: str, unit: str = "count", **extra: object) -> MetricSpec:
    return MetricSpec(name, unit, streams=ANALYTICS_STREAMS, **extra)  # type: ignore[arg-type]


ANALYTICS_METRICS = (
    _analytics("views", definition_changes=ANALYTICS_VIEW_CHANGES),
    _analytics("engagedViews"),
    _analytics("estimatedMinutesWatched", "minutes"),
    _analytics("averageViewDuration", "seconds", additive=False),
    _analytics("averageViewPercentage", "percent", additive=False),
    _analytics("likes"),
    _analytics("dislikes"),
    _analytics("comments"),
    _analytics("shares"),
    _analytics("subscribersGained"),
    _analytics("subscribersLost"),
    _analytics("videosAddedToPlaylists"),
    _analytics("videosRemovedFromPlaylists"),
)
CHANNEL_METRICS = (
    MetricSpec("subscriberCount", "rounded_count", streams=("channel",)),
    MetricSpec("viewCount", "count", streams=("channel",), definition_changes=PUBLIC_VIEW_CHANGES),
    MetricSpec("videoCount", "count", streams=("channel",)),
)
VIDEO_METRICS = (
    MetricSpec("viewCount", "count", streams=("videos",), definition_changes=PUBLIC_VIEW_CHANGES),
    MetricSpec("likeCount", "count", streams=("videos",)),
    MetricSpec("commentCount", "count", streams=("videos",)),
)
BUCKETS = (
    QuotaBucket(DATA, "unit", daily_quota=9000, connection_daily=100, zone=PACIFIC),
    QuotaBucket(ANALYTICS, "request", daily_quota=90000, connection_daily=30, zone=PACIFIC),
)
STREAMS = (
    StreamSpec("channel", None, history_days=1, overlap_days=0, cost={DATA: 1}),
    StreamSpec(
        "channel_daily",
        None,
        history_days=HISTORY_DAYS,
        overlap_days=4,
        cost={ANALYTICS: 1},
        data_delay_hours=PROVISIONAL_HOURS,
    ),
    StreamSpec(
        "videos",
        None,
        history_days=1,
        overlap_days=0,
        cost={DATA: 2},
        attributes=VIDEO_ATTRIBUTES,
        inventory=True,
        confirm_cost={DATA: 1},
    ),
    StreamSpec("video_totals", None, history_days=1, overlap_days=0, cost={DATA: 1, ANALYTICS: 1}),
)
CAPABILITY = Capability(
    provider="synthetic_youtube",
    version="synthetic-youtube-1",
    pkce="S256",
    refresh=True,
    revocation_scope="account",
    scopes=(DATA_SCOPE, ANALYTICS_SCOPE),
    metrics=CHANNEL_METRICS + ANALYTICS_METRICS + VIDEO_METRICS,
    stream="channel",
    cost_unit="unit",
    daily_quota=None,
    freshness_hours=36,
    streams=STREAMS,
    data_delay_hours=0,
    require_all_scopes=True,
    refresh_ahead_seconds=300,
    authorization_check_days=7,
    reconnect_grace_days=14,
    buckets=BUCKETS,
    day_zone=PACIFIC,
    agent_disclosure="dev-agent-approval-1",
    label_refresh_days=30,
)
# The scope each stream needs; a grant without it is refused with insufficientPermissions.
STREAM_SCOPES = MappingProxyType(
    {
        "channel": (DATA_SCOPE,),
        "channel_daily": (ANALYTICS_SCOPE,),
        "videos": (DATA_SCOPE,),
        "video_totals": (DATA_SCOPE, ANALYTICS_SCOPE),
    }
)
# The bucket a quotaExceeded answer concerns for each stream.
STREAM_BUCKET = MappingProxyType(
    {"channel": DATA, "channel_daily": ANALYTICS, "videos": DATA, "video_totals": ANALYTICS}
)
READ_OUTCOMES = FETCH_OUTCOMES | {"quota_exceeded"}
NUMBERS = {
    "access_ttl": 0,
    "refresh_ttl": 0,
    "videos": 0,
    "subscribers": 0,
    "revision": 0,
    "retry_after": 0,
}
DEFAULTS = {
    "access_ttl": ACCESS_SECONDS,
    "refresh_ttl": REFRESH_SECONDS,
    "videos": 4,
    "subscribers": 12345,
    "revision": 0,
    "retry_after": 60,
}
BEHAVIORS = {
    "exchange": {"ok", "retryable"},
    "refresh": {"ok", "invalid_grant", "retryable"},
    "revoke": {"ok", "retryable"},
    "fetch": READ_OUTCOMES,
    "hide_subscribers": {"ok", "yes"},
    "leak_title": {"ok", "yes"},
}


def pacific_start(day: date) -> datetime:
    return datetime.combine(day, time(), ZONE).astimezone(UTC)


def pacific_day(instant: datetime) -> date:
    return instant.astimezone(ZONE).date()


# The end of the last Pacific day that ended at least 72 hours before `now` (D-060): the start
# of the Pacific day containing now - 72 hours.
def complete_through(now: datetime) -> datetime:
    return pacific_start(pacific_day(now - LATENCY))


# A channel_daily position: the read's first day and the offset of the next page in its day
# list, as "<first-day>:<offset>". The first day stays fixed for the whole read, so a page read
# after the 72-hour bound has moved (a deferral across a Pacific midnight) continues the same
# list and skips no day (R011-15). Anything else is refused as invalid_cursor.
def day_cursor(first: date, offset: int) -> str:
    return f"{first.isoformat()}:{offset}"


def parse_day_cursor(position: str) -> tuple[date, int]:
    text, separator, offset = position.partition(":")
    try:
        first = date.fromisoformat(text)
    except ValueError:
        first = None
    valid = first is not None and first.isoformat() == text and separator == ":"
    if not valid or not (offset.isascii() and offset.isdigit()):
        raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
    assert first is not None
    return first, int(offset)


# Round down to three significant figures, as YouTube reports subscriberCount (YT-2).
def rounded_count(value: int) -> int:
    if value < 1000:
        return value
    factor = 10 ** (len(str(value)) - 3)
    return value // factor * factor


def product_type(content_type: str) -> str:
    return CONTENT_TYPES.get(content_type, "UNSPECIFIED")


class SyntheticYouTubeProvider(SyntheticProvider):
    capability = CAPABILITY

    def __repr__(self) -> str:
        return "SyntheticYouTubeProvider()"

    def _number(self, connection: sqlite3.Connection, name: str) -> int:
        row = connection.execute("SELECT value FROM behaviors WHERE name = ?", (name,)).fetchone()
        return int(row[0]) if row else DEFAULTS[name]

    def _ttl(self, connection: sqlite3.Connection) -> int:
        return self._number(connection, "access_ttl")

    def _clock(self, connection: sqlite3.Connection) -> datetime:
        row = connection.execute("SELECT value FROM behaviors WHERE name = 'clock'").fetchone()
        return datetime.fromisoformat(row[0]) if row else CLOCK

    def _list(self, connection: sqlite3.Connection, name: str) -> set[str]:
        row = connection.execute("SELECT value FROM behaviors WHERE name = ?", (name,)).fetchone()
        return {item for item in (row[0] if row else "").split(",") if item}

    # Test control: numbers of NUMBERS; "clock" (an ISO instant placing the data); "deleted"
    # and "hidden" (comma-separated video IDs removed from the channel, or missing from the
    # uploads playlist while they still exist); "content_type" (a creatorContentType value
    # returned for every video, or ""); "omit_metric"; "fetch_script" (as for the 009 provider,
    # with quota_exceeded); or a mode of BEHAVIORS.
    def set_behavior(self, name: str, value: str) -> None:
        if name in NUMBERS:
            if int(value) < NUMBERS[name]:
                raise ValueError("Synthetic number out of range.")
        elif name == "clock":
            if datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("The synthetic clock needs a time zone.")
        elif name in {"deleted", "hidden", "content_type"}:
            pass
        elif name == "omit_metric":
            if value and value not in {spec.name for spec in self.capability.metrics}:
                raise ValueError("Unknown synthetic metric.")
        elif name == "fetch_script":
            for item in filter(None, value.split(",")):
                outcome, _, seconds = item.partition(":")
                if outcome not in READ_OUTCOMES or (seconds and not seconds.isdigit()):
                    raise ValueError("Unknown synthetic read outcome.")
        elif value not in BEHAVIORS.get(name, set()):
            raise ValueError("Unknown synthetic behavior.")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO behaviors (name, value) VALUES (?, ?) "
                "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                (name, value),
            )

    # Google's web server flow: offline access and consent on every connect (D4), and PKCE
    # S256 (D3, F2).
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
            "client_id": "tracking-synthetic-youtube.apps.googleusercontent.invalid",
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        if code_challenge is not None:
            query["code_challenge"] = code_challenge
            query["code_challenge_method"] = "S256"
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    # Stand-in for Google's consent page: the account approves `scopes` (all requested scopes
    # by default) for its channels; `channels` other than 1 leads to a refusal (F4).
    def approve(
        self,
        authorization_url: str,
        account: str,
        label: str | None = None,
        *,
        scopes: tuple[str, ...] | None = None,
        channels: int = 1,
    ) -> str:
        parts = urlsplit(authorization_url)
        if f"{parts.scheme}://{parts.netloc}{parts.path}" != AUTHORIZE_URL:
            raise ValueError("Not a synthetic YouTube authorization URL.")
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if query.get("code_challenge_method") != "S256" or not query.get("code_challenge"):
            raise ValueError("The synthetic YouTube provider requires S256 PKCE.")
        if query.get("access_type") != "offline" or query.get("prompt") != "consent":
            raise ValueError("The synthetic YouTube provider expects offline access and consent.")
        requested = query.get("scope", "").split()
        approved = [scope for scope in requested if scopes is None or scope in scopes]
        code = "syt_code_" + secrets.token_urlsafe(24)
        expires = (_now() + timedelta(seconds=CODE_SECONDS)).isoformat()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO codes (digest, challenge, redirect_uri, scopes, account, label, "
                "kind, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _digest(code),
                    query["code_challenge"],
                    query.get("redirect_uri", ""),
                    " ".join(approved),
                    account,
                    label,
                    f"channels:{channels}",
                    expires,
                ),
            )
        return code

    def _live_scopes(self, connection: sqlite3.Connection, account: str) -> set[str]:
        rows = connection.execute(
            "SELECT scopes FROM grants WHERE account = ? AND revoked = 0", (account,)
        ).fetchall()
        return {scope for row in rows for scope in row[0].split()}

    def exchange(self, *, code: str, code_verifier: str | None, redirect_uri: str) -> TokenGrant:
        error: ProviderError | None = None
        with self._transaction() as connection:
            if self._behavior(connection, "exchange") == "retryable":
                self._call(connection, "exchange", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "backend_error")
            else:
                row = connection.execute(
                    "SELECT challenge, redirect_uri, scopes, account, label, expires_at, used, "
                    "kind FROM codes WHERE digest = ?",
                    (_digest(code),),
                ).fetchone()
                valid = (
                    row is not None
                    and not row[6]
                    and datetime.fromisoformat(row[5]) > _now()
                    and row[1] == redirect_uri
                    and code_verifier is not None
                    and secrets.compare_digest(row[0], _s256(code_verifier))
                )
                connection.execute("UPDATE codes SET used = 1 WHERE digest = ?", (_digest(code),))
                if not valid:
                    self._call(connection, "exchange", "invalid_grant")
                    error = ProviderError(ErrorKind.PERMANENT, "invalid_grant")
                else:
                    account, label = row[3], row[4]
                    # The answer reports the account's whole grant to the project (F1).
                    scopes = sorted(set(row[2].split()) | self._live_scopes(connection, account))
                    grant_id = connection.execute(
                        "INSERT INTO grants (account, label, kind, scopes) VALUES (?, ?, ?, ?)",
                        (account, label, "channel", " ".join(scopes)),
                    ).lastrowid
                    access, expires = self._issue(
                        connection, grant_id, "access_token", self._ttl(connection)
                    )
                    refresh, refresh_expires = self._issue(
                        connection,
                        grant_id,
                        "refresh_token",
                        self._number(connection, "refresh_ttl"),
                    )
                    self._call(connection, "exchange", "ok")
                    channels = int(row[7].removeprefix("channels:"))
        if error is not None:
            raise error
        refusal = None if channels == 1 else ("no_channel" if channels == 0 else "several_channels")
        return TokenGrant(
            access,
            refresh,
            expires,
            tuple(scopes),
            account if channels == 1 else "",
            label,
            "channel",
            refresh_expires,
            refusal,
        )

    # A new access token; the refresh token is not rotated and keeps the expiry counted from
    # the consent (F3).
    def refresh(self, refresh_token: str) -> TokenGrant:
        error: ProviderError | None = None
        with self._transaction() as connection:
            behavior = self._behavior(connection, "refresh")
            found = self._grant(connection, refresh_token, "refresh_token")
            expired = (
                found is not None
                and found[2] is not None
                and datetime.fromisoformat(found[2]) <= _now()
            )
            if behavior == "retryable":
                self._call(connection, "refresh", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "backend_error")
            elif found is None or found[1] or expired or behavior == "invalid_grant":
                self._call(connection, "refresh", "invalid_grant")
                error = ProviderError(ErrorKind.UNAUTHORIZED, "invalid_grant")
            else:
                account, label, scopes = connection.execute(
                    "SELECT account, label, scopes FROM grants WHERE id = ?", (found[0],)
                ).fetchone()
                access, expires = self._issue(
                    connection, found[0], "access_token", self._ttl(connection)
                )
                refresh_expires = datetime.fromisoformat(found[2]) if found[2] else None
                self._call(connection, "refresh", "ok")
        if error is not None:
            raise error
        return TokenGrant(
            access,
            refresh_token,
            expires,
            tuple(scopes.split()),
            account,
            label,
            "channel",
            refresh_expires,
        )

    # Revoking any token removes every grant the account gave the project (G-1). A token that
    # is already revoked is reported as done, like Google's invalid_token answer.
    def revoke(self, token: str, kind: str) -> RevocationOutcome:
        error: ProviderError | None = None
        with self._transaction() as connection:
            behavior = self._behavior(connection, "revoke")
            found = self._grant(connection, token)
            if behavior == "retryable":
                self._call(connection, "revoke", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "backend_error")
            elif found is None:
                self._call(connection, "revoke", "unknown_token")
                error = ProviderError(ErrorKind.PERMANENT, "invalid_token")
            else:
                account = connection.execute(
                    "SELECT account FROM grants WHERE id = ?", (found[0],)
                ).fetchone()[0]
                connection.execute("UPDATE grants SET revoked = 1 WHERE account = ?", (account,))
                self._call(connection, "revoke", "ok")
        if error is not None:
            raise error
        return "done"

    def verify_webhook(self, headers: object, body: bytes, now: datetime) -> WebhookDelivery:
        raise WebhookRejected("signature_invalid")

    def verify_signed_request(self, signed_request: str, now: datetime) -> SignedRequest:
        raise WebhookRejected("signature_invalid")

    # The channel's uploads in playlist order: (video ID, privacy status, published time,
    # duration, content type). Deleted videos are gone; hidden ones are omitted by the playlist
    # only (`playlist` True).
    def _videos(
        self, connection: sqlite3.Connection, playlist: bool
    ) -> list[tuple[str, str, datetime, str, str]]:
        clock = self._clock(connection)
        deleted = self._list(connection, "deleted")
        hidden = self._list(connection, "hidden") if playlist else set()
        override = self._behavior(connection, "content_type")
        items = []
        for index in range(1, self._number(connection, "videos") + 1):
            video = f"v{index:04d}"
            if video in deleted or video in hidden:
                continue
            privacy = {1: "private", 2: "unlisted"}.get(index, "public")
            published = clock - DAY * 2 if index == 1 else clock - DAY * (30 * index)
            content = (
                override
                if override != "ok"
                else ("shorts", "videoOnDemand", "creatorContentTypeUnspecified")[index % 3]
            )
            items.append((video, privacy, published, f"PT{index}M{index}S", content))
        return items

    def _omit(self, connection: sqlite3.Connection) -> str:
        value = self._behavior(connection, "omit_metric")
        return "" if value == "ok" else value

    # Channel metrics of one Pacific day: None for a day the API returns no row (every seventh
    # day), zeros on every fifth day.
    def _day(self, connection: sqlite3.Connection, day: date) -> dict[str, int | float] | None:
        ordinal = day.toordinal()
        if ordinal % 7 == 0:
            return None
        views = 0 if ordinal % 5 == 0 else ordinal % 97 + 10 + self._number(connection, "revision")
        return {
            "views": views,
            "engagedViews": views // 2,
            "estimatedMinutesWatched": views * 3,
            "averageViewDuration": 95 if views else 0,
            "averageViewPercentage": 41.5 if views else 0.0,
            "likes": views // 10,
            "dislikes": 1 if views else 0,
            "comments": 2 if views else 0,
            "shares": 3 if views else 0,
            "subscribersGained": 2 if views else 0,
            "subscribersLost": 1 if views else 0,
            "videosAddedToPlaylists": 1 if views else 0,
            "videosRemovedFromPlaylists": 0,
        }

    # A record with the metrics of one row, or, when the API returned no row, no values and
    # not_returned for every metric of the stream (D-060). An omitted metric is not_returned.
    def _record(
        self,
        object_id: str,
        observed: datetime,
        metrics: dict[str, int | float] | None,
        names: list[str],
        omit: str,
        product: str | None = None,
        provisional_until: datetime | None = None,
    ) -> ProviderRecord:
        if metrics is None:
            unavailable = dict.fromkeys(names, "not_returned")
            metrics = {}
        else:
            unavailable = {}
            if omit in metrics:
                metrics.pop(omit)
                unavailable[omit] = "not_returned"
        return ProviderRecord(
            object_id,
            observed,
            metrics,
            product,
            unavailable,
            provisional_until=provisional_until,
        )

    # Lifetime analytics totals of one video; video 2 has no analytics rows yet.
    def _totals(self, connection: sqlite3.Connection, index: int) -> dict[str, int | float] | None:
        if index == 2:
            return None
        views = 1000 * index + self._number(connection, "revision")
        return {
            "views": views,
            "engagedViews": views // 2,
            "estimatedMinutesWatched": views * 3,
            "averageViewDuration": 60 + index,
            "averageViewPercentage": 35.5,
            "likes": views // 10,
            "dislikes": index,
            "comments": index,
            "shares": index,
            "subscribersGained": index,
            "subscribersLost": 0,
            "videosAddedToPlaylists": index,
            "videosRemovedFromPlaylists": 0,
        }

    # One page of a stream at `position`, the cursor without its prefix (None for the first
    # page): an offset into the inventory, or a channel_daily day cursor (R011-15).
    def _page(
        self,
        connection: sqlite3.Connection,
        stream: str,
        account: str,
        label: str | None,
        position: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> ProviderPage:
        clock = self._clock(connection)
        omit = self._omit(connection)
        names = [spec.name for spec in self.capability.stream_metrics(stream)]
        today = pacific_start(pacific_day(clock))
        through = complete_through(clock)
        if stream == "channel":
            metrics: dict[str, int | float] = {
                "subscriberCount": rounded_count(self._number(connection, "subscribers")),
                "viewCount": 1000 + self._number(connection, "revision"),
                "videoCount": sum(
                    1 for item in self._videos(connection, True) if item[1] == "public"
                ),
            }
            record = self._record(f"snapshot-{pacific_day(clock)}", today, metrics, names, omit)
            if self._behavior(connection, "hide_subscribers") == "yes":
                values = dict(record.metrics)
                values.pop("subscriberCount", None)
                record = ProviderRecord(
                    record.provider_object_id,
                    today,
                    values,
                    unavailable={**record.unavailable, "subscriberCount": "not_returned"},
                )
            return ProviderPage((record,), None, today, clock, label)
        if stream == "channel_daily":
            # The first page fixes the read's first day; the cursor carries it (R011-15).
            last_day = pacific_day(through)
            if position is None:
                first = (
                    last_day - timedelta(days=CONNECT_DAYS) if since is None else pacific_day(since)
                )
                first, offset = max(first, last_day - timedelta(days=HISTORY_DAYS)), 0
            else:
                first, offset = parse_day_cursor(position)
            start = pacific_start(first)
            end = through if until is None else min(through, pacific_start(pacific_day(until)))
            days = []
            day = first
            while start < end and pacific_start(day) < end:
                days.append(day)
                day += DAY
            chunk = days[offset : offset + WINDOW_DAYS]
            records = tuple(
                self._record(
                    f"day-{day}", pacific_start(day), self._day(connection, day), names, omit
                )
                for day in chunk
            )
            following = offset + WINDOW_DAYS
            return ProviderPage(
                records,
                CURSOR_PREFIX + day_cursor(first, following) if following < len(days) else None,
                start if start < end else None,
                max(start, end),
            )
        offset = int(position) if position is not None else 0
        uploads = self._videos(connection, True)
        chunk = uploads[offset : offset + PAGE_VIDEOS]
        following = offset + PAGE_VIDEOS
        cursor = f"{CURSOR_PREFIX}{following}" if following < len(uploads) else None
        if stream == "videos":
            records = []
            for video, privacy, published, duration, _ in chunk:
                index = int(video[1:])
                values: dict[str, int | float] = {
                    "viewCount": 100 * index,
                    "likeCount": 10 * index,
                    "commentCount": index,
                }
                unavailable = {}
                # Video 3 hides its likes and video 2 has comments turned off (F5).
                for name, hidden_on in (("likeCount", 3), ("commentCount", 2)):
                    if index == hidden_on:
                        values.pop(name)
                        unavailable[name] = "not_returned"
                if omit in values:
                    values.pop(omit)
                    unavailable[omit] = "not_returned"
                attributes: dict[str, str | int | bool | None] = {
                    "published_at": published.isoformat(),
                    "duration": duration,
                    "privacy_status": privacy,
                    "live_state": "none",
                }
                if self._behavior(connection, "leak_title") == "yes":
                    attributes["title"] = f"Synthetic title {index}"
                records.append(ProviderRecord(video, today, values, None, unavailable, attributes))
            return ProviderPage(tuple(records), cursor, None, clock)
        # video_totals: lifetime totals through the last complete day, with the content type;
        # totals of a video published within the provisional period stay provisional (D9).
        observed = pacific_start(pacific_day(through) - DAY)
        records = []
        for video, _, published, _, content in chunk:
            index = int(video[1:])
            records.append(
                self._record(
                    video,
                    observed,
                    self._totals(connection, index),
                    names,
                    omit,
                    product_type(content),
                    pacific_start(pacific_day(published)) + timedelta(hours=PROVISIONAL_HOURS),
                )
            )
        return ProviderPage(tuple(records), cursor, None, through)

    def fetch_page(
        self,
        access_token: str,
        *,
        stream: str = "channel",
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ProviderPage:
        if self.capability.stream_spec(stream) is None:
            raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")
        position = None
        if cursor is not None:
            position = cursor.removeprefix(CURSOR_PREFIX)
            if not cursor.startswith(CURSOR_PREFIX):
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
            if stream == "channel_daily":
                parse_day_cursor(position)
            elif not (position.isascii() and position.isdigit()):
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
        error: ProviderError | None = None
        page: ProviderPage | None = None
        with self._transaction() as connection:
            behavior, retry_after = self._read_outcome(connection)
            found = self._grant(connection, access_token, "access_token")
            expired = (
                found is not None
                and found[2] is not None
                and datetime.fromisoformat(found[2]) <= _now()
            )
            detail = f"{stream}:{position or 0}"
            scopes: set[str] = set()
            if found is not None:
                scopes = set(
                    connection.execute("SELECT scopes FROM grants WHERE id = ?", (found[0],))
                    .fetchone()[0]
                    .split()
                )
            if behavior == "retryable":
                self._call(connection, "fetch", "retryable", detail)
                error = ProviderError(ErrorKind.RETRYABLE, "backend_error")
            elif behavior == "rate_limited":
                self._call(connection, "fetch", "rate_limited", detail)
                seconds = self._number(connection, "retry_after")
                error = ProviderError(
                    ErrorKind.RATE_LIMITED,
                    "rate_limit_exceeded",
                    seconds if retry_after is None else retry_after,
                )
            elif behavior == "quota_exceeded":
                self._call(connection, "fetch", "quota_exceeded", detail)
                error = ProviderError(
                    ErrorKind.BUDGET_EXHAUSTED, "quota_exceeded", bucket=STREAM_BUCKET[stream]
                )
            elif behavior == "permanent":
                self._call(connection, "fetch", "permanent", detail)
                error = ProviderError(ErrorKind.PERMANENT, "bad_request")
            elif found is None or found[1] or expired or behavior == "unauthorized":
                self._call(connection, "fetch", "unauthorized", detail)
                error = ProviderError(ErrorKind.UNAUTHORIZED, "auth_error")
            elif behavior == "forbidden" or not set(STREAM_SCOPES[stream]) <= scopes:
                self._call(connection, "fetch", "forbidden", detail)
                error = ProviderError(ErrorKind.FORBIDDEN, "insufficient_permissions")
            else:
                account, label = connection.execute(
                    "SELECT account, label FROM grants WHERE id = ?", (found[0],)
                ).fetchone()
                page = self._page(connection, stream, account, label, position, since, until)
                self._call(connection, "fetch", "ok", detail)
        if error is not None:
            raise error
        assert page is not None
        return page

    # videos.list with the missing IDs: those it no longer returns are gone (D11).
    def confirm_deleted(
        self, access_token: str, *, stream: str, object_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        if len(object_ids) > PAGE_VIDEOS:
            raise ProviderError(ErrorKind.PERMANENT, "invalid_filters")
        with self._transaction() as connection:
            found = self._grant(connection, access_token, "access_token")
            if found is None or found[1]:
                self._call(connection, "confirm", "unauthorized")
                raise ProviderError(ErrorKind.UNAUTHORIZED, "auth_error")
            existing = {item[0] for item in self._videos(connection, False)}
            self._call(connection, "confirm", "ok", ",".join(object_ids))
        return tuple(item for item in object_ids if item not in existing)

    # Test inspection: (stream:offset, outcome) of each read in order.
    def stream_reads(self) -> list[tuple[str, str]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT detail, outcome FROM calls WHERE operation = 'fetch' ORDER BY seq"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]


__all__ = ["CAPABILITY", "SyntheticYouTubeProvider", "complete_through", "product_type"]
