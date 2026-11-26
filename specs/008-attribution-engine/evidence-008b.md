# Spec 008-B evidence: persisted attribution

Recorded 2026-11-26 under D-078 and D-079 on `codex/spec-008-attribution-persistence`, created from `claude/keen-fermat-otlr9d` at `3d1a472`. That branch is merged `main` at `3187c70` (PR 15) plus the 008-B preparation; `origin/main` was still `3187c70` when the work started and when it ended.

**Environment.**
- All data is synthetic.
- Every database case ran on a disposable `postgres:18.6-bookworm` service: Compose project `tracking-test-008b`, database `tracking_foundation_test` on 127.0.0.1:55433, with the repository's `tracking_app`, `tracking_migrator` and `tracking_lifecycle` roles.
- Native `tracking_sys` was not touched, no provider was called, and no dependency was added.

Design: [design note](design-008b.md) over the [entry review](entry-review-008b.md). Developer guide: [persisted attribution](../../docs/engineering/attribution.md).

## Commits

| Commit | Content |
|---|---|
| `8462780` | P0: the design note (inventory, exact schema, keys, pass, rebuild, scrub, routes, test inventory). |
| `5166057` | P1: migration `0029_attribution_persistence`, ORM models, data policy rows, model versions with lazy defaults, the model routes, the pure engine-to-row mapping, AV14 and AV19. |
| `f900147` | P2: the consumer core (`attribution_store`) and `python -m app.attribution_worker`, the consent change signal, the input adapter changes, AV01 to AV07, AV11, AV13 and AV16. |
| `69c57db` | P3: the scrub in every removal path, the erasure target, the lifecycle steps, the release barrier and the status read, AV08 to AV10, AV15, AV17, AV20 and the erasure case of AV11. |
| `1a301a3` | P4: `GET /attribution/status` and `GET /attribution/conversions/{id}/runs` with the D10 permissions, AV12. |
| `faaa067` | P5: a database error in one client no longer stops a pass; the event-retention, new-conversion erasure race and measurement tests. |
| this commit | P5: this evidence, the developer guide and the status documents. |

Each phase was pushed under D-051 after its checks passed. Migration `0029` was amended once on the branch before any merge (P2 grants the worker `UPDATE (binding_id)`), on disposable databases only.

## What was built

- **Schema.**
  - Six tables, with scoped keys, closed checks and restricted grants; listed in the developer guide.
  - The data policy gains four classes and six table entries. Four row rules are approved under D-079; the model versions and the consumer state follow the workspace lifetime.
  - The table counts are now 87.
- **Model versions.**
  - Lazy defaults: First Click, Last Click and Linear at 30 days, with Linear as default.
  - Owner/Admin administration, idempotent and audited, limited to six active versions; the current default cannot be retired.
- **Consumer.**
  - One conversion per verified sale or trusted lead and owner; owner changes supersede.
  - Units with fixed targets and bounded REPEATABLE READ chunks whose first write is the compare-and-swap.
  - A history-preserving staging rebuild, a bounded sweep, and the D11 bounds with explicit states.
  - The calculation is `attribute()` unchanged: the latest stored revision is rebuilt exactly as its `previous` (40 pure round-trip and ledger cases).
- **Privacy.** The D9 scrub runs in every removal transaction, ordered against the worker through the consumer state row. The erasure target is `attribution`. Lifecycle discards failed staging rows and scrubs dangling owners.
- **Reads.** A status route, and a runs route behind the release barrier with the finance split.

## Verification matrix

