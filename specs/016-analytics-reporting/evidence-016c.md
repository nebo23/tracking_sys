# Spec 016-C evidence: retained exports, scheduled reports and the white-label delivery contract

Recorded: 2026-11-27 under D-095. Scope: decisions D1-D14 of the [016-C entry review](entry-review-016c.md), approved as recommended without amendment, implemented under the [implementation handoff](implementation-prompt-016c.md) and the [design note](design-016c.md). Every check below ran with synthetic data on the disposable PostgreSQL service; nothing touched the native `tracking_sys` database.

## Branch and commits

`codex/spec-016c-report-delivery` was created from `origin/claude/keen-fermat-otlr9d` at `5541091`; `06d6a19` (PR 19) is its ancestor, and `origin/main` stayed at `06d6a19` throughout, so no merge was needed. Each phase was pushed after its checks (D-051), and [pull request 20](https://github.com/nebo23/tracking_sys/pull/20) was opened against `main` at `5a79278` for review; it is not merged.

| Phase | Commit | Content |
|---|---|---|
| P0 | `d01bcb6` | Design note: inventory, schema, requests, visibility, the export lock and reservation, periods, worker, email, PNG checks, test inventory |
| P1 | `3894e12` | Migration `0032_report_delivery`, models, data policy rows, retained exports (create, list, read, download, revoke), sealing, lifecycle deletion; RV01-RV05, RV09, RV18 |
| P2 | `159ac37` | Revocation from the 004 and 006 erasures, the erasure of held events, `start_disconnect` and client archival; RV06-RV08 |
| P3 | `4d14aa7` | Schedules, `python -m app.report_worker`, `report_ready` emails; RV10-RV16, RV19 (schedules) |
| P4 | `a2310b2` | Branding profile and logo, route limit, display name in emails; RV17, RV19 (branding) |
| P5 | `563e88f` and the documentation commit | RV13 test isolates the owner role check; this evidence, the guides and the status lines |

The P3 commit message says the snapshot gained seventeen schemas; the correct number for P3 is eleven (twenty after P3, twenty-three after P4).

## Environment

- Disposable PostgreSQL 18.6 in the Compose project `tracking-system-foundation-test` on `127.0.0.1:55433` (`tracking_foundation_test`), with a synthetic environment file in the session scratchpad. The project was recreated (`down -v`, `up --wait`) before the final suite.
- Python 3.12.4 in the project virtual environment; Node.js 24.17.0. No dependency was added or changed.
- The tracker's browser tests used Playwright 1.64.1, the version `packages/tracker-js/package.json` pins, from another worktree's installation through a directory junction, removed after the run.
- Free memory was 0.3-1.7 GB and free disk 4.3-6.9 GB during the runs, so the integration suite ran in foreground batches.

## Verification matrix

| Case | Tests | Result |
|---|---|---|
| RV01 Export creation | `test_report_exports.py`: `test_rv01_rv03_every_family_exports_the_direct_csv` (six families), `test_rv01_parameters_and_bounds`, `test_rv01_client_viewer_exports_what_it_reads`, `test_rv01_keys_and_foreign_scopes_refused`, `test_rv01_fifty_unexpired_exports`, `test_rv01_missing_keyring_not_configured` | passed |
| RV02 Encryption | `test_report_delivery_contract.py::test_rv02_seal_is_bound_to_export_agency_and_client`; `test_report_exports.py`: `test_rv02_no_plaintext_stored`, `test_rv02_copied_ciphertext_does_not_open` | passed |
| RV03 Download | `test_rv01_rv03_every_family_exports_the_direct_csv` (byte for byte equal to the direct CSV of the same revision, attachment, `no-store`), `test_rv03_scope_resolved_again`, `test_rv03_sale_values_need_finance`, `test_rv03_revoked_or_expired_export_gone` | passed |
| RV04 Visibility | `test_rv04_visibility` | passed |
| RV05 Manual revocation | `test_rv05_manual_revocation` | passed |
| RV06 Erasure | `test_report_revocation.py`: `test_rv06_subject_erasure_revokes_earlier_exports`, `test_rv06_person_erasure_revokes_earlier_exports`, `test_rv06_held_event_erasure_revokes`, and with real concurrency `test_rv06_reservation_during_erasure_is_rebuilt`, `test_rv06_erasure_waits_for_reservation` (a waiting advisory lock in `pg_locks`), `test_rv06_erasure_waits_for_store_and_revokes` (a waiting transaction lock) | passed |
| RV07 Disconnection and purge | `test_rv07_disconnection_revokes_its_exports_only`, `test_rv07_every_disconnection_cause_revokes` (five causes), `test_rv07_purge_revokes` | passed |
| RV08 Archival | `test_rv08_archival_revokes`, `test_rv08_closing_agency_exports_unreachable` | passed |
| RV09 Expiry | `test_rv09_lifecycle_deletes_expired_exports` (batches of 2 as `tracking_lifecycle`, a second run deletes nothing) | passed |
| RV10 Schedule rules | `test_report_schedules.py`: `test_rv10_schedule_validation`, `test_rv10_managers_only`, `test_rv10_ten_active_schedules`, `test_rv10_recipients` | passed |
| RV11 Periods | `test_report_delivery_contract.py`: `test_rv11_periods`, `test_rv11_daylight_saving_runs`, `test_rv11_month_ends`, `test_rv11_invalid_timing` (six cases) | passed |
| RV12 Worker | `test_rv12_due_schedule_runs_once_under_two_workers` (two concurrent passes meet at a barrier inside their builds), `test_rv12_next_slot_and_missed_slot`, `test_rv12_pass_is_bounded` | passed |
| RV13 Run permissions | `test_rv13_owner_without_access_pauses`, `test_rv13_recipients_without_access_skipped` | passed |
| RV14 Email | `test_rv14_report_ready_email` (outbox entry, expiry, local `.eml`, text without figures, client name or token); `test_report_delivery_contract.py::test_rv14_email_text` | passed |
| RV15 Stop states | `test_rv15_stop_states_get_no_run` (suspended, closing and closed agency; archived client) | passed |
| RV16 Failures | `test_rv16_failures` | passed |
| RV17 Branding | `test_report_branding.py`: `test_rv17_profile`, `test_rv17_logo`, `test_rv17_emails_carry_the_display_name`; `test_report_delivery_contract.py::test_rv17_png_checks` | passed |
| RV18 Migration | `test_report_delivery_migration.py`: `test_rv18_upgrade_from_populated_0031`, `test_rv18_grants`, `test_rv18_downgrade_refuses_stored_rows`; `test_tenancy.py::test_migration_matches_model_metadata`; the data policy tests (96 tables) | passed |
| RV19 Isolation and logs | `test_report_schedules.py::test_rv19_no_data_in_logs_or_output`, `test_report_branding.py::test_rv19_isolation`, with the foreign-scope cases of RV01, RV04 and RV10 | passed |
| RV20 Existing behavior | every existing suite below; the direct CSV comparison of RV03; the OpenAPI snapshot compared with `main` | passed |

## Commands and counts (final code at `563e88f`; the documentation commit changes no code)

From `backend/`, through a runner that drops inherited `TRACKING_`, `PG` and `PYTHON` variables and points at the disposable service:

| Check | Result |
|---|---|
| `ruff check app tests migrations` | All checks passed |
| `ruff format --check app tests migrations` | 324 files already formatted |
| `pytest -m "not integration" -q` | 969 passed, 800 deselected (949 at the start of the slice) |
| `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1` | 800 collected (746 at the start): 793 passed, 7 skipped, 0 failed, in ten batches |
| `node --test test/unit/*.test.js` (tracker) | 73 passed |
| `node --test --test-concurrency=1 test/browser/*.test.js` (Chromium and Firefox) | 50 passed |
| `pip check` | No broken requirements found |
| `git diff --check origin/main...HEAD` | clean |
| Relative links of the 20 changed or new Markdown files | 382 local targets checked, none broken |

The seven skipped cases are opt-in measurements, never reported as passed: three need `TRACKING_REPORT_MEASURE=1` (BV19), three `TRACKING_ATTRIBUTION_MEASURE=1` (AV16) and one `TRACKING_REVIEW_MEASURE=1`. The browser journeys of `test_tracker_journey.py` ran. Batch 2 shows one `UnsupportedFieldAttributeWarning` about the `Origin` header alias, which earlier evidence files record as well.

| Batch | Modules | Result | Time |
|---|---|---|---|
| 1 | `test_access_api` to `test_attribution_report_bounds` | 128 passed, 3 skipped | 460 s |
| 2 | `test_attribution_reports` to `test_bookings_crm` | 113 passed, 3 skipped | 421 s |
| 3 | `test_collection` to `test_connectors` | 118 passed | 687 s |
| 4a, 4b | `test_conversion_delivery` to `test_ledger_persistence` | 77 and 41 passed | 124 s, 79 s |
| 5a, 5b | `test_lifecycle` to `test_report_schedules` | 59 and 58 passed | 103 s, 115 s |
| 6a, 6b | `test_reports` to `test_saas_plans` | 61 passed; 63 passed, 1 skipped | 78 s, 117 s |
| 7 | `test_tenancy` to `test_whatsapp`, with the browser journeys | 75 passed | 77 s |

The 016-C modules alone: 20 unit cases in `test_report_delivery_contract.py` and 58 integration cases in batch 5b's six report modules (of which `test_report_bounds.py` is 016-A).

**OpenAPI.** `contracts/openapi.json` gains eight paths (the export, schedule and branding routes) and twenty-three schemas. A semantic comparison with `main`'s snapshot finds no changed path, schema or top-level field.

## Mutation check

`mutations_016c.py` (session scratchpad) disabled each safeguard in turn, ran its tests on the disposable database and restored the source; the SHA-256 of every touched file matched before and after each mutation and across the whole run.

| Safeguard disabled | Tests | Outcome |
|---|---|---|
| Client viewers see only their own and received exports | `test_rv04_visibility` | caught |
| The scope is resolved again at download | `test_rv03_scope_resolved_again` | caught |
| `finance:read` for exports with financial figures | `test_rv03_sale_values_need_finance` | caught |
| The seal is bound to the export (mutated to the client) | `test_rv02_copied_ciphertext_does_not_open` | caught |
| The 004 subject erasure revokes | `test_rv06_subject_erasure_revokes_earlier_exports` | caught |
| The 006 person erasure revokes | `test_rv06_person_erasure_revokes_earlier_exports` | caught |
| The erasure of held events revokes | `test_rv06_held_event_erasure_revokes` | caught |
| `start_disconnect` revokes | the three RV07 tests | caught |
| Client archival revokes | `test_rv08_archival_revokes` | caught |
| Manual revocation | `test_rv05_manual_revocation` | caught |
| The export lock | `test_rv06_erasure_waits_for_reservation` | caught |
| The store's recheck of a `pending` reservation | `test_rv06_reservation_during_erasure_is_rebuilt` | caught |
| Revocation discards reservations in progress | `test_rv06_reservation_during_erasure_is_rebuilt` | caught |
| The expiry deletion | `test_rv09_lifecycle_deletes_expired_exports` | caught |
| The 50-export bound | `test_rv01_fifty_unexpired_exports` | caught |
| The 10-schedule bound | `test_rv10_ten_active_schedules` | caught |
| The claim moves a schedule to its next slot | `test_rv12_due_schedule_runs_once_under_two_workers` | caught |
| Stopped agencies are never claimed | `test_rv15_stop_states_get_no_run` | caught |
| The owner must be an Owner or Admin | `test_rv13_owner_without_access_pauses` | caught |
| The recipient's permission check | `test_rv13_recipients_without_access_skipped` | caught |
| The email carries no client name | `test_rv14_report_ready_email` | caught |
| PNG chunk checksums | `test_rv17_png_checks`, `test_rv17_logo` | caught |
| PNG dimension bounds | `test_rv17_png_checks`, `test_rv17_logo` | caught |

Summary: 23 of 23 caught. Before the owner check was isolated (`563e88f`), the demoted owner had no read grant, so the build's scope check paused the schedule as well and the claim check could not be shown alone.

## Observations

- During P1, `test_reports.py::test_v01_foreign_scopes_reveal_nothing` (016-A, code unchanged by 016-C) failed once while free memory was about 0.3 GB; its output was not captured. It passed in four reruns, alone and with the same modules, and in the final suite.
- Batch 3 ran past the 10-minute foreground limit of the tool and finished in the background with all cases passed.
- The pushed branch `codex/spec-018-workspace-screens` (no open pull request) reuses D-093 and D-094 for Spec 018 decisions, which collide with `main`'s D-093 and this work's D-094 and D-095. This slice records no new decision and changes nothing there.

## Limits

- Synthetic data and the disposable database only; no native `tracking_sys` migration (`0032` is not applied there), no live provider, no customer data.
- Exports are stored in PostgreSQL under the local development keyring; object storage, managed keys and download tokens for links without a session are 020 decisions. A missing keyring refuses exports and scheduled runs with `not_configured`.
- `python -m app.report_worker` is a one-pass command, not a scheduler; production scheduling and process supervision are 020. A slot missed while no worker runs is not repeated, by design (D10).
- Report emails are written as local `.eml` files in development; the Gmail transport is unchanged and production email stays Q-008 and 020. Emails carry no figure, client name or token, so they cannot summarize a report.
- No Reports page, branded screen, printable page or PDF file (018, after the owner's brief; D-039). The branding profile is a contract the frontend can apply later.
- No plan limit for exports or schedules beyond the D2 and D8 bounds (017-C).
- Builds of one client's exports serialize only on the short reservation; a revocation waits at most for a reservation. The concurrency tests release their held locks within 1.5 seconds because an erasure waits at most 2 seconds for its privacy lock.
- The run slots and expiries use the database clock and IANA zones (`zoneinfo` with the installed tzdata); a time-zone database change could move future slots.
