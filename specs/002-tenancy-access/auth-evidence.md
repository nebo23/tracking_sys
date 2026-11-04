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

## Pre-upload re-verification (2026-11-03)
Under D-020 the owner approved upload of the completed 001/002 work to the claude/development branch. Before the commit, the documented disposable procedure was rerun against a fresh tracking-system-foundation-test database on 127.0.0.1:55433, which was removed afterward.

- Ruff check and format check passed for all 38 Python files; 17 unit/contract cases passed without a database.
- **115 passed in 50.88 seconds** with no failures or skips.
- One UnsupportedFieldAttributeWarning was emitted during test_concurrent_invitation_acceptance_creates_one_membership. FastAPI 0.162.0 suppresses this Pydantic 2.14 warning with warnings.catch_warnings(), which is process-global and not thread-safe; the concurrent test can therefore surface it. The application declares no Field alias outside model fields, and the test assertions passed. This is recorded as a framework test-output artifact, not a product defect.
- A scan of the 163 commit candidates found no local configuration secret values, private keys, or credential URLs.

No native tracking_sys data, migration, or configuration was changed by this re-verification.

## Review amendments T-01 to T-04 (2026-11-04)
Authority: D-020/D-021 and the [review amendments](review-amendments.md). All database checks used the guarded disposable tracking_foundation_test database on 127.0.0.1:55433 with synthetic data. Native tracking_sys was not migrated, seeded, or queried.

Documentation slice (T-03, T-04; committed locally as 5892e42):
- Purpose comments for every maintained backend module, class, and function, and bounded read-only PostgreSQL reference queries beside all 16 mapped models.
- A script compared `ast.dump(ast.parse(...))` with the previous commit for all 20 changed Python files: every executable AST is identical.
- All 30 reference queries were extracted from the comments and executed in a `SET TRANSACTION READ ONLY` transaction against the 0003_auth schema. All succeeded; none projects password hashes, token/key digests, bucket keys, or encrypted payloads, and every list query is bounded.

T-01 lock cycle (reproduced, then fixed):
- New deterministic test `tests/integration/test_lock_order.py`: the inviter's transaction takes the session-authentication user lock; the invitee's transaction accepts an invitation in a worker thread while the main thread polls `pg_stat_activity` for a `Lock` wait; then the inviter renames the agency.
- Before the fix, the invitee blocked on the inviter's user row while holding the agency lock, and PostgreSQL aborted the acceptance with `DeadlockDetected` (SQLSTATE 40P01) on the issuer-attributed audit insert. This is reproduced evidence, not only a static hypothesis.
- Fix: `_lock_user` and `_user_by_email` use `with_for_update(key_share=True)`, which SQLAlchemy compiles to `FOR NO KEY UPDATE` (confirmed by compiling the statement). The same test then passes: acceptance completes while the inviter holds its lock, the inviter's rename then succeeds, and audit attribution is unchanged (membership/grant events by the inviter, `invitation.accepted` by the invitee).
- A second deterministic test shows a concurrent lock on the same user still waits until the first transaction commits, so per-user serialization is retained.

T-02 invitation throttling:
- `/invitations/accept` now applies an `invitation-ip` peer bucket as a decorator dependency (resolved before session authentication and its user lock) and an `invitation-accept` bucket per authenticated user before invitation lookup. Counters commit on the separate security engine.
- `tests/integration/test_invitation_throttle.py` verifies: invalid tokens counted after rollback, success below the limit, replay rejection, 429 `rate_limited` with Retry-After, no membership/audit side effects for denied attempts, separate budgets per user, recovery after window expiry, and the peer limit counting unauthenticated attempts.
- The OpenAPI snapshot is unchanged (the contract test passed without regeneration).

Full verification after the slice: Ruff check/format pass except the pre-existing owner edit at backend/app/models/tenancy.py line 27 (E501 and formatter rewrap), which was left unchanged and uncommitted. **122 passed in 36.73 seconds** (18 unit/contract and 104 PostgreSQL cases), with no failures, skips, or warnings. F-01 evidence is recorded in the [foundation evidence](../001-foundation/evidence.md).

## D-022 implementation: numeric verification, Google sign-in, and Gmail delivery (2026-11-04)
Authority: D-022 (owner approval of the six decisions in the [auth design](auth-design.md)). Local automated verification only; no live Google or Gmail call was made, and native tracking_sys was not migrated or written.

Delivered:
- Dependency: PyJWT[crypto] 2.15.1 (released 2026-09-28) added with hashes; the lock diff adds only pyjwt, and `pip check` passes. Code exchange, Gmail send, and the sender helper use the standard library.
- Migration 0004_identity: external_identities, oauth_transactions, verification_challenges, mail_outbox.expires_at, and the extended security_events action constraint. Least-privilege column grants; guarded downgrade refuses populated identity state.
- Numeric verification: six-digit codes kept as strings, ten-minute lifetime, keyed HMAC verifier under the independent TRACKING_OTP_SECRET, five failed checks per challenge, 60-second resend cooldown, ten failed checks per email per 24 hours, failure counting in independent transactions, and atomic consumption under user-then-challenge locks. Legacy links remain accepted until expiry and are consumed by a resend.
- Google sign-in: GET /auth/google/start, POST /auth/google/link, GET /auth/google/callback behind TRACKING_GOOGLE_SIGN_IN_ENABLED; state/nonce/S256 PKCE, browser-binding cookie, single-use transactions, PyJWT validation of signature, RS256, issuer, audience, expiry, and nonce; the approved account policy; existing opaque sessions.
- Gmail: TRACKING_MAIL_MODE=gmail transport with token refresh, send-only scope check, bounded timeouts, sanitized failure codes, and expiry-aware delivery; `python -m app.gmail_authorize` loopback helper that refuses the sign-in client and stores the refresh token without printing it.
- Compose forwards the verification key and the optional provider settings; OpenAPI regenerated (29 paths, 36 operations).

