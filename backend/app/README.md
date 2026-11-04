# Application
- config.py: validated runtime/separate migration settings, auth secrets, and development-only mail.
- database.py: bounded PostgreSQL connections, metadata, and revision-aware readiness.
- security.py: Argon2id, token hashing, email normalization, and CSRF helpers.
- main.py: FastAPI factory, lifespan, error handlers, CORS, and health endpoints.
- api/: identity-derived authorization, schemas, auth/tenant routes, and request controls.
- models/: approved tenancy/auth/access entities.
- services/: current membership/grant policy, audit, sessions, tokens, invitations, keys, and mail.
- mail_worker.py: local delivery entry point; no external sending.

Actor identity comes from authenticated cookies or scoped service credentials. HTTP inputs never choose actor IDs. Runtime scope resolution must be repeated before later queued jobs, cache reads, or exports. Those consumers and social/revenue endpoints remain future specifications. See the [walkthrough](../../docs/engineering/authentication.md).
