# Spec 016-A implementation evidence

Date: 2026-11-22. Decision: D-072 (owner approval of D1-D12 as recommended, without pull request authorization). Branch: `codex/spec-016-analytics-reporting`. Scope: slice 016-A only. Spec 016 as a whole, 016-B and 016-C remain open.

Subsequent D-073 independent verification and the three corrected merge-review findings are recorded in the [2026-11-23 review](merge-review-2026-11-23.md). The results below remain the original implementation evidence.

## Baseline and commits
| Item | Value |
|---|---|
| Merged `main` | `2a0c8e5` (Spec 015, PR 13); `origin/main` unchanged when work started |
| Preparation head | `6ef1b59` (D-071) |
| Decision record | `f4c92d0` (D-072 in the register and the working agreement) |
| Implementation | `aa8e211` (code, unit and integration tests, OpenAPI snapshot) |
| Documentation and evidence | the commit that adds this file; it also strengthens the V19 integration case |

No migration, table, role, dependency, setting, provider call or frontend file changed. `git diff 2a0c8e5 -- backend/migrations backend/requirements*.txt frontend packages` is empty.

## Implemented
- `app/reporting/`: the pure contracts (catalog, periods, digests, social, spend, revenue, CSV).
- `app/services/reporting.py`: the snapshot reads, the revision and the release check.
- `app/api/reports.py`: the three routes.
- The behavior is described in the [reporting guide](../../docs/engineering/reporting.md).
- [design](design.md) section 8 records the implementation choices the design left open.

## Environment
- Windows 11 Pro and Python 3.12.4 in the project virtual environment, with the pinned requirements; `pip check` found no broken requirements.
- PostgreSQL `postgres:18.6-bookworm` as Compose project `tracking016`, running only the `database` service on 127.0.0.1:55433 (database `tracking_foundation_test`). The env file was synthetic and in the scratchpad. The runner dropped inherited `TRACKING_`, `PG` and `PYTHON` variables. Port 55433 was not reserved that day.
- Node 24.17.0 with Playwright 1.64.1. For the tracker and browser runs, `packages/tracker-js/node_modules` was a temporary junction to the 005 worktree's installed copy, removed afterwards.
- The native `tracking_sys` database and the owner's `.env` were not used.

## Results
| Check | Command (from `backend/`, through the disposable runner) | Result |
|---|---|---|
| Lint and format | `ruff check app tests`; `ruff format --check app tests` | Clean (209 files) |
| Unit and contract | `pytest -m "not integration"` | 859 passed, 524 deselected, 16.0 s (808 before 016-A, plus 51 in `tests/test_reporting.py`) |
| Integration, batch 1 | `test_access_api` to `test_connector_coverage` (9 modules) | 185 passed, 190.0 s |
| Integration, batch 2 | `test_connector_instagram` to `test_connectors` (7 modules) | 67 passed, 109.6 s |
| Integration, batch 3 | `test_conversion_delivery` to `test_paymob` (12 modules) | 128 passed, 130.8 s |
| Integration, batch 4 | `test_postgres` to `test_whatsapp` (12 modules, `TRACKING_RUN_BROWSER_TESTS=1`) | 144 passed, 133.0 s, including the 3 browser journeys and the 23 new report cases |
| Tracker | `npm test`; `npm run test:browser` in `packages/tracker-js` | 67 passed; 44 passed (Chromium and Firefox), 60.9 s |
| OpenAPI | regenerated with the unit-test settings | 124 operations across 102 paths (121 across 99 before); the three report routes and their schemas are new; no existing path or schema changed, and `info.description` gains one sentence |

In total: 1,383 backend cases passed, with no failure and no skip. The integration suite ran in four foreground batches on one disposable database, because of the workstation's memory limit recorded in the D-069 evidence.

The full runs used the tree later committed as `aa8e211`, before one test-only change: the removal of two unused helpers from `tests/integration/report_support.py`. After that change the report modules ran again (75 passed). The documentation commit adds the stronger V19 case. On that final tree, Ruff, the unit suite (859 passed) and both report modules (23 passed) ran again.

## Verification matrix
Unit cases are in `tests/test_reporting.py`; integration cases are in `tests/integration/test_reports.py` (`test_reports`) and `tests/integration/test_report_bounds.py` (`test_report_bounds`).

