# Specification 004 verification evidence

Date: 2026-11-10. Authority: D-027 ([decision packet](decision-packet.md)). Branch: `codex/spec-004-event-collection`, created from merged `main` at `bab3a33` (PR 2). Status: implemented and verified locally on disposable storage; published for owner review under D-028; not merged and not rolled out to native tracking_sys.

## Delivered

| Slice | Delivered |
|---|---|
| 004-B schema | Migration `0007_event_collection`: nine client-scoped tables (sources, sealed source secrets, forms, subjects, consent records, collected events, daily counters, deletion requests, tombstones) with composite tenancy keys, checks and indexes; immutable `service_credentials.kind` (existing keys `read`); extended audit actions; runtime grants (no UPDATE of consent records or tombstones, runtime `UPDATE` on `service_credentials` narrowed to `status, updated_at`); lifecycle grants excluding tombstones and requests; downgrade refuses populated state. Models, data-policy registry (`004-B`), keyring settings. |
| 004-C trusted path | Ingest key kind enforced at authentication and in `resolve_scope` (`events:write`); trusted API consent with subject issuance; the admission transaction (client advisory lock, receipt time after the lock, scope re-resolution, replay tombstones through `deletion.admission`, J1 consent through `consent.require_all`, minimization through `collection.minimize_url`/`sanitize_submission`, scoped deduplication, conflict counters, trusted upgrades, daily counters, rate limits). |
| 004-D public and webhook | Browser sources (non-secret `pk_` key, exact Origin allowlist, `text/plain` or JSON bodies, identical 202 outcomes); public consent using the registered notice digest; generic webhook with HMAC over the raw body before parsing, 5-minute window, sealed secrets under the D-025 token keyring and 24-hour rotation overlap. |
| 004-E lifecycle and diagnostics | Admin (Owner/Admin, audited) and token-holder erasure with subject and event-ID tombstones under the independent tombstone keyring; lifecycle expiry of events, counters, retired secrets and inactive subjects with their consent; metadata-only event lookup and bounded counters; traffic labels. |

OpenAPI: 44 paths and 53 operations (from 30/37). Engineering guide: [event collection](../../docs/engineering/event-collection.md).

## Verification

Environment: worktree `.worktrees/spec-004-event-collection` (no `.env` present), project `.venv` (Python 3.12.4), Compose project `tracking-spec004-test-20261110` running only the `database` service (`postgres:18.6-bookworm`) with database `tracking_foundation_test` on `127.0.0.1:55433` and a fresh volume. All credentials and keyrings were synthetic, generated into a file outside the repository. Inherited `TRACKING_`, `PG` and `PYTHON` variables were removed; `TRACKING_RUN_DB_TESTS=1`, mail mode local, Google sign-in disabled. Native port 5432 and the owner's configuration were not used.

Tested content: backend tree `cae657f69ec6524d3bf2de69481ef9009d971788` and contracts tree `3ec3b4ad20f96a4ea9a47c260a78d60a46cc8c0d`, committed unchanged as implementation commit `82b4a10` after this run. Only documentation changed afterwards.

| Check | Result |
|---|---|
| Baseline, `bab3a33` unmodified: `python -m pytest -q -p no:cacheprovider` | 380 passed in 72.11 s, no skips |
| Full suite after 004: `python -m pytest -q -p no:cacheprovider -rs` | **455 passed in 104.12 s**, no skips or failures: 234 unit/contract and 221 PostgreSQL cases |
| `python -m ruff check app migrations tests` | All checks passed |
| `python -m ruff format --check app migrations tests` | 82 files already formatted |
| `python -m pip check` | No broken requirements found |
| Migration and metadata | Upgrade, idempotent re-upgrade, downgrade to base and upgrade on empty storage (`test_postgres`); `compare_metadata` empty (`test_tenancy`); populated downgrade refused for 0007 and for 0006 with the head preserved |
| Privileges | Runtime role cannot update consent records, tombstones, key kind, event IDs or public keys, nor delete tombstones, requests or counters; lifecycle role cannot touch tombstones, requests, sources or insert/update events |
| Data-policy registry | 28 application tables plus `alembic_version` classified against metadata and the migrated database |
| OpenAPI snapshot | Matches the implemented routes |

No dependency was added. Existing tests changed only where they hard-coded counts or the head revision (`test_data_policy`, `test_data_policy_schema`, `test_postgres`, `test_account_closure`) and in the fixture table list.

## Acceptance criteria

| Criterion | Executable evidence (`tests/integration/test_collection.py` unless noted) |
|---|---|
| 1. Same event ID via browser and server counted once, preferring the trusted source | `test_trusted_copy_upgrades_public_but_public_never_overwrites`, `test_concurrent_identical_retries_store_one_row` |
| 2. Same ID in another client independent; conflicting copies recorded as conflicts | `test_subjects_exist_only_after_a_grant_and_stay_in_their_client`, `test_trusted_intake_deduplicates_and_counts_conflicts` |
| 3. Invalid signatures, oversized payloads and invalid timestamps rejected; duplicates safe; 429 supports retry | `test_webhook_signature_precedes_parsing_and_rotation_overlaps`, `test_bounds_reject_oversized_batched_and_mistimed_events_without_side_effects`, `test_public_rate_limit_returns_retry_after`, `test_a_held_client_lock_times_out_as_retryable` |
| 4. Late arrivals keep both times without double counting | `test_bounds_reject_...` (a 6-day-late event keeps `occurred_at` and its receipt time); deduplication cases above. Report updates belong to later reporting specifications. |
| 5. Denied consent blocks disallowed fields; no personal data in logs | `test_consent_gates_storage_and_withdrawal_suppresses_retries`, `test_click_identifiers_need_attribution_and_forms_keep_only_mapped_classes` (database dump and captured output checked) |

Transferred 003 obligations: E2 enforcement at ingestion and C1 (unknown consent stores nothing, counter incremented) by the consent tests; M5 (password, card, one-time-code, unmapped and free-text values absent from the database and output) by the form test; D2 (replay of a pre-deletion event ID rejected from server, browser and webhook) by `test_erasure_removes_subject_data_and_tombstones_block_every_replay`. Concurrency: `test_withdrawal_in_flight_serializes_before_a_concurrent_event` and `test_erasure_in_flight_wins_over_a_concurrent_event` observe the request waiting on the client lock in `pg_locks` before the withdrawal or erasure commits. Lifecycle: `test_lifecycle_expires_collected_data_but_never_tombstones`.

## Limitations and items not done

- No native migration, native lifecycle run or real customer data. Q-002, Q-004 and Q-012 remain open; the 13-month retention and the rates are development values.
- No load or workload measurement was run; the client-level lock serializes each client's intake, which is untested at volume (Q-004).
- The Compose file forwards the new keyrings, but the API container itself was not started in this verification; only the database service was used.
- Bot labels are user-agent heuristics only; rate limits key on the direct peer address, so a reverse proxy needs its own configuration (020).
- A revocation committed during an in-flight request can let that one event commit (bounded by the statement timeout), as for existing reads.
- Public subject creation is limited only by the per-source and per-peer rate limit.
- Keyrings are local development custody; production custody, the independent restore journal and restore drills remain with 019/020. Tracker delivery (005), identity and contact identifiers (006), financial truth (007) and reporting consumers remain later specifications.
- The local 003 card-scan follow-up is not part of this branch (decision packet item P1).
