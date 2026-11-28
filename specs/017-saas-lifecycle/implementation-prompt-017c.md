# Spec 017-C implementation: subscription billing, prices and the trial

Prepared 2026-11-28 under D-102. The owner approved decisions D1-D14 of the [017-C entry review](entry-review-017c.md) as recommended, without amendment, on 2026-11-28; the approval is recorded as D-103, so this handoff is ready to execute. Communicate with the owner in Arabic, and write every project file, commit and pull request in formal English. Save this handoff as `specs/017-saas-lifecycle/implementation-prompt-017c.md` on the branch below.

## Where to work

1. Fetch `origin`.
2. Create `codex/spec-017c-saas-billing` from the current `origin/claude/keen-fermat-otlr9d`. That branch is merged `main` at `04dc323` (PR 21) plus the D-099 records, the setup-guide correction, this preparation and D-103. Verify that `git merge-base --is-ancestor 04dc323 HEAD` succeeds.
3. Check `origin/main`. If it moved beyond `04dc323`, merge it into the branch first and report what changed. Pull request 17 (Spec 018) or `codex/spec-018-workspace-screens` may have merged by then:
   - In `AGENTS.md` and `docs/planning/decisions.md`, keep every decision in numeric order. D-081 to D-087 belong to Spec 018 (pull request 17), D-100 and D-101 to `codex/spec-018-workspace-screens`, and D-102 and D-103 to this work. Remove a placeholder note once the decisions it reserves are on `main`.
   - `codex/spec-018-workspace-screens` also records a D-099 of its own, which `main` already uses for the 017-B merge. Do not change that branch; if its work has reached `main`, report the collision instead of renumbering it.
   - If `frontend/` now holds the application, the frontend checks of P5 apply.
4. Use a fresh worktree, and preserve owner files and other checkouts.
5. A new decision record takes the next free number after the highest one on `main`, on this branch, on any open pull request and on `codex/spec-018-workspace-screens`. Check before recording.

Read the following before the first change:
- **Project rules and decisions:** `AGENTS.md`, `README.md`, and in `docs/planning/decisions.md` D-024, D-025, D-051, D-091, D-092, D-098, D-099, D-102 and D-103.
- **The packet:** the [017-C entry review](entry-review-017c.md): its research (section 3), D1-D14, the design of section 5, the verification matrix of section 6 and the provider facts of section 7.
- **Spec 017:** the [spec](spec.md), the [plan](plan.md), the [tasks](tasks.md), the [017-A design note](design-017a.md), the [017-B design note](design-017b.md) and the [plans and closure guide](../../docs/engineering/plans-and-closure.md).
- **Plans, agencies and closure:**
  - `backend/app/services/plans.py` (`default_plan`, `assign_default` and the assignment helper), `backend/app/agency_plans.py` and `backend/app/models/saas.py`;
  - `create_agency` and the agency lock (`TenancyService._manager(write=True)`) in `backend/app/services/tenancy.py`;
  - `backend/app/services/agency_closure.py` and `backend/app/services/agency_lifecycle.py` (request, cancellation, completion);
  - `backend/app/services/agency_purge.py`, the function `purge_agency_batch` in `backend/migrations/versions/0033_agency_offboarding.py`, and `test_ov09_function_covers_every_scoped_table` in `backend/tests/integration/test_agency_offboarding_migration.py`.
- **Signed intake and outbound calls:**
  - `backend/app/api/payments.py` and `backend/app/services/payments.py` (the gate, rate limits, raw body and signature check of 015);
  - `ROUTE_LIMITS` in `backend/app/api/middleware.py`;
  - `backend/app/connectors/meta_ads.py` (standard-library transport, timeouts, closed error codes) and `backend/tests/meta_graph.py` (a synthetic provider server).
- **Mail, workers and rules:**
  - `backend/app/services/mail.py` (the link-only `report_ready` message);
  - `backend/app/report_worker.py` (one-pass workers);
  - `backend/app/services/lifecycle.py` (retention targets and batches);
  - `backend/app/privacy/providers.py` (provider rules and review dates) and `backend/app/data_policy.py`.
- **Patterns to follow:** migrations `0031` to `0033` (checks, scoped keys, grants, guarded downgrade) and `TABLES` in `backend/tests/integration/conftest.py`, which is a valid children-first order.

## Authority

