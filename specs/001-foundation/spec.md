# 001-foundation — Project foundation and environment
Status: Draft; implementation is not approved. Level: L1. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER stack. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Prepare a future FastAPI/PostgreSQL/Docker scaffold, configuration and dependency management, a migration baseline, health/readiness endpoints, logging, and a CI plan.

## Out of scope
Business features, cloud deployment, or selecting an ORM, queue, or React toolchain without an owner decision.

## Acceptance criteria
1. After tool approval, a single setup guide starts the project on a clean machine with a disposable database.
2. A forward migration and documented rollback or recovery procedure work on synthetic data.
3. Health responses expose no secrets; readiness fails when a required dependency is unavailable.
4. Local Python project dependencies install only inside a project virtual environment; backend/requirements.txt declares approved versions. React dependencies remain local to the frontend project. Container builds install from dependency manifests without copying the host virtual environment (D-011).

## Required design contracts
Configuration schema, health/readiness contracts, schema version, and tool ADRs; pin versions after compatibility review.

## Dependencies and open decisions
Dependencies: [000-discovery](../000-discovery/spec.md)

Open decisions: Q-004, Q-009, Q-013. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
