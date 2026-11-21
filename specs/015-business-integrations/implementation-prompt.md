# Spec 015 implementation, first round: payments (Paymob) and the CSV and manual fallback, and the pull request

Work in the owner's local repository, for example in a worktree `C:\Code\Tracking-system\.worktrees\spec-015-business-integrations`. Use a new branch `codex/spec-015-business-integrations` (D-023). Fetch `claude/gallant-cray-b16xwk` and create the branch from `origin/claude/gallant-cray-b16xwk`, which holds this preparation on top of merged `main` at `73efae9` (PR 12, Spec 014). If `main` has meanwhile received this preparation, branch from `main` instead. If your session requires another branch name, create that branch from the same commit.

Before editing:
- Verify that `git log --oneline 73efae9..HEAD` lists only the D-066 (and, once recorded, D-067) preparation commits and any later owner commits.
- Verify that the working tree is clean, and preserve every owner change.

Read:
- `AGENTS.md` and `README.md`;
- D-051, D-063 to D-067 in `docs/planning/decisions.md`;
- every file in `specs/015-business-integrations/`, in particular the [entry review](entry-review.md) sections 2 to 8;
- the [007 entry review](../007-revenue-ledger/entry-review.md) (A1 to A3) and `backend/app/ledger/`, whose `Evidence` contract and `calculate()` this round persists and reads;
- the 004 webhook intake in `backend/app/services/collection.py` (sources, sealed secrets, the 24-hour rotation overlap, rates);
- `backend/app/api/middleware.py` (`RequestBoundary`), `backend/app/privacy/providers.py`, `backend/app/data_policy.py` and `backend/app/services/access.py`;
- the Spec 014 work as the latest pattern: `specs/014-ad-spend-capi/` (design note, evidence, review corrections), `backend/app/services/delivery.py` (which consumes a `LedgerCalculation`) and the migrations `0017` to `0019`.

Communicate with the owner in Arabic, and write project files, code comments and commit messages in formal English.

## Authority

- **D-066 (owner, 2026-11-21).** Spec 014 is merged. This first round of Spec 015 covers payments with Paymob and the CSV and manual fallback, against a synthetic Paymob-shaped sender and fixture tests only.
- **D-067.** The owner's approval of decisions D1-D15 of the entry review, including the pull request against `main` after successful verification without a further upload request. Phase 0 checks that it is recorded before any implementation. The merge remains the owner's decision.
- **Amendments.** Phase 0 reads the official pages behind V-1 to V-13.
  - A fact that changes a decision goes to the owner first, as D-054 did, and the work that depends on it waits.
  - A fact that changes only a parameter (a field name, a bound, a code) is applied and recorded.
  - A later change to D1-D15 also goes to the owner first.

## Hard limits

- No call to Paymob of any kind and no real payment. Do not create or change a Paymob account, integration or secret, and do not ask for Paymob credentials. The Paymob source type stays off by default.
- Never store card data: no PAN or masked PAN, card brand, token, CVC or expiry. Never store billing or shipping data, customer names, emails or phones, order items or raw payloads (D6).
- Test migrations on the disposable PostgreSQL 18 service of `backend/tests/README.md` only, never on the owner's native `tracking_sys`.
- No new dependency. CSV parsing and HMAC come from the standard library.
- No frontend change. Import and source screens wait for the owner's brief, design and brand identity (D-039).
- Do not touch Specs 012 and 013, the YouTube test account or `local-data\youtube-feasibility`. Spec 011 Phase 4 follows its own branch (D-062).
- Never commit a secret, real customer data or an identifier from a live account. Tests use synthetic values only.
- Do not merge, do not enable auto-merge and do not deploy.

## Phase 0: decisions, sources and branch

1. **Branch.** Set up the branch as described above.
2. **D-067 gate.** Look for D-067 in `docs/planning/decisions.md`.
   - If it is recorded, apply it as written.
   - If it is not recorded, present D1-D15 to the owner in Arabic: a short table with the decision, the recommendation and the alternative. Ask whether to approve every recommendation or change some.
   - Record the answer as D-067 in the decision register and as one line in `AGENTS.md`, in the style of the earlier entries, and update section 9 of the entry review.
   - Do not start Phase 1 before D-067 is recorded.
