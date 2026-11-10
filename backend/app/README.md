# Application
- config.py: validated runtime/separate migration settings, auth secrets, and development-only mail.
- database.py: bounded PostgreSQL connections, metadata, and revision-aware readiness.
- security.py: Argon2id, token hashing, email normalization, and CSRF helpers.
- main.py: FastAPI factory, lifespan, error handlers, CORS, and health endpoints.
- logging_config.py: allowlisted structured logs; registered events only, library records and exceptions reduced to safe diagnostics (specification 003-A2).
- data_policy.py: data-class registry for every stored column with end-of-life rule status (specification 003-A1); classification only.
- privacy/: specification 003 contract libraries (consent, collection minimization, deletion and tombstones, token envelope encryption, provider rules, restore journal); stateless. Specification 004 consumes consent, collection, deletion, and token envelope encryption.
- links/: specification 005 managed-link rules (destination, origin, hostname, slug, UTM precedence; policy.py) and custom-domain verification with injected DNS/TLS adapters (verification.py).
- collection/: specification 004 pure rules (EventEnvelope v1, minimization by purpose, form classes, fingerprints, traffic labels, webhook signatures) and the tombstone keyring.
- api/: identity-derived authorization, schemas, auth/tenant/collection routes, and request controls.
- models/: approved tenancy/auth/access entities, the D-027 collection, consent, and erasure tables, and the D-033 managed-link tables.
- services/: current membership/grant policy, audit, sessions, tokens, invitations, keys, mail, event admission/consent/erasure (collection.py), and managed-link administration, verification phases, and redirect resolution (links.py).
- mail_worker.py: local delivery entry point; no external sending.
- lifecycle.py: one bounded retention pass as the tracking_lifecycle role (specification 003-A3); the logic is in services/lifecycle.py.

Actor identity comes from authenticated cookies or scoped service credentials. HTTP inputs never choose actor IDs. Runtime scope resolution must be repeated before later queued jobs, cache reads, or exports. Those consumers and social/revenue endpoints remain future specifications. See the [walkthrough](../../docs/engineering/authentication.md) the [event collection guide](../../docs/engineering/event-collection.md), and the [links and tracker guide](../../docs/engineering/links-and-tracker.md).
