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