3. **Source verification.** Read the official pages behind V-1 to V-13 of the entry review section 2.3: the Paymob developer documentation (callbacks and HMAC, transactions, refunds, voids and captures, the Intention API, regions), Paymob's terms, and the PCI SSC pages behind S-89.
   - **Record.** Fill section 2.4 with one row per page: the URL, the date read and any last-updated date. For each V row, state whether it was confirmed, corrected or not read.
   - **Apply.** Apply parameter-level corrections in the design note (Phase 1). Present any decision-level change to the owner before the work that depends on it.
   - **Unreadable pages.** If a page cannot be read, say so in section 2.4 and keep the assumption marked as unverified. The rules of Phase 3 then stay stale and the Paymob source type stays unusable. That is acceptable for this round.
4. **Commit and push** (D-051).

## Phase 1: design note

Write `specs/015-business-integrations/design-015a.md`, then continue; it is not a stopping point. It covers:
- the tables, columns, constraints and indexes of D2, D3, D8 and D14, with the column-limited privileges of `tracking_app` and `tracking_lifecycle`;
- the `app.data_policy` entries for every new table;
- the upgrade and downgrade of `0020` to `0022`;
- the per-route body bounds of D13 and how `RequestBoundary` applies them;
- the exact HMAC computation and the mapping table of D5, with each source row from Phase 0;
- the delivery ID of D7;
- the CSV columns, limits and closed row error codes of D8;
- the routes with their permissions and answer shapes;
- the mapping of each case T-01 to T-36 (entry review section 7) to its test.

## Phase 2: 015-A, evidence store and ledger read

1. **Store (D2).** An append-only `revenue_evidence` table per agency and client. It holds:
   - the 007-A `Evidence` fields;
   - the intake provenance (Paymob source, CSV import or manual entry);
   - a content digest for the exact-redelivery rule.

   `tracking_app` may insert and read only.
2. **Service.**
   - Load a client's evidence in receipt order and return the 007-A `LedgerCalculation` and the `ledger_feed` journal.
   - 008-A and 014-B (`candidates_from_ledger`) must accept them unchanged; their journeys stay synthetic.
3. **Route (D11).** `GET /agencies/{agency_id}/clients/{client_id}/revenue` needs `finance:read`. It returns:
   - transactions and per-currency totals, with verified and declared amounts apart;
   - pending adjustments and reconciliation items.

   Currencies are never summed, and no answer carries another client's data.
4. **Migration.** `0020`, with the data-policy entries and privileges, tested on the disposable service.
5. **Tests.** T-01 to T-05, with the mutation checks marked (M).
6. **Verify, record and push.** Verify (Phase 5, step 1, for the affected suites), record the commands and counts in `specs/015-business-integrations/evidence.md`, then commit and push.

## Phase 3: 015-B, Paymob payments

1. **Sources (D3).** Owner and Admin routes to create, list, replace the secret of, and disable a Paymob payment source, each with an audit event.
   - The merchant's HMAC secret is entered once, sealed under the D-025 keyring, and never returned or logged.
   - A replaced secret stays accepted for 24 hours.
   - Each source has a callback URL with an unguessable public key.
2. **Callback (D4, D5, D7).** `POST /payments/paymob/callback/{public_key}`:
   - verifies the documented HMAC against the current and previous secret in constant time;
   - refuses invalid or unknown sources with the same 401 answer and stores nothing;
   - maps the transaction to 007-A evidence by the D5 table, and posts nothing for authorizations, failures, pending, declined or unmapped states;
   - derives the D7 delivery ID, stores the evidence, and keeps a diagnostic row (source, digest, receipt time, closed outcome);
   - answers 200 for every verified callback.

   The browser response redirect is never evidence.
3. **Minimization (D6).** Reduce the payload to the allowed fields before anything is stored or logged. Test that no forbidden field survives in the database, the logs or an answer.
4. **Bounds (D13).** 64 KiB for the callback route, or the documented size from V-6, and 2 MiB for the CSV routes of Phase 4. Every other route keeps 16 KiB. Bounds are checked while streaming.
5. **Rates.** Per source and per peer, at the 004 trusted intake rate.
6. **Gate and rules (D12).**
   - The setting `TRACKING_PAYMENTS_PAYMOB_ENABLED` defaults to false and is listed blank in `.env.example`.
   - Re-read the pages behind the `payments.processor_records` rule and re-verify it. Add `paymob.accept`, with its data class registered in `app.data_policy`.
   - Mark a rule current only when its pages were read, with the verification date and a review date one year later.
   - While the setting is off, or a rule is stale or past its review date, sources cannot be created and callbacks are refused.
