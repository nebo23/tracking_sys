"""YouTube Data API v3 and YouTube Analytics API adapter (specification 011-C, D-058, D-060).

The live adapter for YouTube channels authorized by their owner or a manager. Every shape it
reads was observed with the owner's test channel in 011-B (2026-11-17 and 2026-11-18; see
specs/011-youtube/evidence.md) or is documented by Google:

- Authorization through Google's web server flow with offline access, consent on every
  connect and reconnect, and PKCE S256, which the Web client enforces (D3, D4, F2). Only
  youtube.readonly and yt-analytics.readonly are requested (D2). The code exchange reports
  both scopes, a one-hour access token and the refresh token's lifetime (seven days while the
  project is in Testing), which is kept as the grant's expiry (F1). The channel comes from
  channels.list?mine=true: exactly one channel is required (F4); none, several, or a failed
  lookup are refusals. A grant without the Data API scope is returned without an account, so
  the runtime refuses it for its missing scope (D2).
- Refreshes return a new access token and never rotate the refresh token (F3). Revocation
  through oauth2.googleapis.com/revoke removes every grant of the account (G-1); an already
  invalid token is reported as done.
- Streams (D7) and the D8 catalog of the synthetic adapter: the channel snapshot of the
  Pacific day; channel day reports in windows of at most 31 days, complete through the end of
  the last Pacific day that ended at least 72 hours before the read, with a day the API does
  not return recorded as not_returned, never zero (D9 as amended by D-060), and a cursor that
  keeps the read's first day, so a read resumed after a Pacific midnight skips none
  (R011-15); the uploads
  inventory 50 videos per page with the allow-listed attributes (F5, D11), whose missing
  videos are confirmed gone through videos.list; and lifetime totals per video with the
  creatorContentType product type (F9), read as two reports per page because Google refuses
  the playlist metrics with that dimension (011-C live check). The fields parameter keeps
  titles, descriptions and
  every other text out of the answers, except the channel title used as the label.
- Errors (F14, YT-5): 401 is unauthorized; 403 quotaExceeded is the bucket's budget answer;
  403 rate limits and 429 are rate limits; other 403 answers are forbidden for the stream;
  5xx and network failures are retryable; anything else is permanent. A read that finds no
  channel for the authorized account is unauthorized (channel_gone), so a deleted channel
  leads to reconnect_required and the D6 grace purge (R011-16). At the token endpoint only
  invalid_grant ends the user's authorization; a rejected OAuth client is permanent
  (client_rejected) and logged as connector_client_rejected, and connections stay active
  (R011-14).

The adapter is registered only when it is enabled and configured and the
youtube.authorized_analytics and youtube.other_data rules in app.privacy.providers are current
(see build_providers). While the Google Cloud project is in Testing, only its test users can
authorize, and live use stays with the owner's test channels until 011-D.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.connectors.contracts import (
    ErrorKind,
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
from app.connectors.synthetic_youtube import (
    ANALYTICS,
    ANALYTICS_METRICS,
    CONNECT_DAYS,
    DATA,
    DATA_SCOPE,
    HISTORY_DAYS,
    PAGE_VIDEOS,
    PROVISIONAL_HOURS,
    VIDEO_ATTRIBUTES,
    WINDOW_DAYS,
    complete_through,
    day_cursor,
    pacific_day,
    pacific_start,
    parse_day_cursor,
    product_type,
)
from app.connectors.synthetic_youtube import CAPABILITY as SYNTHETIC_CAPABILITY

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
TIMEOUT = 20
# A lifetime total from the day YouTube's records begin is accepted (F10).
HISTORY_START = date(2005, 2, 14)
DAY = timedelta(days=1)
METRIC_NAMES = tuple(spec.name for spec in ANALYTICS_METRICS)
CHANNEL_FIELDS = (
    "items(id,snippet/title,statistics(viewCount,subscriberCount,hiddenSubscriberCount,videoCount))"
)
UPLOADS_FIELDS = "items/contentDetails/relatedPlaylists/uploads"
PLAYLIST_FIELDS = "nextPageToken,items/contentDetails(videoId,videoPublishedAt)"
VIDEO_FIELDS = (
    "items(id,snippet(publishedAt,liveBroadcastContent),contentDetails/duration,"
    "status/privacyStatus,statistics(viewCount,likeCount,commentCount))"
)
QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})
RATE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
# Token endpoint errors that reject the connector's own OAuth client (a wrong, rotated, deleted
# or disabled client), not a user's authorization (R011-14).
CLIENT_ERRORS = frozenset(
    {"invalid_client", "unauthorized_client", "deleted_client", "disabled_client"}
)
RATE_WAIT = 60
logger = logging.getLogger("tracking")
# A page's cost is its maximum: the first page of an inventory read also resolves the uploads
# playlist with one channels.list call (D10). A video_totals page reads two reports.
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
        cost={DATA: 3},
        attributes=VIDEO_ATTRIBUTES,
        inventory=True,
        confirm_cost={DATA: 1},
    ),
    StreamSpec("video_totals", None, history_days=1, overlap_days=0, cost={DATA: 2, ANALYTICS: 2}),
)
CAPABILITY = replace(
    SYNTHETIC_CAPABILITY,
    provider="youtube",
    version="youtube-data-v3-analytics-v2",
    streams=STREAMS,
)


@dataclass
class Reply:
    status: int
    body: Any
    headers: Mapping[str, str] = field(default_factory=dict)


# Send one request. A network failure is a retryable provider error that carries neither the
# URL nor any provider message; the access token travels only in the Authorization header.
# Header names are lower-cased.
def http_send(
    method: str,
    url: str,
    form: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Reply:
    data = None if form is None else urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(url, data=data, method=method)
    if form is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status, raw, answer = response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        status, raw, answer = error.code, error.read(), dict(error.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError(ErrorKind.RETRYABLE, "network") from None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = {}
    return Reply(status, body, {name.lower(): value for name, value in answer.items()})


Transport = Callable[[str, str, Mapping[str, str] | None, Mapping[str, str] | None], Reply]


def _reason(body: Any) -> str | None:
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    errors = error.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        reason = errors[0].get("reason")
        return reason if isinstance(reason, str) else None
    return None


def _retry_after(headers: Mapping[str, str]) -> int:
    value = headers.get("retry-after", "")
    return int(value) if value.isdigit() else RATE_WAIT


# Map a refused Data API or Analytics API answer (YT-5, F14) for the bucket of the call.
def _error(reply: Reply, bucket: str) -> ProviderError:
    reason = _reason(reply.body)
    if reply.status == 401:
        return ProviderError(ErrorKind.UNAUTHORIZED, "auth_error")
    if reply.status == 403 and reason in QUOTA_REASONS:
        return ProviderError(ErrorKind.BUDGET_EXHAUSTED, "quota_exceeded", bucket=bucket)
    if reply.status == 429 or reason in RATE_REASONS:
        return ProviderError(ErrorKind.RATE_LIMITED, "rate_limited", _retry_after(reply.headers))
    if reply.status == 403:
        return ProviderError(ErrorKind.FORBIDDEN, "insufficient_permissions")
    if reply.status >= 500:
        return ProviderError(ErrorKind.RETRYABLE, "backend_error")
    return ProviderError(ErrorKind.PERMANENT, "bad_request" if reply.status == 400 else "refused")


# Map a refused token endpoint answer. Only invalid_grant ends the user's authorization, and
# only for a refresh; at an exchange it is permanent. A client error, which Google answers with
# 401 for a wrong secret, rejects the connector's own client: it is permanent with the closed
# code client_rejected, so runs fail and every connection stays active (R011-14). Any other
# refusal is permanent as well.
def _token_error(reply: Reply, *, refresh: bool) -> ProviderError:
    error = reply.body.get("error") if isinstance(reply.body, dict) else None
    if reply.status == 429:
        return ProviderError(ErrorKind.RATE_LIMITED, "rate_limited", _retry_after(reply.headers))
    if reply.status >= 500:
        return ProviderError(ErrorKind.RETRYABLE, "backend_error")
    if error in CLIENT_ERRORS:
        return ProviderError(ErrorKind.PERMANENT, "client_rejected")
    if error == "invalid_grant":
        kind = ErrorKind.UNAUTHORIZED if refresh else ErrorKind.PERMANENT
        return ProviderError(kind, "invalid_grant")
    return ProviderError(ErrorKind.PERMANENT, "refused")


# The items of a channels.list?mine=true answer. An answer without a channel means the
# authorized account no longer has one (a deleted channel): the authorization has lost its
# object, so the read is unauthorized with the closed code channel_gone, and the runtime makes
# the connection reconnect_required after its one refresh, which leads to the D6 grace purge
# (R011-16). A failed request is mapped by _error and stays retryable.
def _channel_items(answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = [item for item in answer.get("items") or [] if isinstance(item, dict)]
    if not items:
        raise ProviderError(ErrorKind.UNAUTHORIZED, "channel_gone")
    return items


def _count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    return _count(value)


def _published(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class YouTubeProvider:
    capability = CAPABILITY

    # transport None sends real requests through http_send, looked up when each call is made.
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client_id, self._client_secret = client_id, client_secret
        self._transport, self._clock = transport, clock

    def __repr__(self) -> str:
        return "YouTubeProvider()"

    def _send(
        self,
        method: str,
        url: str,
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Reply:
        return (self._transport or http_send)(method, url, form, headers)

    # One read of a Data API or Analytics API resource with the access token in the header.
    def _get(self, url: str, params: Mapping[str, str], token: str, bucket: str) -> dict[str, Any]:
        reply = self._send(
            "GET",
            f"{url}?{urllib.parse.urlencode(params)}",
            None,
            {"Authorization": f"Bearer {token}"},
        )
        if reply.status >= 400 or not isinstance(reply.body, dict):
            raise _error(reply, bucket)
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
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        if code_challenge is not None:
            query["code_challenge"] = code_challenge
            query["code_challenge_method"] = "S256"
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"

    # A token endpoint call. A rejected client is logged as connector_client_rejected, without
    # fields, so the operator learns that the client must be repaired or the connections purged
    # (R011-14).
    def _token(self, form: Mapping[str, str], *, refresh: bool) -> tuple[dict[str, Any], datetime]:
        reply = self._send("POST", TOKEN_URL, form, None)
        body = reply.body if isinstance(reply.body, dict) else {}
        if reply.status >= 400 or not isinstance(body.get("access_token"), str):
            error = _token_error(reply, refresh=refresh)
            if error.provider_code == "client_rejected":
                logger.error("connector_client_rejected")
            raise error
        return body, self._clock()

    @staticmethod
    def _expiry(now: datetime, seconds: Any) -> datetime | None:
        value = _count(seconds)
        return None if value is None else now + timedelta(seconds=value)

    def exchange(self, *, code: str, code_verifier: str | None, redirect_uri: str) -> TokenGrant:
        form = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if code_verifier is not None:
            form["code_verifier"] = code_verifier
        body, now = self._token(form, refresh=False)
        access = body["access_token"]
        refresh = body.get("refresh_token") if isinstance(body.get("refresh_token"), str) else None
        scopes = tuple(sorted(str(body.get("scope", "")).split()))
        grant = TokenGrant(
            access,
            refresh,
            self._expiry(now, body.get("expires_in")),
            scopes,
            "",
            None,
            "channel",
            self._expiry(now, body.get("refresh_token_expires_in")),
        )
        # Without the Data API scope the channel cannot be read; the runtime refuses the grant
        # for its missing scope (D2).
        if DATA_SCOPE not in scopes:
            return grant
        try:
            answer = self._get(
                f"{DATA_API}/channels",
                {"part": "id,snippet", "mine": "true", "fields": "items(id,snippet/title)"},
                access,
                DATA,
            )
        except ProviderError:
            return replace(grant, refusal="channel_unavailable")
        items = [item for item in answer.get("items") or [] if isinstance(item, dict)]
        if len(items) != 1 or not isinstance(items[0].get("id"), str):
            return replace(grant, refusal="no_channel" if not items else "several_channels")
        title = (items[0].get("snippet") or {}).get("title")
        return replace(
            grant,
            external_account_id=items[0]["id"],
            account_label=title[:200] if isinstance(title, str) else None,
        )

    # A new access token; the refresh token is kept unless Google returns a new one (F3).
    def refresh(self, refresh_token: str) -> TokenGrant:
        body, now = self._token(
            {
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
            refresh=True,
        )
        rotated = body.get("refresh_token")
        return TokenGrant(
            body["access_token"],
            rotated if isinstance(rotated, str) else refresh_token,
            self._expiry(now, body.get("expires_in")),
            tuple(sorted(str(body.get("scope", "")).split())),
            "",
            None,
            "channel",
            self._expiry(now, body.get("refresh_token_expires_in")),
        )

    # Revoking any token removes every grant the account gave the project (G-1). An already
    # revoked or expired token is answered 400 invalid_token and counts as done.
    def revoke(self, token: str, kind: str) -> RevocationOutcome:
        reply = self._send("POST", REVOKE_URL, {"token": token}, None)
        if reply.status == 200:
            return "done"
        error = reply.body.get("error") if isinstance(reply.body, dict) else None
        if reply.status == 400 and error == "invalid_token":
            return "done"
        if reply.status == 429 or reply.status >= 500:
            raise ProviderError(ErrorKind.RETRYABLE, "backend_error")
        raise ProviderError(ErrorKind.PERMANENT, "refused")

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, now: datetime
    ) -> WebhookDelivery:
        raise WebhookRejected("signature_invalid")

    def verify_signed_request(self, signed_request: str, now: datetime) -> SignedRequest:
        raise WebhookRejected("signature_invalid")

    # --- reads ------------------------------------------------------------------------------

    def fetch_page(
        self,
        access_token: str,
        *,
        stream: str = "channel",
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ProviderPage:
        now = self._clock()
        if stream == "channel":
            return self._channel_page(access_token, now)
        if stream == "channel_daily":
            return self._daily_page(access_token, now, cursor, since, until)
        if stream in {"videos", "video_totals"}:
            return self._inventory_page(access_token, now, stream, cursor)
        raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")

    def _channel_page(self, token: str, now: datetime) -> ProviderPage:
        answer = self._get(
            f"{DATA_API}/channels",
            {"part": "id,snippet,statistics", "mine": "true", "fields": CHANNEL_FIELDS},
            token,
            DATA,
        )
        items = _channel_items(answer)
        if len(items) != 1:
            raise ProviderError(ErrorKind.PERMANENT, "channel_unavailable")
        item = items[0]
        statistics = item.get("statistics") or {}
        metrics: dict[str, int | float] = {}
        unavailable: dict[str, str] = {}
        for name in ("subscriberCount", "viewCount", "videoCount"):
            value = _count(statistics.get(name))
            if value is None:
                unavailable[name] = "not_returned"
            else:
                metrics[name] = value
        today = pacific_start(pacific_day(now))
        title = (item.get("snippet") or {}).get("title")
        record = ProviderRecord(f"snapshot-{pacific_day(now)}", today, metrics, None, unavailable)
        return ProviderPage((record,), None, today, now, title if isinstance(title, str) else None)

    # The first page fixes the read's first day: 90 days back at connect (since None), the
    # Pacific day of `since` otherwise, never before the history limit. The cursor carries that
    # day with the next offset, so a page read after the 72-hour bound has moved (a deferral
    # across a Pacific midnight) continues the same day list and skips no day (R011-15). The end
    # follows the latest bound, so a later page may add the days that became complete.
    def _daily_page(
        self,
        token: str,
        now: datetime,
        cursor: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> ProviderPage:
        through = complete_through(now)
        last_day = pacific_day(through)
        if cursor is None:
            first = last_day - timedelta(days=CONNECT_DAYS) if since is None else pacific_day(since)
            first, offset = max(first, last_day - timedelta(days=HISTORY_DAYS)), 0
        else:
            first, offset = parse_day_cursor(cursor)
        start = pacific_start(first)
        end = through if until is None else min(through, pacific_start(pacific_day(until)))
        days: list[date] = []
        day = first
        while start < end and pacific_start(day) < end:
            days.append(day)
            day += DAY
        chunk = days[offset : offset + WINDOW_DAYS]
        rows: dict[str, dict[str, int | float]] = {}
        if chunk:
            answer = self._get(
                ANALYTICS_URL,
                {
                    "ids": "channel==MINE",
                    "startDate": chunk[0].isoformat(),
                    "endDate": chunk[-1].isoformat(),
                    "metrics": ",".join(METRIC_NAMES),
                    "dimensions": "day",
                    "sort": "day",
                },
                token,
                ANALYTICS,
            )
            rows = self._rows(answer, "day")
        records = tuple(self._day_record(day, rows.get(day.isoformat())) for day in chunk)
        following = offset + WINDOW_DAYS
        return ProviderPage(
            records,
            day_cursor(first, following) if following < len(days) else None,
            start if start < end else None,
            max(start, end),
        )

    # Rows of a report keyed by the value of one dimension, with each metric column by its
    # header name. A report without rows has no data for the period.
    @staticmethod
    def _rows(answer: Mapping[str, Any], dimension: str) -> dict[str, dict[str, int | float]]:
        headers = [
            item.get("name") for item in answer.get("columnHeaders") or [] if isinstance(item, dict)
        ]
        rows: dict[str, dict[str, int | float]] = {}
        for row in answer.get("rows") or []:
            if not isinstance(row, list) or len(row) != len(headers):
                continue
            values = dict(zip(headers, row, strict=True))
            key = values.get(dimension)
            if not isinstance(key, str) or key in rows:
                continue
            rows[key] = {
                name: number
                for name in METRIC_NAMES
                if (number := _number(values.get(name))) is not None
            }
        return rows

    @staticmethod
    def _day_record(day: date, values: Mapping[str, int | float] | None) -> ProviderRecord:
        unavailable = {
            name: "not_returned" for name in METRIC_NAMES if values is None or name not in values
        }
        return ProviderRecord(
            f"day-{day}", pacific_start(day), dict(values or {}), None, unavailable
        )

    # The uploads playlist and the position in it, carried in the cursor so that every page
    # after the first reads the playlist directly. A channel that no longer exists is
    # channel_gone (R011-16).
    def _uploads(self, token: str) -> str:
        answer = self._get(
            f"{DATA_API}/channels",
            {"part": "contentDetails", "mine": "true", "fields": UPLOADS_FIELDS},
            token,
            DATA,
        )
        items = _channel_items(answer)
        playlist = (
            ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
            if len(items) == 1
            else None
        )
        if not isinstance(playlist, str):
            raise ProviderError(ErrorKind.PERMANENT, "channel_unavailable")
        return playlist

    def _inventory_page(
        self, token: str, now: datetime, stream: str, cursor: str | None
    ) -> ProviderPage:
        if cursor is None:
            playlist, page_token = self._uploads(token), ""
        else:
            parsed = urllib.parse.parse_qs(cursor, keep_blank_values=True)
            if "uploads" not in parsed:
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
            playlist, page_token = parsed["uploads"][0], parsed.get("page", [""])[0]
        params = {
            "part": "contentDetails",
            "playlistId": playlist,
            "maxResults": str(PAGE_VIDEOS),
            "fields": PLAYLIST_FIELDS,
        }
        if page_token:
            params["pageToken"] = page_token
        answer = self._get(f"{DATA_API}/playlistItems", params, token, DATA)
        uploads: dict[str, datetime | None] = {}
        for item in answer.get("items") or []:
            details = (item.get("contentDetails") or {}) if isinstance(item, dict) else {}
            video = details.get("videoId")
            if isinstance(video, str):
                uploads[video] = _published(details.get("videoPublishedAt"))
        following = answer.get("nextPageToken")
        next_cursor = (
            urllib.parse.urlencode({"uploads": playlist, "page": following})
            if isinstance(following, str) and following
            else None
        )
        if stream == "videos":
            records = self._video_records(token, now, list(uploads))
            return ProviderPage(records, next_cursor, None, now)
        through = complete_through(now)
        records = self._total_records(token, through, uploads)
        return ProviderPage(records, next_cursor, None, through)

    def _video_records(
        self, token: str, now: datetime, videos: list[str]
    ) -> tuple[ProviderRecord, ...]:
        if not videos:
            return ()
        answer = self._get(
            f"{DATA_API}/videos",
            {
                "part": "snippet,contentDetails,status,statistics",
                "id": ",".join(videos),
                "maxResults": str(PAGE_VIDEOS),
                "fields": VIDEO_FIELDS,
            },
            token,
            DATA,
        )
        today = pacific_start(pacific_day(now))
        records = []
        for item in answer.get("items") or []:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            statistics = item.get("statistics") or {}
            metrics: dict[str, int | float] = {}
            unavailable: dict[str, str] = {}
            for name in ("viewCount", "likeCount", "commentCount"):
                value = _count(statistics.get(name))
                if value is None:
                    unavailable[name] = "not_returned"
                else:
                    metrics[name] = value
            snippet = item.get("snippet") or {}
            attributes: dict[str, str | int | bool | None] = {
                "published_at": snippet.get("publishedAt"),
                "duration": (item.get("contentDetails") or {}).get("duration"),
                "privacy_status": (item.get("status") or {}).get("privacyStatus"),
                "live_state": snippet.get("liveBroadcastContent"),
            }
            records.append(
                ProviderRecord(
                    item["id"],
                    today,
                    metrics,
                    None,
                    unavailable,
                    {name: value for name, value in attributes.items() if isinstance(value, str)},
                )
            )
        return tuple(records)

    def _total_records(
        self, token: str, through: datetime, uploads: Mapping[str, datetime | None]
    ) -> tuple[ProviderRecord, ...]:
        if not uploads:
            return ()
        last_day = pacific_day(through) - DAY
        window = {
            "ids": "channel==MINE",
            "startDate": HISTORY_START.isoformat(),
            "endDate": last_day.isoformat(),
            "filters": "video==" + ",".join(uploads),
        }
        # Google refuses the playlist metrics together with creatorContentType ("The query is
        # not supported", 011-C live check), so the catalog is read by video, and the product
        # type by video and content type with views only; F9 accepted both shapes.
        found = self._rows(
            self._get(
                ANALYTICS_URL,
                {**window, "metrics": ",".join(METRIC_NAMES), "dimensions": "video"},
                token,
                ANALYTICS,
            ),
            "video",
        )
        kinds = self._content_types(
            self._get(
                ANALYTICS_URL,
                {**window, "metrics": "views", "dimensions": "video,creatorContentType"},
                token,
                ANALYTICS,
            )
        )
        observed = pacific_start(last_day)
        records = []
        for video, published in uploads.items():
            metrics = found.get(video, {})
            unavailable = {name: "not_returned" for name in METRIC_NAMES if name not in metrics}
            provisional = (
                pacific_start(pacific_day(published)) + timedelta(hours=PROVISIONAL_HOURS)
                if published is not None
                else None
            )
            records.append(
                ProviderRecord(
                    video,
                    observed,
                    metrics,
                    product_type(kinds[video]) if video in kinds else None,
                    unavailable,
                    provisional_until=provisional,
                )
            )
        return tuple(records)

    # The content type of each video in a video,creatorContentType answer; the first row of a
    # video wins.
    @staticmethod
    def _content_types(answer: Mapping[str, Any]) -> dict[str, str]:
        headers = [
            item.get("name") for item in answer.get("columnHeaders") or [] if isinstance(item, dict)
        ]
        kinds: dict[str, str] = {}
        for row in answer.get("rows") or []:
            if not isinstance(row, list) or len(row) != len(headers):
                continue
            values = dict(zip(headers, row, strict=True))
            video, content = values.get("video"), values.get("creatorContentType")
            if isinstance(video, str) and isinstance(content, str):
                kinds.setdefault(video, content)
        return kinds

    # videos.list with the missing IDs: those it no longer returns are gone (D11).
    def confirm_deleted(
        self, access_token: str, *, stream: str, object_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not object_ids:
            return ()
        if len(object_ids) > PAGE_VIDEOS:
            raise ProviderError(ErrorKind.PERMANENT, "invalid_filters")
        answer = self._get(
            f"{DATA_API}/videos",
            {"part": "id", "id": ",".join(object_ids), "fields": "items/id"},
            access_token,
            DATA,
        )
        present = {item.get("id") for item in answer.get("items") or [] if isinstance(item, dict)}
        return tuple(item for item in object_ids if item not in present)


__all__ = ["CAPABILITY", "YouTubeProvider", "http_send"]
