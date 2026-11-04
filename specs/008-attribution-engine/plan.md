# Plan: 008-attribution-engine
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Propose First Click, Last Click, and Linear models with configurable lookback windows, direct/unknown rules, model versions, reprocessing, and refund handling.

## Design before implementation
- AttributionRun, ModelVersion, CreditAllocation, and EvidenceClass; distinguish lead credit from revenue credit.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-007.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] For touchpoints A then B and revenue of 100, the approved models produce First: A=100; Last: B=100; Linear: A=50 and B=50.
- [ ] With no eligible touchpoint, unknown receives 100; total allocated credit equals eligible net revenue exactly after rounding.
- [ ] Fixtures define expected results for window boundaries, timezones, timestamp ties, refunds, and late events.
- [ ] Recalculating identical inputs with the same model version produces identical results; model changes preserve history.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
