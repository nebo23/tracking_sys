# Independent merge review of Spec 016-A

Date: 2026-11-23 (Africa/Cairo). Authorization: D-073. Reviewed submission: `c1a4d6a0f5ef841694a7b0d1d438bb3e5d591b3d`. Base: `2a0c8e512e9ae29aecea7728f57ecd366807f178`. Scope: 016-A only; 016-B/C remain open.

## Findings and corrections

| ID | Priority | Reproduced behavior at the submitted head | Correction and regression evidence |
|---|---|---|---|
| R016-01 | P2 | Daily social values were labeled complete even with absent/short coverage; social and spend subtotals were labeled complete while a checkpoint held another page. A fully populated daily series could consequently qualify for comparison despite incomplete coverage. | Daily totals require complete stream coverage. Partial synchronization makes social/spend subtotals partial with `sync_in_progress` and blocks comparisons. Three daily unit cases, one spend unit case and four real JSON/CSV API cases fail before the fix and pass afterward. |
| R016-02 | P2 | An empty revenue CSV had no requested dates: its period existed only on value/total rows, which were absent. A compared empty export also lost both date ranges. | Every CSV now includes current and, when requested, previous period metadata independently of data rows. Two real API regressions compare the empty file's dates to JSON under the same revision. |
| R016-03 | P2 | A content item with no product type was correctly reported unsupported, but excluded from the applicability denominator; a subtotal from the remaining known items was then labeled complete. | An unknown product type keeps the known subtotal partial with `product_type_unknown`. A unit regression also verifies that a known product which does not offer the metric remains legitimately excluded. |

All eleven new regression cases failed on the submitted application code with the expected assertions, then passed after correction. The complete reporting unit/API/boundary selection passed **85 cases**. Contract version changes to `016a.2`, so a page/export revision obtained from the old behavior cannot silently reuse the corrected contract. The metric catalog remains `016a.1`. No schema, migration, dependency, provider operation or product scope was added.

## Review coverage

Inspected the reporting routes, shared contracts, complete metric catalog, source-native periods, social/spend/revenue calculation, typed CSV serialization, canonical digests, database input reads, bounds, revision pagination and final release checks. Traced the readers back to existing access resolution, connector checkpoints and ledger evidence/held-refund handling. Reviewed the new tests and checked the implementation against the approved D1-D12 design.

The permission boundary, full-scope totals before pagination, currency separation, non-additive metric handling, no-attribution fallback, direct CSV bounds and retained-export deferral remain intact. Independent semantic comparison of OpenAPI with the base confirms all **99 existing paths and 148 existing schemas unchanged**; the three report paths are added.

## Verification environment and commands

Used the existing project Python virtual environment and pinned dependencies. The independent database was a new `postgres:18.6-bookworm` container named `tracking016review-db`, bound only to `127.0.0.1:55433`, database `tracking_foundation_test`, with synthetic passwords and the repository's restricted-role initialization. The native database and owner environment files were not used. The disposable runner removed inherited `TRACKING_`, `PG` and `PYTHON` variables before supplying synthetic test settings.

The first sandboxed unit attempt could not complete loopback network-fixture tests and was stopped; the same baseline suite passed with loopback access enabled. A sandbox temporary-path mismatch prevented the first disposable container from initializing; only that review container was replaced using a stable ignored workspace scratch path. These setup attempts are not counted as successful verification.

Commands were run from `backend/` through the disposable runner:

| Check | Observed result |
|---|---|
| Submitted baseline: `pytest -m "not integration" -q` | 859 passed, 524 deselected, 17.16 s |
| Submitted baseline: `pytest tests/integration/test_reports.py tests/integration/test_report_bounds.py -q` | 23 passed, 58.75 s |
| New regressions before correction: `pytest tests/test_reporting.py tests/integration/test_reports.py -k r016 -q` | 11 failed with the expected behavior assertions; 70 deselected |
| Corrected reporting selection: `pytest tests/test_reporting.py tests/integration/test_reports.py tests/integration/test_report_bounds.py -q` | 85 passed, 59.39 s |
| Final unit/contract suite, including `016a.2`: `pytest -m "not integration" -q` | 864 passed, 530 deselected, 16.53 s |
| Final full integration suite | Running in four sequential batches of ten modules; results must be recorded before merge |
| `ruff check app tests`; `ruff format --check app tests` | Clean; 209 files formatted |
| `pip check`; `git diff --check` | Passed |

The final integration suite includes real browser journeys and every predecessor integration module. Tracker verification and final publication/merge observations are recorded after execution, not inferred from the implementer's earlier report.

## Remaining limitations and merge gate

The whole Spec 016 is not complete. 016-B still requires 006, 007-B/C and persisted 008 integration; 016-C retains scheduled/white-label reports and the full AC5/003 retained-export revocation obligations. The 200-evidence financial cap contains but does not solve A3. Development limits are not production SLOs. Specs 012/013, live providers, native rollout and deployment remain separately gated. CI activation remains an owner decision; local results are not GitHub checks.

The owner authorized opening a PR and merging under D-073. Merge only after final verification is complete, the exact remote head and current main are checked, and applicable GitHub checks/reviews permit it. No merge has been claimed by this in-progress record.
