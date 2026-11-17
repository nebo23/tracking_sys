# Independent implementation review — 2026-11-04

## Decision

**The implementation is not ready to approve as fully working.** The existing test suite passes, and the three original review findings have fixes and regression coverage. However, three additional behavioral defects were independently reproduced. The owner's running development environment also lacks the new database revision and complete provider configuration.

This was a review, not an implementation pass. No application source, existing tests, private configuration, or native application data was changed. No external email was sent, Google authorization performed, or repository upload initiated. This report is the retained review deliverable.

## Reviewed version and method

- Implementation commit: `c0d867c` — Implement numeric verification, Google sign-in, and Gmail delivery.
- Final observed HEAD: `8f69a94` — Correct README status for the D-022 additions. Only README changed between these commits; the tested application code is unchanged.
- Branch: `claude/development`. Existing uncommitted owner/documentation changes were preserved, including the formatting edit in `backend/app/models/tenancy.py`.
- Basis: the working agreement, recorded decisions D-020 to D-022, the authentication design, the foundation/tenancy/privacy review amendments, current routes/services/models/migrations, and repository tests.
- Integration checks used a newly created, isolated PostgreSQL database named `tracking_foundation_test` on port `55433`. The native `tracking_sys` database received only a read-only schema inspection.
- Provider tests used controlled Google/Gmail substitutes. They establish application behavior under those responses, not successful live provider configuration or inbox receipt.

## Confirmed findings

### R-01 — P1: A pending Google link remains usable after all sessions are revoked

Location: [Google account policy](../../backend/app/services/google.py), lines 227–244. Related locations: authorization transaction creation at lines 123–138; callback completion at lines 297–337; `OAuthTransaction` in `backend/app/models/auth.py`.

The link transaction retains the user ID and a browser-binding digest, but not the initiating application session. The callback checks that the user is active and email-verified, then attaches the Google identity without checking that the session which authorized linking remains valid. This contradicts account-policy item 5 in the approved authentication design: linking requires the authenticated session that started it.

**Observed reproduction:** using synthetic accounts and the repository's RSA-signing provider substitute, start linking from a valid password session, call logout-all successfully, confirm `/auth/me` rejects the browser, then finish the pending callback. The callback still reports `linked`. A fresh Google login with that identity successfully opens the original local account.

**Impact:** session revocation does not terminate an already started credential-linking operation. Someone holding a session before it is revoked can finish adding another login method during the remaining OAuth transaction lifetime.

**Required correction:** bind linking to the initiating session and validate that exact session at completion, including revocation, absolute/idle expiry, user identity, and browser context. Make the final check and attachment safe against concurrent logout/reset. Add regressions for logout, logout-all, password reset/change, expiry, and switching accounts between initiation and completion. Any storage change should follow the reviewed additive migration process.

### R-02 — P2: Concurrent OTP checks exceed the challenge and daily attempt limits

Location: [OTP verification](../../backend/app/services/auth.py), lines 288–330; supporting functions `check_rate_limit` and `record_verification_failure` in the same file.

Both the daily failure budget and challenge budget are checked before comparing the code, without reserving an attempt or serializing checks for that account. Failed attempts are committed separately only after the comparison. Multiple requests can therefore observe the same remaining allowance and each evaluate a different code.

**Observed reproduction:** with the approved defaults of five failures per challenge and ten per email per day, seed the counters at four and nine. Synchronize three requests immediately before verifier computation. All three evaluate their codes and return the ordinary invalid-code result; the persisted counters become seven and twelve. The concurrency barrier controls scheduling only; it does not replace the comparison or database updates.

**Impact:** the configured budgets are not strict limits under concurrent traffic. Persisting failures correctly across rollback does not by itself enforce an atomic limit. The peer/IP throttle is a separate control and does not repair the account-level race.

**Required correction:** serialize or atomically reserve account/challenge attempt capacity before evaluation, while preserving failure persistence and avoiding a new cross-transaction lock cycle. Cover simultaneous wrong codes, a correct code competing with the final allowed failure, resend races, and multiple workers.

### R-03 — P2: An OTP can be accepted after expiring while it waits for a user lock

Location: [OTP verification](../../backend/app/services/auth.py), lines 303–308 and 332–345.

The expiry cutoff is evaluated when `open_challenge` is first constructed. That same SQL expression and bound timestamp are reused after waiting for the user-row lock. The final query therefore checks expiry against the earlier time, not the time at consumption.

**Observed reproduction:** give a synthetic challenge a short remaining lifetime, hold its user-row lock in another transaction, and submit the correct code while it is still valid. Release the lock after expiry. Verification succeeds, the account becomes verified, and the recorded `consumed_at` is later than `expires_at`.

**Impact:** the validity boundary can be exceeded during lock contention. The reproduction waited within the application's configured lock timeout.

**Required correction:** re-evaluate expiry using the current clock after the required locks are acquired, immediately before consumption. Add a deterministic regression that makes the challenge expire while the verifier is waiting.

## Original review requests