Automated verification on the guarded disposable database (tracking_foundation_test, 127.0.0.1:55433):
- **180 passed in 70.51 seconds** (45 unit/contract and 135 PostgreSQL cases), no failures, skips, or warnings in the final run. An earlier run of the same suite surfaced the known FastAPI warning-filter artifact once.
- New coverage includes leading zeroes and format bounds, per-challenge exhaustion with persisted counts, the per-email daily cap with identical behavior for unknown emails, resend cooldown and invalidation, concurrent consumption, legacy-link transition, expired outbox messages, Gmail-mode delivery through a controlled sender, a Google-only first password through reset, 0004 downgrade refusal when populated, runtime privilege denials on the new tables, and model/migration agreement.
- Google tests use a controlled provider substitute with a locally generated RSA key and PKCE checking: sign-up, repeat sign-in, session parity (Origin/CSRF, logout), wrong audience/issuer/expiry/nonce/signature, missing subject, unverified or non-authoritative email, hosted-domain sign-up, state replay, missing browser binding, cancellation, explicit linking, identity already linked elsewhere, and disabled users.
- Gmail unit tests use a substitute opener: MIME and Message-ID, token caching, sanitized refresh and send failures, scope enforcement, and helper state/scope/storage checks.
- Ruff check and format pass except the pre-existing, uncommitted owner edit at backend/app/models/tenancy.py line 27.

Container smoke test (disposable project tracking-system-otp-test, API port 18003, removed with its volumes and images afterward): /auth/register 202; login before verification 403; /auth/google/start 404 while disabled; one bounded worker batch delivered one message containing a code and no link token; /auth/verify-email-code 204 (the code was read inside the container and never printed); login 200; runtime UID 10001.

Not yet verified (owner-operated): a live Google sign-in in a browser, sender authorization with a separate Desktop client, Gmail acceptance, and receipt at a designated owner test address. The private .env initially reused the sign-in client for TRACKING_GMAIL_CLIENT_ID/SECRET, which Gmail mode and the helper refuse by design. On the owner's instruction (2026-11-04), those duplicated sender values were cleared without displaying them, TRACKING_GOOGLE_COMPLETE_URL was set to the local documentation page, and local Google sign-in was enabled; the settings load successfully. The owner then created a separate Desktop client; its download was checked by type (installed), project, and difference from the sign-in client, and stored as TRACKING_GMAIL_CLIENT_ID/SECRET without display. The sender refresh token and address await the owner's consent, and mail stays in local mode until then.

## Native 0004_identity rollout (2026-11-04)
Authority: the owner's explicit approval in the working session on 2026-11-04, given after the running API reported 503 for verification requests because the native schema lacked the 0004 tables.

- Preflight (read-only, tracking_migrator): revision 0003_auth; 16 application tables. Rows present from an earlier owner registration: users 1, password_credentials 1, auth_tokens 1, mail_outbox 1, security_events 1, auth_rate_limits 3; all other tables empty.
- Applied `alembic upgrade head` with tracking_migrator; exit code 0. No seed, downgrade, truncate, or delete was run.
- Postflight: revision 0004_identity; 19 application tables; every preexisting row count unchanged; external_identities, oauth_transactions, and verification_challenges empty. Runtime readiness, which reported schema_mismatch before the upgrade, reports no failure.
- Runtime role privileges on the new tables: SELECT and INSERT only, with column UPDATE limited to external_identities.last_login_at, oauth_transactions.consumed_at, and verification_challenges.consumed_at/failed_attempts/invalidated_at; no DELETE or TRUNCATE; tables owned by the migration role.
- The running Uvicorn process must be restarted to load the updated .env (settings are read at startup; reload watches Python files only).

## Native schema loss and rebuild (2026-11-04)
- After the 0004 rollout, the public schema of tracking_sys was dropped outside the project between 18:43 (last successful outbox delivery) and about 18:50 local time; read-only inspection then found no public schema, no tables, and no alembic_version, while the database and both project roles remained. No project code drops schemas, and no repository file changed in that window other than this session's documented edits. The earlier owner test registration (one user and related rows) was lost.
- The owner recreated the schema as administrator with the grants in [local-roles.sql](../../infra/postgres/local-roles.sql) (owner pg_database_owner; CREATE revoked from PUBLIC; USAGE and CREATE for tracking_migrator; USAGE for tracking_app). With the owner's go-ahead, `alembic upgrade head` rebuilt revisions 0001 through 0004: 19 empty application tables, runtime privileges identical to the rollout check, readiness without failure, and the running API answering /health/ready with 200.
- Mail delivery was then switched to Gmail mode after the owner's sender consent (refresh token stored in .env without display; sender is the owner-designated company mailbox). The outbox was empty at the switch, so no earlier message could be sent externally.

## Independent review corrections R-01 to R-03 (2026-11-04)

The owner authorized fixing the three reproduced review findings. The corrected local slice binds pending Google links to the exact initiating session and revalidates that session at completion, serializes OTP comparisons before checking budgets, and rechecks OTP expiry after lock acquisition. No schema, dependency, native data, or policy-value change is required. See the [correction design and evidence](auth-corrections-2026-11-04.md).

Verification: **196 passed in 107.18 seconds** on the guarded disposable database, including 16 new security/concurrency cases. Three representative regressions were also run against an isolated archive of the old `8099755` application and failed for the original defective behavior. Changed Python files pass Ruff lint/format; dependency consistency and OpenAPI equality pass. Existing owner changes were preserved. The owner subsequently approved uploading this correction slice as Specification 002 on 2026-11-04; merge and live provider checks remain separate.
