# Combined 006 and 007-B/C evidence

Recorded 2026-11-23 under D-075 on `codex/spec-006-007-identity-ledger` (baseline merged `main` `81977a3`). All data is synthetic; every database case ran on disposable PostgreSQL 18.6 (Compose project `tracking-test-0607`, `tracking_foundation_test` on 127.0.0.1:55433, roles `tracking_app`, `tracking_migrator` and `tracking_lifecycle`). Native `tracking_sys` was not touched. No provider was called and no dependency was added.

## Commits

| Commit | Content |
|---|---|
| `888ea9d` | D-075 recorded (decision register, working agreement, status documents). |
| `3c89110` | P1: migration `0026_identity_journey`, identity keys, normalizers, assertions, retry receipts, handoff, consent, segments, W1, change feed, merge-loss rule, 004 hooks. |
| `29abf66` | P2: `identity:read`, read models, merges and reversals, person erasure with held sets, R006-25, feed reads, identity lifecycle, tracker 0.6.0 (`identityHandoff`, `restart`). |
| `247e7c9` | P3: migration `0027_ledger_persistence`, persisted receipts, movements, projections, fail-closed reads, operator backfill, movements and reconciliation APIs. |
| `958a154` | P4: migration `0028_revenue_identity`, sale association, F1 unlinking, customer qualification, person revenue read, 008-A input adapter. |
| `c7467d7` | P5: remaining matrix cases (populated upgrade and guarded downgrades, key rewrap, held-event exclusion, token-erasure merge loss, association race, log scan). |

Each phase was pushed to the branch under D-051 after its checks passed. No pull request was opened (not authorized for this workstream).

## Final verification at `c7467d7`

Commands run from `backend/` with the project virtual environment through the scratch runner (inherited `TRACKING_`, `PG` and `PYTHON` variables dropped; `TRACKING_RUN_DB_TESTS=1`, `TRACKING_RUN_BROWSER_TESTS=1`) on a freshly recreated database:

| Check | Command | Result |
|---|---|---|
| Backend unit and contract (includes the OpenAPI snapshot) | `pytest -q -p no:cacheprovider -m "not integration"` | 886 passed, 580 deselected (17 s) |
| Integration batch 1 (modules 1-12: access to connector sync) | `pytest -q <modules>` | 205 passed (338 s) |
| Integration batch 2 (modules 13-24: connector webhooks to identity feed) | same | 133 passed (240 s) |
| Integration batch 3 (modules 25-36: identity-ledger migrations to report bounds) | same | 91 passed (203 s) |
| Integration batch 4 (modules 37-47: reports to WhatsApp, browser journeys enabled) | same | 151 passed (213 s) |
| Tracker unit | `node --test test/unit/*.test.js` | 71 passed |
| Tracker browser (Chromium and Firefox, Playwright 1.64.1) | `node --test --test-concurrency=1 test/browser/*.browser.test.js` | 50 passed (71 s) |
| Lint and format | `ruff check app tests migrations`; `ruff format --check` | clean |

Total: 580 integration cases in 47 modules, none failed or skipped. The tracker's `node_modules` was a junction to the Spec 005 worktree's installed copy (unchanged package lock).

Observations from the phase runs (not repeated in the final run): during P2 batch 4, `test_reports.py::test_v01_foreign_scopes_reveal_nothing` failed once because the string `777` matched the microseconds of the response's `generated_at` (`"generated_at":"2026-11-23T02:31:46.977745Z"`); it is a pre-existing time-dependent assertion of 016-A, unrelated to this work, and failed 1 of 9 and 1 of 12 runs in loops. The P4 batch 1 wall time (19,851 s) includes a Modern Standby period from 02:49 to 10:46 (Kernel-Power events 506/507).

Defects found and fixed during the phases before their commits: runtime UPDATE grants missing on `identity_links` (W1 path) and on the merge result (written before insert instead); merge-dependent assertions counted as independent evidence (R006-25 filter); the lifecycle reading a column it may not read and changing its result shape; an inline-projection cost for bulk imports (see A3); over-long foreign-key names.

## Contract changes (OpenAPI)

