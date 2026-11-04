# Local authentication and access

Approved scope: D-019 (specification 002-B/C/D) and D-022 (Google sign-in, numeric email verification, and Gmail delivery). The API uses email/password identity, six-digit email verification codes, optional Google sign-in, server-side sessions, invitations, and read-only scoped service keys. Facebook sign-in is deferred. React screens are not included in this stage, and production delivery remains blocked.

## Configuration

Install the hashed requirements in the project .venv and follow [local setup](local-environment.md). The owner's ignored .env and .env.docker already contain independent generated authentication, mail, and verification keys. Preserve existing values.

For another workstation, add these fields to its ignored configuration:

```dotenv
TRACKING_AUTH_SECRET=
TRACKING_MAIL_ENCRYPTION_KEY=
TRACKING_OTP_SECRET=
TRACKING_COOKIE_SECURE=false
```

TRACKING_AUTH_SECRET and TRACKING_OTP_SECRET each require at least 32 random bytes encoded as hexadecimal and must differ; the verification key is unrelated to every Google secret. TRACKING_MAIL_ENCRYPTION_KEY is a Fernet key. This command fills only missing or blank keys in an existing .env, without printing them or replacing established values:

```powershell
@'
from pathlib import Path
import secrets
from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key

path = Path(".env")
if not path.is_file():
    raise SystemExit("Create .env from .env.example first and configure database credentials.")
existing = dotenv_values(path)
for name, generate in {
    "TRACKING_AUTH_SECRET": lambda: secrets.token_hex(32),
    "TRACKING_MAIL_ENCRYPTION_KEY": lambda: Fernet.generate_key().decode(),
    "TRACKING_OTP_SECRET": lambda: secrets.token_hex(32),
}.items():
    if not existing.get(name):
        set_key(path, name, generate(), quote_mode="always")
print("Required keys are present; values were not displayed.")
'@ | .\.venv\Scripts\python.exe -
```

Use the same procedure with the explicit path .env.docker for an existing container configuration. These keys have different purposes and must remain private. Replacing the mail key makes pending encrypted messages unreadable; replacing the auth key invalidates existing CSRF values and rate-limit buckets; replacing the verification key invalidates outstanding codes. Key rotation requires a separate procedure.

## Run and exercise the local flow

Start Uvicorn using the setup guide, then use a second PowerShell terminal at the repository root. Use synthetic accounts only until privacy/retention requirements are approved.

```powershell
$apiBase = "http://127.0.0.1:8000"
$originHeaders = @{ Origin = $apiBase }
$testEmail = "team-member@example.test"
$securePassword = Read-Host "Synthetic password (15-128 characters)" -AsSecureString
$authPassword = [System.Net.NetworkCredential]::new("", $securePassword).Password
$registration = @{ email = $testEmail; display_name = "Local Reviewer"; password = $authPassword } | ConvertTo-Json
Invoke-RestMethod "$apiBase/auth/register" -Method Post -Headers $originHeaders -ContentType "application/json" -Body $registration

Push-Location backend
try { ..\.venv\Scripts\python.exe -m app.mail_worker } finally { Pop-Location }
```

The worker processes one bounded batch of up to 50 due messages and prints only counts. In the default local mode it writes .eml files to ignored local-data/mail; open the newest message and read the six-digit verification code. No message is sent to an external mailbox in local mode.

```powershell
$verificationCode = Read-Host "Six-digit code from the verification message"
Invoke-RestMethod "$apiBase/auth/verify-email-code" -Method Post -Headers $originHeaders -ContentType "application/json" -Body (@{ email = $testEmail; code = $verificationCode } | ConvertTo-Json)
$loginBody = @{ email = $testEmail; password = $authPassword } | ConvertTo-Json
$login = Invoke-RestMethod "$apiBase/auth/login" -Method Post -Headers $originHeaders -ContentType "application/json" -Body $loginBody -SessionVariable authCookies
$writeHeaders = @{ Origin = $apiBase; "X-CSRF-Token" = $login.csrf_token }
$agency = Invoke-RestMethod "$apiBase/agencies" -Method Post -WebSession $authCookies -Headers $writeHeaders -ContentType "application/json" -Body '{"name":"Local Review Agency"}'
Invoke-RestMethod "$apiBase/agencies/$($agency.id)/clients" -Method Post -WebSession $authCookies -Headers $writeHeaders -ContentType "application/json" -Body '{"name":"Local Review Client"}'
Invoke-RestMethod "$apiBase/auth/logout" -Method Post -WebSession $authCookies -Headers $writeHeaders
Remove-Variable authPassword, securePassword, registration, loginBody, verificationCode, login, authCookies, writeHeaders
```

