# Specification 002-B/C/D: authentication and access completion
Status: Approved for implementation under D-019. Updated: 2026-10-30.

## Authorized direction and pending choices
The owner requested continuation of specification 002 including authentication, and explicitly deferred Google/Facebook login until their credentials are supplied. Existing 002-A roles and isolation rules remain authoritative. No OAuth provider route or placeholder sign-in is included now.

This deferral concerns user sign-in only. Social-account connections and analytics remain in specifications 009-013 with their existing launch scope and access requirements.

The owner explicitly approved this design, its authentication dependencies/schema, self-service registration, and local mail capture on 2026-10-30 (D-019). This authorizes local implementation and verification. It does not authorize deployment, real customer messages, push, or PR creation.

## Approved user flows
1. Self-service account registration with email, display name, and password. The response is generic for an existing email and does not replace an existing password.
2. Verify email with an expiring, single-use token, then log in. A verified user may create an agency and becomes its Owner. Invited users may register without creating an agency.
3. Browser login establishes an opaque server-side session in an HttpOnly cookie. No roles or client grants are trusted from the cookie. Logout, logout-all, password changes, reset, and account disablement invalidate applicable access.
4. Password recovery uses a generic acknowledgement and expiring single-use tokens; reset revokes all sessions. Knowing an email address alone never changes access.
5. Existing Owner/Admin users manage authorized agency/client operations through authenticated HTTP endpoints. The 002-A services remain the authorization source.
6. Owner/Admin users invite members by email with a role and explicit client/financial grants. Only an Owner may invite an Owner. Acceptance requires a verified logged-in matching email, a pending unexpired token, and a still-authorized inviter. Acceptance is atomic and replay-safe. Existing memberships are not silently promoted by invitation acceptance.
7. Owner/Admin users create/revoke expiring service API keys with explicit client grants. Keys support client reads and optional finance-read authorization only; they do not grant administrative writes. Their creator must retain active management membership. Return a key once, store only its digest, and reject revoked/expired credentials.

## Dependencies and session choice
- pwdlib[argon2] for Argon2id password hashing and verification.
- email-validator for syntax and normalization without network/DNS checks during requests. Preserve the existing case-insensitive account identity convention; do not apply provider-specific dot/plus rewrites.
- cryptography/Fernet to encrypt queued email payloads containing one-time links. Its separate local key is not stored in PostgreSQL.
- Existing FastAPI, SQLAlchemy, Psycopg, Alembic, and PostgreSQL remain unchanged. No new queue service, hosted identity provider, or paid subscription is required.

Opaque sessions are approved for the browser application because permission changes and logout can be checked against current server state. API keys use a separate Bearer mechanism and cannot act as browser sessions.

## Approved schema additions
Existing users gain nullable email_verified_at. No existing user is silently treated as verified or given a password.

| Table | Purpose and essential constraints |
|---|---|
| password_credentials | One credential per user; Argon2 hash and password-change timestamp. |
| auth_sessions | Random-token digest, user reference, creation/last-seen/absolute expiry, and revocation timestamp. |
| auth_tokens | Unique digest, user, purpose (email verification/password reset), expiry and single-use consumption timestamp. |
| auth_rate_limits | HMAC-derived bucket keys, expiry, and atomic attempt counters shared across API processes. No raw email/IP. |
| security_events | Append-only authentication events; optional user reference, action code, timestamp. No submitted password/token or raw email/IP. |
| mail_outbox | Encrypted message payload, purpose, attempts, next-attempt time, delivery timestamp, and sanitized failure code. Clear encrypted content after delivery. |
| agency_invitations | Agency, normalized recipient email, role, token digest, inviter membership, expiry, and pending/accepted/revoked state. |
| invitation_client_grants | Composite references bind invitation, agency, and client; explicit financial flag. |
| service_credentials | Agency, creator membership, name, key digest, expiry, active/revoked state, timestamps. |
| service_client_grants | Composite references bind credential, agency, and client; explicit financial flag. |

Extend the scoped audit action/resource constraints for invitations and service credentials. Identity/security events use their separate table because they can occur before agency membership exists. Runtime grants permit required auth operations but keep security/audit events append-only and schema changes reserved to the migrator. Native upgrades are additive; tests and recovery exercises run only on the guarded disposable database.

## Approved HTTP contract
JSON requests and explicit response schemas; secret fields are never echoed by validation errors or list endpoints. Tokens are accepted in request bodies, cookies, or Authorization headers, not backend URL query parameters. Auth responses disable caching.

| Surface | Operations |
|---|---|
| /auth | register, verify-email, resend-verification, login, me, logout, logout-all, forgot-password, reset-password, change-password |
| /agencies | create and list accessible agencies; get/update scoped agency details |
| /agencies/{agency_id}/clients | list/create/get/update authorized client workspaces |
| /agencies/{agency_id}/members | list/update authorized memberships; manage explicit client grants |
| /agencies/{agency_id}/audit | bounded, scoped audit reads |
| /agencies/{agency_id}/invitations | issue, list without token material, revoke; separate authenticated accept operation |
| /agencies/{agency_id}/service-credentials | issue once, list metadata, revoke |

