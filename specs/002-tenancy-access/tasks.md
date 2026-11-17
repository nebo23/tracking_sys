# Tasks: 002-tenancy-access
Status: Approved scope, D-022 additions, and review corrections merged through PR 1 (`98747a2`, 2026-11-04). Reconciled 2026-11-10 against GitHub and dated evidence. Earlier counts below are historical slice results; local handoff checklist entries do not supersede that evidence.

## 002-A: tenancy foundation
- [x] Record D-017 approval of schema, role matrix, and boundaries.
- [x] Implement six models, migration, scoped constraints/services, and atomic audit.
- [x] Verify finance permissions, cross-tenant denial, revocation, last-Owner concurrency, migration recovery, and runtime privileges.
- [x] Apply verified additive native upgrade; retain historical [evidence](evidence.md).

## 002-B/C/D: authentication and access completion
- [x] Record D-018/D-019, social sign-in deferral, and local mail selection.
- [x] Implement approved dependencies, ten-table auth schema, and guarded migration.
- [x] Implement registration, verification, login, sessions, logout, password change/recovery.
- [x] Enforce cookie/Origin/CSRF, shared rate limits, bounded input, and redacted errors.
- [x] Expose agency/client/member/grant/audit APIs through authenticated authorization.
- [x] Implement encrypted mail outbox and reusable local worker with retry/idempotency.
- [x] Implement invitations, verified matching recipients, atomic acceptance, expiry/replay/revocation.
- [x] Implement scoped service keys, creator liveness, finance permission, and one-time return.
- [x] Verify live scope resolver and cache partition contract for future consumers.
- [x] Pass 115 automated cases and Ruff; verify dependencies and generated OpenAPI.
- [x] Apply additive 0003_auth to tracking_sys; verify 16 empty tables, metadata, privileges, health.
- [x] Verify non-root Docker API, real HTTP/local-mail smoke flow, and scoped disposable cleanup.
- [x] Update setup, walkthrough, decisions, boundaries, and [current evidence](auth-evidence.md).
- [x] Re-verify 115 cases and Ruff on 2026-11-03 before upload; record the result in [current evidence](auth-evidence.md).
- [x] Obtain upload approval (D-020); commit and push to the claude/development working branch.
- [x] Verify T-01/T-02 and T-03/T-04 documentation amendments; see [auth evidence](auth-evidence.md#review-amendments-t-01-to-t-04-2026-11-04).
- [x] Implement D-022 Google sign-in, numeric verification OTP, and opt-in Gmail delivery; verify R-01/R-02/R-03 in the [correction evidence](auth-corrections-2026-11-04.md).
- [ ] Complete the owner-requested [review-amendments handoff](review-amendments.md), including comment/query references and the two auth/access findings; track the Docker finding in foundation and Google/Gmail design in privacy.
- [x] Record the completed merge through [PR 1](https://github.com/nebo23/tracking_sys/pull/1), `98747a2`; production sign-off remains separate.

## Explicit later obligations
- Facebook sign-in remains deferred. Google sign-in and the Gmail adapter are implemented under D-022; live-provider and production delivery approval remain separate.
- Actual job/export/report/cache consumers enforce and test the shared scope contract in their specs.
- Privacy/retention/cleanup, production capacity, hosting, monitoring, and release validation retain their specification gates.