- **Gate.** Before any application or migration change, find D-103 in the decision register approving D1-D14 and any amendment it names. If it is missing, stop and ask the owner in Arabic, citing this gate from `AGENTS.md`; do not ask again for approvals already recorded.
- **Amendments.** If D-103 names an amendment (for example another trial length, hold rule or proration mode), it replaces the matching text of the entry review and of this handoff.
- **Precedence.** The latest owner instructions take precedence over this handoff. A provider fact found in Phase 0 that changes a decision goes back to the owner before code depends on it, for example a signature format or a cancellation rule that differs from section 3.2 of the entry review.
- **Publication.** Push verified commits after each phase (D-051). At the end, open one pull request against `main` for review. Do not merge: the merge is a separate owner decision after review.

## Boundaries

- **Data.** Synthetic data only. Every database test runs on the disposable PostgreSQL 18 service of `backend/tests/README.md`; never point anything at native `tracking_sys`.
- **Schema and dependencies.** No new dependency: the adapter uses `urllib`, and the signature uses `hmac` and `hashlib`. The only migration is the additive `0034_saas_billing` of D13. No change to merged migrations. No native rollout.
- **Provider.** No live Paddle call and no change to any Paddle account. The tests run the adapter against a synthetic Paddle-shaped server and send signed events from a synthetic sender. The sandbox check with an owner account comes after the merge.
- **Out of scope.**
  - No frontend or React change: the pages and Paddle.js belong to 018.
  - No second provider, no usage-based price, no automatic suspension or closure for non-payment (D5), and no platform receipt (D11).
  - No change to the agency-client revenue of 015 (Paymob sources, evidence, ledger), and no change to Specs 012 or 013.
- **Existing behavior.** While billing is disabled, every agency behaves exactly as before, and every existing suite passes. Billing never writes revenue evidence, the ledger or a 015 payment source.
- **Privacy.** No API key, webhook secret, signature, name, email, address, card detail or invoice address in any log line, audit event, answer, worker output or command output.

## Phases

Each phase ends with its tests passing, ruff clean, a commit and a push. Record commands and counts as you go for the evidence file.

### P0: Provider facts and design note

1. Verify the branch, `main` and D-103.
2. Verify the provider facts V-1 to V-16 of section 7 against Paddle's official pages (developer.paddle.com and paddle.com) and, for V-16, Stripe's. Record each fact with its address and the date read. Report every difference, and return a difference that changes a decision to the owner before continuing.
3. Write `specs/017-saas-lifecycle/design-017c.md`. It covers:
   - the exact DDL of `0034`: columns, checks, keys, indexes, grants, data policy rows, the `billing_hold` plan seed, the widened assignment values and the new body of `purge_agency_batch`;
   - the standing transitions of section 5.2, each with its lock, its plan assignment, its audit action and its message;
   - the event mapping: each Paddle event type, the fields read, the allowlisted fields stored, its outcome and its effect;
   - the adapter: each call's method, path, headers, body, timeout and error codes, and the synthetic server that implements them;
   - the routes of section 5.3 with their answers and refusal codes;
   - the worker steps of section 5.6 with their bounds;
   - the operator command of D12;
   - the settings of section 5.7 and their validation;
   - a test inventory that maps every case BL01-BL23 to a test name.

   The entry review is the source. Resolve routine details here, and return only material new choices to the owner.
4. Commit and push.

### P1: Schema

- **Migration.** Write `0034_saas_billing` and its ORM models, registered in `app.models` (D13).
- **Purge.** Update `purge_agency_batch` for the new tables (D10): delete the agency's standing, checkouts, events and actions; keep its subscriptions, payments and adjustments. Extend `test_ov09_function_covers_every_scoped_table` with the kept tables and the reason each one stays.
- **Data policy.** Add the `data_policy` rows for every new column, with `billing_events` at 13 months (provisional, Q-012) and the kept financial records named as such. Update the table counts in `tests/test_data_policy.py` and `tests/integration/test_data_policy_schema.py`.
- **Downgrade.** It refuses stored rows, as `0027` does.
- **Tests.** BL21, and the schema half of BL15.

### P2: Standing, trial, hold and the operator command

- **Standing.** The standing service under the agency lock, with every transition of section 5.2 and its plan assignment. `create_agency` records the trial, or the complimentary standing while billing is disabled, in the same transaction.
- **Worker.** `python -m app.billing_worker` with the trial reminders, the end of trials and grants, and the two messages of D11.
- **Command.** `python -m app.agency_billing` with `prices`, `register-price`, `retire-price`, `status`, `grant`, `end-grant`, `extend-trial` and `agencies` (D12).
- **Settings.** Section 5.7, with the validation that enabling billing requires the key and the secret.
- **Tests.** BL01-BL04, BL18 for these subcommands, BL20 and the settings part of BL22.

### P3: Paddle adapter and webhook

