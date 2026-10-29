# Plan: 000-discovery
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Unify the product definition, review the market and source PDF, define a launch capability matrix covering social analytics and attribution, and agree on initial test data and access costs.

## Design before implementation
- Scope document and launch capability matrix; no endpoints.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001 through Q-014.

## Proposed review slices
1. Review the research and complete source traceability.
2. Agree on the launch capability matrix, initial workflows, and access/cost evidence.
3. Record approved and deferred decisions; present specification 000 for owner review.

This discovery stage is documentary. Implementation belongs to later approved specifications.

## Validation
- [ ] All 109 source features and 16 ideas have a source reference, status, and proposed place in the plan.
- [ ] The owner explicitly approves mandatory launch account types, initial lead and revenue sources, and the agency/client model.
- [ ] The decision register records deferred items and reasons without silently changing scope.

## Rollout and recovery
No deployment is involved. Preserve source requirements and record changes to decisions.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
