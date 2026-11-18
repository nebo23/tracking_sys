"""Owner-run YouTube feasibility check (specification 011-B, D-058; entry review decision D16).

    python -m app.youtube_feasibility authorize [--scopes all|analytics-only] [--slot a|b]
                                                [--pkce | --pkce-wrong-verifier] [--no-browser]
                                                [--no-probe] [--max-calls N]
    python -m app.youtube_feasibility probe [--slot a|b] [--max-calls N]
    python -m app.youtube_feasibility refresh [--slot a|b]
    python -m app.youtube_feasibility check-access [--slot a|b]
    python -m app.youtube_feasibility revoke-test --confirm
    python -m app.youtube_feasibility forget

Every command takes --env-file PATH (default: the project's .env) before the command name.
--max-calls (default 120) bounds the reads of a probe; it may be given before the command name
or after authorize and probe.

It establishes, with the owner's Google Cloud project in Testing and one owner-controlled
channel, what Google's OAuth 2.0 web server flow, the YouTube Data API v3 and the YouTube
Analytics API actually return (acceptance criterion 1; questions F1-F14 of the entry review).
It is read-only: it requests only youtube.readonly and yt-analytics.readonly, makes only token,
revocation and GET requests, and never uploads, edits, comments on or changes anything.
revoke-test, the only command that ends access, runs only with --confirm.

The client ID and secret come from the ignored environment file. The browser consent returns
to the registered loopback redirect address, where the tool listens for one answer, so the API
server must not be running on that port. Refresh tokens are stored in the same environment
file (as the D-022 Gmail helper stores its refresh token) and are never printed; forget
removes them. Evidence is redacted before it is written to the ignored local-data folder next
to the environment file: it holds field and metric names, availability, value types, error
codes and reasons, scopes, counts and day offsets, but no token, code, secret, channel or video
ID, title or metric value. Day rows are kept only as keyed digests, whose key stays in the same
local folder, so that a later probe can tell whether recent days changed.
"""

import argparse
import base64
import hashlib
import hmac
import http.server
import json
import re
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from dotenv import dotenv_values, set_key, unset_key

from app.config import PROJECT_ROOT

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
DATA_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPE_SETS = {"all": (DATA_SCOPE, ANALYTICS_SCOPE), "analytics-only": (ANALYTICS_SCOPE,)}
CLIENT_ID, CLIENT_SECRET, REDIRECT = (
    "TRACKING_YOUTUBE_CLIENT_ID",
    "TRACKING_YOUTUBE_CLIENT_SECRET",
    "TRACKING_YOUTUBE_REDIRECT_URI",
)
DEFAULT_REDIRECT = "http://127.0.0.1:8000/connectors/oauth/callback"
SLOTS = {
    "a": ("TRACKING_YOUTUBE_FEASIBILITY_REFRESH_TOKEN", "TRACKING_YOUTUBE_FEASIBILITY_ISSUED_AT"),
    "b": (
        "TRACKING_YOUTUBE_FEASIBILITY_REFRESH_TOKEN_B",
        "TRACKING_YOUTUBE_FEASIBILITY_ISSUED_AT_B",
    ),
}
PACIFIC = ZoneInfo("America/Los_Angeles")
TIMEOUT = 20
CALLBACK_TIMEOUT = 300
REVOCATION_WAIT = 10
DEFAULT_MAX_CALLS = 120
UPLOAD_PAGES = 4
VIDEO_BATCH = 50
# The proposed catalog of entry review section 3.2 (D8). The check records what the Analytics
# API actually returns for each name.
CATALOG = (
    "views",
    "engagedViews",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "dislikes",
    "comments",
    "shares",
    "subscribersGained",
    "subscribersLost",
    "videosAddedToPlaylists",
    "videosRemovedFromPlaylists",
)
VIDEO_STATISTICS = ("viewCount", "likeCount", "dislikeCount", "favoriteCount", "commentCount")
CHANNEL_STATISTICS = ("viewCount", "subscriberCount", "hiddenSubscriberCount", "videoCount")
HISTORY_DAYS = (90, 365, 730, 1095, 1825, 3650)
HISTORY_WINDOW = 30
BEFORE_YOUTUBE = "2005-02-14"
DOCUMENTED_START = "2008-07-01"
CONTENT_TYPES_START = "2019-01-01"
DAY_WINDOW = 30
# Reasons with which Google answers a spent quota or a rate limit; the probe stops on them.
STOP_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded"}
CONSENT_ERRORS = {
    "access_denied",
    "admin_policy_enforced",
    "invalid_request",
    "invalid_scope",
    "org_internal",
    "unauthorized_client",
}
_ISO_DURATION = re.compile(r"P(?=\d|T\d)(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?")


# Raised for any failure; messages are fixed and never contain secrets or URLs.
class FeasibilityFailed(Exception):
    """A feasibility step failed; the message is safe to print."""


@dataclass
class Reply:
    status: int
    body: Any
    headers: Mapping[str, str]


