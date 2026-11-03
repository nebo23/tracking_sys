# Plan: 021-growth-backlog
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Preserve the remaining source features and all 16 ideas; document each item's hypothesis, value, feasibility, data requirements, and cost before creating a separate specification.

## Design before implementation
- A proposed backlog only; no final API schemas or automatic implementation authorization.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: An explicit owner decision for each feature.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Every deferred item retains traceability and status; scope does not grow without an owner decision.
- [ ] Each new idea requires evidence, a bounded experiment, and a success measure before a roadmap commitment.
- [ ] Native mobile SDKs, replay, AI, SSO, payouts, and causal measurement receive separate specifications and security/privacy reviews when selected.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