| ID | Cases | Result |
|---|---|---|
| V01 | `test_v01_foreign_scopes_reveal_nothing` | Passed: foreign client, foreign agency, foreign connection and unknown connection IDs all answer `403 access_denied`; no other client's values appear |
| V02 | `test_v02_permission_matrix_for_people_and_keys` | Passed. Owner and Admin read all three families. Analyst and client viewer read social only. The viewer with a financial grant on A2 reads A2 spend and revenue. Other agencies are refused. A read key with the financial flag reads all; one without it reads social only. Ingest, expired, revoked and demoted-creator keys answer `401`. A social answer has no financial field |
| V03 | `test_v03_revocation_before_release_sends_no_report[json, csv]`, `test_v03_source_changes_before_release_refuse_the_report[json, csv]` | Passed. Each change is made in the release hook, after the result was built. A revoked grant gives `403`, a revoked key `401` and an archived client `403`. A changed generation, changed record or deleted records give `409 report_changed`; a disconnecting connection gives `409 source_unavailable`; evidence appended during the read gives `report_changed`. No report value appears in any refused answer |
| V04 | `test_reach_stays_two_observations_while_views_total_twenty_two`, `test_catalog_classes_follow_the_reviewed_semantics`, `test_v04_v08_daily_semantics_and_independent_stream_states` | Passed: reach 10 and 12 stays two rows with a `null` total; views total 22; snapshots are excluded and never summed; no cross-platform route exists |
| V05 | `test_content_cohort_reports_lifetime_values_without_period_claims`, `test_youtube_cohort_uses_publication_times_and_keeps_averages_apart`, `test_v05_v08_youtube_cohort_and_unknown_combinations` | Passed. Results are labeled `published_cohort_lifetime` and cannot be compared. Averages are never totaled. An unknown product type is `unsupported`. Snapshot metrics are refused (`unsupported_metric`) and a generic connection is refused (`not_a_social_connection`) |
| V06 | `test_periods_are_half_open_bounded_calendar_dates`, `test_pacific_daylight_saving_days_stay_calendar_days`, `test_v06_native_day_boundaries_and_rejected_periods` | Passed: UTC, Pacific and account-local boundaries are exact. The 23-hour and 25-hour Pacific days stay single dates. Reversed, empty and 32-day periods are refused, as are time zone, "as of" and repeated parameters. A zoneless spend connection is `not_synced` |
| V07 | `test_comparison_needs_complete_fresh_final_compatible_periods`, `test_youtube_days_follow_pacific_dates_and_definition_changes`, `test_spend_comparison_per_currency`, `test_v07_previous_period_comparisons` | Passed: the previous period has equal length; differences come only from complete, final, fresh and compatible periods; a zero baseline gives `null` with `zero_baseline`; partial, stale and provisional periods keep both values without a percentage; a definition change blocks the comparison |
| V08 | `test_absent_days_are_never_zero_and_partial_totals_are_labeled`, `test_stored_missing_reasons_and_invalid_values_stay_distinct`, `test_content_cohort_total_is_complete_only_with_proven_inventory`, `test_v04_v08_daily_semantics_and_independent_stream_states` | Passed. The account stream's success leaves the media stream `not_synced`/`never_synced`. Missing, not-synced, invalid, conflicting, unsupported and below-threshold states stay distinct. A stale stream and a read between pages are labeled. A switched-off adapter is `unavailable` and a registered one `available` |
| V09 | `test_refund_activity_follows_its_own_date_with_the_sale_outside_the_period`, `test_v09_refund_activity_with_the_sale_outside_the_period` | Passed: February shows -20.00 only, with the January sale outside the period; January shows +100.00 |
| V10 | `test_duplicates_declarations_and_unresolved_items_stay_separate`, `test_v10_duplicates_declarations_pending_and_held_refunds` | Passed. A duplicate delivery posts once. The declaration stays in the `declared` block. A pending refund (`parent_missing`) and a held wrong-order Paymob refund (`parent_order_mismatch`) add no verified impact, and their counts carry `scope: all_evidence`. No reason, reference or operation ID appears in JSON or CSV |
| V11 | `test_spend_keeps_currencies_and_missing_objects_apart`, `test_currencies_stay_apart_and_conflicting_exponents_fail`, `test_v11_currencies_stay_apart_and_exponent_conflicts_fail` | Passed. EGP and USD stay separate for the same ad set, and a missing object ID is its own row; a page size of 1 traverses all three groups. Revenue is per currency, and a second EGP exponent answers `409 currency_exponent_conflict`. `external_completeness` is `unknown` |
| V12 | `test_percentages_are_exact_and_never_infinite`, `test_digests_are_canonical`, `test_v12_complete_totals_deterministic_pages_and_revisions` | Passed. 720 rows were traversed once each at page sizes 500 and 7, in identical order and with identical totals. A later page without a revision answers `422 revision_required`, a wrong revision `409` and a page past the end `422 invalid_page`. Another principal or another filter changes the revision; page and format do not |
| V13 | `test_v13_changed_inputs_never_mix_revisions` | Passed: a modified, inserted or deleted record makes the next page `409 report_changed`; a previous-period change alters the revision of a compared report; there is no "as of" read |
| V14 | `test_v14_v18_social_bound_is_exact`, `test_v14_v18_spend_bound_counts_refused_rows_and_both_periods`, `test_v14_v18_revenue_bound_counts_the_whole_client` | Passed. 10,000 media records are accepted and 10,001 answer `422 report_too_large`. 10,000 spend facts across both periods, 1,000 of them refused, are accepted, and 10,001 are refused. 200 evidence records are accepted and 201 answer `409 report_requires_ledger_upgrade`, although the period holds one record. The journal function was replaced with one that fails, and was never called |
| V15 | `test_csv_row_and_byte_bounds_refuse_whole_files`, `test_default_csv_bounds_are_the_approved_values`, `test_v15_csv_matches_json_under_one_revision`, `test_v15_v18_csv_row_bound_is_exact` | Passed. CSV and JSON give the same totals, comparisons and value rows under one revision. CSV page parameters are refused. 5,000 records are accepted and 5,001 answer `422 export_too_large` as JSON. The byte bound counts encoded bytes, including two-byte characters, and refuses the whole file |
| V16 | `test_identifiers_are_prefixed_and_quoted` (9 identifiers), `test_unexpected_cells_are_refused_not_coerced` (17 cells), `test_v16_csv_cells_are_typed_and_carry_no_private_text` | Passed. Identifiers with `=`, `+`, `-`, `@`, delimiters, CR/LF, quotes and full-width or minus look-alikes are written `id:`-prefixed and quoted. Negative amounts stay numbers. Unexpected types and forms are refused. No connection label, client name or external account ID appears in the file, and no identifier appears in the logs; titles are absent too (V05) |
| V17 | `test_v17_v19_no_storage_and_dependency_states`, the full backend suite | Passed: the set of public tables is unchanged by report requests; every answer has `Cache-Control: no-store`; V03 shows that output starts only after the release check; all predecessor cases pass |
| V18 | the four `test_report_bounds` cases (measurements below) | Passed within the agreed 120-second test timeout and 60 statements per request |
| V19 | `test_v17_v19_no_storage_and_dependency_states`, `test_v19_won_crm_deals_never_become_revenue_or_funnels` | Passed. Attribution, content revenue, funnels and ROAS are `dependency_unavailable` in all three families and in CSV, with no number. A won CRM deal of 1500.00 EGP under an approved won rule adds nothing to the revenue report, and no funnel is derived. LinkedIn and X stay deferred |

