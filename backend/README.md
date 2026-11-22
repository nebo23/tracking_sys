# Backend
FastAPI, PostgreSQL 18, SQLAlchemy 2, Alembic and Psycopg 3 (D-013, D-014), with the specification slices merged so far and Spec 015 in PR 13. The migration head is `0025_whatsapp` (63 application tables); the generated API contract is [contracts/openapi.json](../contracts/openapi.json) (124 operations across 102 paths, including the Spec 016-A report routes on `codex/spec-016-analytics-reporting`).

- `app/api/`: HTTP routes, schemas, identity dependencies and request controls (body bounds, rate limits, CORS for public collection routes).
- `app/models/`: tenancy and authentication (002), collection and consent (004), links (005), connectors (009-011), advertising (014), revenue evidence, payments, integrations, CRM and WhatsApp (015).
- `app/services/`: the scoped services behind the routes, including access resolution, collection and erasure, the connector runtime, advertising reads and delivery, the revenue ledger read, Paymob intake, bookings, CRM deals and WhatsApp referrals.
- `app/ledger/`, `app/attribution/`, `app/privacy/`, `app/payments/`, `app/integrations/`, `app/connectors/`: pure contracts and adapters (007-A, 008-A, 003, 015, 009-014).
- Commands: `app.mail_worker`, `app.lifecycle`, `app.connector_worker`, `app.connector_purge`, `app.whatsapp_binding` (D-070 operator binding) and the read-only feasibility tools.
- `migrations/`: revisions `0001` to `0025` with restricted runtime and lifecycle grants and guarded downgrades.
- `tests/`: unit and contract cases, and real PostgreSQL integration cases on the disposable service only; see [tests/README.md](tests/README.md) and each specification's evidence for counts and results.
- `requirements.in` and `requirements-dev.in`: direct dependencies; the corresponding `.txt` files pin versions with hashes.

Follow [setup](../docs/engineering/local-environment.md) and the guides in [docs/engineering](../docs/engineering/). Use `.venv` or containers and keep secrets in ignored configuration. Native `tracking_sys` was last documented at `0004_identity`; later migrations, live providers and deployment keep their separate owner decisions.
