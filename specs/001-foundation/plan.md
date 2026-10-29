# Plan: 001-foundation
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Prepare a future FastAPI/PostgreSQL/Docker scaffold, configuration and dependency management, a migration baseline, health/readiness endpoints, logging, and a CI plan.

## Design before implementation
- Configuration schema, health/readiness contracts, schema version, and tool ADRs; pin versions after compatibility review.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-004, Q-009, Q-013.
- Apply D-011: create an isolated Python virtual environment, maintain approved versions in backend/requirements.txt, keep frontend packages local, and install container dependencies from manifests.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

After repository authorization, combine slices for small changes or separate providers into individual PRs. Every PR must contain a reviewable change; no push is authorized now.

## Validation
- [ ] After tool approval, a single setup guide starts the project on a clean machine with a disposable database.
- [ ] A forward migration and documented rollback or recovery procedure work on synthetic data.
- [ ] Health responses expose no secrets; readiness fails when a required dependency is unavailable.
- [ ] Local Python project dependencies install only inside a project virtual environment; backend/requirements.txt declares approved versions. React dependencies remain local to the frontend project. Container builds install from dependency manifests without copying the host virtual environment (D-011).

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