# Send one request and return the decoded JSON reply. Network failures raise
# FeasibilityFailed without the URL or headers, which carry tokens.
def http_send(
    method: str,
    url: str,
    form: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Reply:
    data = None if form is None else urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(url, data=data, method=method)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    if form is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status, raw, answer = response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        status, raw, answer = error.code, error.read(), dict(error.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError):
        raise FeasibilityFailed("A Google endpoint did not answer.") from None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = {"error": {"status": "unreadable_response"}}
    return Reply(status, body, answer)


Transport = Callable[[str, str, Mapping[str, str] | None, Mapping[str, str] | None], Reply]


@dataclass(frozen=True)
class AppConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str


# The Web application client and its registered loopback redirect address (entry review
# sections 8 and 10). Only an http loopback address with a port and a path is accepted,
# because the tool itself listens there for the answer.
def app_config(values: Mapping[str, str | None]) -> AppConfig:
    client_id = (values.get(CLIENT_ID) or "").strip()
    client_secret = (values.get(CLIENT_SECRET) or "").strip()
    redirect = (values.get(REDIRECT) or "").strip() or DEFAULT_REDIRECT
    if not client_id.endswith(".apps.googleusercontent.com") or not client_secret:
        raise FeasibilityFailed(
            f"Set {CLIENT_ID} (a Web application client ID) and {CLIENT_SECRET} in the "
            "environment file."
        )
    parts = urllib.parse.urlsplit(redirect)
    try:
        port = parts.port
    except ValueError:
        port = None
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "localhost"}
        or not port
        or not parts.path.strip("/")
        or parts.query
        or parts.fragment
        or parts.username
    ):
        raise FeasibilityFailed(
            "The redirect URI must be an http loopback address with a port and a path, "
            "exactly as registered on the client."
        )
    return AppConfig(client_id, client_secret, redirect)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


# The web server authorization URL (G-1 of the entry review): offline access, and a consent
# prompt so that every authorization returns a refresh token (D4). PKCE parameters are added
# only for the optional F2 check, which records whether Google accepts or enforces them.
def authorization_url(
    config: AppConfig, scopes: tuple[str, ...], state: str, challenge: str | None = None
) -> str:
    query = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    if challenge is not None:
        query |= {"code_challenge": challenge, "code_challenge_method": "S256"}
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"


class Receiver(Protocol):
    def wait(self, timeout: float) -> str: ...


# An HTTP server that owns its port (R011-09). http.server.HTTPServer sets SO_REUSEADDR, and
# on Windows that lets a second socket bind a port that is already in use, so the tool could
# listen next to a running API server while Google's answer reached the API. CPython's
# socket.create_server leaves SO_REUSEADDR off on Windows for the same reason; here it is off
# and SO_EXCLUSIVEADDRUSE is on, so a busy port is refused.
class _LoopbackServer(http.server.HTTPServer):
    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.allow_reuse_address = False
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


# Listens on the loopback redirect address and keeps the first request to its path. Other
# paths, such as a browser's favicon request, get 404 and the wait continues. Request lines
# carry the authorization code, so nothing is logged.
class CallbackReceiver:
    def __init__(self, host: str, port: int, path: str) -> None:
        self.path, self.received = path.rstrip("/"), None
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server naming)
                if urllib.parse.urlsplit(self.path).path.rstrip("/") != receiver.path:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                receiver.received = self.path
                body = b"The YouTube feasibility check received the answer. You can close this tab."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        try:
            self.server = _LoopbackServer((host, port), Handler)
        except OSError:
            raise FeasibilityFailed(
                "The redirect port is in use; stop the API server and run the command again."
            ) from None
        self.port = self.server.server_address[1]

    def wait(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        try:
            while self.received is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FeasibilityFailed("No answer reached the redirect address in time.")
                self.server.timeout = min(remaining, 1.0)
                self.server.handle_request()
        finally:
            self.server.server_close()
        return self.received


def loopback_receiver(config: AppConfig) -> Receiver:
    parts = urllib.parse.urlsplit(config.redirect_uri)
    return CallbackReceiver(parts.hostname or "127.0.0.1", parts.port or 0, parts.path)


# The authorization code from the redirect request, after checking the state. A refused or
# cancelled consent returns its closed error code instead.
def code_from_callback(target: str, state: str) -> tuple[str | None, str | None]:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(target).query)
    if query.get("error"):
        error = query["error"][0]
        return None, error if error in CONSENT_ERRORS else "other"
    if not hmac.compare_digest(query.get("state", [""])[0], state):
        raise FeasibilityFailed("The state does not match this authorization.")
    code = query.get("code", [""])[0]
    if not code:
        raise FeasibilityFailed("The answer carries no authorization code.")
    return code, None


_WORD = re.compile(r"[A-Za-z0-9_\-./]{6,}")


# Whether a word in a provider message looks like an identifier: it contains a digit or an
# underscore, or it is long and has inner capitals or hyphens.
def _identifying(word: str) -> bool:
    return (
        any(ch.isdigit() for ch in word)
        or "_" in word
        or (len(word) >= 10 and any(ch.isupper() for ch in word[1:]))
        or ("-" in word and len(word) >= 12)
    )


# A provider message with known identifiers and identifier-like words replaced.
def redact(text: Any, known: frozenset[str] | set[str] = frozenset()) -> str | None:
    if not isinstance(text, str):
        return None
    for value in sorted(known, key=len, reverse=True):
        if value:
            text = text.replace(value, "<id>")
    text = _WORD.sub(lambda match: "<id>" if _identifying(match.group(0)) else match.group(0), text)
    return text[:200]


# A Google error reduced to its codes and reasons: the token endpoint's string form
# ({"error": "invalid_grant"}) or the API form ({"error": {"code", "status", "errors"}}).
# Google's status name is kept as error_status, so it never replaces the HTTP status.
def error_summary(body: Any, known: frozenset[str] | set[str] = frozenset()) -> dict[str, Any]:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, str):
        return {
            "error": error if re.fullmatch(r"[a-z_]{1,40}", error) else "other",
            "description": redact(body.get("error_description"), known),
        }
    if not isinstance(error, dict):
        return {"code": None, "error_status": None, "reasons": [], "message": None}
    reasons = sorted(
        {
            str(item["reason"])
            for item in error.get("errors") or []
            if isinstance(item, dict) and item.get("reason")
        }
    )
    return {
        "code": error.get("code"),
        "error_status": error.get("status"),
        "reasons": reasons,
        "message": redact(error.get("message"), known),
    }


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _age_days(timestamp: Any, now: datetime) -> int | None:
    if not isinstance(timestamp, str):
        return None
    try:
        moment = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return (now - moment).days


