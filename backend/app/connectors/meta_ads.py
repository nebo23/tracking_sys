"""Meta Marketing API and Conversions API adapters (specification 014-D, D-064 decision D12).

Two adapters of one Meta integration, so read and delivery access never share a connection or
a token (D2): MetaAdsProvider ("meta_ads", one ad account per connection) reads spend, and
MetaCapiProvider ("meta_capi", one dataset per connection) sends conversion events. Every
shape below comes from Meta's official documentation read on 2026-11-20 and 2026-11-21 (entry
review section 2.4); none was observed live, because D-063 allows no Meta call in Spec 014:

- Facebook Login for Business (V-7): the dialog takes the login configuration ID instead of
  scope, with response_type=code and override_default_response_type=true for business
  integration system user tokens. The code exchange answers a token that does not expire by
  default and has no refresh token; debug_token with the app token reports the granted
  permissions, which are recorded. No revocation endpoint and no deauthorize or data deletion
  callback is documented for these tokens, so revocation is unsupported and no signed request
  is declared; the client business removes the integration under Connected apps.
- Permissions (V-14): both adapters require ads_read, which also covers the Conversions API;
  ads_management is never requested, and a grant that carries it is flagged by the runtime.
- Spend (V-1 to V-6): the ad account (currency, timezone_name, account_status), its campaigns,
  ad sets and ads, and daily ad-level insights (level=ad, time_increment=1, time_range with
  inclusive dates) in windows of at most 7 days, paged with cursors.after. Rows follow the
  account's time zone and carry spend as a decimal string in the account currency.
- Throttling (V-6): codes 4, 17, 32, 613, 80000 to 80004, 80009 and 80014, or HTTP 429, defer
  the run by the largest estimated_time_to_regain_access (minutes) of X-Business-Use-Case-Usage,
  otherwise 15 minutes; a usage header at 90 percent or more defers before Meta throttles.
- Delivery (V-8 to V-13): POST /<dataset>/events with one event in data and an optional
  test_event_code. user_data carries fbc only, never hashed; no other field of D8 is sent.
- Errors (V-13): 190 or HTTP 401 is unauthorized; 10, 200-299 or HTTP 403 is forbidden;
  100 with subcode 33 is an unavailable object (a dataset rejection of class configuration);
  throttling is rate limited; 1, 2 and HTTP 5xx retry; anything else is permanent.

Both adapters are registered only when enabled and configured and while their provider rules
are current (see build_providers and LIVE_RULES). No request carries a person identifier
other than fbc, and nothing here logs a URL, token, payload or trace ID.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.connectors.contracts import (
    AccountSnapshot,
    Capability,
    DeliveryAnswer,
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

GRAPH_VERSION = "v27.0"
DIALOG_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
GRAPH = "https://graph.facebook.com"
SCOPE = "ads_read"
TIMEOUT = 20
MAX_CURSOR = 512
CONNECT_DAYS = 90
WINDOW_DAYS = 7
HISTORY_DAYS = 730
REREAD_DAYS = 28
OBJECT_PAGE = 100
INSIGHT_PAGE = 500
THROTTLE_WAIT = 900
USAGE_PAUSE = 90
UNAUTHORIZED_CODES = frozenset({102, 190})
RATE_CODES = frozenset({4, 17, 32, 613, 80000, 80001, 80002, 80003, 80004, 80009, 80014})
RETRYABLE_CODES = frozenset({1, 2})
PERCENT_KEYS = ("call_count", "total_cputime", "total_time", "acc_id_util_pct", "app_id_util_pct")
EDGES = (
    ("campaigns", "campaign", "id,name,effective_status"),
    ("adsets", "adset", "id,name,effective_status,campaign_id"),
    ("ads", "ad", "id,name,effective_status,campaign_id,adset_id"),
)
INSIGHT_FIELDS = (
    "ad_id,adset_id,campaign_id,spend,impressions,clicks,account_currency,date_start,date_stop"
)
STREAMS = (
    StreamSpec("account", None, history_days=1, overlap_days=0, storage="advertising"),
    StreamSpec("ad_objects", None, history_days=1, overlap_days=0, storage="advertising"),
    StreamSpec(
        "ad_daily", None, history_days=HISTORY_DAYS, overlap_days=REREAD_DAYS, storage="advertising"
    ),
)
ADS_CAPABILITY = Capability(
    provider="meta_ads",
    version=f"meta-marketing-{GRAPH_VERSION}",
    pkce=None,
    refresh=False,
    revocation_scope="unsupported",
    scopes=(SCOPE,),
    stream="account",
    cost_unit="page",
    daily_quota=None,
    freshness_hours=48,
    streams=STREAMS,
    require_all_scopes=True,
    named_account="ad_account",
    connection_day_zone=True,
)
CAPI_CAPABILITY = Capability(
    provider="meta_capi",
    version=f"meta-capi-{GRAPH_VERSION}",
    pkce=None,
    refresh=False,
    revocation_scope="unsupported",
    scopes=(SCOPE,),
    cost_unit="event",
    daily_quota=None,
    require_all_scopes=True,
    named_account="dataset",
    delivery=True,
)
# The only event fields sent (D6, D8); user_data carries fbc alone.
EVENT_FIELDS = ("event_name", "event_time", "event_id", "action_source", "event_source_url")
CUSTOM_FIELDS = ("value", "currency")


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


def _header(headers: Mapping[str, str], name: str) -> Any:
    try:
        return json.loads(headers.get(name, ""))
    except ValueError:
        return None


# The largest estimated_time_to_regain_access of X-Business-Use-Case-Usage, in seconds.
def regain_seconds(headers: Mapping[str, str]) -> int | None:
    data = _header(headers, "x-business-use-case-usage")
    minutes = [
        entry.get("estimated_time_to_regain_access")
        for entries in (data.values() if isinstance(data, dict) else [])
        if isinstance(entries, list)
        for entry in entries
        if isinstance(entry, dict)
    ]
    values = [item for item in minutes if isinstance(item, int) and not isinstance(item, bool)]
    return max(values) * 60 if values and max(values) > 0 else None


# The highest usage percentage Meta reports in its usage headers (V-6), or None.
def usage_percent(headers: Mapping[str, str]) -> float | None:
    entries: list[dict] = []
    business = _header(headers, "x-business-use-case-usage")
    if isinstance(business, dict):
        for values in business.values():
            entries += (
                [item for item in values if isinstance(item, dict)]
                if isinstance(values, list)
                else []
            )
    for name in ("x-app-usage", "x-ad-account-usage", "x-fb-ads-insights-throttle"):
        data = _header(headers, name)
        if isinstance(data, dict):
            entries.append(data)
    figures = [
        float(entry[key])
        for entry in entries
        for key in PERCENT_KEYS
        if isinstance(entry.get(key), int | float) and not isinstance(entry.get(key), bool)
    ]
    return max(figures) if figures else None


def error_of(reply: Reply) -> ProviderError:
    error = reply.body.get("error") if isinstance(reply.body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    subcode = error.get("error_subcode") if isinstance(error, dict) else None
    if reply.status == 401 or code in UNAUTHORIZED_CODES:
        return ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")
    if code in RATE_CODES or reply.status == 429:
        wait = regain_seconds(reply.headers) or THROTTLE_WAIT
        return ProviderError(ErrorKind.RATE_LIMITED, "rate_limited", wait)
    if code == 10 or (isinstance(code, int) and 200 <= code <= 299) or reply.status == 403:
        return ProviderError(ErrorKind.FORBIDDEN, "permission")
    if reply.status >= 500 or code in RETRYABLE_CODES:
        return ProviderError(ErrorKind.RETRYABLE, "unavailable")
    if code == 100 and subcode == 33:
        return ProviderError(ErrorKind.PERMANENT, "dataset_unavailable")
    named = isinstance(code, int) and not isinstance(code, bool)
    return ProviderError(ErrorKind.PERMANENT, f"graph_{code}" if named else "bad_request")


def _count(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return 0


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class _MetaProvider:
    capability: Capability

    # transport None sends real requests through http_send, looked up when each call is made.
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        config_id: str,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._app_id, self._app_secret, self._config_id = app_id, app_secret, config_id
        self._transport, self._clock = transport, clock

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def _send(self, method: str, url: str, form: Mapping[str, str] | None = None) -> Reply:
        return (self._transport or http_send)(method, url, form)

    # One Graph read. A refused read raises its mapped error; an answered read whose usage
    # reached USAGE_PAUSE percent defers the run before Meta starts throttling.
    def _get(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        reply = self._send("GET", f"{GRAPH}/{GRAPH_VERSION}/{path}?{query}")
        if reply.status >= 400 or not isinstance(reply.body, dict):
            raise error_of(reply)
        usage = usage_percent(reply.headers)
        if usage is not None and usage >= USAGE_PAUSE:
            wait = regain_seconds(reply.headers) or THROTTLE_WAIT
            raise ProviderError(ErrorKind.RATE_LIMITED, "usage", wait)
        return reply.body

    # Facebook Login for Business with the login configuration (V-7); scope is not used.
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
            "state": state,
            "config_id": self._config_id,
            "response_type": "code",
            "override_default_response_type": "true",
        }
        return f"{DIALOG_URL}?{urllib.parse.urlencode(query)}"

    # The code exchange, then debug_token with the app token for the granted permissions.
    def exchange(self, *, code: str, code_verifier: str | None, redirect_uri: str) -> TokenGrant:
        query = urllib.parse.urlencode(
            {
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            }
        )
        reply = self._send("GET", f"{GRAPH}/{GRAPH_VERSION}/oauth/access_token?{query}")
        body = reply.body if isinstance(reply.body, dict) else {}
        token = body.get("access_token")
        if reply.status >= 400 or not isinstance(token, str) or not token:
            error = error_of(reply)
            if error.kind in {ErrorKind.UNAUTHORIZED, ErrorKind.FORBIDDEN}:
                error = ProviderError(ErrorKind.PERMANENT, "invalid_grant")
            raise error
        inspected = self._get(
            "debug_token",
            {"input_token": token, "access_token": f"{self._app_id}|{self._app_secret}"},
        )
        data = inspected.get("data") if isinstance(inspected.get("data"), dict) else {}
        if data.get("is_valid") is not True or str(data.get("app_id", "")) != self._app_id:
            raise ProviderError(ErrorKind.PERMANENT, "invalid_grant")
        scopes = tuple(item for item in data.get("scopes", []) if isinstance(item, str))
        expires = data.get("expires_at")
        expires_at = (
            datetime.fromtimestamp(expires, UTC)
            if isinstance(expires, int) and not isinstance(expires, bool) and expires > 0
            else None
        )
        return TokenGrant(token, None, expires_at, scopes, "", None, "business")

    # Business integration system user tokens have no refresh (V-7).
    def refresh(self, refresh_token: str) -> TokenGrant:
        raise ProviderError(ErrorKind.UNAUTHORIZED, "invalid_grant")

    # No revocation endpoint is documented for these tokens (V-7).
    def revoke(self, token: str, kind: str) -> RevocationOutcome:
        return "unsupported"

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, now: datetime
    ) -> WebhookDelivery:
        raise WebhookRejected("signature_invalid")

    def verify_signed_request(self, signed_request: str, now: datetime) -> SignedRequest:
        raise WebhookRejected("signature_invalid")

    def confirm_deleted(
        self, access_token: str, *, stream: str, object_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        return ()


def _local_start(day: date, zone: str) -> datetime:
    return datetime.combine(day, time(), ZoneInfo(zone)).astimezone(UTC)


def _local_day(instant: datetime, zone: str) -> date:
    return instant.astimezone(ZoneInfo(zone)).date()


class MetaAdsProvider(_MetaProvider):
    capability = ADS_CAPABILITY

    def describe_account(self, access_token: str, account: str) -> AccountSnapshot:
        body = self._get(
            account,
            {
                "fields": "id,name,currency,timezone_name,account_status",
                "access_token": access_token,
            },
        )
        if body.get("id") != account:
            raise ProviderError(ErrorKind.PERMANENT, "account_mismatch")
        status = body.get("account_status")
        return AccountSnapshot(
            account,
            _text(body.get("name")),
            "ad_account",
            _text(body.get("timezone_name")),
            {
                "currency": _text(body.get("currency")),
                "timezone_name": _text(body.get("timezone_name")),
                "account_status": status if isinstance(status, int) else None,
                "name": _text(body.get("name")),
            },
        )

    def _objects(self, token: str, account: str, position: str | None) -> ProviderPage:
        index, after = 0, None
        if position is not None:
            text, _, after = position.partition(":")
            if not text.isdigit() or int(text) >= len(EDGES):
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
            index, after = int(text), after or None
        edge, level, fields = EDGES[index]
        params = {"fields": fields, "limit": str(OBJECT_PAGE), "access_token": token}
        if after:
            params["after"] = after
        body = self._get(f"{account}/{edge}", params)
        records = []
        for item in body.get("data", []) if isinstance(body.get("data"), list) else []:
            if not isinstance(item, dict) or not _text(item.get("id")):
                continue
            records.append(
                ProviderRecord(
                    item["id"],
                    self._clock(),
                    attributes={
                        "level": level,
                        "name": _text(item.get("name")),
                        "effective_status": _text(item.get("effective_status")),
                        "campaign_id": _text(item.get("campaign_id")),
                        "adset_id": _text(item.get("adset_id")),
                    },
                )
            )
        following = self._following(body)
        if following is not None:
            cursor = f"{index}:{following}"
        elif index + 1 < len(EDGES):
            cursor = f"{index + 1}:"
        else:
            cursor = None
        return ProviderPage(tuple(records), self._cursor(cursor), None, self._clock())

    @staticmethod
    def _following(body: Mapping[str, Any]) -> str | None:
        paging = body.get("paging") if isinstance(body.get("paging"), dict) else {}
        cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
        after = cursors.get("after")
        return after if paging.get("next") and isinstance(after, str) and after else None

    @staticmethod
    def _cursor(position: str | None) -> str | None:
        if position is None:
            return None
        if len(position) > MAX_CURSOR:
            raise ProviderError(ErrorKind.PERMANENT, "cursor_too_long")
        return position

    def _daily(
        self,
        token: str,
        account: str,
        zone: str,
        position: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> ProviderPage:
        today = _local_day(self._clock(), zone)
        if position is None:
            first = (
                today - timedelta(days=CONNECT_DAYS) if since is None else _local_day(since, zone)
            )
            first = max(first, today - timedelta(days=HISTORY_DAYS))
            window, after = first, None
        else:
            parts = position.split(":", 2)
            try:
                first, window = date.fromisoformat(parts[0]), date.fromisoformat(parts[1])
                after = parts[2] or None
            except (ValueError, IndexError):
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor") from None
        end = today if until is None else min(today, _local_day(until, zone))
        window_end = min(window + timedelta(days=WINDOW_DAYS), end)
        records: list[ProviderRecord] = []
        following = None
        if window < end:
            params = {
                "level": "ad",
                "time_increment": "1",
                "time_range": json.dumps(
                    {
                        "since": window.isoformat(),
                        "until": (window_end - timedelta(days=1)).isoformat(),
                    },
                    separators=(",", ":"),
                ),
                "fields": INSIGHT_FIELDS,
                "limit": str(INSIGHT_PAGE),
                "access_token": token,
            }
            if after:
                params["after"] = after
            body = self._get(f"{account}/insights", params)
            for row in body.get("data", []) if isinstance(body.get("data"), list) else []:
                record = self._row(row, zone)
                if record is not None:
                    records.append(record)
            following = self._following(body)
        if following is not None:
            cursor = f"{first.isoformat()}:{window.isoformat()}:{following}"
        elif window_end < end:
            cursor = f"{first.isoformat()}:{window_end.isoformat()}:"
        else:
            cursor = None
        return ProviderPage(
            tuple(records),
            self._cursor(cursor),
            _local_start(first, zone) if first < end else None,
            _local_start(max(first, end), zone),
        )

    @staticmethod
    def _row(row: Any, zone: str) -> ProviderRecord | None:
        if not isinstance(row, dict) or not _text(row.get("ad_id")):
            return None
        try:
            day = date.fromisoformat(str(row.get("date_start")))
        except ValueError:
            return None
        if row.get("date_stop") != row.get("date_start"):
            return None
        return ProviderRecord(
            row["ad_id"],
            _local_start(day, zone),
            {"impressions": _count(row.get("impressions")), "clicks": _count(row.get("clicks"))},
            attributes={
                "date": day.isoformat(),
                "spend": row.get("spend") if isinstance(row.get("spend"), str) else None,
                "currency": _text(row.get("account_currency")),
                "campaign_id": _text(row.get("campaign_id")),
                "adset_id": _text(row.get("adset_id")),
            },
        )

    def fetch_page(
        self,
        access_token: str,
        *,
        stream: str = "account",
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        account: str | None = None,
        day_zone: str | None = None,
    ) -> ProviderPage:
        if self.capability.stream_spec(stream) is None or not account:
            raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")
        if stream == "account":
            snapshot = self.describe_account(access_token, account)
            record = ProviderRecord(account, self._clock(), attributes=dict(snapshot.attributes))
            return ProviderPage((record,), None, None, self._clock(), snapshot.label)
        if stream == "ad_objects":
            return self._objects(access_token, account, cursor)
        if not day_zone:
            raise ProviderError(ErrorKind.PERMANENT, "day_zone_missing")
        return self._daily(access_token, account, day_zone, cursor, since, until)


class MetaCapiProvider(_MetaProvider):
    capability = CAPI_CAPABILITY

    def describe_account(self, access_token: str, account: str) -> AccountSnapshot:
        body = self._get(account, {"fields": "id,name", "access_token": access_token})
        if body.get("id") != account:
            raise ProviderError(ErrorKind.PERMANENT, "account_mismatch")
        return AccountSnapshot(account, _text(body.get("name")), "dataset", None, {})

    def fetch_page(self, access_token: str, **_: object) -> ProviderPage:
        raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")

    # The one event of a request, reduced to the fields D6 and D8 allow: fbc alone in
    # user_data, never hashed, and value and currency in custom_data.
    @staticmethod
    def request_event(event: Mapping[str, object]) -> dict[str, object]:
        built = {name: event[name] for name in EVENT_FIELDS if event.get(name) is not None}
        user_data = event.get("user_data")
        fbc = user_data.get("fbc") if isinstance(user_data, Mapping) else None
        built["user_data"] = {"fbc": fbc} if isinstance(fbc, str) else {}
        custom = event.get("custom_data")
        if isinstance(custom, Mapping):
            built["custom_data"] = {name: custom[name] for name in CUSTOM_FIELDS if name in custom}
        if built.get("action_source") != "website":
            built.pop("event_source_url", None)
        return built

    def send_event(
        self,
        access_token: str,
        *,
        dataset: str,
        event: Mapping[str, object],
        test_event_code: str | None,
    ) -> DeliveryAnswer:
        form = {
            "data": json.dumps([self.request_event(event)], separators=(",", ":")),
            "access_token": access_token,
        }
        if test_event_code:
            form["test_event_code"] = test_event_code
        reply = self._send("POST", f"{GRAPH}/{GRAPH_VERSION}/{dataset}/events", form)
        if reply.status >= 400 or not isinstance(reply.body, dict) or "error" in reply.body:
            raise error_of(reply)
        received = reply.body.get("events_received")
        trace = reply.body.get("fbtrace_id")
        return DeliveryAnswer(
            received if isinstance(received, int) and not isinstance(received, bool) else None,
            trace[:64] if isinstance(trace, str) and trace else None,
        )


__all__ = [
    "ADS_CAPABILITY",
    "CAPI_CAPABILITY",
    "GRAPH_VERSION",
    "MetaAdsProvider",
    "MetaCapiProvider",
    "error_of",
    "http_send",
    "regain_seconds",
    "usage_percent",
]
