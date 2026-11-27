# Spec 017-B implementation: offboarding export, provider disconnection and the purge of closed agencies

Prepared 2026-11-27 under D-097. The owner approved decisions D1-D14 of the [017-B entry review](entry-review-017b.md) as recommended, without amendment, on 2026-11-27; the approval is recorded as D-098, so this handoff is ready to execute. Communicate with the owner in Arabic, and write every project file, commit and pull request in formal English. Save this handoff as `specs/017-saas-lifecycle/implementation-prompt-017b.md` on the branch below.

## Where to work

1. Fetch `origin`.
2. Create `codex/spec-017b-agency-offboarding` from the current `origin/claude/keen-fermat-otlr9d`. That branch is merged `main` at `e3b3005` (PR 20) plus the D-096 records, this preparation and D-098. Verify that `git merge-base --is-ancestor e3b3005 HEAD` succeeds.
3. Check `origin/main`. If it moved beyond `e3b3005`, merge it into the branch first and report what changed. Pull request 17 (Spec 018) may have merged by then:
   - In `AGENTS.md` and `docs/planning/decisions.md`, keep every decision in numeric order. D-081 to D-087 belong to Spec 018, and D-097 and D-098 to this work. Remove the placeholder notes that say D-081 to D-087 are recorded elsewhere, and keep the numbering note of Spec 018.
   - The branch `codex/spec-018-workspace-screens` numbers two of its decisions D-093 and D-094, which `main` already uses (D-096). Do not change that branch; if its work has reached `main`, report the collision instead of renumbering it.
   - If `frontend/` now exists, the frontend checks of P5 apply.
4. Use a fresh worktree, and preserve owner files and other checkouts.
5. A new decision record takes the next free number after the highest one on `main`, on this branch, on any open pull request and on `codex/spec-018-workspace-screens`. Check before recording.

Read the following before the first change:
- **Project rules and decisions:** `AGENTS.md`, `README.md`, and in `docs/planning/decisions.md` D-024, D-025, D-091, D-092, D-095, D-096, D-097 and D-098.
- **The packet:** the [017-B entry review](entry-review-017b.md), D1-D14, design section 4 and verification matrix section 5.
- **Spec 017:** the [spec](spec.md), the [plan](plan.md), the [tasks](tasks.md), the [017-A design note](design-017a.md) (closure, completion, the sole-Owner rule) and the [plans and closure guide](../../docs/engineering/plans-and-closure.md).
- **The 003 contract:** sections 10, 11, 12 and 15 of `specs/003-privacy-data-policy/design.md` (deletion scopes, exports, backups, roles).
- **Closure and lifecycle:**
  - `backend/app/services/agency_closure.py` and `backend/app/services/agency_lifecycle.py`;
  - `backend/app/services/lifecycle.py` (the runner, its targets, batches and lock timeouts) and `backend/app/lifecycle.py`;
  - `backend/app/data_policy.py` and `docs/engineering/data-lifecycle.md`.
- **Connectors:** `start_disconnect`, `run_teardowns` and `_claim_teardowns` in `backend/app/services/connectors.py`, and `backend/app/connector_purge.py` (the operator purge and its outcome counts).
- **Exports (016-C):** `backend/app/services/report_exports.py` (sealing, reservation, download) and `backend/app/privacy/token_secrets.py` (`seal_bytes`, `open_bytes`).
- **Every tenant table:** the models under `backend/app/models/`, and `TABLES` in `backend/tests/integration/conftest.py`, which is a valid children-first order.
- **Patterns to follow:**
  - `backend/app/agency_plans.py` and `backend/app/whatsapp_binding.py` (operator commands);
  - `backend/app/report_worker.py` (one-pass workers);
  - migrations `0026` to `0032` (scoped keys, grants, guarded downgrade).

## Authority

- **Gate.** Before any application or migration change, find D-098 in the decision register approving D1-D14 and any amendment it names. If it is missing, stop and ask the owner in Arabic, citing this gate from `AGENTS.md`; do not ask again for approvals already recorded.
- **Amendments.** If D-098 names an amendment (for example another export window, bound or retained record), it replaces the matching text of the entry review and of this handoff.
- **Precedence.** The latest owner instructions take precedence over this handoff. A fact found during implementation that changes a decision goes back to the owner before code depends on it, for example a provider rule that forbids a step of D6.
- **Publication.** Push verified commits after each phase (D-051). At the end, open one pull request against `main` for review. Do not merge: the merge is a separate owner decision after review.

## Boundaries

- **Data.** Synthetic data only. Every database test runs on the disposable PostgreSQL 18 service of `backend/tests/README.md`; never point anything at native `tracking_sys`.
- **Schema and dependencies.** No new dependency: the ZIP is built with the standard library. The only migration is the additive `0033_agency_offboarding` of D12. No change to merged migrations. No native rollout.
- **Providers.** No live provider call. The tests' revocations reach the synthetic providers only; the teardown of live connections is an owner-operated check after the merge.
- **Out of scope.**
  - No frontend or React change, no billing, price or trial (017-C), and no backup tooling (020).
  - No export of provider-sourced data, secrets, keys, digests, tokens, or audit and security logs (D4).
  - No change to Specs 012 or 013.
- **Existing behavior.** Agencies that are not closed behave exactly as before, and every existing suite passes. The guard of D9 must make it impossible for the lifecycle role to delete a row of an agency that is not closed and offboarded.
- **Privacy.** No name, figure, token, secret or file content in any log line, audit event, worker output or command output.

## Phases

Each phase ends with its tests passing, ruff clean, a commit and a push. Record commands and counts as you go for the evidence file.

### P0: Inventory and design note

