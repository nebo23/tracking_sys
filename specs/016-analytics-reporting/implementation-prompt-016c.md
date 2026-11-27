# Spec 016-C implementation: retained exports, scheduled reports and the white-label delivery contract

Prepared 2026-11-27 under D-094. It executes decisions D1-D14 of the [016-C entry review](entry-review-016c.md) once the owner has approved them; the approval is recorded as D-095. Communicate with the owner in Arabic, and write every project file, commit and pull request in formal English. Save this handoff as `specs/016-analytics-reporting/implementation-prompt-016c.md` on the branch below.

## Where to work

1. Fetch `origin`.
2. Create `codex/spec-016c-report-delivery` from the current `origin/claude/keen-fermat-otlr9d`. That branch is merged `main` at `06d6a19` (PR 19) plus the D-093 records, this preparation and D-095. Verify that `git merge-base --is-ancestor 06d6a19 HEAD` succeeds.
3. Check `origin/main`. If it moved beyond `06d6a19`, merge it into the branch first and report what changed. Pull request 17 (Spec 018) may have merged by then:
   - In `AGENTS.md` and `docs/planning/decisions.md`, keep both sets of decisions in numeric order. D-081 to D-087 belong to Spec 018, and D-094 and D-095 to this work. Remove the placeholder notes that say D-081 to D-087 are recorded elsewhere, and keep the numbering note of Spec 018.
   - If `frontend/` now exists, the frontend checks of P5 apply.
4. Use a fresh worktree, and preserve owner files and other checkouts.
5. A new decision record takes the next free number after the highest one on `main`, on this branch and on any open pull request. Check before recording.

Read the following before the first change:
- **Project rules and decisions:** `AGENTS.md`, `README.md`, and in `docs/planning/decisions.md` D-024, D-025, D-072, D-089, D-091, D-093, D-094 and D-095.
- **The packet:** the [016-C entry review](entry-review-016c.md), D1-D14, design section 4 and verification matrix section 5.
- **Spec 016:** the [spec](spec.md), the [plan](plan.md), the [tasks](tasks.md), D10 of the [016-A entry review](entry-review.md) and the [reporting guide](../../docs/engineering/reporting.md).
- **The 003 contract:** sections 10 and 11 of `specs/003-privacy-data-policy/design.md` (deletion targets, `export_artifacts`, downloads).
- **Reports:**
  - `backend/app/api/reports.py` (`_strict`, `_serve`, the six routes and their parameters);
  - `backend/app/services/reporting.py` (`ReportQuery`, `build_report`, `release_check`, `PERMISSIONS`, `FINANCE_SPLIT`);
  - `backend/app/reporting/csv_export.py` and `credit_csv.py` (`report_csv`, `MAX_ROWS`, `MAX_BYTES`).
- **Access:** `backend/app/services/access.py` (`Principal`, `resolve_scope`) and `backend/app/services/tenancy.py` (roles, `get_client`, `require_financial_access`, `update_client`).
- **Encryption:** `backend/app/privacy/token_secrets.py` and one of its users, for example `backend/app/services/connectors.py` (`_new_secret`).
- **The paths that must revoke:**
  - `erase_subject` in `backend/app/services/collection.py` (004) and `IdentityAdmin.erase` in `backend/app/services/identity_admin.py` (006), with their `target_outcomes`;
  - `start_disconnect` in `backend/app/services/connectors.py`, which every disconnection uses: the member's request, lost authorization, the provider callbacks of `backend/app/services/connector_callbacks.py` and `backend/app/connector_purge.py`;
  - client archival in `TenancyService.update_client`.
- **Mail:** `backend/app/services/mail.py` and `backend/app/mail_worker.py`.
- **Lifecycle and data policy:** `backend/app/services/lifecycle.py`, `backend/app/lifecycle.py`, `backend/app/data_policy.py` and `docs/engineering/data-lifecycle.md`.
- **Patterns to follow:**
  - `backend/app/attribution_worker.py` and `backend/app/connector_worker.py` (one-pass workers);
  - `backend/app/api/middleware.py` (`ROUTE_LIMITS`);
  - migrations `0026` to `0031` (scoped keys, grants, guarded downgrade).

## Authority

- **Gate.** Before any application or migration change, find D-095 in the decision register approving D1-D14 and any amendment it names. If it is missing, stop and ask the owner in Arabic, citing this gate from `AGENTS.md`; do not ask again for approvals already recorded.
- **Amendments.** If D-095 names an amendment (for example another lifetime or bound), it replaces the matching text of the entry review and of this handoff.
- **Precedence.** The latest owner instructions take precedence over this handoff. A fact found during implementation that changes a decision goes back to the owner before code depends on it.
- **Publication.** Push verified commits after each phase (D-051). At the end, open one pull request against `main` for review. Do not merge: the merge is a separate owner decision after review.

## Boundaries

- **Data.** Synthetic data only. Every database test runs on the disposable PostgreSQL 18 service of `backend/tests/README.md`; never point anything at native `tracking_sys`.
- **Schema and dependencies.** No new dependency. The only migration is the additive `0032_report_delivery` of D12. No change to merged migrations. No native rollout.
- **Out of scope.**
  - No PDF, printable page, frontend or React change (D-039, 018).
  - No external email address, no change to the Gmail transport and no figure in an email (D9, Q-008).
  - No shared cache, object storage, signed URL or download token (D4, D6, 020).
  - No plan limit for exports or schedules (017-C), and no change to Specs 012 or 013.
- **Existing behavior.** The direct CSV and every report answer stay byte for byte as they are. Every existing erasure outcome stays the same when no export exists: `report_exports` is reported only when an export was revoked.
- **Privacy.** No figure, name, token, secret or file content in any log line, audit event, worker output or email beyond the fields D9 lists.

