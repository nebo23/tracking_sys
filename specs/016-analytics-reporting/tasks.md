# Tasks: 016-analytics-reporting

Updated: 2026-11-26. Preparation under D-071; 016-A implemented under D-072; 016-B implemented under D-089. Checked items are supported by the [evidence](evidence.md) and the [016-B evidence](evidence-016b.md); unchecked items remain open.

## Preparation

- [x] Create the specification branch/worktree from merged main `2a0c8e5`.
- [x] Inspect stored facts, access/privacy contracts and 006/007/008 dependencies.
- [x] Preserve D-063 deferral of 012/013 and the combined launch scope.
- [x] Prepare entry review, D1-D12 packet, proposed design, verification matrix and conditional handoff.
- [x] Validate the preparation documents and record their checks; publication follows D-051.
- [x] Record owner approval/amendments to D1-D12 before application work (D-072: all approved as recommended, no amendment).

## 016-A (D-072)

- [x] Establish an explicit reporting metric catalog and typed contracts.
- [x] Implement scoped social and spend reports over complete bounded inputs.
- [x] Implement recorded-revenue activity, with whole-client evidence bounds and verified/declared separation.
- [x] Implement correct native-day comparisons and deterministic revision-bound pagination.
- [x] Implement typed bounded CSV through the same calculation and release checks.
- [x] Verify V01-V19, relevant predecessor regressions and required repository checks; record exact results and performance observations.
- [x] Update OpenAPI and engineering guidance to match actual behavior.
- [x] Publish verified commits under D-051 and present completed 016-A for independent review.
- [x] Obtain PR and merge authorization (D-073, 2026-11-23), conditional on successful independent review and final verification.
- [x] Complete D-073 correction verification: 1,505 final cases passed; prepare the verified PR 14 head for the authorized merge. See [independent review](merge-review-2026-11-23.md).

## 016-B (D-089)

- [x] Record the design note before any code (P0, [design-016b.md](design-016b.md)).
- [x] Attribution report with the groups and models views, registered flags, social content items, reconciliation and freshness states (P1).
- [x] `utm_content` adapter change with its one-time rebuild, `roas_from_credit` and the ROAS report with the cost per lead (P2).
- [x] Migration `0030_reporting_indexes` and the funnel report (P3).
- [x] Conversions list and the O1 and O2 release corrections (P4).
- [x] Verify BV01-BV20, the mutation check and the measurements; update the guides and status (P5).
- [ ] Independent review and the owner's merge decision for the 016-B pull request.

## Full specification; remains open

- [x] Complete dependency review and approved implementation of 006, 007-B/C and persisted 008 integration needed by 016-B (PR 15 and PR 16).
- [x] Implement and verify real attribution/funnel/content-revenue/model-comparison/ROAS reports after their decisions (016-B, D-089; merge pending).
- [ ] Design and approve artifact storage, retention, encryption, download authorization, revocation and deletion consumption under 003.
- [ ] Implement retained/scheduled/white-label reports after relevant delivery and 017/018/020 decisions; obtain owner brief/brand before customer-facing UI work.
- [ ] Verify AC1 across every report, export and job.
- [ ] Verify AC2 source definitions/freshness and financial currency/model/window/evidence across the completed scope.
- [ ] Verify AC3 filters, pagination, native dates and comparison fixtures across the completed scope.
- [ ] Verify AC4 partial/unsupported/currency states across the completed scope.
- [ ] Verify full AC5 short-lived authorized exports and deletion-driven invalidation, including D-025 end-to-end obligations.
- [ ] Resolve applicable production/global decisions explicitly; record limitations and owner acceptance without treating deferred requirements as completed.
