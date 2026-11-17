# Specification 003: PR 2 review

Reviewed: 2026-11-04. PR: https://github.com/nebo23/tracking_sys/pull/2

Base: `98747a296dd570c5f40f76c68796d3e53edb9cc4` (`main`).
Head: `07963515f0145339a10cbd37149272476b821a99` (`codex/spec-003-privacy-data-policy`).
Scope: 11 commits, 77 changed files, 5,256 additions and 69 deletions.

## Recommendation

Request changes before merge. The published suite passes, but additional synthetic diagnostics reproduce three defects. This review does not change application code, publish a GitHub review/comment, push, merge, or authorize native rollout.

D-024 approves the current-data lifecycle and account-closure slices. D-025 explicitly approves contract-level completion for 003-B/C/D, with enforcement and end-to-end acceptance transferred to the named consuming specifications. This review respects that decision; the absence of downstream tracker, connector, or restore infrastructure is not itself a regression in this PR.

## Findings requiring correction

### R003-01 [P1]: Account closure introduces a lock cycle with an in-flight Google link

Location: `backend/app/services/auth.py:605-608`; interacting code: `backend/app/services/google.py:322-350`.

Closure authenticates and holds the user and browser-session locks, then updates that user's open OAuth transactions. The Google callback takes the opposite order: it locks and consumes the OAuth transaction before authenticating the initiating user/session. If closure has the user lock and the callback has the OAuth lock, each waits for the other. The callback's uncommitted consumed_at update does not prevent closure's UPDATE from waiting on that row.

Reproduction on the actual PR services and HTTP callback:

1. Sign in a synthetic password user and start a Google link using the controlled Google fixture.
2. Open the closure transaction and call `AuthService.authenticate` to hold its user/session locks.
3. Run the real callback concurrently; observe PostgreSQL reporting its user-lock wait.
4. Call `close_account` in the closure transaction.

Observed: PostgreSQL SQLSTATE **40P01**, and the callback returned **HTTP 503**. The diagnostic failed twice; the second run captured the exact SQLSTATE and HTTP response. Which transaction PostgreSQL aborts can vary, so closure can also be the victim.

Required correction: remove the user/session -> OAuth versus OAuth -> user/session cycle. Review a consistent locking strategy, or avoid synchronous OAuth-row mutation during closure while preserving fail-closed account/session validation and later lifecycle removal. Do not weaken the merged R-01 originating-session checks. Add a deterministic regression that holds the relevant locks and verifies closure succeeds while the pending link is rejected through the normal authentication outcome, without a database failure or identity attachment.

### R003-02 [P2]: Common whitespace bypasses free-text payment-card filtering

Location: `backend/app/privacy/collection.py:59-60,115-125`.

The digit-run expression and split logic accept only a single ASCII space or hyphen between groups. A synthetic Luhn-valid card number in an otherwise mapped free-text field is returned unchanged when groups are separated by two spaces, a tab, or a non-breaking space. Copy/paste and ordinary formatting can produce all three forms. Field-name/type checks do not protect a normal message field.

Reproduction: call `sanitize_submission` with `FormField("message")`, mapping `{"message": "lead.contact"}`, and the published synthetic card groups `4111`, `1111`, `1111`, `1111` joined separately by each of those separators. All three diagnostics expected the field to be dropped; all failed because the value was retained.

Required correction: normalize or parse the supported whitespace/separator forms consistently, retaining bounded 13-19 digit Luhn checks and the adjacent-CVV/expiry regression coverage. Add these three cases and appropriate negative cases. This is a defect in the shipped contract; runtime tracker/ingestion enforcement is still deferred under D-025.

### R003-03 [P2]: Restore planning silently accepts an incomplete journal

Location: `backend/app/privacy/restore.py:66-71`.

`verify` authenticates the entries supplied, but a valid prefix also passes. `to_reapply` does not check that the available journal reaches even the restored database's known maximum sequence. A journal containing only sequences 1 and 2 with `restored_max_seq=3` returns an empty plan instead of rejecting the inconsistent/incomplete source. Missing deletion or withdrawal entries can consequently be mistaken for a completed reconciliation by a future consumer.

Reproduction: create four valid HMAC-chained entries, supply only the first two, and call `to_reapply(key, entries[:2], restored_max_seq=3)`. The diagnostic expected `JournalTampered`; no exception was raised and the plan was empty.

