"""Synthetic OAuth provider for local development and tests (specification 009, D-048, D-049).

The provider keeps its state in one SQLite file (standard library sqlite3), so the API and a
separate `python -m app.connector_worker` process observe the same codes, grants, tokens, and
revocations; a process-local dictionary could not. Each operation is one immediate SQLite
transaction. Tokens are stored only as SHA-256 digests. Each authorization code creates its own
grant with its own access and refresh tokens; revoking any token of a grant revokes that grant
and nothing else, so two clients authorizing the same external account remain independent.
This per-grant scope describes this adapter only: each live provider's revocation scope is
established from its own evidence in specifications 010-013.

The data set is deterministic and independent of the wall clock (009-B): one object per day
ending at a fixed anchor date, served newest first in pages behind an opaque cursor. Without a
lower bound a read covers the recent window; a backfill reaches older days down to the history
limit. Each page reports the window it covers. A scripted sequence of outcomes can fail
individual reads with 401, 403, 429 (with Retry-After), retryable 5xx, or permanent errors.

The provider also sends signed webhook deliveries naming an event ID and an external account.
Its application secret is generated once in the state file; deliveries are signed with the
Spec 004 scheme (`t=<unix>,v1=<HMAC-SHA256 of '<t>.<raw body>'>`) in X-Synthetic-Signature.

Settings refuse the synthetic provider outside development. The authorization URL uses the
reserved .invalid domain and is never fetched: tests approve it through `approve`, standing
in for the provider's consent page. Behaviors injected through `set_behavior` simulate
provider failures; they are test controls, not configuration.
"""

import base64
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from app.collection.contract import Rejected, sign_webhook, verify_webhook
from app.connectors.contracts import (
    Capability,
    ErrorKind,
    MetricSpec,
    ProviderError,
    ProviderPage,
    ProviderRecord,
    RevocationOutcome,
    TokenGrant,
    WebhookDelivery,
    WebhookRejected,
)

