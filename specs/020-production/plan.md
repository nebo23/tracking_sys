# Plan: 020-production
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Prepare staging and then production after hosting approval, including secrets, TLS/DNS, migrations, backup/restore, monitoring, alerts, runbooks, rollback, and phased rollout.

## Design before implementation
- Runbooks, release manifest, rollback plan, and operational ownership; configure CI/CD only after repository creation.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-003, Q-004, Q-011, Q-012; hosting and production approval.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

After repository authorization, combine slices for small changes or separate providers into individual PRs. Every PR must contain a reviewable change; no push is authorized now.

## Validation
- [ ] An actual restore in an isolated environment meets approved RPO/RTO targets and reapplies deletion controls.
- [ ] Deployment, rollback, and migration recovery exercises preserve event and payment data.
- [ ] Alerts cover worker lag, failed synchronization, rejected webhooks, quotas, cost, errors, and storage.
- [ ] Kill switches disable a specific connector, conversion delivery, or ingestion path while preserving tenant isolation.
- [ ] Launch requires provider approvals, budget, privacy decisions, and explicit owner sign-off.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
