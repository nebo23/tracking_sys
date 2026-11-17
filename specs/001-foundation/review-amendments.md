# Foundation review amendments

Status: Owner-requested implementation handoff; application changes have not been made by this document. Prepared: 2026-11-04.

## Authority and delivery

The owner requested specification-specific amendment files, English explanatory comments, and correction of the findings raised during the joint review. See D-021 in the [decision register](../../docs/planning/decisions.md). The [tenancy handoff](../002-tenancy-access/review-amendments.md) is the entry point for Claude and links the complete package. No new amendment file is required for discovery: the walkthrough identified no specific discovery defect to add; its existing open decisions remain open.

Preserve owner edits and the existing repository. Work on `claude/development`, keep dependencies isolated, and use a disposable PostgreSQL database for integration and migration tests. Do not push, create or update a PR, merge, deploy, or change native data as part of preparing this handoff. Completed implementation slices must be checked and reviewed before a separately approved upload.

## F-01: Docker configuration fails to follow a changed API port

Type: Behavioral defect. Priority: P2. Source: `infra/docker/compose.yaml`, `backend/app/config.py`, and `backend/app/api/dependencies.py`.

Compose publishes `${TRACKING_API_PORT:-8000}` but does not forward an explicit configurable allowed-origin list or frontend origin. Defaults include loopback ports 8000 and 5173. Swagger opened on another published port sends that different Origin, and `require_origin` rejects registration or login with 403. A direct check of the current origin policy accepted port 8000 and rejected port 18002; a complete amended Compose flow has not been tested.

Required change:

- Provide documented `TRACKING_ALLOWED_ORIGINS` and `TRACKING_FRONTEND_ORIGIN` configuration through Compose and example configuration. A host `.env.docker` variable alone does not enter a container unless it is forwarded.
- Keep the actual API origin and intended frontend origin explicit. Use valid JSON for the settings list, and ensure Compose interpolation preserves its quoting. Document the default and an alternate-port example, including the need to set the allowed list when changing the published port.
- Keep worker settings consistent where they affect message links. Do not broaden origins to `*`, disable Origin/CSRF checks, trust arbitrary Host headers, or weaken non-loopback cookie rules.
- Add a regression that checks resolved non-default configuration and an allowed mutation from the configured alternate origin. An unrelated origin must still fail. Verify the actual disposable Compose path when Docker is available; report separately if only configuration/application tests were run.

## F-02: Explain the database foundation

Type: Documentation-only amendment. Add concise formal English `#` comments immediately above the relevant definition. Preserve existing useful docstrings and avoid duplicate prose.

| File and definition | Required explanation |
|---|---|
| `backend/app/database.py`: `Base` | Shared declarative model metadata; stable names for indexes and constraints. Naming rules do not create indexes or constraints by themselves. |
| `create_database_engine` | Construct an Engine with bounded pool, connect, statement, lock, and pool-wait settings. Connections are opened when needed; a pool size does not eagerly open that many connections. `pool_pre_ping` checks connection liveness. |
| `expected_revision` | Read the expected Alembic head from project migration files. It neither reads the applied database revision nor applies migrations. |
| `readiness_failure` | Check connectivity and exact recorded revision agreement; return a sanitized failure code or `None`. This does not verify every column, upgrade the schema, stop the process, or guarantee all application behavior. |
| `backend/app/config.py`: `DatabaseSettings` | Read and validate database configuration; explain the shared settings source and prefix. |
| `DatabaseSettings.model_config` | Explain the prefix, root-relative `.env`, UTF-8, ignored extra dotenv keys, and omission of input values from textual validation errors. Do not claim all structured error serialization is automatically redacted. |
| `DatabaseSettings.require_password` and its decorators | Pydantic calls the registered field validator during validation; `classmethod` supplies the class, not an instance. Reject blank/space-only secrets, return the original value, and do not silently trim a valid password. |
| `DatabaseSettings.database_url` | Compute a structured SQLAlchemy URL when accessed; extract the secret only to supply credentials. This property does not connect to PostgreSQL. |
| `MigrationSettings` | Use separate migrator credentials/aliases and a longer per-statement timeout. This is not a database uptime allowance and does not grant runtime schema privileges. |

Also explain the purpose of other maintained foundation modules, named classes, and functions in `backend/app/main.py` and `backend/app/logging_config.py`. In particular, explain readiness status versus liveness, application lifetime and engine disposal, and sanitized exception handling. Keep comments tied to actual behavior after the fixes; do not describe intended behavior as already implemented.

## Acceptance and evidence

- [ ] F-01 passes alternate-origin acceptance and unrelated-origin rejection without security-policy bypasses.
- [ ] Required database/configuration definitions have accurate English comments.
- [ ] The documentation-only slice leaves executable Python ASTs unchanged; no new tests are needed solely to mirror comments.
- [ ] Relevant settings/health/contract tests and Ruff pass for behavioral changes; `git diff --check` passes.
- [ ] Record commands, actual outcomes, unrun checks, and limitations in the existing foundation evidence rather than inventing a new passing-test count.
- [ ] Native `tracking_sys`, owner configuration, and pre-existing edits remain preserved. Present the completed slice for owner review before upload.
