# Plan: 006-identity-journey
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Represent anonymous visitors, leads, and customers; support deterministic identity linking, sourced event timelines, and auditable merge/unmerge actions.

## Design before implementation
- IdentityKey, Subject, IdentityLink, and Touchpoint; define normalization, versioning, and ambiguity policies.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-002, Q-008, Q-012.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Anonymous visits link to a verified identity only within the same client and under applicable consent.
- [ ] Shared or conflicting email addresses and phone numbers do not automatically merge people without an established policy.
- [ ] Switching users on a shared device does not silently transfer one person's visits to another.
- [ ] Merge/unmerge preserves provenance and recalculates attribution without losing the original evidence.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
