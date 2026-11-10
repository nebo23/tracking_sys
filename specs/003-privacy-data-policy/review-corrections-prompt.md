# Specification 003: scoped review corrections and GitHub handoff

Prepared: 2026-11-08. Authority: D-026. Working directory: `C:\Code\Tracking-system`.
Repository: `https://github.com/nebo23/tracking_sys`.
Branch: `codex/spec-003-privacy-data-policy`. Pull request: [PR 2](https://github.com/nebo23/tracking_sys/pull/2), open and unmerged when checked on 2026-11-08.
Reviewed application revision: `07963515f0145339a10cbd37149272476b821a99`; base: `98747a296dd570c5f40f76c68796d3e53edb9cc4`.

## Task and authority

Implement only R003-01, R003-02, and R003-03 below, their regression tests, and the explicitly listed documentation follow-ups. The owner requested this correction handoff and authorized pushing the completed, verified corrections and creating or updating their GitHub pull request. D-026 is a scoped exception to the earlier requirement to request upload approval again after implementation. Finish the work, inspect the final diff, record real validation results, and then push/update the PR without asking for the same authorization again. Merge and deployment remain owner decisions.

This document supersedes the historical `implementation-prompt.md` for this correction task. Do not restart specification 003 or implement its deferred consumers. Communicate with the owner in Arabic; keep repository content, comments, commit messages, and PR text in formal English. Work without additional agents.

## Read and establish the baseline

Read `AGENTS.md`, `README.md`, `docs/planning/decisions.md`, this specification's `spec.md`, `tasks.md`, `design.md`, `evidence.md`, and `pull-request-review-2026-11-04.md`. Read `docs/engineering/data-lifecycle.md`, the affected implementation and tests, and specification 002's `auth-corrections-2026-11-04.md` before changing shared authentication behavior. The original review report is a local source document and may still be untracked; preserve its historical results.

Inspect the current branch, working tree, index, recent commits, remote branch, and current PR metadata. Line numbers below identify the reviewed revision and may shift. Do not assume the remote still has the recorded head. Compare any later changes before editing and do not overwrite another contributor's work.

Keep amendments on the existing specification branch while PR 2 remains open. Do not commit to `main`, reuse `claude/development`, force-push, or create a duplicate PR. If the PR has already merged by execution time, start only the outstanding corrections on a fresh `codex/spec-003-review-corrections` branch from updated merged `main`, preserving local work, and create a correction PR. If it is closed without merging, report the state and do not silently reopen it or bypass that closure with another PR.

Pre-existing unrelated work observed during handoff preparation includes changes in `backend/app/api/schemas.py`, `backend/app/models/tenancy.py`, the 001/002 task files, older untracked 001/002 review documents, and D-021/Q-008 hunks in shared authority files. This list is not exhaustive: inspect actual diffs. Preserve all such work, exclude it from the correction commits, and never use `git add .`, reset, stash, clean, or broad formatting to obtain a clean tree. Shared-file staging must select only this task's hunks. Where unrelated edits affect validation, verify an isolated candidate tree containing only the intended correction changes and report the exact tested content.

## R003-01: remove the account-closure / Google-link lock cycle

Priority: P1. Reviewed locations: `backend/app/services/auth.py:605-608` and `backend/app/services/google.py:322-351`.

Closure holds the user/session locks and then updates that user's open `OAuthTransaction` rows. The Google callback locks and consumes its OAuth row before authenticating the initiating user/session. Running both concurrently can create a user/session -> OAuth versus OAuth -> user/session cycle. The original diagnostic observed SQLSTATE `40P01` and callback HTTP `503`.

Choose the smallest correct change after examining all affected lock paths. One candidate is to stop synchronously mutating OAuth rows during account closure, relying on immediate account disabling/session revocation to reject the pending link and the existing lifecycle runner to remove closed-account OAuth state. A consistently ordered locking strategy is also acceptable if it preserves all guarantees. Explain the chosen strategy in the correction evidence. Do not mask the defect with retries or exception handling alone.

Preserve originating-session binding, revocation/reset checks, expiry validation after lock waits, browser/state/nonce validation, last-active-Owner protection, and the prohibition on attaching an identity to a closed account. Pending OAuth state must not permit login, linking, or account reactivation after closure.

Add a deterministic PostgreSQL regression using real services and the HTTP callback with controlled Google fixtures: start a link for a synthetic password user; hold closure's user/session locks; start the callback and synchronize on its relevant database wait; then perform closure and finish both transactions. Use bounded synchronization, not sleeps as the sole race trigger. Assert closure succeeds, the pending callback is rejected through the normal authentication outcome, there is no deadlock/database-error response, and no external identity is attached. Verify subsequent lifecycle cleanup. Preserve and run the existing Google, authentication-review, closure, and last-Owner regressions.

## R003-02: reject card numbers separated by common whitespace

Priority: P2. Reviewed location: `backend/app/privacy/collection.py:59-60,115-125`.

`_DIGIT_RUN` and the split expression currently recognize only a single ASCII space or hyphen between digit groups. In an ordinary mapped free-text field, joining the synthetic card groups `4111`, `1111`, `1111`, `1111` with two spaces, a tab, or a non-breaking space bypasses detection.

Normalize or parse the supported separators consistently. Keep detection bounded to 13-19 digits passing Luhn, preserve adjacent CVV/expiry handling, and avoid introducing unbounded or pathological matching. Do not rewrite otherwise allowed submitted text merely to perform detection; retain the established behavior of dropping the unsafe field.

Add parameterized regressions through `sanitize_submission` using `FormField("message")` and mapping `{"message": "lead.contact"}`. Cover double spaces, tabs, non-breaking spaces, and existing ordinary-space/hyphen/contiguous formats. Retain the previous adjacent-digit regressions. Include negative cases such as non-Luhn digit sequences and ordinary short numbers/text that remain allowed. Use synthetic values only. This change corrects the library contract; tracker/ingestion enforcement stays in the consuming specifications under D-025.

## R003-03: require a complete restore journal

Priority: P2. Reviewed location: `backend/app/privacy/restore.py:66-71`.

The current HMAC verification authenticates supplied entries, but a valid prefix still passes. With four valid entries available at the source, passing only entries 1 and 2 to `to_reapply(..., restored_max_seq=3)` incorrectly returns an empty plan. Even a prefix reaching the restored sequence cannot prove that later deletion/withdrawal entries are present.

Correct the contract without introducing a database table, persistence service, provider, or dependency:

- Validate the restored watermark and reject invalid values and journals shorter than that known watermark.
- Define and require a trusted expected journal head/checkpoint that binds the expected final sequence and chain value. Document its trust boundary and how a future caller establishes that it is the authoritative head for this recovery. Do not derive proof of completeness from the same potentially truncated input, and do not allow an optional argument to silently retain the unsafe behavior.
- Detect a missing suffix even when the supplied entries reach or exceed the restored watermark; a valid but stale prefix is insufficient evidence of completeness. Validate the full chain and the expected head before returning a recovery plan.
- Preserve idempotent reapplication and the distinction between no restore having occurred and an incomplete restore. Keep the contract's readiness result blocked when completeness is unknown, verification fails, or reconciliation has not completed. Update existing library callers/tests and the documented consumer obligations as necessary, without building production readiness or storage integration.
- Test a journal shorter than the restored watermark, a missing tail after the restore point, an empty journal with a nonzero watermark, invalid watermark/checkpoint inputs, head/chain mismatches, missing completeness evidence, legitimate empty recovery with a trusted empty head, and normal repeated idempotent recovery. Preserve tampering/gap/reordering/wrong-key tests and verify that failure cannot be treated as completed reconciliation.

The independent journal store, durable checkpoint custody/freshness, restore epochs, and operational restore drill remain specifications 019/020 obligations. Make these limits explicit; do not claim an end-to-end restore guarantee from library tests.

## Required documentation follow-ups

1. **Legacy queued mail:** clarify in `docs/engineering/data-lifecycle.md` that undelivered pre-D-024 rows with both `delivered_at` and `expires_at` null are outside time-based outbox cleanup, and can retain encrypted payloads indefinitely. Document a concrete proposed transition, with options for deriving expiry only from reliably linked source tokens or explicitly retiring affected pending messages. Mark the policy and rollout as awaiting owner approval; do not guess historical expiry values, introduce new retention periods, add a backfill migration, or mutate native rows. This unresolved policy does not block the three independent corrections or their authorized PR update. Do not claim legacy mail has been fixed.
2. **Native/Docker rollout wording:** correct the PR statement that existing Docker volumes must be recreated. Adding the lifecycle role in place before reviewed migrations preserves the volume. Native `tracking_sys` rollout remains separate; no native connection, role creation, migration, lifecycle deletion, or real provider use is authorized by this task. State native status as last verified information unless separately checked with authorization.
3. **Current status and evidence:** update relevant opening status text in `spec.md`, `tasks.md`, `evidence.md`, `README.md`, and other directly affected specification documents so it matches the actual PR and correction state. Label historical A1/A2 evidence clearly instead of presenting its exclusions as the final scope. Preserve earlier results and approved D-025 contract-level completion/deferred acceptance. Do not mark owner acceptance, merge, production readiness, or downstream enforcement complete.
4. Add `specs/003-privacy-data-policy/review-corrections-evidence.md` after implementation, mapping each finding to the change, regression, actual result, and remaining limits. Include the checkpoint contract/trust assumptions, the chosen locking strategy, unchanged schema/dependencies if verified, and the legacy-mail policy still awaiting approval. Link it from the relevant specification evidence/tasks. Do not rewrite the original review as if its historical failures never occurred.

## Scope exclusions

No new product features, downstream specifications, schema/migrations, database roles or grants, major dependencies, retention/account policies, frontend, hosting, scheduler, CI platform, provider setup, or production integration. Preserve tenancy/client authorization and existing Google/Gmail/OTP behavior outside the identified correction. No live Google/Gmail calls, external email, native data changes, secret output, or production/customer fixtures. If a correction unexpectedly requires a material decision outside this scope, complete the independent authorized work and present that concrete dependency instead of silently broadening the task.

## Verification and evidence

Use the existing project `.venv` or existing containers and locked requirements. Inspect installed tooling first; do not install project packages globally. Keep all PostgreSQL integration checks on an explicitly verified disposable `tracking_foundation_test` database at `127.0.0.1:55433` with isolated Compose storage and synthetic credentials. Inspect and honor `backend/tests/integration/conftest.py` guards; never weaken them. Do not reuse an unknown/prepopulated database or remove another task's volumes.

Remove inherited application configuration from the test process and explicitly configure the disposable runtime/migrator/lifecycle connections, valid synthetic hexadecimal secrets, local mail, temporary mail storage, and disabled live Google/Gmail settings. Ensure defaults cannot fall through to the owner's ignored `.env` or native port 5432. Controlled provider fixtures may enable only their mocked path. Do not print private configuration.

Demonstrate the targeted regressions against the uncorrected reviewed code where practical, then run them against the candidate correction. Run the full backend suite with integration tests genuinely enabled, plus Ruff lint/format and dependency consistency checks on the intended committed tree. Typical checks, from `backend` using the project's virtual-environment Python, are:

```text
python -m pytest -q
python -m ruff check app migrations tests
python -m ruff format --check app migrations tests
python -m pip check
```

The preceding test-environment isolation is mandatory; these command examples are not authorization to run against ambient native configuration. The previous result of 327 passing tests is historical, not evidence for the new revision. Record the tested revision/content, commands, target, actual pass/fail/skip counts, and remaining untested behavior. Missing integration prerequisites or skipped critical regressions do not satisfy completion; report the blocker instead of asserting success. Clean up only this task's disposable resources and one-time scripts after verification, leaving reusable regression tests in the repository.

## Commit, publish, and report

After the corrections and required checks pass:

1. Review the complete candidate diff for scope, accidental secrets, unrelated owner hunks, test coverage, and accurate status/limitations. Stage explicit paths/hunks and commit the corrections locally on the verified specification branch. Recheck that the committed code matches what was tested.
2. Re-read remote/PR state before publication. Push normally, without rewriting shared history. For the existing open PR 2, update that PR rather than creating another one. If a later merged state required a fresh correction branch as described above, create its PR against `main`. The owner's D-026 approval covers this publication step; do not stop to request it again.
3. Update the PR title/body to describe the final specification and corrections. Preserve the existing specification summary while adding the resolved R003 findings, actual verification, native rollout constraints, deferred D-025 enforcement, and unresolved legacy-mail policy. Remove the incorrect Docker-volume claim. Use structured tool arguments or an exact temporary `--body-file` for multiline text. Do not claim GitHub CI passed based on local checks; inspect available checks and distinguish absent, pending, failing, and passing results.
4. Verify the remote branch head and PR head match the intended commit and return the clickable PR URL with an Arabic summary of changes, checks, commits, and remaining limitations. Do not merge, enable auto-merge, deploy, or request reviewers without authorization.

If publication is blocked by missing authentication, permissions, or a genuine remote conflict, retain the verified local commits and report the exact blocker. Never claim a PR was created or updated without confirmation.
