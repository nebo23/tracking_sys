"""In-memory stand-in for Google OAuth, the YouTube Data API v3 and the YouTube Analytics API.

It answers with the shapes recorded in the 011-B evidence (specs/011-youtube/evidence.md):
- token answers with scope, expires_in 3599 and refresh_token_expires_in 604799 (Testing);
- PKCE S256 enforced on the code exchange;
- refresh tokens that are never rotated, and revocation of every grant of the account;
- channels.list?mine=true with counts as strings and the uploads playlist;
- playlistItems pages of 50;
- videos.list with private, unlisted and public uploads, hidden likes and disabled comments,
  refusing more than 50 IDs;
- day reports with sparse rows;
- video reports with lowerCamelCase creatorContentType values, which refuse the playlist
  metrics together with that dimension (011-C live check);
- the 401 authError and 403 insufficientPermissions errors.

Identifiers, tokens, secrets and values are synthetic; nothing contacts Google.
"""

import base64
import hashlib
import secrets
from collections.abc import Mapping
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

from app.connectors.synthetic_youtube import ANALYTICS_SCOPE, DATA_SCOPE
from app.connectors.youtube import (
    ANALYTICS_URL,
    DATA_API,
    METRIC_NAMES,
    REVOKE_URL,
    TOKEN_URL,
    Reply,
)

CLIENT_ID = "123456789012-synthetic.apps.googleusercontent.com"
CLIENT_SECRET = "synthetic-client-secret-0123"
CHANNEL = "UCsyntheticLiveChannel1"
UPLOADS = "UU" + CHANNEL[2:]
LABEL = "Synthetic Live Channel"
ACCESS_SECONDS = 3599
REFRESH_SECONDS = 604799
CONTENT_TYPES = ("shorts", "videoOnDemand", "creatorContentTypeUnspecified")
PLAYLIST_METRICS = frozenset({"videosAddedToPlaylists", "videosRemovedFromPlaylists"})
UNSUPPORTED_QUERY = (
    "The query is not supported. Check the documentation at "
    "https://developers.google.com/youtube/analytics/v2/available_reports for a list of "
    "supported queries."
)


def _error(status: int, reason: str, message: str = "") -> Reply:
    return Reply(
        status, {"error": {"code": status, "message": message, "errors": [{"reason": reason}]}}
    )


