"""Meta-shaped synthetic conversion receiver for local development and tests (specification 014-B).

It reproduces the semantics that Meta's official Conversions API documentation describes (read
2026-11-20; entry review section 2.4, V-8 to V-15), never the live service:

- Authorization: the Login for Business stand-in of the spend provider, granting datasets
  instead of ad accounts. Sending needs ads_read (V-14). Tokens do not expire, have no refresh
  and cannot be revoked through an API (V-7).
- send_event validates one event as the documented API does: event_name, event_time (Unix
  seconds, at most 7 days old, which fails the whole request), action_source and user_data are
  required; website events also need event_source_url and client_user_agent (V-9); a Purchase
  needs value and currency (V-11). An accepted request answers events_received, messages and an
  fbtrace_id (V-8).
- Deduplication: events with the same dataset, event name and event ID within 48 hours count
  once, repeated server events included (V-12). Events sent with a test event code are kept
  apart and never counted.
- Failures on demand: a script of outcomes produces HTTP 5xx, throttling, an invalid token, a
  missing permission, an invalid parameter, an unknown dataset, an expired event and a wrong
  events_received, with the Graph codes of V-13.

State lives in its own SQLite file, shared by the API and the worker, through the storage of
the 009 synthetic provider. The define methods and behaviors are test controls.
"""

import json
import re
import secrets
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

from app.connectors.contracts import (
    AccountSnapshot,
    Capability,
    DeliveryAnswer,
    ErrorKind,
    ProviderError,
    ProviderPage,
    RevocationOutcome,
    SignedRequest,
    TokenGrant,
    WebhookDelivery,
    WebhookRejected,
)
from app.connectors.synthetic import CODE_SECONDS, SyntheticProvider, _digest, _now

AUTHORIZE_URL = "https://synthetic-meta.invalid/v27.0/dialog/oauth/capi"
CONFIG_ID = "1000000000000002"
SCOPE = "ads_read"
DATASET = re.compile(r"[1-9][0-9]{0,19}")
ACTION_SOURCES = frozenset(
    {
        "email",
        "website",
        "app",
        "phone_call",
        "chat",
        "physical_store",
        "system_generated",
        "business_messaging",
        "other",
    }
)
USER_DATA_KEYS = frozenset(
    {
        "em",
        "ph",
        "fn",
        "ln",
        "db",
        "ge",
        "ct",
        "st",
        "zp",
        "country",
        "external_id",
        "client_ip_address",
        "client_user_agent",
        "fbc",
        "fbp",
    }
)
MAX_AGE = timedelta(days=7)
DEDUPLICATION = timedelta(hours=48)
SEND_OUTCOMES = frozenset(
    {
        "ok",
        "server_error",
        "throttled",
        "invalid_token",
        "permission",
        "invalid_parameter",
        "unknown_dataset",
        "expired",
        "wrong_count",
    }
)
CAPABILITY = Capability(
    provider="synthetic_meta_capi",
    version="synthetic-meta-capi-1",
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
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, name TEXT)",
    "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, dataset TEXT, event_name TEXT, "
    "event_id TEXT, event_time INTEGER, received_at TEXT, test_code TEXT, body TEXT)",
)


