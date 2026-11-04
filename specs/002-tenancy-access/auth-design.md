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

## Proposed continuation under D-021: Google sign-in, numeric verification, and Gmail delivery
Status: prepared 2026-11-04 from G-01 to G-07 in the [privacy amendments](../003-privacy-data-policy/review-amendments.md); all six decisions were approved as proposed under D-022 on 2026-11-04 and implemented locally (see [evidence](auth-evidence.md)). The native tracking_sys rollout of 0004, live Google/Gmail checks, and production delivery remain separate steps. Facebook remains deferred; React screens remain in specification 018.

### Dependencies
| Need | Proposal | Alternative |
|---|---|---|
| Google ID-token validation (signature, issuer, audience, expiry, nonce) | `PyJWT[crypto]` 2.x pinned with hashes; it reuses the approved cryptography package, and `PyJWKClient` fetches and caches Google's published keys. No hand-written JWT parsing. | `google-auth` (official) plus a `requests` transport and its transitive packages. |
| Authorization-code exchange, Gmail send, sender token refresh | Python standard library (`urllib.request` with bounded timeouts, `email`, `base64`). No new package. | `google-auth-oauthlib` and `google-api-python-client`, which add several transitive packages. |
| Owner-run sender authorization helper | Standard-library loopback flow (`http.server`, `webbrowser`, PKCE S256, state) that requests only `gmail.send` and writes the refresh token to the ignored .env with the installed python-dotenv, without printing it. | `google-auth-oauthlib` InstalledAppFlow. |

Google endpoints are read from the published OpenID discovery document rather than hard-coded.

### Proposed schema: additive migration 0004
| Table or change | Columns and constraints | Runtime privileges |
|---|---|---|
| external_identities | id, user_id (FK users), provider ('google'), issuer, subject, created_at, last_login_at; unique (provider, subject); unique (user_id, provider). No tokens or copied profile. | SELECT, INSERT, UPDATE (last_login_at) |
| oauth_transactions | id, purpose ('login' or 'link'), user_id (nullable, for link), state_digest (unique), binding_digest, created_at, expires_at (10 minutes), consumed_at. The PKCE verifier and nonce are derived from the raw state with the purpose-separated HMAC, so neither is stored. | SELECT, INSERT, UPDATE (consumed_at) |
| verification_challenges | id, user_id (FK users), purpose ('email_verification'), verifier (HMAC-SHA256), failed_attempts (>= 0), created_at, expires_at, consumed_at, invalidated_at. | SELECT, INSERT, UPDATE |
| mail_outbox | Add nullable expires_at so the worker clears expired code messages instead of delivering stale codes. | Existing |
| security_events | Extend the action constraint with google_login_succeeded, google_registered, google_identity_linked, and verification_code_failed. | Existing (append-only) |

No existing row is converted. Fresh/repeat upgrade, guarded downgrade, and model agreement run on the disposable database; tracking_sys receives the reviewed additive upgrade only at the rollout step.

### Google sign-in contract
- `GET /auth/google/start`: requires TRACKING_GOOGLE_SIGN_IN_ENABLED and peer throttling. It creates a login transaction, sets a short-lived HttpOnly SameSite=Lax binding cookie scoped to /auth/google, and redirects (303) to Google with `openid email profile`, state, nonce, and PKCE S256. No offline access is requested.
- `POST /auth/google/link`: requires an authenticated session, Origin, and CSRF. It creates a link transaction for the current user and returns the authorization URL.
- `GET /auth/google/callback`: the only route that accepts protocol values (code, state, error) in the query string. It requires the matching binding cookie and an unconsumed, unexpired transaction under a row lock; exchanges the code with the client secret and PKCE verifier; validates the ID token; and then applies the account policy below. It issues the existing opaque session cookie after commit and redirects (303) to an allowlisted completion URL carrying at most a fixed error code. Only this route skips the Origin header requirement. Uvicorn access logs stay disabled, and responses keep Referrer-Policy: no-referrer.