| Request | Review outcome | Evidence |
| --- | --- | --- |
| F-01: Docker origins with a non-default API port | Fixed in the reviewed code | Compose rendering for port `18007` produced matching API origins and Google callback. The allowed/foreign-origin integration test passed. |
| T-01: invitation/inviter lock cycle | Fixed in the reviewed code | User locks now use `FOR NO KEY UPDATE`; the deterministic invitation concurrency regression and same-user serialization test passed. |
| T-02: invitation acceptance throttling | Fixed in the reviewed code | Peer and authenticated-user limits are present; rollback persistence and no-side-effects regressions passed. |
| Database/configuration explanations | Present | Purpose comments cover Base, engine creation, revision/readiness helpers, configuration imports/validators/properties, and settings classes. |
| Security and authentication service explanations | Present | The inspected definitions, including private helpers and constructors, have nearby comments or docstrings. |
| API file/class/function explanations | Present | Checked authentication, Google, dependencies, middleware, schemas, and tenancy modules. |
| Model reference SQL | Present and syntactically verified | All 34 commented SELECT queries passed PostgreSQL `EXPLAIN` against the disposable migrated schema: tenancy 12, auth 14, access 8. The shared Entity mixin correctly has no table query. |

These conclusions concern the requested fixes and covered cases. They are not a guarantee that every possible concurrency schedule or API input is correct.

## Verification results

| Check | Independently observed result |
| --- | --- |
| Unit/contract subset | 45 passed, 135 deselected. This subset is included in the full suite below. |
| Complete repository suite | **180 passed in 101.38 seconds**: 45 unit/contract and 135 PostgreSQL cases. |
| Additional behavioral reproductions | **All three defects reproduced.** The diagnostic assertions intentionally assert the observed defective behavior, so their passing result is evidence of the defects, not a clean bill of health. |
| OTP race with exact approved defaults | Confirmed separately: challenge count 4 → 7 and daily count 9 → 12 with three concurrent comparisons. |
| Dependency consistency | `pip check` reported no broken requirements. |
| Ruff lint | One E501 at `backend/app/models/tenancy.py:33`, from the pre-existing owner edit. |
| Ruff format check | One file would be reformatted; 49 were already formatted. No formatting change was made. |
| SQL reference examples | 34 queries planned successfully with `EXPLAIN`; no native/customer rows were queried. |
| Current development API | Liveness returned 200; readiness returned **503**. OpenAPI returned 200 and included the Google and numeric-verification routes. |

The complete suite emitted one `UnsupportedFieldAttributeWarning` concerning `X-CSRF-Token` during the concurrent invitation test. The test assertions passed. The temporary diagnostic harness emitted pytest import/marker warnings; those do not establish product failures.

Relevant existing regression groups include `test_lock_order.py`, `test_invitation_throttle.py`, `test_origin_config.py`, `test_verification_code.py`, `test_google.py`, and `test_gmail.py`, together with the existing authentication, migration, access-control, and tenant-isolation tests.

The full suite was run with the repository virtual environment, explicit disposable-database settings, synthetic application secrets, local mail mode, and external Google sign-in disabled except where controlled substitutes were installed by tests. No live Google or Gmail requests were made.

## Current local setup: separate blockers

These are observed configuration/rollout facts, not additional coding defects:

1. **Native schema is still `0003_auth`; code expects `0004_identity`.** The three new identity/challenge tables are absent. This matches the observed readiness failure. Applying the reviewed additive migration to the native database remains a separate rollout step; this review did not apply it.
2. **Google sign-in is disabled** in current settings. Having a client ID/secret alone does not activate it. Route presence in OpenAPI is not proof that the enabled flow works.
3. **Mail mode is `local`.** Current processing is local capture, not Gmail delivery.
4. **Gmail sender address and refresh token are missing.** The configured sender client ID currently equals the sign-in client ID. The approved design and validator require a separate sender client and owner authorization for the send-only scope.
5. **A real browser Google round trip and real Gmail delivery/receipt remain unverified.** No conclusion about the Console redirect, consent/test users, token validity, or inbox receipt can be drawn from the substitute tests.
6. **Production is still deliberately rejected by configuration.** This development implementation is not evidence of production readiness or deployment approval. React authentication screens are a later specification.

No private credential values are included in this report.

## Completion criteria for the next review

1. Correct R-01, R-02, and R-03 and retain deterministic regression tests for them.
2. Rerun the relevant tests and the full suite; resolve the owner formatting edit when authorized.
3. Review and perform the native additive migration rollout through the project's normal process, then confirm readiness is healthy.
4. Complete separate sign-in and sender configuration locally. Obtain sender consent without placing secrets in tracked files or chat.
5. Perform an owner-operated live Google login/link/logout check and one designated-recipient Gmail verification-code delivery/verification check. Record provider acceptance and inbox receipt as separate observations.
6. Present the completed result for owner review before upload, PR, or merge.

Temporary diagnostic code and the review-only Docker container, volume, and network were removed after verification. Existing Docker resources, native application data, and pre-existing workspace edits were preserved.
