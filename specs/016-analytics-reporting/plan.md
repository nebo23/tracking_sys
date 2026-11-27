# Plan: 016-analytics-reporting

Updated: 2026-11-27. D-071 authorized preparation; D-072 approved D1-D12 as recommended. 016-A1 to 016-A4 are implemented, verified and merged in PR 14 (see the [evidence](evidence.md)). D-089 approved the 016-B decisions D1-D14; 016-B is implemented under the [016-B handoff](implementation-prompt-016b.md) and merged in PR 18 (see the [016-B evidence](evidence-016b.md)). 016-C is prepared under D-094 in its [entry review](entry-review-016c.md) and [implementation handoff](implementation-prompt-016c.md); the owner approved its decisions D1-D14 as recommended (D-095).

## Preparation and decision

1. Start from Spec 015 merge `2a0c8e5` on `codex/spec-016-analytics-reporting` and preserve existing worktrees.
2. Review actual stored data, source requirements, access/privacy obligations and unfinished 006/007/008 dependencies.
3. Prepare the [entry packet](entry-review.md), [design](design.md), [verification matrix](verification-matrix.md) and [conditional handoff](implementation-prompt.md); validate documents and publish the preparation under D-051.
4. Obtain and record the owner's decision on the concrete packet. An amended choice must be reconciled across the design before dependent implementation.

## Proposed implementation slices

| Slice | Intended result | Gate |
|---|---|---|
| 016-A1 | Shared contracts, source-native periods, explicit metric catalog, permissions, bounded reads and revision pagination | D1-D12 approval |
| 016-A2 | Social observations/cohorts and spend reports with correct aggregation and comparison | A1 contracts and focused verification |
| 016-A3 | Bounded recorded-revenue activity reports, typed direct CSV and release-time checks | A1/A2; measured financial guard; verification matrix |
| 016-A4 | Integrated evidence, OpenAPI, engineering documentation and independent review | All 016-A checks pass; PR/merge only when separately authorized |
| 016-B | Attribution by campaign, content and link with a model comparison, ROAS and cost per lead, a funnel and a conversions list from stored credit | D-089 (D1-D14); implemented in P0-P5, see the [016-B evidence](evidence-016b.md); merge is the owner's decision |
| 016-C | Retained/revocable exports, scheduled and white-label reports | Artifact/privacy/schema/retention/delivery approval; relevant 017/018/020 work |

No migration, major dependency or UI change is proposed for A. Complete full-scope totals before pagination, and reject exceeded bounds without claiming partial data is complete. Use synthetic fixtures and disposable PostgreSQL; no native rollout, live provider calls or customer intake.

## Validation and completion

Execute the verification matrix only after implementation; record exact commands, commits, results and limitations. Run relevant predecessor regressions and required repository checks. Recheck the actual final head before review. D-051 governs publication of verified work; a new PR and merge remain owner decisions unless explicitly authorized later.

016-A advances AC1-AC4 for its supported read families and verifies its no-retained-artifact deletion boundary. It does not close full AC5 or all Spec 016 requirements. Keep B/C and their dependencies open in task status. Production limits, rollout, monitoring and recovery remain part of separately reviewed production work.
