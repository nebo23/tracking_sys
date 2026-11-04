# Specification 002-A verification evidence

Historical record. See [002-B/C/D evidence](auth-evidence.md) for the current schema and implemented authentication/access scope.
Date: 2026-10-29. Status: implemented and verified locally; owner review pending.
Authority: D-016/D-017 and the approved [design](design.md). This evidence covers 002-A only.

## Delivered
- Six SQLAlchemy entities: User, Agency, AgencyMembership, ClientWorkspace, ClientGrant, and AuditEvent.
- Migration 0002_tenancy with scoped composite foreign keys, role/status constraints, unique memberships, and restricted runtime grants.
- Internal tenancy services for agency/client operations, membership changes, explicit client/financial grants, and scoped audit reads.
- Database-backed access checks on each operation; unit-of-work transactions commit mutations and audit together.
- Agency-row locking serializes sensitive mutations and protects the final active Owner during concurrent membership changes.
- No new dependency, public identity creation endpoint, or business HTTP route was added.

## Automated verification
Final command: pytest -q using the project .venv with TRACKING_RUN_DB_TESTS=1.
Result: **51 passed in 14.00 seconds** (9 foundation unit cases and 42 PostgreSQL integration cases). Ruff lint and formatting passed.

The integration target was tracking_foundation_test on 127.0.0.1:55433, PostgreSQL 18.6, in the separately named tracking-system-foundation-test Compose project. Fixtures reject another host, port, database name, unknown schema, or pre-existing data before cleanup. All identities and tenants were synthetic.

After verification, the test container, network, and volume were removed after checking the volume's exact name and Compose project label. The native database and original development Docker volume were preserved.

Verified cases include:
- Cross-agency reads, lists, mutations, grant creation/revocation, membership changes, and audit access are denied by the services.
- Analyst and ClientViewer see only assigned clients; financial permission requires its own explicit grant. The same user can have a different role in another agency.
- Revocation, disabled identities/memberships, suspended agencies, and archived clients are rechecked even in an existing SQLAlchemy session.
- Admin cannot create/change Owner privileges. Two simultaneous Owner self-demotions produce one success and one protected rejection; an active Owner remains.
- Direct PostgreSQL writes cannot join a client or membership from another agency through composite foreign keys. Audit actor/client references also preserve agency scope.
- Runtime UPDATE/DELETE/TRUNCATE of audit events, changes to migration metadata or identities, and hard client deletion fail with insufficient privilege.
- Transaction and audit-constraint failures roll back the mutation and its audit records. Successful changes record only scoped identifiers/action codes.
- Model metadata matches the migrated database. Fresh upgrade, repeat upgrade, empty downgrade, and recovery succeed.
- Downgrade refuses a populated tenancy schema. Exclusive table locks keep the emptiness check and table removal atomic against writers.

## Native database upgrade
After tests passed, read-only preflight confirmed that tracking_sys still contained only alembic_version at 0001_foundation. Applied the approved additive upgrade using tracking_migrator on native PostgreSQL 18.4.

Observed:
- Current revision: 0002_tenancy.
- All six new tables exist and have zero rows; no fixtures were inserted into the owner's database.
- Alembic model comparison reports no differences.
- Runtime connects as tracking_app in UTC, may append/read audit events, and cannot update/delete them or mutate users.
- FastAPI TestClient connected to this native database and returned liveness=200 and readiness=200. This is an in-process application check, not evidence of a persistent HTTP listener.
- No downgrade, fixture cleanup, or data-deletion test ran against tracking_sys.

## Scope of the guarantee
Authorization is implemented at the internal service boundary. Trusted actor IDs in tests are not an HTTP authentication mechanism. Ordinary application database grants do not themselves provide row-level tenant isolation; RLS has not been implemented or claimed.

Authentication, sessions, registration, verification/recovery, invitations, API credentials, jobs, caches, exports, finance endpoints, React, and production deployment remain their respective later slices/specifications. The full specification 002 is not complete.

No commit, push, PR, email, external account change, or new package installation was performed. Upload approval remains pending under D-012.
