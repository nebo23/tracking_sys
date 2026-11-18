# Connector runtime (specification 009)
Status: 009-A (connection lifecycle) is implemented locally under D-048, and 009-B (synchronization), 009-C (coverage and provenance) and 009-D (provider webhooks) under D-049, against a synthetic provider. 010-A (D-053) adds an Instagram-shaped synthetic provider and the runtime extensions it needs; see [Instagram-shaped providers](#instagram-shaped-providers-010-a). 010-C (D-055) adds the live Instagram Login adapter; see [Live Instagram adapter](#live-instagram-adapter-010-c). 011-A (D-058, D-060) adds a YouTube-shaped synthetic provider and its runtime extensions, and 011-C the live YouTube adapter; see [YouTube providers](#youtube-providers-011-a-and-011-c). Every other real provider rule in `app.privacy.providers` stays blocking until its own specification (012-013) re-verifies it. Native `tracking_sys` has received none of the connector migrations (0009 to 0016).

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
| `TRACKING_CONNECTOR_INSTAGRAM_ENABLED` | Registers the live Instagram Login adapter (010-C) when true, with the app ID and secret set and the `meta.platform_data` and `instagram.login_api` rules current. Default false. |
| `TRACKING_INSTAGRAM_APP_ID`, `TRACKING_INSTAGRAM_APP_SECRET` | The Meta app's Instagram app ID (digits) and app secret, kept only in the ignored `.env` and required when the adapter is enabled. The 010-B feasibility tool reads the same values. |
| `TRACKING_CONNECTOR_YOUTUBE_ENABLED` | Registers the live YouTube adapter (011-C) when true, with the client ID and secret set and the `youtube.authorized_analytics` and `youtube.other_data` rules current. Default false. Turning it off is the kill switch. |
| `TRACKING_YOUTUBE_CLIENT_ID`, `TRACKING_YOUTUBE_CLIENT_SECRET` | The connector's own Google Web client (`...apps.googleusercontent.com`) and secret, kept only in the ignored `.env`. The client must differ from the Google sign-in and Gmail sender clients. The 011-B feasibility tool reads the same values. |

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
A run reads its window page by page. Each page's records, the run's page count and the checkpoint's opaque cursor commit together, fenced by the run attempt, which also renews the lease from the time of that write. Every step of a run reads the clock when it happens (R009-11), so a deferral counts from the provider's answer and fetch and usage times are those of the calls. A worker that stops before that commit leaves the page to be read again; one that stops after it leaves the next page. When the lease expires, another pass resumes the run at the stored cursor, so no page is skipped and no record is stored twice (records are unique per connection and provider object). The last page moves the stream's `covered_from` and `complete_through` watermarks to the window the provider reported and finishes the run in the same transaction. An incremental run starts one day (the provider's overlap) before `complete_through`; a backfill moves only `covered_from`.

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

## Instagram-shaped providers (010-A)
D-053 adds `synthetic_instagram`, built next to `synthetic` from the same development state setting (its SQLite file carries an `-instagram` suffix). It follows the shapes of the Instagram API with Instagram Login described in the [Spec 010 entry review](../../specs/010-instagram/entry-review.md); it is not the live service, and its metric names stay provisional until the feasibility check (010-B).

| Behavior | Runtime handling |
|---|---|
| No PKCE | The authorization URL carries no code challenge and the exchange no verifier; the single-use state, the session-bound cookie and the server-side exchange still apply. |
| One long-lived token that refreshes itself | There is no refresh token. Before reading, the worker refreshes the access token once it is at least 24 hours old and within 7 days of expiry; a refused refresh makes the connection `reconnect_required` (`credential_expired`) with its data kept. |
| No revocation endpoint | Disconnect reports `revocation: unsupported`; tokens are destroyed and data purged as usual. |
| Streams `account` (daily), `media` (daily, 2-day overlap) and `stories` (every 2 hours) | Runs, checkpoints and records carry their stream, with one open run per connection and stream. A connect, a webhook delivery and the scheduling step queue every stream. `POST .../sync` accepts `{"stream": "media"}`; the first stream is the default. `GET .../records?stream=` reads one stream, the first by default. |
| Metrics by media product type, thresholds and empty data | Records carry `product_type` (`FEED`, `REELS`, `STORY`). A metric not offered for the product type is `unsupported`; one the provider withheld is `missing` with `reason` `not_returned` or `below_threshold`; neither is ever 0. Coverage lists each metric with its stream and product types, and each stream with its own latest run. |
| 48-hour data delay | Records observed within the delay are `provisional: true`. |
| No fixed daily quota | Only the per-connection allocation and the provider's rate-limit answers apply. |

