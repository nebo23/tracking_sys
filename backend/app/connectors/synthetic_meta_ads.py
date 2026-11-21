"""Meta-shaped synthetic spend provider for local development and tests (specification 014-A).

It reproduces the shapes that Meta's official documentation describes for Facebook Login for
Business and Marketing API Insights (read 2026-11-20 and 2026-11-21; entry review section 2.4,
V-1 to V-7), never the live service:

- Authorization: a Login for Business stand-in with a configuration ID, response_type=code and
  override_default_response_type=true, and no PKCE. A grant covers the ad accounts approved on
  the stand-in consent page. Business integration system user tokens do not expire and have no
  refresh token (V-7); there is no revocation endpoint.
- Accounts: act_<digits> IDs with currency, time zone, status and name; a test can change the
  currency or the zone (V-2, V-3).
- Objects: campaigns, ad sets and ads with parent IDs, names and effective statuses, including
  ARCHIVED and DELETED, 50 per page.
- Daily rows: one row per ad and account-local day while the ad runs, with spend as a decimal
  string in the account currency (V-1, V-2). Overrides restate single values, give them extra
  decimal places or another currency, or omit them. A test-controlled clock places today; a
  read ends at the start of today in the account's zone, and a window covers at most 7 days.
- Errors: a script of outcomes (throttling with code 80000 and a wait, permission, invalid
  token, temporary and permanent errors), as V-6 and V-13 describe.

State lives in its own SQLite file, shared by the API and the worker, through the storage of
the 009 synthetic provider. Behaviors and the define methods are test controls.
"""

import json
import re
import secrets
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from app.connectors.contracts import (
    AccountSnapshot,
    Capability,
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
from app.connectors.synthetic import CODE_SECONDS, FETCH_OUTCOMES, SyntheticProvider, _digest, _now

AUTHORIZE_URL = "https://synthetic-meta.invalid/v27.0/dialog/oauth"
CONFIG_ID = "1000000000000001"
SCOPE = "ads_read"
ACCOUNT = re.compile(r"act_[1-9][0-9]{0,19}")
OBJECT = re.compile(r"[1-9][0-9]{0,31}")
LEVELS = ("campaign", "adset", "ad")
STATUSES = ("ACTIVE", "PAUSED", "ARCHIVED", "DELETED", "IN_PROCESS", "WITH_ISSUES")
# 90 days at connect, windows of at most 7 days, 730 days of history (D4, D13), and the 28-day
# re-read during which values may still change (V-4).
CONNECT_DAYS = 90
WINDOW_DAYS = 7
HISTORY_DAYS = 730
REREAD_DAYS = 28
PAGE_OBJECTS = 50
THROTTLE_SECONDS = 900
CURSOR_PREFIX = "sma_cursor_"
CLOCK = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
STREAMS = (
    StreamSpec("account", None, history_days=1, overlap_days=0, storage="advertising"),
    StreamSpec("ad_objects", None, history_days=1, overlap_days=0, storage="advertising"),
    StreamSpec(
        "ad_daily",
        None,
        history_days=HISTORY_DAYS,
        overlap_days=REREAD_DAYS,
        storage="advertising",
    ),
)
CAPABILITY = Capability(
    provider="synthetic_meta_ads",
    version="synthetic-meta-ads-1",
    pkce=None,
    refresh=False,
    revocation_scope="unsupported",
    scopes=(SCOPE,),
    stream="account",
    # One unit is one page; Meta has no fixed daily quota for these reads (D5).
    cost_unit="page",
    daily_quota=None,
    freshness_hours=48,
    streams=STREAMS,
    require_all_scopes=True,
    named_account="ad_account",
    connection_day_zone=True,
)
NUMBERS = {"page_rows": 1, "retry_after": 0}
DEFAULTS = {"page_rows": 500, "retry_after": THROTTLE_SECONDS}
BEHAVIORS = {
    "exchange": {"ok", "retryable"},
    "fetch": FETCH_OUTCOMES,
    "describe": {"ok", "retryable"},
}
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, currency TEXT, zone TEXT, "
    "status INTEGER, name TEXT)",
    "CREATE TABLE IF NOT EXISTS objects (account TEXT, id TEXT, level TEXT, campaign TEXT, "
    "adset TEXT, name TEXT, status TEXT, PRIMARY KEY (account, id))",
    "CREATE TABLE IF NOT EXISTS schedules (account TEXT, ad TEXT, first TEXT, last TEXT, "
    "spend TEXT, impressions INTEGER, clicks INTEGER, PRIMARY KEY (account, ad))",
    "CREATE TABLE IF NOT EXISTS overrides (account TEXT, ad TEXT, day TEXT, value TEXT, "
    "PRIMARY KEY (account, ad, day))",
)