These commands intentionally create local review data; they are not run automatically on tracking_sys. Do not run test fixture cleanup or downgrade commands against that database.

## Numeric email verification

- Registration and POST /auth/resend-verification queue a six-digit code valid for ten minutes. Codes are strings, so leading zeroes are significant.
- POST /auth/verify-email-code accepts `{email, code}`. Wrong, expired, superseded, or exhausted codes and unknown emails all return 400 `invalid_or_expired_code`.
- A challenge stops accepting codes after five failed checks. At most ten failed checks per email are accepted in 24 hours; further checks return 429 with Retry-After. Failures are counted in independent transactions.
- A resend within 60 seconds of the latest code queues nothing, so the latest code stays valid. A later resend invalidates the previous code.
- Only an HMAC verifier keyed by TRACKING_OTP_SECRET is stored. The code exists only in the encrypted outbox until delivery; an undelivered message is cleared without sending once the code expires.
- Legacy transition: verification links issued before codes are still accepted by POST /auth/verify-email until they expire (at most 24 hours). No new links are issued, and a resend consumes any outstanding link. Password-reset and invitation links are unchanged.

## Google sign-in

Disabled by default. The routes return 404 until TRACKING_GOOGLE_SIGN_IN_ENABLED=true.

1. In the owner's Google Cloud project, use the Web application client whose authorized redirect URI is exactly `http://127.0.0.1:8000/auth/google/callback` (G-06). Keep TRACKING_GOOGLE_REDIRECT_URI identical.
2. In the ignored .env, set TRACKING_GOOGLE_CLIENT_ID and TRACKING_GOOGLE_CLIENT_SECRET (already present on the owner's workstation) and, for a local test without the React app, `TRACKING_GOOGLE_COMPLETE_URL=http://127.0.0.1:8000/docs`. The completion URL's origin must be an allowed origin. Then set TRACKING_GOOGLE_SIGN_IN_ENABLED=true and restart Uvicorn.
3. In a browser, open http://127.0.0.1:8000/auth/google/start and sign in with an account listed under the consent screen's test users. The browser returns to the completion URL with `?result=signed_in` or `?error=<code>`.
4. In the same browser, open http://127.0.0.1:8000/auth/me to see the signed-in identity and its csrf_token. Swagger at /docs can then call POST /auth/logout with that token in X-CSRF-Token.

Policy (D-022): a known Google subject signs in its linked user. A new verified Gmail/googlemail address, or an address with a Workspace hosted-domain claim, creates a verified account without a password and without any agency membership. An email that already belongs to a local account is never linked automatically; the result is `google_link_required`. Sign in with the password and call POST /auth/google/link (Origin and X-CSRF-Token required), then open the returned authorization_url. A Google-only account can create a first password through forgot-password and the reset email. Disabled users are always denied.

Google sign-in requests only `openid email profile`, uses state, nonce, and S256 PKCE, and binds the attempt to the browser with a short-lived HttpOnly cookie. The callback is the only route that accepts protocol values in its query string. No Google token is stored or placed in a redirect, and the application session is the same opaque cookie used by password login.

## Gmail delivery

Local capture stays the default (TRACKING_MAIL_MODE=local). Gmail mode sends from one owner-authorized mailbox with the send-only scope.

1. Create a separate Desktop app OAuth client for the sender (G-06). The helper refuses to reuse the sign-in Web client. Store the downloaded JSON only under the ignored local-data/google/.
2. Authorize the sender. The helper opens Google's consent page, receives the response on a loopback port, and stores the refresh token in .env without printing it:

```powershell
Push-Location backend
try { ..\.venv\Scripts\python.exe -m app.gmail_authorize --client-json ..\local-data\google\sender-desktop-client.json } finally { Pop-Location }
```

   Sign in with the designated sender account and approve sending only. Without --client-json, the helper uses TRACKING_GMAIL_CLIENT_ID/SECRET from .env, which must belong to the Desktop client.
3. Set TRACKING_GMAIL_SENDER to that account and TRACKING_MAIL_MODE=gmail, then run one bounded worker batch with the command above. Use only a designated owner test recipient for live checks.

Failures are stored as fixed codes (for example gmail_authorization_revoked, gmail_rate_limited, gmail_temporary_failure) and retried with the existing backoff. A timeout after Google accepted a message can cause a duplicate on retry; exactly-once delivery is not claimed. External apps in the consent screen's Testing state receive Gmail refresh tokens that Google documents as expiring after seven days; rerun the helper when gmail_authorization_revoked appears.

## HTTP behavior

- JSON inputs reject unknown fields. Validation errors do not echo passwords, tokens, or codes. Request bodies are limited to 16 KiB.
- Registration, resend-verification, and forgot-password return generic acknowledgements. A 202 response means the request was accepted, not that an email was sent.
- Login requires verification, sets an HttpOnly/SameSite=Lax host-only cookie, and returns a session-bound csrf_token. GET /auth/me returns the same token for that session.
- Browser mutations require both an exact allowed Origin and X-CSRF-Token. Anonymous registration/login/recovery/verification endpoints require Origin. Command-line clients must supply it explicitly. Swagger's mutation fields include these headers; a browser supplies Origin automatically.
- Default sessions expire after 12 hours absolute or 30 minutes idle. Logout revokes one session; logout-all and password change/reset revoke all sessions. Disabled accounts are rejected immediately.
- Reset links last 30 minutes and invitations seven days. Link tokens are single-use; recovery invalidates earlier reset tokens.
- Owner/Admin invitation operations enforce the existing role matrix. Acceptance needs a logged-in verified matching email and a still-authorized inviter. Invite tokens are delivered through the same worker.
- Service keys are returned once at creation, stored as digests, and expire within 90 days. Supply Authorization: Bearer with the key and omit cookies. They allow only assigned-client reads, with optional explicit finance permission for future finance consumers. Administrative writes require a browser session.
- Missing/invalid identity returns 401; denied scope returns 403; invalid/expired one-time tokens or codes return 400; state conflicts return 409; invalid input returns 422. Rate limits return 429 with Retry-After.
- Default authentication limits are 30 requests/minute per direct peer, five login attempts/minute per normalized account, and three registration/verification-resend/reset/change requests/hour per subject. Invitation acceptance has its own namespaces: 30 requests/minute per direct peer before session authentication and five attempts/minute per authenticated user (TRACKING_INVITATION_ATTEMPTS_PER_MINUTE) before invitation lookup. Google routes use a separate 30 requests/minute peer namespace. Database counters persist failed attempts across API processes. Proxy/IP policy and load sizing require production review.

See the generated [OpenAPI contract](../../contracts/openapi.json) for all 36 operations. Errors and authenticated responses use Cache-Control: no-store and Referrer-Policy: no-referrer. Access logging is disabled in the documented Uvicorn command, so the Google callback's authorization code and state never reach request logs; other tokens belong in bodies/headers, not backend query strings.

## Docker mail capture

After starting the optional stack with .env.docker:

```powershell
docker compose --env-file .env.docker -f infra/docker/compose.yaml --profile mail run --rm --no-deps mail-worker
```

Messages are retained in this stack's mail-data volume at /app/local-data/mail. The worker runs as UID 10001 and uses the runtime database role. Compose forwards the verification key, mail mode, and the optional Gmail and Google settings from .env.docker; provider features stay off unless they are set there. To copy local messages for review, create a stopped mail-worker container, copy /app/local-data/mail into an ignored local-data directory, then remove only that container. Do not publish the volume or messages.

## Remaining release boundaries

TRACKING_ENVIRONMENT=production still fails startup: a reviewed production rule set (HTTPS origins and links, secure cookies, adapter secrets, published consent screen) is required first. Gmail acceptance in development does not establish inbox placement or production readiness. Hosting, TLS/proxy policy, retention/cleanup of sessions, counters, challenges, transactions and mail, load tests, monitoring, delivery verification, and Facebook sign-in remain their respective review gates.

The API uses five request connections plus two independent security-event/rate-limit connections per process, with no overflow and a two-second checkout timeout. This avoids requests exhausting the same pool they need for independent security commits. Capacity must be sized across all processes before deployment.

The shared scope resolver and cache partition helper support later jobs, reports, and exports. Those consumers must resolve live authorization before using a queued actor or cached result; their implementation and end-to-end tests remain in their own specifications. There are no finance data endpoints in this slice.
