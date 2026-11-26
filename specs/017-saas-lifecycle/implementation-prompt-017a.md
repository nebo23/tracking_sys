# Spec 017-A implementation: plans, limits and agency closure

Prepared 2026-11-26 under D-091. It executes once the owner's approval of decisions D1-D14 of the [017-A entry review](entry-review-017a.md) is recorded as D-092. Communicate with the owner in Arabic, and write every project file, commit and pull request in formal English. Save this handoff as `specs/017-saas-lifecycle/implementation-prompt-017a.md` on the branch below.

## Where to work

1. Fetch `origin`.
2. Create `codex/spec-017a-saas-plans` from the current `origin/claude/keen-fermat-otlr9d`. That branch is merged `main` at `633ea9a` (PR 18) plus the D-091 records, this preparation and D-092. Verify that `git merge-base --is-ancestor 633ea9a HEAD` succeeds.
3. Check `origin/main`. If it moved beyond `633ea9a`, merge it into the branch first and report what changed. Pull request 17 (Spec 018) may have merged by then:
   - In `AGENTS.md` and `docs/planning/decisions.md`, keep both sets of decisions in numeric order. D-081 to D-087 belong to Spec 018, and D-091 and D-092 to this work. Remove the placeholder notes that say D-081 to D-087 are recorded elsewhere, and keep the numbering note of Spec 018.
   - If `frontend/` now exists, the frontend checks of P5 apply.
4. Use a fresh worktree, and preserve owner files and other checkouts.
5. A new decision record takes the next free number after the highest one on `main`, on this branch and on any open pull request. Check before recording.

Read the following before the first change:
- **Project rules and decisions:** `AGENTS.md`, `README.md`, and in `docs/planning/decisions.md` D-024, D-083 (on the Spec 018 branch, decision D15 of its entry review), D-091 and D-092.
- **The packet:** the [017-A entry review](entry-review-017a.md), D1-D14, design section 4 and verification matrix section 5.
- **Spec 017:** the [spec](spec.md), the [plan](plan.md) and the [tasks](tasks.md).
- **Tenancy and access (002, 003):**
  - `backend/app/models/tenancy.py`, `backend/app/models/access.py` and `backend/app/models/auth.py`;
  - `backend/app/services/tenancy.py` (the agency write lock, `_membership`, `_manager`, the Owner rules);
  - `backend/app/services/access.py` (`resolve_scope`, invitations, service keys);
  - `backend/app/services/auth.py` (`register`, `login`, `close_account`);
  - `backend/app/services/google.py`;
  - `backend/app/api/tenancy.py` and `backend/app/api/auth.py`;
  - `specs/002-tenancy-access/auth-design.md`.
- **Every check of the agency status:** search for `Agency.status` in `backend/app/services/` (links, collection, connectors, delivery, payments, integrations, WhatsApp, attribution store, access).
- **The creation points:** `create_client`, `add_member`, `invite`, the connector `begin`, `create_link`.
- **Lifecycle and data policy:** `backend/app/services/lifecycle.py`, `backend/app/lifecycle.py`, `backend/app/data_policy.py` and `docs/engineering/data-lifecycle.md`.
- **Patterns to follow:**
  - `backend/app/whatsapp_binding.py` and `backend/app/connector_purge.py` (operator commands);
  - migrations `0026` to `0030` (scoped keys, grants, guarded downgrade);
  - `backend/app/api/public_cors.py` and `backend/app/main.py` (CORS).

## Authority

- **Gate.** Before any application or migration change, find D-092 in the decision register approving D1-D14 and any amendment it names. If it is missing, stop and ask the owner in Arabic, citing this gate from `AGENTS.md`; do not ask again for approvals already recorded.
- **Amendments.** If D-092 names an amendment (for example other default limits or another grace period), it replaces the matching text of the entry review and of this handoff.
- **Precedence.** The latest owner instructions take precedence over this handoff. A fact found during implementation that changes a decision goes back to the owner before code depends on it.
- **Publication.** Push verified commits after each phase (D-051). At the end, open one pull request against `main` for review. Do not merge: the merge is a separate owner decision after review.

## Boundaries

- **Data.** Synthetic data only. Every database test runs on the disposable PostgreSQL 18 service of `backend/tests/README.md`; never point anything at native `tracking_sys`.
- **Schema and dependencies.** No new dependency. The only migration is the additive `0031_saas_plans` of D12. No change to merged migrations. No native rollout.
- **Out of scope.**
  - No price, currency, payment provider, trial or invoice (017-C).
  - No purge, export or provider token revocation for closed agencies (017-B).
  - No frontend or React work, no live provider call, no change to Specs 012 or 013.
- **Existing behavior.** An agency within its limits behaves exactly as before. Keep every existing check of `status == 'active'`; a closing or closed agency must fail those checks. Do not weaken the Owner rules of 002.
- **Privacy.** No password, token, contact value or secret in any new row, response, audit event, log line or command output.

## Phases

Each phase ends with its tests passing, ruff clean, a commit and a push. Record commands and counts as you go for the evidence file.

### P0: Inventory and design note

1. Verify the branch, `main` and D-092.
2. Inventory every check of the agency status, every creation point and every place that a closing agency must stop. Confirm that each one refuses a non-active agency today.
3. Write `specs/017-saas-lifecycle/design-017a.md`. It covers:
   - the exact DDL of `0031`: columns, checks, keys, indexes, grants and the seed;
   - each limit's counting statement and the lock it runs under;
   - the usage view's answer shape and its bound;
   - the closure state machine, its routes and their error codes, and the lifecycle step;
   - the agreement fields of each authentication request and the order of the checks;
   - the operator command's subcommands and output;
   - the changes to the authentication test helpers;
   - a test inventory that maps every SV01-SV20 case to a test name.

   Section 4 of the entry review is the source. Resolve routine details here, and return only material new choices to the owner.
