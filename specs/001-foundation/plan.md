# Plan: 001-foundation
Status: Implemented locally; awaiting owner review. Updated: 2026-10-29.

## Approved foundation
D-013 authorizes backend/database foundation work. D-014 selects PostgreSQL 18, SQLAlchemy 2.x, Alembic, and Psycopg 3. Remaining product, hosting, authentication, queue, and frontend decisions stay open.

## Implementation
1. Isolate dependencies in root .venv; maintain direct .in files and generated .txt files with fixed versions and hashes.
2. Build app/config.py, database.py, logging_config.py, and main.py. Use a factory and lifespan cleanup; do not connect or migrate at import time.
3. Keep /health/live independent of the database. Require database access and the exact Alembic head for /health/ready.
4. Provision runtime and migration roles separately. Grant runtime SELECT on alembic_version only; add no business tables.
5. Use a PostgreSQL service, one-shot migration service, and non-root API service in Compose. Keep services local and images pinned by digest.
6. Verify unit behavior, actual PostgreSQL migrations/permissions, and a live container database-outage/recovery exercise.
7. Document setup and evidence, then obtain owner review before upload.

## Validation completed
- Ten tests passed, including the PostgreSQL integration case.
- Ruff lint and format checks passed.
- Windows environment and Linux image dependency checks passed.
- Fresh database initialization, migration job completion, and API/database health were verified.
- Database outage produced live=200 and ready=503; recovery restored ready=200 without restarting the API.
- Runtime container UID, credential separation, and build-context exclusions were checked.

Exact evidence and remaining limits are recorded in [evidence.md](evidence.md).

## Recovery and review
The disposable test database was removed after verification. D-015 subsequently selected the owner's native tracking_sys database. The original Docker stack is stopped with its volume and credentials preserved. Native role provisioning, authenticated connections, and baseline migration are complete; in-process application health checks passed against the real database. Start Uvicorn from .venv when an HTTP listener is needed. Normal Compose shutdown preserves the development volume.

The baseline downgrade is only a migration-framework exercise. Future migrations require their own data-preservation review. No Git commit, push, PR, cloud deployment, or business schema is part of this delivery.