# Read-only probe session: counts calls per API, remembers the identifiers it has seen so
# that they never reach the evidence, and stops reading on a quota or rate-limit answer, when
# the call budget is spent, or when Google does not answer (R011-04), so that the evidence of
# what was read is still written.
class Probe:
    def __init__(self, transport: Transport, access_token: str, max_calls: int) -> None:
        self.transport, self._token, self.max_calls = transport, access_token, max_calls
        self.calls = {"data": 0, "analytics": 0, "invalid_token": 0}
        self.stopped: str | None = None
        self.known: set[str] = set()
        self._unanswered = False

    def __repr__(self) -> str:
        return f"Probe(calls={self.calls})"

    @property
    def total(self) -> int:
        return sum(self.calls.values())

    def get(self, api: str, url: str, token: str | None = None) -> Reply | None:
        if self.stopped or self.total >= self.max_calls:
            return None
        self.calls[api] += 1
        bearer = token if token is not None else self._token
        try:
            reply = self.transport("GET", url, None, {"Authorization": f"Bearer {bearer}"})
        except FeasibilityFailed:
            self.stopped, self._unanswered = "no_answer", True
            return None
        reasons = set(error_summary(reply.body).get("reasons") or [])
        if token is None and (reply.status == 429 or reasons & STOP_REASONS):
            self.stopped = "quota_or_rate_limit"
        return reply

    # The outcome of a call that did not succeed. The call that got no answer is reported as
    # such; the calls skipped after it are not_requested.
    def failure(self, reply: Reply | None) -> dict[str, Any]:
        if reply is None:
            if self._unanswered:
                self._unanswered = False
                return {"outcome": "no_answer"}
            return {"outcome": "not_requested"}
        return {"outcome": "error", "status": reply.status, **error_summary(reply.body, self.known)}


def _data_url(resource: str, params: Mapping[str, str]) -> str:
    return f"{DATA_API}/{resource}?{urllib.parse.urlencode(params)}"


def _analytics_url(params: Mapping[str, str]) -> str:
    return f"{ANALYTICS_URL}?{urllib.parse.urlencode({'ids': 'channel==MINE', **params})}"


def _ok(reply: Reply | None) -> bool:
    return reply is not None and reply.status < 400 and isinstance(reply.body, dict)


# F4: what channels.list?mine=true returns for the authorized channel.
def _probe_channel(probe: Probe) -> tuple[dict[str, Any], str | None, Any]:
    reply = probe.get(
        "data",
        _data_url("channels", {"part": "id,statistics,contentDetails,status", "mine": "true"}),
    )
    if not _ok(reply):
        return {"channel": probe.failure(reply)}, None, None
    items = reply.body.get("items") or []
    record: dict[str, Any] = {"outcome": "ok", "items": len(items)}
    if not items:
        return {"channel": record}, None, None
    item = items[0]
    probe.known.add(str(item.get("id")))
    stats = item.get("statistics") or {}
    uploads = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    if uploads:
        probe.known.add(str(uploads))
    hidden = stats.get("hiddenSubscriberCount")
    record |= {
        "statistics": {
            name: value_type(stats[name]) if name in stats else "absent"
            for name in CHANNEL_STATISTICS
        },
        "hidden_subscriber_count": hidden if isinstance(hidden, bool) else None,
        "uploads_playlist": bool(uploads),
        "privacy_status": (item.get("status") or {}).get("privacyStatus"),
    }
    return {"channel": record}, str(uploads) if uploads else None, stats.get("videoCount")


# F5: the uploads playlist, page by page, with the privacy status of each item.
def _probe_uploads(probe: Probe, uploads: str) -> tuple[dict[str, Any], list[str]]:
    ids: list[str] = []
    privacy: Counter[str] = Counter()
    pages, token = 0, None
    failure: dict[str, Any] | None = None
    while pages < UPLOAD_PAGES:
        params = {"part": "contentDetails,status", "playlistId": uploads, "maxResults": "50"}
        if token:
            params["pageToken"] = token
        reply = probe.get("data", _data_url("playlistItems", params))
        if not _ok(reply):
            failure = probe.failure(reply)
            break
        pages += 1
        for item in reply.body.get("items") or []:
            video = (item.get("contentDetails") or {}).get("videoId")
            if video:
                ids.append(str(video))
                probe.known.add(str(video))
            privacy[(item.get("status") or {}).get("privacyStatus") or "absent"] += 1
        token = reply.body.get("nextPageToken")
        if not token:
            break
    if pages == 0:
        return {"uploads": failure or {"outcome": "not_requested"}}, []
    record = {
        "outcome": "ok",
        "pages": pages,
        "items": len(ids),
        "privacy_status": dict(sorted(privacy.items())),
        "more_pages": bool(token),
    }
    if failure is not None:
        record["later_page"] = failure
    return {"uploads": record}, ids


# Up to `count` distinct IDs from the uploads, repeated in order when the channel has fewer.
def _limit_ids(ids: list[str], count: int) -> list[str]:
    distinct = list(dict.fromkeys(ids))
    return [distinct[index % len(distinct)] for index in range(count)] if distinct else []