## Phases

Each phase ends with its tests passing, ruff clean, a commit and a push. Record commands and counts as you go for the evidence file.

### P0: Inventory and design note

1. Verify the branch, `main` and D-095.
2. Inventory the report parameters of each family, every path of D7 that must revoke, and the locks each one holds.
3. Write `specs/016-analytics-reporting/design-016c.md`. It covers:
   - the exact DDL of `0032`: columns, checks, keys, indexes, grants and the data policy rows;
   - the request schema of an export and of a schedule for each family;
   - the visibility query of D3 and the permission checks of a download;
   - the store-time lock and recheck that make D7 race-free, against each revoking path;
   - the period rules of D8 with examples, including daylight-saving changes and month ends;
   - the worker algorithm of D10, its claims, retries and counts;
   - the email text and link of D9;
   - the PNG checks of D11;
   - a test inventory that maps every RV01-RV20 case to a test name.

   Section 4 of the entry review is the source. Resolve routine details here, and return only material new choices to the owner.
4. Commit and push.

### P1: Schema and retained exports

- **Migration.** Write `0032_report_delivery` and its ORM models, registered in `app.models`.
- **Data policy.** Add the `data_policy` rows for every new column, and update the table counts in `tests/test_data_policy.py` and `tests/integration/test_data_policy_schema.py`.
- **Downgrade.** It refuses stored rows, as `0027` does.
- **Exports.** Create, list, read, download and revoke (D2, D3, D5, D6), sealed under the token keyring (D4), with the audit events.
- **Lifecycle.** Delete expired exports and their content in bounded batches as `tracking_lifecycle`.
- **Tests.** RV01-RV05, RV09 and RV18.
- **Contract.** Regenerate the OpenAPI snapshot.

### P2: Automatic revocation

- **Calls.** Call `revoke_exports` from the 004 and 006 erasures (with the `report_exports` outcome), from `start_disconnect` for every cause, and from the client archival (D7).
- **Race.** Store an export only under the lock and recheck of the design note, so that none is stored after the event that should revoke it.
- **Tests.** RV06-RV08, with real concurrency for the overlap case of RV06.

### P3: Schedules, the worker and the emails

- **Routes.** The schedule routes and the recipient's leave route (D8, D9).
- **Worker.** `python -m app.report_worker` (D10).
- **Emails.** The `report_ready` outbox entries and their text (D9).
- **Tests.** RV10-RV16, with real concurrency for RV12.
- **Contract.** Regenerate the OpenAPI snapshot.

### P4: Branding

- **Routes.** The branding profile and logo routes (D11), with the route size limit.
- **Emails.** The display name in the emails of P3.
- **Tests.** RV17 and RV19.
- **Contract.** Regenerate the OpenAPI snapshot.

### P5: Verification, evidence and pull request

1. **Full verification.** From `backend/`, with the disposable database:
   - `ruff check app tests migrations` and `ruff format --check app tests migrations`;
   - `pytest -m "not integration" -q`;
   - `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1` and the tracker's local browsers (all modules, the browser journeys included);
   - from `packages/tracker-js`, `node --test test/unit/*.test.js` and `node --test --test-concurrency=1 test/browser/*.test.js` (Chromium and Firefox);
   - `pip check` and `git diff --check`;
   - a relative-link check of the changed Markdown.

   If `frontend/` exists on the branch, also run there, with Node.js 24.15 or later: `npm ci`, `npm run api:types`, `npm run api:check`, `npm run typecheck`, `npm run lint` and `npm test`. Commit the generated `src/api/schema.d.ts`, and change no other frontend code.

   Record exact counts. A skipped case is reported as skipped, never as passed.
2. **Mutation check.** Disable each new safeguard in turn and show that its test fails, then restore the source byte for byte (compare SHA-256). The safeguards are:
   - the visibility rule of client viewers;
   - the scope resolved again at download, and the `finance:read` check;
   - the binding of the seal to the export, agency and client;
   - each revocation path of D7, and the store-time lock and recheck;
   - the expiry deletion;
   - the 50-export and 10-schedule bounds;
   - the worker's claim, the owner's permission check and the recipient's check;
   - the email without figures;
   - the PNG checks.
3. **Documentation.**
   - `specs/016-analytics-reporting/evidence-016c.md`: commits, RV01-RV20 with test names and results, commands and counts, mutation results and limits.
   - The [reporting guide](../../docs/engineering/reporting.md) and the [data lifecycle guide](../../docs/engineering/data-lifecycle.md).
   - The 016 spec, plan and tasks.
   - The status lines in `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md`.
4. **Pull request.** Push, then open one pull request from `codex/spec-016c-report-delivery` against `main`. Follow `.github/pull_request_template.md` if one exists. Describe:
   - the decisions (D-094, D-095);
   - the scope and the three parts;
   - the schema;
   - the routes, the worker and the permissions;
   - the verification counts;
   - the API changes;
   - the limits;
   - what remains (the frontend pages and branded screens, PDF files, production storage, keys and email, digests).

   Do not merge.
5. **Report.** Tell the owner in Arabic:
   - the pull request link and head commit;
   - what was built;
   - the tests actually executed with their counts;
   - every limitation;
   - that the branch is ready for Claude's independent review.

## What success looks like

- A member saves a report, downloads it for 7 days with the permissions they hold at that moment, and nobody else can.
- An erasure, a disconnection or an archival revokes the exports it covers at once, and no export escapes it through a race.
- A manager schedules a report; it is built on time with its owner's permissions, and each recipient who may read it is told by an email that carries no data.
- An agency keeps a branding profile; report emails carry its display name, and the frontend can apply the profile to its clients' screens later.
- Nothing outside the approved scope changes.