- **Adapter.** The calls of section 5.5, against the synthetic Paddle-shaped server.
- **Webhook.** `POST /billing/paddle/webhook` in the order of D7, with its body bound in `ROUTE_LIMITS`, the `paddle.billing` provider rule and the event processing of section 5.4.
- **Records.** Subscriptions, payments, adjustments, unmatched events and duplicate subscriptions, and the `events` and `duplicates` subcommands.
- **Tests.** BL06-BL08, BL10, BL12, BL16, BL19 and the log part of BL22.

### P4: Owner routes, closure and reconciliation

- **Routes.** Section 5.3: prices, the billing view, checkout (D6), plan changes with the preview (D8), cancellation and its undo (D9), the payment-method transaction, the payment history and the invoice redirect (D11).
- **Closure.** The actions of D10, queued by the closure request, its cancellation and its completion, and executed by the worker with bounded retries.
- **Reconciliation.** The worker's reconciliation step and the `reconcile` subcommand; the lifecycle runner's retention of events and expired checkouts.
- **Journey.** One end-to-end test: create an agency, run out its trial onto hold, check out, activate, upgrade, fail a renewal and recover it, cancel at the period end, return to hold, and close the agency through the purge.
- **Tests.** BL05, BL09, BL11, BL13-BL15, BL17 and BL23.
- **Contract.** Regenerate the OpenAPI snapshot.

### P5: Verification, evidence and pull request

1. **Full verification.** From `backend/`, with the disposable database:
   - `ruff check app tests migrations` and `ruff format --check app tests migrations`;
   - `pytest -m "not integration" -q`;
   - `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1` and the tracker's local browsers (all modules, the browser journeys included);
   - from `packages/tracker-js`, `node --test test/unit/*.test.js` and `node --test --test-concurrency=1 test/browser/*.test.js` (Chromium and Firefox);
   - `pip check` and `git diff --check`;
   - a relative-link check of the changed Markdown.

   If `frontend/` holds the application on the branch, also run there, with Node.js 24.15 or later: `npm ci`, `npm run api:types`, `npm run api:check`, `npm run typecheck`, `npm run lint` and `npm test`. Commit the generated `src/api/schema.d.ts`, and change no other frontend code.

   Record exact counts. A skipped case is reported as skipped, never as passed. A failure that does not reproduce is reported with its output and the reruns that passed.
2. **Mutation check.** Disable each new safeguard in turn and show that its test fails, then restore the source byte for byte (compare SHA-256). The safeguards are:
   - the signature check and the timestamp tolerance;
   - the uniqueness of `event_id` and the `stale` order check;
   - the binding of a subscription through the checkout's transaction ID;
   - the Owner-only checkout, the single open checkout and `already_subscribed`;
   - the hold's plan assignment;
   - the absence of any standing effect while billing is disabled;
   - the closure's cancellation action;
   - the purge's delete and keep lists;
   - the separation from agency-client revenue;
   - the redaction of secrets;
   - `--confirm`.
3. **Documentation.**
   - `specs/017-saas-lifecycle/evidence-017c.md`: commits, the V-1 to V-16 record, BL01-BL23 with test names and results, commands and counts, mutation results and limits.
   - A billing guide, `docs/engineering/billing.md`, linked from the [plans and closure guide](../../docs/engineering/plans-and-closure.md), and the [data lifecycle guide](../../docs/engineering/data-lifecycle.md).
   - The new settings in `.env.example`, blank or off.
   - The 017 spec, plan and tasks, and Q-005 in the decision register.
   - The status lines in `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md`.
4. **Pull request.** Push, then open one pull request from `codex/spec-017c-saas-billing` against `main`. Follow `.github/pull_request_template.md` if one exists. Describe:
   - the decisions (D-102, D-103);
   - the scope: the billing core, the trial, the hold and the Paddle adapter;
   - the schema and the purge changes;
   - the routes, the webhook, the worker, the command and the permissions;
   - the provider facts and any difference found;
   - the verification counts;
   - the API changes;
   - the limits;
   - what remains (the 018 pages with Paddle.js, hosting and the webhook address in 020, the Paddle sandbox check and the live account approval).

   Do not merge.
5. **Report.** Tell the owner in Arabic:
   - the pull request link and head commit;
   - what was built;
   - the tests actually executed with their counts;
   - every provider fact that differed from the entry review;
   - every limitation;
   - that the branch is ready for Claude's independent review.

## What success looks like

- A new agency tries the platform for 14 days, then subscribes in USD through Paddle, and its limits follow what it pays for.
- An agency that stops paying cannot add anything, but its clients' links, tracking, reports and data keep working, and nothing is deleted.
- A repeated, late or forged webhook never changes an agency's standing twice, backwards, or at all.
- No two subscriptions arise from one agency's checkouts, and platform billing never touches agency-client revenue.
- Nothing outside the approved scope changes.