| Case | Test | Result |
|---|---|---|
| AV01 | `test_attribution_store.py::test_av01_first_last_and_linear_from_stored_allocations` | Passed: First A 100.00, Last B 100.00, Linear 50.00 and 50.00 from stored allocations. |
| AV02 | `test_av02_unknown_and_unassociated_sales_reconcile_with_the_net`; `test_av02_random_journeys_allocate_the_exact_net` (seeds 1-3) | Passed: unknown 100 % for an owner without touches and for an unassociated sale; random journeys allocate the exact net. |
| AV03 | `test_av03_window_boundaries_zones_ties_refund_and_late_touch` | Passed: inclusive window start, a sale written at UTC+2, ID order for equal instants, a refund (signed differences) and a late touch. |
| AV04 | `test_av04_an_identical_pass_stores_nothing`; `test_av04_a_new_version_keeps_the_old_history_byte_identical` | Passed: three identical passes store nothing; a new version rebuilds, its own revision 1 is added and every older row is unchanged. |
| AV05 | `test_av05_incremental_equals_rebuild_after_every_random_step` | Passed. A seeded sequence of 16 steps covers sales, refunds, touches, leads, a merge, an unmerge, a withdrawal, a regrant and a detach. After every step: the stored state equals a from-scratch calculation, a dry rebuild would change nothing, the ledger equals the latest allocations, and attributed revenue equals ledger revenue. A real rebuild then adds only the new version's rows. |
| AV06 | `test_av06_refund_release_chargeback_and_correction_revisions`; `test_av06_a_held_refund_changes_nothing_until_it_posts`; `test_av06_a_ledger_generation_change_rebuilds` | Passed: revisions follow the stored journal (including a real release movement); a held Paymob refund changes nothing until its settlement posts it; an operator backfill (new generation) rebuilds and stores nothing new. |
| AV07 | `test_av07_ownership_changes_supersede_without_mutation` | Passed: association, merge, unmerge and detach each supersede and open a successor; earlier identities are byte-identical, the ledger evidence is unchanged and money is credited once. |
| AV08 | `test_attribution_privacy.py::test_av08_withdrawals_remove_touches_from_new_revisions`; `test_av08_a_surviving_person_keeps_its_history_after_w1`; `test_av08_erasure_and_expiry_scrub_every_pointer`; `test_av08_a_replay_after_erasure_restores_no_pointer` | Passed: withdrawal removes touches from new revisions; a W1 that deletes the person scrubs it; erasure and expiry scrub every pointer in the removal transaction; a replayed association, passes and a rebuild restore nothing. |
| AV09 | `test_av09_marked_events_never_become_touches` | Passed, also for an event marked after the first pass (repaired by the sweep). |
| AV10 | `test_av10_identical_references_in_two_clients_never_mix` | Passed: the same email, operation and campaigns in two clients; an erasure, passes and a lifecycle run in one leave the other byte-identical. |
| AV11 | `test_attribution_store.py::test_av11_two_workers_publish_once`, `::test_av11_a_stale_checkpoint_never_publishes`, `::test_av11_a_concurrent_rebuild_wins_once`, `::test_av11_a_pruned_feed_forces_a_rebuild`; `test_attribution_privacy.py::test_av11_an_erasure_after_the_snapshot_is_never_restored`, `::test_av11_an_erasure_after_the_snapshot_never_reaches_a_new_conversion` | Passed: the worker that loses the compare-and-swap writes nothing; an erasure after a worker's snapshot is never undone, for an existing or a new conversion. |
| AV12 | `test_attribution_api.py::test_av12_model_administration_is_owner_admin_and_audited`, `::test_av12_runs_need_identity_read_and_amounts_need_finance_read`, `::test_av12_service_keys_reach_models_and_status_only`, `::test_av12_a_revocation_during_the_request_releases_nothing` (both flags) | Passed. |
| AV13 | `test_av13_currencies_stay_apart` | Passed: EGP and USD sales keep separate ledger rows; nothing is converted or added. |
| AV14 | `test_attribution_models.py::test_av14_populated_upgrade_guarded_downgrade_and_privileges`; `::test_av14_runtime_role_cannot_rewrite_allocations_or_amounts` | Passed: a populated 0028 upgrades and keeps its rows; the downgrade refuses stored rows and new audit values (consumer state alone does not block it); fourteen denied statements for both roles. |
| AV15 | `test_av15_lifecycle_scrubs_and_discards_without_touching_money`; `test_av15_an_event_leaving_retention_is_scrubbed_from_stored_attribution` | Passed: a failed rebuild's staging rows are discarded and its staged supersessions undone; a dangling owner is scrubbed; money, shares and provenance columns are byte-identical. |
| AV16 | `test_av16_pass_transaction_and_touch_bounds`; `test_worker_command_prints_counts_only`; `test_a_database_error_for_one_client_does_not_stop_the_pass`; `test_av16_measurements` (opt-in) | Passed: explicit `bounded`, `ledger_unavailable` and `touch_bound_exceeded` states; counts-only output; measurements below. |
| AV17 | `test_av17_stale_while_behind_then_released`; `test_attribution_api.py::test_stale_reads_answer_the_retryable_code` | Passed. The read answers stale while the feed or the ledger is ahead, after a consent lapsed (no watermark moves), after a detach and during a rebuild; it is released after the pass, with the finance split. |
| AV18 | The existing suites (below) | Passed unchanged; only the head-dependent table lists, counts and head pins were updated. |
| AV19 | `test_av19_defaults_and_a_retired_default_is_refused`; `test_model_administration_codes_idempotency_and_audit`; `test_service_read_keys_reach_the_models_of_granted_clients_only` | Passed. |
| AV20 | `test_av20_no_contact_value_token_or_identifier_in_rows_responses_or_logs` | Passed: no email, subject token or key in any row, response, worker output or log; no ID in the worker output or the log. |

