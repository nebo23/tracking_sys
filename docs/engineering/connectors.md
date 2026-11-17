# Connector runtime (specification 009)
Status: 009-A (connection lifecycle) is implemented locally under D-048, and 009-B (synchronization), 009-C (coverage and provenance) and 009-D (provider webhooks) under D-049, against a synthetic provider. No real provider adapter exists, and every real provider rule in `app.privacy.providers` stays blocking until its own specification (010-013) re-verifies it. Native `tracking_sys` has received none of the connector migrations (0009 onward).

## Configuration
Connectors need the D-025 token keyring of the [event collection guide](event-collection.md) (`TRACKING_TOKEN_KEYRING`, `TRACKING_TOKEN_KEYRING_ACTIVE`). Routes answer `503 connector_not_configured` while it is blank.

| Setting | Meaning |
|---|---|
| `TRACKING_CONNECTOR_SYNTHETIC_STATE` | Path of the synthetic provider's SQLite state file, shared by the API and the worker. Development only; production configuration is refused. Unset means no provider is available (`404 provider_unavailable`). |
| `TRACKING_CONNECTOR_REDIRECT_URI` | The provider callback, which must be this API's `/connectors/oauth/callback` (HTTP only on loopback). Default `http://127.0.0.1:8000/connectors/oauth/callback`. |
| `TRACKING_CONNECTOR_COMPLETE_URL` | Where the browser goes after the callback; its origin must be an allowed origin. Default `<frontend origin>/connections/complete`. |
| `TRACKING_CONNECTOR_TEARDOWN_HOURS` | Teardown deadline after a disconnect request, at most 72. The 72-hour target applies to the local synthetic slice only. |
| `TRACKING_CONNECTOR_SYNC_INTERVAL_HOURS` | The worker queues an incremental run for an active connection whose last run is older than this, 1-168 hours. Default 24. |
| `TRACKING_CONNECTOR_CONNECTION_DAILY_UNITS` | Daily allocation of each connection in its provider's cost unit, counted per UTC day, in addition to the provider's own daily quota. Default 100. A synthetic development value, not a commercial budget (Q-004). |

The synthetic provider never makes network calls. Its authorization URL uses the reserved `.invalid` domain. Tests approve it with `SyntheticProvider.approve`, which stands in for the provider's consent page and returns the code that the provider would send to the callback.

## Roles
| Actor | May | May not |
|---|---|---|
| Owner/Admin (browser session) | Connect, reconnect, request a sync, disconnect | — |
| Members with client visibility, read service keys with a client grant | List and read connection status | Any mutation |
| The browser session that started an authorization | Complete its callback | Complete another session's callback |
| Worker (`tracking_app`) | Claim runs and teardowns, write fenced results, revoke, destroy and purge | Delete connections, secrets, runs or transactions |

## Flow
1. `POST /agencies/{a}/clients/{c}/connections` with `{"provider": "synthetic"}` returns `authorization_url` and sets the HttpOnly binding cookie `tracking_connector_oauth` (`__Secure-` when secure) on `/connectors/oauth`.
2. The provider redirects to `GET /connectors/oauth/callback?code=&state=`. The browser is redirected (303) to the completion URL with `result=connected&connection_id=...`, or with one fixed `error`: `connection_failed`, `connection_cancelled`, `connection_denied`, `connection_changed`, `account_mismatch`, `account_already_connected`, `provider_unavailable` or `connector_not_configured`.
3. `GET /agencies/{a}/clients/{c}/connections[/{id}]` returns the status: provider, account reference, status and reason, scopes, connection and last successful sync times, available actions, and the disconnect outcome. Sealed material, key IDs, generations, leases and digests are never returned. The `actions` flags are `true` only for an Owner or Admin session and a connection in the matching state.
4. `POST .../connections/{id}/sync` queues a synchronization of an active connection (202). Without a body, or with `{"kind": "incremental"}`, it reads from the stored watermark. `{"kind": "backfill", "days": N}` extends the stored history N days further back, at most the provider's history limit (`422 invalid_backfill`), after a completed synchronization (`409 sync_required`). An open run of the same kind is returned; an open run of the other kind answers `409 sync_in_progress`. The callback also queues an incremental run.
5. `POST .../connections/{id}/reconnect` starts a new authorization for a connection in `reconnect_required`. It must return the same external account. The callback first checks everything the installation needs: a current session, the initiator's Owner or Admin membership in an active agency, an active client, the generation recorded when the reconnect began, and the external account. A reconnect refused by any of these checks disposes of its new grant and leaves the previous grant untouched. Only then are the previous grant's tokens revoked at the provider, before the new grant replaces them. If that revocation is not confirmed or reported unsupported, the reconnect ends with `provider_unavailable` and can be retried; the previous tokens stay outstanding for the next reconnect or disconnect. When two reconnects of one connection overlap, one installs its grant and the other ends with `connection_changed` and disposes of its own grant only.
6. `POST .../connections/{id}/disconnect` (202) stops the connection and fixes `purge_due_at`. Repeated requests return the same state.

