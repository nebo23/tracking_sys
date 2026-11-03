# Specification 002-B/C/D verification evidence

Date: 2026-10-30. Status: approved local implementation verified; owner acceptance and upload approval pending. Authority: D-018/D-019 and [auth design](auth-design.md). [002-A evidence](evidence.md) remains historical evidence.

## Delivered
- Email/password registration, verification/resend, login, current identity, logout/logout-all, password change, and recovery/reset.
- Argon2id credentials, opaque server-side sessions, hashed one-time tokens, database-backed rate limits, and append-only security events.
- HttpOnly cookies, exact Origin validation, session-bound CSRF, explicit CORS, bounded request bodies, no-store responses, and sanitized errors.
- Authenticated agency/client/member/grant/audit HTTP operations using the existing role and tenant policy.
- Email invitations with explicit client/financial grants, verified recipient matching, live role checks, expiry/revocation, atomic acceptance, and replay protection.
- Expiring read-only service credentials, returned once and stored as digests. Creator status/role and client grants are rechecked on use.
- Shared live scope resolver and principal/permission-partitioned cache keys for later jobs, exports, and reports. A queued actor or cache key alone never grants access.
- Encrypted transactional mail outbox and reusable local .eml worker, including retry/idempotency. External transport is absent and production startup fails closed.
- Additive 0003_auth: ten tables, nullable users.email_verified_at, expanded audit constraints, and restricted runtime privileges. Existing users are not silently verified.
- Hashed requirements and OpenAPI snapshot: 25 paths, 32 operations. No frontend or social sign-in placeholder routes.

## Automated verification
Final command: project .venv Python running `pytest -q -x --tb=short` with TRACKING_RUN_DB_TESTS=1 and the documented disposable connection overrides.

**115 passed in 124.16 seconds**: 17 unit/contract cases and 98 real PostgreSQL cases. No skipped tests or warnings in the final run. Ruff lint/formatting passed. Installed requirements pass pip check.

Target: tracking_foundation_test on 127.0.0.1:55433, PostgreSQL 18.6, Compose project tracking-system-foundation-test. Name/port/host/schema/empty-state guards remain mandatory. All identities and tenant data are synthetic. Native tracking_sys is never a fixture target.

Verified behavior includes:
- Full register -> local email capture -> verify -> login -> agency/client creation -> logout.
- Duplicate/concurrent registration preserves one identity without replacing its password. Concurrent token consumption has one winner.
- Verification/reset purpose, expiry, replay, resend invalidation; reset/change revokes other sessions.
- Idle/absolute expiry, disabled users, logout-one/logout-all, cookie flags, CORS, Origin/CSRF checks, and cross-session CSRF rejection.
- Generic recovery responses, redacted errors, request-size limits, persistent/shared/concurrent throttling, and independent security commits while the request pool is exhausted.
- HTTP tenant/client isolation, last-Owner protection, membership revocation, and existing service-level finance/access cases.
- Invitation matching, expired/revoked tokens, disabled/demoted inviter, archived client, unverified recipient, Owner restrictions, foreign-client denial, existing membership conflicts, concurrent acceptance, and audit/outbox rollback.
- Key scope/expiry/revocation, disabled/demoted creator, disabled user, archived client, cookie/Bearer ambiguity, denied administrative writes, financial scope, and immediate resolver reauthorization.
- Composite foreign keys reject foreign-client invitation/key grants. Audit/security events remain append-only; runtime cannot change user status or migration metadata.
- Encrypted outbox, failure backoff, retry after file publication before database commit, and payload clearing after delivery.
- Fresh/repeat upgrade, guarded empty downgrade/recovery, populated downgrade refusal, metadata agreement, health, fail-closed configuration, and OpenAPI agreement.

The first migration trial found a naming-convention issue in audit constraint replacement. It was corrected and the entire migration cycle passed before the native upgrade. A separate bounded pool protects independent counters/failure events from request-pool exhaustion; its regression case passes.

## Native database
Preflight found 0002_tenancy and six empty tables. Applied only additive 0003_auth using tracking_migrator on native PostgreSQL 18.4.

- Revision 0003_auth; all 16 application tables exist and are empty.
- Alembic metadata comparison reports zero differences.
- Runtime is tracking_app; security event UPDATE and users.status UPDATE privileges are false.
- In-process FastAPI: /health/live = 200, /health/ready = 200, unauthenticated /agencies = 401.
- No fixture account, cleanup, downgrade, or customer data was written to tracking_sys.

These checks do not establish a persistent native HTTP listener. Use the setup guide to start Uvicorn.

## Container verification
The final API/migration images built from pinned Python and hashed runtime dependencies. The API became healthy on loopback port 18002 against the isolated database. A real HTTP smoke test recorded: registration 202, local mail delivery of one message, verification 204, login 200, and agency creation 201. Cookie handling used a real HTTP cookie jar; token/password values were not printed.

The local worker wrote a synthetic .eml into the test mail volume. Runtime UID was 10001, and container pip check passed. The migration service completed successfully before API startup. No external email transport was used.

After verifying exact volume names and Compose project labels, removed only the tracking-system-foundation-test containers/network and its postgres-data/mail-data volumes. Native tracking_sys and the original development Docker volume were preserved. The test HTTP listener was removed with its container.

## Repository verification
Final Ruff check and format check passed for all 38 Python files; host pip check found no broken requirements. Git diff whitespace checks passed. A scan of 163 maintained files found no local configuration secret values and no broken relative Markdown links. .env, .env.docker, .venv, and local mail paths remain ignored. Existing unrelated workspace changes were preserved.

## Boundaries
Google/Facebook login is deferred; social analytics scope is unchanged. Local capture proves local flows only; external provider selection and delivery verification remain production prerequisites.

No React screens, finance data endpoints, actual jobs/caches/exports, RLS, deployment, security certification, load/SLO guarantee, or real customer data handling is claimed. Future consumers must adopt/test the shared scope contract in their own specs. Retention/cleanup remains in specification 003 and production gates. Local mailbox files contain sensitive test links and remain ignored.

No commit, push, PR, external email, or provider-account change was performed. Owner review precedes upload or progression.
