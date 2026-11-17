"""In-memory stand-in for the Instagram API with Instagram Login (specification 010-C tests).

It answers with the shapes recorded in the 010-B evidence (specs/010-instagram/evidence.md): a
flat code exchange that grants every permission configured on the app, the long-lived and
refresh exchanges, a flat /me, total_value account insights with empty follows_and_unfollows
under 100 followers, the media list with media_product_type and cursor paging, lifetime media
insights that refuse a metric the product type does not offer with code 100, and the stories
edge. Identifiers, tokens, secrets, and values are synthetic; nothing contacts Meta.
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from app.connectors.instagram import CODE_URL, GRAPH, GRAPH_VERSION, Reply

APP_ID = "100000000000001"
APP_SECRET = "0123456789abcdef0123456789abcdef"
APP_SCOPED_ID = "9100000000000001"
USER_ID = "17841400000000001"
USERNAME = "synthetic.studio"
LONG_LIVED = 5_183_331
PERMISSIONS = (
    "instagram_business_basic",
    "instagram_business_manage_insights",
    "instagram_business_content_publish",
    "instagram_business_manage_comments",
    "instagram_business_manage_messages",
)
ACCOUNT_METRICS = (
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
PRODUCT_METRICS = {
    "FEED": {
        "reach",
        "views",
        "likes",
        "comments",
        "saved",
        "shares",
        "total_interactions",
        "profile_visits",
        "follows",
    },
    "REELS": {
        "reach",
        "views",
        "likes",
        "comments",
        "saved",
        "shares",
        "total_interactions",
        "ig_reels_avg_watch_time",
        "ig_reels_video_view_total_time",
        "reels_skip_rate",
    },
    "STORY": {
        "reach",
        "views",
        "replies",
        "navigation",
        "shares",
        "follows",
        "profile_visits",
        "total_interactions",
    },
}
PREFIX = f"{GRAPH}/{GRAPH_VERSION}/"


def graph_error(code: int, status: int = 400, kind: str = "IGApiException") -> Reply:
    return Reply(status, {"error": {"message": "synthetic", "type": kind, "code": code}})


def _value(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:4], 16) % 500 + 1


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


@dataclass
class Media:
    id: str
    product: str
    timestamp: datetime
    media_type: str = "IMAGE"


class FakeGraph:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))
        self.followers = 42
        self.exchange_shape = "flat"
        self.usage: int | None = None
        self.codes: dict[str, bool] = {}
        self.short: set[str] = set()
        self.tokens: dict[str, tuple[datetime, datetime]] = {}
        self.media: list[Media] = []
        self.stories: list[Media] = []
        self.deleted: set[str] = set()
        self.unsupported: dict[str, set[str]] = {}
        self.failures: list[tuple[str, Reply]] = []
        self.calls: list[tuple[str, str, str]] = []
        self.counter = 0

    def __repr__(self) -> str:
        return "FakeGraph()"

    # --- test controls ----------------------------------------------------------------------

    def issue_code(self) -> str:
        self.counter += 1
        code = f"synthetic-code-{self.counter:04d}"
        self.codes[code] = False
        return code + "#_"

    def post(self, product: str, age: timedelta, media_type: str = "IMAGE") -> Media:
        self.counter += 1
        item = Media(f"{18000000000000000 + self.counter}", product, self.clock() - age, media_type)
        (self.stories if product == "STORY" else self.media).append(item)
        return item

    # The next request whose path contains `fragment` answers `reply` instead.
    def fail_next(self, fragment: str, reply: Reply) -> None:
        self.failures.append((fragment, reply))

    def expire(self, token: str) -> None:
        issued, _ = self.tokens[token]
        self.tokens[token] = (issued, self.clock() - timedelta(seconds=1))

    def age(self, token: str, hours: float) -> None:
        issued, expires = self.tokens[token]
        self.tokens[token] = (issued - timedelta(hours=hours), expires)

    def sign(self, account: str, issued_at: datetime, secret: str = APP_SECRET) -> str:
        payload = _b64(
            json.dumps(
                {
                    "algorithm": "HMAC-SHA256",
                    "expires": 0,
                    "issued_at": int(issued_at.timestamp()),
                    "user_id": account,
                }
            ).encode()
        )
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        return f"{_b64(signature)}.{payload}"

    def paths(self) -> list[str]:
        return [path for _, path, _ in self.calls]

    # --- transport --------------------------------------------------------------------------

    def __call__(self, method: str, url: str, form: Mapping[str, str] | None = None) -> Reply:
        parts = urlsplit(url)
        params = {key: values[0] for key, values in parse_qs(parts.query).items()}
        address = f"{parts.scheme}://{parts.netloc}{parts.path}"
        path = address.removeprefix(PREFIX) if address.startswith(PREFIX) else parts.path
        self.calls.append((method, path, params.get("metric", "")))
        for index, (fragment, reply) in enumerate(self.failures):
            if fragment in path:
                del self.failures[index]
                return reply
        if method == "POST" and address == CODE_URL:
            return self._exchange(form or {})
        if address == f"{GRAPH}/access_token":
            return self._long_lived(params)
        if address == f"{GRAPH}/refresh_access_token":
            return self._refresh(params)
        token = params.get("access_token", "")
        if not self._valid(token):
            return graph_error(190, 400, "OAuthException")
        reply = self._read(path, params)
        if self.usage is not None and reply.status < 400:
            reply.headers = {"x-app-usage": json.dumps({"call_volume": self.usage, "cpu_time": 1})}
        return reply

    def _valid(self, token: str) -> bool:
        found = self.tokens.get(token)
        return found is not None and found[1] > self.clock()

    def _issue(self) -> str:
        self.counter += 1
        token = f"synthetic-long-{self.counter:04d}"
        self.tokens[token] = (self.clock(), self.clock() + timedelta(seconds=LONG_LIVED))
        return token

    def _exchange(self, form: Mapping[str, str]) -> Reply:
        code = form.get("code", "")
        if (
            form.get("client_id") != APP_ID
            or form.get("client_secret") != APP_SECRET
            or form.get("grant_type") != "authorization_code"
            or self.codes.get(code, True)
        ):
            return Reply(
                400,
                {"error_type": "OAuthException", "code": 400, "error_message": "synthetic"},
            )
        self.codes[code] = True
        self.counter += 1
        short = f"synthetic-short-{self.counter:04d}"
        self.short.add(short)
        if self.exchange_shape == "flat":
            return Reply(
                200,
                {"access_token": short, "user_id": int(USER_ID), "permissions": list(PERMISSIONS)},
            )
        return Reply(
            200,
            {
                "data": [
                    {
                        "access_token": short,
                        "user_id": USER_ID,
                        "permissions": ",".join(PERMISSIONS),
                    }
                ]
            },
        )

    def _long_lived(self, params: Mapping[str, str]) -> Reply:
        if (
            params.get("grant_type") != "ig_exchange_token"
            or params.get("client_secret") != APP_SECRET
            or params.get("access_token") not in self.short
        ):
            return graph_error(190, 400, "OAuthException")
        self.short.discard(params["access_token"])
        return Reply(
            200,
            {"access_token": self._issue(), "token_type": "bearer", "expires_in": LONG_LIVED},
        )

    # Meta refreshes a long-lived token that is at least 24 hours old and still valid.
    def _refresh(self, params: Mapping[str, str]) -> Reply:
        token = params.get("access_token", "")
        found = self.tokens.get(token)
        if (
            params.get("grant_type") != "ig_refresh_token"
            or found is None
            or found[1] <= self.clock()
            or self.clock() - found[0] < timedelta(hours=24)
        ):
            return graph_error(190, 400, "OAuthException")
        return Reply(
            200,
            {"access_token": self._issue(), "token_type": "bearer", "expires_in": LONG_LIVED},
        )

    def _read(self, path: str, params: Mapping[str, str]) -> Reply:
        if path == "me":
            profile = {
                "id": APP_SCOPED_ID,
                "user_id": USER_ID,
                "username": USERNAME,
                "account_type": "BUSINESS",
                "followers_count": self.followers,
            }
            fields = params.get("fields", "").split(",")
            return Reply(200, {name: profile[name] for name in fields if name in profile})
        if path == f"{USER_ID}/insights":
            return self._account(params)
        if path == f"{USER_ID}/media":
            return self._media(params)
        if path == f"{USER_ID}/stories":
            live = [
                item for item in self.stories if self.clock() - item.timestamp < timedelta(hours=24)
            ]
            return Reply(200, {"data": [self._item(item) for item in live]})
        if path.endswith("/insights"):
            return self._media_insights(path.removesuffix("/insights"), params)
        return graph_error(100)

    def _account(self, params: Mapping[str, str]) -> Reply:
        names = params.get("metric", "").split(",")
        if (
            any(name not in ACCOUNT_METRICS for name in names)
            or params.get("period") != "day"
            or params.get("metric_type") != "total_value"
        ):
            return graph_error(100)
        data = [
            {
                "name": name,
                "period": "day",
                "title": name,
                "total_value": {"value": _value(name, params.get("since", ""))},
                "id": f"{USER_ID}/insights/{name}/day",
            }
            for name in names
            if not (name == "follows_and_unfollows" and self.followers < 100)
        ]
        return Reply(200, {"data": data})

    @staticmethod
    def _item(item: Media) -> dict[str, str]:
        return {
            "id": item.id,
            "media_type": item.media_type,
            "media_product_type": item.product,
            "timestamp": item.timestamp.strftime("%Y-%m-%dT%H:%M:%S+0000"),
        }

    def _media(self, params: Mapping[str, str]) -> Reply:
        items = sorted(self.media, key=lambda item: item.timestamp, reverse=True)
        limit = int(params.get("limit", "25"))
        offset = 0
        if "after" in params:
            offset = int(base64.urlsafe_b64decode(params["after"].encode()).decode())
        page = items[offset : offset + limit]
        body: dict[str, object] = {"data": [self._item(item) for item in page]}
        # Like Meta, the last page still names an "after" cursor but no "next" page.
        after = base64.urlsafe_b64encode(str(offset + len(page)).encode()).decode()
        paging: dict[str, object] = {"cursors": {"before": "synthetic-before", "after": after}}
        if offset + limit < len(items):
            paging["next"] = f"{PREFIX}{USER_ID}/media?after={after}"
        body["paging"] = paging
        return Reply(200, body)

    def _media_insights(self, object_id: str, params: Mapping[str, str]) -> Reply:
        everything = {item.id: item for item in self.media + self.stories}
        item = everything.get(object_id)
        if item is None or object_id in self.deleted:
            return graph_error(100)
        names = params.get("metric", "").split(",")
        offered = PRODUCT_METRICS[item.product] - self.unsupported.get(object_id, set())
        if any(name not in offered for name in names):
            return graph_error(100)
        data = [
            {
                "name": name,
                "period": "lifetime",
                "values": [{"value": _value(object_id, name)}],
                "title": name,
                "id": f"{object_id}/insights/{name}/lifetime",
            }
            for name in names
        ]
        return Reply(200, {"data": data})
