# Local backend and database setup
Updated: 2026-10-30. Scope: foundation and approved specification 002, authorized by D-013 through D-019.

Current target schema: revision 0004_identity, with six tenancy tables, ten auth/access tables, and three D-022 identity/verification tables. Native tracking_sys received the owner-approved additive 0004 rollout on 2026-11-04. See [current verification evidence](../../specs/002-tenancy-access/auth-evidence.md) for the observed native state and [authentication guide](authentication.md) for registration, sessions, local mail, invitations, and service keys. Existing health endpoints are unchanged.

## Requirements
Use Python 3.12 and the owner's existing PostgreSQL 18 installation. The selected development database is tracking_sys on 127.0.0.1:5432. pgAdmin manages this PostgreSQL server; the application connects directly to PostgreSQL. Docker Desktop and Compose are required only for the optional container stack.

Python packages belong only in the project .venv or a container. Frontend packages are not required for this specification. Do not install application packages globally.

## 1. Create the isolated Python environment
Run from the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r backend/requirements-dev.txt
```

Activation is optional when the environment's executable is invoked explicitly. On POSIX systems, use python3 to create the environment and .venv/bin/python for subsequent Python commands.

Runtime requirements are locked in backend/requirements.txt. Development requirements add pytest, the Starlette-compatible httpx2 test client, and Ruff. The .in files declare direct dependencies; generated .txt files pin transitive versions and hashes.

## 2. Prepare the native database roles
On the owner's current workstation, this step is complete: tracking_app and tracking_migrator have matching generated passwords in .env, the baseline migration is applied, and both connections are verified. The native server reports PostgreSQL 18.4. The administrator connection URL was removed from the runtime password field and is not retained in project configuration. Do not rerun role creation on this provisioned server.

The following instructions are for initial provisioning on another workstation:

The owner has already created tracking_sys. In pgAdmin, open Query Tool for that database as its administrator and run [local-roles.sql](../../infra/postgres/local-roles.sql). This provisions the same separate tracking_app and tracking_migrator roles used by the container foundation. It does not create business tables or change existing role passwords.

The script refuses a different database or PostgreSQL major version. Existing role names cause a transaction failure; execute ROLLBACK and inspect their ownership and privileges before proceeding. Do not drop or reset existing roles to work around this guard.

Refresh Login/Group Roles in pgAdmin. Open Properties > Definition for each new role and set a distinct password. Enter those same values in the ignored root .env:

```dotenv
TRACKING_DATABASE_HOST=127.0.0.1
TRACKING_DATABASE_PORT=5432
TRACKING_DATABASE_NAME=tracking_sys
TRACKING_DATABASE_USER=tracking_app
TRACKING_DATABASE_PASSWORD=
TRACKING_MIGRATION_USER=tracking_migrator
TRACKING_MIGRATION_PASSWORD=
TRACKING_API_PORT=8000
```

On another workstation, copy .env.example to .env without overwriting existing configuration, then fill its blank password fields. Each password field contains only that role's password, not a postgresql:// connection URL. Host, port, database, and user are separate fields. Use single-quoted dotenv values for passwords containing #, $ or whitespace. Passwords belong only in local configuration and the PostgreSQL roles, never in chat, committed SQL, or alembic.ini. An administrator password is not required by the API.

Changing .env does not set or rotate a PostgreSQL role password. The matching roles and passwords must exist in PostgreSQL before connection can succeed.

## 3. Migrate and run from .venv
From the repository root, after configuring both database passwords and the independent keys described in the [authentication guide](authentication.md):

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw "Database migration failed; do not start the API." }
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log
```

The baseline creates Alembic's version table and grants runtime read access. Revision 0002_tenancy adds the six approved access-model tables; 0003_auth adds the approved authentication tables and nullable email verification timestamp; 0004_identity adds Google identities, OAuth transactions, verification challenges, and mail_outbox.expires_at (D-022). Existing identities are not automatically verified. Models derive from app.database.Base and are registered through app.models in migration metadata. Further model/table changes go through reviewed Alembic migrations in their approved specifications; the API does not create tables automatically.

Settings locate the root .env independently of the working directory. SQLAlchemy builds the connection URL from separate fields, so password punctuation does not require manual URL encoding.

After successful startup:
- API documentation: http://127.0.0.1:8000/docs
- Liveness: http://127.0.0.1:8000/health/live
- Readiness: http://127.0.0.1:8000/health/ready

Readiness must return 200 after database connection and migration verification. Listener availability alone does not verify credentials, database existence, or schema readiness. Use Ctrl+C to stop the local Uvicorn process.

## 4. Optional self-contained Docker stack
The optional stack has its own database tracking_local on port 55432. It does not connect to or migrate the owner's native tracking_sys database. Stop the local Uvicorn process before starting the container API because both use port 8000.

The existing Docker credentials have been preserved in ignored .env.docker. For a new setup only, the following command creates that file with three distinct random passwords and independent authentication/mail keys without printing them. It refuses to replace an existing file.