# The ID-limit check of one method (F5, R011-02): 50 IDs as the control, then 51. A refusal
# (400) is conclusive; an acceptance is conclusive only when every ID sent was distinct,
# because a server may merge repeated IDs and so answer fewer than were sent.
def _id_limit(probe: Probe, resource: str, part: str, ids: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for count in (50, 51):
        sent = _limit_ids(ids, count)
        reply = probe.get("data", _data_url(resource, {"part": part, "id": ",".join(sent)}))
        record: dict[str, Any] = {"ids_sent": len(sent), "distinct_ids": len(set(sent))}
        if _ok(reply):
            record |= {
                "outcome": "ok",
                "returned": len(reply.body.get("items") or []),
                "conclusive": len(set(sent)) == len(sent),
            }
        else:
            record |= {
                **probe.failure(reply),
                "conclusive": reply is not None and reply.status == 400,
            }
        out[str(count)] = record
    return out


# F5: videos.list with a fields filter that leaves out titles, the ID limits of videos.list
# and videos:batchGetStats (GET with part and a comma-separated id, as its reference page
# states, in its own quota bucket). The public items are compared with the channel's
# videoCount only when every upload was read in one batch (R011-05).
def _probe_videos(
    probe: Probe, ids: list[str], public_count: Any, now: datetime, complete: bool = True
) -> dict[str, Any]:
    if not ids:
        return {"videos": {"outcome": "no_videos"}}
    batch = ids[:VIDEO_BATCH]
    fields = (
        "items(id,snippet(publishedAt,liveBroadcastContent),contentDetails/duration,"
        "status/privacyStatus,statistics)"
    )
    reply = probe.get(
        "data",
        _data_url(
            "videos",
            {
                "part": "snippet,contentDetails,status,statistics",
                "id": ",".join(batch),
                "fields": fields,
            },
        ),
    )
    result: dict[str, Any] = {}
    if _ok(reply):
        items = reply.body.get("items") or []
        present = Counter()
        privacy: Counter[str] = Counter()
        live: Counter[str] = Counter()
        ages: list[int] = []
        durations = 0
        for item in items:
            stats = item.get("statistics") or {}
            present.update(name for name in VIDEO_STATISTICS if name in stats)
            privacy[(item.get("status") or {}).get("privacyStatus") or "absent"] += 1
            snippet = item.get("snippet") or {}
            live[snippet.get("liveBroadcastContent") or "absent"] += 1
            duration = str((item.get("contentDetails") or {}).get("duration") or "")
            durations += bool(_ISO_DURATION.fullmatch(duration))
            age = _age_days(snippet.get("publishedAt"), now)
            if age is not None:
                ages.append(age)
        public = privacy.get("public", 0)
        if not complete or len(ids) > VIDEO_BATCH:
            skipped: str | None = "inventory_not_read_in_one_batch"
        elif len(items) != len(batch):
            skipped = "videos_missing_from_answer"
        elif not isinstance(public_count, str):
            skipped = "video_count_missing"
        else:
            skipped = None
        result["videos"] = {
            "outcome": "ok",
            "requested": len(batch),
            "returned": len(items),
            "statistics_present": {name: present.get(name, 0) for name in VIDEO_STATISTICS},
            "privacy_status": dict(sorted(privacy.items())),
            "live_broadcast_content": dict(sorted(live.items())),
            "iso_durations": durations,
            "age_days_range": [min(ages), max(ages)] if ages else None,
            "title_returned": any("title" in (item.get("snippet") or {}) for item in items),
            "public_items_equal_video_count": (
                str(public) == public_count if skipped is None else None
            ),
        }
        if skipped is not None:
            result["videos"]["public_items_comparison_skipped"] = skipped
    else:
        result["videos"] = probe.failure(reply)
    result["videos_id_limit"] = _id_limit(probe, "videos", "id", ids)
    stats = probe.get(
        "data", _data_url("videos:batchGetStats", {"part": "statistics", "id": ",".join(batch)})
    )
    if _ok(stats):
        result["batch_get_stats"] = {
            "outcome": "ok",
            "items": len(stats.body.get("items") or []),
            "top_level_keys": sorted(stats.body),
            "summary_keys": sorted(stats.body.get("summary") or {}),
        }
    else:
        result["batch_get_stats"] = probe.failure(stats)
    result["batch_get_stats_id_limit"] = _id_limit(probe, "videos:batchGetStats", "id", ids)
    return result


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _digest(key: bytes, values: list[Any]) -> str:
    message = json.dumps(values, separators=(",", ":")).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:20]


def _rows(reply: Reply) -> list[list[Any]]:
    rows = reply.body.get("rows") if isinstance(reply.body, dict) else None
    return [row for row in rows or [] if isinstance(row, list) and row]


# One analytics answer reduced to its outcome: rows or empty, the column names, and the
# categorical values of one column when asked (never IDs or metric values).
def _table(
    probe: Probe, reply: Reply | None, requested: int | None = None, column: str | None = None
) -> dict[str, Any]:
    if not _ok(reply):
        return probe.failure(reply)
    rows = _rows(reply)
    names = [str(h.get("name")) for h in reply.body.get("columnHeaders") or []]
    record: dict[str, Any] = {
        "outcome": "rows" if rows else "empty",
        "rows": len(rows),
        "rows_key_present": "rows" in reply.body,
        "columns": names,
    }
    if requested is not None:
        record["requested_videos"] = requested
    if column in names:
        index = names.index(column)
        record["values_of_" + column] = sorted({str(row[index]) for row in rows})
    return record


