# Spec 016-B evidence: attribution reports

Implemented on `codex/spec-016b-attribution-reports` under D-089 (decisions D1-D14 of the [entry review](entry-review-016b.md), approved as recommended without amendment), following the [implementation handoff](implementation-prompt-016b.md) and the [design note](design-016b.md). The branch starts from `claude/keen-fermat-otlr9d` at `7435545` (merged `main` at `f15b6e4` plus the D-080, D-088 and D-089 records). `origin/main` had not moved beyond `f15b6e4` when the work started, so nothing was merged in. All data is synthetic, every database case ran on the disposable PostgreSQL 18 service, and nothing called a provider. Recorded 2026-11-26.

## Commits

| Phase | Commit | Content |
|---|---|---|
| P0 | `f0485b6` | Design note: statements, answers, states, CSV columns, the `0030` DDL and the BV01-BV20 test inventory |
| P1 | `4785554` | Attribution report (groups and models views), reconciliation, the dependency block and contract `016b.1` |
| P2 | `a05e8e8` | `utm_content` adapter change with its one-time rebuild, `roas_from_credit` and the ROAS report |
| P3 | `fd07c03` | Migration `0030_reporting_indexes` and the funnel report |
| P4 | `e2d61a8` | Conversions list, the change token on the list and the runs route (O1), the status snapshot (O2) |
| P5 | `6404f22` | BV19 bounds and measurements; the conversion counts join by key |
| P5 | the commit that adds this file | Test cleanup of bulk rows, the reconciliation zero-floor regression, evidence and documentation |

## What was built

- **Attribution report** (`GET /reports/attribution`): stored credit of the published generation by campaign, content, link or recipient class, on the UTC conversion date, under one model version (`view=groups`) or every active version side by side (`view=models`). Direct and unknown credit are rows of their own; registered flags and, for content, the social content items with the same ID are named. Totals are per currency and recipient class; a reconciliation compares credited revenue with the persisted ledger's verified net per currency.
- **ROAS report** (`GET /reports/roas`): one spend connection on account-local dates, rows per ad, ad set or campaign from `app.advertising.roas.roas_from_credit`, which shares the row rules and roll-up with `roas_report`; credited leads and the cost per lead; unmatched credit apart; the 016-A spend source status.
- **Funnel report** (`GET /reports/funnel`): tracked visits (consented link page views on their received date), credited leads, credited sales and credited revenue per campaign, content or link and for the client, with each stage's basis and no rate.
- **Conversions list** (`GET /attribution/conversions`): the person-level list of stored conversions with the latest revision under one version, cursor pages, filters, the stale barrier and the change token.
- **Adapter and rebuild (D7)**: `utm_content` is the content reference of a campaign interaction without a managed-link content reference; input adapter revision 2 joins the model-set digest, so each client rebuilds once.
- **Release corrections (D11)**: the runs route and the list refuse an answer when the change token moved while it was built (O1); the status route reads in one snapshot (O2).
- **Migration `0030_reporting_indexes`**: two indexes, no other schema change.
- **Dependency block**: every family, the 016-A ones included, reports the four capabilities as `available` with the family that serves them; the contract version is `016b.1`.

## Verification

### Commands and counts

