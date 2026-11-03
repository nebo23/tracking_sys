# Database migrations
Alembic tracks schema revisions using dedicated migration credentials. The API role only reads the revision table.

Run from the repository root using the project environment:

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini current
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

The initial 0001_foundation revision introduces no business tables. Alembic creates its own version table; the revision grants tracking_app SELECT access. A downgrade revokes that grant and returns to the base revision.

Only run the following recovery exercise on the dedicated disposable test database, after verifying its name and contents:

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini downgrade base
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

Do not treat a successful foundation downgrade as proof that later data migrations are reversible. Review future generated migrations, ownership/grants, locking, data loss, backfill, and recovery before execution. The API does not run migrations during startup.

Revision 0002_tenancy creates the six models approved in D-017. Composite keys prevent cross-agency grants and audit references; application services still enforce access for individual users. Runtime may append/read audit records but cannot update/delete/truncate them.

The 0002 downgrade takes exclusive table locks and refuses populated tables. Use a reviewed forward fix when data exists. Its upgrade and empty downgrade/recovery were tested on disposable PostgreSQL; tracking_sys received only the additive upgrade, with no sample records.

Revision 0003_auth implements D-019: ten authentication/access tables, nullable users.email_verified_at, expanded audit checks, and restricted grants. Runtime may insert identities and update their verification/timestamp columns, but cannot change user status. Security events remain append-only. Tokens and keys are stored as digests; queued mail payloads are encrypted.

The 0003 downgrade refuses non-empty auth tables, verified identities, or auth audit records under exclusive locks. Native tracking_sys is at 0003_auth with 16 empty application tables after the verified additive upgrade. See [current evidence](../../specs/002-tenancy-access/auth-evidence.md).
