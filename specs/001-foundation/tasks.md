# Tasks: 001-foundation
Status: Implemented and merged through PR 1 (`98747a2`, 2026-11-04), including F-01/F-02. Reconciled 2026-11-10 against GitHub and the dated evidence. Historical local handoff checklist entries are not the current implementation status.

- [x] Record authorization to begin backend/database foundation work (D-013).
- [x] Record approved PostgreSQL, SQLAlchemy, Alembic, and Psycopg choices (D-014).
- [x] Document which discovery decisions remain deferred.
- [x] Create an isolated .venv and pinned, hashed runtime/development requirements.
- [x] Implement configuration, connection management, structured logging, and health endpoints.
- [x] Establish the Alembic baseline without business tables.
- [x] Provision separate runtime and migration roles for local PostgreSQL.
- [x] Build and start the API, migration, and database containers.
- [x] Verify unit cases and real PostgreSQL upgrade/downgrade/recovery and permissions.
- [x] Verify actual database outage and recovery behavior.
- [x] Verify non-root execution, credential separation, and image exclusions.
- [x] Document setup, recovery, known limitations, and verification evidence.
- [x] Obtain explicit upload approval (D-020); commit and push to the claude/development working branch.
- [x] Resolve F-01 (Docker origins) and F-02 (purpose comments); see [dated evidence](evidence.md#review-amendments-f-01-and-f-02-2026-11-04).
- [x] Record the completed merge: [PR 1](https://github.com/nebo23/tracking_sys/pull/1), `98747a2`. Progression to 002 was authorized by D-016. This records repository acceptance, not production sign-off.