All Python commands ran from `backend/` with the project virtual environment; database cases used `tracking_foundation_test` on 127.0.0.1:55433 (Compose project `tracking-test-016b`, recreated before the full run). Port 55433 was not reserved that day.

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check app tests migrations` | clean |
| Format | `ruff format --check app tests migrations` | 295 files formatted |
| Unit | `pytest -m "not integration" -q` | **933 passed** (690 deselected), 16.2 s |
| Integration, batch 1 | `test_access_api` to `test_attribution_store` (11 modules) | **129 passed, 6 skipped**, 257.8 s |
| Integration, batch 2 | `test_auth` to `test_collection` (4 modules) | **126 passed**, 192.3 s |
| Integration, batch 3 | `test_connector_coverage` to `test_google` (14 modules) | **132 passed**, 281.8 s |
| Integration, batch 4 | `test_identity` to `test_paymob` (13 modules) | **111 passed**, 242.3 s |
| Integration, batch 5 | `test_postgres` to `test_review_006_007` (9 modules) | **101 passed, 1 skipped**, 196.7 s |
| Integration, batch 6 | `test_roas` to `test_whatsapp` (6 modules, browser journeys included) | **84 passed**, 95.6 s |
| Regression added after batch 1 | `test_attribution_reports.py` (with the zero-floor case) | **15 passed** |
| Tracker unit | `node --test test/unit/*.test.js` (from `packages/tracker-js`) | **73 passed** |
| Tracker browser | `node --test --test-concurrency=1 test/browser/*.test.js` | **50 passed** (Chromium and Firefox) |
| Dependencies | `pip check` | no broken requirements |
| Whitespace | `git diff --check` | clean |
| Links | relative-link check of the changed Markdown | every local target exists |

The integration batches ran with `TRACKING_RUN_BROWSER_TESTS=1`, so the three backend browser journeys of `test_tracker_journey.py` ran and passed. Together the batches cover all 57 integration modules: **683 passed and 7 skipped**. The 7 skipped cases are opt-in measurements, reported as skipped, not passed: 3 AV16 cases (`TRACKING_ATTRIBUTION_MEASURE`), 3 BV19 cases (`TRACKING_REPORT_MEASURE`, run separately below) and 1 review measurement (`TRACKING_REVIEW_MEASURE`). The tracker's Playwright 1.64.1 browsers came from the 005 worktree's installed copy through a directory junction, removed afterwards; the tracker package is unchanged on this branch.

`frontend/` on this branch holds only placeholder READMEs, with no `package.json`: pull request 17 (Spec 018) has not merged, so the frontend drift checks do not apply yet.

### BV01-BV20

Test modules are under `backend/tests/` (integration modules under `integration/`).

| Case | Tests | Result |
|---|---|---|
| BV01 Isolation | `test_attribution_reports::test_bv01_isolation_across_agencies_clients_and_versions`; `test_roas_reports::test_roas_isolation_permissions_and_periods`; `test_funnel_reports::test_funnel_isolation_permissions_and_comparison`; `test_attribution_conversions::test_bv15_scrub_pages_filters_finance_and_keys` | passed |
| BV02 Permissions | `test_attribution_reports::test_bv02_lead_credit_without_finance_and_key_rules`; the ROAS, funnel and list tests above | passed |
| BV03 Credit equals stored allocations | `test_attribution_reports::test_bv03_credit_equals_stored_allocations_and_reconciles`; `test_attribution_reporting::test_groups_keep_direct_and_unknown_apart` | passed |
| BV04 Revisions | `test_attribution_reports::test_bv04_refund_late_touch_owner_change_and_moved_sale` | passed |
| BV05 Periods | `test_attribution_reports::test_bv05_utc_bounds_to_the_microsecond_and_refusals`; `test_roas_reports::test_roas_isolation_permissions_and_periods` (25-hour day in `America/Los_Angeles`, invalid zone) | passed |
| BV06 Comparison | `test_attribution_reporting::test_comparisons_are_exact_and_blocked_when_not_authoritative`; `test_attribution_reports::test_bv06_comparison_of_equal_periods`; `test_roas_reports::test_roas_comparison_pages_release_and_csv`; `test_funnel_reports::test_funnel_isolation_permissions_and_comparison` | passed |
| BV07 Model comparison | `test_attribution_reports::test_bv07_models_view_side_by_side` | passed |
| BV08 Groups | `test_attribution_reports::test_bv08_groups_flags_and_social_content_pointer` | passed |
| BV09 Currency and fractions | `test_attribution_reporting::test_exact_fractions_and_half_even_text`; `test_attribution_reports::test_bv09_currencies_stay_apart_and_thirds_sum_to_one` | passed |
| BV10 Freshness | `test_attribution_reports::test_bv10_not_ready_behind_rebuild_failed_and_ledger_unavailable` | passed |
| BV11 ROAS equals the contract | `test_attribution_reporting::test_roas_from_credit_equals_roas_report`; `test_roas_reports::test_bv11_roas_from_stored_credit_equals_the_contract` | passed |
| BV12 ROAS join and adapter | `test_roas_reports::test_bv12_join_needs_campaign_and_ad_of_the_connection`, `::test_bv12_adapter_change_rebuilds_once_and_keeps_history` | passed |
| BV13 Cost per lead | `test_attribution_reporting::test_cost_per_lead_rules`; `test_roas_reports::test_bv13_cost_per_lead` | passed |
| BV14 Funnel | `test_funnel_reports::test_bv14_visits_are_consented_link_page_views_of_the_client`; `test_attribution_report_bounds::test_bv14_link_event_bound` (50,000 pass, 50,001 refused) | passed |
| BV15 Conversions list | `test_attribution_conversions::test_bv15_stale_while_behind_and_after_withdrawal`, `::test_bv15_scrub_pages_filters_finance_and_keys`, `::test_bv15_commit_during_build_refuses_list_and_runs` (6 cases: erasure, worker pass and revocation, for the list and the runs route), `::test_bv15_status_reads_one_snapshot` | passed |
| BV16 Pages and revision | `test_attribution_reports::test_bv16_pages_and_revision`; the ROAS and funnel page tests | passed |
| BV17 Release race | `test_attribution_reports::test_bv17_release_race` (worker pass, scrub, default model, revoked finance and client grants; JSON and CSV); `test_roas_reports::test_roas_comparison_pages_release_and_csv` (spend fact); `test_funnel_reports::test_funnel_pages_release_and_csv` (new visit) | passed |
| BV18 CSV | `test_attribution_reports::test_bv18_csv_equals_json_and_bounds`; `test_attribution_reporting::test_csv_identifier_prefix_and_record_bound` (5,000 records pass, 5,001 refused, 2 MiB bound); the ROAS and funnel CSV tests | passed |
| BV19 Bounds and measurements | `test_attribution_report_bounds::test_bv19_group_bound` (10,000 pass, 10,001 refused before any total), `::test_bv19_statements_do_not_grow_with_credit_rows`, `::test_bv19_measurements` (opt-in, below) | passed |
| BV20 Existing behavior | `test_reports::test_v17_v19_no_storage_and_dependency_states` (dependency block); `test_attribution_models::test_bv20_0030_upgrade_from_populated_0029_and_downgrade`; the full suites above (AV, R008, 006, 007, 014 and 015 included); the OpenAPI comparison below | passed |

`test_attribution_reports::test_reconciliation_counts_a_negative_net_as_zero` was added for the zero-floor mutation.

### Mutation check

`mutations_016b.py` (a scratch script, not committed) disabled each safeguard in turn, ran its tests on the disposable database, and restored the source byte for byte; the SHA-256 of every touched file was compared before and after, and all matched. **12 of 12 were caught.**

| Safeguard disabled | Tests that failed |
|---|---|
| Published-generation filter of the credit read | BV10 (staged credit of a new version became visible during a rebuild) |
| Finance split (sale values built for every reader) | BV02 attribution and funnel permission tests |
| Finance scope recheck before release | BV17 (a revoked financial flag no longer refused) |
| Change token in the release check (tokens left out of the inputs digest) | BV17 and BV16 |
| Stale barrier of the conversions list | BV15 stale case |
| Change token recheck of the list and the runs route | BV15 commit-during-build cases |
| Status read outside one snapshot (O2) | BV15 status case |
| `id:` prefix of identifier cells | BV18 |
| 10,000 group bound | BV19 group bound |
| Campaign ID test of the ad match | BV12 join |
| Client scope of the visit count | BV14 |
| Zero floor of the reconciliation's ledger net | the zero-floor regression |

### Measurements (BV19)

One report of each family over synthetic stored credit inserted by the migration role (one sale conversion, run, allocation and credit change per row, 200 groups), on the development workstation under memory pressure (about 1 GB free), after one warm-up request. These are observations, not SLOs; A3 stays open.

| Stored credit rows | Attribution (groups) | Attribution (models) | ROAS | Funnel | Seeding |
|---|---|---|---|---|---|
| 1,000 | 0.246 s, 44 statements | 0.107 s, 44 | 0.106 s, 48 | 0.123 s, 52 | 0.27 s |
| 10,000 | 0.190 s, 44 | 0.203 s, 44 | 0.091 s, 48 | 0.239 s, 52 | 1.41 s |
| 100,000 | 2.191 s, 44 | 1.881 s, 44 | 0.304 s, 48 | 2.404 s, 52 | 18.05 s |

The statement count is the same at every size. The ROAS report aggregates only by campaign and content reference and needs no conversion counts, which explains its lower cost.

### OpenAPI

`contracts/openapi.json` was regenerated and compared semantically with `main` (`f15b6e4`): 128 paths and 151 operations against 124 and 147. Four paths were added (`/reports/attribution`, `/reports/roas`, `/reports/funnel`, `/attribution/conversions`) with 42 new schemas; no existing path changed; the only changed schema is `Dependency` (`state` gains `available`, and the optional `family` names the serving report family), as documented. No new class name collides with an existing one.

## Findings during implementation

- **Planner on fresh tables.** The first measurement at 10,000 runs hit the 3-second statement timeout: the conversion count joined allocations and conversions with a client constant, so on tables without statistics the planner scanned a client-wide index (the new `0030` index) for every run, 11.6 seconds. Both joins now use the key alone, 75 milliseconds; the runs are scoped by agency and client, and the joined rows are bound to the same client by scoped foreign keys.
- **Bulk test rows.** Under memory pressure, the shared teardown, which deletes every table row by row, outlasted its statement timeout on 50,000 copied events. The bulk tests now truncate their own rows first; this is test-only.
- **Test journeys.** An event dated before its subject's identity link is never assigned to the person, and a lead cannot be dated ahead, so the tests place touches and leads at the current time and sales on future dates.
- **Negative nets.** The ledger keeps a transaction's net at zero or above (an oversized correction stays pending), so the reconciliation's zero floor is defensive; its regression sets the stored projection directly.

## Limits

- Comparisons cover the report totals, not each group (design section 11).
- The conversions list places a conversion at its stored conversion time; a sale whose time a later receipt corrects keeps its opening time in the list, while its runs and the reports use the corrected time (`latest_run.window_end`).
- A revision covers the attribution status and watermarks, so pages and releases refuse whenever the worker writes, a feed record arrives or a consent grant lapses; under continuous intake, a long pagination can keep answering `report_changed`.
- Visits count every stored page view with a link ID, whatever its traffic label, as the attribution touches do.
- ROAS answers `409 day_zone_unknown` for a never-synced spend connection without any zone.
- Measurements are development observations at synthetic sizes; A3, Q-004 and Q-011 stay open.

## What remains

016-C (retained, scheduled and white-label reports and full AC5), the React UI, native `tracking_sys` migration (0005-0030), live providers, production scheduling (020) and deployment. The merge of this branch is the owner's decision after review.
