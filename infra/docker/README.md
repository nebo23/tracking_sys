# Local containers
- Dockerfile: pinned Python image, hashed runtime dependencies, non-root application user.
- compose.yaml: PostgreSQL 18, a one-shot migration service, FastAPI, and an optional local mail worker; loopback-only published ports.
- postgres/init-roles.sh: provisions separate runtime and migration roles on an empty database volume.

The build context excludes .env, .venv, Git metadata, tests, and unrelated project content. The PostgreSQL named volume is mounted at /var/lib/postgresql for the approved major version.

Use the [setup guide](../../docs/engineering/local-environment.md). Never use global Docker prune/reset commands to manage this project's environment.

Always pass --env-file .env.docker to this Compose stack. The root .env now configures the owner's native tracking_sys database for the Python virtual environment; it must not be used to initialize this separate container database.

The mail profile runs the reusable development worker using the runtime database role and separate encryption key. Its mail-data volume holds sensitive local .eml messages and is not an external email service. See the [auth guide](../../docs/engineering/authentication.md). The migration container does not receive authentication or mail secrets.

## Browser origins and alternate ports
Compose forwards TRACKING_ALLOWED_ORIGINS and TRACKING_FRONTEND_ORIGIN to the API and mail worker; a host or .env.docker variable alone does not enter a container unless it is forwarded. By default the allowed list contains the published API origin on 127.0.0.1/localhost at TRACKING_API_PORT plus the local frontend on port 5173, so changing TRACKING_API_PORT keeps Swagger mutations working from the new port. Set the complete JSON list in .env.docker when any other API or frontend origin is used, for example `TRACKING_ALLOWED_ORIGINS='["http://127.0.0.1:18002","http://127.0.0.1:5173"]'`. Wildcards, paths, and non-loopback origins with insecure cookies are rejected at startup. TRACKING_FRONTEND_ORIGIN sets the base origin of links in queued messages.
