"""Owner-run Instagram feasibility check (specification 010-B, D-053 decision D10).

    python -m app.instagram_feasibility --env-file PATH authorize [--pkce | --pkce-wrong-verifier]
    python -m app.instagram_feasibility --env-file PATH probe
    python -m app.instagram_feasibility --env-file PATH refresh
    python -m app.instagram_feasibility --env-file PATH check-access
    python -m app.instagram_feasibility --env-file PATH forget

It establishes, with the owner's own Meta app in development mode and one owner-controlled
Instagram professional test account, what the Instagram API with Instagram Login actually
returns (acceptance criterion 1). It is read-only: it requests only the scopes
instagram_business_basic and instagram_business_manage_insights, makes only the documented
token requests and GET reads, and never publishes, comments, messages, or changes anything.

The app ID, app secret, and redirect URI come from the ignored environment file. The browser
consent ends on the registered redirect URI, which need not load; the owner pastes the full
address from the browser into a hidden prompt. The long-lived token is stored in the same
environment file (as the D-022 Gmail helper stores its refresh token) and is never printed;
`forget` removes it. Evidence is redacted before it is written to the ignored local-data
folder next to the environment file: it holds metric and field names, availability, value
types, error codes, counts, ages in days, and rate-limit percentages, but no token, code,
secret, account or media ID, username, caption, URL, or metric value.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import re
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key, unset_key

from app.config import PROJECT_ROOT

GRAPH_VERSION = "v27.0"
AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
CODE_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
SCOPES = ("instagram_business_basic", "instagram_business_manage_insights")
APP_ID, APP_SECRET, REDIRECT = (
    "TRACKING_INSTAGRAM_APP_ID",
    "TRACKING_INSTAGRAM_APP_SECRET",
    "TRACKING_INSTAGRAM_REDIRECT_URI",
)
TOKEN, ISSUED = "TRACKING_INSTAGRAM_FEASIBILITY_TOKEN", "TRACKING_INSTAGRAM_FEASIBILITY_ISSUED_AT"
TIMEOUT = 20
DEFAULT_MAX_CALLS = 150
# The provisional D2 catalog of the entry review, plus the deprecated impressions metric to
# confirm its refusal. The check records what the API actually returns for each name.
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
    "impressions",
)
MEDIA_METRICS = (
    "reach",
    "views",
    "likes",
    "comments",
    "saved",
    "shares",
    "total_interactions",
    "profile_visits",
    "follows",
    "ig_reels_avg_watch_time",
    "ig_reels_video_view_total_time",
    "reels_skip_rate",
    "impressions",
)
STORY_METRICS = (
    "reach",
    "views",
    "replies",
    "navigation",
    "link_clicks",
    "shares",
    "follows",
    "profile_visits",
    "total_interactions",
    "impressions",
)
ME_FIELDS = (
    "user_id",
    "username",
    "account_type",
    "media_count",
    "followers_count",
    "follows_count",
)
HISTORY_DAYS = (7, 30, 90, 365, 730)
# Error codes the Graph API uses for throttling; the check stops reading when it sees one.
THROTTLE_CODES = {4, 17, 32, 613, 80002}


# Raised for any failure; messages are fixed and never contain secrets or URLs.
class FeasibilityFailed(Exception):
    """A feasibility step failed; the message is safe to print."""


@dataclass
class Reply:
    status: int
    body: Any
    headers: Mapping[str, str]


# Send one request and return the decoded JSON reply. Network failures raise
# FeasibilityFailed without the URL, which may carry a token.
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
        raise FeasibilityFailed("The Instagram API did not answer.") from None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = {"error": {"type": "unreadable_response"}}
    return Reply(status, body, headers)


Transport = Callable[[str, str, Mapping[str, str] | None], Reply]


def _graph(path: str, params: Mapping[str, str]) -> str:
    return f"{GRAPH}/{GRAPH_VERSION}/{path}?{urllib.parse.urlencode(params)}"


@dataclass(frozen=True)
class AppConfig:
    app_id: str
    app_secret: str = field(repr=False)
    redirect_uri: str


def app_config(values: Mapping[str, str | None]) -> AppConfig:
    app_id = (values.get(APP_ID) or "").strip()
    app_secret = (values.get(APP_SECRET) or "").strip()
    redirect = (values.get(REDIRECT) or "").strip()
    if not app_id.isdigit() or not app_secret or not redirect:
        raise FeasibilityFailed(
            f"Set {APP_ID} (digits), {APP_SECRET} and {REDIRECT} in the environment file."
        )
    parts = urllib.parse.urlsplit(redirect)
    local = parts.hostname in {"localhost", "127.0.0.1"}
    if (
        parts.fragment
        or parts.username
        or not (parts.scheme == "https" or (parts.scheme == "http" and local))
    ):
        raise FeasibilityFailed("The redirect URI must be HTTPS (HTTP only on localhost).")
    return AppConfig(app_id, app_secret, redirect)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


# The Business Login authorization URL (IG-4 of the entry review). PKCE parameters are added
# only for the optional probe, which records whether the provider accepts or enforces them.
def authorization_url(config: AppConfig, state: str, challenge: str | None = None) -> str:
    query = {
        "client_id": config.app_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
    }
    if challenge is not None:
        query |= {"code_challenge": challenge, "code_challenge_method": "S256"}
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"


# Read the code from the pasted redirect address: the state must match, a cancelled consent
# is refused, and the documented "#_" suffix is never part of the code.
def code_from_redirect(pasted: str, state: str, redirect_uri: str) -> str:
    text = pasted.strip()
    parts = urllib.parse.urlsplit(text)
    expected = urllib.parse.urlsplit(redirect_uri)
    if (parts.scheme, parts.netloc, parts.path.rstrip("/")) != (
        expected.scheme,
        expected.netloc,
        expected.path.rstrip("/"),
    ):
        raise FeasibilityFailed("Paste the full address of the redirect page.")
    query = urllib.parse.parse_qs(parts.query)
    if query.get("error"):
        raise FeasibilityFailed("The consent was cancelled or denied.")
    received = query.get("state", [""])[0]
    if not hmac.compare_digest(received, state):
        raise FeasibilityFailed("The state does not match this authorization.")
    code = query.get("code", [""])[0].removesuffix("#_")
    if not code:
        raise FeasibilityFailed("The address carries no authorization code.")
    return code


_ID_LIKE = re.compile(r"\d{5,}")


# A Graph error reduced to its codes and a message without long digit runs (IDs).
def error_summary(body: Any) -> dict[str, Any]:
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {"code": None, "subcode": None, "type": None, "message": None}
    message = error.get("message")
    if isinstance(message, str):
        message = _ID_LIKE.sub("<n>", message)[:200]
    else:
        message = None
    return {
        "code": error.get("code"),
        "subcode": error.get("error_subcode"),
        "type": error.get("type"),
        "message": message,
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


# Rate-limit headers with every key that could identify a business replaced and only numbers
# kept (Business Use Case and application usage, as percentages and waits).
def usage_headers(headers: Mapping[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, raw in headers.items():
        if "usage" not in name.lower():
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            result[name.lower()] = "unreadable"
            continue
        result[name.lower()] = _numbers_only(data)
    return result


def _numbers_only(data: Any) -> Any:
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for index, (key, value) in enumerate(data.items()):
            name = f"<id-{index}>" if _ID_LIKE.fullmatch(str(key)) else str(key)
            if name == "type" and isinstance(value, str):
                out[name] = value
            else:
                reduced = _numbers_only(value)
                if reduced not in (None, {}, []):
                    out[name] = reduced
        return out
    if isinstance(data, list):
        return [item for item in (_numbers_only(value) for value in data) if item not in ({}, [])]
    if isinstance(data, bool):
        return None
    if isinstance(data, int | float):
        return data
    return None


# Read-only probe session: counts calls, keeps the largest usage figures seen, and stops
# reading once the provider throttles or the call budget is spent.
class Probe:
    def __init__(self, transport: Transport, token: str, max_calls: int) -> None:
        self.transport, self._token, self.max_calls = transport, token, max_calls
        self.calls, self.throttled = 0, False
        self.usage: dict[str, Any] = {}

    def __repr__(self) -> str:
        return f"Probe(calls={self.calls})"

    def get(self, path: str, params: Mapping[str, str] | None = None) -> Reply | None:
        if self.throttled or self.calls >= self.max_calls:
            return None
        self.calls += 1
        reply = self.transport(
            "GET", _graph(path, {**(params or {}), "access_token": self._token}), None
        )
        seen = usage_headers(reply.headers)
        if seen:
            self.usage = seen
        if reply.status >= 400 and error_summary(reply.body)["code"] in THROTTLE_CODES:
            self.throttled = True
        return reply

    # The outcome of one metric request: ok with data, ok but empty, or the error codes.
    def metric(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        reply = self.get(path, params)
        if reply is None:
            return {"outcome": "not_requested"}
        if reply.status >= 400:
            return {"outcome": "error", "status": reply.status, **error_summary(reply.body)}
        data = reply.body.get("data") if isinstance(reply.body, dict) else None
        if not data:
            return {"outcome": "empty"}
        entry = data[0] if isinstance(data, list) and data else {}
        if "total_value" in entry:
            return {"outcome": "ok", "value_type": value_type(entry["total_value"].get("value"))}
        values = entry.get("values") or []
        return {
            "outcome": "ok",
            "value_type": value_type(values[0].get("value")) if values else "absent",
            "period": entry.get("period"),
            "points": len(values),
        }


def _age_days(timestamp: str | None, now: datetime) -> int | None:
    if not timestamp:
        return None
    try:
        moment = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
    return (now - moment).days


# The fields /me returns: all at once, otherwise one by one to see which are refused.
def _me(probe: Probe) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    reply = probe.get("me", {"fields": ",".join(ME_FIELDS)})
    found: dict[str, Any] = {}
    if reply is not None and reply.status < 400 and isinstance(reply.body, dict):
        found = reply.body
        outcome = {name: ("present" if name in found else "absent") for name in ME_FIELDS}
    else:
        outcome = {}
        for name in ME_FIELDS:
            single = probe.get("me", {"fields": name})
            if single is None:
                outcome[name] = "not_requested"
            elif single.status >= 400:
                outcome[name] = {"refused": error_summary(single.body)}
            else:
                found |= single.body if isinstance(single.body, dict) else {}
                outcome[name] = "present" if name in single.body else "absent"
    user_id = found.get("user_id") or found.get("id")
    facts = {
        "account_type": found.get("account_type"),
        "followers_bucket": (
            None
            if not isinstance(found.get("followers_count"), int)
            else ("100_or_more" if found["followers_count"] >= 100 else "under_100")
        ),
        "media_count_type": value_type(found.get("media_count")),
    }
    return outcome, str(user_id) if user_id else None, facts


def probe_account(
    transport: Transport, token: str, now: datetime, max_calls: int = DEFAULT_MAX_CALLS
) -> dict[str, Any]:
    probe = Probe(transport, token, max_calls)
    fields, user_id, facts = _me(probe)
    evidence: dict[str, Any] = {
        "schema": "instagram-feasibility-1",
        "generated_at": now.isoformat(timespec="seconds"),
        "graph_version": GRAPH_VERSION,
        "login": "instagram_login",
        "me_fields": fields,
        "account": facts,
    }
    if user_id is None:
        evidence |= {"calls": probe.calls, "stopped": "no_user_id"}
        return evidence
    since, until = int((now - timedelta(days=2)).timestamp()), int(now.timestamp())
    evidence["account_insights"] = {
        name: probe.metric(
            f"{user_id}/insights",
            {
                "metric": name,
                "period": "day",
                "metric_type": "total_value",
                "since": str(since),
                "until": str(until),
            },
        )
        for name in ACCOUNT_METRICS
    }
    history = {}
    for days in HISTORY_DAYS:
        start = now - timedelta(days=days)
        history[str(days)] = probe.metric(
            f"{user_id}/insights",
            {
                "metric": "reach",
                "period": "day",
                "since": str(int(start.timestamp())),
                "until": str(int((start + timedelta(days=1)).timestamp())),
            },
        )
    evidence["history_reach_one_day_at_depth"] = history
    evidence |= _probe_media(probe, user_id, now)
    evidence |= _probe_stories(probe, user_id)
    evidence |= {"calls": probe.calls, "throttled": probe.throttled, "rate_limit": probe.usage}
    return evidence


def _probe_media(probe: Probe, user_id: str, now: datetime) -> dict[str, Any]:
    fields = "id,media_type,media_product_type,timestamp"
    reply = probe.get(f"{user_id}/media", {"fields": fields, "limit": "50"})
    product_field = "returned"
    if reply is not None and reply.status >= 400:
        product_field = {"refused": error_summary(reply.body)}
        reply = probe.get(f"{user_id}/media", {"fields": "id,media_type,timestamp", "limit": "50"})
    if reply is None or reply.status >= 400:
        failure = "not_requested" if reply is None else error_summary(reply.body)
        return {"media": {"outcome": failure, "media_product_type_field": product_field}}
    items = reply.body.get("data") or [] if isinstance(reply.body, dict) else []
    groups: dict[str, list[str]] = {}
    ages = []
    product_seen = False
    for item in items:
        product = item.get("media_product_type")
        product_seen = product_seen or product is not None
        key = f"{item.get('media_type')}/{product or '-'}"
        groups.setdefault(key, []).append(str(item.get("id")))
        age = _age_days(item.get("timestamp"), now)
        if age is not None:
            ages.append(age)
    if product_field == "returned" and items and not product_seen:
        product_field = "absent_from_items"
    insights = {
        key: {name: probe.metric(f"{ids[0]}/insights", {"metric": name}) for name in MEDIA_METRICS}
        for key, ids in sorted(groups.items())
    }
    paging = isinstance(reply.body, dict) and "paging" in reply.body
    return {
        "media": {
            "outcome": "ok",
            "media_product_type_field": product_field,
            "counts": {key: len(ids) for key, ids in sorted(groups.items())},
            "age_days_range": [min(ages), max(ages)] if ages else None,
            "paging": paging,
        },
        "media_insights_by_type": insights,
    }


def _probe_stories(probe: Probe, user_id: str) -> dict[str, Any]:
    reply = probe.get(f"{user_id}/stories", {"fields": "id,media_type,timestamp"})
    if reply is None:
        return {"stories": {"outcome": "not_requested"}}
    if reply.status >= 400:
        return {"stories": {"outcome": "error", **error_summary(reply.body)}}
    items = reply.body.get("data") or [] if isinstance(reply.body, dict) else []
    result: dict[str, Any] = {"stories": {"outcome": "ok", "live_stories": len(items)}}
    if items:
        story = str(items[0].get("id"))
        result["story_insights"] = {
            name: probe.metric(f"{story}/insights", {"metric": name}) for name in STORY_METRICS
        }
    return result


# Exchange the code for a short-lived token, then for a long-lived one. Returns the long-lived
# token and the redacted record of both answers.
def exchange_code(
    transport: Transport, config: AppConfig, code: str, verifier: str | None
) -> tuple[str, dict[str, Any]]:
    form = {
        "client_id": config.app_id,
        "client_secret": config.app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": config.redirect_uri,
        "code": code,
    }
    if verifier is not None:
        form["code_verifier"] = verifier
    reply = transport("POST", CODE_URL, form)
    record: dict[str, Any] = {"code_exchange_status": reply.status}
    if reply.status >= 400 or not isinstance(reply.body, dict):
        record["code_exchange_error"] = error_summary(reply.body)
        raise _Recorded(record)
    payload = reply.body
    shape = "flat"
    if isinstance(payload.get("data"), list) and payload["data"]:
        payload, shape = payload["data"][0], "data_array"
    short = payload.get("access_token")
    if not isinstance(short, str) or not short:
        record["code_exchange_error"] = {"type": "no_access_token"}
        raise _Recorded(record)
    permissions = payload.get("permissions")
    if isinstance(permissions, str):
        permissions = permissions.split(",")
    record |= {
        "code_exchange_shape": shape,
        "granted_permissions": sorted(permissions or []),
        "user_id_returned": bool(payload.get("user_id")),
    }
    long_reply = transport(
        "GET",
        f"{GRAPH}/access_token?"
        + urllib.parse.urlencode(
            {
                "grant_type": "ig_exchange_token",
                "client_secret": config.app_secret,
                "access_token": short,
            }
        ),
        None,
    )
    record["long_lived_status"] = long_reply.status
    body = long_reply.body if isinstance(long_reply.body, dict) else {}
    token = body.get("access_token")
    if long_reply.status >= 400 or not isinstance(token, str) or not token:
        record["long_lived_error"] = error_summary(long_reply.body)
        raise _Recorded(record)
    record |= {"token_type": body.get("token_type"), "expires_in": body.get("expires_in")}
    return token, record


class _Recorded(Exception):
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        super().__init__("recorded failure")


def refresh_token(transport: Transport, token: str) -> tuple[str | None, dict[str, Any]]:
    reply = transport(
        "GET",
        f"{GRAPH}/refresh_access_token?"
        + urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": token}),
        None,
    )
    body = reply.body if isinstance(reply.body, dict) else {}
    new = body.get("access_token")
    if reply.status >= 400 or not isinstance(new, str) or not new:
        return None, {"status": reply.status, **error_summary(reply.body)}
    return new, {
        "status": reply.status,
        "token_type": body.get("token_type"),
        "expires_in": body.get("expires_in"),
        "token_changed": new != token,
    }


# Store values in the environment file (quoted) without echoing any of them.
def store(env_file: Path, values: Mapping[str, str]) -> None:
    for name, value in values.items():
        set_key(env_file, name, value, quote_mode="always")


def write_evidence(directory: Path, name: str, evidence: Mapping[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{name}-{stamp}.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _summary(evidence: Mapping[str, Any]) -> list[str]:
    lines = [f"Calls made: {evidence.get('calls', 0)}; throttled: {evidence.get('throttled')}"]
    for section in ("account_insights", "media_insights_by_type", "story_insights"):
        block = evidence.get(section)
        if isinstance(block, dict):
            flat = (
                block.values()
                if section != "media_insights_by_type"
                else [item for group in block.values() for item in group.values()]
            )
            outcomes = [item.get("outcome") for item in flat]
            lines.append(
                f"{section}: {outcomes.count('ok')} ok, {outcomes.count('empty')} empty, "
                f"{outcomes.count('error')} refused"
            )
    return lines


# Command-line entry point for the owner. Returns a process exit code.
def main(argv: list[str] | None = None, transport: Transport = http_send) -> int:
    parser = argparse.ArgumentParser(description="Instagram feasibility check (read-only).")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    commands = parser.add_subparsers(dest="command", required=True)
    authorize = commands.add_parser("authorize", help="Consent, store the token, then probe.")
    mode = authorize.add_mutually_exclusive_group()
    mode.add_argument("--pkce", action="store_true", help="Send PKCE parameters.")
    mode.add_argument(
        "--pkce-wrong-verifier", action="store_true", help="Check whether PKCE is enforced."
    )
    authorize.add_argument("--no-browser", action="store_true", help="Print the URL only.")
    commands.add_parser("probe", help="Read the account with the stored token.")
    commands.add_parser("refresh", help="Refresh the stored token (at least 24 hours old).")
    commands.add_parser("check-access", help="Check the stored token after removing access.")
    commands.add_parser("forget", help="Remove the stored token from the environment file.")
    options = parser.parse_args(argv)
    env_file: Path = options.env_file
    output = env_file.parent / "local-data" / "instagram-feasibility"
    now = datetime.now(UTC)
    try:
        if not env_file.is_file():
            raise FeasibilityFailed("The environment file does not exist.")
        values = dotenv_values(env_file)
        if options.command == "forget":
            for name in (TOKEN, ISSUED):
                if values.get(name) is not None:
                    unset_key(env_file, name)
            print("Removed the stored feasibility token (if any).")
            return 0
        if options.command == "authorize":
            config = app_config(values)
            return _authorize(options, config, env_file, output, now, transport)
        token = (values.get(TOKEN) or "").strip()
        if not token:
            raise FeasibilityFailed("No stored token; run authorize first.")
        issued = values.get(ISSUED) or ""
        age_hours = None
        if issued:
            age_hours = round((now - datetime.fromisoformat(issued)).total_seconds() / 3600, 1)
        if options.command == "probe":
            evidence = probe_account(transport, token, now, options.max_calls)
            evidence["token_age_hours"] = age_hours
            path = write_evidence(output, "probe", evidence)
            print("\n".join(_summary(evidence)))
            print(f"Redacted evidence written to {path}")
            return 0
        if options.command == "refresh":
            new, record = refresh_token(transport, token)
            record["token_age_hours"] = age_hours
            if new is not None:
                store(env_file, {TOKEN: new, ISSUED: now.isoformat(timespec="seconds")})
            path = write_evidence(output, "refresh", record)
            print(f"Refresh {'succeeded' if new else 'was refused'}; evidence in {path}")
            return 0
        reply = transport("GET", _graph("me", {"fields": "user_id", "access_token": token}), None)
        record = {
            "status": reply.status,
            "usable": reply.status < 400,
            "token_age_hours": age_hours,
            **(error_summary(reply.body) if reply.status >= 400 else {}),
        }
        path = write_evidence(output, "check-access", record)
        print(f"Stored token usable: {record['usable']}; evidence in {path}")
        return 0
    except FeasibilityFailed as failure:
        print(f"Instagram feasibility check failed: {failure}", file=sys.stderr)
        return 1


def _authorize(options, config, env_file, output, now, transport) -> int:
    state = secrets.token_urlsafe(24)
    verifier = challenge = None
    if options.pkce or options.pkce_wrong_verifier:
        verifier, challenge = pkce_pair()
    url = authorization_url(config, state, challenge)
    print("Sign in with the Instagram professional test account and approve read-only access.")
    print(f"If the browser does not open, visit:\n{url}")
    if not options.no_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    print("The browser then shows the redirect address, which may fail to load. That is fine.")
    pasted = getpass.getpass("Paste the full address from the browser (hidden): ")
    code = code_from_redirect(pasted, state, config.redirect_uri)
    sent = pkce_pair()[0] if options.pkce_wrong_verifier else verifier
    record: dict[str, Any] = {
        "pkce": (
            "wrong_verifier"
            if options.pkce_wrong_verifier
            else ("sent" if options.pkce else "not_sent")
        ),
        "requested_scopes": list(SCOPES),
    }
    try:
        token, exchange_record = exchange_code(transport, config, code, sent)
    except _Recorded as failure:
        record |= failure.record
        path = write_evidence(output, "authorize", record)
        print(f"The code exchange was refused; evidence in {path}")
        return 0 if options.pkce_wrong_verifier else 1
    record |= exchange_record
    store(env_file, {TOKEN: token, ISSUED: now.isoformat(timespec="seconds")})
    path = write_evidence(output, "authorize", record)
    print(f"Stored the long-lived token in {env_file.name} (value not shown); evidence in {path}")
    evidence = probe_account(transport, token, now, options.max_calls)
    evidence["token_age_hours"] = 0.0
    probe_path = write_evidence(output, "probe", evidence)
    print("\n".join(_summary(evidence)))
    print(f"Redacted evidence written to {probe_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