## Measurements (V18)
These are observations on the workstation with the disposable database, measured twice on the committed code; they are not service objectives. Times are the full request through the test client, including both snapshot reads.

| Case | Status | Seconds (two runs) | Response bytes | SQL statements |
|---|---|---|---|---|
| Social cohort, 10,000 records, first page | 200 | 1.182, 1.198 | 51,416 | 30 |
| Same, last page of 500 rows | 200 | 1.232, 1.258 | 209,752 | 30 |
| Social cohort, 10,001 records | 422 | 0.016, 0.017 | 28 | 11 |
| Spend, 9,999 current facts | 200 | 0.714, 0.725 | 18,576 | 28 |
| Spend, 10,000 facts across both periods | 200 | 0.627, 0.630 | 19,649 | 28 |
| Spend, 10,001 facts across both periods | 422 | 0.017, 0.017 | 28 | 12 |
| Revenue, 200 evidence records | 200 | 0.546, 0.550 | 1,578 | 19 |
| Same, compared | 200 | 0.382, 0.383 | 3,645 | 19 |
| Revenue, 201 evidence records | 409 | 0.014, 0.018 | 42 | 10 |
| Spend CSV, 5,000 records | 200 | 0.228, 0.254 | 1,144,682 | 28 |
| Spend CSV, 5,001 records | 422 | 0.053, 0.055 | 28 | 16 |

The statement count does not grow with the number of rows, and an excess fails after the bounded count, before any row is loaded. The 200-record revenue bound costs about half a second; the release check compares only the evidence digest and does not recalculate the ledger. Earlier, while the check still recalculated, the same case took 0.883 s. The 200-record bound therefore stays as approved; A3 (ledger scaling) remains the follow-up for 007-B.

## Mutation spot checks
`mutations_016.py` (scratchpad) changed one safeguard at a time and ran its cases on the disposable database, restoring each file byte for byte (SHA-256 checked). All eleven mutants were caught:

| Mutant | Caught by |
|---|---|
| The release check ignores changed inputs | V03 source changes |
| The release check skips the fresh authorization | V03 revocation |
| Every metric is summable | unit (reach) |
| The evidence bound is off by one | V14 revenue |
| The source bound is off by one | V14 spend |
| Identifier cells lose their prefix | unit (V16) |
| The revision ignores the principal | V12 |
| Later pages need no revision | V12 |
| Spend groups ignore the currency | unit and V11 |
| Revenue dates follow the sale instead of each posting | unit and V09 |
| Comparisons ignore partial periods | unit (V07) |

## Limitations and open items
- 016-A closes only its own checklist. Acceptance criteria 1 to 4 are advanced for the three implemented families. Acceptance criterion 5 (short-lived authorized export URLs and deletion-driven revocation) and the D-025 cache and export obligations of 003 remain open for 016-C. There is no stored export, so already downloaded files are outside server revocation.
- Attribution, funnels, content revenue, model comparisons and ROAS wait for 006 implementation, 007-B/C and persisted 008 (016-B). LinkedIn and X stay deferred (D-063).
- The bounds are development values; production capacity and freshness objectives need Q-004 and Q-011. A3 (repeated full-ledger calculation) is unchanged and is contained only by the 200-record guard.
- No continuous integration exists (A2); every result above is a local run.
- No pull request was opened and nothing was merged; both need the owner's authorization.
