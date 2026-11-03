# Tasks: 002-tenancy-access
Status: approved local implementation verified; owner acceptance and upload approval pending.

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
- [ ] Obtain owner review and acceptance of the completed local scope.
- [ ] Obtain upload approval before push/PR; preserve owner merge authority.

## Explicit later obligations
- Google/Facebook login after provider configuration and reviewed implementation.
- External email adapter and verified delivery before production.
- Actual job/export/report/cache consumers enforce and test the shared scope contract in their specs.
- Privacy/retention/cleanup, production capacity, hosting, monitoring, and release validation retain their specification gates.
