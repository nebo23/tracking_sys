# 011-A design: YouTube-shaped synthetic adapter and runtime extensions

Prepared: 2026-11-18 on `codex/spec-011-youtube`. Authority: D-058 (D1-D14, D16 and D17 as recommended) and D-060 (D9 amended, completion order). At the owner's request of 2026-11-18, 011-A started before the next-day probe (F8) ran. F8 is recorded when it runs, and any change to D9 that it requires goes to the owner first. This note implements the [entry review](entry-review.md) section 6, item 1, with the consequences recorded in the [evidence](evidence.md). It adds no dependency and makes no live call. Migration `0015` runs only on the disposable PostgreSQL service of `backend/tests/README.md`.

## 1. Contract extensions (`app/connectors/contracts.py`)

All new fields have defaults that keep the 009 and 010 adapters unchanged.

| Contract | Addition | Decision |
|---|---|---|
| `Capability.revocation_scope` | New value `account`: one revocation invalidates every token the account granted to the project (G-1). | D5 |
| `Capability.require_all_scopes` | The callback installs a grant only when its `scope` answer holds every requested scope. | D2 |
| `Capability.refresh_ahead_seconds` | A run refreshes the access token when it expires within this many seconds (300 for YouTube). | D4 |
| `Capability.authorization_check_days` | A run forces a refresh when the last one is older than this (7). | D6 |
| `Capability.reconnect_grace_days` | A connection left in `reconnect_required` this long (14) is disconnected and purged with reason `authorization_lost`. | D6 |
| `Capability.buckets`, `QuotaBucket` | Named daily buckets, each with a unit, a provider cap, a per-connection allocation and the time zone of its day. | D10 |
| `Capability.day_zone` | The zone of the provider's days (`America/Los_Angeles`); incremental overlaps are counted in its local days. | D9 |
| `Capability.agent_disclosure` | The disclosure version a connect or reconnect must approve (`dev-agent-approval-1` until the owner's wording, D-039). | D13 |
| `Capability.label_refresh_days` | The account label carries a refresh time and is cleared when not refreshed for this many days (30). | D11 |
| `StreamSpec.cost` | Units per page in each bucket. | D10 |
| `StreamSpec.data_delay_hours` | A per-stream delay for the provisional marking, replacing the capability's. | D9 |
| `StreamSpec.attributes` | The allow-listed record attributes; anything else an adapter returns is dropped. | D11 |
| `StreamSpec.inventory`, `confirm_cost` | A complete read lists every live object; objects missing from it are confirmed gone through the adapter and purged from every stream. | D11 |
| `MetricSpec.additive`, `definition_changes` | The non-additive marker and the dates on which the provider changed a metric's definition. The unit `rounded_count` marks `subscriberCount`. | D8 |
| `TokenGrant.refresh_expires_at` | The reported refresh-token lifetime (`refresh_token_expires_in`), kept as the grant's expiry. | D4, F1 |
| `TokenGrant.refusal` | The adapter holds tokens but the account cannot be connected (no channel, several channels). | F4 |
| `ProviderRecord.attributes`, `provisional_until` | Allow-listed attributes, and an explicit end of the provisional period for lifetime totals of recent videos. | D9, D11 |
| `ProviderPage.account_label` | A label read with the page (the channel title), which refreshes the connection's label. | D11 |
| `ProviderError.bucket` | The bucket a `quotaExceeded` answer concerns. | D10 |
| `ConnectorProvider.confirm_deleted` | Given object IDs missing from an inventory read, return those the provider confirms gone. | D11 |

## 2. Runtime changes (`app/services/connectors.py`, `connector_coverage.py`, `lifecycle.py`)

- **Scopes (D2).** After the exchange, a grant whose scopes lack a requested scope is refused with the callback code `scopes_missing` and disposed of under the D5 rule. A grant with an adapter refusal is refused with `account_unavailable`.
- **Account-wide grants (D5).** For `revocation_scope = "account"`:
  - A reconnect records the previous versions as `not_required` and destroys them without a provider call, because revoking them would revoke the new grant.
  - A refused grant, or the teardown of a disconnect, revokes only when no other `active` connection of the same provider and external account exists, in any tenant. Otherwise the tokens are destroyed and the revocation is recorded as `shared`, and the connection-level outcome is `shared`. The last connection revokes. The check reveals nothing to the caller: the response is the same either way.
  - A refreshed access token is never disposed of after a generation change, because the teardown or the reconnect settles the grant.
  - A disconnect racing a new connect of the same channel can revoke the new grant (Google revokes every token at once). That connection then fails its first refresh and requires reconnection; this is recorded as a known limit.
- **Refresh (D4, D6).** A run refreshes when the access token expires within `refresh_ahead_seconds`, so no call is made with an expired token, and when the last refresh is older than `authorization_check_days`. The scheduler queues every stream at least daily, so the check holds for tokens of any lifetime. `invalid_grant` makes the connection `reconnect_required` and sets `reconnect_required_since`. The worker step `expire_reconnects` starts the disconnect, with reason `authorization_lost`, of connections whose grace period has passed. The refresh-token expiry is stored on the token row and on the connection (`grant_expires_at`), and the connection view shows it.
- **Quota buckets (D10).** Each data call reserves its stream's cost in every bucket it touches, against the bucket's provider cap and per-connection allocation for the bucket's local day. The usage row records the bucket, and its `period` is that local day. A refresh reserves nothing in a bucketed provider (the token endpoint is not metered). A cap or allocation stop, and an adapter `quotaExceeded` (`BUDGET_EXHAUSTED` with its bucket), defer the run to the bucket's next local midnight with `budget_exhausted`, not counted as a retry or a failure. Providers without buckets keep the 009 behavior.
- **Pacific days (D9 as amended by D-060).** The incremental window starts `overlap_days` local days before `complete_through`, computed in `day_zone`, so it starts at a local midnight on both sides of a daylight-saving change. The adapter reports `complete_through` as the end of the last local day that ended at least 72 hours before the read, and a day of the window without a row as a record with no values and `not_returned` for every metric. Day records are provisional for 193 hours from the day's start (the 4-day re-read after the 72-hour latency, plus one hour for a 25-hour day). Lifetime totals of videos published within that period carry `provisional_until`.
- **Attributes and labels (D11).** `_store_page` keeps only the stream's allow-listed attributes and sets `attributes_refreshed_at`, and a page's `account_label` refreshes the connection's label and `account_label_refreshed_at`. The lifecycle job clears attributes and labels not refreshed for 30 days, leaving the statistics.
- **Deleted videos (D11).** At the end of a complete read of an inventory stream, the runtime collects the stream's objects that the read did not return. It asks the adapter which of them are gone (reserved at `confirm_cost` per 50 IDs), deletes the confirmed objects' records from every stream of the connection under the run fence, and then completes the run. An object that still exists stays.
- **Retention (D11).** `LifecycleSettings.connector_provider_retention_days` sets a period per provider (730 for `synthetic_youtube` and `youtube`), at most the global 730 days.
- **Agent approval (D13).** For a provider with `agent_disclosure`, connect and reconnect require `agent_approval: {"approved": true, "disclosure": <version>}` with the current version. Otherwise the request is refused with 422 `agent_approval_required`. The transaction stores the approval time and version, and the installation copies them to the connection, where a disconnect keeps them as evidence. No customer-facing text is added.
- **Catalog and coverage (D8).** Coverage lists each metric's `additive` flag and `definition_changes`, and the cost block adds one entry per bucket. Records list their allow-listed attributes with the refresh time, and product types widen to `SHORTS`, `VIDEO_ON_DEMAND`, `LIVE_STREAM` and `UNSPECIFIED`.

## 3. Synthetic adapter (`app/connectors/synthetic_youtube.py`)

It reuses the SQLite storage of the 009 synthetic provider and reproduces the 011-B answers, not the live service:

- **Authorization.** `access_type=offline`, `prompt=consent` and PKCE `S256`, which is required (F2). Access tokens last one hour. The refresh token is not rotated and expires 7 days after the consent (Testing, F1 and F3), and refreshes report the same expiry.
- **Account-wide revocation (G-1).** Revoking any token revokes every grant of the account.
- **Partial consent.** It grants only the scopes approved on the stand-in consent page, together with any scope a live grant of the same account already holds (F1).
- **Channels.** The account has one channel by default; zero or several channels produce a refusal (F4).
- **Clock.** A test-controlled clock (default 2026-11-06 20:00 UTC) places the data and the 72-hour completeness. Sparse days: every seventh day returns no row, and some days return zeros.
- **Videos.** The inventory includes private and unlisted uploads with their privacy status. Pages hold 50 videos, matching the 50-ID limit (F5). Statistics may be hidden (`not_returned`). `creatorContentType` comes back in lowerCamelCase and maps to `SHORTS`, `VIDEO_ON_DEMAND` and `UNSPECIFIED`; unobserved values map to `UNSPECIFIED`.
- **Errors (F14, YT-5).**

  | Answer | Kind | Effect |
  |---|---|---|
  | 401 `authError` | `UNAUTHORIZED` | One refresh, then `reconnect_required` |
  | 403 `insufficientPermissions` | `FORBIDDEN` | The stream's run fails; other streams continue |
  | 403 `quotaExceeded` | `BUDGET_EXHAUSTED` with its bucket | Deferred to the next Pacific midnight |
  | 429 or `rateLimitExceeded` | `RATE_LIMITED` | Deferred with backoff, as in 009 |
  | 5xx | `RETRYABLE` | Deferred with backoff, as in 009 |
  | 400 | `PERMANENT` | The run fails |

- **Test controls.** `set_behavior` also controls titles leaked into attributes (to test the allow-list) and a playlist that hides a video that still exists.

Streams and costs (D7, D10):

| Stream | Records | Window | Cost per page |
|---|---|---|---|
| `channel` | `snapshot-YYYY-MM-DD`, one per Pacific day read; `subscriberCount` (rounded count), `viewCount`, `videoCount`; label refresh | The read day | 1 Data unit |
| `channel_daily` | `day-YYYY-MM-DD`, the section 3.2 catalog; a missing day has `not_returned` for every metric | 90 days at connect, 4-day overlap, backfill to 730 days, 31 days per page | 1 Analytics request |
| `videos` | One per video: `viewCount`, `likeCount`, `commentCount`; attributes `published_at`, `duration`, `privacy_status`, `live_state`; inventory | Whole inventory, 50 per page | 2 Data units (playlist page and `videos.list`); confirmation 1 Data unit per 50 IDs |
| `video_totals` | One per video with lifetime totals and the product type; `provisional_until` for recent uploads | Whole inventory, 50 per page | 1 Data unit and 1 Analytics request |

Buckets: `youtube_data` (cap 9,000 of 10,000 units, 100 per connection), and `youtube_analytics` (cap 90,000 of 100,000 requests, 30 per connection), both on the Pacific day. The adapter makes no `batchGetStats` call, because `videos.list` returns the statistics with the attributes, so that bucket is not declared. A channel with more than about 1,450 videos exceeds the 30 Analytics requests a day; its `video_totals` run then continues from its cursor the next Pacific day.

## 4. Migration `0015_youtube_runtime`

| Table | Change |
|---|---|
| `connector_connections` | Provider `synthetic_youtube`; reason `authorization_lost`; revocation outcome `shared`; columns `reconnect_required_since`, `account_label_refreshed_at`, `grant_expires_at`, `agent_approved_at` and `agent_disclosure` (varchar 64). Checks: `reconnect_required_since` is set exactly when the status is `reconnect_required` (existing rows take `updated_at`), and the two approval columns are set together. |
| `connector_oauth_transactions` | `agent_approved_at` and `agent_disclosure`, set together. |
| `connector_token_secrets` | Revocation outcome `shared`. |
| `connector_usage_records` | Column `bucket` (varchar 32, null for providers without buckets); operation `confirm`; index on (`provider`, `bucket`, `period`). |
| `connector_records` | Product types `SHORTS`, `VIDEO_ON_DEMAND`, `LIVE_STREAM` and `UNSPECIFIED`. Column `attributes` (jsonb object of at most 1,024 characters, default `{}`), with `attributes_refreshed_at` set whenever attributes are present. Column `provisional_until`. |
| `connector_webhook_deliveries`, `connector_deletion_requests` | Provider `synthetic_youtube`. |

**Privileges.**
- `tracking_app` gains `UPDATE` on the new connection and record columns.
- `tracking_lifecycle` gains:
  - `SELECT (id, provider, account_label_refreshed_at)` and `UPDATE (account_label, account_label_refreshed_at)` on connections;
  - `UPDATE (attributes, attributes_refreshed_at)` on records.

  It still cannot read labels or change metrics.

**Downgrade.** It refuses while any 011-A state exists (a `synthetic_youtube` row in any table, a `shared` or `authorization_lost` value, a bucket, attributes, a provisional end, an approval, or a widened product type), then reverts every change.

## 5. API changes

- `POST .../connections` accepts `synthetic_youtube` and an optional `agent_approval`. `POST .../reconnect` takes an optional body with the same field.
- Connection responses add `grant_expires_at`. The revocation outcome adds `shared`, and the reasons add `authorization_lost`.
- Coverage adds, per metric, `additive` and `definition_changes`, and adds `cost.buckets`.
- Records add `attributes` and `attributes_refreshed_at`, and the product types widen.
- The callback codes add `scopes_missing` and `account_unavailable`.
- The OpenAPI snapshot is regenerated.

## 6. Tests (entry review section 6) and mutation checks

`backend/tests/integration/test_connector_youtube.py` covers each case on the disposable service:

- authorization parameters (offline access, consent, PKCE `S256`);
- partial consent refused and disposed without harming another channel's connection, and the union grant of F1 accepted;
- refresh ahead of expiry with no unauthorized call;
- account-wide grants: two clients with one channel, the shared disconnect, the last disconnect revoking, reconnect without revocation, and a refused duplicate connect;
- the 7-day check and the purge after 14 days in `reconnect_required`;
- the Pacific quota day, a `quotaExceeded` deferral that is not a failure, and separate buckets;
- Pacific days across the 2026-11-01 change (a 25-hour day), `complete_through`, provisional values and `not_returned` days;
- product types, rounded counts and the non-additive marker;
- attributes and labels cleared after 30 days without refresh;
- a deleted video purged from every stream, and a hidden but existing video kept;
- the 730-day retention per provider and the lifecycle privileges;
- the D13 approval;
- tenant isolation.

Unit tests in `backend/tests/test_connector_youtube_synthetic.py` cover the pure parts: the Pacific day arithmetic, the content-type mapping, the completeness bound and the capability declarations.

**Mutation checks.** Each safeguard is disabled in turn, the YouTube tests are rerun, and the source is restored byte for byte, as in 009 and 010. The safeguards:
1. the scope check;
2. the shared-revocation rule;
3. the reconnect without revocation;
4. refresh ahead;
5. the authorization check;
6. the grace purge;
7. the bucket reservation;
8. the Pacific period;
9. the quota deferral;
10. the local-day overlap;
11. the attribute allow-list;
12. the deletion confirmation;
13. the approval check;
14. the lifecycle clearing.
