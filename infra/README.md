# Infrastructure
Native PostgreSQL role provisioning is in postgres/local-roles.sql. The optional self-contained Docker foundation is in docker/. See [setup](../docs/engineering/local-environment.md) for the selected tracking_sys connection and separate Docker configuration.

Production hosting, deployment, monitoring, backup, restoration, and incident response remain subject to specification 020. Local Compose does not establish production readiness.
