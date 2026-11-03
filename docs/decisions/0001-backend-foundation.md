# ADR 0001: Backend and database foundation
Date: 2026-10-29. Status: accepted for specification 001 through D-013 and D-014.

## Decision and authority
The owner authorized starting backend/database implementation using the existing specification sequence, then explicitly approved PostgreSQL 18, SQLAlchemy 2.x, Alembic, and Psycopg 3. This is a foundation only. It does not approve business schemas, authentication design, frontend implementation, production infrastructure, or upload.

Python 3.12 is retained to use the available local interpreter. Direct package versions are recorded in [requirements.in](../../backend/requirements.in); complete runtime versions and hashes are in [requirements.txt](../../backend/requirements.txt). Supporting settings/server/testing tools are isolated in the project environment. Current Starlette recommends httpx2 for its test client, which is used in development requirements.

## Implementation choices
- A synchronous SQLAlchemy engine with Psycopg 3 keeps the initial connection and migration path small. FastAPI runs synchronous health handlers outside its event loop. This does not decide the architecture of future background jobs.
- A public liveness endpoint checks the process. Readiness additionally requires PostgreSQL access and the exact Alembic head. A missing or different revision returns 503.
- Connection, statement, lock, and pool-wait timeouts are bounded. Error responses and application logs do not include database exception details or configuration values.
- A one-shot migration service uses separate credentials and must succeed before the API starts. The API never applies schema changes automatically.
- The runtime role is neither a superuser nor a schema creator and cannot update the migration-version table. The migrator can create schema objects but is not a superuser or BYPASSRLS role.
- The baseline establishes Alembic version control only. No agency, client, lead, payment, or revenue table exists.
- Compose is local development infrastructure. API/database ports bind to loopback; images are pinned by digest. Production backups, high availability, authentication, and deployment remain later specifications.
- D-015 selects the owner's native tracking_sys database on port 5432 for local development from .venv. The root .env configures that connection; optional Compose uses a separate .env.docker and database tracking_local. Both modes retain separate runtime and migration roles.
- The official PostgreSQL 18 image uses the /var/lib/postgresql volume mount. Initialization runs only for a new data directory; changing environment passwords does not rotate existing roles.

## References checked
- [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/)
- [FastAPI settings](https://fastapi.tiangolo.com/advanced/settings/)
- [SQLAlchemy PostgreSQL/Psycopg](https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)
- [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [PostgreSQL version policy](https://www.postgresql.org/support/versioning/)
- [Official PostgreSQL image](https://hub.docker.com/_/postgres)

Version metadata and compatibility were checked against PyPI before locking dependencies. Local installation and verification evidence belong in the active specification rather than implying provider or production readiness.
