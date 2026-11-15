"""Synthetic OAuth provider for local development and tests (specification 009-A, D-048).

The provider keeps its state in one SQLite file (standard library sqlite3), so the API and a
separate `python -m app.connector_worker` process observe the same codes, grants, tokens, and
revocations; a process-local dictionary could not. Each operation is one immediate SQLite
transaction. Tokens are stored only as SHA-256 digests. Each authorization code creates its own
grant with its own access and refresh tokens; revoking any token of a grant revokes that grant
and nothing else, so two clients authorizing the same external account remain independent.
This per-grant scope describes this adapter only: each live provider's revocation scope is
established from its own evidence in specifications 010-013.

Settings refuse the synthetic provider outside development. The authorization URL uses the
reserved .invalid domain and is never fetched: tests approve it through `approve`, standing
in for the provider's consent page. Behaviors injected through `set_behavior` simulate
provider failures; they are test controls, not configuration.
"""

import base64
import hashlib
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from app.connectors.contracts import (
    Capability,
    ErrorKind,
    ProviderError,
    ProviderRecord,
    RevocationOutcome,
    TokenGrant,
)

AUTHORIZE_URL = "https://synthetic-provider.invalid/oauth/authorize"
CAPABILITY = Capability(
    provider="synthetic",
    version="synthetic-1",
    pkce="S256",
    refresh=True,
    revocation_scope="grant",
    scopes=("synthetic.metrics.read",),
    metrics=("impressions", "engagements"),
)
CODE_SECONDS = 60
DEFAULT_ACCESS_SECONDS = 3600
OBSERVED_AT = datetime(2026, 11, 1, tzinfo=UTC)
BEHAVIORS = {
    "exchange": {"ok", "retryable"},
    "refresh": {"ok", "invalid_grant", "retryable"},
    "fetch": {"ok", "unauthorized", "retryable"},
    "revoke": {"ok", "retryable", "unsupported"},
}
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS codes (digest TEXT PRIMARY KEY, challenge TEXT, redirect_uri "
    "TEXT, scopes TEXT, account TEXT, label TEXT, expires_at TEXT, used INTEGER DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS grants (id INTEGER PRIMARY KEY, account TEXT, label TEXT, "
    "scopes TEXT, revoked INTEGER DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS tokens (digest TEXT PRIMARY KEY, grant_id INTEGER, kind TEXT, "
    "expires_at TEXT)",
    "CREATE TABLE IF NOT EXISTS behaviors (name TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS calls (seq INTEGER PRIMARY KEY, operation TEXT, outcome TEXT)",
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
    def _call(connection: sqlite3.Connection, operation: str, outcome: str) -> None:
        connection.execute(
            "INSERT INTO calls (operation, outcome) VALUES (?, ?)", (operation, outcome)
        )

    # Test control: inject a failure mode, or set "access_ttl" in seconds (0 issues tokens that
    # are already expired).
    def set_behavior(self, name: str, value: str) -> None:
        if name == "access_ttl":
            int(value)
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
    # account and return the authorization code that the provider would send to redirect_uri.
    def approve(self, authorization_url: str, account: str, label: str | None = None) -> str:
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
                "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _digest(code),
                    query["code_challenge"],
                    query.get("redirect_uri", ""),
                    query.get("scope", ""),
                    account,
                    label,
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
                    "SELECT challenge, redirect_uri, scopes, account, label, expires_at, used "
                    "FROM codes WHERE digest = ?",
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
                        "INSERT INTO grants (account, label, scopes) VALUES (?, ?, ?)",
                        (row[3], row[4], row[2]),
                    ).lastrowid
                    access, expires = self._issue(
                        connection, grant_id, "access_token", self._ttl(connection)
                    )
                    refresh, _ = self._issue(connection, grant_id, "refresh_token", None)
                    self._call(connection, "exchange", "ok")
        if error is not None:
            raise error
        return TokenGrant(access, refresh, expires, tuple(row[2].split()), row[3], row[4])

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
                account, label, scopes = connection.execute(
                    "SELECT account, label, scopes FROM grants WHERE id = ?", (found[0],)
                ).fetchone()
                access, expires = self._issue(
                    connection, found[0], "access_token", self._ttl(connection)
                )
                self._call(connection, "refresh", "ok")
        if error is not None:
            raise error
        return TokenGrant(access, refresh_token, expires, tuple(scopes.split()), account, label)

    def fetch_page(self, access_token: str) -> list[ProviderRecord]:
        error: ProviderError | None = None
        with self._transaction() as connection:
            behavior = self._behavior(connection, "fetch")
            found = self._grant(connection, access_token, "access_token")
            expired = (
                found is not None
                and found[2] is not None
                and datetime.fromisoformat(found[2]) <= _now()
            )
            if behavior == "retryable":
                self._call(connection, "fetch", "retryable")
                error = ProviderError(ErrorKind.RETRYABLE, "unavailable")
            elif found is None or found[1] or expired or behavior == "unauthorized":
                self._call(connection, "fetch", "unauthorized")
                error = ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token")
            else:
                account = connection.execute(
                    "SELECT account FROM grants WHERE id = ?", (found[0],)
                ).fetchone()[0]
                self._call(connection, "fetch", "ok")
        if error is not None:
            raise error
        return [
            ProviderRecord(
                f"{account}-post-{index}",
                OBSERVED_AT,
                {"impressions": 100 * index, "engagements": 10 * index},
            )
            for index in range(1, 4)
        ]

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

    # Test inspection: (operation, outcome) per call in order.
    def calls(self) -> list[tuple[str, str]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT operation, outcome FROM calls ORDER BY seq"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]