1. Verify the branch, `main` and D-098.
2. Inventory every table that carries `agency_id` or `client_id`. For each one, record: its delete order, its index on the agency or client column, its foreign keys, and whether D4 exports it, with the columns and the excluded columns.
3. Write `specs/017-saas-lifecycle/design-017b.md`. It covers:
   - the exact DDL of `0033`: columns, checks, keys, indexes, grants, data policy rows and the body of `purge_agency_batch`;
   - the export catalog: each table, its columns, its file name and the rule for each excluded column;
   - the export build: snapshot, ZIP layout, manifest, parts, bounds, and the checks before storing;
   - the offboarding pass of D6: every step, its lock and its idempotence;
   - the teardown wait and the purge loop of D7, with their bounds;
   - the record that stays (D8) and the pseudonym of the agency's name;
   - the operator command of D11;
   - a test inventory that maps every OV01-OV20 case to a test name.

   Section 4 of the entry review is the source. Resolve routine details here, and return only material new choices to the owner.
4. Commit and push.

### P1: Schema and the guarded purge function

- **Migration.** Write `0033_agency_offboarding` and its ORM models, registered in `app.models`, with the function of D9 and its grant.
- **Data policy.** Add the `data_policy` rows for every new column, and update the end-of-life rules that said "offboarding is 017" so that they name the 017-B purge. Update the table counts in `tests/test_data_policy.py` and `tests/integration/test_data_policy_schema.py`.
- **Downgrade.** It refuses stored rows, as `0027` does.
- **Tests.** OV09 (the table list), OV12 and OV18.

### P2: Offboarding and the purge

- **Offboarding.** The pass of D6 in `python -m app.offboarding_worker`, as the runtime role.
- **Purge.** The lifecycle runner's purge step (D7), the record of D8 and the pseudonym.
- **Operator command.** `python -m app.agency_offboarding` (D11).
- **Tests.** OV07-OV11, OV13-OV16, with synthetic providers for OV08.

### P3: The offboarding export

- **Routes.** The three export routes of section 4.2 (D2, D3).
- **Build.** The worker's export build, the catalog, the manifest, the bounds and the sealed parts (D4, D5).
- **Tests.** OV01-OV06 and OV17.
- **Contract.** Regenerate the OpenAPI snapshot.

### P4: Concurrency and the full lifecycle

- **Journey.** One end-to-end test: request closure, request and download the export, complete the closure, offboard, settle the teardowns, purge, and check what stays.
- **Concurrency.** OV17 with real concurrency: the completion against an export build, two offboarding workers, and the purge against a late worker.
- **Logs.** OV19.

### P5: Verification, evidence and pull request

1. **Full verification.** From `backend/`, with the disposable database:
   - `ruff check app tests migrations` and `ruff format --check app tests migrations`;
   - `pytest -m "not integration" -q`;
   - `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1` and the tracker's local browsers (all modules, the browser journeys included);
   - from `packages/tracker-js`, `node --test test/unit/*.test.js` and `node --test --test-concurrency=1 test/browser/*.test.js` (Chromium and Firefox);
   - `pip check` and `git diff --check`;
   - a relative-link check of the changed Markdown.

   If `frontend/` exists on the branch, also run there, with Node.js 24.15 or later: `npm ci`, `npm run api:types`, `npm run api:check`, `npm run typecheck`, `npm run lint` and `npm test`. Commit the generated `src/api/schema.d.ts`, and change no other frontend code.

   Record exact counts. A skipped case is reported as skipped, never as passed. A failure that does not reproduce is reported with its output and the reruns that passed.
2. **Mutation check.** Disable each new safeguard in turn and show that its test fails, then restore the source byte for byte (compare SHA-256). The safeguards are:
   - the function's refusal of an agency that is not closed and offboarded;
   - the purge's completeness, by leaving one table out of the function;
   - the teardown wait;
   - the Owner-only, reauthenticated export request and its 24-hour cut-off;
   - the scope resolved again at download;
   - the exclusion of provider data and secret columns;
   - the bound of D5;
   - the check before storing an export;
   - each revocation of D6;
   - the pseudonym of the agency's name;
   - `--confirm`.
3. **Documentation.**
   - `specs/017-saas-lifecycle/evidence-017b.md`: commits, OV01-OV20 with test names and results, commands and counts, mutation results and limits.
   - The [plans and closure guide](../../docs/engineering/plans-and-closure.md) and the [data lifecycle guide](../../docs/engineering/data-lifecycle.md).
   - The 017 spec, plan and tasks.
   - The status lines in `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md`.
4. **Pull request.** Push, then open one pull request from `codex/spec-017b-agency-offboarding` against `main`. Follow `.github/pull_request_template.md` if one exists. Describe:
   - the decisions (D-097, D-098);
   - the scope and the three parts;
   - the schema and the guarded function;
   - the routes, the workers, the command and the permissions;
   - the verification counts;
   - the API changes;
   - the limits;
   - what remains (017-C, the purge journal of restores and the worker schedule in 020, the live teardown checks, the frontend pages).

   Do not merge.
5. **Report.** Tell the owner in Arabic:
   - the pull request link and head commit;
   - what was built;
   - the tests actually executed with their counts;
   - every limitation;
   - that the branch is ready for Claude's independent review.

## What success looks like

- An Owner of a closing agency downloads all of the agency's first-party data in one file, and nobody else can.
- When the closure completes, every connection is disconnected and every token is revoked at its provider.
- Once the teardowns settle, no row of the agency remains anywhere, apart from the minimal record of D8.
- No agency that is not closed can lose a single row to the purge.
- Nothing outside the approved scope changes.
