# Tasks: 008-attribution-engine
Status: 008-A, the in-memory synthetic attribution slice (D-046, corrected under D-047), merged by the owner in [PR 7](https://github.com/nebo23/tracking_sys/pull/7) at `3f6dc06` (2026-11-15). Production defaults (Q-007), persistence and identity integration remain open.

- [x] Approve the scope and sources for lead and revenue attribution engine.
- [x] Resolve Q-007 for the synthetic slice and record the owner decision (D-046; production defaults remain open).
- [x] Verify the merged 007-A calculation contract and identify the 006, 007-B and 007-C dependencies for live attribution in the [entry review](entry-review.md).
- [x] Prepare applicable contracts and synthetic data/permission examples.
- [x] Define independently reviewable local changes for the approved specification.
- [x] Implement the first approved slice (008-A, [evidence](evidence.md)).
- [x] Verify: For touchpoints A then B and revenue of 100, the approved models produce First: A=100; Last: B=100; Linear: A=50 and B=50.
- [x] Verify: With no eligible touchpoint, unknown receives 100; total allocated credit equals eligible net revenue exactly after rounding.
- [x] Verify: Fixtures define expected results for window boundaries, timezones, timestamp ties, refunds, and late events.
- [x] Verify: Recalculating identical inputs with the same model version produces identical results; model changes preserve history.
- [x] Update documentation, limitations, and untested assumptions.
- [x] Present a reviewable result to the owner: [PR 7](https://github.com/nebo23/tracking_sys/pull/7).
- [x] Obtain owner review and upload approval, then push and create or update a PR (D-012): PR 7.
- [x] Record owner acceptance before progressing to dependent work: the owner merged PR 7 (`3f6dc06`, 2026-11-15) and started Spec 009 (D-048). This is repository acceptance, not production sign-off.

## Pre-PR corrections (D-047)

Reviewed commit `3d772d1`; regressions in `backend/tests/test_attribution_corrections.py`; results in the [evidence](evidence.md#pre-pr-corrections-2026-11-15). Each item failed at `3d772d1` and passes after the correction.

- [x] R008-01: one scoped sale is credited once per model (`test_r008_01_one_scoped_sale_is_credited_once_per_model`).
- [x] R008-02: a confirmed capture time re-anchors the sale without a movement (`test_r008_02_confirmed_capture_time_reanchors_the_sale`).
- [x] R008-03: stale snapshots and a restarted consumer cannot supersede a newer revision (`test_r008_03_stale_snapshots_cannot_restore_an_earlier_balance`, `test_r008_03_a_consumer_on_a_populated_history_publishes_no_spurious_zero`).
- [x] R008-04: each receipt keeps its revision in one batch (`test_r008_04_each_receipt_keeps_its_revision_in_one_batch`).
- [x] R008-05: a receipt split across pages converges without a negative balance (`test_r008_05_paged_receipt_converges_without_a_negative_balance`).
- [x] R008-06: consent and ownership changes of a non-winning touch update the current view (`test_r008_06_a_non_winning_touch_leaves_the_current_view`).
- [x] R008-07: a reassigned campaign transfers credit in the differences (`test_r008_07_reassigned_campaign_transfers_credit_in_the_differences`).
- [x] R008-08: identical items coalesce; mismatch and gap are distinct refusals (`test_r008_08_identical_copies_within_one_delivery_coalesce`, `test_r008_08_mismatched_replay_and_gap_are_refused_without_change`).
- [x] R008-09: history validates conversions and model definitions (`test_r008_09_history_validates_conversions_and_model_definitions`).
- [x] R008-10: an unrepresentable intermediate receipt recovers (`test_r008_10_unrepresentable_intermediate_receipt_recovers`).
- [x] R008-11: a corrected repeated local hour is a new revision (`test_r008_11_corrected_repeated_local_hour_is_a_new_revision`).
- [x] R008-12: a currency or exponent change is refused (`test_r008_12_currency_change_is_refused_before_a_revision`).
- [x] Window boundary: `timedelta.max` and the earliest dates give a documented outcome (`test_window_boundary_at_the_earliest_representable_instant`).
- [ ] Owner review of the open items in the evidence: the sale association conflict policy, model version ID scope, 007-B persistence of receipt items, and `net_out_of_range` reporting.

- [x] Verify the six follow-up findings on snapshot order, pending receipts, repeated local times, journey recovery, sale currency across models, and financial reads. The [follow-up results](evidence.md#follow-up-verification-against-9892556) cover replay, rejection, and retries.

## 008-B persisted attribution (D-079)

Branch `codex/spec-008-attribution-persistence` from `claude/keen-fermat-otlr9d` at `3d1a472`; [design note](design-008b.md); [evidence](evidence-008b.md).

- [x] P0: inventory of the persisted inputs and the design note (`8462780`).
- [x] P1: migration `0029_attribution_persistence`, data policy, grants, model versions with lazy defaults and the model routes; AV14, AV19 (`5166057`).
- [x] P2: the consumer core and `python -m app.attribution_worker`; AV01-AV07, AV11, AV13, AV16 (`f900147`).
- [x] P3: the scrub in every removal path, the erasure target, the lifecycle steps and the release barrier; AV08-AV10, AV15, AV17, AV20 (`69c57db`).
- [x] P4: the status and runs routes with the D10 permissions; AV12 (`1a301a3`).
- [x] P5: the full verification, 17 mutation checks, the AV16 measurements, the evidence and the guides (`faaa067` and the documentation commit).
- [ ] Independent review of the pull request and the owner's merge decision.
- [ ] Follow-ups outside 008-B: 016-B reports and ROAS from the stored credit changes, 016-C, native rollout of 0005-0029, live providers and production scheduling (020); A3 and Q-012 stay open.