# F6, F8: the channel day report for the last 30 Pacific days through today, with the whole
# proposed catalog; one metric at a time if the combined query is refused. The combined
# failure is recorded first, so a call without an answer keeps its own label, and no fallback
# is attempted once the probe has stopped (R011-10).
def _probe_day_report(
    probe: Probe, today: date, key: bytes, previous: Mapping[str, str] | None
) -> dict[str, Any]:
    start = today - timedelta(days=DAY_WINDOW)
    window = {"startDate": start.isoformat(), "endDate": today.isoformat()}
    reply = probe.get(
        "analytics",
        _analytics_url(
            {**window, "metrics": ",".join(CATALOG), "dimensions": "day", "sort": "day"}
        ),
    )
    if not _ok(reply):
        combined = probe.failure(reply)
        if probe.stopped:
            return {"day_report": {"combined": combined}}
        per_metric = {
            name: _table(
                probe,
                probe.get(
                    "analytics", _analytics_url({**window, "metrics": name, "dimensions": "day"})
                ),
            )
            for name in CATALOG
        }
        return {"day_report": {"combined": combined, "per_metric": per_metric}}
    headers = reply.body.get("columnHeaders") or []
    names = [str(h.get("name")) for h in headers]
    rows = _rows(reply)
    days = sorted(day for day in (_day(row[0]) for row in rows) if day is not None)
    views = names.index("views") if "views" in names else None
    digests = {str(row[0]): _digest(key, row[1:]) for row in rows}
    record: dict[str, Any] = {
        "outcome": "rows" if rows else "empty",
        "requested_days": DAY_WINDOW + 1,
        "rows": len(rows),
        "rows_key_present": "rows" in reply.body,
        "column_headers": [
            {
                "name": h.get("name"),
                "column_type": h.get("columnType"),
                "data_type": h.get("dataType"),
            }
            for h in headers
        ],
        "value_types": {
            name: sorted({value_type(row[index]) for row in rows if index < len(row)})
            for index, name in enumerate(names)
        },
        "first_day_offset": (today - days[0]).days if days else None,
        "last_day_offset": (today - days[-1]).days if days else None,
        "missing_days_within_range": (
            (days[-1] - days[0]).days + 1 - len(set(days)) if days else None
        ),
        "zero_view_days": sum(1 for row in rows if views is not None and row[views] == 0),
        "digests": digests,
    }
    if previous is not None:
        common = sorted(set(previous) & set(digests))
        record["changed_since_previous_probe"] = {
            "compared_days": len(common),
            "changed_day_offsets": [
                (today - date.fromisoformat(day)).days
                for day in common
                if previous[day] != digests[day]
            ],
        }
    return {"day_report": record}


