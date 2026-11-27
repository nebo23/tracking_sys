# Spec 017-A evidence: plans, limits and agency closure

Recorded: 2026-11-27 under D-092 (decisions D1-D14 of the [entry review](entry-review-017a.md), approved as recommended, without amendment). The [design note](design-017a.md) fixed the statements, answers and tests before any code; this file records what was built, what was run and what remains open. Everything ran against synthetic data on the disposable PostgreSQL 18 service of `backend/tests/README.md` (Compose project `tracking-test-017a`, `127.0.0.1:55433`); native `tracking_sys` was never used.

## 1. Commits

Branch `codex/spec-017a-saas-plans`, created from `origin/claude/keen-fermat-otlr9d` at `25975bf` (merged `main` at `633ea9a` plus the D-091 and D-092 records). `origin/main` did not move beyond `633ea9a` during the work, so no merge was needed; pull request 17 (Spec 018) is still open, so its decisions D-081 to D-087 and its frontend are not on this branch. No new decision number was recorded: D-091 and D-092 cover the work and the pull request.

| Phase | Commit | Content |
|---|---|---|
| P0 | `b204ad6` | Inventory and [design note](design-017a.md) |
| P1 | `ae342e9` | Migration `0031_saas_plans`, models, data policy, default plan at agency creation, `python -m app.agency_plans`, agreement deletion for closed accounts |
| P2 | `e3b3e22` | Limits at every creation point, `GET /agencies/{agency_id}/plan` |
| P3 | `f6eb8bd` | Agency closure routes, the lifecycle completion step, the D9 account-closure rule |
| P4 | `2fa7db6` | Agreement record at registration and every sign-in, `GET /auth/agreements`, `Retry-After` exposed |
| P5 | this commit | Evidence, developer guide, status lines |

Each phase was verified, committed and pushed before the next one started.

