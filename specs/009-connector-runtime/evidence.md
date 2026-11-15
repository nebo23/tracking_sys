# Spec 009-A evidence

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