AUTHORIZE_URL = "https://synthetic-provider.invalid/oauth/authorize"
CAPABILITY = Capability(
    provider="synthetic",
    version="synthetic-3",
    pkce="S256",
    refresh=True,
    revocation_scope="grant",
    scopes=("synthetic.metrics.read",),
    metrics=(
        MetricSpec("impressions", "count"),
        MetricSpec("engagements", "count"),
        MetricSpec("saves", "count", ("business",)),
    ),
    stream="objects",
    history_days=30,
    overlap_days=1,
    cost_unit="synthetic_unit",
    daily_quota=1000,
    freshness_hours=24,
    webhooks=True,
)
# The synthetic webhook reuses the Spec 004 signature contract under its own header.
WEBHOOK_HEADER = "x-synthetic-signature"
ACCOUNT_KINDS = ("business", "creator")
CODE_SECONDS = 60
DEFAULT_ACCESS_SECONDS = 3600
# The newest synthetic object is observed on this day; object i is observed i - 1 days earlier.
OBSERVED_AT = datetime(2026, 11, 1, tzinfo=UTC)
DAY = timedelta(days=1)
CURSOR_PREFIX = "syn_cursor_"
FETCH_OUTCOMES = {"ok", "unauthorized", "forbidden", "rate_limited", "retryable", "permanent"}
NUMBERS = {"access_ttl": 0, "objects": 0, "page_size": 1, "recent_days": 1, "retry_after": 0}
BEHAVIORS = {
    "exchange": {"ok", "retryable"},
    "refresh": {"ok", "invalid_grant", "retryable"},
    "fetch": FETCH_OUTCOMES,
    "revoke": {"ok", "retryable", "unsupported"},
}
DEFAULTS = {"objects": 3, "page_size": 100, "recent_days": 3, "retry_after": 60}
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS codes (digest TEXT PRIMARY KEY, challenge TEXT, redirect_uri "
    "TEXT, scopes TEXT, account TEXT, label TEXT, kind TEXT, expires_at TEXT, "
    "used INTEGER DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS grants (id INTEGER PRIMARY KEY, account TEXT, label TEXT, "
    "kind TEXT, scopes TEXT, revoked INTEGER DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS tokens (digest TEXT PRIMARY KEY, grant_id INTEGER, kind TEXT, "
    "expires_at TEXT)",
    "CREATE TABLE IF NOT EXISTS behaviors (name TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS calls (seq INTEGER PRIMARY KEY, operation TEXT, outcome TEXT, "
    "detail TEXT)",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


class SyntheticProvider:
    capability = CAPABILITY

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        with self._transaction() as connection:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute(
                "INSERT OR IGNORE INTO behaviors (name, value) VALUES ('webhook_secret', ?)",
                (secrets.token_urlsafe(32),),
            )

    def __repr__(self) -> str:
        return "SyntheticProvider()"

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _behavior(self, connection: sqlite3.Connection, name: str) -> str:
        row = connection.execute("SELECT value FROM behaviors WHERE name = ?", (name,)).fetchone()
        return row[0] if row else "ok"

    @staticmethod
    def _call(
        connection: sqlite3.Connection, operation: str, outcome: str, detail: str | None = None
    ) -> None:
        connection.execute(
            "INSERT INTO calls (operation, outcome, detail) VALUES (?, ?, ?)",
            (operation, outcome, detail),
        )

    def _number(self, connection: sqlite3.Connection, name: str) -> int:
        row = connection.execute("SELECT value FROM behaviors WHERE name = ?", (name,)).fetchone()
        return int(row[0]) if row else DEFAULTS[name]

    # Test control: inject a failure mode; set a number ("access_ttl" in seconds, where 0 issues
    # tokens that are already expired, "objects", "page_size", "recent_days", "retry_after");
    # name a metric to report as zero ("zero_metric") or to omit ("omit_metric"), or "" for
    # none; or script the outcomes of the next reads ("fetch_script", comma-separated items of
    # FETCH_OUTCOMES, where "rate_limited:30" sets that read's Retry-After), consumed in order
    # before the "fetch" behavior applies.
    def set_behavior(self, name: str, value: str) -> None:
        if name in NUMBERS:
            if int(value) < NUMBERS[name]:
                raise ValueError("Synthetic number out of range.")
        elif name in {"zero_metric", "omit_metric"}:
            if value and value not in {spec.name for spec in self.capability.metrics}:
                raise ValueError("Unknown synthetic metric.")
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

    def authorization_url(
        self, *, state: str, code_challenge: str, redirect_uri: str, scopes: tuple[str, ...]
    ) -> str:
        query = {
            "response_type": "code",
            "client_id": "tracking-synthetic",
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    # Stand-in for the provider's consent page: approve the authorization URL for one external
    # account of the given kind and return the authorization code that the provider would send
    # to redirect_uri.
    def approve(
        self,
        authorization_url: str,
        account: str,
        label: str | None = None,
        kind: str = "business",
    ) -> str:
        if kind not in ACCOUNT_KINDS:
            raise ValueError("Unknown synthetic account kind.")
        parts = urlsplit(authorization_url)
        if f"{parts.scheme}://{parts.netloc}{parts.path}" != AUTHORIZE_URL:
            raise ValueError("Not a synthetic authorization URL.")
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if query.get("code_challenge_method") != "S256" or not query.get("code_challenge"):
            raise ValueError("The synthetic provider requires S256 PKCE.")
        code = "syn_code_" + secrets.token_urlsafe(24)
        expires = (_now() + timedelta(seconds=CODE_SECONDS)).isoformat()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO codes (digest, challenge, redirect_uri, scopes, account, label, "
                "kind, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _digest(code),
                    query["code_challenge"],
                    query.get("redirect_uri", ""),
                    query.get("scope", ""),
                    account,
                    label,
                    kind,
                    expires,
                ),
            )
        return code

    def _issue(
        self, connection: sqlite3.Connection, grant_id: int, kind: str, seconds: int | None
    ) -> tuple[str, datetime | None]:
        token = f"syn_{'at' if kind == 'access_token' else 'rt'}_" + secrets.token_urlsafe(32)
        expires = _now() + timedelta(seconds=seconds) if seconds is not None else None
        connection.execute(
            "INSERT INTO tokens (digest, grant_id, kind, expires_at) VALUES (?, ?, ?, ?)",
            (_digest(token), grant_id, kind, expires.isoformat() if expires else None),
        )
        return token, expires

    def _ttl(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT value FROM behaviors WHERE name = 'access_ttl'").fetchone()
        return int(row[0]) if row else DEFAULT_ACCESS_SECONDS

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> TokenGrant:
        error: ProviderError | None = None
        with self._transaction() as connection:
            if self._behavior(connection, "exchange") == "retryable":
                self._call(connection, "exchange", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "unavailable")
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
                    and secrets.compare_digest(row[0], s256(code_verifier))
                )
                # A presented code is spent whether or not the exchange succeeds.
                connection.execute("UPDATE codes SET used = 1 WHERE digest = ?", (_digest(code),))
                if not valid:
                    self._call(connection, "exchange", "invalid_grant")
                    error = ProviderError(ErrorKind.PERMANENT, "invalid_grant")
                else:
                    grant_id = connection.execute(
                        "INSERT INTO grants (account, label, kind, scopes) VALUES (?, ?, ?, ?)",
                        (row[3], row[4], row[7], row[2]),
                    ).lastrowid
                    access, expires = self._issue(
                        connection, grant_id, "access_token", self._ttl(connection)
                    )
                    refresh, _ = self._issue(connection, grant_id, "refresh_token", None)
                    self._call(connection, "exchange", "ok")
        if error is not None:
            raise error
        return TokenGrant(access, refresh, expires, tuple(row[2].split()), row[3], row[4], row[7])

    def _grant(
        self, connection: sqlite3.Connection, token: str, kind: str | None = None
    ) -> tuple[int, bool, str | None] | None:
        row = connection.execute(
            "SELECT t.grant_id, g.revoked, t.expires_at, t.kind FROM tokens t "
            "JOIN grants g ON g.id = t.grant_id WHERE t.digest = ?",
            (_digest(token),),
        ).fetchone()
        if row is None or (kind is not None and row[3] != kind):
            return None
        return row[0], bool(row[1]), row[2]

    # Refresh issues a new access token; the refresh token is not rotated.
    def refresh(self, refresh_token: str) -> TokenGrant:
        error: ProviderError | None = None
        with self._transaction() as connection:
            behavior = self._behavior(connection, "refresh")
            found = self._grant(connection, refresh_token, "refresh_token")
            if behavior == "retryable":
                self._call(connection, "refresh", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "unavailable")
            elif found is None or found[1] or behavior == "invalid_grant":
                self._call(connection, "refresh", "invalid_grant")
                error = ProviderError(ErrorKind.UNAUTHORIZED, "invalid_grant")
            else:
                account, label, scopes, kind = connection.execute(
                    "SELECT account, label, scopes, kind FROM grants WHERE id = ?", (found[0],)
                ).fetchone()
                access, expires = self._issue(
                    connection, found[0], "access_token", self._ttl(connection)
                )
                self._call(connection, "refresh", "ok")
        if error is not None:
            raise error
        return TokenGrant(
            access, refresh_token, expires, tuple(scopes.split()), account, label, kind
        )

    # The next scripted read outcome, if any, removed from the script; otherwise the behavior.
    def _read_outcome(self, connection: sqlite3.Connection) -> tuple[str, int | None]:
        row = connection.execute(
            "SELECT value FROM behaviors WHERE name = 'fetch_script'"
        ).fetchone()
        items = [item for item in (row[0] if row else "").split(",") if item]
        if items:
            connection.execute(
                "UPDATE behaviors SET value = ? WHERE name = 'fetch_script'",
                (",".join(items[1:]),),
            )
            outcome, _, seconds = items[0].partition(":")
            return outcome, int(seconds) if seconds else None
        return self._behavior(connection, "fetch"), None

    # The window [since, until) after the history limit; since None is the recent window.
    def _window(
        self, connection: sqlite3.Connection, since: datetime | None, until: datetime | None
    ) -> tuple[datetime, datetime]:
        newest = OBSERVED_AT + DAY
        end = newest if until is None else min(until, newest)
        oldest = newest - self.capability.history_days * DAY
        start = newest - self._number(connection, "recent_days") * DAY if since is None else since
        return max(start, oldest), end

    def fetch_page(
        self,
        access_token: str,
        *,
        stream: str = "objects",
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ProviderPage:
        if stream != self.capability.stream:
            raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")
        error: ProviderError | None = None
        offset = 0
        if cursor is not None:
            digits = cursor.removeprefix(CURSOR_PREFIX)
            if not cursor.startswith(CURSOR_PREFIX) or not digits.isdigit():
                raise ProviderError(ErrorKind.PERMANENT, "invalid_cursor")
            offset = int(digits)
        with self._transaction() as connection:
            behavior, retry_after = self._read_outcome(connection)
            found = self._grant(connection, access_token, "access_token")
            expired = (
                found is not None
                and found[2] is not None
                and datetime.fromisoformat(found[2]) <= _now()
            )
            detail = str(offset)
            if behavior == "retryable":
                self._call(connection, "fetch", "retryable", detail)
                error = ProviderError(ErrorKind.RETRYABLE, "unavailable")
            elif behavior == "rate_limited":
                self._call(connection, "fetch", "rate_limited", detail)
                seconds = self._number(connection, "retry_after")
                error = ProviderError(
                    ErrorKind.RATE_LIMITED,
                    "too_many_requests",
                    seconds if retry_after is None else retry_after,
                )
            elif behavior == "permanent":
                self._call(connection, "fetch", "permanent", detail)
                error = ProviderError(ErrorKind.PERMANENT, "bad_request")
            elif found is None or found[1] or expired or behavior == "unauthorized":
                self._call(connection, "fetch", "unauthorized", detail)
                error = ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")
            elif behavior == "forbidden":
                self._call(connection, "fetch", "forbidden", detail)
                error = ProviderError(ErrorKind.FORBIDDEN, "insufficient_permission")
            else:
                account, kind = connection.execute(
                    "SELECT account, kind FROM grants WHERE id = ?", (found[0],)
                ).fetchone()
                start, end = self._window(connection, since, until)
                size = self._number(connection, "page_size")
                total = self._number(connection, "objects")
                zero = self._behavior(connection, "zero_metric")
                omit = self._behavior(connection, "omit_metric")
                self._call(connection, "fetch", "ok", detail)
        if error is not None:
            raise error
        indexes = [
            index for index in range(1, total + 1) if start <= OBSERVED_AT - (index - 1) * DAY < end
        ]
        records = []
        for index in indexes[offset : offset + size]:
            metrics: dict[str, int | float] = {
                "impressions": 100 * index,
                "engagements": 10 * index,
            }
            if kind == "business":
                metrics["saves"] = index
            if zero in metrics:
                metrics[zero] = 0
            metrics.pop(omit, None)
            records.append(
                ProviderRecord(f"{account}-post-{index}", OBSERVED_AT - (index - 1) * DAY, metrics)
            )
        following = offset + size
        return ProviderPage(
            tuple(records),
            f"{CURSOR_PREFIX}{following}" if following < len(indexes) else None,
            start,
            end,
        )

    def revoke(self, token: str, kind: str) -> RevocationOutcome:
        error: ProviderError | None = None
        with self._transaction() as connection:
            behavior = self._behavior(connection, "revoke")
            found = self._grant(connection, token, kind)
            if behavior == "unsupported":
                self._call(connection, "revoke", "unsupported")
                return "unsupported"
            if behavior == "retryable":
                self._call(connection, "revoke", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "unavailable")
            elif found is None:
                self._call(connection, "revoke", "unknown_token")
                error = ProviderError(ErrorKind.PERMANENT, "unknown_token")
            else:
                connection.execute("UPDATE grants SET revoked = 1 WHERE id = ?", (found[0],))
                self._call(connection, "revoke", "ok")
        if error is not None:
            raise error
        return "done"

    # Test inspection: whether the provider would accept this token now.
    def token_usable(self, token: str) -> bool:
        with self._transaction() as connection:
            found = self._grant(connection, token)
        if found is None or found[1]:
            return False
        return found[2] is None or datetime.fromisoformat(found[2]) > _now()

    # Test inspection: (account, revoked) per grant in creation order.
    def grants(self) -> list[tuple[str, bool]]:
        with self._transaction() as connection:
            rows = connection.execute("SELECT account, revoked FROM grants ORDER BY id").fetchall()
        return [(row[0], bool(row[1])) for row in rows]

    def _webhook_secret(self) -> str:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT value FROM behaviors WHERE name = 'webhook_secret'"
            ).fetchone()
        return row[0]

    # Test control standing in for the provider's sender: the signature header for a body.
    def sign_delivery(self, body: bytes, timestamp: int) -> str:
        return f"t={timestamp},v1={sign_webhook(self._webhook_secret(), timestamp, body)}"

    # Verify the signature over the exact raw body before parsing it, then read the event ID
    # and the external account; anything else in the body is ignored.
    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, now: datetime
    ) -> WebhookDelivery:
        try:
            verify_webhook(headers.get(WEBHOOK_HEADER), body, [self._webhook_secret()], now)
        except Rejected as rejection:
            raise WebhookRejected(rejection.reason) from None
        try:
            data = json.loads(body)
            event_id, account = data["event_id"], data["account_id"]
        except (ValueError, TypeError, KeyError):
            raise WebhookRejected("invalid_delivery") from None
        valid = all(
            isinstance(value, str) and 1 <= len(value) <= 128 for value in (event_id, account)
        )
        if not valid:
            raise WebhookRejected("invalid_delivery")
        return WebhookDelivery(event_id, account)

    # Test inspection: (offset, outcome) of each read in order, so a test can show which pages
    # were requested and that none was skipped.
    def reads(self) -> list[tuple[int, str]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT detail, outcome FROM calls WHERE operation = 'fetch' ORDER BY seq"
            ).fetchall()
        return [(int(row[0]), row[1]) for row in rows]

    # Test inspection: (operation, outcome) per call in order.
    def calls(self) -> list[tuple[str, str]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT operation, outcome FROM calls ORDER BY seq"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]