## 2. Commands and counts (final run, head `2fa7db6` plus documentation)

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check app tests migrations` (from `backend/`) | All checks passed |
| Format | `ruff format --check app tests migrations` | 309 files already formatted |
| Unit | `pytest -m "not integration" -q` | **949 passed** (746 deselected), 19.5 s |
| Integration, batch 1 | `test_access_api` to `test_attribution_reports` (13 modules) | **144 passed, 3 skipped**, 353.9 s |
| Integration, batch 2 | `test_attribution_store` to `test_collection` (5 modules) | **147 passed, 3 skipped**, 298.0 s |
| Integration, batch 3 | `test_connector_coverage` to `test_google` (14 modules) | **133 passed**, 251.8 s |
| Integration, batch 4 | `test_identity` to `test_paymob` (13 modules) | **111 passed**, 211.9 s |
| Integration, batch 5 | `test_postgres` to `test_review_006_007` (9 modules) | **101 passed, 1 skipped**, 188.6 s |
| Integration, batch 6 | `test_roas` to `test_whatsapp` (7 modules, browser journeys included) | **103 passed**, 165.2 s |
| Tracker unit | `node --test test/unit/*.test.js` (from `packages/tracker-js`) | **73 passed** |
| Tracker browser | `node --test --test-concurrency=1 test/browser/*.test.js` | **50 passed** (Chromium and Firefox) |
| Dependencies | `pip check` | No broken requirements found |
| Whitespace | `git diff --check` | Clean |
| Links | relative-link check of the changed Markdown | Section 9 |

The integration batches ran with `TRACKING_RUN_BROWSER_TESTS=1`, so the three backend browser journeys of `test_tracker_journey.py` ran and passed. Together the six batches cover all 61 integration modules: **739 passed and 7 skipped**. The 7 skipped cases are opt-in measurements of earlier specifications, reported as skipped, not passed: 3 AV16 (`TRACKING_ATTRIBUTION_MEASURE`), 3 BV19 (`TRACKING_REPORT_MEASURE`) and 1 review measurement (`TRACKING_REVIEW_MEASURE`). The batches ran in the foreground, each under ten minutes, because the workstation had under 1 GB of free memory. The tracker's Playwright 1.64.1 browsers came from the 005 worktree's installed copy through a directory junction, removed afterwards; the tracker package is unchanged on this branch.

The frontend checks of P5 do not apply: on this branch `frontend/` holds only its placeholder README files (the Spec 018 application is on pull request 17), so there is no `package.json`, no generated `schema.d.ts` and nothing to run. Section 8 records the change the frontend's sign-in and registration need.

The new tests are 69 cases: 16 unit cases in `tests/test_agency_plans_command.py` and 53 integration cases in `test_saas_plans.py` (19), `test_agency_closure.py` (11), `test_agency_closure_stops.py` (18) and `test_agreements.py` (5).

## 3. Verification matrix

Test modules are under `backend/tests/` (integration modules under `integration/`). Every case passed in the final run.

| Case | Tests | Result |
|---|---|---|
| SV01 Default plan | `test_saas_plans::test_sv01_new_agencies_get_the_current_default_plan`; the agencies existing at migration in `test_sv18_...` | passed |
| SV02 Limits | `test_saas_plans::test_sv02_clients_limit_refuses_exactly_the_creation_beyond_it`, `::test_sv02_seats_count_members_and_pending_invitations`, `::test_sv02_connections_are_limited_at_the_start_and_at_installation`, `::test_sv02_managed_links_limit_counts_active_links`, `::test_sv02_a_missing_limit_never_refuses` | passed |
| SV03 Concurrency | `test_saas_plans::test_sv03_concurrent_creations_at_the_limit_have_one_winner` (clients, invitations, links and two concurrent connector callbacks, real PostgreSQL), `::test_sv03_a_waiting_creation_counts_after_the_lock` (a creation blocked on the agency lock counts the committed creation) | passed |
| SV04 Downgrade | `test_saas_plans::test_sv04_a_smaller_plan_keeps_everything_and_refuses_only_new_creations` | passed |
| SV05 Never refused | `test_saas_plans::test_sv05_reads_syncs_redirects_collection_erasure_archival_and_revocation_are_never_refused` (every limit at 0, including the event allowance) | passed |
| SV06 Tracked events | `test_saas_plans::test_sv06_events_beyond_the_allowance_are_accepted_and_counted_by_utc_month` (microsecond month edges, another agency), `::test_sv06_the_count_is_bounded` | passed |
| SV07 Usage view | `test_saas_plans::test_sv07_usage_view_roles_keys_and_answer` | passed |
| SV08 Operator command | `test_saas_plans::test_sv08_operator_command_subcommands_audit_and_refusals`, `::test_sv08_operator_command_runs_as_its_own_process`; `test_agency_plans_command` (16 cases) | passed |
| SV09 Suspension | `test_saas_plans::test_sv09_suspension_stops_the_agency_and_reactivation_restores_it`; the `suspended` cases of SV11 | passed |
| SV10 Closure request | `test_agency_closure::test_sv10_closure_request_is_owner_only_named_and_reauthenticated`, `::test_sv10_the_closure_throttle_and_the_reauthentication_without_a_password` | passed |
| SV11 Closing stops everything | `test_agency_closure_stops`, each for `suspended` and `closing`: `test_sv11_member_routes_and_keys_stop`, `_collection_stops` (trusted, public and webhook intake), `_redirects_stop`, `_payments_stop`, `_integrations_stop`, `_whatsapp_stops`, `_connector_worker_stops`, `_delivery_worker_stops`, `_attribution_worker_skips_the_agency` | passed (18) |
| SV12 Cancel | `test_agency_closure::test_sv12_cancellation_restores_the_agency_and_its_connections` | passed |
| SV13 Completion | `test_agency_closure::test_sv13_lifecycle_completes_due_closures_once_and_in_bounded_batches`, `::test_sv13_a_cancellation_holding_the_agency_lock_leaves_the_step_incomplete` | passed |
| SV14 Sole Owner | `test_agency_closure::test_sv14_sole_owner_account_closure_by_agency_status` (active, suspended, closing, closed), `::test_sv14_a_sole_owner_is_still_held_by_another_active_agency` | passed |
| SV15 Agreement at registration | `test_agreements::test_sv15_registration_requires_and_records_the_current_versions` | passed |
| SV16 Agreement at sign-in | `test_agreements::test_sv16_password_sign_in_records_a_new_version_once`, `::test_sv16_outdated_versions_are_refused_before_the_credential_check`, `::test_sv16_google_sign_in_carries_the_versions_in_its_transaction` | passed |
| SV17 `Retry-After` | `test_agreements::test_sv17_retry_after_is_readable_from_the_application_origin`; `test_event_links::test_consent_state_enforces_origin_body_and_its_own_rate_limit` (public collection CORS unchanged) | passed |
| SV18 Migration | `test_saas_plans::test_sv18_upgrade_seeds_and_assigns_grants_and_guarded_downgrade`; `test_saas_plans::test_agreements_of_closed_accounts_follow_the_credential_state`; `test_tenancy::test_migration_matches_model_metadata`; `test_data_policy_schema`; `test_postgres` | passed |
| SV19 Isolation and logs | `test_saas_plans::test_sv19_agencies_never_see_each_other_and_output_carries_no_secret`, `test_agency_closure::test_sv19_closure_isolation_and_logs`; the name and secret checks of SV07 and SV08 | passed |
| SV20 Existing behavior | the whole suite of section 2; `test_contract::test_openapi_snapshot_matches_implemented_routes`; the semantic OpenAPI diff of section 6 | passed |

## 4. Mutation check

`mutations_017a.py` (scratch, not committed) disabled each new safeguard in turn, ran its tests through the disposable-database runner, and restored the source byte for byte. Before and after the 17 runs the SHA-256 of all 157 files under `backend/app` were identical, and `git status` was clean.

| Mutation | Tests failing while it was in place |
|---|---|
| Client limit check disabled | SV02 clients (1 failed) |
| Seat limit check disabled | SV02 seats (1) |
| Connection limit check disabled | SV02 connections (1) |
| Managed-link limit check disabled | SV02 links (1) |
| Binding connection check at installation removed | SV02 connections, SV03 concurrency (2) |
| Agency row lock before the count removed | both SV03 cases (2) |
| Closure request leaves the agency active (the intake and workers keep serving it) | all 9 `closing` cases of SV11 (9) |
| Any active member may request or cancel a closure | SV10 (1) |
| Closure reauthentication skipped | both SV10 cases (2) |
| Lifecycle completion step completes nothing | SV13 and SV14 `closed` (2) |
| Sole-Owner rule kept for closing and closed agencies | SV14 `closing` and `closed` (2) |
| Sole-Owner rule lifted for every agency | SV14 `active`, `suspended` and the second-agency case (3) |
| Agreement check of registration and password sign-in disabled | SV15 and both password SV16 cases (3) |
| Agreement check of the Google start disabled | SV16 Google (1) |
| Agreement check of the Google callback disabled | SV16 Google (1) |
| A repeated version is inserted again (single record per version) | SV16 password and Google (2) |
| Changes run without `--confirm` | the 5 `--confirm` unit cases and both SV08 cases (7) |

Result: 17 of 17 caught.

## 5. Changes to existing tests

Every existing test passes; these changed, each for a stated reason:

- **Agreement versions (the handoff's helper change).** `conftest.api.login` and the registration and sign-in helpers and direct calls of `test_auth`, `test_account_closure`, `test_auth_review_regressions`, `test_google`, `test_lifecycle`, `test_origin_config` and `test_verification_code` send the current versions (`tests/integration/auth_support.py`). Without them those requests would now be refused with `agreement_required`.
- **The seeded plan.** `conftest.TABLES` gains the four tables; the empty-database guard and the teardown keep the seeded development plan and restore it as the default. `test_postgres` accepts the four tables and the seed row before it downgrades to base.
- **Head-dependent expectations.** `test_attribution_models` and `test_identity_ledger_migrations` expect head `0031_saas_plans`; `test_data_policy` and `test_data_policy_schema` expect 91 tables and 11 single-column user references, and `test_data_policy` lists the two new approved rules.
- **New columns and fields.** `test_tenancy` lists `audit_events.actor_kind`; `test_auth` compares the agency list exactly and now expects its `status` field.
- **Older downgrade guards.** Sign-ins and registrations now store agreement records, which the 0031 downgrade refuses to drop. The guard tests of earlier revisions (`test_account_closure`, `test_collection`, `test_connector_youtube`, `test_connector_youtube_live`, `test_connectors`, `test_links`, `test_verification_code`) therefore delete those rows first, so that the guard under test is still the one that refuses.
- **D11.** `test_event_links` asserted that platform responses expose no header; it now expects exactly `Retry-After`.

## 6. API changes

The semantic diff of `contracts/openapi.json` against `633ea9a`:

- **Added paths:** `GET /agencies/{agency_id}/plan`; `POST`, `GET` and `DELETE /agencies/{agency_id}/closure`; `GET /auth/agreements`.
- **Added schemas:** `AgencyPlanResponse`, `PlanSummary`, `PlanLimitUse`, `TrackedEventsUse`, `PlanLimitError`, `AgencyClosureInput`, `AgencyClosureResponse`, `OpenAgencyClosure`, `AgreementAcceptance`, `AgreementVersions`, `AgreementRequiredError`.
- **Agreement fields of the authentication requests:** `Registration` and `Login` gain the optional `agreements`; `POST /auth/register` and `POST /auth/login` document `422` as `AgreementRequiredError`; `GET /auth/google/start` gains the optional `terms` and `privacy` query parameters.
- **Agency status values:** `AgencyAccess` gains `status` (`active` or `closing`).
- **Documented 409 refusals:** the `409` answer of `POST /agencies/{agency_id}/clients`, `PATCH /agencies/{agency_id}/clients/{client_id}`, `PATCH /agencies/{agency_id}/members/{membership_id}`, `POST /agencies/{agency_id}/invitations`, `POST .../connections` and `POST` and `PATCH .../managed-links` is documented as `PlanLimitError`, a superset of `ErrorResponse`. Nothing else in those operations changed.
- **Operator audit rows:** `AuditResponse` gains `actor_kind`, and `actor_user_id` becomes nullable for rows written by the platform operator (design section 2.2).

No other path or schema changed. The connector and Google callbacks gain the redirect codes `plan_limit_reached` and `agreement_required`, outside the OpenAPI schema.

## 7. Details found during implementation

- **Snapshot expiry.** The usage view's snapshot session commits when it closes, which expires the loaded rows; the answer is therefore built inside the snapshot. The first version answered `503` and was corrected before P2 was committed.
- **Throttles count refusals.** The registration throttle (three per email per hour) and the closure throttle (three per user per hour, as for account closure) run before the agreement or name check, so refused attempts count; the tests use separate addresses or clear the buckets.
- **Bound of the event count.** A selected literal is untyped for server-side parameter binding; the bounded count selects the event ID instead, which is part of the `(client_id, first_received_at, id)` index.
- **CORS.** Starlette sends its static `Access-Control-Expose-Headers` list also to an origin it does not grant; without `Access-Control-Allow-Origin` a browser can read nothing there, so the list is inert. The test checks that no grant is made.
- **Disk space.** During the P1-P4 runs the free space of drive C: fell from 8.4 GB to 1.1 GB while the Docker disk image grew to 12.5 GB. The verification stopped, and the owner chose to clear the npm download cache (`npm cache clean --force`, about 6.5 GB). The disposable database was then recreated, and the final run of section 2 started with 6.9 GB free and ended with 6.9 GB free.

## 8. Limits and what remains

- **Frontend change needed (pull request 17).** The Spec 018 sign-in and registration must read `GET /auth/agreements` and send `agreements: {terms, privacy}` with `POST /auth/register` and `POST /auth/login`, open `/auth/google/start?terms=...&privacy=...`, and handle `422 agreement_required` and `error=agreement_required` on the Google completion page by showing the agreement box again with the returned versions. Until then its sign-ins and registrations are refused. It should also show `409 plan_limit_reached` (limit, value, use) and the usage view, offer the closure routes to Owners, and read `Retry-After`, which the browser can now see. No frontend code changed here.
- **Legal texts.** The Terms of Service and the Privacy Policy do not exist yet; the versions are `draft-1` and `GET /auth/agreements` reports `published: false`. Whether proof of agreement must outlive a closed account awaits legal advice (Q-012); today the lifecycle runner deletes it with the account's credential state.
- **Development values.** The `development` plan's limits are development values (D3); prices, currencies, trials and a payment provider belong to 017-C (Q-005 stays open).
- **Closed agencies.** A closed agency's data stays stored and unreachable; its purge, export and the revocation of its provider tokens belong to 017-B. A closing agency whose last Owner closed the account can no longer be cancelled and completes at `closes_at`.
- **Lifecycle role.** `tracking_lifecycle` now updates `agencies.status` (and `updated_at`) and `agency_closures.completed_at`; the grant cannot restrict values, the runner's predicate and the status check do.
- **Not measured.** The bounded tracked-event count was verified with a lowered bound; its cost near the 1,000,000-row bound was not measured.
- **Not done.** Native `tracking_sys` migration, deployment, live providers, 016-C and the React UI remain separate decisions (D-092). The merge of the pull request is the owner's decision after Claude's independent review.

## 9. Documentation

The [developer guide](../../docs/engineering/plans-and-closure.md) describes the plans, limits, usage view, operator command, closure and agreement record; the [authentication guide](../../docs/engineering/authentication.md) and the [data lifecycle guide](../../docs/engineering/data-lifecycle.md) link to it. The spec, plan and tasks of 017 and the status lines of `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md` are updated. The relative links of every changed Markdown file were checked (`check_links.py`): all targets exist.