```powershell
@'
from pathlib import Path
import secrets
from cryptography.fernet import Fernet

path = Path(".env.docker")
if path.exists():
    raise SystemExit(".env.docker already exists; preserve its credentials.")
content = Path(".env.docker.example").read_text(encoding="utf-8")
for name in (
    "TRACKING_DATABASE_PASSWORD",
    "TRACKING_MIGRATION_PASSWORD",
    "TRACKING_POSTGRES_PASSWORD",
):
    content = content.replace(name + "=\n", name + "=" + secrets.token_hex(24) + "\n")
content = content.replace("TRACKING_AUTH_SECRET=\n", "TRACKING_AUTH_SECRET=" + secrets.token_hex(32) + "\n")
content = content.replace("TRACKING_MAIL_ENCRYPTION_KEY=\n", "TRACKING_MAIL_ENCRYPTION_KEY=" + Fernet.generate_key().decode() + "\n")
content = content.replace("TRACKING_OTP_SECRET=\n", "TRACKING_OTP_SECRET=" + secrets.token_hex(32) + "\n")
path.write_text(content, encoding="utf-8")
'@ | .\.venv\Scripts\python.exe -
```

Keep .env and .env.docker private; Git and the Docker build context exclude them. Compose uses the administrator password only to initialize its PostgreSQL container. The API and local mail worker receive the runtime password and auth/mail keys; the migration service receives only its migration password, and the optional lifecycle runner only its own role password ([lifecycle guide](data-lifecycle.md)).

Local Compose provisions the fixed roles tracking_app and tracking_migrator. Do not change the role names independently of the initialization contract. Changing passwords in .env.docker does not change roles inside an existing database volume; use a reviewed credential rotation procedure.

```powershell
docker compose --env-file .env.docker -f infra/docker/compose.yaml up --build -d
docker compose --env-file .env.docker -f infra/docker/compose.yaml ps -a
```

The database becomes healthy before the migration job runs. The API starts only after that job succeeds. PostgreSQL 18 stores its named volume at /var/lib/postgresql in this configuration, following the official image layout.

Default local endpoints:
- API documentation: http://127.0.0.1:8000/docs
- Liveness: http://127.0.0.1:8000/health/live
- Readiness: http://127.0.0.1:8000/health/ready
- PostgreSQL: 127.0.0.1:55432, database tracking_local

Both published ports bind to the loopback interface. These are local development services, not a production deployment.

To publish the API on another port, set TRACKING_API_PORT for the Compose command, for example 18002. Compose then forwards matching default allowed origins for that port, so Swagger at http://127.0.0.1:18002/docs can register and log in. If the API or frontend is reached through any other origin, set the complete TRACKING_ALLOWED_ORIGINS JSON list in .env.docker; see the [Docker notes](../../infra/docker/README.md). Origin and CSRF checks are never disabled to work around a mismatch.

## 5. Validate
```powershell
.\.venv\Scripts\python.exe -m ruff check backend/app backend/migrations backend/tests
.\.venv\Scripts\python.exe -m ruff format --check backend/app backend/migrations backend/tests
Push-Location backend
try {
    ..\.venv\Scripts\python.exe -m pytest -m "not integration" -q
} finally {
    Pop-Location
}
```

Real PostgreSQL migration tests require an isolated database named tracking_foundation_test. Never run downgrade/recovery tests on tracking_sys. See [test guidance](../../backend/tests/README.md). A skipped integration test is not a pass.

## Dependency updates
Use the installed uv tool to regenerate lock files after reviewing changes:

```powershell
uv --no-cache pip compile backend/requirements.in --python-version 3.12 --universal --generate-hashes --output-file backend/requirements.txt
uv --no-cache pip compile backend/requirements-dev.in --constraint backend/requirements.txt --python-version 3.12 --universal --generate-hashes --output-file backend/requirements-dev.txt
uv --no-cache pip sync --python .venv/Scripts/python.exe --require-hashes backend/requirements-dev.txt
```

Recheck compatibility and relevant tests after an update. Container images are pinned by digest; update them deliberately rather than relying on a changing tag. Do not copy .venv or node_modules into images.

## Shutdown and recovery
```powershell
docker compose --env-file .env.docker -f infra/docker/compose.yaml down
```

This removes this project's containers/network while preserving its database volume. Do not add --volumes for the development database unless its deletion is explicitly intended. Do not use global Docker cleanup commands.

For migration recovery, inspect the current revision and review the migration before choosing a forward fix or downgrade. The foundation baseline creates only Alembic's version table and grants runtime SELECT access; it has a tested reversible path on a disposable database. Future migrations require their own data-preservation review.

## CI plan
After owner review and upload approval, a repository workflow can run dependency installation, Ruff, unit tests, and PostgreSQL integration tests against a fresh disposable service. Use synthetic credentials and data. No cloud hosting, external account, CI secret, or deployment has been configured by this specification.
