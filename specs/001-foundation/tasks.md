# Tasks: 001-foundation
Status: Implementation and verification complete locally; owner review pending.

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
- [ ] Obtain owner review and resolve any findings.
- [ ] Obtain explicit upload approval, then prepare the branch/commit, push, and PR.
- [ ] Record owner acceptance before starting specification 002.