Missing/invalid authentication returns 401; unauthorized resources remain unavailable without revealing foreign-tenant records. Invalid input returns sanitized 422, state conflicts 409, throttling 429 with Retry-After. Health endpoints retain their existing contract. Generate and review OpenAPI from the implemented route schemas.

## Browser and credential controls
- Use a Secure, HttpOnly, SameSite cookie in production, without a Domain attribute. Allow an explicit loopback development exception for HTTP; production settings reject it.
- Check an exact allowed Origin and a session-bound CSRF header on cookie-authenticated mutations. CORS uses explicit origins with credentials, never a wildcard. Reject ambiguous cookie/Bearer authentication.
- Session identifiers, verification/reset tokens, and service keys have cryptographic randomness; persist digests only. Verification/reset/invitation tokens are consumed under transactional locking.
- Approved configurable defaults: session absolute lifetime 12 hours and idle lifetime 30 minutes; verification 24 hours; reset 30 minutes; invitation 7 days; service key at most 90 days. Passwords permit 15-128 characters without arbitrary character-composition rules.
- Bound input and password hashing cost. Database-backed throttling applies to login, registration, verification/recovery, and token consumption. Failed attempts must remain counted even when the business transaction rolls back.
- Review amendment T-02 (2026-11-04): invitation acceptance uses an `invitation-ip` peer bucket (the existing 30 requests/minute default) resolved before session authentication, and an `invitation-accept` bucket per authenticated user before invitation lookup. Proposed default for owner review: five attempts per user per minute (`invitation_attempts_per_minute`), mirroring the login subject limit; configurable from 1 to 100.
- Review amendment T-01 (2026-11-04): user-row locks in session authentication and email lookup use `FOR NO KEY UPDATE`. The mode still serializes same-user credential, verification, and session changes, but it is compatible with the key-share locks taken by foreign keys from audit and membership rows. A deterministic disposable-database test reproduced `DeadlockDetected` between invitation acceptance and a concurrent inviter mutation under the previous `FOR UPDATE` mode; see [evidence](auth-evidence.md).
- Generate independent session/CSRF/rate-key and email-encryption secrets in ignored local configuration; never log request bodies or raw authentication failures.

## Email delivery for the current stage
Approved implementation: a durable encrypted outbox and a reusable local mail worker that writes development .eml messages to ignored local-data/mail. This allows the complete verification, reset, and invitation flows to be exercised locally without sending external messages or selecting a paid provider.

Local capture is a development delivery mode, not proof of internet delivery. Production refuses that mode. An actual email provider/SMTP configuration and delivery verification remain an explicit production prerequisite. The worker retries recoverable failures and reuses message identifiers so a retry does not generate a new token. Tests use temporary local mail output.

## Jobs, cache, and export contracts
Provide one resolver for a trusted user or authenticated service credential plus agency/client scope and requested permission. Resolve live status/grants at execution time; queued actor IDs or cache keys do not authorize access. Cache keys include agency, client, principal, and permission partition. Consumers must reauthorize before reading cached data or creating an export. Tests exercise the resolver across two agencies, two clients each, and revocation. Real reporting/export/job implementations remain in their own specs and are not falsely claimed here.

## Verification and delivery gates
- Real PostgreSQL HTTP flow: register -> captured verification -> verify -> login -> agency/client operations -> logout.
- Password hashing, generic account recovery, token expiry/replay, password reset and session revocation, duplicate-registration and invitation races.
- Cookie attributes, CSRF/Origin rejection, session expiry, immediate membership/grant revocation, sanitized errors, and persistent rate limits.
- Invitation role restrictions, matching verified identity, client isolation, disabled inviter, expiry/reuse, and transactional audit.
- API-key expiry/revocation/scope, creator downgrade, foreign-client denial, and job/cache resolver rechecks.
- Encrypted outbox content, local delivery, retry/idempotency, and absence of secret material in API lists/logs/OpenAPI.
- Existing 51 cases continue to pass; update schema guards and intentional privilege expectations to reflect the approved auth additions.
- Verify migration/model agreement on the disposable service, then apply the reviewed additive upgrade to tracking_sys and verify health. Keep native customer/identity tables unseeded.

## Primary references checked
- [FastAPI security example](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/): current password hashing integration with pwdlib/Argon2.
- [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): session lifecycle, cookies, and revocation considerations.
- [OWASP password recovery](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html): non-enumerating responses and single-use expiring recovery tokens.
- [Fernet documentation](https://cryptography.io/en/latest/fernet/): authenticated encryption and key handling for queued payloads.

The owner approved these project-specific choices under D-019; they are not requirements imposed by the references.
