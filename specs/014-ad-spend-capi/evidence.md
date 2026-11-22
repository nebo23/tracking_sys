# Specification 014 evidence

Branch `codex/spec-014-ad-spend-capi`, created from `a52d2fb` (the D-063 and D-064 preparation on top of merged `main` at `6283935`). Authority: D-063 and D-064, decisions D1-D14 of the [entry review](entry-review.md) as recommended. Design: [design-014.md](design-014.md).

No live Meta call was made, nothing was sent to Meta, and no Meta app, business, ad account or dataset was created or changed. Phase 0 read public documentation pages only. Every migration ran on the disposable PostgreSQL 18 service of `backend/tests/README.md` (Compose project `tracking-014-test`, `127.0.0.1:55433`), never on the native `tracking_sys`. No dependency was added and no frontend file changed.

## Baseline

At `a52d2fb`, in the worktree `.worktrees/spec-014-ad-spend-capi` with the project `.venv` (Python 3.12.4):
- unit suite: 608 passed, 346 deselected;
- integration suite on the disposable service: 343 passed and 3 skipped (the browser journeys, which need `TRACKING_RUN_BROWSER_TESTS=1`).

## Phase 0: sources

[Entry review section 2.4](entry-review.md#24-official-sources-read-in-phase-0) lists every page read on 2026-11-20 and 2026-11-21, with the result for V-1 to V-18. In summary:
- **Confirmed:** V-1, V-2, V-4 to V-6 and V-9 to V-12, V-16 to V-18.
- **Corrected at parameter level:** V-7 (Login for Business tokens do not expire, and no callbacks or revocation endpoint are documented), V-8 (one invalid event no longer fails a whole batch) and V-14 (the delivery permission is `ads_read`).
- **Partly read:** V-13 and V-15; their dedicated pages answer 404.
- **Not stated:** V-3.

No fact changes D1-D14. The design note applies the parameters (section 1).

## 014-A: spend ingestion

**Scope (D2 to D5, D13, D14).**
- The synthetic `synthetic_meta_ads` provider.
- The named ad account of a connect, described after the exchange (`account_unavailable` otherwise).
- Per-connection day zones from the account.
- The `account`, `ad_objects` and `ad_daily` streams, stored in `ad_accounts`, `ad_objects` and `ad_spend_facts` under the checkpoint's fence.
- The 28-day provisional re-read, exact minor units with the `unparseable_amount` and `unsupported_currency` refusals, no zero rows, and facts kept when a later read omits them.
- The spend route (`finance:read`), the purge at disconnect, the 730-day lifecycle deletion, and migration `0017_ad_spend`.

**Tests.**
- `tests/integration/test_ad_spend.py`: T-01 to T-10, plus the connect case.
- `tests/integration/test_ad_migrations.py`: the `0017` privileges, its refused and empty downgrades, and the 730-day lifecycle deletion.
- `tests/test_advertising_spend.py`: the parsing table and the currency table (T-04), local-day windows across the 2026-11-01 New York change (25 hours) and the 2026-10-04 Sydney change (23 hours) (T-03), the 7-day windows, the cursor and the Login for Business request.

Existing expectations updated: the synthetic registry set (`test_connector_contracts.py`), the table counts (`test_data_policy.py`, `test_data_policy_schema.py`) and the approved rules.

**Verification of 014-A** (from `backend/` with the project `.venv`, 2026-11-21):

| Check | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | Clean (163 files) |
| Unit suite (`pytest -m "not integration"`) | 638 passed, 361 deselected |
| Integration suite on the disposable service (`run_db.py`, `pytest -m integration`) | 358 passed, 3 skipped (the browser journeys), 638 deselected |
| OpenAPI snapshot (`tests/test_contract.py`) | Regenerated in `contracts/openapi.json`; passing |

The first full integration run of 014-A found five failures, all expectations of the previous head: the synthetic registry set (`test_connector_instagram_login.py`), the head revision after a refused downgrade (`test_connector_youtube_live.py`, which now compares with the head it read), and the known table list of the migration cycle (`test_postgres.py`). They were updated and the suite reran clean.

**Mutation checks of 014-A.** Each safeguard was disabled in turn, its tests rerun on the disposable service, and every source restored byte for byte (SHA-256 compared). The migration mutation downgraded the disposable database to `0016` before and after the run.

| Safeguard (case) | Mutation | Result |
|---|---|---|
| Unique fact key (T-01) | The key of `0017` also covers the row ID | Caught: `test_rereading_a_window_keeps_facts_and_totals` |
| Exact parsing (T-04) | A rounding parse instead of `Money.parse` | Caught: 6 parametrized refusal cases and `test_refused_amounts_are_not_stored` |
| Per-currency totals (T-05) | Totals summed into the first currency | Caught: `test_currency_change_keeps_earlier_facts` |
| `finance:read` on the spend route (T-09) | `client:read` in the route and the service | Caught: `test_spend_reads_need_finance_access` |

Caught 4 of 4.

## 014-B: conversion delivery

**Scope (D6 to D10, D13, D14).**
- **Synthetic receiver.** `synthetic_meta_capi`, with the documented validation, `events_received`, deduplication by dataset, event name and event ID within 48 hours, and test events kept apart.
- **Delivery connections.** One per dataset, requiring `ads_read` (V-14) and never synchronized.
- **Destinations.** Disabled by default; Owner and Admin create, enable, disable and rename them, each with an audit event.
- **Conversion source.** `candidates_from_ledger` and `candidates_from_feed` read the 007-A ledger, plus synthetic journeys.
- **Enqueue.** E4 under the client's privacy lock: verified evidence, a net above zero, the deadline, the `fbc` match key, the action-source fields (website refused as `provider_field_missing`, V-9), replay and subject tombstones through `admission`, and `ads.measurement` with `sale_or_share`.
- **Outbox.** Deterministic event IDs, the consent basis and policy version, and a sealed payload destroyed when the delivery ends.
- **Worker step.** E5 in the claiming transaction (`FOR UPDATE SKIP LOCKED`), a 2-minute lease and attempt fence, and acknowledgements per attempt. Retries are capped at 5 attempts with a 30-second to 15-minute backoff, and the deadline is the age limit less 1 hour. Configuration rejections can be requeued at most 3 times; payload rejections can only be dismissed. An invalid token makes the connection `reconnect_required` and the delivery waits.
- **Teardown and lifecycle.** The teardown cancels the connection's deliveries and disables its destination. The lifecycle runner deletes ended deliveries and their acknowledgements after 30 days.
- **Routes and migration.** The destination and delivery routes, and migration `0018_conversion_delivery`.

**Tests.**
- `tests/integration/test_conversion_delivery.py`: T-20 to T-35, T-52 and the disconnect case. Consent records, events and erasure go through the 004 API, so C2 (T-21), C3 (T-23), C5 (T-24) and outbound replay blocking (T-25) run end to end on the disposable service.
- `tests/integration/test_ad_migrations.py`: the `0018` privileges, its refused downgrade and the 30-day lifecycle deletion.
- `tests/test_delivery_rules.py`: the `fbc` format, the deadline, the refusal order, the error classes and the synthetic receiver.

Existing expectations updated: the registry sets, the table counts and approved rules, the known tables of the migration cycle, and the worker command's output, which now includes the delivery step (`test_connectors.py`).

Fixed during verification: the lifecycle predicate first read `EXISTS (SELECT * ...)`, which the column-limited lifecycle role may not run. It now selects only `delivery_id`, and the role keeps its minimal privileges.

**Verification of 014-B** (2026-11-21):

| Check | Result |
|---|---|
| Ruff check and format | Clean (170 files) |
| Unit suite | 671 passed, 382 deselected |
| Integration suite on the disposable service | 378 passed, 3 skipped, 1 failed; the failure was the worker command's output expectation, updated and rerun: passed. 379 passed, 3 skipped in total |
| OpenAPI snapshot | Regenerated; passing |

**Mutation checks of 014-B.**

| Safeguard (case) | Mutation | Result |
|---|---|---|
| Verified evidence at enqueue (T-20) | Check removed | Caught: `test_only_verified_sales_are_enqueued` and 3 refusal-order cases |
| E5 recheck at the claim (T-23) | Recheck skipped | Caught: `test_c3_withdrawal_after_enqueue_blocks_at_claim` |
| Replay tombstones (T-25) | Ignored | Caught: `test_tombstones_block_enqueue_claim_and_replay` |
| Deterministic event ID (T-26) | A random part added | Caught: `test_repeated_enqueue_and_retry_keep_one_event` |
| Attempt cap (T-27) | Raised to 50 | Caught: `test_attempt_cap_and_deadline` |
| Deadline of a retry (T-27) | Ignored | Caught: `test_attempt_cap_and_deadline` |
| `finance:read` on the delivery list (T-34) | `client:read` in the route and the service | Caught: `test_isolation_and_no_identifiers_in_answers` |

Caught 7 of 7.

## 014-C: ROAS contract

**Scope (D11).** `app/advertising/roas.py` is a pure contract with no route. For one client, one spend connection, a period of account-local dates and one 008-A model version:
- It returns rows per ad, ad set and campaign, each naming its model, version, window, period, currency and the `conversion_date` basis.
- Revenue is the verified net credited to touches that carry Meta's dynamic URL parameters (`source` `meta`, the campaign ID and the ad ID, V-18). Credit of any other touch, or for another account's ad, is reported as unmatched per currency; names never join.
- ROAS is an exact fraction with a 4-decimal string. Zero spend has no value (`zero_spend`), and spend or credit in more than one currency has none either (`currency_mismatch`). Spend without credit gives 0.
- Each row's spend is marked `complete`, `provisional` or `incomplete`.
- Runs of another model version or client are refused.

**Tests.**
- `tests/test_advertising_roas.py`: T-40 to T-47 with constructed facts and real 008-A runs on 007-A transactions.
- `tests/integration/test_roas.py`: the same cases over spend facts stored by the 014-A synthetic sync and read back from `ad_spend_facts` on the disposable service, under each of First Click, Last Click and Linear. The spend lab of `test_ad_spend.py` became a shared builder (`make_ads_lab`).

**Verification of 014-C** (2026-11-21):
- ruff clean;
- unit suite: 680 passed;
- `tests/integration/test_roas.py` and `tests/integration/test_ad_spend.py`: 14 passed.

The full integration suite runs again with 014-D and in Phase 6.

**Mutation checks of 014-C.**

| Safeguard (case) | Mutation | Result |
|---|---|---|
| Zero-spend rule (T-41) | Removed | Caught: `test_zero_spend_has_no_value` and `test_zero_spend_currency_mismatch_and_spend_states` |
| Currency rule (T-43) | Removed | Caught: `test_currency_mismatch_has_no_value` and `test_zero_spend_currency_mismatch_and_spend_states` |

Caught 2 of 2.

## 014-D: live adapters with fixture tests

**Scope (D12, D14).** `app/connectors/meta_ads.py` provides `MetaAdsProvider` (`meta_ads`) and `MetaCapiProvider` (`meta_capi`) over the standard library, with Graph API `v27.0` (V-17):
- **Authorization.** The Facebook Login for Business dialog with the configuration ID, `response_type=code` and `override_default_response_type=true`, and no `scope` (V-7). The code exchange is followed by `debug_token` with the app token, and the granted permissions are recorded.
- **Tokens.** No expiry and no refresh. Revocation is `unsupported`, and no signed requests are declared (V-7).
- **Spend reads.** The ad account node, the campaigns, ad sets and ads edges with `cursors.after`, and daily ad-level insights in windows of at most 7 days (V-1 to V-5).
- **Delivery.** The Conversions API sender sends one event per request with `user_data` = `{fbc}` only, never hashed, and strips any field outside D8 (V-8 to V-12).
- **Error mapping.** That of V-6 and V-13. A usage header at 90 percent or more defers the run before Meta throttles.
- **Settings.** `TRACKING_CONNECTOR_META_ADS_ENABLED` (default false), `TRACKING_META_ADS_APP_ID`, `TRACKING_META_ADS_APP_SECRET` and `TRACKING_META_ADS_CONFIG_ID`. When enabled, they require a numeric app ID, a non-blank secret and a numeric configuration ID, separate from the Instagram settings. They are listed blank in `.env.example`.
- **Rules.** `meta.conversions_api` is re-verified, and `meta.marketing_api` (data class `advertising.spend`, registered in `app.data_policy`) is added. Both were verified on 2026-11-20 against the pages of section 2.4, with the review due 2027-11-20. `LIVE_RULES` requires `meta.platform_data` with `meta.marketing_api` for `meta_ads`, and with `meta.conversions_api` for `meta_capi`.
- **Migration.** `0019_meta_providers` admits both providers; its downgrade refuses their state.

**Tests.**
- `tests/test_connector_meta.py` against the in-memory Graph `tests/meta_graph.py`:
  - T-50: registration needs the setting, the configuration and current rules; a stale or overdue rule removes the adapter.
  - T-51: the authorization URL, the exchange with `debug_token`, the account and inventory pages, insights parsing (decimal strings, local days, windows, cursors), eleven error classes, the usage-header deferral, and Conversions API request building (no field outside D8, `fbc` unhashed, the test event code).
  - T-52: `ads_read` is required and nothing more is asked.
  - T-53: an autouse guard fails any socket or `urlopen` use, and the default transport is shown to be the only network path.
- `tests/integration/test_ad_migrations.py`: the `0019` downgrade refusal for both providers.
- `test_privacy_secrets_restore.py`: updated for the two re-verified rows.

**Verification of 014-D** (2026-11-21):

| Check | Result |
|---|---|
| Ruff check and format | Clean |
| Unit suite | 700 passed, 385 deselected |
| Integration suite on the disposable service | 383 passed, 3 skipped (the browser journeys), 701 deselected; one pydantic `UnsupportedFieldAttributeWarning` from the existing 002 test `test_concurrent_invitation_acceptance_creates_one_membership`, unrelated to 014 |
| OpenAPI snapshot | Regenerated; passing |

**Mutation check of 014-D.** The rule check in `build_providers` was removed (`if True:`). Caught by `test_registration_needs_settings_and_current_rules`: 1 of 1.

## Phase 6: final verification

At `2b9c6d6`, whose backend tree is the one under review (the later records commit changes documentation only). From `backend/` with the project `.venv` on 2026-11-21:

```powershell
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m ruff format --check .
..\.venv\Scripts\python.exe -m pytest -m "not integration" -q
# Disposable PostgreSQL 18 (Compose project tracking-014-test on 127.0.0.1:55433), through a
# runner that drops inherited TRACKING_/PG/PYTHON variables and loads synthetic credentials:
python run_db.py . pytest -m integration -q -rs
python mutations_014.py a b c d   # from the worktree root
```

| Check | Result |
|---|---|
| Ruff check | All checks passed |
| Ruff format | 177 files already formatted |
| Unit suite | 701 passed, 386 deselected |
| Integration suite | 383 passed, 3 skipped (the Spec 005 browser journeys), 701 deselected; no failure and no warning |
| OpenAPI snapshot (`tests/test_contract.py`) | Passed; `contracts/openapi.json` includes the spend, destination and delivery routes |
| New regressions | All pass within the suites above. 014-A: 11 integration, 4 migration and lifecycle, and 30 unit cases. 014-B: 18 integration, 3 migration and lifecycle, and 33 unit cases. 014-C: 3 integration and 9 unit cases. 014-D: 21 unit cases and 1 migration case. |
| Mutation checks | Caught 14 of 14 (four of 014-A, seven of 014-B, two of 014-C, one of 014-D); every source restored byte for byte |

Skipped tests are reported as skipped, not as passed: the three browser journeys of Spec 005 need `TRACKING_RUN_BROWSER_TESTS=1` with installed browsers and are outside 014.

## Decisions and amendments

D1-D14 apply as approved by D-064, with the D9 delivery key amended by D-065 after Claude's review of PR 12 (see [Claude's review of PR 12 and the corrections](#claudes-review-of-pr-12-and-the-corrections-d-065)). No fact of Phase 0 changed a decision, so none went back to the owner. The parameter-level corrections applied (design note, section 1):
- **V-14.** The delivery permission is `ads_read`; the V-14 row of entry review section 2.3 assigns this to recording. The read and delivery separation of D2 therefore rests on separate connections and tokens, not on different permissions.
- **V-7.** Login for Business tokens have no refresh, so an invalid token makes a connection `reconnect_required` at once instead of after one refresh (T-07). No revocation endpoint and no callbacks are documented, so revocation is `unsupported` and no signed requests are declared.
- **V-9.** The consequence that D8 states applies: website conversions are refused as `provider_field_missing`.
- **V-8.** One invalid event no longer fails a whole batch; this does not affect D9, which sends one event per request.
- **V-2, V-4, V-5, V-6, V-10, V-17.** The currency allow-list, the 28-day provisional window, the 730-day backfill bound (D13), the throttling codes and wait, the `fbc` form and Graph `v27.0`.

## Claude's review of PR 12 and the corrections (D-065)

Claude reviewed PR 12 at `f00d997` on 2026-11-21 in an independent environment (Python 3.13, PostgreSQL 16.15). Its results there:
- ruff check and format: clean;
- unit suite: 700 passed, and the OpenAPI snapshot failed;
- integration suite: 381 passed, 3 skipped, and two failed: the PostgreSQL 18 version assertion of `test_postgres.py` and `test_disconnect_through_worker_command_isolates_other_clients` (R014-02).

**Environment notes.** Two of those failures come from that environment, not from Spec 014, and also fail at `main` there: the OpenAPI snapshot, because Python 3.13 renames the 413 and 422 phrases, and the PostgreSQL 18 version assertion of `test_postgres.py`. Nothing was changed for them. The corrections below were verified on the project environment (Python 3.12 `.venv`, PostgreSQL 18 disposable service).

D-065 (2026-11-21) authorized correcting the two findings with regressions that fail at `f00d997`, and amended the D9 delivery key. The handoff is in [review-corrections-prompt.md](review-corrections-prompt.md).

### R014-01: one sale could be counted twice in one dataset

At `f00d997` the event ID was an HMAC under `TRACKING_AUTH_SECRET` of the client, the destination and the sale. Deliveries were unique only on (`destination_id`, `event_id`). A reconnection of the same dataset makes a new connection and destination, and a rotation of the secret changes the HMAC. Either way, a repeated enqueue of a delivered sale (for example a partial refund within the 7 days) inserted and sent a second delivery with a new event ID. The synthetic receiver then counted the sale twice in dataset 880001, and Meta, which deduplicates identical event IDs only, would do the same (against AC3).

The correction (D9 as amended by D-065):
- **Event ID.** `event_id_of(client_id, dataset, source_account, operation)` is the SHA-256 hex digest of a length-prefixed encoding (4-byte big-endian length, then UTF-8) of `conversion-event:v2`, the client ID, the dataset ID (the delivery connection's account at enqueue), the source account and the sale operation. It uses no destination and no secret, and it is never returned by a route or logged.
- **Uniqueness.** Migration `0018`, amended in place on this unmerged branch, replaces the unique key on (`destination_id`, `event_id`) with the partial unique index `uq_conversion_deliveries_event` on (`client_id`, `event_id`). The index excludes only rows with `status = 'cancelled' AND attempts = 0 AND reason IN ('destination_disabled', 'connection_ended')`. The model declares the same index (`HOLDS_EVENT`).
- **Lookup.** The enqueue looks up a delivery of the same client and event ID with the same predicate, under the client's privacy lock. It follows it (`_follow`) only when it belongs to the current destination and is still waiting; otherwise the outcome is `unchanged`.
- **Cancelled before any attempt.** Such a sale may be enqueued again through the re-enabled destination or a new destination of the same dataset, with the same event ID.

### R014-02: the worker command failed without the tombstone keyring

At `f00d997` the worker command always ran the delivery step, and the step required the tombstone keyring whenever a delivery provider was registered, which the synthetic state always does. With the documented connector configuration (the token keyring only), `python -m app.connector_worker` exited 1 with `CollectionError: collection_not_configured`. This happened after the teardown, scheduling and sync work had committed, and the command printed no counts. The test passed in the original runs only because the runner's environment supplied `TRACKING_TOMBSTONE_KEYRING`.

The correction: when a delivery provider is registered but the token or tombstone keyring is not configured, `run_deliveries` still expires overdue deliveries (no key needed; their payloads are destroyed), claims nothing and returns the expired count with `"not_configured": 1`. The command exits 0 with every step's counts. The worker-command tests set both tombstone keyring variables explicitly, so they no longer depend on the developer's environment or `.env`. The [connector guide](../../docs/engineering/connectors.md) (Configuration) and the [advertising guide](../../docs/engineering/advertising.md) state that the delivery step needs both keyrings.

### Regressions

| Regression | Test | At `f00d997` | At the corrected head |
|---|---|---|---|
| 1. R014-01 (a), reconnection | `tests/integration/test_conversion_delivery.py::test_reconnection_never_delivers_a_sale_twice` | Failed: the repeated enqueue answered `{"queued": 1}`, not `{"unchanged": 1}`. A probe that continued past it got `{"delivered": 1}`, two delivery rows and two counted events in dataset 880001. | Passed: `{"unchanged": 1}`, also for a partial refund; the step sends nothing; one counted event |
| 2. R014-01 (b), rotation | `test_conversion_delivery.py::test_secret_rotation_never_delivers_a_sale_twice` | Failed: `{"queued": 1}`, not `{"unchanged": 1}`. The probe got `{"delivered": 1}`, two rows and two counted events. | Passed: `{"unchanged": 1}`, one row, one counted event |
| 3. R014-01 (c), cancelled before any attempt | `test_conversion_delivery.py::test_sale_cancelled_before_any_attempt_is_enqueued_again_with_its_event_id` | Failed: the new delivery's event ID differed from the cancelled row's | Passed: `{"queued": 1}` with the same event ID through the new destination and again through the re-enabled destination; one delivered and one counted event; a later enqueue is `unchanged` |
| 4. R014-01 (d), database constraint | `tests/integration/test_ad_migrations.py::test_0018_one_delivery_per_client_and_event_id` | Failed: `DID NOT RAISE IntegrityError`; a second delivery with the same event ID under another destination was accepted | Passed: refused for a delivered row and for rows cancelled after an attempt or as `sale_reversed`; accepted only after rows cancelled before any attempt with `destination_disabled` or `connection_ended` |
| 5. R014-02, blank tombstone keyring | `tests/integration/test_connectors.py::test_worker_command_without_the_tombstone_keyring_reports_not_configured` | Failed: exit 1 with `CollectionError: collection_not_configured` | Passed: exit 0 with `{"teardown": {"disconnected": 1}, "schedule": {}, "sync": {}, "delivery": {"not_configured": 1}}` |
| 5. R014-02, both keyrings set explicitly | `test_connectors.py::test_disconnect_through_worker_command_isolates_other_clients` | Passed (`"delivery": {}`), as expected: only the environment changed | Passed (`"delivery": {}`) |
| 5. R014-02, unit case | `tests/test_delivery_rules.py::test_delivery_step_without_a_keyring_reports_not_configured` | Failed: `CollectionError: collection_not_configured` | Passed: `{"not_configured": 1}`, with the expired count when there is one; nothing claimed |
| D-065 event ID, unit case | `tests/test_delivery_rules.py::test_event_id_depends_only_on_client_dataset_and_sale` | Failed: `TypeError` (the old signature takes the settings and the destination) | Passed |

At `f00d997` the regressions ran on a `git archive` checkout outside the repository, with the four changed test modules copied in, on a fresh disposable database migrated by that checkout. The two-count probe (`test_probe_r014_01.py`) existed only in that checkout. The database was then downgraded to `0016` with that checkout's migrations, so the corrected `0018` was applied for the runs below. The checkout was removed afterwards.

### Changed expectations

- `event_id_of(client_id, dataset, source_account, operation)` replaces `event_id_of(settings, client_id, destination_id, scope, operation)` (D-065); no earlier test called it directly.
- `test_disconnect_through_worker_command_isolates_other_clients` runs the command through the new helper `_worker_command`, which sets both tombstone keyring variables explicitly. Its expected output is unchanged (`"delivery": {}`).
- No other expectation changed.

### Commands and counts

From `backend/` with the project `.venv` (Python 3.12.4) on 2026-11-21:

```powershell
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m ruff format --check .
..\.venv\Scripts\python.exe -m pytest -m "not integration" -q
# Disposable PostgreSQL 18 (Compose project tracking-014-test on 127.0.0.1:56433, see the
# environment note below), through a runner that drops inherited TRACKING_/PG/PYTHON variables
# and loads synthetic credentials:
python run_db_56433.py . pytest -m integration -q -rs
python run_db_56433.py <f00d997 checkout>\backend pytest <the new regressions>
python mutations_d065.py   # from the worktree root
```

| Check | Result |
|---|---|
| Ruff check | All checks passed |
| Ruff format | 177 files already formatted |
| Unit suite | 703 passed, 391 deselected (701 before; two new cases) |
| Integration suite | 388 passed, 3 skipped (the Spec 005 browser journeys, which need `TRACKING_RUN_BROWSER_TESTS=1`), 703 deselected; no failure and no warning (383 before; five new cases) |
| OpenAPI snapshot (`tests/test_contract.py`) | Passed; `contracts/openapi.json` is unchanged, as no route changed |
| New regressions at `f00d997` | 7 of 8 failed with the reasons above; the explicit-keyring worker case passed there, as expected |
| New regressions at the corrected head | 8 of 8 passed |
| Mutation checks | Caught 3 of 3 (below); every source restored byte for byte |

**Environment note: the database port.** On 2026-11-21 Windows had reserved the TCP port range 55351-55450 (IPv4 and IPv6), which includes the documented port 55433, so Docker could not publish the disposable service there, and releasing the reservation needs administrator rights. With the owner's instruction to complete the work, the same disposable PostgreSQL 18 service (database `tracking_foundation_test` on `127.0.0.1`, synthetic credentials) ran on port 56433. Only during the runs, the port number in the guard of `backend/tests/integration/conftest.py` (and of the `f00d997` checkout) was changed from 55433 to 56433. Afterwards the file was restored byte for byte: its SHA-256 (`336b8dd7...`) and its Git blob (`79c541a`) match the committed version, and this correction does not change it. The guard's purpose, that integration tests never reach the owner's native `tracking_sys`, was kept: only the disposable container listened on that port.

### Mutation checks

| Mutation | Regressions run | Result |
|---|---|---|
| The per-destination delivery key of `f00d997`: the lookup by destination, and `0018` unique on (`destination_id`, `event_id`); the database downgraded to `0016` before and after | 1 and 4 | Caught: both failed |
| The auth secret in the event ID (a keyed digest over the new ID) | 2 | Caught |
| The `not_configured` guard removed | 5 and its unit case | Caught: both failed |

### Review notes (follow-ups, unchanged)

- **N1.** The `system_generated` default of `SyntheticJourney.action_source`.
- **N2.** Absent `impressions` and `clicks` are stored as 0.
- **N3.** The fixed limit of 10 deliveries per worker pass.

## Limitations

- **Documentation only.** The live adapters are built from documentation and tested against an in-memory Graph. Details that no readable page settled stay unverified until 014-E:
  - whether insights at ad level include deleted or archived ads by default;
  - the dataset node read (`GET /<dataset>?fields=id,name`);
  - whether the business integration system user exchange accepts `redirect_uri` (the manual flow requires it; the Login for Business sample omits it);
  - the `events_received` and `fbtrace_id` answer fields, taken from the S-70 research;
  - Conversions API-specific error subcodes;
  - the exact layouts of the usage headers;
  - the numeric form of the configuration ID.
- **Website conversions** cannot be delivered until the owner decides how browser fields may be obtained (D8). Match rates with `fbc` alone will be low.
- **Conversion source.** It is the in-memory 007-A calculation or journal with synthetic journeys; 007-B and 006 replace it. Sale-level provider-object tombstones arrive with 007-B; replay blocking in 014 covers the subject tokens and the 004 event IDs a conversion references.
- **Event IDs and the delivery key (corrected under D-065).** A sale's event ID is derived only from the client, the dataset and the sale, and at most one delivery per client and event ID holds it. A reconnection of the dataset, a second destination of it or a rotation of `TRACKING_AUTH_SECRET` therefore never sends the sale to that dataset again, at any time: Meta deduplicates identical event IDs only within 48 hours (V-12), and the outbox prevents every later second send. The cost runs the other way. A delivery that ended without a confirmed send after at least one attempt (cancelled during or after an attempt, dismissed, undeliverable or expired) keeps the ID, so the sale is not sent to that dataset again and may be missing there. Only a delivery cancelled before any attempt because its destination was disabled or its connection ended releases the ID. A sale sent to two datasets has a different ID in each and is counted once in each. The earlier text of this limitation ("within 48 hours", "deliveries not yet enqueued") understated the defect that review finding R014-01 found.
- **Cancellation while sending.** A delivery cancelled while an attempt is in flight (a destination disabled, a connection torn down) may still reach Meta; that attempt's result is not recorded. It keeps its event ID, so the sale is never sent to the dataset a second time.
- **Age limit.** It is 7 days for every action source, although Meta advises up to 62 days for physical store events.
- **Values** are sent as JSON numbers, exact only below 10^15 minor units; larger values are refused at enqueue.
- **No routes for ROAS** (016), **no destination or account screens** (018, D-039), and **no production scheduling** of the worker (020).
- **No native migration.** `0017` to `0019` ran only on the disposable service; native `tracking_sys` has none of the migrations after `0004_identity`.

## Follow-ups

- **014-E.** A read-only live spend check with the owner's Meta app (Facebook Login for Business and the Marketing API) and an ad account the owner controls, confirming the unverified details above. A browser connect needs a registered HTTPS redirect (020) or an approved feasibility tool.
- **014-F.** Test events to an owner dataset with a test event code. This writes to Meta and needs its own approval.
- **014-G.** App Review for `ads_read`, Business Verification, Tech Provider status if required, the Data Use Checkup, and HTTPS hosting with the redirect (020). The client's authority as principal for the Business Tools Terms (V-16) belongs to that onboarding.
- **Owner decisions.** Browser fields for website events (D8, V-9), and email or phone match keys after 006.
- **Dependent work.** The 007-B journal as the persisted conversion source; ROAS read routes and reports (016); destination and account screens (018); production scheduling (020).
- **Later providers.** Google Ads, and LinkedIn Ads with Spec 012 when the owner resumes it.
- **Separate decisions.** Native `tracking_sys` migration (`0005` to `0019` and the lifecycle role) and deployment.

## Later correction (2026-11-22, D-069)
The [001-015 review](../../reports/specs-001-015-review-2026-11-22.md) found R010: the spend read grouped rows by object and currency but paged by object ID only, so an object with facts in two currencies (kept under D4) lost its second currency at `limit=1`. It is corrected in PR 13 with a cursor carrying the complete key (`<object ID>:<currency>`, an empty object ID when the level's ID is missing); see the [correction evidence](../015-business-integrations/review-corrections-evidence.md) and the [advertising guide](../../docs/engineering/advertising.md).