Required correction: reject invalid watermarks and journals shorter than a known watermark. Define a trusted journal-head/checkpoint contract so a missing suffix after the restore point also cannot be accepted as a complete source; authentication of a prefix does not prove completeness. Keep readiness blocked when journal completeness cannot be established. Add missing-tail, empty-journal/nonzero-watermark, invalid-watermark, and normal idempotent-recovery cases. This changes the contract, not the separately deferred production journal store.

## Scope comparison

| Required area | Observed implementation and verification | Review result |
|---|---|---|
| Current schema data classification | Registry and metadata/migrated-schema checks, including identity tables and closure field | Existing checks pass |
| Application/library log protection | Allowlist formatter and real uvicorn process tests; previous authentication leak checks remain | Existing checks pass |
| Credential-state retention and restricted role | Migrations 0005/0006, dedicated role, boundary/batch/lock tests | Existing checks pass; legacy mail limitation below |
| Account closure, last Owner, session revocation, identity reuse | HTTP/service tests, concurrency cases, lifecycle deletion | Existing checks pass; R003-01 adds an uncovered concurrency case |
| Consent and collection contracts | J1 opt-in evaluation, collection minimization and provider consent signals | Contract tests pass; R003-02 remains |
| Deletion/tombstone contracts | State transitions, target outcomes, domain-separated keyed matching and admission checks | Existing contract tests pass; downstream enforcement remains transferred |
| Connector-secret encryption and provider policy | AES-GCM envelope/AAD isolation tests; connector rows explicitly stale/blocking | Existing contract tests pass; live connectors not claimed |
| Restore contract | HMAC chain, reapplication planning, reconciliation and readiness helpers | Existing tests pass; R003-03 remains |
| Original end-to-end acceptance | Consumer obligations recorded in 004/005/006/009-016/019/020 | Explicit D-025 deferral; not verified end to end in this review |

## Known limitations and documentation follow-up

1. **Legacy queued mail remains outside the new expiry behavior.** Reset/invitation messages queued before D-024 have nullable expires_at. An undelivered row with both delivered_at and expires_at NULL never matches the lifecycle outbox predicate. A synthetic 60-day-old reset row retained its encrypted payload after a run, confirming the limitation already disclosed in `docs/engineering/data-lifecycle.md`. Distinguish this from the three new findings above: document an explicit reviewed transition/backfill or retirement policy before claiming existing queued mail is covered. Do not silently delete native rows or guess historical expiry values.
2. **Native rollout is separate.** The PR reports native `tracking_sys` is still at 0004. This review did not inspect or modify native data. Applying the new application code there needs the reviewed role setup and migrations first. Correct the PR body's assertion that existing Docker volumes "must be recreated": the lifecycle guide already allows adding the role in place, preserving data. Recreating a volume is not required.
3. **Status wording is stale.** `spec.md`, `tasks.md`, and parts of `evidence.md` still say not uploaded/upload pending, while PR 2 exists. The evidence file also starts with the early A1/A2 exclusions before appending later implementation results. Update the opening status to identify the final reviewed revision and clearly label historical slice evidence.
4. **External/provider and operational claims remain limited.** No real Google/Gmail operation, production deployment, native migration, downstream event enforcement, or backup restore drill was performed in this review.

## Independent verification

The committed PR head was extracted with `git archive` into an isolated temporary directory, excluding the owner's uncommitted modifications. No runtime dependency was installed or changed. A separate Compose project, `tracking-pr2-review`, used synthetic credentials and only `tracking_foundation_test` at `127.0.0.1:55433`; inherited application environment variables were removed and mail was forced local with Google sign-in disabled except controlled fixture overrides.

| Check | Result |
|---|---|
| Full existing suite at the exact PR head | **327 passed in 102.81 seconds**: 142 unit/contract and 185 PostgreSQL; no failures or skips reported |
| Ruff check on committed app/migrations/tests | Passed |
| Ruff format check | Passed; 72 files already formatted |
| pip check | No broken requirements |
| Additional diagnostics | 5 failing cases across R003-01/02/03, plus 1 failing expectation confirming the documented legacy-mail limitation |
| Precise concurrency confirmation | SQLSTATE 40P01; callback HTTP 503 |
| GitHub status/workflow tools for reviewed head | No status entries or PR-triggered workflow runs returned; local results are not a claim of green GitHub CI |

The first integration invocation was a review-harness setup failure: its synthetic application secrets were not hexadecimal. Correcting only that harness setting produced the full passing result above. It was not a PR application failure. Unit tests already passed in that initial invocation.

Diagnostic tests were temporary review probes, not edits to the published application or test suite. Their reproduction procedures are preserved above. The disposable database and temporary archive/runner are removed after verification. Existing owner edits remain unstaged and untouched. This report is local and uncommitted.
