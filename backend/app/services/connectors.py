"""Connector connection lifecycle and synchronization (specification 009, D-048, D-049).

An Owner or Admin starts a connect or reconnect authorization for one client. The provider
redirects to one fixed callback, which recovers the agency, client, initiator, and, for a
reconnect, the connection and expected generation from the single-use state. The callback
consumes the state and commits before any provider call, exchanges the code with the derived
PKCE verifier while holding no lock, and then installs the grant in a second transaction that
rechecks the session, the manager role, the client, and the connection. When that
installation fails for any reason, including a lost race or a failed commit, the newly issued
grant is revoked at the provider: a provider grant survives a local rollback, and the cleanup
targets only that new grant.

Workers carry agency, client, connection, and generation in each run and recheck them when
they claim work and before they persist results. Every result write locks the agency and
client rows (FOR SHARE) and then the connection, and requires an active agency and client, an
active connection, and the run's generation. Disconnect takes the agency write lock and then
the connection, so a write either commits first and is purged, or sees the new generation and
is discarded. Teardown revokes each outstanding token at the provider, then destroys the
sealed material and purges provider data in one transaction; it finishes regardless of a
later archive or suspension, and after the deadline it finishes with the revocation reported
as failed. Every step can be repeated: a revocation that succeeded before a crash is
confirmed again on the next run.

Synchronization (009-B, D-049) reads a run's window page by page. Each page's records and the
checkpoint cursor commit together under the attempt fence, so a reclaimed run resumes at the
next unstored page; the last page moves the coverage watermarks and finishes the run. Every
provider data call is reserved against a per-connection daily allocation and the provider's
daily quota before it is made. Rate-limited and retryable failures defer the run (Retry-After
or backoff, at most five times); forbidden and permanent failures fail it; a budget stop defers
it to the next UTC day. The worker's scheduling step queues incremental runs that are due.

010-A (D-053) runs several streams per connection, each with its own open run, checkpoint and
interval; offers no PKCE when the provider has none; refreshes a self-refreshing long-lived
access token before it expires; stores each record's media product type and the reason for
every metric the provider did not report; and lets a provider's signed deauthorize or data
deletion request start the disconnect of every connection of the named account.

010-C (D-055) registers the live Instagram adapter only when it is enabled and configured and
its provider rules are current, and logs connector_extra_scopes when a kept grant carries
permissions that were not requested.

011-A (D-058, D-060) adds the runtime rules for Google-shaped providers. A grant without every
requested scope, or one the adapter refuses, is not installed. Grants shared by every token of
an account are never revoked while another active connection holds them, and a reconnect
replaces them without a revocation. A run refreshes an access token about to expire and
checks the authorization periodically; a connection left in reconnect_required past its grace
period is disconnected and purged. Quota buckets are counted on their local day and a provider
quota answer defers the run to the next reset. Incremental windows overlap by local days.
Records keep only allow-listed attributes with their refresh time, the label is refreshed from
the provider, and objects missing from a complete inventory read are confirmed gone and purged
from every stream. A connect carries the agent approval its provider requires.
"""