class FakeYouTube:
    def __init__(self, videos: int = 4, channels: int = 1) -> None:
        self.videos = videos
        self.channels = channels
        self.codes: dict[str, tuple[str, tuple[str, ...]]] = {}
        self.tokens: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        self.revoked: set[str] = set()
        self.deleted: set[str] = set()
        self.failures: list[Reply] = []
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.hidden_subscribers = False
        self.revoke_unavailable = False

    # Stand-in for the consent page: approve the authorization URL and return the code.
    def approve(self, url: str, scopes: tuple[str, ...] | None = None) -> str:
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        assert query["access_type"] == "offline" and query["prompt"] == "consent"
        assert query["code_challenge_method"] == "S256"
        granted = tuple(scopes if scopes is not None else query["scope"].split())
        code = "synthetic-code-" + secrets.token_urlsafe(8)
        self.codes[code] = (query["code_challenge"], granted)
        return code

    # Queue an error answer for the next Data or Analytics read.
    def fail_next(self, reply: Reply) -> None:
        self.failures.append(reply)

    def _issue(self, kind: str, scopes: tuple[str, ...], grant: str) -> str:
        token = (
            "synthetic-access-" if kind == "access" else "synthetic-refresh-"
        ) + secrets.token_urlsafe(8)
        self.tokens[token] = (kind, grant, scopes)
        return token

    def usable(self, token: str) -> bool:
        found = self.tokens.get(token)
        return found is not None and found[1] not in self.revoked

    def __call__(
        self,
        method: str,
        url: str,
        form: Mapping[str, str] | None,
        headers: Mapping[str, str] | None,
    ) -> Reply:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}{parts.path}"
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        self.requests.append((method, base, query))
        if base == TOKEN_URL:
            return self._token(form or {})
        if base == REVOKE_URL:
            if self.revoke_unavailable:
                return Reply(503, {})
            found = self.tokens.get((form or {}).get("token", ""))
            if found is None or found[1] in self.revoked:
                return Reply(400, {"error": "invalid_token"})
            # Every grant of the account is revoked at once (G-1).
            self.revoked.update(
                grant for _, grant, _ in self.tokens.values() if grant.startswith("grant")
            )
            return Reply(200, {})
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        found = self.tokens.get(token)
        if found is None or found[0] != "access" or found[1] in self.revoked:
            return _error(401, "authError", "Invalid Credentials")
        if self.failures:
            return self.failures.pop(0)
        scopes = found[2]
        if base == ANALYTICS_URL:
            if ANALYTICS_SCOPE not in scopes:
                return _error(403, "insufficientPermissions")
            return self._report(query)
        if DATA_SCOPE not in scopes:
            return _error(403, "insufficientPermissions")
        assert "title" not in query.get("fields", "").replace("snippet/title", "")
        if base == f"{DATA_API}/channels":
            return self._channels(query)
        if base == f"{DATA_API}/playlistItems":
            return self._playlist(query)
        if base == f"{DATA_API}/videos":
            return self._videos(query)
        return _error(404, "notFound")

    def _token(self, form: Mapping[str, str]) -> Reply:
        if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
            return Reply(401, {"error": "invalid_client"})
        if form.get("grant_type") == "authorization_code":
            found = self.codes.pop(form.get("code", ""), None)
            verifier = form.get("code_verifier", "")
            digest = hashlib.sha256(verifier.encode()).digest()
            challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
            if found is None or found[0] != challenge:
                return Reply(400, {"error": "invalid_grant", "error_description": "Bad Request"})
            grant = f"grant{len(self.tokens)}"
            scopes = found[1]
            return Reply(
                200,
                {
                    "access_token": self._issue("access", scopes, grant),
                    "expires_in": ACCESS_SECONDS,
                    "refresh_token": self._issue("refresh", scopes, grant),
                    "refresh_token_expires_in": REFRESH_SECONDS,
                    "scope": " ".join(scopes),
                    "token_type": "Bearer",
                },
            )
        found = self.tokens.get(form.get("refresh_token", ""))
        if found is None or found[0] != "refresh" or found[1] in self.revoked:
            return Reply(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": "Token has been expired or revoked.",
                },
            )
        return Reply(
            200,
            {
                "access_token": self._issue("access", found[2], found[1]),
                "expires_in": ACCESS_SECONDS,
                "refresh_token_expires_in": REFRESH_SECONDS - 120,
                "scope": " ".join(found[2]),
                "token_type": "Bearer",
            },
        )

    def _channels(self, query: Mapping[str, str]) -> Reply:
        assert query.get("mine") == "true"
        if self.channels == 0:
            return Reply(
                200, {"kind": "youtube#channelListResponse", "pageInfo": {"totalResults": 0}}
            )
        part = query["part"]
        items = []
        for index in range(self.channels):
            item: dict[str, object] = {"id": CHANNEL if index == 0 else f"{CHANNEL}{index}"}
            if "snippet" in part:
                item["snippet"] = {"title": LABEL}
            if "statistics" in part:
                statistics = {
                    "viewCount": "1234",
                    "videoCount": str(sum(1 for video in self._uploads() if video[1] == "public")),
                    "hiddenSubscriberCount": self.hidden_subscribers,
                }
                if not self.hidden_subscribers:
                    statistics["subscriberCount"] = "12300"
                item["statistics"] = statistics
            if "contentDetails" in part:
                item["contentDetails"] = {"relatedPlaylists": {"uploads": UPLOADS}}
            items.append(item)
        return Reply(200, {"items": items})

    # (video ID, privacy status, published date) of every upload in playlist order.
    def _uploads(self) -> list[tuple[str, str, date]]:
        return [
            (
                f"v{index:04d}",
                {1: "private", 2: "unlisted"}.get(index, "public"),
                date(2026, 11, 14 - index % 10),
            )
            for index in range(1, self.videos + 1)
            if f"v{index:04d}" not in self.deleted
        ]

    def _playlist(self, query: Mapping[str, str]) -> Reply:
        assert query["playlistId"] == UPLOADS and query["maxResults"] == "50"
        offset = int(query.get("pageToken", "0") or "0")
        uploads = self._uploads()
        page = uploads[offset : offset + 50]
        body: dict[str, object] = {
            "items": [
                {"contentDetails": {"videoId": video, "videoPublishedAt": f"{published}T10:00:00Z"}}
                for video, _, published in page
            ]
        }
        if offset + 50 < len(uploads):
            body["nextPageToken"] = str(offset + 50)
        return Reply(200, body)

    def _videos(self, query: Mapping[str, str]) -> Reply:
        ids = query["id"].split(",")
        if len(set(ids)) > 50:
            return _error(400, "invalidFilters")
        known = {video: (privacy, published) for video, privacy, published in self._uploads()}
        items = []
        for video in ids:
            if video not in known:
                continue
            if query["part"] == "id":
                items.append({"id": video})
                continue
            index = int(video[1:])
            statistics = {"viewCount": str(100 * index)}
            if index != 3:
                statistics["likeCount"] = str(10 * index)
            if index != 2:
                statistics["commentCount"] = str(index)
            items.append(
                {
                    "id": video,
                    "snippet": {
                        "publishedAt": f"{known[video][1]}T10:00:00Z",
                        "liveBroadcastContent": "none",
                    },
                    "contentDetails": {"duration": f"PT{index}M"},
                    "status": {"privacyStatus": known[video][0]},
                    "statistics": statistics,
                }
            )
        return Reply(200, {"kind": "youtube#videoListResponse", "items": items})

    # Report shapes as Google answered them: sparse day rows (F8); video rows only for videos
    # with data (F9); and "The query is not supported" for the playlist metrics together with
    # creatorContentType (011-C live check, 2026-11-18).
    def _report(self, query: Mapping[str, str]) -> Reply:
        assert query["ids"] == "channel==MINE"
        metrics = query["metrics"].split(",")
        assert set(metrics) <= set(METRIC_NAMES)
        headers = [
            {"name": name, "columnType": "METRIC", "dataType": "INTEGER"} for name in metrics
        ]
        if query["dimensions"] == "day":
            assert tuple(metrics) == METRIC_NAMES
            start = date.fromisoformat(query["startDate"])
            end = date.fromisoformat(query["endDate"])
            rows = []
            day = start
            while day <= end:
                # Sparse rows: every seventh day has no row (F8).
                if day.toordinal() % 7:
                    rows.append(
                        [day.isoformat(), *[day.day + position for position in range(len(metrics))]]
                    )
                day += timedelta(days=1)
            dimension = [{"name": "day", "columnType": "DIMENSION", "dataType": "STRING"}]
            return Reply(200, {"columnHeaders": dimension + headers, "rows": rows})
        dimensions = query["dimensions"].split(",")
        assert dimensions in (["video"], ["video", "creatorContentType"])
        if len(dimensions) == 2 and set(metrics) & PLAYLIST_METRICS:
            return _error(400, "badRequest", UNSUPPORTED_QUERY)
        rows = []
        for video in query["filters"].removeprefix("video==").split(","):
            if video == "v0002":
                continue
            number = int(video[1:])
            kind = [CONTENT_TYPES[number % 3]] if len(dimensions) == 2 else []
            values = [number * 10 + METRIC_NAMES.index(name) for name in metrics]
            rows.append([video, *kind, *values])
        columns = [
            {"name": name, "columnType": "DIMENSION", "dataType": "STRING"} for name in dimensions
        ]
        return Reply(200, {"columnHeaders": columns + headers, "rows": rows})
