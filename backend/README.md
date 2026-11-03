# Backend
FastAPI/PostgreSQL foundation and approved local specification 002 (D-013 through D-019).

- app/api/: authenticated HTTP routes, schemas, identity dependencies, and request controls.
- app/models/: six tenancy entities and ten authentication/access entities.
- app/services/: tenancy, authentication, invitations/keys, live scope resolution, and encrypted local mail.
- app/mail_worker.py: reusable bounded local mail-delivery command.
- migrations/: baseline, tenancy, and auth revisions with runtime grants and guarded downgrades.
- tests/: 115 unit/contract and real PostgreSQL HTTP, permission, concurrency, and migration checks.
- requirements.in and requirements-dev.in: direct dependencies; corresponding .txt files pin versions/hashes.

Follow [setup](../docs/engineering/local-environment.md) and the [auth walkthrough](../docs/engineering/authentication.md). Use .venv or containers; keep secrets in ignored configuration. [Current evidence](../specs/002-tenancy-access/auth-evidence.md) records results and limits. Owner review precedes upload/PR. Social sign-in, external email, React, and later business capabilities retain their gates.