## Commands and counts

Final verification at `faaa067`, from `backend/` with the project virtual environment through the scratch runner:
- inherited `TRACKING_`, `PG` and `PYTHON` variables dropped;
- `TRACKING_RUN_DB_TESTS=1` and `TRACKING_RUN_BROWSER_TESTS=1`;
- a freshly recreated database.

The suite ran in five foreground batches because free memory was about 2 GB.

| Check | Command | Result |
|---|---|---|
| Lint and format | `ruff check app tests migrations`; `ruff format --check app tests migrations` | Clean (282 files). |
| Backend unit and contract | `pytest -q -m "not integration"` | 926 passed, 651 deselected (18 s). |
| Integration batch 1 (11 modules, access API to bookings and CRM) | `pytest -q -rs <modules>` | 178 passed, 3 skipped: the opt-in AV16 measurements (509 s). |
| Integration batch 2 (10 modules, collection to conversion delivery) | same | 139 passed (453 s). |
| Integration batch 3 (11 modules, data policy schema to invitation throttle) | same | 83 passed (172 s). |
| Integration batch 4 (10 modules, ledger persistence to revenue evidence) | same | 104 passed (240 s). |
| Integration batch 5 (10 modules, revenue identity to WhatsApp, browser journeys included) | same | 143 passed, 1 skipped: the D-076 opt-in measurement `TRACKING_REVIEW_MEASURE` (177 s). |
| AV16 measurements | `TRACKING_ATTRIBUTION_MEASURE=1 pytest -s -k measurements`, per size | 3 passed (separate runs). |
| Tracker unit | `node --test test/unit/*.test.js` | 73 passed. |
| Tracker browser (Chromium and Firefox, Playwright 1.64.1) | `node --test --test-concurrency=1 test/browser/*.test.js` | 50 passed, 0 skipped. |
| Dependencies | `python -m pip check` | No broken requirements. |
| Whitespace and links | `git diff --check`; relative-link check of the changed Markdown | Clean. |

**Totals.** 647 integration cases passed in 52 modules and 4 were skipped as described; none failed. 47 of the cases are new 008-B cases, 3 of them the opt-in measurements.

**Tracker setup.** The tracker's `node_modules` was a junction to the Spec 005 worktree's installed copy, Playwright 1.64.1, which is the version this branch's lockfile pins. The tracker package is unchanged on this branch.

**OpenAPI.** The regenerated `contracts/openapi.json` equals `main`'s once the 5 new paths and 15 new schemas are removed. `git diff --minimal` counts 1,927 insertions and no deletion; the default diff shows deletions only because of how it aligns moved JSON lines.

## Measurements (AV16)

These are observations on the development workstation, not SLOs; A3 stays open. Each size has five persons with three touches each, and one sale in five associated. The operator backfill publishes the ledger before measuring.

| Conversions | First pass (rebuild from empty) | One incremental step (a new sale, an association and a late touch, plus the sweep) | Rebuild for a new model version |
|---|---|---|---|
| 50 | 1.38 s, 556 statements, 50 slots, 150 revisions | 0.81 s, 367 statements, 3 slots, 9 revisions | 1.18 s, 575 statements, 51 slots, 51 revisions |
| 200 | 3.53 s, 1,636 statements, 200 slots, 600 revisions | 1.43 s, 965 statements, 9 slots, 27 revisions | 1.53 s, 868 statements, 201 slots, 201 revisions |
| 1,000 | 15.86 s, 10,634 statements, 1,000 slots, 3,000 revisions | 3.05 s, 2,250 statements, 41 slots, 123 revisions | 14.62 s, 10,713 statements, 1,001 slots, 1,001 revisions |

The step at 1,000 recalculated 41 slots: the new sale and the 40 sales of the person whose late touch arrived.

