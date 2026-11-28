# Spec 017-B evidence: offboarding export, provider disconnection and the purge of closed agencies

Prepared: 2026-11-28 under D-098. Branch: `codex/spec-017b-agency-offboarding`, created from `origin/claude/keen-fermat-otlr9d` at `dc92506`; merged `main` at `e3b3005` is an ancestor and did not move. Scope: the [entry review](entry-review-017b.md) (D1-D14, approved without amendment), the [implementation handoff](implementation-prompt-017b.md) and the [design note](design-017b.md). Synthetic data, the disposable PostgreSQL service and synthetic providers only; native `tracking_sys` was never used and no live provider was called.

## 1. Commits

| Phase | Commit | Content |
|---|---|---|
| P0 | `926ed1b` | Design note: inventory of the 83 scoped tables, the DDL and function of `0033`, the export catalog, build, offboarding, purge, command and test inventory |
| P1 | `a1c0ab2` | Migration `0033_agency_offboarding`, models, `purge_agency_batch`, data policy rows and the D-098 purge rule, OV09 (table list), OV12, OV18 |
| P2 | `c249894` | Offboarding pass, lifecycle purge step, `python -m app.agency_offboarding`, teardown limited to one agency, OV07, OV08, OV09-OV11, OV13-OV16 |
| P3 | `1cfbe9e` | Export routes, build, catalog, manifest, bounds, checks, sealed parts, expiry of parts, OpenAPI snapshot, OV01-OV06 and the sequenced OV17 case |
| P4 | `a00a6a6` | End-to-end journey, OV17 with real concurrency, OV19 |
| P5 | `2ba5cf7` and the next | Two tests strengthened for the mutation check, evidence, guides, status lines; then the pull request number |

