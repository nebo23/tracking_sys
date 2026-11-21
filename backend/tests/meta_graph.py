"""In-memory Graph API for the Meta adapter fixture tests (specification 014-D, T-51 to T-53).

A transport stand-in built from the shapes recorded in Phase 0 (entry review section 2.4): the
Login for Business code exchange and debug_token, the ad account and dataset nodes, the
campaigns, ad sets and ads edges with cursor paging, daily ad-level insights with decimal-string
spend, the Conversions API events edge, and Graph error bodies with usage headers. It never
opens a socket. Every request is recorded with its parsed query or form for assertions. All
values are synthetic.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from app.connectors.meta_ads import Reply

APP_ID = "1000000000000777"
APP_SECRET = "syntheticmetaappsecret0000000000"
CONFIG_ID = "2000000000000777"
CODE = "synthetic-meta-code"
TOKEN = "EAAsyntheticbusinesstoken0000000000"


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    form: dict[str, str] | None


@dataclass
class MetaGraph:
    scopes: list[str] = field(default_factory=lambda: ["ads_read"])
    accounts: dict[str, dict] = field(default_factory=dict)
    datasets: dict[str, str] = field(default_factory=dict)
    objects: dict[str, list[dict]] = field(default_factory=dict)
    insights: list[dict] = field(default_factory=list)
    page_size: int = 2
    queued: list[Reply] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)
    expires_at: int = 0

    # Answer the next request with this reply instead (an error or a usage header).
    def fail_next(self, status: int, body: dict, headers: Mapping[str, str] | None = None) -> None:
        self.queued.append(Reply(status, body, dict(headers or {})))

    def __call__(self, method: str, url: str, form: Mapping[str, str] | None = None) -> Reply:
        parts = urlsplit(url)
        assert parts.scheme == "https" and parts.netloc == "graph.facebook.com", "Graph only"
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        path = parts.path.removeprefix("/v27.0/")
        assert parts.path.startswith("/v27.0/"), "Graph v27.0 only"
        self.requests.append(Request(method, path, query, dict(form) if form else None))
        if self.queued:
            return self.queued.pop(0)
        if path == "oauth/access_token":
            if query.get("code") != CODE or query.get("client_secret") != APP_SECRET:
                return _error(400, 100, "Invalid verification code format.")
            return Reply(200, {"access_token": TOKEN, "token_type": "bearer"})
        if path == "debug_token":
            if query.get("access_token") != f"{APP_ID}|{APP_SECRET}":
                return _error(400, 190, "Invalid OAuth access token.")
            valid = query.get("input_token") == TOKEN
            return Reply(
                200,
                {
                    "data": {
                        "app_id": APP_ID,
                        "type": "SYSTEM_USER",
                        "application": "Synthetic app",
                        "is_valid": valid,
                        "expires_at": self.expires_at,
                        "scopes": list(self.scopes),
                        "granular_scopes": [{"scope": scope} for scope in self.scopes],
                    }
                },
            )
        if query.get("access_token") != TOKEN and form is None:
            return _error(400, 190, "Invalid OAuth access token.")
        if method == "POST" and path.endswith("/events"):
            assert form is not None and form.get("access_token") == TOKEN
            dataset = path.removesuffix("/events")
            if dataset not in self.datasets:
                return _error(400, 100, "Unsupported post request.", subcode=33)
            events = json.loads(form["data"])
            return Reply(
                200,
                {"events_received": len(events), "messages": [], "fbtrace_id": "AsyntheticTrace1"},
            )
        account, _, edge = path.partition("/")
        if not edge:
            if account in self.accounts:
                return Reply(200, {"id": account, **self.accounts[account]})
            if account in self.datasets:
                return Reply(200, {"id": account, "name": self.datasets[account]})
            return _error(400, 100, "Unsupported get request.", subcode=33)
        if edge in {"campaigns", "adsets", "ads"}:
            return self._page(self.objects.get(edge, []), query)
        if edge == "insights":
            span = json.loads(query["time_range"])
            assert query["level"] == "ad" and query["time_increment"] == "1"
            rows = [
                row for row in self.insights if span["since"] <= row["date_start"] <= span["until"]
            ]
            return self._page(rows, query)
        return _error(400, 100, "Unknown path.")

    def _page(self, items: list[dict], query: Mapping[str, str]) -> Reply:
        offset = int(query.get("after", "0") or 0)
        chunk = items[offset : offset + self.page_size]
        following = offset + self.page_size
        paging: dict = {"cursors": {"before": str(offset), "after": str(following)}}
        if following < len(items):
            paging["next"] = "https://graph.facebook.com/v27.0/next-page"
        return Reply(200, {"data": chunk, "paging": paging})

    def paths(self) -> list[str]:
        return [request.path for request in self.requests]


def _error(status: int, code: int, message: str, *, subcode: int | None = None) -> Reply:
    body = {"error": {"message": message, "type": "OAuthException", "code": code}}
    if subcode is not None:
        body["error"]["error_subcode"] = subcode
    body["error"]["fbtrace_id"] = "AsyntheticErrorTrace"
    return Reply(status, body)
