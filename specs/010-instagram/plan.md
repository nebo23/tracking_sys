# Plan: 010-instagram
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Connect supported accounts and retrieve profile/content insights under verified permissions; define metric catalogs, history, freshness, and a proposed read-only launch scope.

## Design before implementation
- A provider capability matrix is mandatory; do not invent final metric names.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001; exact Meta Insights metrics, access, and history require verification.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] An authorized test-account feasibility check proves account type, OAuth scopes, and actual fields before the final contract is designed.
- [ ] Account/media metrics match verified reference fixtures with period, source, and version; unsupported metrics are not displayed as zero.
- [ ] Access failure, content deletion, and disconnection are explicit and apply the retention policy.
- [ ] The interface makes no metric or historical-coverage claim unsupported by documentation and API responses.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