## Synchronization (009-B)
A run reads its window page by page. Each page's records, the run's page count and the checkpoint's opaque cursor commit together, fenced by the run attempt, which also renews the lease. A worker that stops before that commit leaves the page to be read again; one that stops after it leaves the next page. When the lease expires, another pass resumes the run at the stored cursor, so no page is skipped and no record is stored twice (records are unique per connection and provider object). The last page moves the stream's `covered_from` and `complete_through` watermarks to the window the provider reported and finishes the run in the same transaction. An incremental run starts one day (the provider's overlap) before `complete_through`; a backfill moves only `covered_from`.

| Provider answer | Run outcome |
|---|---|
| `401` | One refresh, then `reconnect_required` (009-A) |
| `403` | `failed` with `forbidden`, no retry; the connection stays `active` |
| `429` | Back to `queued` until `Retry-After` has passed (default 60 s, at most 1 hour) |
| Retryable `5xx` | Back to `queued` after 30 s, doubling per deferral, at most 15 minutes |
| Permanent | `failed` with `permanent` |

A run is deferred at most five times for `429` and retryable failures together; the next such failure fails it. Every provider data call (`fetch`, `refresh`) is first reserved in `connector_usage_records` with the provider's cost, then settled with its outcome; a call whose worker stopped stays `reserved` and still counts. A reservation that would exceed the connection's daily allocation or the provider's daily quota (counted across all tenants, per UTC day) is not made: the run returns to `queued` with `budget_exhausted` until the next UTC day and keeps its checkpoint. The disconnect purge deletes checkpoints with the provider records; usage rows hold no provider data and stay with the run history, whose retention awaits Q-012.

## Coverage and provenance (009-C)
Readers with `client:read` (members with client visibility and read service keys) may call:

- `GET .../connections/{id}/coverage`: the source (provider, adapter version, account kind), status, last successful sync and `freshness` (`fresh`, `stale` after the adapter's freshness window, 24 hours for the synthetic adapter, or `never_synced`), the latest run's `sync` state (`idle`, `queued`, `running`, `delayed` after a rate limit or retryable failure, `budget_stopped`, `failed`) with its reason and next attempt, each stream's `covered_from`, `complete_through` and history limit with `state` `not_synced`, `partial` (a run stopped between pages) or `complete`, each declared metric's availability (`available`, `unsupported` for the account kind, `missing` when no stored record has a value, `stale`, `not_synced`), and the connection's own cost for the current UTC day (`consumed`, `allocation`, `remaining`, `state`, and `reason` `connection_allocation` or `provider_quota`).
- `GET .../connections/{id}/records?limit=&after=`: stored records ordered by provider object ID, at most 100 per page, each with `observed_at`, `fetched_at`, its source (provider, adapter version, run) and every declared metric as `{"state", "value"}`: `observed` (zero included), `missing` (omitted or null), `unsupported` (value null) or `stale` (value kept).

Neither response contains another tenant's usage, the provider-wide quota consumption, cursors, leases, tokens or raw provider errors. After a disconnect, the purge removes records and checkpoints and clears the account kind, so every metric reads `not_synced`.

## Provider webhooks (009-D)
`POST /connectors/webhooks/{provider}` is public: it needs no session, credential or Origin. The adapter verifies its own signature over the exact raw body before reading it. The synthetic adapter reuses the Spec 004 scheme in `X-Synthetic-Signature` (`t=<unix seconds>,v1=<hex HMAC-SHA256 of '<t>.<raw body>'>`, 300-second window) with an application secret generated once in its state file; `SyntheticProvider.sign_delivery` stands in for the provider's sender. Its body names an `event_id` and an `account_id`.

| Delivery | Answer | Effect |
|---|---|---|
| Verified, first time | `200 {"result": "accepted"}` | One incremental run queued for each `active` connection of the account whose agency and client are active, coalescing with an open run; a delivery record is kept |
| Verified, repeated event ID | `200 {"result": "duplicate"}` | None |
| Missing, invalid or expired signature | `401 signature_invalid` or `signature_expired` | None; nothing is stored |
| Verified but unreadable body | `400 invalid_delivery` | None |
| Body above 16 KiB | `413 request_too_large` (request boundary) | None |
| Provider without webhooks or not configured | `404 provider_unavailable` | None |

The answer is the same whether or not any connection matched, so it reveals nothing about connected accounts. The payload is never stored: the queued sync reads the data through the authorized API under each connection's own tokens, fence and limits. Connections that require reconnection, are disconnecting or are disconnected receive nothing. `connector_webhook_deliveries` keeps only the provider, a SHA-256 digest of the event ID, the receipt time and the number of connections notified, and `python -m app.lifecycle` deletes it 7 days after receipt. Deliveries are rate-limited per provider and peer at the trusted intake rate.

## Worker
`python -m app.connector_worker` (from `backend/`, with the project `.venv`) runs one bounded pass and prints counts, for example `{"teardown": {"disconnected": 1}, "schedule": {"queued": 2}, "sync": {"succeeded": 2}}`. It runs teardowns first, then a scheduling step that queues an incremental run for each active connection (of an active agency and client) with no open run whose last run is older than the sync interval, then sync runs. It is not a long-running scheduler: an operator or an OS scheduler invokes it, and production scheduling and supervision are decided in 020. The 72-hour target is met only if it runs within that time. Teardowns past their deadline run first, then those with the fewest attempts, so one failing provider revocation cannot hold back other connections. A sync attempt whose lease expired and was claimed again by another pass is superseded: it writes nothing.

Teardown revokes each outstanding token at the provider, refresh token first. It then destroys all sealed material (the rows stay, with NULL material and `status = destroyed`), deletes the connection's provider records, and clears the account reference. A transient revocation failure is retried on later passes. At the deadline the teardown completes anyway and reports `revocation: failed`. The completion time (`disconnect.completed_at`) is read after the purge, so `deadline_met` is `false` whenever the revocation or the purge itself ends after `purge_due_at`. In that case, remove the application's access in the provider account's settings. When a newly issued grant cannot be kept and its revocation is unsupported or fails, the log event `connector_grant_disposal_failed` reports `outcome` `unsupported` or `failed`.

## Verification
The integration suite `backend/tests/integration/test_connectors.py` runs on the disposable PostgreSQL service of the [backend test guide](../../backend/tests/README.md). One case starts the worker as a separate process with the shared provider file. Never point it at `tracking_sys`.