def local_start(day: date, zone: str) -> datetime:
    return datetime.combine(day, time(), ZoneInfo(zone)).astimezone(UTC)


def local_day(instant: datetime, zone: str) -> date:
    return instant.astimezone(ZoneInfo(zone)).date()


# A daily read position: the read's first day, the start of the current window and the offset
# of the next row in it, as "<first>:<window>:<offset>". The first day stays fixed for the whole
# read, so a page read after midnight continues the same days. Anything else is invalid_cursor.
def day_cursor(first: date, window: date, offset: int) -> str:
    return f"{first.isoformat()}:{window.isoformat()}:{offset}"


def parse_day_cursor(position: str) -> tuple[date, date, int]:
    parts = position.split(":")
    try:
        first, window = date.fromisoformat(parts[0]), date.fromisoformat(parts[1])
        valid = len(parts) == 3 and parts[2].isascii() and parts[2].isdigit()
        valid = valid and first.isoformat() == parts[0] and window.isoformat() == parts[1]
    except (ValueError, IndexError):
        valid = False
    if not valid or window < first:
        raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
    return first, window, int(parts[2])


class SyntheticMetaAdsProvider(SyntheticProvider):
    capability = CAPABILITY

    def __init__(self, path) -> None:
        super().__init__(path)
        with self._transaction() as connection:
            for statement in SCHEMA:
                connection.execute(statement)

    def __repr__(self) -> str:
        return "SyntheticMetaAdsProvider()"

    def _number(self, connection: sqlite3.Connection, name: str) -> int:
        row = connection.execute("SELECT value FROM behaviors WHERE name = ?", (name,)).fetchone()
        return int(row[0]) if row else DEFAULTS[name]

    def _clock(self, connection: sqlite3.Connection) -> datetime:
        row = connection.execute("SELECT value FROM behaviors WHERE name = 'clock'").fetchone()
        return datetime.fromisoformat(row[0]) if row else CLOCK

    # Test control: numbers of NUMBERS; "clock" (an ISO instant placing today); "fetch_script"
    # (as for the 009 provider); or a mode of BEHAVIORS.
    def set_behavior(self, name: str, value: str) -> None:
        if name in NUMBERS:
            if int(value) < NUMBERS[name]:
                raise ValueError("Synthetic number out of range.")
        elif name == "clock":
            if datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("The synthetic clock needs a time zone.")
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

    # Test control: create or change an ad account.
    def define_account(
        self,
        account: str,
        *,
        currency: str = "USD",
        zone: str = "America/New_York",
        status: int = 1,
        name: str = "Synthetic Ad Account",
    ) -> None:
        if not ACCOUNT.fullmatch(account):
            raise ValueError("Synthetic ad accounts are act_<digits>.")
        ZoneInfo(zone)
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO accounts (id, currency, zone, status, name) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET currency = excluded.currency, "
                "zone = excluded.zone, status = excluded.status, name = excluded.name",
                (account, currency, zone, status, name),
            )

    # Test control: create or change a campaign, ad set or ad. An ad runs from `first` through
    # `last` (inclusive; None while it still runs) with the same daily values.
    def define_object(
        self,
        account: str,
        object_id: str,
        level: str,
        *,
        campaign: str | None = None,
        adset: str | None = None,
        name: str = "Synthetic object",
        status: str = "ACTIVE",
        first: date | None = None,
        last: date | None = None,
        spend: str = "10.00",
        impressions: int = 100,
        clicks: int = 5,
    ) -> None:
        if not OBJECT.fullmatch(object_id) or level not in LEVELS or status not in STATUSES:
            raise ValueError("Invalid synthetic object.")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO objects (account, id, level, campaign, adset, name, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (account, id) DO UPDATE SET "
                "level = excluded.level, campaign = excluded.campaign, "
                "adset = excluded.adset, name = excluded.name, status = excluded.status",
                (account, object_id, level, campaign, adset, name, status),
            )
            if level == "ad" and first is not None:
                connection.execute(
                    "INSERT INTO schedules (account, ad, first, last, spend, impressions, "
                    "clicks) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (account, ad) DO UPDATE "
                    "SET first = excluded.first, last = excluded.last, spend = excluded.spend, "
                    "impressions = excluded.impressions, clicks = excluded.clicks",
                    (
                        account,
                        object_id,
                        first.isoformat(),
                        last.isoformat() if last else None,
                        spend,
                        impressions,
                        clicks,
                    ),
                )

    # Test control: restate one ad-day. Keys: spend (a decimal string), impressions, clicks,
    # currency, or omit (True leaves the day without a row).
    def override(self, account: str, ad: str, day: date, **values: object) -> None:
        allowed = {"spend", "impressions", "clicks", "currency", "omit"}
        if not set(values) <= allowed:
            raise ValueError("Unknown synthetic override.")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO overrides (account, ad, day, value) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (account, ad, day) DO UPDATE SET value = excluded.value",
                (account, ad, day.isoformat(), json.dumps(values)),
            )

    # Login for Business: a configuration ID instead of scope, the authorization code grant and
    # no PKCE (V-7).
    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None,
        redirect_uri: str,
        scopes: tuple[str, ...],
    ) -> str:
        query = {
            "client_id": "1000000000000000",
            "redirect_uri": redirect_uri,
            "state": state,
            "config_id": CONFIG_ID,
            "response_type": "code",
            "override_default_response_type": "true",
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    # Stand-in for the Login for Business dialog: the client business grants these ad accounts
    # with these permissions (by default ads_read).
    def approve(
        self,
        authorization_url: str,
        accounts: tuple[str, ...],
        *,
        scopes: tuple[str, ...] = (SCOPE,),
    ) -> str:
        parts = urlsplit(authorization_url)
        if f"{parts.scheme}://{parts.netloc}{parts.path}" != AUTHORIZE_URL:
            raise ValueError("Not a synthetic Meta authorization URL.")
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if (
            query.get("config_id") != CONFIG_ID
            or query.get("response_type") != "code"
            or query.get("override_default_response_type") != "true"
            or "scope" in query
        ):
            raise ValueError("The synthetic Meta provider expects a Login for Business request.")
        code = "sma_code_" + secrets.token_urlsafe(24)
        expires = (_now() + timedelta(seconds=CODE_SECONDS)).isoformat()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO codes (digest, challenge, redirect_uri, scopes, account, label, "
                "kind, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _digest(code),
                    "",
                    query.get("redirect_uri", ""),
                    " ".join(scopes),
                    ",".join(accounts),
                    None,
                    "business",
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
                    "SELECT redirect_uri, scopes, account, expires_at, used FROM codes "
                    "WHERE digest = ?",
                    (_digest(code),),
                ).fetchone()
                valid = (
                    row is not None
                    and not row[4]
                    and datetime.fromisoformat(row[3]) > _now()
                    and row[0] == redirect_uri
                )
                connection.execute("UPDATE codes SET used = 1 WHERE digest = ?", (_digest(code),))
                if not valid:
                    self._call(connection, "exchange", "invalid_grant")
                    error = ProviderError(ErrorKind.PERMANENT, "invalid_grant")
                else:
                    grant_id = connection.execute(
                        "INSERT INTO grants (account, label, kind, scopes) VALUES (?, ?, ?, ?)",
                        (row[2], None, "business", row[1]),
                    ).lastrowid
                    # Business integration system user tokens never expire by default (V-7).
                    access, _ = self._issue(connection, grant_id, "access_token", None)
                    self._call(connection, "exchange", "ok")
        if error is not None:
            raise error
        return TokenGrant(access, None, None, tuple(row[1].split()), "", None, "business")

    def refresh(self, refresh_token: str) -> TokenGrant:
        raise ProviderError(ErrorKind.UNAUTHORIZED, "invalid_grant")

    # No revocation endpoint is documented for these tokens (V-7); the client business removes
    # the integration under Connected apps.
    def revoke(self, token: str, kind: str) -> RevocationOutcome:
        return "unsupported"

    # Test control standing in for the business removing the integration.
    def remove_integration(self, token: str) -> None:
        with self._transaction() as connection:
            found = self._grant(connection, token)
            if found is not None:
                connection.execute("UPDATE grants SET revoked = 1 WHERE id = ?", (found[0],))

    def verify_webhook(self, headers: object, body: bytes, now: datetime) -> WebhookDelivery:
        raise WebhookRejected("signature_invalid")

    def verify_signed_request(self, signed_request: str, now: datetime) -> SignedRequest:
        raise WebhookRejected("signature_invalid")

    def confirm_deleted(
        self, access_token: str, *, stream: str, object_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        return ()

    # The grant's accounts and scopes for a usable token, or None.
    def _access(
        self, connection: sqlite3.Connection, token: str
    ) -> tuple[set[str], set[str]] | None:
        found = self._grant(connection, token, "access_token")
        if found is None or found[1]:
            return None
        accounts, scopes = connection.execute(
            "SELECT account, scopes FROM grants WHERE id = ?", (found[0],)
        ).fetchone()
        return set(filter(None, accounts.split(","))), set(scopes.split())

    def _account(self, connection: sqlite3.Connection, account: str) -> tuple | None:
        return connection.execute(
            "SELECT id, currency, zone, status, name FROM accounts WHERE id = ?", (account,)
        ).fetchone()

    # GET /act_<id>?fields=id,name,currency,timezone_name,account_status with the new token. A
    # grant that does not cover the account is refused (D2).
    def describe_account(self, access_token: str, account: str) -> AccountSnapshot:
        with self._transaction() as connection:
            if self._behavior(connection, "describe") == "retryable":
                self._call(connection, "describe", "retryable")
                raise ProviderError(ErrorKind.RETRYABLE, "unavailable")
            access = self._access(connection, access_token)
            row = self._account(connection, account)
            if access is None:
                self._call(connection, "describe", "unauthorized")
                raise ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")
            if row is None or account not in access[0]:
                self._call(connection, "describe", "forbidden")
                raise ProviderError(ErrorKind.FORBIDDEN, "account_unavailable")
            self._call(connection, "describe", "ok", account)
        return AccountSnapshot(
            account,
            row[4],
            "ad_account",
            row[2],
            {"currency": row[1], "timezone_name": row[2], "account_status": row[3], "name": row[4]},
        )

    def _overrides(self, connection: sqlite3.Connection, account: str) -> dict:
        return {
            (ad, date.fromisoformat(day)): json.loads(value)
            for ad, day, value in connection.execute(
                "SELECT ad, day, value FROM overrides WHERE account = ?", (account,)
            )
        }

    # The daily rows of [first, end) in day order, then ad ID.
    def _rows(
        self,
        connection: sqlite3.Connection,
        account: str,
        currency: str,
        zone: str,
        first: date,
        end: date,
    ) -> list[ProviderRecord]:
        overrides = self._overrides(connection, account)
        parents = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT id, campaign, adset FROM objects WHERE account = ? AND level = 'ad'",
                (account,),
            )
        }
        schedules = connection.execute(
            "SELECT ad, first, last, spend, impressions, clicks FROM schedules "
            "WHERE account = ? ORDER BY ad",
            (account,),
        ).fetchall()
        records = []
        day = first
        while day < end:
            for ad, start, last, spend, impressions, clicks in schedules:
                if day < date.fromisoformat(start) or (last and day > date.fromisoformat(last)):
                    continue
                values = overrides.get((ad, day), {})
                if values.get("omit"):
                    continue
                campaign, adset = parents.get(ad, (None, None))
                records.append(
                    ProviderRecord(
                        ad,
                        local_start(day, zone),
                        {
                            "impressions": int(values.get("impressions", impressions)),
                            "clicks": int(values.get("clicks", clicks)),
                        },
                        attributes={
                            "date": day.isoformat(),
                            "spend": str(values.get("spend", spend)),
                            "currency": str(values.get("currency", currency)),
                            "campaign_id": campaign,
                            "adset_id": adset,
                        },
                    )
                )
            day += timedelta(days=1)
        return records

    def _page(
        self,
        connection: sqlite3.Connection,
        stream: str,
        account: str,
        zone: str,
        position: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> ProviderPage:
        clock = self._clock(connection)
        _, currency, account_zone, status, name = self._account(connection, account)
        if stream == "account":
            record = ProviderRecord(
                account,
                clock,
                attributes={
                    "currency": currency,
                    "timezone_name": account_zone,
                    "account_status": status,
                    "name": name,
                },
            )
            return ProviderPage((record,), None, None, clock, name)
        if stream == "ad_objects":
            offset = int(position) if position is not None else 0
            objects = connection.execute(
                "SELECT id, level, campaign, adset, name, status FROM objects WHERE account = ? "
                "ORDER BY CASE level WHEN 'campaign' THEN 0 WHEN 'adset' THEN 1 ELSE 2 END, id",
                (account,),
            ).fetchall()
            chunk = objects[offset : offset + PAGE_OBJECTS]
            records = tuple(
                ProviderRecord(
                    item[0],
                    clock,
                    attributes={
                        "level": item[1],
                        "campaign_id": item[2],
                        "adset_id": item[3],
                        "name": item[4],
                        "effective_status": item[5],
                    },
                )
                for item in chunk
            )
            following = offset + PAGE_OBJECTS
            cursor = f"{CURSOR_PREFIX}{following}" if following < len(objects) else None
            return ProviderPage(records, cursor, None, clock)
        # ad_daily: days of the account zone; the read ends at the start of today (V-2).
        today = local_day(clock, zone)
        if position is None:
            first = (
                today - timedelta(days=CONNECT_DAYS) if since is None else local_day(since, zone)
            )
            first = max(first, today - timedelta(days=HISTORY_DAYS))
            window, offset = first, 0
        else:
            first, window, offset = parse_day_cursor(position)
        end = today if until is None else min(today, local_day(until, zone))
        window_end = min(window + timedelta(days=WINDOW_DAYS), end)
        rows = (
            self._rows(connection, account, currency, zone, window, window_end)
            if window < end
            else []
        )
        size = self._number(connection, "page_rows")
        chunk = rows[offset : offset + size]
        if offset + size < len(rows):
            cursor = day_cursor(first, window, offset + size)
        elif window_end < end:
            cursor = day_cursor(first, window_end, 0)
        else:
            cursor = None
        start = local_start(first, zone)
        through = local_start(max(first, end), zone)
        return ProviderPage(
            tuple(chunk),
            CURSOR_PREFIX + cursor if cursor else None,
            start if first < end else None,
            through,
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
        if self.capability.stream_spec(stream) is None:
            raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")
        position = None
        if cursor is not None:
            if not cursor.startswith(CURSOR_PREFIX):
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
            position = cursor.removeprefix(CURSOR_PREFIX)
            if stream == "ad_daily":
                parse_day_cursor(position)
            elif not (position.isascii() and position.isdigit()):
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
        error: ProviderError | None = None
        page: ProviderPage | None = None
        with self._transaction() as connection:
            behavior, retry_after = self._read_outcome(connection)
            access = self._access(connection, access_token)
            detail = f"{stream}:{position or 0}"
            row = self._account(connection, account or "")
            if behavior == "retryable":
                self._call(connection, "fetch", "retryable", detail)
                error = ProviderError(ErrorKind.RETRYABLE, "graph_2")
            elif behavior == "rate_limited":
                self._call(connection, "fetch", "rate_limited", detail)
                seconds = self._number(connection, "retry_after")
                error = ProviderError(
                    ErrorKind.RATE_LIMITED,
                    "graph_80000",
                    seconds if retry_after is None else retry_after,
                )
            elif behavior == "permanent":
                self._call(connection, "fetch", "permanent", detail)
                error = ProviderError(ErrorKind.PERMANENT, "graph_100")
            elif access is None or behavior == "unauthorized":
                self._call(connection, "fetch", "unauthorized", detail)
                error = ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")
            elif (
                behavior == "forbidden"
                or row is None
                or account not in access[0]
                or SCOPE not in access[1]
            ):
                self._call(connection, "fetch", "forbidden", detail)
                error = ProviderError(ErrorKind.FORBIDDEN, "permission")
            else:
                assert account is not None
                page = self._page(
                    connection, stream, account, day_zone or row[2], position, since, until
                )
                self._call(connection, "fetch", "ok", detail)
        if error is not None:
            raise error
        assert page is not None
        return page

    # Test inspection: (stream:position, outcome) of each read in order.
    def stream_reads(self) -> list[tuple[str, str]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT detail, outcome FROM calls WHERE operation = 'fetch' ORDER BY seq"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]


__all__ = ["CAPABILITY", "SyntheticMetaAdsProvider", "local_day", "local_start"]