Pull request: [PR 21](https://github.com/nebo23/tracking_sys/pull/21) against `main`, opened at `2ba5cf7` for Claude's independent review, not merged.

## 2. Environment and deviation

- **Database.** PostgreSQL 18.6 (`postgres:18.6-bookworm`, pinned digest) in the Compose project `tracking-system-foundation-test`, created for this session with synthetic credentials and removed with its volume afterwards.
- **Port deviation (owner's choice, 2026-11-28).** Windows had reserved the TCP range 55365-55464 (`netsh interface ipv4 show excludedportrange`), so nothing could bind 55433, the port the integration guard requires. The owner chose to run the same disposable service on 127.0.0.1:56433. The runner patched only the guard's port number in `tests/integration/conftest.py` for the length of each pytest run and restored the file in a `finally` block, checking its SHA-256 after every run. The patched guard was never committed: every commit was preceded by a check that the file holds `config.database_port != 55433` and no `56433`.
- **Tools.** Python 3.12.4 in the project virtual environment, Node.js 24.17.0, Playwright 1.64.1 browsers (Chromium 1248, Firefox 1555) reused through a junction to the installed `node_modules` of the `spec-005-links-tracker` worktree, whose Playwright version is the one this branch pins; the tracker package is unchanged from `main`. The junction was removed after the runs.
- **Frontend.** `frontend/` holds only the placeholder README files of the initial commit, without `package.json`, so the frontend checks of P5 do not apply.

## 3. Verification

| Check | Command (from `backend/` unless stated) | Result |
|---|---|---|
| Lint | `ruff check app tests migrations` | All checks passed |
| Format | `ruff format --check app tests migrations` | 339 files already formatted |
| Unit | `pytest -m "not integration" -q` | 986 passed, 832 deselected |
| Integration | `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1`, in nine batches (below) | 825 passed, 7 skipped, 0 failed (832 cases) |
| Tracker unit | `node --test test/unit/*.test.js` (from `packages/tracker-js`) | 73 passed |
| Tracker browser | `node --test --test-concurrency=1 test/browser/*.test.js` | 50 passed (Chromium and Firefox) |
| Dependencies | `pip check` | No broken requirements found |
| Whitespace | `git diff --check origin/main...HEAD`, and the working tree | clean |
| Links | relative links of the changed Markdown | 409 local targets in the 19 Markdown files that differ from `main`, none missing |
| Contract | regenerated `contracts/openapi.json`, semantic diff against `main` | 2 paths and 3 schemas added, nothing changed or removed |

The integration suite ran in nine foreground batches of 81-100 cases on one database, because the workstation had 0.7-0.8 GB of free memory:

| Batch | First module | Result | Time |
|---|---|---|---|
| 1 | `test_access_api.py` (7 modules, `test_agency_export.py` included) | 97 passed | 181 s |
| 2 | `test_agency_offboarding.py` (10 modules) | 79 passed, 3 skipped | 240 s |
| 3 | `test_attribution_store.py` (4 modules) | 97 passed, 3 skipped | 219 s |
| 4 | `test_collection.py` (8 modules) | 94 passed | 187 s |
| 5 | `test_connectors.py` (7 modules) | 89 passed | 194 s |
| 6 | `test_identity.py` (12 modules) | 89 passed | 156 s |
| 7 | `test_paymob.py` (8 modules) | 81 passed | 205 s |
| 8 | `test_reports.py` (8 modules) | 99 passed, 1 skipped | 181 s |
| 9 | `test_roas_reports.py` (6 modules, the tracker journeys included) | 100 passed | 133 s |

The seven skipped cases are the opt-in measurements, skipped as in earlier evidence: `test_attribution_report_bounds.py::test_bv19_measurements` (3, `TRACKING_REPORT_MEASURE`), `test_attribution_store.py::test_av16_measurements` (3, `TRACKING_ATTRIBUTION_MEASURE`) and `test_review_006_007.py::test_review_r0607_11_a_200_row_commit_on_a_client_with_history` (1, `TRACKING_REVIEW_MEASURE`). The browser journeys of `test_tracker_journey.py` ran and passed.

After the full run, two test modules changed: OV12 gained a case (a closed agency without connections whose offboarding is still running), and the paused sections of the concurrency tests now release their thread in `finally`. The second change followed a mutation run in which a failing assertion left a paused thread holding its locks, so the fixture cleanup could not empty the database and the next run refused it; the disposable Compose project was then recreated. Both modules were rerun on the fresh database: 11 passed (`test_agency_offboarding_migration.py` 6, `test_agency_offboarding_journey.py` 5), and `test_postgres.py` passed after the repeated two-workers mutation, which shows the database was left empty.

## 4. OV01-OV20

All tests are under `backend/tests/`; every listed test passed in the runs of section 3.

| Case | Tests | Evidence |
|---|---|---|
| OV01 | `integration/test_agency_export.py::test_ov01_export_request_is_owner_only_reauthenticated_and_audited`, `::test_ov01_export_window_and_agency_status` | An active agency answers `409 agency_not_closing`; Admins, Analysts, client viewers, outsiders and the other agency's Owner `403`; a wrong or missing password `401 invalid_credentials`; a bearer key `401`; the fourth request in an hour `429`. A request answers `202` and is audited (`agency.export_requested`, resource `agency_export`); a new request revokes the open export (`agency.export_revoked`). 23 hours before the closing time `409 export_window_ended`, 25 hours `202`; suspended and closed agencies `403` for the request, the state and the download. |
| OV02 | `test_agency_export.py::test_ov02_export_contents_match_the_catalog_and_manifest`; `test_agency_export_contract.py` (4 cases) | The ZIP holds exactly the 36 catalog files of both clients and `manifest.json`; each file's rows equal the database rows of its client, each line's keys are the catalog columns in order, and its bytes and SHA-256 match the manifest; the manifest's SHA-256 is stored. No value of an excluded digest or key column, no other agency's ID, no agency name, email, `kek_id` or `ciphertext` appears. The unit tests check that every scoped table is exported or excluded, that each exported table lists or excludes every column, and that no binary, digest, key or token column is exported. |
| OV03 | `test_agency_export.py::test_ov03_export_beyond_the_bound_fails_without_storing`, `::test_ov03_a_zip_that_fails_its_checks_is_not_stored` | With the row bound at 3 or the size bound at 300 bytes, the export fails with `export_too_large` and has no part; a ZIP whose manifest disagrees or whose bytes are damaged fails with `build_failed` and stores nothing. |
| OV04 | `test_agency_export.py::test_ov04_parts_are_sealed_and_bound_to_their_export` | With 1 KiB parts, at least three parts, numbered from 1, each at most 1 KiB of plaintext; no part holds a ZIP header, a path or a name in clear; a part does not open for another part number, export or agency; the parts decrypt to the downloaded file. |
| OV05 | `test_agency_export.py::test_ov05_download_streams_the_built_zip_for_owners_only`, `::test_ov05_download_is_gone_after_expiry_revocation_or_purge` | Two Owners download the same bytes as the decrypted parts, with `application/zip`, `Content-Length`, `Content-Disposition` and `no-store`, and the download count rises to 2; other members get `403`. After expiry `410 export_gone` and the status `expired`, and the lifecycle runner deletes the parts; a replaced export is revoked and the new pending one answers `409 export_not_ready`; a cancellation revokes the export and deletes its parts; after the completion `403`, and the purge deletes the export. |
| OV06 | `test_agency_export.py::test_ov06_export_pending_at_completion_is_discarded` | A pending export of a closure that completed before the build is marked `failed` with `closure_completed` and has no part. |
| OV07 | `integration/test_agency_offboarding.py::test_ov07_offboarding_disconnects_revokes_and_disables_once` | One pass: 2 connections `disconnecting` with `agency_closed` and a 72-hour deadline, 1 key, 1 invitation and 1 report export revoked, 1 pending offboarding export failed, 3 sources, 1 destination and 2 WhatsApp numbers changed; the other agency's connection stays active; the purge record is `waiting` with the copied closure times. A second pass changes nothing. |
| OV08 | `test_agency_offboarding.py::test_ov08_teardown_revokes_at_the_provider_and_the_purge_waits`, `::test_ov08_a_teardown_past_its_deadline_no_longer_holds_the_purge` | While the synthetic provider fails, the teardown stays pending and the purge waits without deleting a row; once it succeeds the provider records the revocation of agency A's grant only, the connection is `disconnected` and the purge follows. Past its deadline, an unsettled teardown no longer holds the purge, which deletes the connection, its sealed tokens and its provider rows itself. |
| OV09 | `integration/test_agency_offboarding_migration.py::test_ov09_function_covers_every_scoped_table`; `test_agency_offboarding.py::test_ov09_purge_leaves_no_row_of_the_agency` | The deployed function deletes exactly the 81 scoped tables other than the kept record, children before parents, with leaves first only for the two self-referencing tables. After the purge of an agency populated through the identity, attribution, revenue, link, connector and report flows and direct rows (all 20 tables reached through a parent key or a self-reference populated beforehand), no row with its ID or one of its client IDs remains; the per-table counts add up to the reported total. |
| OV10 | `test_agency_offboarding.py::test_ov10_what_stays_after_the_purge` | The agency row is `closed`, named `Closed agency <id>`, with `purged_at`; its plan assignments are unchanged; the record is `purged` with the closure times and the export summary; no name, client ID or email is stored in it; the seven users remain, the Admin and the other agency's Owner sign in, and the purged agency is listed for neither. |
| OV11 | `test_agency_offboarding.py::test_ov11_other_agencies_keep_every_row`; the agency B check of `::test_ov09_purge_leaves_no_row_of_the_agency` | Every scoped table of agency B holds the same rows before and after A's purge; B's grant is not revoked; the analyst, a member of both, still reads B. |
| OV12 | `test_agency_offboarding_migration.py::test_ov12_function_refuses_agencies_not_closed_and_offboarded`, `::test_ov12_lifecycle_role_cannot_delete_tenant_configuration` | The function refuses active, suspended and closing agencies (`agency_not_closed`), a closed agency without a record, with a record still offboarding, or with a live connection (`offboarding_not_completed`), a teardown before its deadline (`teardown_pending`) and budgets outside 1-10,000 (`invalid_budget`); no refused call deletes a row. The lifecycle role cannot delete clients, memberships, grants, links, campaigns, audit events, purge records or exports, nor rename an agency; the runtime role cannot execute the function. |
| OV13 | `test_agency_offboarding.py::test_ov13_purge_is_bounded_and_resumable` | With a budget of 7 and one batch per run, a run deletes 7 rows and reports `agency_purges` incomplete; a held row lock makes one batch time out and roll back alone; the next calls each delete at most 7 rows and finish the purge with the expected total. |
| OV14 | `test_agency_offboarding.py::test_ov14_whatsapp_number_and_custom_domain_are_released` | Until the purge, another agency's claim of the same number cannot be verified (`number_already_bound`) and its domain request answers `409`; after the purge the claim is verified and the domain created. |
| OV15 | `test_agency_offboarding.py::test_ov15_workers_skip_closed_and_purged_agencies`, `::test_ov15_delivery_worker_skips_a_closed_agency` | While closed, offboarded and purged, the connector worker schedules and synchronizes only the other agency, the attribution worker reads two clients, the report worker finds no due schedule and the offboarding worker nothing more; the delivery worker leaves a queued delivery of a closed agency unsent and refuses new ones (`client_inactive`). |
| OV16 | `test_agency_offboarding.py::test_ov16_operator_command_status_and_run`; `test_agency_offboarding_command.py` (12 cases) | `status` before and after; `run` offboards, tears down and purges at once, and a second `run` changes nothing; refusals `agency_not_closed` with the status and `agency_not_found`; outputs carry no name, account or email; the command runs as its own process; `run` without `--confirm` and every invalid argument exit with 2 before connecting. |
| OV17 | `test_agency_export.py::test_ov17_a_completion_between_build_and_store_discards_the_export`; `integration/test_agency_offboarding_journey.py::test_ov17_completion_against_an_export_build`, `::test_ov17_two_offboarding_workers`, `::test_ov17_purge_against_a_late_worker` | With the store holding the agency lock, the completion batch times out and the export becomes ready before the closure completes; with the completion holding it, the waiting store discards the export. Two concurrent offboarding workers: the second passes the locked agency by, each connection's generation rises once. A late teardown, a late write between calls and an uncommitted write during a call do not break the purge, which finishes on the next run with no row left. |
| OV18 | `test_agency_offboarding_migration.py::test_ov18_upgrade_from_populated_0032`, `::test_ov18_grants`, `::test_ov18_downgrade_refuses_stored_rows`; `test_data_policy.py`, `integration/test_data_policy_schema.py` | The upgrade keeps every row of a populated 0032 and adds empty tables, `purged_at` and a `SECURITY DEFINER` function owned by the migrator with `search_path = pg_catalog, pg_temp`; the grants are exactly those of design section 2.6; the downgrade refuses each kind of stored row; the registry has 99 tables, 11 user references and the D-098 rules. |
| OV19 | `test_agency_offboarding_journey.py::test_journey_export_completion_offboarding_teardown_purge`, `::test_ov19_failures_log_codes_only` | Across the journey's logs, API answers, worker and runner results and the two commands run as processes: no agency, client or brand name, email, password, session cookie, account ID, provider token, sale amount (987,654 minor units), path or JSON line of the file. A failed build, a damaged part and a failed offboarding log only `agency_export_failed`, `agency_export_unreadable` and `agency_offboarding_failed`. |
| OV20 | the full suites of section 3 | Every existing case passes; existing modules changed only for the new head (`0033`), the table counts, the known tables and the D-098 rules; the OpenAPI snapshot has additions only. |

## 5. Mutation check

`mutations_017b.py` (scratch tooling, not committed) disabled one safeguard at a time, ran its tests through the same runner, and restored the source byte for byte; a migration mutation downgraded the disposable database to `0032` before and after its run. The SHA-256 of the five edited sources was identical before and after all runs (`0033_agency_offboarding.py` `3de8a217fa2a`, `agency_exports.py` `c44ea6742b71`, `agency_offboarding.py` (service) `1b8c25beacbd`, `agency_closure.py` `26dc14ee2bcc`, `agency_offboarding.py` (command) `01d17a94bd48`). All 25 mutations were caught:

| Safeguard disabled | Failing test and observation |
|---|---|
| The function's refusal of an agency that is not closed | OV12: an active agency got `offboarding_not_completed` instead of `agency_not_closed` |
| The function's refusal while the offboarding is not done | OV12: the call ran and failed on the record's progress check (`23514`), which kept the deletion from committing |
| One table (`link_campaigns`) left out of the function | OV09: 80 tables instead of 81; the populated purge never completed |
| The teardown wait | OV08: the agency was purged while its teardown was pending |
| The pseudonym of the agency's name | OV10: the original name stayed |
| Owner-only request and download | OV01: an Admin's request answered `202`; OV05: an Admin received the ZIP |
| The request's reauthentication | OV01: a wrong password answered `202` |
| The 24-hour cut-off | OV01: a request 23 hours before closing was accepted |
| The scope resolved again at download | OV05: an Admin received the ZIP |
| Exclusion of a digest column (`token_digest` exported) | `test_agency_export_contract.py`; OV02 found subject token digests in the file |
| Exclusion of provider data (`ad_spend_facts` exported) | `test_agency_export_contract.py`: 37 tables, one of them excluded |
| The row bound (write and check) | OV03: the export was built |
| The size bound (write and check) | OV03: the export was built |
| The check before storing | OV03: tampered ZIPs were stored |
| The store's requirement of a closing agency | OV17: exports were stored after the closure completed |
| Each revocation of D6 (connections, keys, invitations, report exports, the pending export, sources, destinations, WhatsApp): 8 mutations | OV07: each count or row state differed |
| Passing a locked agency by (`SKIP LOCKED`) | OV17: the second worker waited, hit the lock timeout and failed |
| `--confirm` | `test_agency_offboarding_command.py::test_run_requires_confirm` |

## 6. Details found during implementation

1. **Function body.** A spent budget ends a call after any step, the last one included, so a call marks the purge complete only after walking every step with budget to spare. The first draft checked after every step except the last and was corrected before any run.
2. **Progress check as a backstop.** The progress check of `agency_purges` refuses a state that skips its times, so even with the offboarding guard removed the function could not commit a purge (mutation 2).
3. **Self-references.** `identity_merges.reverses_id` and `identity_subjects.merged_into_id` reference their own table; bounded batches delete only rows that nothing remaining references, with a single-statement fallback for a cycle, which the merge rules exclude.
4. **Index paths.** Partial indexes cannot serve the purge's predicates; `attribution_allocations` is reached through `run_id`, and `conversion_deliveries` and `conversion_acknowledgements` through the agency index. Three short-lived tables are scanned (`agency_closures`, `payment_callback_diagnostics`, `connector_oauth_transactions`).
5. **Catalog as an allowlist.** The export lists its columns explicitly and names every other column of an exported table, so a new column is never exported before review.
6. **Lock timeouts.** Every session has `lock_timeout = 3000` ms: an export store that waits longer for the agency lock fails with `build_failed` instead of `discarded`, and the Owner requests again.
7. **Teardown filter.** `run_teardowns` and `_claim_teardowns` take an optional agency, used only by the operator command.
8. **Late connector rows.** The lab's first synchronization of another agency runs in any worker pass; the isolation tests let it finish before taking their baseline.

## 7. API changes

Additions only: `POST /agencies/{agency_id}/closure/export` (`202`), `GET /agencies/{agency_id}/closure/export`, `GET /agencies/{agency_id}/closure/export/download` (`application/zip`), and the schemas `AgencyExportInput`, `AgencyExportState` and `AgencyExportView`.

## 8. Limits

- **Port.** The integration suite ran on 127.0.0.1:56433 with the guard's port patched during the runs only (section 2), because Windows reserved 55433; the committed guard still requires 55433.
- **Live providers.** The revocations reached the synthetic provider only; the teardown of live Meta and Google connections is an owner-operated check after the merge (D13).
- **Scale.** The bounds and the single-transaction offboarding are sized for development and the plan limits. Foreign keys without an index on the referencing side (the two self-references and `bookings.subject_id`) make each deleted parent scan its client's rows, as the existing retention does; production sizes come with Q-004 and 020.
- **Queued mail.** Invitation and `report_ready` messages carry no agency reference; they expire with their invitation or export and leave under the outbox rule. Their links stop working at once.
- **Backups and scheduling.** Backups are not edited (D10): a restore must reapply the recorded purges (the 003 journal, 020). The workers and the runner are not scheduled (020).
- **Frontend.** The export and closure pages belong to 018; no frontend code changed.
- **Native rollout.** `0033_agency_offboarding` was applied to the disposable database only.
