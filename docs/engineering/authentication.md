# Local authentication and access

Approved scope: D-019, specification 002-B/C/D. The API uses email/password identity, verified email, server-side sessions, invitations, and read-only scoped service keys. Google/Facebook sign-in is deferred. React screens and external email delivery are not included in this stage.

## Configuration

Install the hashed requirements in the project .venv and follow [local setup](local-environment.md). The owner's ignored .env and .env.docker already contain independent generated authentication and mail keys. Preserve existing values.

For another workstation, add these fields to its ignored configuration:

```dotenv
TRACKING_AUTH_SECRET=
TRACKING_MAIL_ENCRYPTION_KEY=
TRACKING_COOKIE_SECURE=false
```

The first key requires at least 32 random bytes encoded as hexadecimal. The second is a Fernet key. This command fills only missing or blank keys in an existing .env, without printing them or replacing established values:

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
}.items():
    if not existing.get(name):
        set_key(path, name, generate(), quote_mode="always")
print("Required keys are present; values were not displayed.")
'@ | .\.venv\Scripts\python.exe -
```

Use the same procedure with the explicit path .env.docker for an existing container configuration. These keys have different purposes and must remain private. Replacing the mail key makes pending encrypted messages unreadable; replacing the auth key invalidates existing CSRF values and rate-limit buckets. Key rotation requires a separate procedure.

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

The reusable worker processes up to 50 due messages and writes .eml files to ignored local-data/mail. Open the message locally and copy the value after `#token=`. The link's React page is not implemented yet; verification is performed through the API now. No message is sent to an external mailbox.

```powershell
$verificationToken = Read-Host "Token from the local verification message"
Invoke-RestMethod "$apiBase/auth/verify-email" -Method Post -Headers $originHeaders -ContentType "application/json" -Body (@{ token = $verificationToken } | ConvertTo-Json)
$loginBody = @{ email = $testEmail; password = $authPassword } | ConvertTo-Json
$login = Invoke-RestMethod "$apiBase/auth/login" -Method Post -Headers $originHeaders -ContentType "application/json" -Body $loginBody -SessionVariable authCookies
$writeHeaders = @{ Origin = $apiBase; "X-CSRF-Token" = $login.csrf_token }
$agency = Invoke-RestMethod "$apiBase/agencies" -Method Post -WebSession $authCookies -Headers $writeHeaders -ContentType "application/json" -Body '{"name":"Local Review Agency"}'
Invoke-RestMethod "$apiBase/agencies/$($agency.id)/clients" -Method Post -WebSession $authCookies -Headers $writeHeaders -ContentType "application/json" -Body '{"name":"Local Review Client"}'
Invoke-RestMethod "$apiBase/auth/logout" -Method Post -WebSession $authCookies -Headers $writeHeaders
Remove-Variable authPassword, securePassword, registration, loginBody, verificationToken, login, authCookies, writeHeaders
```

These commands intentionally create local review data; they are not run automatically on tracking_sys. Do not run test fixture cleanup or downgrade commands against that database.

## HTTP behavior

- JSON inputs reject unknown fields. Validation errors do not echo passwords or tokens. Request bodies are limited to 16 KiB.
- Registration, resend-verification, and forgot-password return generic acknowledgements. A 202 response means the request was accepted, not that an external email was sent.
- Login requires verification, sets an HttpOnly/SameSite=Lax host-only cookie, and returns a session-bound csrf_token. GET /auth/me returns the same token for that session.
- Browser mutations require both an exact allowed Origin and X-CSRF-Token. Anonymous registration/login/recovery endpoints require Origin. Command-line clients must supply it explicitly. Swagger's mutation fields include these headers; a browser supplies Origin automatically.
- Default sessions expire after 12 hours absolute or 30 minutes idle. Logout revokes one session; logout-all and password change/reset revoke all sessions. Disabled accounts are rejected immediately.
- Verification lasts 24 hours, reset 30 minutes, and invitations seven days. Tokens are single-use; resend/recovery invalidates earlier tokens of the same purpose.
- Owner/Admin invitation operations enforce the existing role matrix. Acceptance needs a logged-in verified matching email and a still-authorized inviter. Invite tokens are delivered through the same local worker.
- Service keys are returned once at creation, stored as digests, and expire within 90 days. Supply Authorization: Bearer with the key and omit cookies. They allow only assigned-client reads, with optional explicit finance permission for future finance consumers. Administrative writes require a browser session.
- Missing/invalid identity returns 401; denied scope returns 403; invalid/expired one-time tokens return 400; state conflicts return 409; invalid input returns 422. Rate limits return 429 with Retry-After.
- Default authentication limits are 30 requests/minute per direct peer, five login attempts/minute per normalized account, and three registration/verification-resend/reset/change requests/hour per subject. Database counters persist failed attempts across API processes. Proxy/IP policy and load sizing require production review.

See the generated [OpenAPI contract](../../contracts/openapi.json) for all 32 operations. Errors and authenticated responses use Cache-Control: no-store. Access logging is disabled in the documented Uvicorn command to keep token-bearing URLs out of request logs; tokens belong in bodies/headers, not backend query strings.

## Docker mail capture

After starting the optional stack with .env.docker:

```powershell
docker compose --env-file .env.docker -f infra/docker/compose.yaml --profile mail run --rm --no-deps mail-worker
```

Messages are retained in this stack's mail-data volume at /app/local-data/mail. The worker runs as UID 10001, uses the runtime database role, and has no external transport. To copy local messages for review, create a stopped mail-worker container, copy /app/local-data/mail into an ignored local-data directory, then remove only that container. Do not publish the volume or messages.

## Remaining release boundaries

TRACKING_ENVIRONMENT=production currently fails startup because an approved external mail adapter is required. Local capture does not establish internet delivery or production readiness. Hosting, TLS/proxy policy, retention/cleanup of sessions, counters and mail, load tests, monitoring, email delivery verification, and social sign-in configuration remain their respective review gates.

The API uses five request connections plus two independent security-event/rate-limit connections per process, with no overflow and a two-second checkout timeout. This avoids requests exhausting the same pool they need for independent security commits. Capacity must be sized across all processes before deployment.

The shared scope resolver and cache partition helper support later jobs, reports, and exports. Those consumers must resolve live authorization before using a queued actor or cached result; their implementation and end-to-end tests remain in their own specifications. There are no finance data endpoints in this slice.
