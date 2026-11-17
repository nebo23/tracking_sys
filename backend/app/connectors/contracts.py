"""Connector adapter contracts (specification 009, D-048 and D-049).

The runtime talks to a provider only through ConnectorProvider. An adapter declares its
Capability and maps every provider failure to a ProviderError kind, so runtime decisions never
depend on provider-specific codes. TokenGrant and ProviderError never show token values or
provider messages in their representation. 009-B adds paged reads within a time window with an
opaque cursor, call costs, and a provider daily quota. Real provider adapters do not exist yet:
each needs a current rule in app.privacy.providers and dated evidence (specifications 010-013).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
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
    def __init__(
        self, kind: ErrorKind, provider_code: str = "", retry_after: int | None = None
    ) -> None:
        self.kind, self.provider_code, self.retry_after = kind, provider_code, retry_after
        super().__init__(kind.value)

    def __repr__(self) -> str:
        return f"ProviderError({self.kind.value!r})"


# One metric an adapter can report, with its unit and the account kinds that offer it (None
# means every kind). A metric outside an account's kinds is reported as unsupported, never as
# zero (009-C, D-049 decision D17).
@dataclass(frozen=True)
class MetricSpec:
    name: str
    unit: str
    account_kinds: tuple[str, ...] | None = None


# What an adapter supports. revocation_scope states what a revocation call invalidates: one
# token, the whole provider grant behind it, or nothing ("unsupported"). Specifications 010-013
# record each live provider's scope from dated evidence before use. 009-B adds the synchronized
# stream, how far back the provider serves history, how many days an incremental run re-reads
# before its watermark, the cost of each data call in the provider's unit, and the provider's
# daily quota in that unit (D-049 decisions D13 and D15). 009-C adds the metric catalog and
# the freshness window after which stored values are reported as stale (decision D17).
@dataclass(frozen=True)
class Capability:
    provider: str
    version: str
    pkce: Literal["S256"]
    refresh: bool
    revocation_scope: Literal["token", "grant", "unsupported"]
    scopes: tuple[str, ...]
    metrics: tuple[MetricSpec, ...] = ()
    stream: str = "objects"
    history_days: int = 30
    overlap_days: int = 1
    cost_unit: str = "unit"
    call_costs: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({"fetch": 1, "refresh": 1})
    )
    daily_quota: int = 1000
    freshness_hours: int = 24

    def cost(self, operation: str) -> int:
        return self.call_costs.get(operation, 1)


# Tokens and account identity from a code exchange or refresh, including the provider's
# account kind when it reports one. Repr omits the tokens.
@dataclass(frozen=True, repr=False)
class TokenGrant:
    access_token: str
    refresh_token: str | None
    access_expires_at: datetime | None
    scopes: tuple[str, ...]
    external_account_id: str
    account_label: str | None = None
    account_kind: str | None = None

    def __repr__(self) -> str:
        return f"TokenGrant(account={self.external_account_id!r}, scopes={self.scopes!r})"


# One provider object with its observed metrics.
@dataclass(frozen=True)
class ProviderRecord:
    provider_object_id: str
    observed_at: datetime
    metrics: Mapping[str, int | float] = field(default_factory=dict)


# One page of a windowed read. next_cursor is the provider's opaque position of the following
# page, or None on the last page. covered_from and complete_through are the provider-reported
# bounds of the window the read covers, after the provider applied its history limit; the
# runtime moves its coverage watermarks to them only when the last page is stored.
@dataclass(frozen=True)
class ProviderPage:
    records: tuple[ProviderRecord, ...]
    next_cursor: str | None
    covered_from: datetime | None
    complete_through: datetime | None


RevocationOutcome = Literal["done", "unsupported"]


class ConnectorProvider(Protocol):
    capability: Capability

    def authorization_url(
        self, *, state: str, code_challenge: str, redirect_uri: str, scopes: tuple[str, ...]
    ) -> str: ...

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> TokenGrant: ...

    def refresh(self, refresh_token: str) -> TokenGrant: ...

    # Read one page of the stream for the window [since, until). since None asks for the
    # provider's recent default window and until None for everything up to now. A cursor from
    # a previous page continues the same window.
    def fetch_page(
        self,
        access_token: str,
        *,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ProviderPage: ...

    # Revoke one token. Returns "done" when the provider confirms the token is unusable
    # (including an already revoked token), or "unsupported"; raises ProviderError otherwise.
    def revoke(self, token: str, kind: str) -> RevocationOutcome: ...