def _positive(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def _month_start(text: str) -> date | None:
    try:
        year, month = (int(part) for part in text.split("-")[:2])
        return date(year, month, 1)
    except ValueError:
        return None


def _month_offset(start: date, today: date) -> int:
    return (today.year - start.year) * 12 + today.month - start.month


# A day-dimension answer with the number of its days that had views (a count, not a value).
def _day_window(probe: Probe, reply: Reply | None) -> dict[str, Any]:
    record = _table(probe, reply)
    if _ok(reply):
        names = [str(h.get("name")) for h in reply.body.get("columnHeaders") or []]
        views = names.index("views") if "views" in names else None
        record["days_with_views"] = sum(
            1 for row in _rows(reply) if views is not None and _positive(row[views])
        )
    return record


# F10: 30-day day windows ending at growing depths (whether old ranges still come back as
# day rows), a start before YouTube existed, monthly totals since the documented start (a
# month report needs first-of-month start and end dates), and the day rows of the earliest
# month with views. A single day without views answers like a day without data, so the
# monthly totals tell the two apart.
def _probe_history(probe: Probe, today: date) -> dict[str, Any]:
    windows = {}
    for days in HISTORY_DAYS:
        end = today - timedelta(days=days)
        start = end - timedelta(days=HISTORY_WINDOW - 1)
        windows[str(days)] = _day_window(
            probe,
            probe.get(
                "analytics",
                _analytics_url(
                    {
                        "startDate": start.isoformat(),
                        "endDate": end.isoformat(),
                        "metrics": "views",
                        "dimensions": "day",
                    }
                ),
            ),
        )
    before = _table(
        probe,
        probe.get(
            "analytics",
            _analytics_url(
                {"startDate": BEFORE_YOUTUBE, "endDate": today.isoformat(), "metrics": "views"}
            ),
        ),
    )
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    reply = probe.get(
        "analytics",
        _analytics_url(
            {
                "startDate": DOCUMENTED_START,
                "endDate": last_month.isoformat(),
                "metrics": "views",
                "dimensions": "month",
                "sort": "month",
            }
        ),
    )
    months = _table(probe, reply)
    if _ok(reply):
        names = [str(h.get("name")) for h in reply.body.get("columnHeaders") or []]
        views = names.index("views") if "views" in names else None
        rows = [(_month_start(str(row[0])), row) for row in _rows(reply)]
        listed = sorted(start for start, _ in rows if start is not None)
        active = sorted(
            start
            for start, row in rows
            if start is not None and views is not None and _positive(row[views])
        )
        months |= {
            "earliest_month_offset": _month_offset(listed[0], today) if listed else None,
            "months_with_views": len(active),
            "earliest_month_with_views_offset": (
                _month_offset(active[0], today) if active else None
            ),
        }
        if active:
            first = active[0]
            last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            months["earliest_month_with_views_days"] = _day_window(
                probe,
                probe.get(
                    "analytics",
                    _analytics_url(
                        {
                            "startDate": first.isoformat(),
                            "endDate": last.isoformat(),
                            "metrics": "views",
                            "dimensions": "day",
                        }
                    ),
                ),
            )
    return {
        "history_windows": windows,
        "start_before_youtube": before,
        "months_since_documented_start": months,
        "day_density": _probe_density(probe, today),
    }


# F8: whether day reports list every day of the range or only days with data, and whether
# that depends on how recent the range is or on the metrics requested. The recent window is
# read with views only, and a window ending 365 days ago with the whole catalog.
def _probe_density(probe: Probe, today: date) -> dict[str, Any]:
    old_end = today - timedelta(days=365)
    reads = {
        "recent_views_only": (today - timedelta(days=DAY_WINDOW), today, "views"),
        "old_full_catalog": (
            old_end - timedelta(days=HISTORY_WINDOW - 1),
            old_end,
            ",".join(CATALOG),
        ),
    }
    out = {}
    for name, (start, end, metrics) in reads.items():
        out[name] = _day_window(
            probe,
            probe.get(
                "analytics",
                _analytics_url(
                    {
                        "startDate": start.isoformat(),
                        "endDate": end.isoformat(),
                        "metrics": metrics,
                        "dimensions": "day",
                    }
                ),
            ),
        )
        out[name]["requested_days"] = (end - start).days + 1
    return out


# F9: per-video lifetime reports by filter, with the content type, the top-200 report, and
# the channel by content type. Video reports are sent with sort and maxResults, which entry
# review YT-13 records as required (R011-01); one unsorted variant shows whether they are.
def _probe_video_reports(probe: Probe, ids: list[str], today: date) -> dict[str, Any]:
    end = today.isoformat()
    out: dict[str, Any] = {}
    if ids:
        sample = ids[:VIDEO_BATCH]
        video_filter = "video==" + ",".join(sample)
        lifetime = {
            "startDate": DOCUMENTED_START,
            "endDate": end,
            "filters": video_filter,
            "sort": "-views",
            "maxResults": "200",
        }
        reply = probe.get(
            "analytics",
            _analytics_url({**lifetime, "metrics": ",".join(CATALOG), "dimensions": "video"}),
        )
        out["video_filter_catalog"] = _table(probe, reply, len(sample))
        if not _ok(reply) and not probe.stopped:
            out["video_filter_two_metrics"] = _table(
                probe,
                probe.get(
                    "analytics",
                    _analytics_url(
                        {
                            **lifetime,
                            "metrics": "views,estimatedMinutesWatched",
                            "dimensions": "video",
                        }
                    ),
                ),
                len(sample),
            )
        out["video_and_content_type"] = _table(
            probe,
            probe.get(
                "analytics",
                _analytics_url(
                    {**lifetime, "metrics": "views", "dimensions": "video,creatorContentType"}
                ),
            ),
            len(sample),
            "creatorContentType",
        )
        unsorted = {key: lifetime[key] for key in ("startDate", "endDate", "filters")}
        out["video_filter_unsorted"] = _table(
            probe,
            probe.get(
                "analytics",
                _analytics_url({**unsorted, "metrics": "views", "dimensions": "video"}),
            ),
            len(sample),
        )
    else:
        out["video_filter_catalog"] = {"outcome": "no_videos"}
    out["top_videos"] = _table(
        probe,
        probe.get(
            "analytics",
            _analytics_url(
                {
                    "startDate": DOCUMENTED_START,
                    "endDate": end,
                    "metrics": "views,estimatedMinutesWatched",
                    "dimensions": "video",
                    "sort": "-views",
                    "maxResults": "200",
                }
            ),
        ),
    )
    out["channel_by_content_type"] = _table(
        probe,
        probe.get(
            "analytics",
            _analytics_url(
                {
                    "startDate": CONTENT_TYPES_START,
                    "endDate": end,
                    "metrics": "views",
                    "dimensions": "creatorContentType",
                }
            ),
        ),
        None,
        "creatorContentType",
    )
    return {"video_reports": out}


# F14: what each API answers to an invalid token.
def _probe_invalid_token(probe: Probe, today: date) -> dict[str, Any]:
    day = today.isoformat()
    urls = {
        "data": _data_url("channels", {"part": "id", "mine": "true"}),
        "analytics": _analytics_url({"startDate": day, "endDate": day, "metrics": "views"}),
    }
    out = {}
    for api, url in urls.items():
        reply = probe.get("invalid_token", url, token="invalid-feasibility-token")
        out[api] = (
            probe.failure(None)
            if reply is None
            else {"status": reply.status, **error_summary(reply.body, probe.known)}
        )
    return {"invalid_token": out}


def probe_channel(
    transport: Transport,
    access_token: str,
    now: datetime,
    max_calls: int = DEFAULT_MAX_CALLS,
    digest_key: bytes = b"",
    previous: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    probe = Probe(transport, access_token, max_calls)
    local = now.astimezone(PACIFIC)
    today = local.date()
    evidence: dict[str, Any] = {
        "schema": "youtube-feasibility-1",
        "generated_at": now.isoformat(timespec="seconds"),
        "pacific_utc_offset_hours": (local.utcoffset() or timedelta()).total_seconds() / 3600,
    }
    channel, uploads, public_count = _probe_channel(probe)
    evidence |= channel
    ids: list[str] = []
    if uploads:
        uploads_record, ids = _probe_uploads(probe, uploads)
        evidence |= uploads_record
        listing = uploads_record["uploads"]
        complete = (
            listing.get("outcome") == "ok"
            and not listing.get("more_pages")
            and "later_page" not in listing
        )
        evidence |= _probe_videos(probe, ids, public_count, now, complete)
    evidence |= _probe_day_report(probe, today, digest_key or secrets.token_bytes(32), previous)
    evidence |= _probe_history(probe, today)
    evidence |= _probe_video_reports(probe, ids, today)
    evidence |= _probe_invalid_token(probe, today)
    evidence |= {"calls": dict(probe.calls), "stopped": probe.stopped}
    return evidence


class _Recorded(Exception):
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        super().__init__("recorded failure")


# The token answer reduced to its field names, granted scopes and lifetimes (F1).
def _token_record(body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fields": sorted(body),
        "granted_scopes": sorted(str(body.get("scope") or "").split()),
        "token_type": body.get("token_type"),
        "expires_in": body.get("expires_in"),
        "refresh_token_returned": bool(body.get("refresh_token")),
        "refresh_token_expires_in": body.get("refresh_token_expires_in"),
    }


def exchange_code(
    transport: Transport, config: AppConfig, code: str, verifier: str | None
) -> tuple[dict[str, str | None], dict[str, Any]]:
    form = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": config.redirect_uri,
    }
    if verifier is not None:
        form["code_verifier"] = verifier
    reply = transport("POST", TOKEN_URL, form, None)
    record: dict[str, Any] = {"code_exchange_status": reply.status}
    body = reply.body if isinstance(reply.body, dict) else {}
    if reply.status >= 400 or not body.get("access_token"):
        record["code_exchange_error"] = error_summary(reply.body)
        raise _Recorded(record)
    record |= _token_record(body)
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token"),
    }, record


