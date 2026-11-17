# Pull request 1: independent comparison and readiness review

Reviewed: 2026-11-04. Recommendation: **request changes; do not approve merge yet**.

The three original findings F-01, T-01, and T-02 are fixed in the reviewed branch. The three later findings R-01, R-02, and R-03 remain unfixed and were reproduced again against the exact committed application code. The repository's 180 tests pass, but they do not cover these failing security and concurrency scenarios. Native configuration has progressed since the earlier review: schema revision, readiness, and provider settings now pass local checks.

This document is a local review deliverable. It does not change application behavior, approve a schema change, establish live provider delivery, or authorize publication or merge.

## Reviewed versions and scope

| Reference | Value and purpose |
| --- | --- |
| Pull request | [PR 1](https://github.com/nebo23/tracking_sys/pull/1), open, not merged, targeting `main` |
| Base | `3a3bba13d60a8c325dcf55b2f4970c0849d51e96` |
| Reviewed head | `8099755cb1c8d3a9f58782375858272c55e8f813` on `claude/development`; GitHub and local HEAD agree |
| Complete change | 11 commits, 139 changed files, 17,706 additions, 264 deletions |
| Earlier implementation | `c408e4b`, before the documentation, original fixes, and D-022 continuation |
| Original fixes | `60dd174`: F-01, T-01, and T-02 |
| D-022 implementation | `c0d867c`: numeric verification, Google sign-in/linking, Gmail delivery, and migration 0004 |
| Earlier independent review | [review-report-2026-11-04.md](review-report-2026-11-04.md), application at `c0d867c`, final HEAD `8f69a94` |

Compared the complete PR change inventory with `main`, inspected the implementation and security-sensitive paths, compared the original correction commit with its predecessor, and compared the current branch with the earlier independent review. The three commits after `8f69a94` change environment examples and rollout/documentation records only. `app/services/auth.py`, `app/services/google.py`, and `app/api/google.py` are byte-for-byte unchanged since `c0d867c`.

Tests used an archive of the committed HEAD, isolated from existing owner edits. The temporary diagnostic tests were added only to that archive after the unchanged repository suite completed. No application file or existing test in the working tree was edited.

## Blocking findings

### R-01 — P1: Google linking survives invalidation of the initiating session

Location: [services/google.py, lines 227-244](https://github.com/nebo23/tracking_sys/blob/8099755cb1c8d3a9f58782375858272c55e8f813/backend/app/services/google.py#L227-L244). Related code: `begin_authorization`, `complete_authorization`, `api/google.py::link`, and `OAuthTransaction`.

The OAuth transaction records a user ID and browser-binding digest but does not identify the application session that authorized linking. Completion checks that the user remains active and verified, then adds the identity without validating the initiating session. The callback does not require that session cookie. This violates D-022 account-policy item 5, which requires the authenticated session that started linking.

**Reproduced in six independent HTTP scenarios:** start a link from an authenticated synthetic account; then perform logout, logout-all, password change, password reset, absolute session expiry, or logout followed by login as a different user. In every case, completion still returns `result=linked`. A fresh browser can then use the newly linked Google identity to sign in to the original account. The provider substitute signs real RSA test tokens and validates PKCE; no live Google calls are involved.

**Impact:** someone who started linking while holding a valid session can retain the pending browser authorization and add a new login method after that session is revoked, including after password recovery. Switching the current application user does not prevent linking to the former user.

**Required outcome:** bind linking to the exact initiating session and revalidate its identity, revocation, absolute and idle expiry, and browser context at completion. Serialize the final authorization check and identity attachment safely against logout/reset. Preserve no-automatic-linking policy. Review any necessary additive storage change before implementation; do not silently modify an already applied migration. Retain regressions for the six reproduced cases, idle expiry, and concurrent revocation.

### R-02 — P2: Concurrent OTP comparisons exceed the approved attempt budgets

Location: [services/auth.py, lines 286-330](https://github.com/nebo23/tracking_sys/blob/8099755cb1c8d3a9f58782375858272c55e8f813/backend/app/services/auth.py#L286-L330), `check_rate_limit`, and `record_verification_failure`.

The daily bucket and challenge limit are read before comparing a code. No account serialization or atomic attempt reservation protects that decision. Failures are recorded in separate transactions after comparison, allowing simultaneous requests to use the same remaining allowance.

**Reproduced with the approved defaults:** five failures per challenge and ten failures per email per day. Seed synthetic counters at four and nine, then synchronize three independent transactions immediately before verifier computation. All three compare different incorrect codes and return `invalid_or_expired_code`; committed counters become **seven and twelve**. The synchronization controls scheduling only and does not replace the verifier, limit checks, or updates.

**Impact:** the approved challenge and account budgets are not strict under concurrency. Persistent failure recording and the separate peer throttle do not correct the account-level race.

**Required outcome:** serialize or atomically reserve comparison capacity before evaluating another candidate. Preserve failures across request rollback without introducing a cross-transaction lock cycle. Cover wrong-code concurrency, a correct code competing for the final allowance, resend races, multiple workers, and independent accounts.

### R-03 — P2: An OTP can expire during lock waiting and still be consumed

Location: [services/auth.py, lines 303-308](https://github.com/nebo23/tracking_sys/blob/8099755cb1c8d3a9f58782375858272c55e8f813/backend/app/services/auth.py#L303-L308) and [lines 332-345](https://github.com/nebo23/tracking_sys/blob/8099755cb1c8d3a9f58782375858272c55e8f813/backend/app/services/auth.py#L332-L345).

The expiry predicate binds `now_utc()` when the first challenge query is constructed. The second query reuses that predicate after waiting for the user lock, so it checks expiry against the earlier timestamp.

**Reproduced:** hold the synthetic user's row lock in another transaction; submit the correct OTP while it remains valid; release the lock after expiry, within the application's lock timeout. Verification succeeds and sets both `consumed_at` and `email_verified_at` after `expires_at`. The measured excess in this run was approximately **0.064 seconds**.

**Impact:** the stated validity cutoff is not enforced at consumption during contention. This finding does not claim an unlimited expiry extension.

**Required outcome:** re-evaluate expiry against the current time after the required locks are acquired and immediately before consumption. Retain a deterministic test that expires the challenge while the verifier waits.

## Comparison with earlier review requests

| Item | Previous behavior or gap | Current result and evidence |
| --- | --- | --- |
| F-01: alternate Docker API port | Container origin settings did not follow the published port | **Fixed.** Compose forwards both origin settings to API and worker. Real Docker API on port `18007`: configured origin registration 202; default-port and unrelated origins 403. |
| T-01: inviter/invitation lock cycle | User `FOR UPDATE` lock could conflict with foreign-key key-share locks | **Fixed for the reported cycle.** Both user lookup helpers now use `FOR NO KEY UPDATE`. Current deterministic invitation test and same-user serialization test pass. The old-code comparison confirms the lock-mode change; this review did not rerun the historical deadlock reproduction on the old tree. |
| T-02: invitation acceptance throttle | No explicit persistent acceptance limit | **Fixed.** Peer limit precedes authentication; per-user limit precedes invitation lookup. Existing regressions pass for persistence after rollback, 429/Retry-After, isolation between users, expiry recovery, replay, and absence of denied-attempt side effects. |
| F-02/T-03: purpose explanations | Requested database, settings, services, and API explanations | **Present.** Relevant modules, classes, helpers, validation, lifetime, and transaction behavior are documented. Comments do not replace behavioral proof. |
| Model reference SQL | Requested per-model diagnostic examples | **Verified.** All 34 commented SELECT examples pass PostgreSQL EXPLAIN on the disposable migrated database: tenancy 12, authentication 14, access 8. |
| R-01: pending Google link | Session invalidation did not cancel link authority | **Unfixed; reproduced in six scenarios.** |
| R-02: OTP attempt race | Concurrent comparisons exceeded budgets | **Unfixed; reproduced at the approved defaults.** |
| R-03: OTP expiry during lock wait | Consumption reused the pre-wait cutoff | **Unfixed; reproduced.** |

## Coverage and independently observed checks

| Area or check | Observed result |
| --- | --- |
| Unmodified committed test suite | **180 passed in 55.75 seconds**, with no failures, skips, or warnings reported. Includes the 45 unit/contract and 135 PostgreSQL cases. |
| Additional defect diagnostics | **8 diagnostic cases passed in 10.71 seconds by asserting the defective behavior.** These are evidence of three defects, not eight additional product acceptance passes. |
| SQL example validation | One separate diagnostic passed; 34 EXPLAIN statements, no native/customer rows queried. |
| Committed Ruff checks | Lint passes; all 50 Python files already formatted, checked before adding the temporary diagnostics. |
| Dependency consistency | Project virtual environment `pip check`: no broken requirements. Linux container build also installs the pinned runtime requirements with `--require-hashes` successfully. No host-global packages were installed. |
| Diff hygiene | `git diff main..HEAD --check` and working-tree `git diff --check` pass. |
| Foundation and migrations | Repository suite verifies health failure/recovery, fresh and repeated upgrades, empty-state downgrade/recovery, populated-state refusal, model/schema agreement, and runtime permission restrictions on disposable PostgreSQL 18. |
| Tenancy and access | Role/grant enforcement, cross-agency and cross-client denial, composite relationships, last-Owner protection, audit atomicity, invitation rules, and scoped service credential tests pass. Future jobs, exports, and analytics consumers remain outside this implemented scope. |
| Password/session HTTP | Registration, password verification/recovery/change, expiry/revocation, Origin/CSRF, response sanitization, body limits, and existing concurrency cases pass. Pending Google-link revocation remains the exception described in R-01. |
| Google validation | Existing controlled-provider tests pass for signature, issuer, audience, nonce, state, binding cookie, replay, authoritative signup, explicit linking, and disabled users. They do not prove live Google configuration or cover R-01. |
| Mail delivery | Existing Gmail transport/error/scope substitute tests and outbox tests pass. The real Docker local-capture flow queues and processes one synthetic numeric code, verifies it with 204, and logs in with 200; unverified login returns 403. Container runtime UID is 10001. |
| OpenAPI | Existing generated-contract equality test passes. |
| Bounded secret audit | Compared 14 sufficiently long configured secret values and selected credential/private-key patterns against 337 historical Git blobs reachable from local refs. No matches. This is not a comprehensive credential-discovery or vulnerability audit. No secret value was printed. |
| GitHub evidence | No submitted reviews, review threads, discussion comments, commit statuses, or PR-triggered workflow runs were returned for this PR/head. GitHub's mergeability flag is not passing CI or review approval. |

Execution used the existing `.venv`, an archive of `8099755`, and a newly created Compose project `tracking-pr1-review-20261104`. The disposable database was `tracking_foundation_test` on `127.0.0.1:55433`, with synthetic credentials, local mail, and Google disabled except for controlled provider fixtures. The first sandboxed attempt could not connect to localhost; the complete successful run used the same isolated database with the required network permission. That environment restriction was not a product test failure.

Representative commands were `python -m pytest -q --tb=short`, `ruff check <archived backend>`, `ruff format --check <archived backend>`, `python -m pip check`, and `docker compose --env-file <synthetic environment> -p tracking-pr1-review-20261104 -f <archived compose> up -d --wait --build api`. Additional diagnostics ran separately after the unchanged suite; counters, identities, and mail in them were synthetic.

## Native environment: what changed since the previous report

Read-only inspection of the current native configuration/database and GET requests to the running local health endpoints established:

| Earlier report | Current observation |
| --- | --- |
| Native schema `0003_auth`, readiness 503 | **Resolved:** native `0004_identity` matches the code; 19 application tables; `/health/live` 200 and `/health/ready` 200. |
| Google disabled | **Configuration changed:** enabled settings validate. A successful live browser round trip remains unverified by this review. |
| Local mail, incomplete sender configuration | **Configuration changed:** Gmail mode validates, required sender values are present, and the sender client differs from the sign-in client. No provider request was made to validate those credentials. |
| Runtime restrictions | Runtime remains non-superuser, cannot create databases/roles, has no BYPASSRLS flag, and cannot CREATE in public schema. |

The [committed evidence](auth-evidence.md#native-schema-loss-and-rebuild-2026-11-04) records a native schema loss and rebuild after the additive rollout, including loss of the earlier test registration. This review verifies the current revision and readiness; it does **not** independently establish the historical cause or claim that the lost rows were restored. Its native SQL session was read-only and inspected metadata only.

Live Google sign-in/link/logout, Gmail API acceptance, and inbox receipt remain separate owner-operated checks. Complete-looking settings and a healthy database do not prove them. Production startup remains deliberately gated, and React remains a later specification.

## Documentation and publication preparation

These are additional review-preparation issues, distinct from the three behavioral blockers:

1. The committed decision register contains D-020 and D-022 but omits the locally recorded D-021. The PR explicitly acknowledges that omission. Preserve the owner's pending files and select the required decision/handoff documents deliberately for the next reviewed upload.
2. Three committed relative links have no target in the committed tree: `specs/001-foundation/evidence.md -> review-amendments.md`, `specs/002-tenancy-access/auth-evidence.md -> review-amendments.md`, and `specs/002-tenancy-access/auth-design.md -> ../003-privacy-data-policy/review-amendments.md`. The local files exist but are untracked.
3. Status prose is stale: README still says D-022 awaits upload although PR 1 already includes it; `specs/002-tenancy-access/spec.md` still states that Google is deferred and cites the earlier 115-case/0003 state. Update current-status passages while retaining historical evidence as history.
4. The pre-existing owner formatting edit at `backend/app/models/tenancy.py:33` triggers Ruff E501 and a format change in the working tree. It is absent from the committed PR and has the same executable AST. It was preserved, not reported as a defect in the committed application.

## Required next review

1. Correct R-01 first, including review of any additive session-binding storage design.
2. Correct R-02 and R-03 while preserving the approved OTP values, rollback behavior, and lock-order guarantees.
3. Retain regression tests that assert the required secure behavior, then run relevant tests and the complete suite on a disposable database.
4. Reconcile the current status and required decision/amendment links; preserve unrelated owner work.
5. Perform and record owner-operated live provider checks separately from automated substitutes.
6. Present the actual correction diff and evidence for owner review before its upload. Merge remains the owner's decision.

No push, PR update, merge, external message, provider authorization, or native data mutation was performed in this review. The prior report and owner edits were preserved. Review-only scripts, archive, synthetic mail, and Docker containers/volumes/images were removed after verification; the reusable deliverable is this report.