Only additions, compared semantically with the previous snapshot at each phase: identity handoff and assertion routes (P1); identity subjects, profile, timeline, leads, review, merges, reversal, erasures and resolution (P2); revenue movements, reconciliation queue and review actions (P3); identity associations, detach and a person's revenue (P4). `FinancialGrant` and `ClientGrantInput` gained the optional `can_view_identities` only. A 004 erasure reports `identity_records` only when identity evidence existed, so its outcome set is unchanged otherwise.

## Deferred 006 findings

| Finding | Status | Evidence (tests in `backend/tests/`) |
|---|---|---|
| R006-23 scoped event FK | Closed | `uq_collected_events_scope` and the non-cascading scoped hold FK in 0026; `integration/test_identity.py::test_scoped_hold_foreign_key_and_write_once_markers` (cross-client hold refused, held event delete refused); holds settled by resolution (`test_identity_admin.py::test_shared_device_erasure_holds_exact_set_and_resolutions`), token erasure and lifecycle expiry (`test_identity_lifecycle.py::test_expiring_held_event_settles_its_hold_and_completes_the_request`). |
| R006-24 trusted upgrade | Closed | Write-once `identity_excluded_at` and immutable `first_received_at` enforced by a trigger (`test_scoped_hold_foreign_key_and_write_once_markers`); a retained event stays out after a trusted upgrade and a new assertion (`test_identity_admin.py::test_retained_event_never_returns_to_a_journey`); a still-held event is in no journey (`test_identity_ledger_migrations.py::test_held_event_and_token_erasure_of_a_merge_participant`); the 008 adapter reads only `journey_events`, which excludes marked events. |
| R006-25 independent merge evidence | Closed | `has_evidence(..., excluding_merge)` ignores keys, links and assertions of the edge; loss on withdrawal (`test_identity_admin.py::test_merge_participant_loss_closes_the_edge_first`), expiry (`test_identity_lifecycle.py::test_expiry_of_a_participant_closes_the_merge_edge_first`) and token-holder erasure (`test_identity_ledger_migrations.py::test_held_event_and_token_erasure_of_a_merge_participant`). The first run of the withdrawal case failed before the filter excluded merge-dependent assertions. |
| R006-26 expired receipts | Closed | `test_identity.py::test_retry_receipts_answer_inside_the_window_only` (expiry at the exact instant, failed proof leaves the receipt unchanged, valid proof replaces it in place without a uniqueness error, nothing applied twice) and `test_concurrent_identical_retries_and_new_keys_are_deterministic`; a retry inside the window after W1 answers `duplicate` (`test_w1_withdrawal_removes_identity_evidence_in_the_consent_transaction`). |
| R006-27 retrospective interval | Closed | Unit `test_identity_rules.py` (boundary equality, two-time rule, classes); `test_identity.py::test_provisional_prefix_shared_device_and_two_time_rule` and `test_consent_gap_and_late_grant_are_never_adopted`. |
| R006-28 rebuild publication | Closed | `test_identity_feed.py`: a rebuild fails when another worker advanced the checkpoint or published a generation, concurrent replays commit once, an erasure after the snapshot is never released stale, and a completely pruned feed forces a rebuild. |

For R006-23 to R006-28 the behavior did not exist before this branch, so each regression is an acceptance test that fails without the implementation (D-075 closure rule); no claim is made that it failed on the old application.

## Joint verification matrix