class SyntheticMetaCapiProvider(SyntheticProvider):
    capability = CAPABILITY

    def __init__(self, path) -> None:
        super().__init__(path)
        with self._transaction() as connection:
            for statement in SCHEMA:
                connection.execute(statement)

    def __repr__(self) -> str:
        return "SyntheticMetaCapiProvider()"

    def _clock(self, connection: sqlite3.Connection) -> datetime:
        row = connection.execute("SELECT value FROM behaviors WHERE name = 'clock'").fetchone()
        return datetime.fromisoformat(row[0]) if row else _now()

    # Test control: "clock" (an ISO instant for the age limit and deduplication, otherwise the
    # real clock), "retry_after" (seconds of a throttling answer), "send_script" (comma-separated
    # outcomes of the next sends, consumed in order) or the "exchange" mode.
    def set_behavior(self, name: str, value: str) -> None:
        if name == "clock":
            if datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("The synthetic clock needs a time zone.")
        elif name == "retry_after":
            if int(value) < 0:
                raise ValueError("Synthetic number out of range.")
        elif name == "send_script":
            if not set(filter(None, value.split(","))) <= SEND_OUTCOMES:
                raise ValueError("Unknown synthetic send outcome.")
        elif name != "exchange" or value not in {"ok", "retryable"}:
            raise ValueError("Unknown synthetic behavior.")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO behaviors (name, value) VALUES (?, ?) "
                "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                (name, value),
            )

    # Test control: create a dataset (Meta pixel ID).
    def define_dataset(self, dataset: str, name: str = "Synthetic dataset") -> None:
        if not DATASET.fullmatch(dataset):
            raise ValueError("Synthetic datasets are numeric IDs.")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO datasets (id, name) VALUES (?, ?) "
                "ON CONFLICT (id) DO UPDATE SET name = excluded.name",
                (dataset, name),
            )

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

    # Stand-in for the Login for Business dialog: the client business grants these datasets
    # with these permissions (by default ads_read).
    def approve(
        self,
        authorization_url: str,
        datasets: tuple[str, ...],
        *,
        scopes: tuple[str, ...] = (SCOPE,),
    ) -> str:
        parts = urlsplit(authorization_url)
        if f"{parts.scheme}://{parts.netloc}{parts.path}" != AUTHORIZE_URL:
            raise ValueError("Not a synthetic Meta delivery authorization URL.")
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if query.get("config_id") != CONFIG_ID or "scope" in query:
            raise ValueError("The synthetic Meta provider expects a Login for Business request.")
        code = "smc_code_" + secrets.token_urlsafe(24)
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
                    ",".join(datasets),
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
                    error = ProviderError(ErrorKind.PERMANENT, "invalid_grant")
                else:
                    grant_id = connection.execute(
                        "INSERT INTO grants (account, label, kind, scopes) VALUES (?, ?, ?, ?)",
                        (row[2], None, "business", row[1]),
                    ).lastrowid
                    access, _ = self._issue(connection, grant_id, "access_token", None)
                    self._call(connection, "exchange", "ok")
        if error is not None:
            raise error
        return TokenGrant(access, None, None, tuple(row[1].split()), "", None, "business")

    def refresh(self, refresh_token: str) -> TokenGrant:
        raise ProviderError(ErrorKind.UNAUTHORIZED, "invalid_grant")

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

    def fetch_page(self, access_token: str, **_: object) -> ProviderPage:
        raise ProviderError(ErrorKind.PERMANENT, "unknown_stream")

    def confirm_deleted(
        self, access_token: str, *, stream: str, object_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        return ()

    def _access(
        self, connection: sqlite3.Connection, token: str
    ) -> tuple[set[str], set[str]] | None:
        found = self._grant(connection, token, "access_token")
        if found is None or found[1]:
            return None
        datasets, scopes = connection.execute(
            "SELECT account, scopes FROM grants WHERE id = ?", (found[0],)
        ).fetchone()
        return set(filter(None, datasets.split(","))), set(scopes.split())

    # GET /<dataset>?fields=id,name with the new token; a grant without the dataset is refused.
    def describe_account(self, access_token: str, account: str) -> AccountSnapshot:
        with self._transaction() as connection:
            access = self._access(connection, access_token)
            row = connection.execute(
                "SELECT id, name FROM datasets WHERE id = ?", (account,)
            ).fetchone()
            if access is None:
                raise ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")
            if row is None or account not in access[0]:
                raise ProviderError(ErrorKind.FORBIDDEN, "account_unavailable")
            self._call(connection, "describe", "ok", account)
        return AccountSnapshot(account, row[1], "dataset", None, {})

    def _next_outcome(self, connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT value FROM behaviors WHERE name = 'send_script'"
        ).fetchone()
        items = [item for item in (row[0] if row else "").split(",") if item]
        if not items:
            return "ok"
        connection.execute(
            "UPDATE behaviors SET value = ? WHERE name = 'send_script'", (",".join(items[1:]),)
        )
        return items[0]

    # The first problem of an event as the documented API reports it, or None.
    @staticmethod
    def _invalid(event: Mapping[str, object], now: datetime) -> str | None:
        user_data = event.get("user_data")
        custom = event.get("custom_data")
        time_value = event.get("event_time")
        if not isinstance(event.get("event_name"), str) or not event.get("event_name"):
            return "graph_100"
        if not isinstance(time_value, int) or isinstance(time_value, bool):
            return "graph_100"
        if event.get("action_source") not in ACTION_SOURCES:
            return "graph_100"
        if not isinstance(user_data, dict) or not set(user_data) & USER_DATA_KEYS:
            return "graph_100"
        if event.get("action_source") == "website" and (
            not event.get("event_source_url") or not user_data.get("client_user_agent")
        ):
            return "graph_100"
        if event.get("event_name") == "Purchase":
            if not isinstance(custom, dict):
                return "graph_100"
            value, currency = custom.get("value"), custom.get("currency")
            if isinstance(value, bool) or not isinstance(value, int | float):
                return "graph_100"
            if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
                return "graph_100"
        if datetime.fromtimestamp(time_value, UTC) < now - MAX_AGE:
            return "event_too_old"
        return None

    # POST /<dataset>/events with one event and an optional test event code.
    def send_event(
        self,
        access_token: str,
        *,
        dataset: str,
        event: Mapping[str, object],
        test_event_code: str | None,
    ) -> DeliveryAnswer:
        error: ProviderError | None = None
        answer: DeliveryAnswer | None = None
        with self._transaction() as connection:
            now = self._clock(connection)
            outcome = self._next_outcome(connection)
            access = self._access(connection, access_token)
            known = connection.execute("SELECT 1 FROM datasets WHERE id = ?", (dataset,)).fetchone()
            retry_row = connection.execute(
                "SELECT value FROM behaviors WHERE name = 'retry_after'"
            ).fetchone()
            retry_after = int(retry_row[0]) if retry_row else 60
            problem = self._invalid(event, now)
            if outcome == "server_error":
                error = ProviderError(ErrorKind.RETRYABLE, "http_500")
            elif outcome == "throttled":
                error = ProviderError(ErrorKind.RATE_LIMITED, "graph_4", retry_after)
            elif outcome == "invalid_token" or access is None:
                error = ProviderError(ErrorKind.UNAUTHORIZED, "graph_190")
            elif outcome == "permission" or dataset not in access[0] or SCOPE not in access[1]:
                error = ProviderError(ErrorKind.FORBIDDEN, "graph_200")
            elif outcome == "unknown_dataset" or known is None:
                error = ProviderError(ErrorKind.PERMANENT, "dataset_unavailable")
            elif outcome == "invalid_parameter" or problem == "graph_100":
                error = ProviderError(ErrorKind.PERMANENT, "graph_100")
            elif outcome == "expired" or problem == "event_too_old":
                error = ProviderError(ErrorKind.PERMANENT, "event_too_old")
            else:
                trace = "SYN" + secrets.token_hex(8)
                if outcome == "wrong_count":
                    answer = DeliveryAnswer(0, trace)
                else:
                    connection.execute(
                        "INSERT INTO events (dataset, event_name, event_id, event_time, "
                        "received_at, test_code, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            dataset,
                            event.get("event_name"),
                            event.get("event_id"),
                            event.get("event_time"),
                            now.isoformat(),
                            test_event_code,
                            json.dumps(dict(event), sort_keys=True),
                        ),
                    )
                    answer = DeliveryAnswer(1, trace)
            self._call(connection, "send", outcome if error is None else error.provider_code)
        if error is not None:
            raise error
        assert answer is not None
        return answer

    # Test inspection: every received event of a dataset, test events only when test is True.
    def received(self, dataset: str, *, test: bool = False) -> list[dict]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT body, test_code FROM events WHERE dataset = ? AND "
                + ("test_code IS NOT NULL" if test else "test_code IS NULL")
                + " ORDER BY seq",
                (dataset,),
            ).fetchall()
        return [{**json.loads(body), "test_event_code": code} for body, code in rows]

    # Test inspection: the events Meta would count, one per event name and ID within 48 hours of
    # the first copy; test events are not counted.
    def counted(self, dataset: str) -> list[tuple[str, str]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT event_name, event_id, received_at FROM events "
                "WHERE dataset = ? AND test_code IS NULL ORDER BY seq",
                (dataset,),
            ).fetchall()
        first: dict[tuple[str, str], datetime] = {}
        counted = []
        for name, event_id, received in rows:
            key, when = (name, event_id), datetime.fromisoformat(received)
            if key in first and when - first[key] <= DEDUPLICATION:
                continue
            first[key] = when
            counted.append(key)
        return counted


__all__ = ["CAPABILITY", "SyntheticMetaCapiProvider"]