### Deauthorize and data deletion callbacks
`POST /connectors/{provider}/deauthorize` and `POST /connectors/{provider}/data-deletion` are public form posts with one field, `signed_request` (`<base64url HMAC-SHA256 signature>.<base64url JSON payload>` signed with the app secret, as Meta sends it). The adapter verifies the signature before reading the payload and refuses a request issued more than 1 hour ago (synthetic adapter) or 24 hours ago (live Instagram adapter) (`401 signature_invalid` or `signature_expired`, `400 invalid_delivery`). A verified request starts the disconnect of every live connection of the named account in every agency and client, archived clients included, with reason `deauthorized` or `deletion_requested`; the answer never reveals whether any connection matched. A data deletion request answers `{"url", "confirmation_code"}`; `GET /connectors/{provider}/data-deletion/{code}` reports `pending` until every connection it stopped has been destroyed and purged, then `completed`. The request row keeps no account or tenant. These provider-initiated disconnects have no human actor and therefore no audit event; the connection's reason and the request row record them.

## Live Instagram adapter (010-C)
D-055 adds `instagram`, the adapter for the Instagram API with Instagram Login (`app.connectors.instagram`, version `instagram-login-v27.0`). It has the behaviors of the Instagram-shaped providers above, with the answer shapes the 010-B feasibility check recorded; see the [Spec 010 evidence](../../specs/010-instagram/evidence.md#010-c-live-instagram-login-adapter-2026-11-17).

| Topic | Behavior |
|---|---|
| Registration | Only with `TRACKING_CONNECTOR_INSTAGRAM_ENABLED=true`, the app ID and secret, and current `meta.platform_data` and `instagram.login_api` rules (re-verified 2026-11-17, review due 2027-11-17). A rule past its review date removes the adapter at the next API or worker start. |
| Account reference | The app-scoped `id` from `GET /me`, which Meta's signed requests name; reads use the professional account's `user_id`. |
| Permissions | The adapter requests `instagram_business_basic` and `instagram_business_manage_insights`. Instagram grants every permission configured on the app, so the product's Meta app must be configured with these two only; a grant with more is kept, with every permission in `granted_scopes`, and logged as `connector_extra_scopes`. |
| Streams | `account`: one UTC day per page with the eleven account metrics, up to 729 days back. `media`: feed posts and reels, ten per page, with lifetime insights requested by product type, up to 730 days back. `stories`: every live story is re-read on each run. |
| Absent values | `follows_and_unfollows` is `below_threshold` under 100 followers; any other empty or refused metric is `not_returned`; an item whose insights are all refused is left out. |
| Limits | Graph throttling codes (4, 17, 32, 613, 80001, 80002, or HTTP 429) and an `x-app-usage` figure of 90% or more defer the run by 15 minutes; the per-connection daily allocation counts pages. |
| Tokens | No PKCE and no revocation endpoint; the long-lived token refreshes itself through `ig_refresh_token`. |
| Signed requests | Verified with the app secret and accepted for 24 hours after Meta signed them. |

Meta redirects only to an HTTPS redirect URI registered on the app, so a browser connect through `/connectors/oauth/callback` needs the API hosted at such an address (020), where the deauthorize and data deletion URLs are registered as well. Until App Review, Advanced Access and Business Verification (010-D), Meta's development mode lets only people with a role on the app authorize it, and live use stays with owner-authorized test accounts. The tests use the in-memory `backend/tests/instagram_graph.py`; nothing in the suite contacts Meta.

## YouTube providers (011-A and 011-C)
D-058 and D-060 add two providers:
- `synthetic_youtube` (011-A), built next to the other synthetic providers from the same development state setting. Its SQLite file carries a `-youtube` suffix.
- `youtube` (011-C, `app.connectors.youtube`, version `youtube-data-v3-analytics-v2`), the adapter for the YouTube Data API v3 and the YouTube Analytics API.

Both follow:
- the [Spec 011 entry review](../../specs/011-youtube/entry-review.md) as decided;
- the [011-A design note](../../specs/011-youtube/design-011a.md);
- the answers of the 011-B feasibility check in the [evidence](../../specs/011-youtube/evidence.md).

| Topic | Behavior |
|---|---|
| Registration | `youtube` only with `TRACKING_CONNECTOR_YOUTUBE_ENABLED=true`, its own Web client, and current `youtube.authorized_analytics` and `youtube.other_data` rules (re-verified 2026-11-18, review due 2027-11-18). |
| Authorization | Offline access, consent on every connect and reconnect, PKCE `S256`, and only `youtube.readonly` and `yt-analytics.readonly`. A grant without both scopes is refused (`scopes_missing`). An account is refused (`account_unavailable`) when it has no channel or several, or when its channel cannot be read. |
| Agent approval | Connect and reconnect carry `agent_approval: {"approved": true, "disclosure": "dev-agent-approval-1"}`, otherwise `422 agent_approval_required`. The approval time and version stay on the connection. |
| Account-wide grants | Google revokes every token of an account at once. A reconnect replaces the tokens without revoking them (`not_required`). A disconnect or a refused grant revokes only when no other active connection holds the same account; otherwise the outcome is `shared`. A refusal whose account cannot be told apart from another connection's keeps the grant. |
| Tokens | One-hour access tokens are refreshed when they expire within 5 minutes, and at least every 7 days. A refused refresh makes the connection `reconnect_required`. After 14 days without a reconnect, the worker's scheduling step disconnects and purges it with reason `authorization_lost`. The refresh token's reported expiry is the connection's `grant_expires_at`. |
| Streams | `channel`: one snapshot per Pacific day, which also refreshes the label. `channel_daily`: Pacific days in windows of up to 31 days (see below). `videos`: the uploads inventory, 50 per page, with the allow-listed attributes `published_at`, `duration`, `privacy_status` and `live_state`. Videos missing from a complete read are confirmed gone through `videos.list` and purged from every stream. `video_totals`: lifetime totals per video with the `creatorContentType` product type. The live adapter reads two reports per page: the catalog by `video`, and the content type with `views` only, because Google refuses the playlist metrics together with `creatorContentType`. |
| Quotas | Buckets on the Pacific day: `youtube_data` (cap 9,000 units, 100 per connection) and `youtube_analytics` (cap 90,000 requests, 30 per connection). A cap, an allocation or a `quotaExceeded` answer defers the run to the next Pacific midnight with `budget_exhausted`; this does not count as a retry or failure. Coverage reports each bucket. |
| Retention | Records are kept at most 730 days (`connector_provider_retention_days`). The lifecycle job clears attributes and labels 30 days after their last refresh. |
| Operator purge | `python -m app.connector_purge --provider youtube --confirm` disconnects every YouTube connection with reason `operator_purged` and brings forward the deadline of teardowns already under way to the time of the purge (P-2 section 24.3). It revokes where the adapter is registered; with the setting off, it purges without revoking. Sealed material is destroyed and records purged in the same command. A teardown that a running worker holds is reported as `remaining` and completed by that worker. Only counts are printed. |

`channel_daily` reads:
- 90 days at connect, and backfill up to 730 days.
- It is complete through the end of the last Pacific day that ended at least 72 hours before the read.
- Each day stays provisional for 193 hours.
- A day the API does not return is recorded as `not_returned`.

Google accepts the loopback callback, so a browser connect through `/connectors/oauth/callback` works locally. While the Google Cloud project is in Testing:
- only its test users can authorize;
- refresh tokens last 7 days;
- live use stays with the owner's test channels until 011-D.

The tests use the in-memory `backend/tests/youtube_api.py` and the synthetic adapter; nothing in the suite contacts Google.
