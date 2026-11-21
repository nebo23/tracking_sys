# 014 design: advertising spend and conversion delivery (Meta)

Prepared: 2026-11-21 on `codex/spec-014-ad-spend-capi`. Authority: D-063 and D-064 (D1-D14 of the [entry review](entry-review.md) as recommended). The Phase 0 source verification is in [entry review section 2.4](entry-review.md#24-official-sources-read-in-phase-0). This note applies its parameter-level results, adds no dependency and makes no Meta call. D-065 (2026-11-21) amended the D9 delivery key and the worker's delivery step after Claude's review of PR 12; sections 5.2, 5.3, 7 and 8 record it. Migrations `0017` to `0019` run only on the disposable PostgreSQL service of `backend/tests/README.md`. No frontend changes.

## 1. Parameters applied from Phase 0

| Source | Parameter | Where |
|---|---|---|
| V-1, V-4 | Daily ad-level insights (`level=ad`, `time_increment=1`, `time_range` with inclusive dates), windows of at most 7 days, cursor `after`; the last 28 days are re-read and stay provisional until 28 days after each day ends. | 014-A, 014-D |
| V-1 | Whether insights include deleted or archived ads by default is unverified. A re-read therefore never deletes a stored fact that a later read omits. | 014-A |
| V-2 | The allowed currencies are Meta's codes that are current in ISO 4217, with their ISO exponents (section 3.2). | 014-A |
| V-5, D13 | Backfills reach 730 days (the 37-month provider limit is longer). | 014-A |
| V-6 | Throttling codes 4, 17, 32, 613, 80000 to 80004, 80009 and 80014, or HTTP 429. The wait is the largest `estimated_time_to_regain_access` (minutes) of `X-Business-Use-Case-Usage`, otherwise 15 minutes. | 014-D |
| V-7 | Facebook Login for Business with `config_id`, `response_type=code` and `override_default_response_type=true`; tokens that do not expire and have no refresh; revocation `unsupported`; no signed callbacks. An invalid token makes the connection `reconnect_required` at once (T-07). Granted permissions come from `debug_token`. | 014-A, 014-B, 014-D |
| V-8, V-9, V-11 | One event per request; `event_name`, `event_time`, `action_source` and `user_data` required; `value` and `currency` for purchases; website events need `event_source_url` and `client_user_agent`, so website conversions are refused at enqueue (`provider_field_missing`). | 014-B, 014-D |
| V-9 | The 7-day age limit applies to every action source. The delivery deadline is `event_time` plus 7 days less 1 hour. | 014-B |
| V-10 | `fbc` = `fb.1.<first receipt of the fbclid in milliseconds>.<fbclid>`, never hashed or case-changed. | 014-B |
| V-12 | Deduplication by dataset, `event_name` and `event_id` within 48 hours, repeated server events included. | 014-B |
| V-13 | The error mapping of section 5.4. | 014-B, 014-D |
| V-14 | The delivery permission is `ads_read`. Both connection kinds require `ads_read`; `ads_management` is never needed and is flagged when granted. | 014-B, 014-D |
| V-17 | Graph API `v27.0`. | 014-D |
| V-18 | The ROAS join reads `utm_source=meta`, `utm_campaign={{campaign.id}}` and `utm_content={{ad.id}}`; collection ads on Instagram cannot carry them and stay unmatched. | 014-C |

## 2. Contract and runtime extensions

All new fields have defaults that leave the 009 to 011 adapters unchanged.

| Contract | Addition | Decision |
|---|---|---|
| `Capability.named_account` | `"ad_account"` or `"dataset"`: the connect request names the account (`act_<digits>` or `<digits>`), the transaction stores it, and after the exchange the runtime asks the adapter to describe it. | D2 |
| `Capability.connection_day_zone` | The day zone of a connection comes from its account (stored on the connection), not from the provider. | D4 |
| `Capability.delivery` | A delivery provider has no streams and is never synchronized; its connections serve destinations. | D2, D9 |
| `StreamSpec.storage` | `"advertising"` stores the stream's pages in the spend tables instead of `connector_records`. | D3 |
| `AccountSnapshot` | The described account: ID, label, kind, day zone and allow-listed attributes (currency, time zone, status). | D2, D4 |
| `ConnectorProvider.describe_account` | Describe the named account with a newly exchanged token, or raise `ProviderError` when the grant cannot read it. | D2 |
| `ConnectorProvider.send_event` | Send one conversion event to the dataset and return `DeliveryAnswer(events_received, trace_id)`, or raise `ProviderError`. | D9 |
| `fetch_page(..., account=, day_zone=)` | Passed only to adapters with `named_account` and `connection_day_zone`. | D2, D4 |

Runtime (`app/services/connectors.py`):
- **Named account (D2).** `begin` requires `account` for a provider with `named_account` and refuses it otherwise (422 `invalid_account`). A reconnect names the connection's own account. The callback describes the account after the exchange. Any refusal or provider error ends the connect with `account_unavailable`, and the grant is disposed of. The described ID becomes the connection's external account, so a reconnect can never move to another account (`account_mismatch` remains as a second check). `scopes_missing` applies as before (`require_all_scopes`).
- **Day zone (D4).** The installation stores the described zone in `connector_connections.day_zone`. The `account` stream refreshes it and records a change in `ad_accounts`. Incremental windows start `overlap_days` local days before `complete_through` in that zone.
- **Storage (D3).** For a stream with `storage="advertising"`, `_store_page` calls `app.advertising.spend.store_page` inside the same fenced transaction that moves the checkpoint.
- **Purge (D13).** The teardown's final transaction deletes the connection's `ad_spend_facts`, `ad_objects` and `ad_accounts`, cancels its open deliveries (`connection_ended`, payloads destroyed) and disables its destination.
- **Delivery providers.** They declare no streams, so no run is queued, synchronized or requested (`invalid_stream`), and coverage lists no stream.
- **Worker.** `process_connectors` adds a bounded delivery step after the sync step (section 5.3).

## 3. 014-A: spend ingestion

### 3.1 Synthetic provider `synthetic_meta_ads`

`app/connectors/synthetic_meta_ads.py`, state file `<state>-meta-ads.sqlite3`, registered with the other synthetic providers. It reuses the 009 SQLite storage and reproduces the verified shapes:
- **Authorization.** A Login for Business stand-in: `config_id`, `response_type=code`, `override_default_response_type=true`, no PKCE. `approve` grants a set of ad accounts and permissions. Access tokens do not expire; there is no refresh token.
- **Accounts.** Test controls create accounts with currency, time zone, status and name, and can change the currency or zone. `describe_account` refuses an account outside the grant.
- **Objects.** Campaigns, ad sets and ads with parent IDs, names and effective statuses (`ACTIVE`, `PAUSED`, `ARCHIVED`, `DELETED`), served 50 per page.
- **Daily rows.** One row per ad and account-local day while the ad runs, with `spend` as a decimal string, `impressions`, `clicks` and `account_currency`. Overrides change single values (restatements, extra decimal places, other currencies). A test-controlled clock places "today"; reads end at the start of today in the account zone.
- **Errors.** A script of outcomes: throttling (code 80000 with a wait), permission, invalid token, temporary and permanent errors.

### 3.2 Amounts

`app/advertising/currencies.py` holds the allow-list: every code of Meta's currency page that is current in ISO 4217, with its ISO exponent: exponent 0 for CLP, ISK, JPY, KRW, PYG and VND; 3 for BHD and JOD; 2 for the others (DZD, ARS, AUD, BDT, BOB, BGN, BRL, GBP, CAD, CNY, COP, CRC, CZK, DKK, EGP, EUR, GTQ, HNL, HKD, HUF, INR, IDR, ILS, KES, MOP, MYR, MXN, NZD, NIO, NGN, NOK, PKR, PEN, PHP, PLN, QAR, RON, RUB, SAR, RSD, SGD, ZAR, SEK, CHF, TWD, THB, TRY, AED, UAH, USD, UYU, VES). The ISO exponent is never below Meta's offset precision, so every amount Meta can report parses exactly. `Money.parse` reads `spend`. A value it refuses is `unparseable_amount`; a currency outside the table is `unsupported_currency`. Neither is rounded, and neither amount is stored.

### 3.3 Tables (`0017_ad_spend`)

Every table is scoped by agency and client and references its spend connection through the composite connection key.

**`ad_accounts`** (one row per spend connection): `connection_id` (unique), `account_id` (`act_<digits>`), `name` (200), `currency` (3), `time_zone` (64), `account_status` (integer), `previous_currency`, `currency_changed_at`, `previous_time_zone`, `time_zone_changed_at`, `observed_at`, `refreshed_at`. Checks: account pattern, currency `^[A-Z]{3}$`, each previous value present exactly when its change time is.

**`ad_objects`**: `connection_id`, `object_id` (digits, 32), `level` (`campaign`, `adset`, `ad`), `campaign_id`, `adset_id`, `name` (400), `effective_status` (32), `first_observed_at`, `refreshed_at`, `source_run_id`, `adapter_version`. Unique (connection, object). Checks: an ad set names its campaign, an ad names both parents. Refreshed by every inventory read; objects that a read omits are kept with their last status.

**`ad_spend_facts`**: `connection_id`, `ad_id`, `adset_id`, `campaign_id`, `spend_date` (account-local), `time_zone`, `currency`, `spend_minor` (bigint, null when refused), `impressions`, `clicks`, `refusal` (`unparseable_amount`, `unsupported_currency` or null), `provisional_until`, `revisions`, `first_observed_at`, `last_observed_at`, `source_run_id`, `adapter_version`. Unique (`connection_id`, `ad_id`, `spend_date`): a re-read updates the row. Checks: `(refusal IS NULL) = (spend_minor IS NOT NULL)`, non-negative counts and amounts. Index (`connection_id`, `spend_date`).

Also: `connector_connections.day_zone` (64) and `connector_oauth_transactions.requested_account` (32); providers admit `synthetic_meta_ads`.

**Privileges.** `tracking_app`: `SELECT, INSERT, DELETE` on the three tables; `UPDATE` only on the columns a re-read or refresh changes (all columns except the scope, connection, object and date keys and `first_observed_at`); `UPDATE (day_zone)` on connections. `tracking_lifecycle`: `SELECT (id, spend_date)` and `DELETE` on `ad_spend_facts`.

**Downgrade.** Refuses while any spend row, any `synthetic_meta_ads` connector row, a day zone or a requested account exists; then drops the tables and columns and restores the constraints.

### 3.4 Synchronization (D4, D5)

| Stream | Content | History | Overlap | Storage |
|---|---|---|---|---|
| `account` | Daily snapshot of currency, zone, status and name. | 1 day | 0 | `ad_accounts`; refreshes the connection's day zone and label. |
| `ad_objects` | Campaigns, ad sets and ads. | 1 day | 0 | `ad_objects` |
| `ad_daily` | One row per ad and day. | 730 days | 28 days | `ad_spend_facts` |

- The first `ad_daily` read covers 90 days back from the start of today in the account zone. A backfill extends `covered_from` within 730 days.
- A read is split into windows of at most 7 local days. The cursor keeps the read's first day, the window and the provider cursor inside it, so a resumed read skips no day.
- `complete_through` is the start of today in the account zone; today is never stored.
- A fact is provisional until 28 days after its day ends (`provisional_until`). A changed value increments `revisions`; identical values leave the row unchanged.
- Absent rows store nothing; a stored fact that a later read omits is kept (V-1).
- Throttling defers the run by the documented wait, otherwise 15 minutes (D5). Permission errors are `forbidden`. An invalid token makes the connection `reconnect_required` (no refresh, V-7). The per-connection daily allocation counts pages.

### 3.5 Route

`GET /agencies/{agency_id}/clients/{client_id}/ad-spend` with `connection_id`, `since`, `until` (account-local dates, at most 366 days) and `level` (`ad`, `adset`, `campaign`). It needs `finance:read`. The answer contains:
- the account's currency, zone and status;
- totals per currency (spend as a decimal string and in minor units, impressions, clicks);
- rows per object and currency at the chosen level, paged by `after`/`limit`;
- the provisional dates;
- the refused facts per reason;
- the coverage (`covered_from`, `complete_through` as local dates, and a state).

No total adds two currencies. The connection's records route returns no spend, because spend is never stored in `connector_records`.

## 4. 014-C: ROAS contract

`app/advertising/roas.py` is pure and has no route. `roas_report(facts, runs, *, connection_id, period, zone, model_version)`:
- **Spend.** Facts of the period (account-local dates), summed per ad, ad set and campaign.
- **Revenue.** For each 008-A run of the given model version whose sale instant falls in the period on the account's local calendar (conversion-date basis), each allocation whose touch has `source == "meta"`, `campaign_ref` equal to the ad's campaign and `content_ref` equal to the ad is credited to that ad. Credit from other touches, from other accounts' ads, or without the convention is reported as unmatched per currency. Names never join.
- **Value.** ROAS is credited revenue divided by spend (minor units of one currency, as an exact fraction and a 4-decimal string), only when spend is above zero and both share one currency. Otherwise it has no value and the reason is `zero_spend` or `currency_mismatch`. Spend with no credit gives 0.
- **Labels.** Each row names the model, version, window, period, currency and basis (`conversion_date`), and its spend state: `complete`, `provisional` (a provisional day) or `incomplete` (a refused fact or a day outside the coverage).
- **Never.** Runs of different model versions are refused (`model_version_mismatch`); amounts are never converted.

## 5. 014-B: conversion delivery

### 5.1 Synthetic receiver `synthetic_meta_capi`

`app/connectors/synthetic_meta_capi.py`, state file `<state>-meta-capi.sqlite3`. Authorization as in 3.1, granting datasets instead of ad accounts. `send_event` validates like the documented API:
- the required fields per action source;
- `value` and `currency` for `Purchase`;
- the 7-day age limit, which fails the whole request.

It answers `events_received`, `messages` and an `fbtrace_id`, and counts one event per dataset, event name and event ID within 48 hours. Test events are kept apart. A script of outcomes produces HTTP 5xx, throttling, an invalid token, a missing permission, an invalid parameter, an unknown dataset, an expired event and a wrong `events_received`.

### 5.2 Tables (`0018_conversion_delivery`)

**`conversion_destinations`**: `connection_id` (unique; a `meta_capi`-kind connection of the client), `event_name` (default `Purchase`, `^[A-Za-z][A-Za-z0-9_]{0,39}$`), `test_event_code` (`^[A-Za-z0-9]{1,32}$` or null), `enabled` (default false), `created_by_membership_id`, `created_at`, `updated_at`. The dataset is the connection's external account; it is not copied.

**`conversion_deliveries`**: `destination_id`, `connection_id`, `event_id` (64 hex; see the delivery key below), `event_name`, `action_source`, `event_time`, `deadline`, `currency`, `currency_exponent`, `value_minor` (bigint, above 0), `status`, `reason`, `rejection_class`, `attempts`, `retries`, `requeues` (0-3), `not_before`, `lease_expires_at`, `consent_basis` (consent record IDs), `policy_version`, the sealed payload (`kek_id`, `wrap_nonce`, `wrapped_dek`, `nonce`, `ciphertext`), `created_at`, `updated_at`, `delivered_at`, `ended_at`. Checks: closed statuses and reasons; `rejection_class` set exactly for `rejected` and `dismissed`; the payload present exactly while `ended_at` is null; `deadline > event_time`.

**Delivery key (D9 as amended by D-065).** The partial unique index `uq_conversion_deliveries_event` on (`client_id`, `event_id`) covers every delivery except one with `status = 'cancelled' AND attempts = 0 AND reason IN ('destination_disabled', 'connection_ended')`, which never reached Meta. Because the event ID is derived from the client, the dataset and the sale (section 5.3), a sale reaches a dataset at most once, through any destination or connection of that dataset. Ended deliveries are deleted 30 days after they end (section 5.6), longer than the 7-day age limit after which a sale is refused as `too_old`, so the key holds for as long as a sale can be enqueued. Review finding R014-01 replaced the earlier unique key on (`destination_id`, `event_id`), which let a reconnection or a rotation of the auth secret deliver a sale twice; `0018` was amended in place, as only disposable databases had applied it.

**`conversion_acknowledgements`**: `delivery_id`, `attempt`, `occurred_at`, `outcome` (`accepted`, `count_mismatch`, `retryable`, `rate_limited`, `unauthorized`, `configuration`, `payload`), `provider_code` (the adapter's closed code), `events_received`, `trace_id`. Unique (delivery, attempt).

Also: audit actions `destination.created`, `destination.updated`, `delivery.requeued` and `delivery.dismissed` with resources `destination` and `delivery`; providers admit `synthetic_meta_capi`.

**Privileges.** `tracking_app`: `SELECT, INSERT` on the three tables; `UPDATE (event_name, test_event_code, enabled, updated_at)` on destinations; on deliveries, `UPDATE` of the state, schedule, value, payload and time columns only (never the event ID, event time, deadline, consent basis or keys). No `DELETE`. `tracking_lifecycle`: `SELECT (id, ended_at)` and `DELETE` on deliveries; `SELECT (id, delivery_id)` and `DELETE` on acknowledgements.

**Downgrade.** Refuses while any destination, delivery, acknowledgement, `synthetic_meta_capi` row or new audit action exists.

### 5.3 States, enqueue and worker

```
            enqueue (E4 passed)
                  |
                  v
   +---------> queued ---- disable / connection ended / sale reversed ----> cancelled
   |              |  \---- deadline passed ------------------------------> expired
   |    claim: E5 |  \---- E5 denied --------------------------------------> blocked
   |              v
   |          sending --- events_received = 1 ----------------------------> delivered
   |              |------ retryable (5 attempts in the cycle) ------------> undeliverable
   +-- retry -----|------ invalid token: connection reconnect_required, the delivery waits
   |              |------ permission or dataset --> rejected (configuration)
   |              \------ invalid parameter ------> rejected (payload)
   |
   +---- requeue (Owner or Admin, at most 3, same event ID) <-- rejected (configuration)
         dismiss (Owner or Admin): rejected or undeliverable --> dismissed
```

Closed reasons:
- `blocked`: `consent_unknown`, `consent_denied`, `consent_withdrawn`, `consent_expired`, `subject_deleted`, `subject_unknown`, `subject_objected`, `no_consent_after_deletion`, `replay_before_deletion`;
- `cancelled`: `destination_disabled`, `connection_ended`, `sale_reversed`;
- `expired`: `deadline_passed`;
- `rejected`: `permission_missing`, `dataset_unavailable`, `invalid_parameter`, `invalid_event`;
- `undeliverable`: `retries_exhausted`;
- `queued` after a failure: `retryable`, `rate_limited`, `count_mismatch`, `invalid_token`.

**Conversion source (D6, D8).** `candidates_from_ledger(ledger, journeys)` and `candidates_from_feed(items, journeys)` turn the posted 007-A transactions, or the closing sale states of a `ledger_feed` journal, into candidates: the sale state (authoritative instant, verified net in minor units and currency) and the sale's evidence classes. A synthetic journey adds the person, the collection subjects (`subject_ref`, the subject token digest), the click identifiers (the `fbclid` with its first receipt time and its 004 event ID) and the sale's action source. There is no enqueue route; the 007-B journal replaces this source later.

**Enqueue (`enqueue_conversions`, E4).** For each candidate and each enabled destination of its client, in this order:
1. Only a sale whose evidence is a confirmed capture or settlement (`not_verified` otherwise).
2. A net of zero is not enqueued (`sale_reversed`).
3. The event is younger than the deadline (`too_old`).
4. An `fbc` exists: the latest click received at or before the sale (`no_match_key` otherwise).
5. The action source's required fields exist (`provider_field_missing` for `website`).
6. The value fits the exact range (`value_out_of_range`).
7. Under the client's privacy lock (004), `admission` with the subject and replay tombstones, and `require_all({ads.measurement, sale_or_share})` for every subject. GPC denies both purposes.

**Event ID (D9 as amended by D-065).** The SHA-256 hex digest of the length-prefixed encoding (4-byte big-endian length, then the UTF-8 bytes) of the domain `conversion-event:v2`, the client ID, the dataset ID (the delivery connection's external account at enqueue), the source account and the sale operation. It uses no destination, connection or secret, so a reconnection, a new destination or a rotation of `TRACKING_AUTH_SECRET` gives the sale the same ID in the same dataset, and Meta's deduplication applies to every send of it. The ID is not a secret, but it is never returned by a route or written to a log.

**Existing deliveries.** Before the checks, the enqueue looks for a delivery of the same client and event ID that holds the key (section 5.2), under the client's privacy lock. If it belongs to the current destination and is still waiting (`queued`, or `rejected` with the `configuration` class), it follows the sale: a changed net updates its value and a net of zero cancels it (`sale_reversed`). Any other existing delivery, including one of another destination of the same dataset or of an earlier connection to it, leaves the outcome `unchanged`. A delivery cancelled before any attempt because its destination was disabled or its connection ended does not hold the key, so the sale may be enqueued again through the re-enabled destination or a new destination of the same dataset, with the same event ID.

A refusal stores nothing and is counted in the returned counts. An admitted candidate inserts the delivery with its deterministic event ID, the consent basis (the latest record IDs of both purposes for every subject), the policy version and the sealed payload. The payload holds `fbc`, the subject references and the replay keys; it is sealed under the D-025 keyring with the delivery as its context. A repeated enqueue is otherwise a no-op. A delivered sale is never resent, through any destination; a later refund is not sent (V-11).

**Worker (`run_deliveries`, in `python -m app.connector_worker`).**
- It first expires overdue deliveries, which needs no key and destroys their payloads.
- Claims need both the token keyring (payloads and access tokens) and the tombstone keyring (E5). When a delivery provider is registered but either keyring is not configured, the step claims nothing and reports `not_configured` with the expired count, and the command still exits 0 with every step's counts (R014-02).
- It then claims at most `limit` deliveries. A claim takes a queued delivery that is due, or a sending delivery whose lease expired, of an enabled destination, an active delivery connection and an active agency and client, `FOR UPDATE SKIP LOCKED`.
- In the same transaction it takes the client's privacy lock and repeats E5 from the payload's subject references and replay keys. A denial makes the delivery `blocked` and destroys the payload. Otherwise it increments `attempts`, sets a 2-minute lease and opens the connection's token.
- The event is validated locally and sent with no lock held.
- The result is written only while the delivery is still `sending` under the same attempt; a superseded attempt writes nothing.
- Each attempt stores an acknowledgement.
- Retry delays are 30 seconds doubling to 15 minutes, or the provider's wait. A retry that would start after the deadline expires the delivery instead.
- The step prints counts only.

### 5.4 Error mapping

| Answer | Synthetic code | Live (V-13) | Result |
|---|---|---|---|
| Accepted, `events_received` = 1 | - | HTTP 200 | `delivered` |
| Accepted, other count | - | HTTP 200 | retry (`count_mismatch`) |
| Temporary | HTTP 5xx | 1, 2, HTTP 5xx, network | retry (`retryable`) |
| Throttled | 80000 / 429 | 4, 17, 32, 613, 80000-80004, 80009, 80014, HTTP 429 | retry (`rate_limited`) with the provider's wait |
| Invalid token | 190 | 190, HTTP 401 | the connection becomes `reconnect_required`; the delivery waits |
| Missing permission | 200 | 10, 200-299, HTTP 403 | `rejected` / `configuration` (`permission_missing`) |
| Unknown dataset | 100/33 | 100 with subcode 33 | `rejected` / `configuration` (`dataset_unavailable`) |
| Invalid parameter or old event | 100 | other 100, other 4xx | `rejected` / `payload` (`invalid_parameter`) |

Spend reads map the same way, as 009 kinds: throttling is `rate_limited`, a token error is `unauthorized`, a permission error is `forbidden`, a temporary error is `retryable`, and the rest is `permanent`.

### 5.5 Routes (D10)

| Route | Permission | Answer |
|---|---|---|
| `POST .../conversion-destinations` | Owner or Admin session; audit `destination.created` | The destination, disabled |
| `GET .../conversion-destinations` | `client:read` | Destinations with status, event name, test event code and enabled flag; no amounts |
| `PATCH .../conversion-destinations/{id}` | Owner or Admin session; audit `destination.updated` | The destination; disabling cancels its open deliveries |
| `GET .../conversion-deliveries` | `finance:read` | Deliveries with status, reason, class, value, currency, attempts and times |
| `POST .../conversion-deliveries/{id}/requeue` | Owner or Admin session; audit `delivery.requeued` | The delivery |
| `POST .../conversion-deliveries/{id}/dismiss` | Owner or Admin session; audit `delivery.dismissed` | The delivery |

No answer or log contains `fbc`, `fbclid`, a payload, the event ID or a provider trace ID. Ingest keys have no access, and read keys follow their grants.

### 5.6 Lifecycle (D13)

`python -m app.lifecycle` deletes, as `tracking_lifecycle`:
- acknowledgements, then deliveries, 30 days after the delivery ended;
- spend facts 730 days after their spend date.

## 6. 014-D: live adapters

`app/connectors/meta_ads.py` provides `MetaAdsProvider` (`meta_ads`) and `MetaCapiProvider` (`meta_capi`) over the standard library, with Graph `v27.0`:
- **Authorization.** `https://www.facebook.com/v27.0/dialog/oauth` with `client_id`, `redirect_uri`, `state`, `config_id`, `response_type=code` and `override_default_response_type=true`.
- **Exchange.** `GET /v27.0/oauth/access_token` with the redirect URI, then `GET /v27.0/debug_token` with the app token (`<app id>|<app secret>`) for the granted permissions. The token has no expiry and no refresh.
- **Accounts.** `GET /act_<id>?fields=id,name,currency,timezone_name,account_status`, or `GET /<dataset>?fields=id,name`.
- **Reads.** `/act_<id>/campaigns`, `/adsets` and `/ads` with their status and parent fields, and `/act_<id>/insights` with `level=ad`, `time_increment=1`, `time_range` and the fields of V-1.
- **Sending.** `POST /<dataset>/events` with `data` (one event) and `test_event_code`. `user_data` holds `fbc` only, unhashed, and no other D8 field is sent.
- **Settings.** `TRACKING_CONNECTOR_META_ADS_ENABLED` (false), `TRACKING_META_ADS_APP_ID` (digits), `TRACKING_META_ADS_APP_SECRET` (not blank) and `TRACKING_META_ADS_CONFIG_ID` (digits).
- **Registration.** Both adapters are registered only when enabled and configured and when their rules are current: `meta_ads` needs `meta.platform_data` and `meta.marketing_api`, and `meta_capi` needs `meta.platform_data` and `meta.conversions_api`.
- **Migration.** `0019_meta_providers` admits `meta_ads` and `meta_capi`. Its downgrade refuses any row of either.

## 7. Tests

The integration cases run on the disposable service; the unit cases need no database. (M) marks a mutation check (section 8).

| Case | Test |
|---|---|
| T-01 (M) | `tests/integration/test_ad_spend.py::test_rereading_a_window_keeps_facts_and_totals` |
| T-02 | `test_ad_spend.py::test_restated_value_replaces_the_old_one` |
| T-03 | `test_ad_spend.py::test_daylight_saving_days`, `tests/test_advertising_spend.py::test_local_day_windows` |
| T-04 (M) | `tests/test_advertising_spend.py::test_exponents_and_refusals`, `test_ad_spend.py::test_refused_amounts_are_not_stored` |
| T-05 (M) | `test_ad_spend.py::test_currency_change_keeps_earlier_facts` |
| T-06 | `test_ad_spend.py::test_deleted_and_archived_ads_keep_facts` |
| T-07 | `test_ad_spend.py::test_throttling_permission_and_token_errors` |
| T-08 | `test_ad_spend.py::test_unavailable_account_and_reconnect` |
| T-09 (M) | `test_ad_spend.py::test_spend_reads_need_finance_access` |
| T-10 | `test_ad_spend.py::test_disconnect_purges_spend` |
| T-20 (M) | `tests/integration/test_conversion_delivery.py::test_only_verified_sales_are_enqueued` |
| T-21 | `test_conversion_delivery.py::test_c2_measurement_denied` |
| T-22 | `test_conversion_delivery.py::test_sale_or_share_not_granted` |
| T-23 (M) | `test_conversion_delivery.py::test_c3_withdrawal_after_enqueue_blocks_at_claim` |
| T-24 | `test_conversion_delivery.py::test_c5_gpc_suppresses` |
| T-25 (M) | `test_conversion_delivery.py::test_tombstones_block_enqueue_claim_and_replay` |
| T-26 (M) | `test_conversion_delivery.py::test_repeated_enqueue_and_retry_keep_one_event` |
| T-27 (M) | `test_conversion_delivery.py::test_attempt_cap_and_deadline` |
| T-28 | `test_conversion_delivery.py::test_requeue_and_dismiss` |
| T-29 | `test_conversion_delivery.py::test_refunds_before_the_claim` |
| T-30 | `test_conversion_delivery.py::test_lease_fencing_and_crash_after_send` |
| T-31 | `test_conversion_delivery.py::test_invalid_token_waits_for_reconnection` |
| T-32 | `test_conversion_delivery.py::test_disabling_cancels_and_destroys` |
| T-33 | `test_conversion_delivery.py::test_test_event_code` |
| T-34 (M) | `test_conversion_delivery.py::test_isolation_and_no_identifiers_in_answers` |
| T-35 | `test_conversion_delivery.py::test_field_and_match_key_refusals` |
| T-40 to T-47 (M: T-41, T-43) | `tests/integration/test_roas.py`, with the pure cases in `tests/test_advertising_roas.py` |
| T-50 (M) | `tests/test_connector_meta.py::test_registration_needs_settings_and_current_rules` |
| T-51 | `tests/test_connector_meta.py` (Insights parsing, request building, answers, errors, authorization and exchange) against `tests/meta_graph.py` |
| T-52 | `tests/test_connector_meta.py::test_delivery_scope_required`, `tests/integration/test_conversion_delivery.py::test_delivery_connect_needs_ads_read` |
| T-53 | `tests/test_connector_meta.py::test_suite_makes_no_network_call` |
| R014-01 (M), D-065 | `test_conversion_delivery.py::test_reconnection_never_delivers_a_sale_twice`, `::test_secret_rotation_never_delivers_a_sale_twice`, `::test_sale_cancelled_before_any_attempt_is_enqueued_again_with_its_event_id`, `test_ad_migrations.py::test_0018_one_delivery_per_client_and_event_id`, `tests/test_delivery_rules.py::test_event_id_depends_only_on_client_dataset_and_sale` |
| R014-02 (M) | `tests/integration/test_connectors.py::test_worker_command_without_the_tombstone_keyring_reports_not_configured`, `::test_disconnect_through_worker_command_isolates_other_clients` (both keyrings set explicitly), `tests/test_delivery_rules.py::test_delivery_step_without_a_keyring_reports_not_configured` |

The migration tests (`tests/integration/test_ad_migrations.py`) cover each upgrade, each refused downgrade and the privileges. The existing data-policy schema test covers the registry of every new table and column.

## 8. Mutation checks

Each safeguard is disabled in turn, its tests are rerun, and the source is restored byte for byte, as in 009 to 011:
1. The unique fact key (the conflict target becomes an insert): T-01.
2. Exact parsing (a rounding parse): T-04.
3. The per-currency totals (totals summed across currencies): T-05.
4. The `finance:read` check on the spend route (`client:read`): T-09.
5. The verified-evidence check at enqueue: T-20.
6. The E5 recheck at the claim: T-23.
7. The tombstone admission at enqueue and claim: T-25.
8. The conflict-free insert of a repeated enqueue: T-26.
9. The attempt cap and the deadline: T-27.
10. The `finance:read` check on the delivery list: T-34.
11. The zero-spend rule and the currency rule of ROAS: T-41, T-43.
12. The rule check in `build_providers`: T-50.
13. The per-destination delivery key of `f00d997` (lookup and unique key by destination): R014-01 (a) and (d).
14. The auth secret in the event ID: R014-01 (b).
15. The `not_configured` guard of the delivery step: R014-02.
