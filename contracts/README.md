# Interface contracts
Technical contracts define the data exchanged between components; they are not legal contracts.

[openapi.json](openapi.json) describes 60 paths and 75 operations: health, email/password identity, numeric email verification, optional Google sign-in and linking, sessions/recovery, self-service account closure, agencies/clients/members/grants/audit, invitations, scoped read and ingest service credentials, specification 004 event collection (EventEnvelope v1 trusted intake, public collection, consent and self-erasure, generic signed webhooks, sources, forms, erasure requests, diagnostics, and event metadata), and specification 005 managed links (campaigns, content references, UTM templates, destination origins, custom domains with challenge and verification, managed links, the public `GET /r/{slug}` redirect, the optional envelope `link_id`, and the non-mutating public consent-state read). `HEAD /r/{slug}` behaves like GET without a body and is omitted from the document. An automated test compares the snapshot with the actual FastAPI routes. Public collection routes accept the JSON body as `text/plain` or `application/json` (other media types return 415) and are readable only by the origins registered for their browser source. Their CORS preflights are answered by middleware and do not appear as OpenAPI operations. Webhook routes document the `X-Tracking-Signature` header. See the [event collection guide](../docs/engineering/event-collection.md) and the [links and tracker guide](../docs/engineering/links-and-tracker.md).

The existing health contract remains public:
- GET /health/live: 200 with status ok; independent of database readiness.
- GET /health/ready: 200 with status ready when PostgreSQL and the migration revision are ready; otherwise 503 with status not_ready.

Responses disable caching and errors never echo credentials or raw database exceptions. Browser mutations require an allowed Origin and a session-bound X-CSRF-Token. Anonymous identity entry points require Origin. Service keys use Bearer on supported client reads; mixing cookies and Bearer is rejected. See the [auth guide](../docs/engineering/authentication.md) for lifecycle, limits, and local verification.

Regenerate the snapshot from backend/ after changing endpoint definitions:

```powershell
..\.venv\Scripts\python.exe -c 'import json; from pathlib import Path; from app.main import create_app; Path("../contracts/openapi.json").write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")'
```

Custom event schemas, provider-specific mappings, and later business contracts require the appropriate approved specification.