Proposed account policy:
1. A known (issuer, subject) signs in its linked user if that user is active and verified. Email changes at Google do not move the identity.
2. An unknown subject with `email_verified` true, an authoritative address (gmail.com or googlemail.com, or an `hd` hosted-domain claim), and no existing local user creates a verified user without a password and without any agency membership.
3. An unknown subject whose email already belongs to a local user is never linked automatically. The callback returns `google_link_required`; the user signs in with the password and links from an authenticated session.
4. A non-authoritative or unverified Google email is refused for sign-up (`google_email_not_verified`); that person may register with email and password and then link.
5. Linking requires the authenticated session that started it, attaches at most one Google identity per user, and rejects a subject already linked elsewhere. Unlinking and erasure wait for the privacy decisions in specification 003.
6. A Google-only account may create its first password only through the existing reset email, which proves current mailbox control. Disabled users stay denied on every path.

### Numeric email verification contract
- Registration and `POST /auth/resend-verification` keep their generic 202 responses. Each issue invalidates the previous open challenge under the user lock and queues a code instead of a link. A resend inside the cooldown queues nothing and returns the same response.
- New `POST /auth/verify-email-code` accepts `{email, code}`. The code is a string matching `^[0-9]{6}$`, so leading zeroes survive. Every failure returns the same `invalid_or_expired_code`.
- Verifier: HMAC-SHA256 keyed by TRACKING_OTP_SECRET (64 hexadecimal characters, generated locally, independent of every Google secret) over purpose, challenge ID, user ID, and code, compared in constant time. No plaintext code is stored in the challenge table or logs; the encrypted outbox holds it only until delivery or expiry.
- A mismatch increments failed_attempts in an independent transaction before the error is returned, so the count survives rollback; the request transaction does not hold the challenge lock at that point. A match locks the user and then the challenge, rechecks its state, consumes it, and sets email_verified_at atomically.
- Request contract: email plus code is recommended over a returned challenge identifier. A returned identifier needs indistinguishable decoys for ineligible emails and for resends during the cooldown, which either breaks the user's latest valid code or reveals account existence through repeated identifiers. The challenge ID still binds the verifier.
- Legacy transition: stop issuing verification links immediately; keep honoring already issued, unexpired verification links (at most 24 hours) through the existing route; deliver already queued link messages unchanged; a resend consumes legacy verification tokens and issues a code. Reset and invitation links are unchanged.

Proposed OTP values: six digits, ten-minute lifetime, five failed checks per challenge, a 60-second resend cooldown, and at most ten failed checks per account per 24 hours across challenges (bounding repeated resend-and-guess attempts against a registration made with someone else's email), in addition to the existing persistent peer and per-subject limits.

### Gmail delivery contract
- TRACKING_MAIL_MODE accepts `local` (default) or `gmail`. Gmail mode requires the sender client ID and secret, refresh token, and a valid sender address, or configuration fails closed. Production remains blocked until a separate production rule set is approved.
- The worker refreshes a short-lived access token, builds a MIME message from the authorized sender with the stable outbox Message-ID, and calls `users.messages.send` with bounded timeouts. Failures map to sanitized codes (authorization revoked, rate limited, temporary failure, rejected message) without provider bodies, recipients, or codes in logs. The existing backoff applies; messages past expires_at are cleared without sending.
- A send that times out after Google accepted it can be retried and delivered twice. Duplicate delivery is possible; exactly-once delivery is not claimed. Local capture remains the default and keeps its tests.
- Google documents a seven-day refresh-token lifetime for external apps in Testing that request Gmail scopes, so the owner should expect to rerun the helper until the consent screen's publishing status is reviewed.

### Decisions required before implementation
1. Dependencies: PyJWT[crypto] plus standard-library HTTP/OAuth code (recommended), or Google's client libraries.
2. Schema: migration 0004 as listed, including mail_outbox.expires_at.
3. Account policy items 1-6, especially no automatic linking and sign-up only for authoritative verified emails.
4. OTP values and the email-plus-code request contract, including the per-account daily failure cap.
5. The legacy verification-link transition as described.
6. Sender client: the sender flow needs its own OAuth client. A Desktop client is recommended for the loopback helper; reusing the sign-in Web client would need a loopback redirect registered on it and mixes the two consents.

Verification after approval: unit and disposable-PostgreSQL tests with controlled substitutes for Google endpoints (no live calls in automated tests), migration fresh/repeat/downgrade checks, OpenAPI regeneration, and separate owner-operated live checks for Google sign-in, Gmail acceptance, and receipt at a designated owner test address.
