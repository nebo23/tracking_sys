# Plan: 016-analytics-reporting
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Provide query APIs that clearly present social metrics alongside journey/revenue data, filters, leaderboards, freshness, exports, and proposed basic reports.

## Design before implementation
- Read models, aggregation provenance, and report snapshot schemas; identify non-additive metrics explicitly.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001, Q-006, Q-007, Q-011.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Every report enforces tenant, client, and field permissions, including exports and background generation.
- [ ] Social metrics show platform definitions, ranges, and freshness; revenue shows currency, model, attribution window, and evidence.
- [ ] Pagination, filters, date boundaries, timezones, and comparisons match reference fixtures.
- [ ] Partial synchronization, unsupported metrics, and currency mismatches are not displayed as zero or complete totals.
- [ ] Export URLs are short-lived and authorized; client deletion invalidates accessible reports according to policy.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
