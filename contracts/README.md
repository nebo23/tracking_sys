# Interface contracts
Technical contracts define the data exchanged between components; they are not legal contracts.

[openapi.json](openapi.json) describes 29 paths and 36 operations: health, email/password identity, numeric email verification, optional Google sign-in and linking, sessions/recovery, agencies/clients/members/grants/audit, invitations, and scoped service credentials. An automated test compares the snapshot with the actual FastAPI routes.

The existing health contract remains public:
- GET /health/live: 200 with status ok; independent of database readiness.
- GET /health/ready: 200 with status ready when PostgreSQL and the migration revision are ready; otherwise 503 with status not_ready.

Responses disable caching and errors never echo credentials or raw database exceptions. Browser mutations require an allowed Origin and a session-bound X-CSRF-Token. Anonymous identity entry points require Origin. Service keys use Bearer on supported client reads; mixing cookies and Bearer is rejected. See the [auth guide](../docs/engineering/authentication.md) for lifecycle, limits, and local verification.

Regenerate the snapshot from backend/ after changing endpoint definitions:

```powershell
..\.venv\Scripts\python.exe -c 'import json; from pathlib import Path; from app.main import create_app; Path("../contracts/openapi.json").write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")'
```

Future event schemas, provider mappings, pagination, authorization, and business contracts require the appropriate approved specification.
