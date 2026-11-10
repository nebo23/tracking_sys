# Backend verification
Unit tests cover configuration isolation, secret redaction, health behavior under database failure, missing/mismatched schema revisions, and engine cleanup. Specification 003 adds the data-class registry check (metadata and migrated schema) and log allowlist cases, including real uvicorn servers in child processes.

The suite covers unit/contract cases and real PostgreSQL cases; see the latest evidence file for the current count and result. D-022 adds numeric verification, Google sign-in with a controlled provider substitute (no live Google calls), Gmail transport substitutes, outbox expiry, and 0004 migration/privilege cases. It covers HTTP authentication, email capture/retry, sessions/tokens/CSRF, invitations, service credentials, live scope resolution, tenancy isolation, audit atomicity, migration recovery, runtime grants, and concurrency. Integration setup refuses to run unless:
- TRACKING_RUN_DB_TESTS=1 is explicitly set.
- The selected database is tracking_foundation_test at 127.0.0.1:55433.
- Only known foundation/002 tables exist, and all application tables are empty before the test session starts.

All seeded identities are synthetic. Tests remove only fixtures created within that guarded disposable environment. Never point them at tracking_sys. Actual future job/export/cache consumers still require their own end-to-end tests; this suite verifies their shared live scope and cache partition contract. Email tests write to temporary local directories, never external mailboxes.

## Unit tests
Run from backend/:
```powershell
..\.venv\Scripts\python.exe -m pytest -m "not integration" -q
```

## Disposable PostgreSQL integration environment
Run from the repository root. The following uses .env.docker credentials, a separate Compose project and port, and restores the caller's environment afterward. It does not use the owner's native tracking_sys connection.

```powershell
$previousName = $env:TRACKING_DATABASE_NAME
$previousPort = $env:TRACKING_DATABASE_PORT
$previousTestFlag = $env:TRACKING_RUN_DB_TESTS
try {
    $env:TRACKING_DATABASE_NAME = "tracking_foundation_test"
    $env:TRACKING_DATABASE_PORT = "55433"
    $env:TRACKING_RUN_DB_TESTS = "1"
    docker compose --env-file .env.docker -f infra/docker/compose.yaml -p tracking-system-foundation-test up -d --wait database
    if ($LASTEXITCODE -ne 0) { throw "Test database startup failed." }
    @'
import os
import subprocess
import sys
from dotenv import load_dotenv

load_dotenv(".env.docker", override=True)
os.environ.update(
    TRACKING_DATABASE_HOST="127.0.0.1",
    TRACKING_DATABASE_PORT="55433",
    TRACKING_DATABASE_NAME="tracking_foundation_test",
    TRACKING_RUN_DB_TESTS="1",
)
raise SystemExit(subprocess.run(
    [sys.executable, "-m", "pytest", "-m", "integration", "-q"],
    cwd="backend",
).returncode)
'@ | .\.venv\Scripts\python.exe -
    if ($LASTEXITCODE -ne 0) { throw "Integration verification failed." }
} finally {
    docker compose --env-file .env.docker -f infra/docker/compose.yaml -p tracking-system-foundation-test down --volumes
    $env:TRACKING_DATABASE_NAME = $previousName
    $env:TRACKING_DATABASE_PORT = $previousPort
    $env:TRACKING_RUN_DB_TESTS = $previousTestFlag
}
```

The cleanup deletes only the explicitly named disposable test project's volume. Do not substitute the normal development project name. No real customer data belongs in this environment.
