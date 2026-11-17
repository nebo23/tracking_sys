# Spec 009 evidence

Sections below cover 009-A (D-048), its two correction rounds, 009-B to 009-D (D-049), and the [verification before merge with correction R009-11](#verification-before-merge-and-correction-r009-11-2026-11-17) (D-050), followed by the [acceptance summary](#spec-009-acceptance-summary).

## 009-A (2026-11-15)

Scope: D-048 (2026-11-15). Entry-review decisions D1-D10 with the [follow-up](entry-review-follow-up.md) clarifications at `54f733c`, implemented locally on `codex/spec-009-connector-runtime` against the synthetic provider. Not pushed. Native `tracking_sys` was not touched. No live provider was contacted. How each clarification was implemented is in [entry review section 9](entry-review.md#9-implementation-reconciliation-d-048).

## What changed

| Area | Files |
|---|---|
| Migration `0009_connector_runtime` (five tables, grants, audit constraints, guarded downgrade) | `backend/migrations/versions/0009_connector_runtime.py` |
| Models | `backend/app/models/connectors.py`, `backend/app/models/tenancy.py` (audit constraints), `backend/app/models/__init__.py` |
| Adapter contracts: Capability, ProviderError, TokenGrant, ProviderRecord, ConnectorProvider | `backend/app/connectors/contracts.py` |
| Synthetic provider (SQLite state shared across processes, S256 PKCE, single-use codes, per-grant revocation, injected failures) | `backend/app/connectors/synthetic.py` |
| Lifecycle service: authorization, callback, status, disconnect, sync worker, refresh, teardown | `backend/app/services/connectors.py` |
| Worker command | `backend/app/connector_worker.py` |
| Routes (7 operations; the API now has 82) | `backend/app/api/connectors.py`, `backend/app/main.py`, `contracts/openapi.json` |
| Settings, log event, data-class registry (`009-A`), lifecycle target | `backend/app/config.py`, `backend/app/logging_config.py`, `backend/app/data_policy.py`, `backend/app/services/lifecycle.py` |
| Tests | `backend/tests/integration/test_connectors.py` (12 cases), `backend/tests/test_connector_contracts.py` (7 cases), registry and guard updates |
| Documentation | D-048 in the [decision register](../../docs/planning/decisions.md) and `AGENTS.md`; [connector guide](../../docs/engineering/connectors.md); entry review, plan, tasks and spec status; migration notes; `.env.example` |

No dependency was added. The synthetic provider uses only the standard library `sqlite3`.

## Commands and results (2026-11-15)

Environment: project `.venv` at `C:\Code\Tracking-system\.venv` (Python 3.12). The disposable PostgreSQL 18.6 container is `tracking-system-foundation-test` on `127.0.0.1:55433` (`tracking_foundation_test`), started from `infra/docker/compose.yaml` with the ignored `.env.docker`, and recreated empty before the final runs. Commands run from `backend/` unless noted.

| Command | Result |
|---|---|
| Baseline before changes: `python -m pytest -m "not integration" -q` | 500 passed, 279 deselected |
| Baseline before changes: integration suite on the disposable database (`TRACKING_RUN_DB_TESTS=1`, `-m integration`) | 276 passed, 3 skipped (browser journey without `TRACKING_RUN_BROWSER_TESTS`) |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 120 files formatted |
| `python -m pytest -m "not integration" -q` | **507 passed**, 291 deselected |
| Integration suite, `-m integration -q`, three runs on the final code | **288 passed, 3 skipped** each time. The first run also reported one warning that did not recur in the next two runs (the second run used `-rw`); its text was not captured. |
| `python -m pytest -m integration -q tests/integration/test_connectors.py` | 12 passed |
| Mutation check: each of six safeguards disabled in turn, connector integration tests rerun, source restored | Every mutation was caught: generation fence (2 failures), grant disposal (3), finalize before deadline (1), reconnect generation check (1, after adding the stale-reconnect case), manager role recheck (1), claim-time client check (1) |
| `git diff --check` | No whitespace errors |

The 3 skipped cases are the Spec 005 Playwright journeys, which need `TRACKING_RUN_BROWSER_TESTS=1` and installed browsers; skipped is not passed. The 12 additional integration cases are the connector tests. Existing cases cover the 0009 migration cycle, model agreement, registry agreement and lifecycle targets.

## Acceptance mapping

| Case | Status | Test |
|---|---|---|
| AC1: state validation, replay rejection, PKCE, no tokens in browser or logs | Verified for the synthetic provider | `test_callback_replay_expiry_binding_and_concurrent_submission` (four concurrent submissions: one connection, one exchange), `test_connect_status_isolation_and_sync`, token search in `test_disconnect_through_worker_command_isolates_other_clients`, PKCE and single-use unit cases |
| AC2: expiry or revocation disconnects only the affected connection | Verified | `test_refresh_install_is_fenced_and_terminal_failure_requires_reconnect`, `test_reconnect_binding_mismatch_and_race_with_disconnect` |
| AC3 (`401` part): reconnection required | Verified | Same tests |
| 003 case D3: revoke at the provider, destroy ciphertext and wrapped keys, purge within the deadline, honest outcomes | Verified for the synthetic provider | `test_disconnect_through_worker_command_isolates_other_clients` (worker subprocess, K1 tokens unusable, K2 and K3 still served), `test_teardown_outcomes_with_controlled_clock` (transient, unsupported, failure through the deadline), `test_teardown_resumes_after_crash_and_records_late_completion` |
| Isolation across clients and agencies for one external account | Verified | K1 (A1), K2 (A2) and K3 (B1) share `syn-acct-777` in every case |
| Worker outlives the enqueue check (archive, suspension, role loss) | Verified | `test_disconnect_during_fetch_discards_results_and_archive_stops_writes`, `test_late_callback_after_role_loss_is_denied` |
| Privileges, scoped references, lifecycle cleanup, guarded downgrade | Verified | `test_runtime_privileges_scoped_references_and_lifecycle` |

## Open for independent review

- Still planned: AC3 backoff (`429` with `Retry-After`), `403`, retryable `5xx`, pagination, backfill, overlapping runs, and crash recovery at the page/checkpoint boundary (009-B). AC4 coverage and provenance states (009-C). Provider webhook verification (009-D). Q-001, Q-004, Q-009 and Q-010 remain open.
- The synthetic provider's per-grant revocation proves isolation only for that adapter. A live provider whose revocation invalidates a grant shared by several connections, rotates refresh tokens, or revokes single tokens needs its own handling, decided from dated evidence in 010-013.
- Known limits are recorded in [entry review section 9.4](entry-review.md#94-known-limits): an undisposable grant is only logged with its outcome code, and nothing runs the worker automatically. The reconnect limit was corrected by R009-01.
- An intermittent warning was seen once in three full integration runs and not identified.
- Not done, and needing separate approval: push, pull request, native `tracking_sys` migration and role rollout, live providers and deployment.

## Pre-publication corrections (2026-11-15)

Scope: the [independent review](pre-pr-review-2026-11-15.md) of `b21219f`, recorded at `d5bef79`, findings R009-01 to R009-07, corrected within D-048. No schema, migration, privilege or dependency changed. The corrections are described in [entry review section 9.5](entry-review.md#95-pre-publication-corrections-r009-01-to-r009-07).

| Finding | Regression test (`backend/tests/integration/test_connectors.py`) | Result on `b21219f` service code | After correction |
|---|---|---|---|
| R009-01 | `test_r009_01_reconnect_keeps_the_previous_grant_revocation_obligation` | Failed: the reconnect succeeded while the previous grant could not be revoked | Passed |
| R009-02 | `test_r009_02_superseded_sync_attempt_cannot_overwrite_its_replacement` | Failed: the delayed attempt reported `succeeded` and overwrote the replacement's result | Passed |
| R009-03 | `test_r009_03_stale_refresh_never_revokes_the_winning_grant` | Failed: the winning tokens were unusable at the provider | Passed |
| R009-04 | `test_r009_04_deadline_is_judged_at_completion_time` | Failed: completion recorded at the batch start, `deadline_met` true | Passed |
| R009-05 | `test_r009_05_actions_reflect_the_requesting_principal` | Failed: the analyst was offered `disconnect` | Passed |
| R009-06 | `test_r009_06_unresolved_grant_disposal_is_reported` | Failed: no disposal event for `unsupported` | Passed |
| R009-07 | `test_r009_07_a_retrying_teardown_does_not_starve_other_tenants` | Failed: the healthy connection stayed `disconnecting` after four passes | Passed |

Method: with the regression tests in place, the three corrected modules (`app/services/connectors.py`, `app/api/connectors.py`, `app/logging_config.py`) were temporarily checked out at `b21219f`. The seven regressions all failed, and the corrected files were then restored. The R009-02 test failed at its first scenario. Its later scenario, a stale attempt that has already refreshed and then receives `401`, is shown by the mutation check below.

| Command (from `backend/`, project `.venv`, disposable PostgreSQL 18.6 recreated empty at `127.0.0.1:55433`) | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 120 files formatted |
| `python -m pytest -m "not integration" -q` | **507 passed**, 298 deselected |
| `python -m pytest -m integration -q -rw`, two runs | **295 passed, 3 skipped** each time, no warnings. The 7 new cases are the regressions; the 3 skips are the opt-in Spec 005 browser journeys. |
| `python -m pytest -m integration -q tests/integration/test_connectors.py` | 19 passed |
| Mutation check: each new safeguard disabled in turn, connector tests rerun, source restored | All nine caught: settling the previous grant (R009-01), aggregating replaced versions (R009-01), attempt ownership (R009-02), the stale attempt's `reconnect_required` path (R009-02, after adding its scenario), disposal only on a generation change (R009-03, also the existing disconnect-race test), completion-time clock (R009-04), principal-aware actions (R009-05), unsupported disposal (R009-06) and fair teardown order (R009-07). |
| `git diff --check` | No whitespace errors |

Behavior change for review: a reconnect is now refused with `provider_unavailable` while the provider cannot confirm revocation of the previous grant. It succeeds once revocation is confirmed or reported unsupported. The alternative, keeping a separate outstanding obligation so the reconnect could proceed, would need a schema change and was not taken.

Still open: the items listed above for 009-B to 009-D, the live-provider revocation scope, and publication, native rollout and deployment.

## Correction review corrections (2026-11-17)

Scope: the [correction review](corrections-review-2026-11-15.md) of `2d0ac21`, recorded at `817a582`, findings R009-08 to R009-10, corrected within D-048. The application code at `817a582` is identical to `2d0ac21` (`git diff --quiet 2d0ac21 817a582 -- backend/app`). No schema, migration, privilege, dependency or public contract changed; the OpenAPI snapshot is unchanged. The corrections are described in [entry review section 9.6](entry-review.md#96-correction-review-corrections-r009-08-to-r009-10).

| Finding | Regression test (`backend/tests/integration/test_connectors.py`) | Result with the service code of `2d0ac21` | After correction |
|---|---|---|---|
| R009-08 | `test_r009_08_concurrent_reconnects_keep_the_winning_grant_usable`, two cases: the same Owner initiates both reconnects, and an Owner and an Admin initiate one each, so only the connection lock orders them | Both failed: the winning callback returned `reconnected` and the connection reported `active`, but the delayed callback had revoked the winning grant at the provider | Both passed: one callback installs, the other returns `connection_changed` and disposes only of its own grant; the installed tokens read a fresh page at the provider and the next worker sync succeeds |
| R009-09 | `test_r009_09_a_rejected_reconnect_keeps_the_original_grant`: account mismatch, an initiating Admin demoted to Analyst, an archived client, and a session that logged out before the callback | Failed at the first case: the original versions recorded `revocation = done` and the original grant was revoked | Passed: each rejection disposes of its new grant with no `connector_grant_disposal_failed` event, while the original grant still reads a page at the provider and its rows, statuses and recorded outcomes are unchanged; a valid reconnect then succeeds and only then revokes the original grant |
| R009-10 | `test_r009_10_completion_is_timed_after_the_purge`: on-time completion, late provider revocation, and late database cleanup with a controlled clock advanced when `DELETE FROM connector_records` executes | Failed at the late-cleanup case: `disconnected_at` was one second before the deadline and `deadline_met` true | Passed: records deleted, secrets destroyed, `purge_due_at` unchanged, `disconnected_at` equal to the clock reading after the purge, and `deadline_met` true, false and false respectively |

Each regression also checks that K2 (another client of the same agency sharing `syn-acct-777`) and K3 (a client of another agency with the same account) keep their tokens, remain usable at the provider and, where applicable, still synchronize. The regressions use independent database sessions and events or a controlled clock for ordering; the only polling waits for another thread to finish or to wait on a lock (`pg_locks ... NOT granted`), so no outcome depends on a delay.

Method: with the regression tests in place, `app/services/connectors.py` was temporarily replaced by its `2d0ac21` version, the four new cases were run and all failed as listed, and the corrected file was restored.

| Command (from `backend/`, project `.venv`, fresh disposable PostgreSQL 18.6 at `127.0.0.1:55433/tracking_foundation_test` with a synthetic environment file) | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 120 files formatted |
| `python -m pytest -m "not integration" -q` | **507 passed**, 302 deselected |
| `python -m pytest -m integration -q -rw` | **299 passed, 3 skipped**, 1 warning. The 3 skips are the opt-in Spec 005 browser journeys. The warning is Pydantic's `UnsupportedFieldAttributeWarning` for the `X-CSRF-Token` header alias of `browser_identity` in `app/api/dependencies.py` (Spec 002 code), emitted once per process; this identifies the intermittent warning noted for 009-A. |
| `python -m pytest -m integration -q tests/integration/test_connectors.py` | 23 passed |
| Mutation check: each new safeguard disabled in turn, the matching regression rerun, source restored | All three caught: no shared connection lock while settling (the Owner/Admin case of R009-08 failed; the same-Owner case is also ordered by the session's user lock), no authority and account check before revocation (R009-09), completion timed before the purge (R009-10) |
| `git diff --check` | No whitespace errors |

Remaining limits are unchanged from section 9.4 of the entry review. 009-B to 009-D remain subject to their own decisions.

## 009-B synchronization (2026-11-17)

Scope: D-049 decisions D11-D15 and D20 ([decision packet](decision-packet-009bcd.md)), implemented against the synthetic provider with migration `0010_connector_sync`. Implementation details settled during the work are in [packet section 6.1](decision-packet-009bcd.md#61-009-b-synchronization). No dependency was added. Native `tracking_sys` was not touched and no live provider was contacted.

| Area | Files |
|---|---|
| Migration (run kind, window, deferral, retries, pages; checkpoints; usage records; grants; guarded downgrade) | `backend/migrations/versions/0010_connector_sync.py` |
| Contracts (paged reads, call costs, provider quota, history and overlap) | `backend/app/connectors/contracts.py` |
| Synthetic provider (fixed-anchor data set, cursor pages, scripted `401`/`403`/`429`/`5xx`/permanent outcomes, read log) | `backend/app/connectors/synthetic.py` |
| Runtime (claims with `not_before`, attempt-fenced page and checkpoint writes, error policy, usage reservation and daily limits, scheduling, backfill requests, purge of checkpoints) | `backend/app/services/connectors.py`, `backend/app/connector_worker.py`, `backend/app/api/connectors.py`, `backend/app/config.py` |
| Models, registry (`009-B`), OpenAPI snapshot | `backend/app/models/connectors.py`, `backend/app/data_policy.py`, `contracts/openapi.json` |
| Tests | `backend/tests/integration/test_connector_sync.py` (8 cases), shared lab in `backend/tests/integration/connector_support.py`, updated registry and table guards |

| Command (from `backend/`, project `.venv`, disposable PostgreSQL 18.6 at `127.0.0.1:55433/tracking_foundation_test` with a synthetic environment file) | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 123 files formatted |
| `python -m pytest -m "not integration" -q` | **507 passed**, 310 deselected |
| `python -m pytest -m integration -q -rw` | **307 passed, 3 skipped**, no warnings. The skips are the opt-in Spec 005 browser journeys. |
| `python -m pytest -m integration -q tests/integration/test_connector_sync.py` | 8 passed |
| Model and migration agreement, registry against the migrated schema, migration cycle with grants | Passed (`test_migration_matches_model_metadata`, `test_migrated_schema_matches_registry`, `test_postgresql_migration_cycle_and_runtime_permissions`) |
| Mutation check: each 009-B safeguard disabled in turn, the 009-B tests rerun, source restored | All eight caught: resume ignoring the stored cursor (5 failures), claiming before `not_before` (2), no usage limits (1), no provider quota (1), unbounded retries (1), ignoring `Retry-After` (1), scheduling regardless of the interval (1), moving the watermark on every page (6) |
| `git diff --check` | No whitespace errors |

| Criterion | Test (`test_connector_sync.py`) | Result |
|---|---|---|
| Pagination, checkpoints, incremental overlap, backfill within the history limit, overlapping requests | `test_009b_pages_checkpoints_backfill_and_overlapping_requests` | Passed |
| AC3 crash recovery: a stop after a read, inside the page transaction, and after its commit; each resumes at the right page, stores every object once and counts every reserved call | `test_009b_restart_at_the_page_boundary_skips_and_duplicates_nothing` (3 cases) | Passed |
| AC3 `429` backoff (Retry-After honored and capped), retryable `5xx` backoff and the five-deferral limit, `403` and permanent failures, usage of failed calls | `test_009b_rate_limits_retries_forbidden_and_permanent_failures` | Passed |
| Usage accounting, connection allocation and provider quota stops, resumption on the next UTC day at the stored cursor | `test_009b_usage_accounting_and_budget_stops` | Passed |
| Scheduling of due connections only, skipping inactive clients, connections that require reconnection, and connections with an open run | `test_009b_scheduling_queues_due_connections_once` | Passed |
| Privileges, scoped checkpoint references, and the disconnect purge of checkpoints (003 case D3 extended) | `test_009b_privileges_scoped_references_and_disconnect_purge` | Passed |

Each 009-B test also keeps the other connections of the fixture working where it uses them: another client of the same agency and a client of another agency sharing `syn-acct-777`. The 23 connector cases of 009-A pass unchanged apart from the paged return type of the synthetic read and the `schedule` key of the worker command output.

Remaining for later slices: coverage and provenance reads (009-C) and provider webhooks (009-D). Commercial budgets (Q-004) and production scheduling and supervision (020) remain open.

## 009-C coverage and provenance (2026-11-17)

Scope: D-049 decisions D16, D17 and D20, implemented against the synthetic provider with migration `0011_connector_coverage`. Details settled during implementation are in [packet section 6.2](decision-packet-009bcd.md#62-009-c-coverage-and-provenance). No dependency was added.

| Area | Files |
|---|---|
| Migration (account kind, record source run and adapter version, scoped run key, grants, guarded downgrade) | `backend/migrations/versions/0011_connector_coverage.py` |
| Contracts (metric catalog with units and account kinds, freshness window, account kind on grants) and synthetic adapter `synthetic-3` (business and creator accounts, `saves` for business only) | `backend/app/connectors/contracts.py`, `backend/app/connectors/synthetic.py` |
| Coverage and record reads; provenance on stored records; account kind set at connect and reconnect and cleared by the purge | `backend/app/services/connector_coverage.py`, `backend/app/services/connectors.py`, `backend/app/api/connectors.py` |
| Models, registry (`009-C`), OpenAPI snapshot (now 84 operations) | `backend/app/models/connectors.py`, `backend/app/data_policy.py`, `contracts/openapi.json` |
| Tests | `backend/tests/integration/test_connector_coverage.py` |

| Command (from `backend/`, project `.venv`, disposable PostgreSQL 18.6 at `127.0.0.1:55433/tracking_foundation_test` with a synthetic environment file) | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 126 files formatted |
| `python -m pytest -m "not integration" -q` | **507 passed**, 311 deselected |
| `python -m pytest -m integration -q -rw` | **308 passed, 3 skipped**, no warnings (the opt-in Spec 005 browser journeys) |
| Connector, schema and migration agreement modules | 35 passed |
| Mutation check: each 009-C safeguard disabled in turn, the coverage test rerun, source restored | All six caught: a zero reported as missing, account-kind support ignored, records never stale, provider-wide usage in the cost block, a waiting run reported as queued, partial coverage reported as complete |
| `git diff --check` | No whitespace errors |

| Criterion | Evidence in `test_009c_coverage_and_metric_states` |
|---|---|
| AC4 metric availability | Before any sync every metric is `not_synced`; after a sync an engagements value of zero is `observed` with value 0 and `available`; an omitted impressions metric is `missing`; `saves` is `unsupported` for a creator account with a null value; values fetched two days earlier are `stale` with their values kept |
| AC4 last synchronization and historical coverage | `last_successful_sync_at`, `freshness`, and the stream's `covered_from` and `complete_through`; after a delayed backfill page the stream is `partial`, the watermarks are unchanged, and the stored first page is readable |
| AC4 cost state | Consumed, allocation and remaining for the connection's own UTC day; after a provider-quota stop the run is `budget_stopped` with the next attempt at the next UTC day and the cost is `exhausted` with `provider_quota`, without the provider-wide total; with a smaller allocation the reason is `connection_allocation` |
| Provenance | Each record names its provider, adapter version and source run; pages continue by provider object ID |
| Isolation | Members with client visibility and the analyst with a grant read coverage and records; another agency's owner and an analyst without a grant are refused |
| After disconnect | The purge leaves the account kind cleared, the stream `not_synced`, every metric `not_synced`, and no records |

## 009-D provider webhooks (2026-11-17)

Scope: D-049 decisions D18-D20, implemented against the synthetic provider with migration `0012_connector_webhooks`. Details settled during implementation are in [packet section 6.3](decision-packet-009bcd.md#63-009-d-provider-webhooks). No dependency was added; the synthetic adapter reuses `app.collection.contract.verify_webhook` and `sign_webhook` from Spec 004.

| Area | Files |
|---|---|
| Migration (delivery records, grants, lifecycle privilege, guarded downgrade) | `backend/migrations/versions/0012_connector_webhooks.py` |
| Contracts (`WebhookDelivery`, `WebhookRejected`, `verify_webhook`, Capability `webhooks`) and the synthetic sender and verifier | `backend/app/connectors/contracts.py`, `backend/app/connectors/synthetic.py` |
| Delivery handling, route, lifecycle target (7 days) | `backend/app/services/connector_webhooks.py`, `backend/app/api/connectors.py`, `backend/app/main.py`, `backend/app/services/lifecycle.py`, `backend/app/config.py` |
| Models, registry (`009-D`), OpenAPI snapshot (85 operations), lifecycle guide | `backend/app/models/connectors.py`, `backend/app/data_policy.py`, `contracts/openapi.json`, `docs/engineering/data-lifecycle.md` |
| Tests | `backend/tests/integration/test_connector_webhooks.py` (5 cases), updated registry and table guards |

| Command (from `backend/`, project `.venv`, disposable PostgreSQL 18.6 at `127.0.0.1:55433/tracking_foundation_test` with a synthetic environment file) | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 129 files formatted |
| `python -m pytest -m "not integration" -q` | **507 passed**, 316 deselected |
| `python -m pytest -m integration -q -rw` | **313 passed, 3 skipped**, no warnings (the opt-in Spec 005 browser journeys). This run covers the complete Spec 009 tree. |
| Webhook, registry and migration agreement modules | 7 passed |
| Mutation check: each 009-D safeguard disabled in turn, the webhook tests rerun, source restored | All five caught: repeats not recognized (2 failures), signature not verified, connections of any status notified, inactive clients notified, connections of any account notified |
| `git diff --check` | No whitespace errors |

| Criterion | Test (`test_connector_webhooks.py`) |
|---|---|
| A valid delivery has one scoped effect: one incremental run per active connection of the account, in its own agency and client; a delivery for an unconnected account gets the same answer and no effect; an open run is not duplicated | `test_009d_a_verified_delivery_has_one_scoped_effect_per_connection` |
| A repeated delivery, freshly signed, has no further effect, also when two arrive concurrently | the same test and `test_009d_concurrent_repeats_have_one_effect` |
| An invalid, tampered, foreign-secret, missing or expired signature, an unreadable verified body, an oversized body and an unknown provider cause no ingestion, and do not consume the event ID | `test_009d_refused_deliveries_cause_no_ingestion` |
| Tenant isolation and behavior after disconnect: archived clients, connections that require reconnection, disconnecting and disconnected connections receive nothing; a reactivated client receives again | `test_009d_deliveries_skip_inactive_connections_and_follow_disconnect` |
| Privileges and the 7-day lifecycle deletion | `test_009d_privileges_and_lifecycle` |

## Verification before merge and correction R009-11 (2026-11-17)

Scope: D-050. The owner asked for a check of every specification up to Spec 009, then the pull request and merge of Spec 009. The complete branch at `2be837e` (PR 8) was verified again on a fresh disposable database, and the 009-B to 009-D code, which had no independent review, was reviewed. One finding was corrected within the D-049 scope. No schema, migration, privilege, dependency, public contract or OpenAPI snapshot changed.

| Command on `2be837e` (from `backend/`, project `.venv`, fresh disposable PostgreSQL 18.6 at `127.0.0.1:55433/tracking_foundation_test` with a synthetic environment file) | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 129 files formatted |
| `python -m pytest -m "not integration" -q` | **507 passed**, 316 deselected |
| `python -m pytest -m integration -q -rw` | **313 passed, 3 skipped**, no warnings; the evidence counts above are reproduced |

**R009-11 (medium): a synchronization read the clock once per claim.** `run_syncs` read the time when it claimed a run and passed that value to every later step of the run. On the synthetic provider and in tests, where each worker pass uses one fixed time, this is invisible. With real time and a provider that answers slowly, three consequences follow:

1. A `429` (or retryable failure) later in a run set `not_before` from the claim time. When the run had already lasted longer than `Retry-After`, the deferral was already past, and the same worker pass claimed the run again at once, calling the provider without waiting (acceptance criterion 3).
2. Each stored page set `lease_expires_at` to the claim time plus five minutes, so the lease that D13 says each page renews never moved. A run lasting more than five minutes could be claimed by another pass while still working. The attempt fence keeps that safe, but the first attempt's in-flight call is wasted.
3. Fetch times, usage reservation and settlement times, and the UTC usage period were those of the claim, not of the calls.

A temporary reproduction run with a provider wrapper that took one second per read, with the worker using the real clock, showed the next read **1.04 s** after a `429` that asked for 2 s, in the same pass, and a lease still equal to the claim time plus 5 minutes after two stored pages.

Correction: `run_syncs` gives `_execute` and `_refresh` a clock, as `run_teardowns` already does, and each step reads it when it happens: the token expiry check, every reservation and settlement, every page write and its lease renewal, and every deferral, failure or reconnect decision. A fixed `now` (tests) still applies to every step, so the existing cases are unchanged.

| Regression (`backend/tests/integration/test_connector_sync.py`) | Result with the service code of `2be837e` | After correction |
|---|---|---|
| `test_r009_11_each_sync_step_reads_the_clock_when_it_happens`: a controlled clock advances two minutes per provider read; the third read answers `429` with `Retry-After: 300` | Failed: the pass reported `{"deferred": 1, "succeeded": 1}`, so the run was claimed again before its `Retry-After` had passed | Passed: the pass defers the run once, with `not_before` five minutes after the `429`; the lease seen before each read is the claim time plus 5 minutes, then the first and second page writes plus 5 minutes; record fetch times and usage times follow the calls; the run resumes at its cursor only at `not_before`; K2 and K3 synchronize again |

| Command after the correction (same environment) | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 129 files formatted |
| `python -m pytest -m "not integration" -q` | **507 passed**, 317 deselected |
| `python -m pytest -m integration -q -rw` | **314 passed, 3 skipped**, no warnings. The new case is the R009-11 regression; the skips are the opt-in Spec 005 browser journeys. |
| The same browser journeys with `TRACKING_RUN_BROWSER_TESTS=1` and the tracker's installed Playwright browsers: `python -m pytest -m integration -q tests/integration/test_tracker_journey.py` | **3 passed** (Chromium and Firefox), so no case of the suite is left unexercised |
| Mutation check: each half of the correction disabled in turn, the regression rerun, source restored | Both caught: a page write that does not renew the lease (the lease assertion failed) and a deferral counted from the time before the call (the `not_before` assertion failed) |
| `git diff --check` | No whitespace errors |

Status documents corrected in the same review: `README.md` and `docs/engineering/local-environment.md` named revision `0009_connector_runtime`, 39 tables and an 82-operation API, while the branch head is `0012_connector_webhooks` with 42 application tables and 85 operations.

Observation, not corrected: the coverage `cost.reason` reports `provider_quota` for a budget stop whenever the connection has spent less than its allocation. That holds while every call costs 1 unit, as for the synthetic adapter; an adapter with larger call costs needs the stop to record which limit applied (010-013).

## Spec 009 acceptance summary

Every case runs against the synthetic provider on disposable PostgreSQL. The named tests are in `backend/tests/integration/` unless stated.

| Criterion | Slice | Named tests |
|---|---|---|
| AC1: state validation, replay rejection, PKCE, no token exposure | 009-A | `test_connectors.py::test_callback_replay_expiry_binding_and_concurrent_submission`, `test_connect_status_isolation_and_sync`, the token search in `test_disconnect_through_worker_command_isolates_other_clients`, and `backend/tests/test_connector_contracts.py::test_exchange_requires_pkce_redirect_and_single_use` |
| AC2: expiry or revocation stops only the affected connection | 009-A | `test_connectors.py::test_refresh_install_is_fenced_and_terminal_failure_requires_reconnect`, `test_reconnect_binding_mismatch_and_race_with_disconnect`, `test_r009_08_concurrent_reconnects_keep_the_winning_grant_usable`, `test_r009_09_a_rejected_reconnect_keeps_the_original_grant` |
| AC3: `401` reconnection | 009-A | `test_connectors.py::test_refresh_install_is_fenced_and_terminal_failure_requires_reconnect` |
| AC3: `429` backoff, retryable failures, `403` | 009-B | `test_connector_sync.py::test_009b_rate_limits_retries_forbidden_and_permanent_failures`, `test_r009_11_each_sync_step_reads_the_clock_when_it_happens` (a late `429` in real time) |
| AC3: crash recovery without skipped pages or duplicate records | 009-B | `test_connector_sync.py::test_009b_restart_at_the_page_boundary_skips_and_duplicates_nothing` (three stop points), `test_connectors.py::test_r009_02_superseded_sync_attempt_cannot_overwrite_its_replacement` |
| AC4: metric availability, last synchronization, historical coverage and cost | 009-B, 009-C | `test_connector_coverage.py::test_009c_coverage_and_metric_states`, `test_connector_sync.py::test_009b_usage_accounting_and_budget_stops`, `test_009b_pages_checkpoints_backfill_and_overlapping_requests` |
| Webhook delivery: one scoped effect, no effect on repeat, none for an invalid signature, isolation, after disconnect | 009-D | `test_connector_webhooks.py` (5 cases) |
| 003 case D3: revocation at the provider, destroyed material, scoped purge before the deadline, honest outcomes | 009-A, extended by 009-B and 009-C | `test_connectors.py::test_disconnect_through_worker_command_isolates_other_clients`, `test_teardown_outcomes_with_controlled_clock`, `test_teardown_resumes_after_crash_and_records_late_completion`, `test_r009_10_completion_is_timed_after_the_purge`; checkpoints in `test_connector_sync.py::test_009b_privileges_scoped_references_and_disconnect_purge`; account kind and records in `test_connector_coverage.py` |
| Isolation across clients and agencies sharing one external account | All | K1, K2 and K3 share `syn-acct-777` in every connector module |

### Limits that remain

- Only the synthetic adapter exists. Every real provider rule in `app.privacy.providers` stays stale and blocking until 010-013 re-verify it. The synthetic per-grant revocation, cost units, quota, history limit and webhook scheme describe that adapter only.
- The worker is a bounded command. Production scheduling and process supervision are decided in 020; until something invokes it, neither the 72-hour teardown target nor the sync interval is met.
- The synthetic budgets are development values, not commercial budgets (Q-004). Usage records and run history have no approved retention period (Q-012).
- Section 9.4 of the entry review lists the 009-A limits (an undisposable discarded grant is only logged; a commit reported as failed after it succeeded is resolved by the next sync).
- Native `tracking_sys` has none of the migrations 0009-0012. Merge, native rollout and deployment are owner decisions.

### Readiness for Spec 010 (Instagram)

The runtime contracts that Spec 010 consumes are in place: the connection lifecycle and teardown, paged and rate-limited synchronization with checkpoints and usage limits, coverage and provenance with explicit metric states, and signed webhook verification. Spec 010 is not ready to implement until the owner decides the following, in this order.

1. Account types and metrics (Q-001 for Instagram): which Instagram professional account kinds (business, creator) are in scope, and which account and media metrics form the launch catalog, each declared with its unit and account kinds as a `MetricSpec`. 010 acceptance criterion 2 relies on the 009-C `unsupported` state for metrics an account kind lacks.
2. Authorized test-account evidence (010 acceptance criterion 1): a dated feasibility check with an owner-authorized Instagram professional test account, recording the login route used, the granted scopes, the fields and metrics actually returned for each account kind and media type, the history window available, token lifetimes and refresh behavior, revocation scope, rate-limit signals, and the webhook verification scheme. No live call is authorized until the owner approves this check.
3. Policy rows requiring re-verification before any feature they govern runs: `meta.platform_data` (retention until no longer necessary, deletion on user, client or Meta request, signed data deletion callback, annual Data Use Checkup, per-client separation) and `instagram.login_api` (deauthorize handling, deauthorize and deletion URLs, token refresh after 24 hours and before 60 days, App Review, Advanced Access and Business Verification). Both were researched on 2026-11-03 and are stale. `meta.conversions_api` belongs to 014.