import base64
import hashlib
import hmac
import logging
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import (
    DateTime,
    Engine,
    String,
    case,
    column,
    delete,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy import values as values_clause
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.contracts import (
    UNAVAILABLE_REASONS,
    Capability,
    ConnectorProvider,
    ErrorKind,
    ProviderError,
    ProviderPage,
    QuotaBucket,
    TokenGrant,
)
from app.connectors.instagram import InstagramProvider
from app.connectors.synthetic import SyntheticProvider
from app.connectors.synthetic_instagram import SyntheticInstagramProvider
from app.connectors.synthetic_youtube import SyntheticYouTubeProvider
from app.models import (
    Agency,
    AgencyMembership,
    ClientWorkspace,
    ConnectorCheckpoint,
    ConnectorConnection,
    ConnectorDeletionRequest,
    ConnectorOAuthTransaction,
    ConnectorRecord,
    ConnectorSyncRun,
    ConnectorTokenSecret,
    ConnectorUsageRecord,
)
from app.privacy.providers import feature_allowed, rule
from app.privacy.token_secrets import (
    AAD_VERSION,
    ALGORITHM,
    LocalKeyring,
    SealedSecret,
    SecretContext,
    open_secret,
    seal,
)
from app.security import AuthError, digest, keyed_digest, new_token, now_utc
from app.services.access import Principal, ScopedAccess
from app.services.auth import AuthService
from app.services.tenancy import MANAGERS, AccessDenied, TenancyService

TRANSACTION_SECONDS = 600
RUN_LEASE = timedelta(minutes=5)
TEARDOWN_LEASE = timedelta(minutes=2)
LIVE = ("active", "reconnect_required")
OPEN_RUNS = ("queued", "running")
# Revocation outcomes that settle a token version: confirmed, unsupported, kept because another
# active connection shares the account's grant, or not required (a reconnect of an
# account-wide grant, 011-A D5).
SettledRevocation = ("done", "unsupported", "shared", "not_required")
Purpose = Literal["connect", "reconnect"]
# Synchronization policy (D-049 decisions D14 and D15).
MAX_DEFERRALS = 5
RETRY_BASE = timedelta(seconds=30)
RETRY_CAP = timedelta(minutes=15)
RATE_LIMIT_DEFAULT = 60
RATE_LIMIT_CAP = 3600
USAGE_LOCK_NAMESPACE = 9009
logger = logging.getLogger("tracking")


# A connector failure with a fixed public code and HTTP status.
class ConnectorError(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


# Fixed codes the callback may append to the completion URL; anything else is connection_failed.
CALLBACK_ERRORS = frozenset(
    {
        "connection_failed",
        "connection_cancelled",
        "connection_denied",
        "connection_changed",
        "account_mismatch",
        "account_already_connected",
        "provider_unavailable",
        "connector_not_configured",
        "scopes_missing",
        "account_unavailable",
    }
)


# Provider rules that must be current before a live adapter is registered (003-C, D-025).
LIVE_RULES = {"instagram": ("meta.platform_data", "instagram.login_api")}


# Whether every provider rule a live adapter depends on allows it today.
def rules_allow(provider: str, today: date) -> bool:
    return all(feature_allowed(rule(name), today).allowed for name in LIVE_RULES[provider])


# The adapters this process may use: the development synthetic providers when their state
# file is configured, and the live Instagram adapter when it is enabled and configured and its
# provider rules are current (010-C, D-055). A rule that becomes due for review takes effect
# when the registry is next built, at the API's or worker's next start.
def build_providers(settings: Settings, today: date | None = None) -> dict[str, ConnectorProvider]:
    registry: dict[str, ConnectorProvider] = {}
    if settings.connector_synthetic_state is not None:
        state = settings.connector_synthetic_state
        registry["synthetic"] = SyntheticProvider(state)
        registry["synthetic_instagram"] = SyntheticInstagramProvider(
            state.with_name(state.stem + "-instagram" + state.suffix)
        )
        registry["synthetic_youtube"] = SyntheticYouTubeProvider(
            state.with_name(state.stem + "-youtube" + state.suffix)
        )
    if settings.connector_instagram_enabled and rules_allow("instagram", today or now_utc().date()):
        registry["instagram"] = InstagramProvider(
            settings.instagram_app_id, settings.instagram_app_secret.get_secret_value()
        )
    return registry


# The stream names a provider synchronizes, in declaration order.
def stream_names(provider: ConnectorProvider | None) -> tuple[str, ...]:
    if provider is None:
        return ("objects",)
    return tuple(spec.name for spec in provider.capability.stream_specs())


def provider_for(registry: Mapping[str, ConnectorProvider], name: str) -> ConnectorProvider:
    provider = registry.get(name)
    if provider is None:
        raise ConnectorError("provider_unavailable", 404)
    return provider


def require_keys(settings: Settings) -> LocalKeyring:
    keys = settings.token_keys()
    if keys is None:
        raise ConnectorError("connector_not_configured", 503)
    return keys


# PKCE verifier derived from the raw state with a purpose-separated keyed HMAC, so the
# transaction stores neither; 64 hexadecimal characters.
def pkce_verifier(settings: Settings, raw_state: str) -> str:
    return keyed_digest(settings, "connector-pkce", raw_state)


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


# The start of the local day `days` days before the local day of `instant` (011-A, D9), so a
# window starts at a local midnight on both sides of a daylight-saving change.
def local_days_before(instant: datetime, days: int, zone: str) -> datetime:
    local = ZoneInfo(zone)
    day = instant.astimezone(local).date() - timedelta(days=days)
    return datetime.combine(day, time(), local).astimezone(UTC)


# The local day of a quota bucket at `now`, and the instant its next day starts (D10).
def bucket_day(now: datetime, bucket: QuotaBucket | None) -> date:
    return now.astimezone(ZoneInfo(bucket.zone) if bucket else UTC).date()


def next_reset(now: datetime, bucket: QuotaBucket | None) -> datetime:
    local = ZoneInfo(bucket.zone) if bucket else UTC
    day = now.astimezone(local).date() + timedelta(days=1)
    return datetime.combine(day, time(), local).astimezone(UTC)


# Whether another active connection of the provider holds a grant of the same external account
# (011-A, D5). The answer never reaches the caller, so it reveals no other tenant.
def _account_shared(
    session: Session, provider: str, account: str | None, exclude: UUID | None = None
) -> bool:
    if not account:
        return False
    query = select(ConnectorConnection.id).where(
        ConnectorConnection.provider == provider,
        ConnectorConnection.external_account_id == account,
        ConnectorConnection.status == "active",
    )
    if exclude is not None:
        query = query.where(ConnectorConnection.id != exclude)
    return session.scalar(query.limit(1)) is not None


def binding_digest(settings: Settings, binding: str, session_token: str) -> str:
    return keyed_digest(settings, "connector-oauth-binding", binding + "\0" + digest(session_token))


def _context(row: ConnectorTokenSecret) -> SecretContext:
    return SecretContext(
        row.agency_id, row.client_id, row.connection_id, row.id, row.kind, row.version
    )  # type: ignore[arg-type]


def _sealed(row: ConnectorTokenSecret) -> SealedSecret:
    assert row.kek_id and row.wrap_nonce and row.wrapped_dek and row.nonce and row.ciphertext
    return SealedSecret(
        row.kek_id, row.wrap_nonce, row.wrapped_dek, row.nonce, row.ciphertext, row.alg
    )


def _open(keyring: LocalKeyring, row: ConnectorTokenSecret) -> str:
    return open_secret(keyring, _sealed(row), _context(row))


def _new_secret(
    keyring: LocalKeyring,
    connection: ConnectorConnection,
    kind: Literal["access_token", "refresh_token"],
    version: int,
    token: str,
    expires_at: datetime | None,
    now: datetime,
) -> ConnectorTokenSecret:
    row = ConnectorTokenSecret(
        id=uuid4(),
        agency_id=connection.agency_id,
        client_id=connection.client_id,
        connection_id=connection.id,
        kind=kind,
        version=version,
        alg=ALGORITHM,
        aad_version=AAD_VERSION,
        status="active",
        provider_expires_at=expires_at,
        last_refreshed_at=now,
    )
    sealed = seal(keyring, token, _context(row))
    row.kek_id, row.wrap_nonce, row.wrapped_dek = (
        sealed.kek_id,
        sealed.wrap_nonce,
        sealed.wrapped_dek,
    )
    row.nonce, row.ciphertext = sealed.nonce, sealed.ciphertext
    return row


# Destroy one version's sealed material (D-048 decision D8): the row stays as evidence.
def _destroy(row: ConnectorTokenSecret, now: datetime, revocation: str | None = None) -> None:
    row.kek_id = row.wrap_nonce = row.wrapped_dek = row.nonce = row.ciphertext = None
    row.status, row.destroyed_at = "destroyed", now
    if revocation is not None:
        row.revocation = revocation


def _live_secrets(session: Session, connection_id: UUID) -> list[ConnectorTokenSecret]:
    return list(
        session.scalars(
            select(ConnectorTokenSecret)
            .where(
                ConnectorTokenSecret.connection_id == connection_id,
                ConnectorTokenSecret.status != "destroyed",
            )
            .order_by(ConnectorTokenSecret.kind.desc(), ConnectorTokenSecret.version)
            .execution_options(populate_existing=True)
        )
    )


def _next_version(session: Session, connection_id: UUID, kind: str) -> int:
    current = session.scalar(
        select(func.max(ConnectorTokenSecret.version)).where(
            ConnectorTokenSecret.connection_id == connection_id, ConnectorTokenSecret.kind == kind
        )
    )
    return (current or 0) + 1


def _cancel_open_runs(session: Session, connection_id: UUID, now: datetime, kind: str) -> None:
    session.execute(
        update(ConnectorSyncRun)
        .where(
            ConnectorSyncRun.connection_id == connection_id,
            ConnectorSyncRun.status.in_(OPEN_RUNS),
        )
        .values(status="canceled", error_kind=kind, finished_at=now, lease_expires_at=None)
    )


def _enqueue(
    session: Session,
    connection: ConnectorConnection,
    kind: str = "incremental",
    since: datetime | None = None,
    until: datetime | None = None,
    stream: str = "objects",
) -> ConnectorSyncRun:
    run = ConnectorSyncRun(
        id=uuid4(),
        agency_id=connection.agency_id,
        client_id=connection.client_id,
        connection_id=connection.id,
        connection_generation=connection.generation,
        status="queued",
        kind=kind,
        window_since=since,
        window_until=until,
        stream=stream,
    )
    session.add(run)
    return run


# Revoke both tokens of a grant that was issued but not kept. Only a confirmed revocation
# disposes of a token: an "unsupported" outcome or a provider error leaves the grant live and
# is reported with the event connector_grant_disposal_failed and its outcome code ("failed"
# when any call failed, otherwise "unsupported"). No row exists to record it on, and no
# identifier or provider detail is logged (R009-06).
# 011-A (D5): a grant of an account-wide provider that another active connection shares is kept
# (shared=True): revoking it would revoke that connection's tokens too.
def dispose_grant(provider: ConnectorProvider, grant: TokenGrant, shared: bool = False) -> bool:
    if shared:
        logger.info("connector_grant_kept_shared")
        return True
    unresolved: set[str] = set()
    for token, kind in (
        (grant.refresh_token, "refresh_token"),
        (grant.access_token, "access_token"),
    ):
        if token is None:
            continue
        try:
            if provider.revoke(token, kind) != "done":
                unresolved.add("unsupported")
        except ProviderError:
            unresolved.add("failed")
    if unresolved:
        outcome = "failed" if "failed" in unresolved else "unsupported"
        logger.warning("connector_grant_disposal_failed", extra={"outcome": outcome})
    return not unresolved


# Stop a live connection, cancel its runs, and fix the teardown deadline; the worker then
# revokes, destroys, and purges. Used by the Owner/Admin disconnect and, with reason
# "deauthorized" or "deletion_requested", by a provider's signed request (D-053 decision D5).
def start_disconnect(
    session: Session,
    settings: Settings,
    connection: ConnectorConnection,
    reason: str,
    now: datetime,
) -> None:
    connection.status, connection.status_reason = "disconnecting", reason
    connection.reconnect_required_since = None
    connection.generation += 1
    connection.disconnect_requested_at = now
    connection.purge_due_at = now + timedelta(hours=settings.connector_teardown_hours)
    connection.revocation_status = "pending"
    connection.destruction_status = connection.purge_status = "pending"
    connection.updated_at = now
    _cancel_open_runs(session, connection.id, now, "connection_inactive")


# Owner/Admin administration: connect, reconnect, disconnect, and sync requests; audited.
class ConnectorAdmin(TenancyService):
    def __init__(
        self,
        session: Session,
        actor_user_id: UUID,
        settings: Settings,
        registry: Mapping[str, ConnectorProvider],
    ) -> None:
        super().__init__(session, actor_user_id)
        self.settings, self.registry = settings, registry

    def _connection(
        self, agency_id: UUID, client_id: UUID, connection_id: UUID
    ) -> ConnectorConnection:
        item = self.session.scalar(
            select(ConnectorConnection)
            .where(
                ConnectorConnection.agency_id == agency_id,
                ConnectorConnection.client_id == client_id,
                ConnectorConnection.id == connection_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AccessDenied()
        return item

    def _client(self, agency_id: UUID, client_id: UUID, *, active: bool) -> ClientWorkspace:
        query = select(ClientWorkspace).where(
            ClientWorkspace.agency_id == agency_id, ClientWorkspace.id == client_id
        )
        client = self.session.scalar(query.execution_options(populate_existing=True))
        if client is None or (active and client.status != "active"):
            raise AccessDenied()
        return client

    # Start a connect (connection_id None) or reconnect authorization. Returns the provider
    # authorization URL and the raw browser-binding value for the HttpOnly cookie.
    def begin(
        self,
        agency_id: UUID,
        client_id: UUID,
        provider_name: str,
        session_token: str,
        connection_id: UUID | None = None,
        agent_disclosure: str | None = None,
    ) -> tuple[str, str]:
        actor = self._manager(agency_id, write=True)
        self._client(agency_id, client_id, active=True)
        expected: int | None = None
        if connection_id is not None:
            connection = self._connection(agency_id, client_id, connection_id)
            if connection.status != "reconnect_required":
                raise ConnectorError("reconnect_not_available", 409)
            provider_name, expected = connection.provider, connection.generation
        provider = provider_for(self.registry, provider_name)
        required = provider.capability.agent_disclosure
        if required is not None and agent_disclosure != required:
            raise ConnectorError("agent_approval_required", 422)
        require_keys(self.settings)
        raw_state, binding = new_token(), new_token()
        self.session.add(
            ConnectorOAuthTransaction(
                agency_id=agency_id,
                client_id=client_id,
                connection_id=connection_id,
                expected_generation=expected,
                initiator_membership_id=actor.id,
                provider=provider_name,
                purpose="connect" if connection_id is None else "reconnect",
                state_digest=digest(raw_state),
                binding_digest=binding_digest(self.settings, binding, session_token),
                expires_at=now_utc() + timedelta(seconds=TRANSACTION_SECONDS),
                agent_approved_at=now_utc() if required is not None else None,
                agent_disclosure=required,
            )
        )
        self.session.flush()
        url = provider.authorization_url(
            state=raw_state,
            code_challenge=(
                pkce_challenge(pkce_verifier(self.settings, raw_state))
                if provider.capability.pkce
                else None
            ),
            redirect_uri=self.settings.connector_redirect_uri,
            scopes=provider.capability.scopes,
        )
        return url, binding

    # Request disconnection. The first request stops the connection, cancels its runs, and
    # fixes the teardown deadline; repeated requests return the same state and deadline.
    def disconnect(
        self, agency_id: UUID, client_id: UUID, connection_id: UUID, now: datetime | None = None
    ) -> ConnectorConnection:
        self._manager(agency_id, write=True)
        connection = self._connection(agency_id, client_id, connection_id)
        if connection.status not in LIVE:
            return connection
        start_disconnect(
            self.session, self.settings, connection, "user_requested", now or now_utc()
        )
        self._audit(
            agency_id, "connector.disconnect_requested", "connection", connection.id, client_id
        )
        return connection

    # Queue a synchronization of an active connection (D-049 decision D12). An open run of the
    # same kind is returned unchanged; an open run of the other kind refuses the request. A
    # backfill extends the stream's history `days` further back from its oldest covered time,
    # within the provider's history limit, and needs a completed synchronization first.
    def request_sync(
        self,
        agency_id: UUID,
        client_id: UUID,
        connection_id: UUID,
        kind: str = "incremental",
        days: int | None = None,
        stream: str | None = None,
    ) -> ConnectorSyncRun:
        self._manager(agency_id, write=True)
        self._client(agency_id, client_id, active=True)
        connection = self._connection(agency_id, client_id, connection_id)
        if connection.status != "active":
            raise ConnectorError("connection_not_active", 409)
        names = stream_names(self.registry.get(connection.provider))
        stream = stream or names[0]
        if stream not in names:
            raise ConnectorError("invalid_stream", 422)
        existing = self.session.scalar(
            select(ConnectorSyncRun).where(
                ConnectorSyncRun.connection_id == connection.id,
                ConnectorSyncRun.stream == stream,
                ConnectorSyncRun.status.in_(OPEN_RUNS),
            )
        )
        if existing is not None:
            if existing.kind != kind:
                raise ConnectorError("sync_in_progress", 409)
            return existing
        since = until = None
        if kind == "backfill":
            capability = provider_for(self.registry, connection.provider).capability
            spec = capability.stream_spec(stream)
            assert spec is not None
            if days is None or not 1 <= days <= spec.history_days:
                raise ConnectorError("invalid_backfill", 422)
            checkpoint = self.session.scalar(
                select(ConnectorCheckpoint).where(
                    ConnectorCheckpoint.connection_id == connection.id,
                    ConnectorCheckpoint.stream == stream,
                )
            )
            if checkpoint is None or checkpoint.covered_from is None:
                raise ConnectorError("sync_required", 409)
            until = checkpoint.covered_from
            since = until - timedelta(days=days)
        run = _enqueue(self.session, connection, kind, since, until, stream)
        self.session.flush()
        return run


@dataclass(frozen=True)
class CallbackResult:
    purpose: Purpose
    connection_id: UUID


@dataclass(frozen=True)
class _Authorization:
    agency_id: UUID
    client_id: UUID
    connection_id: UUID | None
    expected_generation: int | None
    membership_id: UUID
    provider: str
    purpose: Purpose
    agent_approved_at: datetime | None = None
    agent_disclosure: str | None = None


# Lock the transaction by state digest, require the matching session-bound binding, no prior
# use, and no expiry, and consume it. Commits before the provider is contacted.
def _consume(
    engine: Engine,
    settings: Settings,
    raw_state: str,
    binding: str | None,
    session_token: str | None,
) -> _Authorization:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        item = session.scalar(
            select(ConnectorOAuthTransaction)
            .where(ConnectorOAuthTransaction.state_digest == digest(raw_state))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            item is None
            or item.consumed_at is not None
            or item.expires_at <= now_utc()
            or not binding
            or not session_token
            or not hmac.compare_digest(
                item.binding_digest, binding_digest(settings, binding, session_token)
            )
        ):
            raise ConnectorError("connection_failed", 400)
        item.consumed_at = now_utc()
        return _Authorization(
            item.agency_id,
            item.client_id,
            item.connection_id,
            item.expected_generation,
            item.initiator_membership_id,
            item.provider,
            "connect" if item.purpose == "connect" else "reconnect",
            item.agent_approved_at,
            item.agent_disclosure,
        )


# Recheck that the authorization may still act: the browser session is current, its user
# still holds the initiating Owner or Admin membership of an active agency, and the client is
# active. With write=True the agency write lock is taken, as for every administration change.
def _initiator(
    session: Session,
    settings: Settings,
    authorization: _Authorization,
    session_token: str,
    *,
    write: bool,
) -> tuple[TenancyService, AgencyMembership]:
    user, _ = AuthService(session, settings).authenticate(session_token)
    tenancy = TenancyService(session, user.id)
    member = tenancy._membership(authorization.agency_id, write=write)
    if member.id != authorization.membership_id or member.role not in MANAGERS:
        raise AccessDenied()
    client = session.scalar(
        select(ClientWorkspace)
        .where(
            ClientWorkspace.agency_id == authorization.agency_id,
            ClientWorkspace.id == authorization.client_id,
            ClientWorkspace.status == "active",
        )
        .execution_options(populate_existing=True)
    )
    if client is None:
        raise AccessDenied()
    return tenancy, member


# Lock the reconnect target and require what the authorization expects: the connection still
# requires reconnection at the generation recorded when the authorization began, and the new
# grant is for the same external account. The callback that settles the previous grant takes
# a shared lock and the installation an exclusive one, so neither can observe the other half
# done (R009-08).
def _reconnect_target(
    session: Session, authorization: _Authorization, grant: TokenGrant, *, write: bool
) -> ConnectorConnection:
    connection = session.scalar(
        select(ConnectorConnection)
        .where(
            ConnectorConnection.agency_id == authorization.agency_id,
            ConnectorConnection.client_id == authorization.client_id,
            ConnectorConnection.id == authorization.connection_id,
        )
        .with_for_update(read=not write)
        .execution_options(populate_existing=True)
    )
    if (
        connection is None
        or connection.status != "reconnect_required"
        or connection.generation != authorization.expected_generation
    ):
        raise ConnectorError("connection_changed", 409)
    if grant.external_account_id != connection.external_account_id:
        raise ConnectorError("account_mismatch", 409)
    return connection


# Install a newly exchanged grant after rechecking the initiator, client, and connection.
# A reconnect destroys the previous versions only when each has a settled revocation outcome
# (recorded by _settle_previous), so the outcome stays on the destroyed rows (R009-01).
def _install(
    session: Session,
    settings: Settings,
    keyring: LocalKeyring,
    authorization: _Authorization,
    grant: TokenGrant,
    session_token: str,
    streams: tuple[str, ...] = ("objects",),
    capability: Capability | None = None,
) -> ConnectorConnection:
    tenancy, member = _initiator(session, settings, authorization, session_token, write=True)
    now = now_utc()
    refreshes_label = capability is not None and capability.label_refresh_days is not None
    if authorization.purpose == "connect":
        connection = ConnectorConnection(
            id=uuid4(),
            agency_id=authorization.agency_id,
            client_id=authorization.client_id,
            provider=authorization.provider,
            external_account_id=grant.external_account_id,
            account_label=grant.account_label,
            account_kind=grant.account_kind,
            status="active",
            generation=1,
            granted_scopes=list(grant.scopes),
            created_by_membership_id=member.id,
            connected_at=now,
        )
        session.add(connection)
        session.flush()
        action = "connector.connected"
    else:
        connection = _reconnect_target(session, authorization, grant, write=True)
        for row in _live_secrets(session, connection.id):
            if row.revocation not in SettledRevocation:
                raise ConnectorError("provider_unavailable", 503)
            _destroy(row, now)
        session.flush()
        connection.status, connection.status_reason = "active", None
        connection.reconnect_required_since = None
        connection.generation += 1
        connection.account_label = grant.account_label
        connection.account_kind = grant.account_kind
        connection.granted_scopes = list(grant.scopes)
        connection.connected_at = connection.updated_at = now
        action = "connector.reconnected"
    connection.grant_expires_at = grant.refresh_expires_at
    connection.account_label_refreshed_at = (
        now if refreshes_label and grant.account_label is not None else None
    )
    if authorization.agent_approved_at is not None:
        connection.agent_approved_at = authorization.agent_approved_at
        connection.agent_disclosure = authorization.agent_disclosure
    session.add(
        _new_secret(
            keyring,
            connection,
            "access_token",
            _next_version(session, connection.id, "access_token"),
            grant.access_token,
            grant.access_expires_at,
            now,
        )
    )
    if grant.refresh_token is not None:
        session.add(
            _new_secret(
                keyring,
                connection,
                "refresh_token",
                _next_version(session, connection.id, "refresh_token"),
                grant.refresh_token,
                grant.refresh_expires_at,
                now,
            )
        )
    for stream in streams:
        _enqueue(session, connection, stream=stream)
    tenancy._audit(
        authorization.agency_id, action, "connection", connection.id, authorization.client_id
    )
    return connection


# Before a reconnect replaces the previous grant, revoke each of its outstanding versions at
# the provider and record every outcome on its row. Nothing is revoked unless the reconnect
# could be installed now: the session, the initiator's Owner or Admin membership, the agency
# and client, the expected generation, and the external account are all checked first, so a
# rejected reconnect leaves the previous grant and its recorded outcome intact (R009-09). The
# generation check and the selection of the versions to revoke happen under one shared lock
# on the connection, so a concurrent reconnect cannot install its grant in between and have
# it revoked here; a callback that loses that race revokes only versions of the grant it was
# meant to replace and then disposes of its own grant (R009-08). When any revocation is not
# settled the reconnect is refused and the previous versions stay outstanding, so a later
# reconnect or disconnect retries them and the connection-level result includes them,
# including after a restart. Installation repeats every check under the exclusive lock.
def _settle_previous(
    engine: Engine,
    settings: Settings,
    keyring: LocalKeyring,
    provider: ConnectorProvider,
    authorization: _Authorization,
    grant: TokenGrant,
    session_token: str,
) -> None:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        _initiator(session, settings, authorization, session_token, write=False)
        connection = _reconnect_target(session, authorization, grant, write=False)
        outstanding = [
            _Outstanding(row.id, row.kind, _open(keyring, row))
            for row in _live_secrets(session, connection.id)
            if row.revocation not in SettledRevocation
        ]
    settled = True
    for item in outstanding:
        # Revoking an account-wide grant would revoke the new grant too (011-A, D5).
        if provider.capability.revocation_scope == "account":
            _record_revocation(engine, item.secret_id, "not_required")
            continue
        try:
            _record_revocation(engine, item.secret_id, provider.revoke(item.token, item.kind))
        except ProviderError:
            settled = False
    if not settled:
        raise ConnectorError("provider_unavailable", 503)


# Whether a refused grant of an account-wide provider is shared with an active connection.
def _grant_shared(engine: Engine, provider: ConnectorProvider, grant: TokenGrant) -> bool:
    if provider.capability.revocation_scope != "account":
        return False
    with Session(engine) as session:
        return _account_shared(session, provider.capability.provider, grant.external_account_id)


# Complete a provider callback. Raises ConnectorError with a callback code on any refusal.
def complete_authorization(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    raw_state: str,
    binding: str | None,
    code: str,
    session_token: str | None,
) -> CallbackResult:
    authorization = _consume(engine, settings, raw_state, binding, session_token)
    provider = provider_for(registry, authorization.provider)
    keyring = require_keys(settings)
    try:
        grant = provider.exchange(
            code=code,
            code_verifier=(
                pkce_verifier(settings, raw_state) if provider.capability.pkce else None
            ),
            redirect_uri=settings.connector_redirect_uri,
        )
    except ProviderError as error:
        unavailable = error.kind in {ErrorKind.RETRYABLE, ErrorKind.RATE_LIMITED}
        raise ConnectorError(
            "provider_unavailable" if unavailable else "connection_failed", 400
        ) from None
    capability = provider.capability
    try:
        if grant.refusal is not None:
            raise ConnectorError("account_unavailable", 409)
        if capability.require_all_scopes and not set(capability.scopes) <= set(grant.scopes):
            raise ConnectorError("scopes_missing", 400)
        if authorization.purpose == "reconnect":
            _settle_previous(
                engine, settings, keyring, provider, authorization, grant, session_token or ""
            )
        with Session(engine, expire_on_commit=False) as session, session.begin():
            connection = _install(
                session,
                settings,
                keyring,
                authorization,
                grant,
                session_token or "",
                stream_names(provider),
                capability,
            )
            result = CallbackResult(authorization.purpose, connection.id)
    except Exception as error:
        dispose_grant(provider, grant, _grant_shared(engine, provider, grant))
        if isinstance(error, ConnectorError):
            raise
        if isinstance(error, IntegrityError):
            raise ConnectorError("account_already_connected", 409) from None
        if isinstance(error, (AccessDenied, AuthError)):
            raise ConnectorError("connection_denied", 403) from None
        raise
    # A grant may carry permissions that were not requested (010-B evidence: Instagram grants
    # every permission configured on the app). They are recorded in granted_scopes and flagged,
    # because the product's app must be configured with the read-only permissions only.
    if set(grant.scopes) - set(provider.capability.scopes):
        logger.warning("connector_extra_scopes")
    return result


# Reader-visible view of a connection; worker-only state is never included.
@dataclass(frozen=True)
class ConnectionView:
    id: UUID
    provider: str
    account: dict[str, str | None] | None
    status: str
    status_reason: str | None
    granted_scopes: list[str]
    connected_at: datetime
    last_successful_sync_at: datetime | None
    actions: dict[str, bool]
    disconnect: dict[str, object] | None = field(default=None)
    grant_expires_at: datetime | None = None


# Whether the principal may mutate connections of the agency now: an active user with an
# active Owner or Admin membership. Service keys never may (R009-05).
def can_manage(session: Session, principal: Principal, agency_id: UUID) -> bool:
    if principal.kind != "user":
        return False
    try:
        member = TenancyService(session, principal.identifier)._membership(agency_id)
    except AccessDenied:
        return False
    return member.role in MANAGERS


# Reader view; the action flags combine the connection state with the caller's authority.
def connection_view(row: ConnectorConnection, *, manage: bool) -> ConnectionView:
    disconnect = None
    if row.disconnect_requested_at is not None:
        disconnect = {
            "requested_at": row.disconnect_requested_at,
            "completed_at": row.disconnected_at,
            "revocation": row.revocation_status,
            "secret_destruction": row.destruction_status,
            "data_purge": row.purge_status,
            "purge_due_at": row.purge_due_at,
            "deadline_met": (
                None
                if row.disconnected_at is None or row.purge_due_at is None
                else row.disconnected_at <= row.purge_due_at
            ),
        }
    account = (
        None
        if row.external_account_id is None
        else {"external_account_id": row.external_account_id, "label": row.account_label}
    )
    return ConnectionView(
        id=row.id,
        provider=row.provider,
        account=account,
        status=row.status,
        status_reason=row.status_reason,
        granted_scopes=list(row.granted_scopes),
        connected_at=row.connected_at,
        last_successful_sync_at=row.last_successful_sync_at,
        actions={
            "reconnect": manage and row.status == "reconnect_required",
            "disconnect": manage and row.status in LIVE,
        },
        disconnect=disconnect,
        grant_expires_at=row.grant_expires_at,
    )


def list_connections(session: Session, access: ScopedAccess) -> list[ConnectorConnection]:
    return list(
        session.scalars(
            select(ConnectorConnection)
            .where(
                ConnectorConnection.agency_id == access.agency_id,
                ConnectorConnection.client_id == access.client_id,
            )
            .order_by(ConnectorConnection.created_at, ConnectorConnection.id)
            .limit(100)
        )
    )


def get_connection(
    session: Session, access: ScopedAccess, connection_id: UUID
) -> ConnectorConnection:
    item = session.scalar(
        select(ConnectorConnection).where(
            ConnectorConnection.agency_id == access.agency_id,
            ConnectorConnection.client_id == access.client_id,
            ConnectorConnection.id == connection_id,
        )
    )
    if item is None:
        raise AccessDenied()
    return item


# --- Worker -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Claim:
    run_id: UUID
    agency_id: UUID
    client_id: UUID
    connection_id: UUID
    generation: int
    provider: str
    access_id: UUID
    access_version: int
    access_token: str = field(repr=False)
    access_expires_at: datetime | None
    refresh_token: str | None = field(repr=False)
    attempt: int = 0
    kind: str = "incremental"
    since: datetime | None = None
    until: datetime | None = None
    stream: str = "objects"
    cursor: str | None = field(default=None, repr=False)
    adapter_version: str | None = None
    refresh_mode: str = "refresh_token"
    access_refreshed_at: datetime | None = None


# Lock the claimed run and report this attempt's ownership: "owned" while the run is running
# under the same attempt number, "superseded" when a replacement claim after lease expiry has
# taken it (a higher attempt), and "ended" when it was canceled, finished, or deferred, for
# example by a disconnect. A delayed worker can therefore never act for its replacement
# (R009-02).
def _ownership(session: Session, claim: _Claim) -> str:
    row = session.execute(
        select(ConnectorSyncRun.status, ConnectorSyncRun.attempt)
        .where(ConnectorSyncRun.id == claim.run_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        return "ended"
    if row.attempt != claim.attempt:
        return "superseded"
    return "owned" if row.status == "running" else "ended"


def _owns(session: Session, claim: _Claim) -> bool:
    return _ownership(session, claim) == "owned"


# Lock the agency and client (FOR SHARE), then the connection, then the run, in that order,
# and report whether this attempt's results may still be persisted: "superseded" when another
# attempt owns the run, "client_inactive", or "fenced" when the connection moved on.
def _fence(session: Session, claim: _Claim) -> tuple[ConnectorConnection | None, str | None]:
    agency_id, client_id = claim.agency_id, claim.client_id
    connection_id, generation = claim.connection_id, claim.generation
    agency = session.scalar(
        select(Agency.status)
        .where(Agency.id == agency_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    client = session.scalar(
        select(ClientWorkspace.status)
        .where(ClientWorkspace.agency_id == agency_id, ClientWorkspace.id == client_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    connection = session.scalar(
        select(ConnectorConnection)
        .where(ConnectorConnection.id == connection_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    ownership = _ownership(session, claim)
    if ownership == "superseded":
        return connection, "superseded"
    if agency != "active" or client != "active":
        return connection, "client_inactive"
    if connection is None or connection.status != "active" or connection.generation != generation:
        return connection, "fenced"
    if ownership != "owned":
        return connection, "fenced"
    return connection, None


# Finish the claimed attempt; a superseded attempt changes nothing.
def _finish(
    session: Session, claim: _Claim, status: str, now: datetime, error_kind: str | None = None
) -> None:
    session.execute(
        update(ConnectorSyncRun)
        .where(
            ConnectorSyncRun.id == claim.run_id,
            ConnectorSyncRun.status == "running",
            ConnectorSyncRun.attempt == claim.attempt,
        )
        .values(status=status, error_kind=error_kind, finished_at=now, lease_expires_at=None)
    )


def _not_owned(ownership: str, default: str = "stopped") -> str:
    return "superseded" if ownership == "superseded" else default


# Return the owned run to the queue until `until`, recording why (D-049 decision D14). A
# rate-limit or retryable deferral counts toward MAX_DEFERRALS; a budget deferral does not.
# The checkpoint is untouched, so the next attempt resumes at the stored cursor.
def _requeue(session: Session, claim: _Claim, reason: str, until: datetime) -> None:
    session.execute(
        update(ConnectorSyncRun)
        .where(
            ConnectorSyncRun.id == claim.run_id,
            ConnectorSyncRun.status == "running",
            ConnectorSyncRun.attempt == claim.attempt,
        )
        .values(
            status="queued",
            not_before=until,
            error_kind=reason,
            lease_expires_at=None,
            retries=ConnectorSyncRun.retries
            + (1 if reason in {"rate_limited", "retryable"} else 0),
        )
    )


# The start of the next UTC day, when the daily usage limits reset.
def _next_period(now: datetime) -> datetime:
    day = now.astimezone(UTC).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


# How long a failed call defers its run: the provider's Retry-After for 429 (default 60 s, at
# most 1 hour) and 30 s doubling per earlier deferral for retryable failures (at most 15 min).
def _delay(error: ProviderError, retries: int) -> timedelta:
    if error.kind is ErrorKind.RATE_LIMITED:
        seconds = RATE_LIMIT_DEFAULT if error.retry_after is None else error.retry_after
        return timedelta(seconds=min(max(seconds, 1), RATE_LIMIT_CAP))
    return min(RETRY_BASE * 2**retries, RETRY_CAP)


# Apply the error policy to a failed data call (D-049 decision D14): rate-limited and
# retryable failures defer the run until at most MAX_DEFERRALS have been used, then fail it;
# forbidden, permanent, and other failures fail it without retry. The connection stays active.
# 011-A (D10): for a provider with quota buckets, a provider quota answer defers the run to the
# bucket's next local midnight with budget_exhausted, counted neither as a retry nor a failure.
def _fail_or_defer(
    engine: Engine,
    claim: _Claim,
    error: ProviderError,
    now: datetime,
    capability: Capability | None = None,
) -> str:
    with Session(engine) as session, session.begin():
        ownership = _ownership(session, claim)
        if ownership != "owned":
            return _not_owned(ownership, "discarded")
        if error.kind is ErrorKind.BUDGET_EXHAUSTED and capability and capability.buckets:
            bucket = capability.bucket(error.bucket or "") or capability.buckets[0]
            _requeue(session, claim, "budget_exhausted", next_reset(now, bucket))
            return "deferred"
        retries = session.scalar(
            select(ConnectorSyncRun.retries).where(ConnectorSyncRun.id == claim.run_id)
        )
        retryable = error.kind in {ErrorKind.RATE_LIMITED, ErrorKind.RETRYABLE}
        if retryable and (retries or 0) < MAX_DEFERRALS:
            _requeue(session, claim, error.kind.value, now + _delay(error, retries or 0))
            return "deferred"
        _finish(session, claim, "failed", now, error.kind.value)
    return "failed"


def _usage_key(provider: str) -> int:
    return zlib.crc32(provider.encode()) & 0x7FFFFFFF


# Reserve one data call against the daily limits before it is made (D-049 decision D15). The
# per-provider advisory lock serializes reservations, so concurrent workers cannot together
# exceed the connection allocation or the provider quota. Only the attempt that owns the run
# may reserve. When either limit would be exceeded, the run is deferred to the next period
# with budget_exhausted in the same transaction. 011-A (D10): a provider with quota buckets
# reserves the call's cost in each bucket it touches, against the bucket's cap and
# per-connection allocation for the bucket's local day, and defers to that bucket's next local
# midnight; a refresh reserves nothing there. Returns the usage row IDs (possibly none), or
# None with the run outcome.
def _reserve(
    engine: Engine,
    settings: Settings,
    capability: Capability,
    claim: _Claim,
    operation: str,
    now: datetime,
) -> tuple[list[UUID] | None, str]:
    charges: list[tuple[QuotaBucket | None, int]]
    if capability.buckets:
        charges = []
        for name, units in capability.bucket_costs(operation, claim.stream).items():
            bucket = capability.bucket(name)
            assert bucket is not None, "A stream cost names an undeclared bucket."
            charges.append((bucket, units))
    else:
        charges = [(None, capability.cost(operation))]
    with Session(engine) as session, session.begin():
        session.execute(
            select(func.pg_advisory_xact_lock(USAGE_LOCK_NAMESPACE, _usage_key(claim.provider)))
        )
        ownership = _ownership(session, claim)
        if ownership != "owned":
            return None, _not_owned(ownership)
        rows = []
        for bucket, cost in charges:
            period = bucket_day(now, bucket)
            spent = select(func.coalesce(func.sum(ConnectorUsageRecord.quantity), 0)).where(
                ConnectorUsageRecord.period == period,
                ConnectorUsageRecord.bucket == bucket.name
                if bucket
                else ConnectorUsageRecord.bucket.is_(None),
            )
            connection_spent = session.scalar(
                spent.where(ConnectorUsageRecord.connection_id == claim.connection_id)
            )
            allocation = (
                bucket.connection_daily if bucket else settings.connector_connection_daily_units
            )
            quota = bucket.daily_quota if bucket else capability.daily_quota
            quota_exceeded = False
            if quota is not None:
                provider_spent = session.scalar(
                    spent.where(ConnectorUsageRecord.provider == claim.provider)
                )
                quota_exceeded = provider_spent + cost > quota
            if connection_spent + cost > allocation or quota_exceeded:
                until = next_reset(now, bucket) if bucket else _next_period(now)
                _requeue(session, claim, "budget_exhausted", until)
                return None, "deferred"
            rows.append(
                ConnectorUsageRecord(
                    id=uuid4(),
                    agency_id=claim.agency_id,
                    client_id=claim.client_id,
                    connection_id=claim.connection_id,
                    run_id=claim.run_id,
                    attempt=claim.attempt,
                    provider=claim.provider,
                    operation=operation,
                    unit=bucket.unit if bucket else capability.cost_unit,
                    quantity=cost,
                    period=period,
                    occurred_at=now,
                    bucket=bucket.name if bucket else None,
                )
            )
        session.add_all(rows)
        return [row.id for row in rows], "reserved"


# Record the outcome of reserved calls. A call whose worker stopped before this stays
# "reserved" and still counts against the limits.
def _settle(engine: Engine, usage_ids: list[UUID], outcome: str, now: datetime) -> None:
    if not usage_ids:
        return
    with Session(engine) as session, session.begin():
        session.execute(
            update(ConnectorUsageRecord)
            .where(ConnectorUsageRecord.id.in_(usage_ids))
            .values(outcome=outcome, settled_at=now)
        )


# Claim the oldest queued run whose deferral has passed, or a running run whose lease expired,
# and open its tokens. A run whose agency, client, or connection is no longer eligible is
# canceled instead. The first claim of an incremental run fixes its window from the stream's
# watermark minus the provider's overlap; a later claim of the same run resumes at the cursor
# its last stored page left in the checkpoint.
def _claim(
    engine: Engine,
    keyring: LocalKeyring,
    registry: Mapping[str, ConnectorProvider],
    now: datetime,
) -> tuple[_Claim | None, bool]:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        run = session.scalar(
            select(ConnectorSyncRun)
            .where(
                (
                    (ConnectorSyncRun.status == "queued")
                    & (ConnectorSyncRun.not_before.is_(None) | (ConnectorSyncRun.not_before <= now))
                )
                | (
                    (ConnectorSyncRun.status == "running")
                    & (ConnectorSyncRun.lease_expires_at < now)
                )
            )
            .order_by(ConnectorSyncRun.created_at, ConnectorSyncRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return None, False
        agency = session.scalar(select(Agency.status).where(Agency.id == run.agency_id))
        client = session.scalar(
            select(ClientWorkspace.status).where(
                ClientWorkspace.agency_id == run.agency_id, ClientWorkspace.id == run.client_id
            )
        )
        connection = session.get(ConnectorConnection, run.connection_id)
        reason = None
        if agency != "active" or client != "active":
            reason = "client_inactive"
        elif (
            connection is None
            or connection.status != "active"
            or connection.generation != run.connection_generation
        ):
            reason = "connection_inactive"
        secrets = {row.kind: row for row in _live_secrets(session, run.connection_id)}
        access = secrets.get("access_token")
        if reason is None and access is None:
            reason = "connection_inactive"
        if reason is not None:
            run.status, run.error_kind, run.finished_at = "canceled", reason, now
            run.lease_expires_at = None
            return None, True
        assert connection is not None and access is not None
        provider = registry.get(connection.provider)
        stream = run.stream
        spec = provider.capability.stream_spec(stream) if provider is not None else None
        checkpoint = session.scalar(
            select(ConnectorCheckpoint).where(
                ConnectorCheckpoint.connection_id == connection.id,
                ConnectorCheckpoint.stream == stream,
            )
        )
        if run.attempt == 0 and run.kind == "incremental":
            watermark = checkpoint.complete_through if checkpoint is not None else None
            zone = provider.capability.day_zone if provider is not None else None
            if watermark is not None and spec is not None and zone is not None:
                watermark = local_days_before(watermark, spec.overlap_days, zone)
            elif watermark is not None and spec is not None:
                watermark -= timedelta(days=spec.overlap_days)
            run.window_since, run.window_until = watermark, None
        resume = (
            checkpoint.cursor if checkpoint is not None and checkpoint.run_id == run.id else None
        )
        run.status, run.attempt, run.started_at = "running", run.attempt + 1, now
        run.lease_expires_at, run.not_before = now + RUN_LEASE, None
        refresh = secrets.get("refresh_token")
        return (
            _Claim(
                run_id=run.id,
                agency_id=run.agency_id,
                client_id=run.client_id,
                connection_id=run.connection_id,
                generation=run.connection_generation,
                provider=connection.provider,
                access_id=access.id,
                access_version=access.version,
                access_token=_open(keyring, access),
                access_expires_at=access.provider_expires_at,
                refresh_token=_open(keyring, refresh) if refresh is not None else None,
                attempt=run.attempt,
                kind=run.kind,
                since=run.window_since,
                until=run.window_until,
                stream=stream,
                cursor=resume,
                adapter_version=provider.capability.version if provider is not None else None,
                refresh_mode=(
                    provider.capability.refresh_mode if provider is not None else "refresh_token"
                ),
                access_refreshed_at=access.last_refreshed_at,
            ),
            False,
        )


# Terminal credential failure: only this connection, only if it is still the claimed
# generation, and only from the attempt that owns the run, becomes reconnect_required; data
# is kept without further writes (D-048 D7). Returns "stopped" or "superseded".
def _require_reconnect(engine: Engine, claim: _Claim, reason: str, now: datetime) -> str:
    with Session(engine) as session, session.begin():
        connection = session.scalar(
            select(ConnectorConnection)
            .where(ConnectorConnection.id == claim.connection_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        ownership = _ownership(session, claim)
        if ownership != "owned":
            return _not_owned(ownership)
        _finish(session, claim, "failed", now, "unauthorized")
        if (
            connection is None
            or connection.status != "active"
            or connection.generation != claim.generation
        ):
            return "stopped"
        connection.status, connection.status_reason = "reconnect_required", reason
        connection.reconnect_required_since = now
        connection.generation += 1
        connection.updated_at = now
        for row in _live_secrets(session, connection.id):
            row.status = "revoked"
        _cancel_open_runs(session, connection.id, now, "connection_inactive")
        return "stopped"


# Refresh the access token only while this attempt owns the run (checked when the call is
# reserved against the usage limits), and install the result only if the attempt still owns
# it, the connection is still active under the claimed generation, and its agency and client
# are active. The new token is revoked only when the connection's generation changed: then
# its grant is being torn down or was replaced. A superseded attempt or an inactive client
# leaves the token unsaved without revoking it, because it belongs to the grant the connection
# still holds and the winning attempt's tokens share that grant (R009-03); it expires at the
# provider. Each step reads the clock when it happens (R009-11). Returns the access token, or
# the run outcome.
def _refresh(
    engine: Engine,
    settings: Settings,
    keyring: LocalKeyring,
    provider: ConnectorProvider,
    claim: _Claim,
    clock: Callable[[], datetime],
) -> tuple[str | None, str]:
    secret = _refresh_secret(claim)
    assert secret is not None
    usage, outcome = _reserve(engine, settings, provider.capability, claim, "refresh", clock())
    if usage is None:
        return None, outcome
    try:
        grant = provider.refresh(secret)
    except ProviderError as error:
        _settle(engine, usage, error.kind.value, clock())
        if error.kind is ErrorKind.UNAUTHORIZED:
            return None, _require_reconnect(engine, claim, "credential_expired", clock())
        return None, _fail_or_defer(engine, claim, error, clock(), provider.capability)
    _settle(engine, usage, "ok", clock())
    now = clock()
    moved_on = False
    try:
        with Session(engine) as session, session.begin():
            connection, reason = _fence(session, claim)
            moved_on = connection is None or connection.generation != claim.generation
            if reason is not None or connection is None:
                _finish(session, claim, "canceled", now, reason or "fenced")
                return None, "superseded" if reason == "superseded" else "stopped"
            previous = session.get(ConnectorTokenSecret, claim.access_id)
            if previous is None or previous.status == "destroyed":
                _finish(session, claim, "canceled", now, "fenced")
                return None, "stopped"
            _destroy(previous, now, "not_required")
            session.flush()
            if grant.refresh_expires_at is not None:
                connection.grant_expires_at = grant.refresh_expires_at
            session.add(
                _new_secret(
                    keyring,
                    connection,
                    "access_token",
                    _next_version(session, connection.id, "access_token"),
                    grant.access_token,
                    grant.access_expires_at,
                    now,
                )
            )
            if grant.refresh_token is not None and grant.refresh_token != claim.refresh_token:
                for row in _live_secrets(session, connection.id):
                    if row.kind == "refresh_token":
                        _destroy(row, now, "not_required")
                session.flush()
                session.add(
                    _new_secret(
                        keyring,
                        connection,
                        "refresh_token",
                        _next_version(session, connection.id, "refresh_token"),
                        grant.refresh_token,
                        grant.refresh_expires_at,
                        now,
                    )
                )
    finally:
        # An account-wide grant is settled by the teardown or the reconnect (011-A, D5).
        if moved_on and provider.capability.revocation_scope != "account":
            dispose_grant(
                provider,
                TokenGrant(
                    grant.access_token,
                    grant.refresh_token if grant.refresh_token != claim.refresh_token else None,
                    grant.access_expires_at,
                    grant.scopes,
                    grant.external_account_id,
                ),
            )
    return grant.access_token, "refreshed"


# Store one page under the attempt fence (D-049 decision D13): the page's records, the run's
# page count and renewed lease, and the checkpoint's cursor commit together, so a stop before
# the commit repeats the page and a stop after it resumes at the next one. The last page also
# moves the stream's watermarks to the window the provider reported, records the successful
# sync, and finishes the run, in the same transaction. Returns "stored", "succeeded",
# "superseded", or "discarded".
# 011-A (D9, D11): only the stream's allow-listed attributes are stored, with their refresh
# time, together with the end of a lifetime total's provisional period, and a page's account
# label refreshes the connection's label. With complete False the last page is stored without
# moving the watermarks or finishing the run ("stored_last"), so an inventory sweep can run
# before _complete.
def _store_page(
    engine: Engine,
    claim: _Claim,
    page: ProviderPage,
    now: datetime,
    capability: Capability | None = None,
    complete: bool = True,
) -> str:
    spec = capability.stream_spec(claim.stream) if capability is not None else None
    allowed = frozenset(spec.attributes) if spec is not None else frozenset()
    with Session(engine) as session, session.begin():
        connection, reason = _fence(session, claim)
        if reason == "superseded":
            return "superseded"
        if reason is not None or connection is None:
            _finish(session, claim, "canceled", now, reason or "fenced")
            return "discarded"
        for record in page.records:
            attributes = {
                name: value for name, value in record.attributes.items() if name in allowed
            }
            values = {
                "id": uuid4(),
                "agency_id": claim.agency_id,
                "client_id": claim.client_id,
                "connection_id": claim.connection_id,
                "connection_generation": claim.generation,
                "provider_object_id": record.provider_object_id,
                "observed_at": record.observed_at,
                "metrics": dict(record.metrics),
                "fetched_at": now,
                "source_run_id": claim.run_id,
                "adapter_version": claim.adapter_version,
                "stream": claim.stream,
                "product_type": record.product_type,
                "unavailable": {
                    name: reason
                    for name, reason in record.unavailable.items()
                    if reason in UNAVAILABLE_REASONS and name not in record.metrics
                },
                "attributes": attributes,
                "attributes_refreshed_at": now if attributes else None,
                "provisional_until": record.provisional_until,
            }
            statement = insert(ConnectorRecord).values(**values)
            session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_connector_records_object",
                    set_={
                        "connection_generation": statement.excluded.connection_generation,
                        "observed_at": statement.excluded.observed_at,
                        "metrics": statement.excluded.metrics,
                        "fetched_at": statement.excluded.fetched_at,
                        "source_run_id": statement.excluded.source_run_id,
                        "adapter_version": statement.excluded.adapter_version,
                        "product_type": statement.excluded.product_type,
                        "unavailable": statement.excluded.unavailable,
                        "attributes": statement.excluded.attributes,
                        "attributes_refreshed_at": statement.excluded.attributes_refreshed_at,
                        "provisional_until": statement.excluded.provisional_until,
                    },
                )
            )
        if (
            page.account_label is not None
            and capability is not None
            and capability.label_refresh_days is not None
        ):
            connection.account_label = page.account_label[:200]
            connection.account_label_refreshed_at = now
        session.execute(
            update(ConnectorSyncRun)
            .where(ConnectorSyncRun.id == claim.run_id)
            .values(pages=ConnectorSyncRun.pages + 1, lease_expires_at=now + RUN_LEASE)
        )
        checkpoint = session.scalar(
            select(ConnectorCheckpoint)
            .where(
                ConnectorCheckpoint.connection_id == claim.connection_id,
                ConnectorCheckpoint.stream == claim.stream,
            )
            .with_for_update()
        )
        if checkpoint is None:
            checkpoint = ConnectorCheckpoint(
                id=uuid4(),
                agency_id=claim.agency_id,
                client_id=claim.client_id,
                connection_id=claim.connection_id,
                stream=claim.stream,
            )
            session.add(checkpoint)
        checkpoint.run_id, checkpoint.cursor = claim.run_id, page.next_cursor
        checkpoint.updated_at = now
        if page.next_cursor is not None:
            return "stored"
        if not complete:
            return "stored_last"
        _complete_run(session, claim, connection, checkpoint, page, now)
    return "succeeded"


# Move the stream's watermarks to the window the provider reported, record the successful
# sync, and finish the run, in the caller's transaction.
def _complete_run(
    session: Session,
    claim: _Claim,
    connection: ConnectorConnection,
    checkpoint: ConnectorCheckpoint,
    page: ProviderPage,
    now: datetime,
) -> None:
    if page.covered_from is not None:
        known = checkpoint.covered_from
        checkpoint.covered_from = (
            page.covered_from if known is None else min(known, page.covered_from)
        )
    if page.complete_through is not None and claim.kind == "incremental":
        known = checkpoint.complete_through
        checkpoint.complete_through = (
            page.complete_through if known is None else max(known, page.complete_through)
        )
    connection.last_successful_sync_at = connection.updated_at = now
    _finish(session, claim, "succeeded", now)


# Complete a run whose last page was stored with complete False, under the attempt fence.
def _complete(engine: Engine, claim: _Claim, page: ProviderPage, now: datetime) -> str:
    with Session(engine) as session, session.begin():
        connection, reason = _fence(session, claim)
        if reason == "superseded":
            return "superseded"
        if reason is not None or connection is None:
            _finish(session, claim, "canceled", now, reason or "fenced")
            return "discarded"
        checkpoint = session.scalar(
            select(ConnectorCheckpoint)
            .where(
                ConnectorCheckpoint.connection_id == claim.connection_id,
                ConnectorCheckpoint.stream == claim.stream,
            )
            .with_for_update()
        )
        assert checkpoint is not None
        _complete_run(session, claim, connection, checkpoint, page, now)
    return "succeeded"


# Inventory sweep (011-A, D11): after a complete read of an inventory stream, the stream's
# objects that the read did not return are asked about in calls of at most 50 IDs, each
# reserved at the stream's confirmation cost, and the objects the provider confirms gone are
# purged from every stream of the connection under the attempt fence. An object that still
# exists is kept. A failed confirmation leaves the remaining objects for the next run. Returns
# "swept" or the run outcome.
CONFIRM_BATCH = 50


def _sweep(
    engine: Engine,
    settings: Settings,
    provider: ConnectorProvider,
    claim: _Claim,
    access: str,
    clock: Callable[[], datetime],
) -> str:
    with Session(engine) as session:
        missing = list(
            session.scalars(
                select(ConnectorRecord.provider_object_id)
                .where(
                    ConnectorRecord.connection_id == claim.connection_id,
                    ConnectorRecord.stream == claim.stream,
                    or_(
                        ConnectorRecord.source_run_id.is_(None),
                        ConnectorRecord.source_run_id != claim.run_id,
                    ),
                )
                .order_by(ConnectorRecord.provider_object_id)
            )
        )
    for start in range(0, len(missing), CONFIRM_BATCH):
        chunk = tuple(missing[start : start + CONFIRM_BATCH])
        usage, outcome = _reserve(engine, settings, provider.capability, claim, "confirm", clock())
        if usage is None:
            return outcome
        try:
            gone = set(
                provider.confirm_deleted(access, stream=claim.stream, object_ids=chunk)
            ) & set(chunk)
        except ProviderError as error:
            _settle(engine, usage, error.kind.value, clock())
            return "swept"
        _settle(engine, usage, "ok", clock())
        if not gone:
            continue
        now = clock()
        with Session(engine) as session, session.begin():
            connection, reason = _fence(session, claim)
            if reason == "superseded":
                return "superseded"
            if reason is not None or connection is None:
                _finish(session, claim, "canceled", now, reason or "fenced")
                return "discarded"
            session.execute(
                delete(ConnectorRecord).where(
                    ConnectorRecord.connection_id == claim.connection_id,
                    ConnectorRecord.provider_object_id.in_(sorted(gone)),
                )
            )
    return "swept"


# The secret a refresh presents: the refresh token, or, for a self-refreshing provider, the
# current access token (D-053 decision D4).
def _refresh_secret(claim: _Claim) -> str | None:
    return claim.access_token if claim.refresh_mode == "self" else claim.refresh_token


# Whether a self-refreshing access token is due for renewal: at least refresh_min_age_hours old
# and within refresh_before_days of its expiry. A token not refreshed in time expires and the
# connection then requires reconnection (D-053 decision D4).
def _renewal_due(capability: Capability, claim: _Claim, now: datetime) -> bool:
    if claim.refresh_mode != "self" or claim.access_expires_at is None:
        return False
    old_enough = claim.access_refreshed_at is None or now - claim.access_refreshed_at >= timedelta(
        hours=capability.refresh_min_age_hours
    )
    return old_enough and claim.access_expires_at - now <= timedelta(
        days=capability.refresh_before_days
    )


# Read the claimed run's window page by page from its resume cursor. Every data call, refresh
# included, is first reserved against the usage limits and settled with its outcome. The
# clock is read at each step rather than once per claim (R009-11): a deferral counts from the
# provider's answer, so a late 429 still waits its full Retry-After; each stored page renews
# the lease from the time of its write; and fetch, usage, and usage-period times are those of
# the call.
def _execute(
    engine: Engine,
    settings: Settings,
    keyring: LocalKeyring,
    registry: Mapping[str, ConnectorProvider],
    claim: _Claim,
    clock: Callable[[], datetime],
) -> str:
    provider = registry.get(claim.provider)
    if provider is None:
        with Session(engine) as session, session.begin():
            _finish(session, claim, "failed", clock(), "permanent")
        return "failed"
    access: str | None = claim.access_token
    refreshed = False
    now = clock()
    capability = provider.capability
    # 011-A (D4, D6): refresh an access token that expires within the provider's margin, and
    # force a refresh when the last one is older than the authorization check period.
    ahead = timedelta(seconds=capability.refresh_ahead_seconds)
    expired = claim.access_expires_at is not None and claim.access_expires_at <= now + ahead
    check = (
        capability.authorization_check_days is not None
        and claim.access_refreshed_at is not None
        and now - claim.access_refreshed_at >= timedelta(days=capability.authorization_check_days)
    )
    due = expired or check or _renewal_due(capability, claim, now)
    if due and _refresh_secret(claim) is not None:
        (access, outcome), refreshed = (
            _refresh(engine, settings, keyring, provider, claim, clock),
            True,
        )
        if access is None:
            return outcome
    cursor = claim.cursor
    while True:
        usage, outcome = _reserve(engine, settings, provider.capability, claim, "fetch", clock())
        if usage is None:
            return outcome
        try:
            page = provider.fetch_page(
                access or "",
                stream=claim.stream,
                cursor=cursor,
                since=claim.since,
                until=claim.until,
            )
        except ProviderError as error:
            _settle(engine, usage, error.kind.value, clock())
            if error.kind is ErrorKind.UNAUTHORIZED and _refresh_secret(claim) and not refreshed:
                (access, outcome), refreshed = (
                    _refresh(engine, settings, keyring, provider, claim, clock),
                    True,
                )
                if access is None:
                    return outcome
                continue
            if error.kind is ErrorKind.UNAUTHORIZED:
                return _require_reconnect(engine, claim, "provider_revoked", clock())
            return _fail_or_defer(engine, claim, error, clock(), capability)
        _settle(engine, usage, "ok", clock())
        spec = capability.stream_spec(claim.stream)
        sweep = spec is not None and spec.inventory and page.next_cursor is None
        outcome = _store_page(engine, claim, page, clock(), capability, complete=not sweep)
        if outcome == "stored_last":
            outcome = _sweep(engine, settings, provider, claim, access or "", clock)
            if outcome != "swept":
                return outcome
            return _complete(engine, claim, page, clock())
        if outcome != "stored":
            return outcome
        cursor = page.next_cursor


# Process at most `limit` sync runs, each claimed, fetched, and persisted separately. A fixed
# `now` (tests) is used for every step; otherwise each step reads the current time.
def run_syncs(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> dict[str, int]:
    keyring = require_keys(settings)

    def clock() -> datetime:
        return now if now is not None else now_utc()

    counts: dict[str, int] = {}
    for _ in range(limit):
        claim, canceled = _claim(engine, keyring, registry, clock())
        if claim is None:
            if not canceled:
                break
            counts["canceled"] = counts.get("canceled", 0) + 1
            continue
        outcome = _execute(engine, settings, keyring, registry, claim, clock)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


# Queue one incremental run for each stream of each active connection, of an active agency
# and client, whose stream has no open run and whose most recent run of that stream was
# created more than the stream's interval ago, or the configured sync interval when the stream
# declares none (D-049 decision D11, D-053 decision D6). Only providers in the registry are
# scheduled. Connections locked by another transaction are skipped; the open-run index keeps a
# concurrent request from creating a second open run of a stream.
def schedule_syncs(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    *,
    limit: int = 100,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or now_utc()
    plan_rows = [
        (
            name,
            spec.name,
            now - timedelta(hours=spec.interval_hours or settings.connector_sync_interval_hours),
        )
        for name, provider in sorted(registry.items())
        for spec in provider.capability.stream_specs()
    ]
    if not plan_rows:
        return {}
    plan = values_clause(
        column("provider", String),
        column("stream", String),
        column("cutoff", DateTime(timezone=True)),
        name="plan",
    ).data(plan_rows)
    recent = (
        select(ConnectorSyncRun.id)
        .where(
            ConnectorSyncRun.connection_id == ConnectorConnection.id,
            ConnectorSyncRun.stream == plan.c.stream,
            ConnectorSyncRun.status.in_(OPEN_RUNS) | (ConnectorSyncRun.created_at > plan.c.cutoff),
        )
        .exists()
    )
    with Session(engine) as session, session.begin():
        due = list(
            session.execute(
                select(ConnectorConnection, plan.c.stream)
                .join(plan, plan.c.provider == ConnectorConnection.provider)
                .join(Agency, Agency.id == ConnectorConnection.agency_id)
                .join(
                    ClientWorkspace,
                    (ClientWorkspace.agency_id == ConnectorConnection.agency_id)
                    & (ClientWorkspace.id == ConnectorConnection.client_id),
                )
                .where(
                    ConnectorConnection.status == "active",
                    Agency.status == "active",
                    ClientWorkspace.status == "active",
                    ~recent,
                )
                .order_by(ConnectorConnection.id, plan.c.stream)
                .limit(limit)
                .with_for_update(of=ConnectorConnection, skip_locked=True)
            ).all()
        )
        queued = 0
        for connection, stream in due:
            created = session.execute(
                insert(ConnectorSyncRun)
                .values(
                    id=uuid4(),
                    agency_id=connection.agency_id,
                    client_id=connection.client_id,
                    connection_id=connection.id,
                    connection_generation=connection.generation,
                    status="queued",
                    kind="incremental",
                    stream=stream,
                    created_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["connection_id", "stream"],
                    index_where=text("status IN ('queued', 'running')"),
                )
                .returning(ConnectorSyncRun.id)
            ).first()
            queued += created is not None
    return {"queued": queued} if queued else {}


# Disconnect, with reason authorization_lost, connections that have required reconnection for
# longer than their provider's grace period (011-A, D6); the teardown then revokes, destroys and
# purges as for any disconnect. Connections locked by another transaction are left for the
# next pass.
def expire_reconnects(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    *,
    limit: int = 100,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or now_utc()
    graces = {
        name: provider.capability.reconnect_grace_days
        for name, provider in sorted(registry.items())
        if provider.capability.reconnect_grace_days is not None
    }
    expired = 0
    with Session(engine) as session, session.begin():
        for name, days in graces.items():
            assert days is not None
            rows = session.scalars(
                select(ConnectorConnection)
                .where(
                    ConnectorConnection.provider == name,
                    ConnectorConnection.status == "reconnect_required",
                    ConnectorConnection.reconnect_required_since <= now - timedelta(days=days),
                )
                .order_by(ConnectorConnection.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            for connection in rows:
                start_disconnect(session, settings, connection, "authorization_lost", now)
                expired += 1
    return {"expired": expired} if expired else {}


@dataclass(frozen=True)
class _Outstanding:
    secret_id: UUID
    kind: str
    token: str = field(repr=False)


# Claim disconnecting connections whose teardown lease is free and open their outstanding
# tokens (not destroyed and not yet settled), refresh tokens first. 011-A (D5): each claim also
# reports whether another active connection shares the account, for account-wide grants.
def _claim_teardowns(
    engine: Engine, keyring: LocalKeyring, now: datetime, limit: int
) -> list[tuple[UUID, str, list[_Outstanding], bool]]:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        rows = list(
            session.scalars(
                select(ConnectorConnection)
                .where(
                    ConnectorConnection.status == "disconnecting",
                    (ConnectorConnection.teardown_lease_until.is_(None))
                    | (ConnectorConnection.teardown_lease_until < now),
                )
                .order_by(
                    case((ConnectorConnection.purge_due_at <= now, 0), else_=1),
                    ConnectorConnection.teardown_attempts,
                    ConnectorConnection.purge_due_at,
                    ConnectorConnection.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        claimed = []
        for connection in rows:
            connection.teardown_lease_until = now + TEARDOWN_LEASE
            connection.teardown_attempts += 1
            outstanding = [
                _Outstanding(row.id, row.kind, _open(keyring, row))
                for row in _live_secrets(session, connection.id)
                if row.revocation not in SettledRevocation
            ]
            shared = _account_shared(
                session, connection.provider, connection.external_account_id, connection.id
            )
            claimed.append((connection.id, connection.provider, outstanding, shared))
        return claimed


def _record_revocation(engine: Engine, secret_id: UUID, outcome: str) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(ConnectorTokenSecret)
            .where(ConnectorTokenSecret.id == secret_id, ConnectorTokenSecret.status != "destroyed")
            .values(revocation=outcome)
        )


# Finish a teardown when every outstanding token is settled, or at the deadline: destroy all
# sealed material, purge provider records, clear the account reference, and report the
# revocation outcome. The outcome covers every version with a provider obligation, including
# versions a reconnect replaced earlier (R009-01); superseded access versions of a kept grant
# ("not_required") do not count. The clock is read once the connection is locked, to decide
# whether the deadline forces completion (R009-04), and again after the purge has run, in the
# transaction that records the outcome: that second reading is the completion time, so a
# purge that ends after the deadline is reported as late (R009-10). purge_due_at never
# changes. Before the deadline an unsettled teardown releases its lease for retry.
def _finalize(engine: Engine, connection_id: UUID, clock: Callable[[], datetime]) -> str:
    with Session(engine) as session, session.begin():
        connection = session.scalar(
            select(ConnectorConnection)
            .where(ConnectorConnection.id == connection_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if connection is None or connection.status != "disconnecting":
            return "skipped"
        now = clock()
        secrets = _live_secrets(session, connection.id)
        unsettled = [row for row in secrets if row.revocation not in SettledRevocation]
        assert connection.purge_due_at is not None
        if unsettled and now < connection.purge_due_at:
            connection.teardown_lease_until = None
            return "pending"
        for row in unsettled:
            row.revocation = "failed"
        session.flush()
        outcomes = set(
            session.scalars(
                select(ConnectorTokenSecret.revocation).where(
                    ConnectorTokenSecret.connection_id == connection.id,
                    ConnectorTokenSecret.revocation.in_(
                        ("done", "unsupported", "failed", "shared")
                    ),
                )
            )
        )
        for row in secrets:
            _destroy(row, now)
        session.execute(
            delete(ConnectorCheckpoint).where(ConnectorCheckpoint.connection_id == connection.id)
        )
        session.execute(
            delete(ConnectorRecord).where(ConnectorRecord.connection_id == connection.id)
        )
        _cancel_open_runs(session, connection.id, now, "connection_inactive")
        session.flush()
        completed = clock()
        connection.revocation_status = (
            "failed"
            if "failed" in outcomes
            else "unsupported"
            if "unsupported" in outcomes
            else "shared"
            if "shared" in outcomes and "done" not in outcomes
            else "done"
        )
        connection.destruction_status = connection.purge_status = "done"
        connection.external_account_id = connection.account_label = None
        connection.account_kind = None
        connection.account_label_refreshed_at = connection.grant_expires_at = None
        connection.status, connection.disconnected_at = "disconnected", completed
        connection.teardown_lease_until, connection.updated_at = None, completed
        if connection.deletion_request_id is not None:
            _complete_deletion(session, connection, completed)
        return "disconnected"


# Record a data deletion request as completed once the last connection it started to
# disconnect has finished. The request row lock orders concurrent finalizations.
def _complete_deletion(
    session: Session, connection: ConnectorConnection, completed: datetime
) -> None:
    request = session.scalar(
        select(ConnectorDeletionRequest)
        .where(ConnectorDeletionRequest.id == connection.deletion_request_id)
        .with_for_update()
    )
    if request is None or request.completed_at is not None:
        return
    session.flush()
    remaining = session.scalar(
        select(func.count())
        .select_from(ConnectorConnection)
        .where(
            ConnectorConnection.deletion_request_id == request.id,
            ConnectorConnection.status != "disconnected",
        )
    )
    if remaining == 0:
        request.completed_at = completed


def run_teardowns(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> dict[str, int]:
    keyring = require_keys(settings)

    def clock() -> datetime:
        return now if now is not None else now_utc()

    counts: dict[str, int] = {}
    for connection_id, provider_name, outstanding, shared in _claim_teardowns(
        engine, keyring, clock(), limit
    ):
        provider = registry.get(provider_name)
        for item in outstanding:
            if provider is None:
                continue
            # Another active connection holds the same account-wide grant: keep it (D5).
            if shared and provider.capability.revocation_scope == "account":
                _record_revocation(engine, item.secret_id, "shared")
                continue
            try:
                outcome = provider.revoke(item.token, item.kind)
            except ProviderError:
                continue
            _record_revocation(engine, item.secret_id, outcome)
        result = _finalize(engine, connection_id, clock)
        counts[result] = counts.get(result, 0) + 1
    return counts


# One bounded worker pass: teardowns first, then the scheduling step (unless disabled), then
# sync runs.
def process_connectors(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    *,
    limit: int = 10,
    now: datetime | None = None,
    schedule: bool = True,
) -> dict[str, dict[str, int]]:
    result = {"teardown": run_teardowns(engine, settings, registry, limit=limit, now=now)}
    if schedule:
        result["schedule"] = {
            **expire_reconnects(engine, settings, registry, now=now),
            **schedule_syncs(engine, settings, registry, now=now),
        }
    result["sync"] = run_syncs(engine, settings, registry, limit=limit, now=now)
    return result


__all__ = [
    "CALLBACK_ERRORS",
    "CallbackResult",
    "ConnectionView",
    "ConnectorAdmin",
    "ConnectorError",
    "build_providers",
    "complete_authorization",
    "connection_view",
    "dispose_grant",
    "expire_reconnects",
    "get_connection",
    "list_connections",
    "process_connectors",
    "run_syncs",
    "run_teardowns",
    "schedule_syncs",
    "start_disconnect",
    "stream_names",
]
