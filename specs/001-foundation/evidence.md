# Foundation verification evidence
Date: 2026-10-29. Scope: specification 001 only. Status: passed locally; owner review pending.

This is historical foundation evidence. The subsequent approved 002-A upgrade advances tracking_sys to 0002_tenancy and adds six empty tables; see [current verification evidence](../002-tenancy-access/evidence.md).

## Environment and dependencies
- Host interpreter: Python 3.12.4 in the project .venv; sys.prefix differs from sys.base_prefix.
- Runtime image interpreter: Python 3.12.16.
- PostgreSQL: 18.6 official image, pinned by digest.
- Docker Engine/CLI: 29.5.3. Compose: 5.1.4.
- Runtime dependency versions and download hashes: [requirements.txt](../../backend/requirements.txt).
- Development dependency versions and hashes: [requirements-dev.txt](../../backend/requirements-dev.txt).
- Dependency installation succeeded in the Windows virtual environment and Linux image. pip check reported no broken requirements in both environments.

## Automated checks
| Check | Result |
|---|---|
| Ruff lint | Passed |
| Ruff formatting | Passed |
| Pytest including the PostgreSQL integration case | 10 passed in 1.82 seconds |
| Compose configuration validation | Passed |
| Image build with hashed requirements | Passed |
| Fresh PostgreSQL initialization | Passed |
| One-shot migration service | Exited with code 0 |
| API and PostgreSQL container health | Healthy |
| Local OpenAPI snapshot compared with the running API | Exact match |
| Project hygiene audit | 132 maintained files checked; no broken relative Markdown links, Arabic text, or local password values found |
| Git whitespace validation | Passed |

The full suite ran with TRACKING_RUN_DB_TESTS=1, database tracking_foundation_test, port 55433, and Compose project tracking-system-foundation-test. That isolated project and its volume were removed afterward.

## Actual migration and permission evidence
The integration case ran against PostgreSQL, not SQLite or a mock:
1. Verified the major version and refused databases containing business tables.
2. Migrated to base and observed readiness=503.
3. Upgraded to head twice and observed readiness=200.
4. Verified runtime is not superuser, CREATEDB, CREATEROLE, or BYPASSRLS.
5. Verified runtime cannot CREATE in public or UPDATE alembic_version; attempted version-table mutation was denied.
6. Downgraded to base and observed readiness=503.
7. Upgraded again and observed readiness=200.

Unit cases cover configuration validation, punctuation in passwords, separate migration credentials, missing/mismatched/multiple revisions, database errors, liveness independence, redacted responses, and engine disposal.

## Live container failure exercise
- Before stopping PostgreSQL: /health/live=200 and /health/ready=200.
- PostgreSQL stopped for this project only: /health/live=200 and /health/ready=503.
- PostgreSQL restarted and became healthy: /health/ready=200 without restarting the API.

The development stack was restored after this exercise. It was subsequently stopped during the D-015 switch to native PostgreSQL; its volume and credentials remain preserved.

## Runtime boundaries
Verified API UID 10001, absence of migration/admin passwords in the API environment, absence of /app/.env in the image, and ignored local .env/.venv paths. The API receives runtime credentials only. Generated passwords were not printed or committed.

## Workstation prerequisite repaired
Docker initially failed before starting its engine because its temporary runtime socket entries could not be accessed. With Docker stopped, the runtime directory was checked to contain only three empty socket entries, preserved as run.tracking-foundation-backup-20261029 under the user's Docker application-data directory, and recreated. Docker then started. Existing images, containers, volumes, and application settings were not deleted. This was a workstation prerequisite repair, not product code.

## Limits
No business tables, tenant isolation implementation, authentication, social API grants, production deployment, performance target, security certification, or production backup/restore claim is established. A second physical development machine has not been tested. The reversible baseline does not establish reversibility of future migrations.

No commit, push, or PR was created during this implementation. Owner review and upload approval remain pending under D-012.

## Native PostgreSQL configuration follow-up (D-015)
- The owner confirmed the existing database name as tracking_sys.
- Windows service postgresql-x64-18 is running. pgAdmin server metadata identifies localhost:5432; pg_isready confirmed that listener is accepting connections.
- Root .env targets 127.0.0.1:5432/tracking_sys. It initially had blank password fields; provisioning and matching passwords were completed in the follow-up below. Previous Docker credentials are preserved in ignored .env.docker.
- Dedicated-role provisioning SQL and the local setup guide are available for fresh installations. The completed native provisioning is recorded below.
- Existing configuration/health unit checks passed: 9 passed, 1 integration case deselected in 0.90 seconds. Ruff lint and formatting passed. The preserved Docker configuration validated successfully.
- Only this project's prior Docker stack was stopped, preserving its database volume and freeing the API port for native development. No native business data or schema was modified.
- Initial credential check after the owner's update: the runtime field contained a full administrator connection URL and the migration password was empty. Runtime authentication failed. This was corrected by the subsequent provisioning below; no password values were displayed.

### Completed native provisioning and verification
- The owner supplied administrator connection details and requested correction. Read-only checks confirmed tracking_sys on PostgreSQL 18.4, no existing project roles, no project role memberships, and no user tables.
- Created tracking_app and tracking_migrator with distinct generated passwords and restricted privileges. Saved only their matching credentials in ignored .env; the administrator URL/password is not retained there.
- Both roles connected successfully to 127.0.0.1:5432/tracking_sys. Neither has SUPERUSER, CREATEDB, CREATEROLE, or BYPASSRLS. Only tracking_migrator can create objects in public.
- Applied Alembic upgrade head. Verified revision 0001_foundation and exactly one public table, alembic_version. No business tables were created.
- FastAPI TestClient using the real native database returned /health/live=200 and /health/ready=200 with {"status":"ready"}. This was an in-process application check, not evidence of a persistent HTTP server on port 8000.
- No downgrade, data-deletion test, or Docker integration test ran against the owner's native database.
