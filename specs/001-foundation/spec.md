# 001-foundation — Project foundation and environment
Status: Implemented locally; awaiting owner review. Level: L1. Updated: 2026-10-29.

## Sources and authorization
The owner confirmed FastAPI, PostgreSQL, and Docker, then authorized beginning the backend/database foundation using the existing specification sequence (D-013). D-014 explicitly approves PostgreSQL 18, SQLAlchemy 2.x, Alembic, and Psycopg 3.

The remaining discovery decisions are recorded and deferred to the specifications they affect. They do not block this independent infrastructure foundation and are not implicitly approved.

D-015 selects the owner's native tracking_sys database for local development. The dedicated roles and matching private configuration are provisioned. Both authenticated connections, the baseline migration, and in-process application readiness are verified against native PostgreSQL 18.4; the earlier Docker verification is separate evidence.

## Implemented scope
- Isolated Python environment and pinned, hashed runtime/development requirements.
- Validated settings with separate runtime and migration credentials.
- FastAPI factory, structured application logs, liveness, and schema-aware readiness.
- SQLAlchemy/Psycopg connectivity with bounded connection, query, lock, and pool-wait timeouts.
- Alembic baseline and an actual upgrade/downgrade/recovery test.
- Local PostgreSQL and API containers, pinned images, loopback-only ports, and non-root API execution.
- Setup, migration, dependency-update, test, recovery, and future CI guidance.
- OpenAPI snapshot for the two health endpoints.

## Out of scope
Business tables and features, agency/client access control, authentication, jobs, social connectors, revenue logic, React, cloud deployment, GitHub workflow activation, push, PR, and merge.

## Acceptance criteria and evidence
1. A single setup guide reproduces the foundation using an isolated Python environment and fresh PostgreSQL storage. Verified on this workstation with fresh container images and a dedicated disposable test database; a second physical machine has not been tested.
2. Migration upgrade, repeated upgrade, downgrade to base, and upgrade recovery pass against PostgreSQL 18. The baseline creates only Alembic's version table.
3. Liveness remains available during database failure. Readiness returns 503 for unavailable PostgreSQL or a missing/mismatched schema, and returns 200 after recovery. Responses do not expose secrets.
4. Python dependencies remain in .venv or the container. Hashed requirements install successfully on Windows and Linux. No host environment is copied into images.
5. The runtime role cannot create persistent schema objects or update the migration version; neither runtime nor migrator is a PostgreSQL superuser or BYPASSRLS role.

See [verification evidence](evidence.md), [the implementation plan](plan.md), and [the foundation ADR](../../docs/decisions/0001-backend-foundation.md).

## Dependencies and decisions
Specification 000 supplied the requirements inventory and proposed sequence. D-013 permits foundation work while unresolved product decisions remain tracked. Q-009 is resolved only for the database tools in D-014; authentication, jobs, and React tooling remain open for their relevant stages. Q-004 production capacity/budget and optional team reviewer assignments in Q-013 are not required to operate this local foundation.

## Owner review
Implementation is available locally for review. D-012 still requires explicit owner approval before uploading or creating a PR. This specification is not owner-accepted and does not authorize advancing to specification 002.