| Case | Executed evidence | Remaining gap |
|---|---|---|
| JV01 | `test_identity_ledger_migrations.py::test_populated_upgrade_from_0025_and_guarded_downgrades` (one head, legacy issuance `unknown`, rows and privileges kept, each of 0028, 0027 and 0026 refuses its populated state and rolls back); `test_postgres.py` full cycle; model and registry agreement tests. | None known. |
| JV02 | `test_identity.py::test_identical_values_in_two_clients_never_link_or_collide`; scoped FKs; lifecycle per client. | No separate restricted-role FK fuzz. |
| JV03 | `test_identity_admin.py::test_identity_reads_need_the_identity_permission` and `test_invitation_carries_the_identity_flag`; person revenue needs both permissions (`test_revenue_identity.py`). | Member and agency disablement for identity reads rely on `resolve_scope` (tested in 002), not a new case. |
| JV04 | Normalizer unit cases; six proof cells; single-use handoff; key rewrap (`test_matching_key_rewrap_keeps_matching`); value scan of identity tables (`test_worked_journey_links_three_devices_to_one_person`) and log scan (`test_no_identifier_token_or_code_reaches_the_log`). | None known. |
| JV05 | Provisional prefix, shared device, consent gap, W1 on public withdrawal and trusted denial, attribution withdrawal (F1). | Floor and marker after expiry are covered by the lifecycle cases only indirectly. |
| JV06-JV11 | See the deferred findings above. | JV09: retry outside the window after an early handoff removal is not a separate case. |
| JV12 | Concurrent assertions, merge versions and retries (`test_worked_mistaken_merge_and_exact_reversal`), association racing withdrawal. | No randomized merge/event race. |
| JV13 | `test_ledger_persistence.py::test_acceptance_cases_through_stored_receipts` and a seeded randomized log: stored calculation, movements and journal equal `calculate()` and `ledger_feed()`; currencies separate; manual declarations unverified. Existing 007-A suites unchanged and passing. | The individual R007-01 to R007-11 unit cases were not each replayed through the database; equality with the reference engine covers them for hold-free logs. Synthetic FX snapshots are unchanged 007-A code. |
| JV14 | Concurrent duplicate deliveries, equal receipt instants, contiguous per-client ordinals across another client, injected failure after the movements were written. | Crash points are simulated in-process, not by killing PostgreSQL. |
| JV15 | `test_held_refund_keeps_its_position_and_posts_at_a_later_receipt`. | Multiple sources with identical operation IDs only through the full transaction key in JV18. |
| JV16 | Interrupted, resumed, concurrently appended and conflicting backfills. | Run with up to 250 rows only. |
| JV17 | `test_reconciliation_queue_and_review`. | None known. |
| JV18-JV20 | `test_revenue_identity.py` (six cases). | Pending associations resolve on read, without a new revision. |
| JV21 | `test_persisted_inputs_drive_the_008_engine` (First, Last, Linear; refund revision; merge gives a new conversion identity; reversal restores it; erasure removes inputs, money unchanged). | Production 008 persistence is not implemented (excluded by J12). |
| JV22 | Full 014, 015 and 016-A suites pass. `test_report_bounds.py::test_v14_v18_...` now patches the source modules of `ledger_feed` and `calculate`, because reads no longer import them. | None known. |
| JV23 | Tracker unit `identity.test.js` and browser `identity.browser.test.js` in Chromium and Firefox; existing GPC and consent suites. | None known. |
| JV24 | Measurements below; lock order reviewed (no path takes the revenue lock before the privacy or agency lock); `test_lock_order.py` passes. | No dedicated contention benchmark; A3 stays open. |

## Measurements (development workstation, disposable database)

| Operation | 50 rows | 100 rows | 200 rows |
|---|---|---|---|
| One receipt written with its evidence | 0.015 s | 0.019 s | 0.028 s |
| Ledger read (one pass plus stored movements) | 0.008 s | 0.011 s | 0.020 s |
| Operator backfill of the whole history | 0.17 s | 0.37 s | 1.18 s |

Projecting every row of one bulk commit inline grows quadratically: 250 rows 2.44 s, 500 rows 7.39 s, 1,000 rows 25.9 s. Therefore a CSV commit above 200 rows keeps the existing intake behavior (250 rows committed in 0.29 s) and leaves the projection behind; ledger reads then fail closed with `ledger_projection_unavailable` until `python -m app.ledger_backfill` publishes a caught-up generation. **A3 remains open**: writes and rebuilds still recompute the current state per receipt, and no operating limit above the existing bounds is claimed. The 016-A 200-evidence cap is unchanged.

## Self-review and limitations

A structured self-review of the diff covered tenant scope, permissions, lock order, F1, held refunds and the contract diff. It is not an independent review; an independent review is still recommended before any merge decision. Known limitations:

- `staff_verified` is refused (`method_invalid`) because no client attestation setting exists.
- A held or retained event stays stored as an anonymous device event until its ordinary retention.
- An erasure of a merge participant deletes the closed merge-ledger row naming it (design 7.2); withdrawal and expiry keep the closed row for its 2-year period.
- The per-client privacy and revenue locks serialize identity and financial writes per client; sizing needs Q-004.
- Retention values are development values (Q-012 stays open for real data).
- Not in scope and not done: production 008 persistence, 016-B/C, React UI, live providers, native `tracking_sys` migration, deployment, CI (A2).