4. Commit and push.

### P1: Schema, plans and the operator command

- **Migration.** Write `0031_saas_plans` and its ORM models, registered in `app.models`. It seeds the `development` plan with the D3 values, assigns it to every existing agency and widens `agencies.status`.
- **Data policy.** Add the `data_policy` rows for every new column, and update the table counts in `tests/test_data_policy.py` and `tests/integration/test_data_policy_schema.py`.
- **Downgrade.** It refuses stored rows, as `0027` does.
- **Default plan.** A new agency gets the current default plan in the same transaction as its creation.
- **Command.** Write `backend/app/agency_plans.py` with the D7 subcommands, `--confirm` and the audit events. Extend the closed audit action and resource lists.
- **Tests.** SV01, SV08, SV09 and SV18.

### P2: Limits and the usage view

- **Enforcement.** Add the limit check to each creation point of section 4.2, under the agency lock, with `409 plan_limit_reached`.
- **Route.** `GET /agencies/{agency_id}/plan` (D6).
- **Tests.** SV02 to SV07, with real concurrency for SV03, modeled on the existing concurrency tests.
- **Contract.** Regenerate the OpenAPI snapshot.

### P3: Agency closure

- **Routes.** `POST`, `GET` and `DELETE /agencies/{agency_id}/closure` (D8, section 4.4).
- **Status.** A closing or closed agency fails every existing active check; only the closure routes and `GET /agencies` read a closing agency, for its Owners.
- **Lifecycle.** Add the completion step to the lifecycle runner, bounded and idempotent.
- **Account closure.** `close_account` ignores closing and closed agencies when it looks for a sole Owner (D9).
- **Tests.** SV10 to SV14, including every intake path and worker of SV11.

### P4: Agreement record and `Retry-After`

- **Settings.** `terms_version` and `privacy_version` with the development value `draft-1`.
- **Requests.** The agreement fields of registration, password sign-in and the Google completion, the refusal `422 agreement_required` and the record (D10, section 4.5).
- **Discovery.** `GET /auth/agreements`.
- **Test helpers.** Update the shared authentication helpers of the test suites so that every existing test sends the current versions.
- **CORS.** Expose `Retry-After` on platform CORS (D11).
- **Tests.** SV15, SV16 and SV17.
- **Contract.** Regenerate the OpenAPI snapshot.

### P5: Verification, evidence and pull request

1. **Full verification.** From `backend/`, with the disposable database:
   - `ruff check app tests migrations` and `ruff format --check app tests migrations`;
   - `pytest -m "not integration" -q`;
   - `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1` and the tracker's local browsers (all modules, the browser journeys included);
   - from `packages/tracker-js`, `node --test test/unit/*.test.js` and `node --test --test-concurrency=1 test/browser/*.test.js` (Chromium and Firefox);
   - `pip check` and `git diff --check`;
   - a relative-link check of the changed Markdown.

   If `frontend/` exists on the branch, also run there, with Node.js 24.15 or later: `npm ci`, `npm run api:types`, `npm run api:check`, `npm run typecheck`, `npm run lint` and `npm test`. Commit the generated `src/api/schema.d.ts`. The frontend's sign-in and registration must then send the agreement versions; report the change it needs, and do not change frontend code beyond the generated types.

   Record exact counts. A skipped case is reported as skipped, never as passed.
2. **Mutation check.** Disable each new safeguard in turn and show that its test fails, then restore the source byte for byte (compare SHA-256). The safeguards are:
   - the limit check of each of the four limits;
   - the lock around the count;
   - the refusal of a closing agency in the intake and the workers;
   - the Owner-only closure;
   - the reauthentication of the closure;
   - the completion step;
   - the sole-Owner rule;
   - the agreement check;
   - the single record per version;
   - `--confirm`.
3. **Documentation.**
   - `specs/017-saas-lifecycle/evidence-017a.md`: commits, SV01-SV20 with test names and results, commands and counts, mutation results and limits.
   - A developer guide `docs/engineering/plans-and-closure.md`, linked from the tenancy and data lifecycle guides.
   - The 017 spec, plan and tasks.
   - The status lines in `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md`.
4. **Pull request.** Push, then open one pull request from `codex/spec-017a-saas-plans` against `main`. Follow `.github/pull_request_template.md` if one exists. Describe:
   - the decisions (D-091, D-092);
   - the scope and the seven parts;
   - the schema and the seed;
   - the routes, the command and the permissions;
   - the change that the frontend's sign-in and registration need;
   - the verification counts;
   - the API changes;
   - the limits;
   - what remains (017-B purge and export, 017-C billing, 016-C, the React UI, native rollout).

   Do not merge.
5. **Report.** Tell the owner in Arabic:
   - the pull request link and head commit;
   - what was built;
   - the tests actually executed with their counts;
   - every limitation;
   - that the branch is ready for Claude's independent review.

## What success looks like

- Every agency has a plan, and the server refuses a creation beyond a limit while nothing that exists breaks.
- An Owner, Admin or Analyst sees the plan and the current use; the operator manages plans from the command line.
- Tracked events beyond the allowance are kept and flagged, never dropped.
- An Owner can close an agency, everything stops at once, and the closure can be cancelled within 30 days.
- The sole Owner of a closed agency can close their account.
- Every account records the terms and privacy versions it agreed to.
- The interface can read `Retry-After`.
- Nothing outside the approved scope changes.