7. **Synthetic sender.** A test helper that builds Paymob-shaped processed callbacks from the documented fields and signs them with a test secret. It covers sales, captures, partial and full refunds, voids, authorizations, failures, pending and unmapped states, and oversized bodies.
8. **Migration.** `0021`: sources, sealed secrets and callback diagnostics, with a 30-day lifecycle deletion of diagnostics by `tracking_lifecycle`. Test it on the disposable service.
9. **Tests.** T-10 to T-21 with the mutation checks.
10. **Verify, record and push.** Verify, record in `evidence.md`, then commit and push.

## Phase 4: 015-C, CSV import and manual declarations

1. **Preview (D8).** An Owner or Admin uploads a transaction CSV (fixed columns, at most 2 MiB and 10,000 rows). Every row is validated with closed error codes. The refusals:
   - formula-injection cells (beginning with `=`, `+`, `-` or `@`);
   - personal-data headers (name, email, phone, address);
   - any column outside the fixed set.

   The preview stores nothing and returns the row results.
2. **Commit (D8).** The same file, with an import ID, stores the valid rows once as unverified `manual_declaration` evidence. A repeated commit is a no-op, and the commit has an audit event. The file is not kept; an import record keeps the counts and the file digest, and is deleted after 13 months by `tracking_lifecycle`.
3. **Manual declaration (D9).** An Owner or Admin route declares one transaction with a reason. It has the same validation and classification and an audit event. Audited corrections stay in 007-B.
4. **Exclusions.** Declared rows never enter verified totals (007-A A1) and are never enqueued by 014-B.
5. **Migration.** `0022` (import records), tested on the disposable service.
6. **Tests.** T-30 to T-36 with the mutation checks.
7. **Verify, record and push.** Verify, record, then commit and push.

## Phase 5: verification, records and the pull request

1. **Verification.** From `backend/` with the project `.venv`:
   - `python -m ruff check .` and `python -m ruff format --check .`;
   - the full unit suite;
   - the full integration suite on the disposable service, following `backend/tests/README.md`;
   - the OpenAPI snapshot updated in `contracts/openapi.json`, with its test passing;
   - every new regression;
   - every mutation check, with its result.

   Report skipped tests as skipped, never as passed. If a check cannot run in your environment, tell the owner in Arabic and wait for instructions instead of opening the pull request. If the documented database port is unavailable, as on 2026-11-21 with Spec 014, follow the D-065 record: the same disposable service on another port, the guard changed only during the runs and restored byte for byte, all recorded.
2. **Records.**
   - `specs/015-business-integrations/evidence.md`: the scope and decisions applied, the source verification summary, the commands with their counts, the mutation checks, the limitations and the follow-ups.
   - `spec.md`: the status line, AC1 and AC5 each mapped to its evidence, and AC2 to AC4 marked open for later rounds.
   - `plan.md` and `tasks.md`: completed items closed, later rounds and separately gated items listed as follow-ups.
   - An operator guide `docs/engineering/payments.md`: Paymob sources, the callback URL, secret replacement, states and mapping, diagnostics, the CSV format and error codes, manual declarations, settings and lifecycle.
   - The status lines of `README.md`, `specs/README.md`, `docs/planning/roadmap.md` and `docs/planning/review-next.md`.
3. **Pull request.** Push, then open a pull request from your branch against `main`. If `.github/pull_request_template.md` exists, follow it. Suggested title: "Spec 015 (first round): Paymob payments, CSV import and manual declarations (synthetic and fixtures)". The description covers:
   - the problem and the resulting behavior per slice;
   - D-066, D-067 and any amendment;
   - the source verification summary;
   - the commands and counts;
   - migrations `0020` to `0022` with their downgrade behavior;
   - the limitations and follow-ups;
   - a plain statement that no call was made to Paymob, no real payment was involved, no card data is stored, and no native migration was run.

   Do not merge.
4. **Report.** Tell the owner in Arabic that the pull request is ready for Claude's review: the head commit, the link, the counts, any amendment, and the open follow-ups.

## Follow-ups that stay open after this round

- Later rounds of Spec 015: bookings (AC2), CRM (AC3), WhatsApp and ManyChat (AC4), automation webhooks, third-party form tools, Paymob transaction reads and backfill, and Stripe, each with its own provider decision.
- A live Paymob check with an owner sandbox account and an HTTPS-hosted API (020), separately approved.
- 007-B: persisted postings and movements, finance write permissions, audited corrections, reconciliation workflows and the approval of declarations.
- 006: linking payments to people and journeys.
- Native `tracking_sys` migration and deployment, which remain separate owner decisions.
