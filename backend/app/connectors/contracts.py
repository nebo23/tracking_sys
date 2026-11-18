"""Connector adapter contracts (specification 009, D-048 and D-049).

The runtime talks to a provider only through ConnectorProvider. An adapter declares its
Capability and maps every provider failure to a ProviderError kind, so runtime decisions never
depend on provider-specific codes. TokenGrant and ProviderError never show token values or
provider messages in their representation. 009-B adds paged reads within a time window with an
opaque cursor, call costs, and a provider daily quota. Real provider adapters do not exist yet:
each needs a current rule in app.privacy.providers and dated evidence (specifications 010-013).

010-A (D-053) adds what Instagram-shaped providers need: several streams per connection, an
optional PKCE method, a long-lived access token that refreshes itself, metric support by media
product type with a reason for every absent value, a provider data delay, and Meta-style signed
requests for deauthorization and data deletion.

011-A (D-058, D-060) adds what Google-shaped providers need: account-wide revocation, a
required set of scopes, refresh ahead of expiry with a periodic authorization check and a grace
period after lost access, named quota buckets counted on the provider's local day, local-day
stream windows, allow-listed record attributes with refresh times, inventory streams whose
missing objects are confirmed gone and purged, a non-additive metric marker, and the agent
approval a connect must carry.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Protocol


class ErrorKind(StrEnum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    BUDGET_EXHAUSTED = "budget_exhausted"


# A provider failure in runtime terms. provider_code is a short closed code chosen by the
# adapter, never a provider message or response body.
class ProviderError(Exception):
    # bucket names the quota bucket of a BUDGET_EXHAUSTED answer (011-A, D10).
    def __init__(
        self,
        kind: ErrorKind,
        provider_code: str = "",
        retry_after: int | None = None,
        bucket: str | None = None,
    ) -> None:
        self.kind, self.provider_code, self.retry_after = kind, provider_code, retry_after
        self.bucket = bucket
        super().__init__(kind.value)

    def __repr__(self) -> str:
        return f"ProviderError({self.kind.value!r})"


# One metric an adapter can report, with its unit and the account kinds that offer it (None
# means every kind). A metric outside an account's kinds is reported as unsupported, never as
# zero (009-C, D-049 decision D17). 010-A adds the streams that carry the metric and the media
# product types that offer it (None means all), so a story metric is unsupported for a reel.
# 011-A (D8): additive False marks a metric whose values must not be summed (averages), and
# definition_changes lists the dates on which the provider changed the metric's definition.
@dataclass(frozen=True)
class MetricSpec:
    name: str
    unit: str
    account_kinds: tuple[str, ...] | None = None
    streams: tuple[str, ...] | None = None
    product_types: tuple[str, ...] | None = None
    additive: bool = True
    definition_changes: tuple[date, ...] = ()


# One synchronized stream of a connection (010-A, D-053 decision D6): its name, how often the
# worker queues an incremental run (None uses the configured sync interval), how far back the
# provider serves history, and how many days an incremental run re-reads before its watermark.
# 011-A adds the units a page costs in each quota bucket (D10), a stream-specific data delay
# for the provisional marking (D9), the record attributes the runtime may store (D11), and
# whether a complete read lists every live object, so that objects it misses are confirmed
# gone at confirm_cost per call and purged from every stream (D11).
@dataclass(frozen=True)
class StreamSpec:
    name: str
    interval_hours: float | None = None
    history_days: int = 30
    overlap_days: int = 1
    cost: Mapping[str, int] | None = None
    data_delay_hours: int | None = None
    attributes: tuple[str, ...] = ()
    inventory: bool = False
    confirm_cost: Mapping[str, int] | None = None


# A named daily quota bucket (011-A, D10): its unit, the provider-wide cap the runtime keeps
# under, the allocation of one connection, and the time zone whose midnight resets it.
@dataclass(frozen=True)
class QuotaBucket:
    name: str
    unit: str
    daily_quota: int
    connection_daily: int
    zone: str = "UTC"


# What an adapter supports. revocation_scope states what a revocation call invalidates: one
# token, the whole provider grant behind it, or nothing ("unsupported"). Specifications 010-013
# record each live provider's scope from dated evidence before use. 009-B adds the synchronized
# stream, how far back the provider serves history, how many days an incremental run re-reads
# before its watermark, the cost of each data call in the provider's unit, and the provider's
# daily quota in that unit (D-049 decisions D13 and D15). 009-C adds the metric catalog and
# the freshness window after which stored values are reported as stale (decision D17).
# 010-A (D-053): pkce None means the provider offers no PKCE, and the authorization relies on
# the single-use state, the session binding and the server-side exchange (D3). refresh_mode
# "self" means the provider refreshes the long-lived access token itself, with no refresh
# token; the worker refreshes it once it is refresh_min_age_hours old and within
# refresh_before_days of expiry (D4). streams declares several streams (D6); without it the
# single stream, history and overlap fields above apply. daily_quota None means the provider
# has no fixed daily quota and its rate-limit answers govern (D8). data_delay_hours marks
# recently observed values as provisional (D8). signed_requests declares the Meta-style
# deauthorize and data deletion callbacks (D5).
# 011-A (D-058, D-060): revocation_scope "account" means one revocation invalidates every token
# the account granted (Google, G-1; D5). require_all_scopes refuses a grant without every
# requested scope (D2). refresh_ahead_seconds refreshes an access token about to expire, and
# authorization_check_days forces a refresh when the last one is older (D4, D6);
# reconnect_grace_days disconnects a connection left in reconnect_required that long (D6).
# buckets replace the single unit and daily_quota (D10); day_zone is the zone of the
# provider's days (D9). agent_disclosure is the disclosure version a connect must approve
# (D13), and label_refresh_days the period after which an unrefreshed label is cleared (D11).
@dataclass(frozen=True)
class Capability:
    provider: str
    version: str
    pkce: Literal["S256"] | None
    refresh: bool
    revocation_scope: Literal["token", "grant", "account", "unsupported"]
    scopes: tuple[str, ...]
    metrics: tuple[MetricSpec, ...] = ()
    stream: str = "objects"
    history_days: int = 30
    overlap_days: int = 1
    cost_unit: str = "unit"
    call_costs: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({"fetch": 1, "refresh": 1})
    )
    daily_quota: int | None = 1000
    freshness_hours: int = 24
    webhooks: bool = False
    refresh_mode: Literal["refresh_token", "self"] = "refresh_token"
    refresh_min_age_hours: int = 24
    refresh_before_days: int = 7
    streams: tuple[StreamSpec, ...] = ()
    data_delay_hours: int = 0
    signed_requests: bool = False
    require_all_scopes: bool = False
    refresh_ahead_seconds: int = 0
    authorization_check_days: int | None = None
    reconnect_grace_days: int | None = None
    buckets: tuple[QuotaBucket, ...] = ()
    day_zone: str | None = None
    agent_disclosure: str | None = None
    label_refresh_days: int | None = None

    def cost(self, operation: str) -> int:
        return self.call_costs.get(operation, 1)

    def bucket(self, name: str) -> QuotaBucket | None:
        return next((item for item in self.buckets if item.name == name), None)

    # The bucket costs of one call: a page of the stream, or ("confirm") one confirmation of
    # missing inventory objects. A refresh is not metered in a bucketed provider.
    def bucket_costs(self, operation: str, stream: str) -> dict[str, int]:
        spec = self.stream_spec(stream)
        if operation == "refresh" or spec is None:
            return {}
        costs = spec.confirm_cost if operation == "confirm" else spec.cost
        return dict(costs or {})

    # The provisional delay of a stream's records.
    def stream_delay_hours(self, stream: str) -> int:
        spec = self.stream_spec(stream)
        if spec is not None and spec.data_delay_hours is not None:
            return spec.data_delay_hours
        return self.data_delay_hours

    # The declared streams, or the single stream of a 009 adapter.
    def stream_specs(self) -> tuple[StreamSpec, ...]:
        return self.streams or (
            StreamSpec(self.stream, None, self.history_days, self.overlap_days),
        )

    def stream_spec(self, name: str) -> StreamSpec | None:
        return next((spec for spec in self.stream_specs() if spec.name == name), None)

    @property
    def primary_stream(self) -> str:
        return self.stream_specs()[0].name

    # The metrics a stream carries.
    def stream_metrics(self, stream: str) -> tuple[MetricSpec, ...]:
        return tuple(m for m in self.metrics if m.streams is None or stream in m.streams)


# Tokens and account identity from a code exchange or refresh, including the provider's
# account kind when it reports one. Repr omits the tokens.
# 011-A: refresh_expires_at is the provider-reported end of the refresh token (Google's
# refresh_token_expires_in), kept as the grant's expiry; refusal is a closed reason why the
# account cannot be connected although tokens were issued (no channel or several channels, F4).
@dataclass(frozen=True, repr=False)
class TokenGrant:
    access_token: str
    refresh_token: str | None
    access_expires_at: datetime | None
    scopes: tuple[str, ...]
    external_account_id: str
    account_label: str | None = None
    account_kind: str | None = None
    refresh_expires_at: datetime | None = None
    refusal: str | None = None

    def __repr__(self) -> str:
        return f"TokenGrant(account={self.external_account_id!r}, scopes={self.scopes!r})"


# One provider object with its observed metrics. 010-A adds the media product type and, for a
# metric the provider did not report, a closed reason: "not_returned" (empty data) or
# "below_threshold" (the provider withholds it under its minimum audience). An absent metric is
# never stored as zero (D-053 decision D7).
UNAVAILABLE_REASONS = frozenset({"not_returned", "below_threshold"})


# 011-A (D9, D11): attributes are candidate record attributes, of which the runtime stores only
# those its stream allows; provisional_until ends the provisional period of a value that does
# not follow the stream's delay (lifetime totals of a recent video).
@dataclass(frozen=True)
class ProviderRecord:
    provider_object_id: str
    observed_at: datetime
    metrics: Mapping[str, int | float] = field(default_factory=dict)
    product_type: str | None = None
    unavailable: Mapping[str, str] = field(default_factory=dict)
    attributes: Mapping[str, str | int | bool | None] = field(default_factory=dict)
    provisional_until: datetime | None = None


# One page of a windowed read. next_cursor is the provider's opaque position of the following
# page, or None on the last page. covered_from and complete_through are the provider-reported
# bounds of the window the read covers, after the provider applied its history limit; the
# runtime moves its coverage watermarks to them only when the last page is stored.
# 011-A (D11): account_label is the account's label as read with the page, which refreshes the
# connection's label.
@dataclass(frozen=True)
class ProviderPage:
    records: tuple[ProviderRecord, ...]
    next_cursor: str | None
    covered_from: datetime | None
    complete_through: datetime | None
    account_label: str | None = None


# A provider webhook delivery after its adapter verified the signature over the raw body: the
# provider's event ID and the external account it concerns. The payload itself is not kept
# (009-D, D-049 decisions D18 and D19).
@dataclass(frozen=True)
class WebhookDelivery:
    event_id: str
    external_account_id: str


# A refused delivery with a closed reason: signature_invalid, signature_expired, or
# invalid_delivery (a verified body the adapter cannot read).
class WebhookRejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# A Meta-style signed request after its adapter verified the signature (010-A, D-053 decision
# D5): the provider account it names and when the provider issued it. Nothing else is kept.
@dataclass(frozen=True)
class SignedRequest:
    external_account_id: str
    issued_at: datetime


RevocationOutcome = Literal["done", "unsupported"]


class ConnectorProvider(Protocol):
    capability: Capability

    # code_challenge is None when the capability offers no PKCE.
    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None,
        redirect_uri: str,
        scopes: tuple[str, ...],
    ) -> str: ...

    def exchange(
        self, *, code: str, code_verifier: str | None, redirect_uri: str
    ) -> TokenGrant: ...

    # Refresh with the refresh token, or, for refresh_mode "self", with the current access
    # token, which the provider replaces.
    def refresh(self, refresh_token: str) -> TokenGrant: ...

    # Read one page of the stream for the window [since, until). since None asks for the
    # provider's recent default window and until None for everything up to now. A cursor from
    # a previous page continues the same window.
    def fetch_page(
        self,
        access_token: str,
        *,
        stream: str,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ProviderPage: ...

    # Verify a Meta-style signed_request (deauthorize or data deletion callback) before reading
    # it; raises WebhookRejected. Only adapters whose Capability declares signed_requests are
    # called.
    def verify_signed_request(self, signed_request: str, now: datetime) -> SignedRequest: ...

    # Verify a webhook delivery's signature over the exact raw body before reading it; raises
    # WebhookRejected. Only adapters whose Capability declares webhooks are called.
    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, now: datetime
    ) -> WebhookDelivery: ...

    # Revoke one token. Returns "done" when the provider confirms the token is unusable
    # (including an already revoked token), or "unsupported"; raises ProviderError otherwise.
    def revoke(self, token: str, kind: str) -> RevocationOutcome: ...

    # Of object IDs that a complete read of an inventory stream did not return (at most 50),
    # those the provider confirms no longer exist (011-A, D11). Only adapters with an inventory
    # stream are called.
    def confirm_deleted(
        self, access_token: str, *, stream: str, object_ids: tuple[str, ...]
    ) -> tuple[str, ...]: ...
