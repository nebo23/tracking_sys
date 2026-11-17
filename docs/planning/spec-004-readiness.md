# Readiness review before specification 004

Date: 2026-11-10. Authority: the owner's request to review and complete predecessor work before 004, alongside D-023 to D-026. This review does not authorize merge, deployment, native operations, or new business schema/policy.

## Verified repository state

GitHub PR 1 is merged (`98747a296dd570c5f40f76c68796d3e53edb9cc4`, 2026-11-04). PR 2 was re-read on 2026-11-10: open, unmerged, head `21f02339da523bd425f4ddabcdfccc98f7cf31c5`, matching local HEAD before this follow-up. Local main is stale; future branch preparation must fetch and compare merged remote main.

## Predecessor closure matrix

| Work | Evidence | Status |
|---|---|---|
| 000 discovery | Decision register and source inventory | Planning baseline; unanswered source, market and workload questions remain decisions. |
| 001 F-01/F-02 | [Foundation evidence](../../specs/001-foundation/evidence.md#review-amendments-f-01-and-f-02-2026-11-04) | Docker origin fix and purpose comments implemented and merged; historical actual Compose checks retained. |
| 002 T-01 to T-04 | [Auth evidence](../../specs/002-tenancy-access/auth-evidence.md#review-amendments-t-01-to-t-04-2026-11-04) | Lock cycle, invitation throttling, comments and SQL references implemented and merged. |
| 002 D-022 and R-01/R-02/R-03 | [Authentication corrections](../../specs/002-tenancy-access/auth-corrections-2026-11-04.md) | Implemented and merged; controlled providers, not production sign-off. |
| 003 R003-01 | [Correction evidence](../../specs/003-privacy-data-policy/review-corrections-evidence.md) | Closure/Google cycle corrected, original-session checks preserved. |
| 003 R003-02 | Correction evidence and this follow-up | Whitespace bypass corrected; quadratic suffix copies removed during this review. |
| 003 R003-03 | Correction evidence | Trusted head mandatory; incomplete/unknown restore blocked at library level. |
| 003 transferred enforcement | D-025 and consuming specifications | Intentional transfer; ingestion/tracker/operational restore are not claimed complete. |

## Bounded card-scan follow-up

`groups[start:]` copied the remaining suffix at every candidate start, even though candidate growth stopped at 19 digits. Long runs of overlength groups therefore required quadratic copying. The scan now indexes groups without copying suffixes and checks combined length before concatenating. Each start examines at most 20 nonempty groups with at most 19 candidate digits; group extraction remains linear in input length. Detection policy and submitted text are unchanged.

A regression passes 20,000 overlength groups through `sanitize_submission`, verifies the text is retained, then appends a valid synthetic card and verifies the entire field is dropped. It exercises full-scan and tail detection without a flaky timing assertion. This follows up R003-02 rather than introducing an ingestion feature or policy.

## Verification on 2026-11-10

The candidate is a `git archive` of `21f0233` with only `backend/app/privacy/collection.py` and `backend/tests/test_privacy_collection.py` overlaid. It excludes unrelated owner Python edits and contains no `.env`. The runner removes inherited TRACKING_/PG/PYTHON settings, sets synthetic hexadecimal credentials, local temporary mail, development mode and disabled live Google/Gmail. Database guards remain unchanged. Fresh `tracking_foundation_test` runs at `127.0.0.1:55433` in isolated Compose project `tracking-spec004-readiness-20261110`; native port 5432 and private configuration were not used.

| Check | Result |
|---|---|
| Full suite, project `.venv`, `python -m pytest -q -p no:cacheprovider` | **381 passed in 81.75 s**, no failures, skips or reported warnings; 194 unit/contract and 187 PostgreSQL cases. |
| `python -m ruff check app migrations tests` | All checks passed. |
| `python -m ruff format --check app migrations tests` | 72 files already formatted. |
| `python -m pip check` | No broken requirements. |

Only one new test was added to the prior 380-test suite. No dependency, migration, schema, role, infrastructure or OpenAPI change was made. Historical 196/380 results retain their original dates; the previously interrupted test run and missing failure output remain documented in the correction evidence.

## Entry gates and explicit deferrals

| Item | Next action | Blocks |
|---|---|---|
| PR 2 | Owner review and explicit merge decision; no merge executed here. | Starting 004 implementation branch from merged main. |
| 004 design | Review [entry packet](../../specs/004-event-collection/entry-review.md), resolve dependent Q-002/Q-004/Q-012 choices and approve concrete schema/contract. | Dependent code/schema and real customer intake. |
| Native rollout | Separate approved role/migration/readiness procedure; last verified native revision was 0004_identity on 2026-11-04. | Running this branch against native data, not synthetic design work. |
| Legacy mail | Approve/revise [T1/T2 proposal](../engineering/data-lifecycle.md#legacy-queued-mail-proposal-awaiting-owner-approval), then implement/test separately. | Claiming legacy-mail cleanup complete, not independent 004 design. |
| Consumers/production | Implement 004-020 obligations; review live-provider, mail, capacity, retention and restore requirements. | Their respective end-to-end/production acceptance. |

## Preservation

Pre-existing AGENTS.md/decision-register hunks, Python formatting edits and untracked review/handoff documents remain local and excluded from the follow-up. The two pre-existing added 001/002 checklist lines are preserved verbatim in the working tree and excluded from staging; current tracked status links actual closure evidence. Original reviews are not rewritten. No live provider or native operation was performed.

The result prepares 004 for concrete design review. It does not mark 004 implemented or make unresolved owner decisions.
