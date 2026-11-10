# Readiness review before specification 004

Date: 2026-11-10. Authority: the owner's request to review and complete predecessor work before 004, then to begin 004, alongside D-023 to D-026. This review does not authorize merge, deployment, native operations, or new business schema/policy.

## Verified repository state

GitHub PR 1 is merged (`98747a296dd570c5f40f76c68796d3e53edb9cc4`, 2026-11-04). PR 2 is merged (`bab3a3309bb4f4b8ab171036ef87434a8cf16b45`, parents `98747a2` and `21f02339da523bd425f4ddabcdfccc98f7cf31c5`); its tree is identical to `21f0233`. Specification 004 work uses `codex/spec-004-event-collection`, created from `bab3a33` without upstream tracking. The local `main` ref is stale and was not used.

## Predecessor closure matrix

| Work | Evidence | Status |
|---|---|---|
| 000 discovery | Decision register and source inventory | Planning baseline; unanswered source, market and workload questions remain decisions. |
| 001 F-01/F-02 | [Foundation evidence](../../specs/001-foundation/evidence.md#review-amendments-f-01-and-f-02-2026-11-04) | Docker origin fix and purpose comments implemented and merged; historical actual Compose checks retained. |
| 002 T-01 to T-04 | [Auth evidence](../../specs/002-tenancy-access/auth-evidence.md#review-amendments-t-01-to-t-04-2026-11-04) | Lock cycle, invitation throttling, comments and SQL references implemented and merged. |
| 002 D-022 and R-01/R-02/R-03 | [Authentication corrections](../../specs/002-tenancy-access/auth-corrections-2026-11-04.md) | Implemented and merged; controlled providers, not production sign-off. |
| 003 R003-01 | [Correction evidence](../../specs/003-privacy-data-policy/review-corrections-evidence.md) | Closure/Google cycle corrected and merged in PR 2. |
| 003 R003-02 | Correction evidence | Whitespace bypass corrected and merged in PR 2. A further local follow-up is not in `main` (next section). |
| 003 R003-03 | Correction evidence | Trusted head mandatory; incomplete/unknown restore blocked at library level; merged in PR 2. |
| 003 transferred enforcement | D-025 and consuming specifications | Intentional transfer; ingestion/tracker/operational restore are not claimed complete. |

## Bounded card-scan follow-up (not in main)

`groups[start:]` in `contains_card_number` copies the remaining suffix at every candidate start, although candidate growth stops at 19 digits, so long runs of overlength groups cost quadratic copying. A local follow-up indexes groups without copying suffixes and checks the combined length before concatenating; a regression passes 20,000 overlength groups and then a valid synthetic card at the end. Detection policy is unchanged.

That follow-up is staged in the main working tree on `codex/spec-003-privacy-data-policy`, uncommitted, and is **not** part of `bab3a33` or of the 004 branch. It is tracked as decision packet item P1. Merged `main` therefore still contains the suffix copy.

## Verification

| Date | Tested content | Result |
|---|---|---|
| 2026-11-10 (earlier session) | `git archive` of `21f0233` plus only the two follow-up files; isolated Compose project `tracking-spec004-readiness-20261110` | 381 passed in 81.75 s; Ruff check and format check passed (72 files); pip check clean. This result belongs to that candidate, not to `main`. |
| 2026-11-10 (this session) | Branch `codex/spec-004-event-collection` at `bab3a33`, unmodified backend; Compose project `tracking-spec004-test-20261110`, database `tracking_foundation_test` on `127.0.0.1:55433`, synthetic credentials, no `.env` in the worktree, inherited `TRACKING_`/`PG`/`PYTHON` variables removed | `python -m pytest -q -p no:cacheprovider`: **380 passed in 72.11 s**, no skips. |

Cleanup: the earlier project's container, network and volume, and its ignored `tmp/spec004-readiness` working folder (archive, synthetic credentials, logs and one-time scripts), were inspected and removed on 2026-11-10. No other Compose project or volume was touched.

## Entry gates and explicit deferrals

| Item | Next action | Blocks |
|---|---|---|
| 004 design | Owner decisions D1-D11 in the [decision packet](../../specs/004-event-collection/decision-packet.md). | Dependent code, schema and permissions. |
| 003 follow-up and status reconciliation (P1/P2) | Owner direction; recommended small follow-up PR from the 003 branch. | Nothing in 004. |
| Native rollout | Separate approved role/migration/readiness procedure; last verified native revision was 0004_identity on 2026-11-04. | Running this branch against native data, not synthetic design work. |
| Legacy mail | Approve/revise [T1/T2 proposal](../engineering/data-lifecycle.md#legacy-queued-mail-proposal-awaiting-owner-approval), then implement/test separately. | Claiming legacy-mail cleanup complete, not independent 004 design. |
| Consumers/production | Implement 004-020 obligations; review live-provider, mail, capacity, retention and restore requirements. | Their respective end-to-end/production acceptance. |

## Preservation

Pre-existing owner edits (AGENTS.md and decision-register D-021 hunks, Python formatting edits, two unchecked 001/002 checklist lines and untracked review documents) and the staged 003 follow-up remain in the main working tree, untouched and excluded from 004 commits. No live provider or native operation was performed.
