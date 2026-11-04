# Authentication review corrections: R-01, R-02, and R-03

Date: 2026-11-04. Status: implemented, verified, and owner-approved for upload as Specification 002; merge pending.

## Authority and scope

The owner explicitly requested implementation of the three confirmed findings after the independent PR review. This slice restores the approved D-022 session-linking, OTP-attempt, and expiry contracts. It introduces no schema, dependency, OTP-policy value, provider, or production configuration change. Native data and private configuration are unchanged. Upload and merge retain their separate owner review gates.

The earlier local report, `pull-request-review-2026-11-04.md`, describes the defects in [PR 1](https://github.com/nebo23/tracking_sys/pull/1) at commit `8099755`. It remains historical evidence; its assessment does not describe this corrected local slice.

## R-01: require the initiating session throughout Google linking

Link initiation now passes the authenticated session token to the authorization service. For link transactions, the existing `binding_digest` stores a purpose-separated HMAC over the random browser binding and the initiating session-token digest. Neither raw token is stored. The callback supplies the current session cookie and must reproduce that same binding. A replacement session, even for the same user, cannot authorize the pending link.

After provider validation, the callback authenticates that exact session again, checks the user matches the initiating user, and retains the existing user/session row locks through identity attachment and commit. Logout-all and password reset/change use the same user-first locking order. A revocation completed during the provider exchange is therefore observed before attachment; a competing later revocation cannot interleave between the final session check and attachment.

Login transactions keep their existing browser-binding format. Existing pending link transactions using the old digest fail closed and must be restarted; no stored identity or active application session is removed. The normal valid-link and Google-login tests remain passing. Google-only sign-up and the no-automatic-linking policy are unchanged.

No migration is required. In particular, revision 0004 is not rewritten or reapplied.

## R-02: serialize verification before checking attempts

Verification acquires the existing normalized-email advisory lock, followed by the active user's `FOR NO KEY UPDATE` lock, before reading the daily budget or comparing a code. The advisory lock also serializes attempts for absent accounts and coordinates with registration. The user lock coordinates with resends and existing account-state changes. Separate database sessions cannot evaluate different candidates using the same remaining allowance.

Failures still commit their challenge counter, daily counter, and security event through the independent security engine before the request rolls back. The request deliberately holds no challenge lock on that failure path. Its user lock remains compatible with the foreign-key key-share lock needed by the failure event, avoiding a self-blocking transaction. Successful verification still commits atomically in the caller's transaction.

The limits remain five failed checks per challenge and ten per normalized email per day. An exhausted challenge can receive generic rejected requests, counted toward the daily budget, but those requests do not perform additional candidate comparisons. Resending does not reset the daily budget.

## R-03: check expiry after lock acquisition

The user lock is now acquired before selecting a challenge. After a matched challenge is locked, verification checks `expires_at` against a newly sampled clock value immediately before consumption. Expiry during either a user-row wait or a challenge-row wait causes rejection without verifying the user or consuming the challenge.

## Regression coverage and observed evidence

The retained tests are in `backend/tests/integration/test_auth_review_regressions.py`:

| Cases | Required behavior verified |
| --- | --- |
| Nine Google-link cases | Reject completion after logout, logout-all, password change, reset, absolute expiry, idle expiry, switching users, replacing the session for the same user, or encountering an old browser-only link binding. Revocation tests restore the revoked cookie, proving server enforcement rather than relying on browser deletion. |
| One concurrent Google case | Logout-all completed during the provider exchange prevents identity attachment. |
| Two concurrent wrong-code cases | Three contenders share one remaining challenge allowance; only one candidate is compared. The challenge count stops at five. With the daily count initially nine, it stops at ten and the other requests are rate-limited. |
| Two competing-operation cases | The final allowed wrong code serializes with a correct code or a resend. The correct code cannot bypass the now-exhausted daily budget; a resend preserves that budget. |
| Two expiry cases | Reject a correct code that expires while waiting for either the user row or challenge row. |

These use explicit events/barriers and PostgreSQL lock observations, with bounded waits, separate transactions, and synthetic records. They do not contact Google or Gmail.

Observed commands and results:

- Targeted existing Google/OTP tests plus the initial regressions: **44 passed in 29.59 seconds**.
- Final correction regression file: **16 passed in 13.05 seconds**.
- Complete repository suite: **196 passed in 107.18 seconds**, with no failures, skips, or warnings reported. This includes 45 unit/contract and 151 PostgreSQL cases.
- Representative new regressions copied into an untouched archive of `8099755`: **three expected failures in 3.55 seconds**. Old code accepted a pending link after logout-all, compared three candidates using one remaining allowance, and accepted a code after expiry. The same tests pass on the corrected code.
- Ruff lint and format checks pass on all five changed Python files; `pip check` reports no broken requirements. The pre-existing formatting-only owner edit in `models/tenancy.py` remains untouched and outside this slice.
- The full suite includes OpenAPI equality, migration/model agreement, runtime privileges, last-Owner and invitation concurrency, authentication, tenant isolation, scoped credentials, and existing mail/provider substitutes.

Execution used the existing project `.venv` and the dedicated Compose project `tracking-auth-fixes`, with synthetic credentials, database `tracking_foundation_test` on `127.0.0.1:55433`, local mail mode, and Google disabled outside the controlled fixtures. The native database was not used for tests. Temporary runners, the baseline archive, and the test project's container, volume, and network were removed afterward.

## Review and rollout notes

After reviewing the correction summary and evidence, the owner explicitly authorized uploading these changes on 2026-11-04 and naming the update for the completed specification. This authorizes publication of the reviewed correction slice on claude/development and updating PR 1 as Specification 002. It does not authorize merge, deployment, or publication of unrelated working-tree changes.

Restarting the development API loads the corrected code; no database migration or new configuration is needed. A Google-link flow already pending across that restart must be started again. Existing completed links are unaffected.

Live Google and Gmail owner-operated checks and production readiness remain separate from these automated results. No external email, live provider authorization, upload, or merge was performed during implementation and verification; publication was authorized separately afterward as recorded above.