## Mutation check

`mutations_008b.py` (in the session scratchpad, not committed) disabled each safeguard in turn and ran its tests on the disposable database. It restored the source byte for byte after each run, checked by SHA-256; a final `sha256sum -c` against the hashes taken before the first mutation passed for all four files. The complete set ran once more in one invocation: 17 of 17 as expected.

| Safeguard | Mutation | Tests | Outcome |
|---|---|---|---|
| Compare-and-swap | Predicate and rowcount check removed, chunk at READ COMMITTED | AV11 two workers, stale checkpoint | Caught |
| Compare-and-swap, one layer | Predicate removed, snapshot kept | same | Held (the serialization failure refuses) |
| Compare-and-swap, one layer | Snapshot removed, predicate kept | same | Held (the predicate refuses) |
| Release barrier | Watermark and recalculation checks removed | AV17, stale HTTP read | Caught |
| Release barrier, one layer | Watermark check removed | same | Held (the recalculation refuses) |
| Release barrier, one layer | Recalculation check removed | same | Caught (a lapsed consent moves no watermark) |
| Scrub | `scrub_conversions` does nothing | AV08 erasure and expiry, replay | Caught |
| Scrub ordering | The removal no longer changes the consumer state first | AV11 erasure reaching a new conversion | Caught |
| Supersession | An owner change keeps the conversion | AV07 | Caught |
| Rebuild trigger | A pruned feed does not rebuild | AV11 pruned feed | Caught |
| Rebuild trigger | A new model set does not rebuild | AV04 new version | Caught |
| Rebuild trigger | A new ledger generation does not rebuild | AV06 generation | Caught |
| Bounds | A chunk ignores the transaction bound | AV16 bounds | Caught |
| Bounds | The touch bound is never exceeded | AV16 bounds | Caught |
| Bounds | The pass ignores its budget | AV16 bounds | Caught |
| Model-version limit | More than six active versions | model administration | Caught |
| Finance permission | Amounts without `finance:read` | AV12 runs | Caught |

**What the runs taught.**
- The first run expected the recalculation layer of the release barrier to be redundant. It is not: no watermark moves when a consent expires, so the recalculation is a required check of its own, and the mutation is now expected to be caught.
- The scrub-ordering mutation first survived. In that test the worker's pending runs referenced a conversion whose key the scrub had changed, and the foreign-key check refused them. A conversion the stale pass opens has no such protection, so `test_av11_an_erasure_after_the_snapshot_never_reaches_a_new_conversion` was added, and it catches the mutation.

## Defects found and fixed during the phases

- The retire route autoflushed a retired version before its retirement time was set (a clock query between the two assignments), which the `retirement` check refused; the clock is now read first.
- Seeded defaults share one creation time, so they are listed by creation time and version key.
- The first measurement setup stored every sale before any projection and waited for `catch_up`, which answers `not_ready` for such a client; it now uses the operator backfill. The timed-out run left synthetic rows, and the database was recreated (`down -v`, `up -d --wait`).

## Resolutions beyond the packet's wording

Section 10 of the [design note](design-008b.md) lists them for the review:
1. A consent change now appends an `events_changed` feed record for the subject's owners.
2. The deletion of a person scrubs its pointers for every removal kind.
3. The input adapter adds content provenance and ignores an unusable `utm_campaign` value.
4. The rebuild preserves history in a staging generation.
5. A few bookkeeping columns are added.
6. A lead conversion is the trusted lead event itself.

A database error in one client no longer stops the whole pass.

## Limits and open items

- A3 remains open (see the measurements); no SLO is set.
- No route lists conversions. A conversion ID is found in the database or, later, through 016-B reports.
- Changes that no signal reports are repaired only by the sweep (200 conversions per pass). The runs route answers stale for an affected conversion until then. An example is an event marked excluded without a feed record.
- `net_out_of_range` cannot occur from the persisted ledger, whose amounts are BIGINT; the status is supported but unreachable.
- A failed consumer is retried only after the lifecycle runner resets it; a deterministic engine refusal therefore fails again at each lifecycle cycle, visibly in the status route.
- Retention values are the development values of D12; Q-012 stays open.
- Not in this slice: the native `tracking_sys` migration, live providers, 016-B and 016-C reports, the React UI and production scheduling (020).
- The owner decided the merge after Claude's review (D-080); see the [merge review](merge-review-008b.md).