def refresh_access(
    transport: Transport, config: AppConfig, refresh_token: str
) -> tuple[str | None, dict[str, Any]]:
    reply = transport(
        "POST",
        TOKEN_URL,
        {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        None,
    )
    body = reply.body if isinstance(reply.body, dict) else {}
    if reply.status >= 400 or not body.get("access_token"):
        return None, {"status": reply.status, **error_summary(reply.body)}
    return str(body["access_token"]), {"status": reply.status, **_token_record(body)}


def revoke(transport: Transport, token: str) -> dict[str, Any]:
    reply = transport("POST", REVOKE_URL, {"token": token}, None)
    record: dict[str, Any] = {"status": reply.status}
    if reply.status >= 400:
        record |= error_summary(reply.body)
    return record


# Store values in the environment file (quoted) without echoing any of them.
def store(env_file: Path, values: Mapping[str, str]) -> None:
    for name, value in values.items():
        set_key(env_file, name, value, quote_mode="always")


def write_evidence(directory: Path, name: str, evidence: Mapping[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{name}-{stamp}.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# The local key of the day digests, created once in the evidence folder.
def digest_key(directory: Path) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "digest-key"
    if not path.is_file():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return bytes.fromhex(path.read_text(encoding="utf-8").strip())


# The day digests of the most recent earlier probe, if any.
def latest_digests(directory: Path) -> dict[str, str] | None:
    for path in sorted(directory.glob("probe-*.json"), reverse=True):
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        digests = (evidence.get("day_report") or {}).get("digests")
        if isinstance(digests, dict):
            return {str(day): str(value) for day, value in digests.items()}
    return None


def _summary(evidence: Mapping[str, Any]) -> list[str]:
    channel = evidence.get("channel") or {}
    day = evidence.get("day_report") or {}
    reports = evidence.get("video_reports") or {}
    lines = [
        f"Calls made: {evidence.get('calls')}; stopped: {evidence.get('stopped')}",
        f"Channel: {channel.get('outcome')} ({channel.get('items', 0)} item(s)); uploads listed: "
        f"{(evidence.get('uploads') or {}).get('items', 0)}",
        f"Day report: {day.get('outcome', (day.get('combined') or {}).get('outcome'))}, "
        f"{day.get('rows', 0)} row(s), last day {day.get('last_day_offset')} day(s) before today "
        "(Pacific)",
        "Video reports: "
        + ", ".join(f"{name} {value.get('outcome')}" for name, value in sorted(reports.items())),
    ]
    return lines


# Command-line entry point for the owner. Returns a process exit code.
def main(
    argv: list[str] | None = None,
    transport: Transport = http_send,
    receiver_factory: Callable[[AppConfig], Receiver] = loopback_receiver,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description="YouTube feasibility check (read-only).")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    commands = parser.add_subparsers(dest="command", required=True)
    authorize = commands.add_parser("authorize", help="Consent, store the token, then probe.")
    authorize.add_argument("--scopes", choices=sorted(SCOPE_SETS), default="all")
    authorize.add_argument("--slot", choices=sorted(SLOTS), default="a")
    mode = authorize.add_mutually_exclusive_group()
    mode.add_argument("--pkce", action="store_true", help="Send PKCE parameters (F2).")
    mode.add_argument(
        "--pkce-wrong-verifier", action="store_true", help="Check whether PKCE is enforced (F2)."
    )
    authorize.add_argument("--no-browser", action="store_true", help="Print the URL only.")
    authorize.add_argument("--no-probe", action="store_true", help="Do not read the channel.")
    authorize.add_argument("--timeout", type=int, default=CALLBACK_TIMEOUT)
    subcommands = {"authorize": authorize}
    for name, text in (
        ("probe", "Read the channel with the stored refresh token."),
        ("refresh", "Refresh the stored token (F3)."),
        ("check-access", "Refresh after removing access in the Google account (F13)."),
    ):
        subcommands[name] = commands.add_parser(name, help=text)
        subcommands[name].add_argument("--slot", choices=sorted(SLOTS), default="a")
    # --max-calls is also accepted after the commands that read the channel (R011-06); the
    # suppressed default keeps the value given before the command, or the default.
    for name in ("authorize", "probe"):
        subcommands[name].add_argument("--max-calls", type=int, default=argparse.SUPPRESS)
    revoke_test = commands.add_parser(
        "revoke-test", help="Revoke slot a and check slot b (F12). Ends access."
    )
    revoke_test.add_argument("--confirm", action="store_true")
    commands.add_parser("forget", help="Remove the stored tokens from the environment file.")
    options = parser.parse_args(argv)
    env_file: Path = options.env_file
    output = env_file.parent / "local-data" / "youtube-feasibility"
    now = datetime.now(UTC)
    try:
        if not env_file.is_file():
            raise FeasibilityFailed("The environment file does not exist.")
        values = dotenv_values(env_file)
        if options.command == "forget":
            for names in SLOTS.values():
                for name in names:
                    if values.get(name) is not None:
                        unset_key(env_file, name)
            print("Removed the stored feasibility tokens (if any).")
            return 0
        config = app_config(values)
        if options.command == "authorize":
            return _authorize(options, config, env_file, output, now, transport, receiver_factory)
        if options.command == "revoke-test":
            return _revoke_test(options, config, env_file, output, transport, sleep)
        name, issued = SLOTS[options.slot]
        token = (values.get(name) or "").strip()
        if not token:
            raise FeasibilityFailed(f"No stored refresh token in slot {options.slot}.")
        age_hours = None
        if values.get(issued):
            started = datetime.fromisoformat(str(values[issued]))
            age_hours = round((now - started).total_seconds() / 3600, 1)
        access, record = refresh_access(transport, config, token)
        record |= {"slot": options.slot, "token_age_hours": age_hours}
        if options.command in {"refresh", "check-access"}:
            path = write_evidence(output, options.command, record)
            outcome = "succeeded" if access else "was refused"
            print(f"Refresh {outcome}; evidence in {path}")
            return 0
        if access is None:
            path = write_evidence(output, "refresh", record)
            raise FeasibilityFailed(f"The stored refresh token was refused; evidence in {path}")
        evidence = probe_channel(
            transport, access, now, options.max_calls, digest_key(output), latest_digests(output)
        )
        evidence["token"] = record
        path = write_evidence(output, "probe", evidence)
        print("\n".join(_summary(evidence)))
        print(f"Redacted evidence written to {path}")
        return 0
    except FeasibilityFailed as failure:
        print(f"YouTube feasibility check failed: {failure}", file=sys.stderr)
        return 1


def _authorize(options, config, env_file, output, now, transport, receiver_factory) -> int:
    scopes = SCOPE_SETS[options.scopes]
    state = secrets.token_urlsafe(24)
    verifier = challenge = None
    if options.pkce or options.pkce_wrong_verifier:
        verifier, challenge = pkce_pair()
    url = authorization_url(config, scopes, state, challenge)
    receiver = receiver_factory(config)
    print("Sign in with the Google account of the test channel and approve read-only access.")
    print("If Google asks which account or channel to use, choose the test channel.")
    print(f"If the browser does not open, visit:\n{url}")
    if not options.no_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    print(f"Waiting up to {options.timeout} seconds for the answer on the redirect address.")
    code, refused = code_from_callback(receiver.wait(options.timeout), state)
    record: dict[str, Any] = {
        "pkce": (
            "wrong_verifier"
            if options.pkce_wrong_verifier
            else ("sent" if options.pkce else "not_sent")
        ),
        "requested_scopes": list(scopes),
        "slot": options.slot,
    }
    if code is None:
        record["consent"] = refused
        path = write_evidence(output, "authorize", record)
        print(f"The consent was not completed ({refused}); evidence in {path}")
        return 1
    sent = pkce_pair()[0] if options.pkce_wrong_verifier else verifier
    try:
        tokens, exchange_record = exchange_code(transport, config, code, sent)
    except _Recorded as failure:
        record |= failure.record
        path = write_evidence(output, "authorize", record)
        print(f"The code exchange was refused; evidence in {path}")
        return 0 if options.pkce_wrong_verifier else 1
    record |= exchange_record
    if options.pkce_wrong_verifier:
        record["pkce_enforced"] = False
        path = write_evidence(output, "authorize", record)
        print(f"A wrong PKCE verifier was accepted; no token was stored; evidence in {path}")
        return 0
    refresh = tokens.get("refresh_token")
    if refresh:
        name, issued = SLOTS[options.slot]
        store(env_file, {name: refresh, issued: now.isoformat(timespec="seconds")})
    path = write_evidence(output, "authorize", record)
    stored = f"stored in {env_file.name} (value not shown)" if refresh else "not returned"
    print(f"Refresh token {stored}; evidence in {path}")
    if options.no_probe:
        return 0
    evidence = probe_channel(
        transport,
        str(tokens["access_token"]),
        now,
        options.max_calls,
        digest_key(output),
        latest_digests(output),
    )
    evidence["token"] = {"source": "code_exchange", **exchange_record}
    probe_path = write_evidence(output, "probe", evidence)
    print("\n".join(_summary(evidence)))
    print(f"Redacted evidence written to {probe_path}")
    return 0


# F12: whether revoking one consent's refresh token also ends another consent of the same
# account. It ends access for the account in the whole project, so it needs --confirm.
# Google says a revocation may take some time to take full effect (entry review G-1), so a
# slot b that still works after the wait is only a provisional answer (R011-03): slot b is
# kept, and check-access --slot b at least 30 minutes later decides.
def _revoke_test(options, config, env_file, output, transport, sleep) -> int:
    if not options.confirm:
        raise FeasibilityFailed(
            "revoke-test ends this Google account's access in the whole project (the Gmail "
            "sender's token too, if it is the same account). Run it with --confirm."
        )
    values = dotenv_values(env_file)
    first = (values.get(SLOTS["a"][0]) or "").strip()
    second = (values.get(SLOTS["b"][0]) or "").strip()
    if not first or not second:
        raise FeasibilityFailed(
            "revoke-test needs refresh tokens in slots a and b: authorize twice, the second "
            "time with --slot b."
        )
    record: dict[str, Any] = {"wait_seconds": REVOCATION_WAIT}
    _, record["b_before"] = refresh_access(transport, config, second)
    record["revoke_a"] = revoke(transport, first)
    sleep(REVOCATION_WAIT)
    _, record["a_after"] = refresh_access(transport, config, first)
    access_b, record["b_after"] = refresh_access(transport, config, second)
    survived = access_b is not None
    record["b_survives_revocation_of_a"] = survived
    record["conclusion"] = "provisional" if survived else "final"
    for name in SLOTS["a"]:
        unset_key(env_file, name)
    if not survived:
        for name in SLOTS["b"]:
            unset_key(env_file, name)
    path = write_evidence(output, "revoke-test", record)
    if survived:
        print(
            f"Slot b still worked {REVOCATION_WAIT} seconds after slot a was revoked. This is "
            "provisional: run check-access --slot b again at least 30 minutes later before "
            f"drawing a conclusion. Evidence in {path}"
        )
    else:
        print(f"Slot b stopped working when slot a was revoked (final); evidence in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
