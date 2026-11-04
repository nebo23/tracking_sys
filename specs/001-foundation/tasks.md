# Tasks: 001-foundation
Status: Implementation verified and uploaded to the claude/development branch under D-020; formal acceptance and merge pending.

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
- [ ] Resolve any owner review findings.
- [ ] Record formal owner acceptance and the merge decision. Progression to specification 002 was authorized separately by D-016.
