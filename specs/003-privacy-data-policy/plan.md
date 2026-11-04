# Plan: 003-privacy-data-policy
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Define consent contracts, data classes, masking before transmission, token encryption, retention, deletion, export, residency decisions, and integration authorization.

## Design before implementation
- ConsentRecord, DataClassPolicy, DeletionRequest, TokenSecretReference, and a provider-specific policy table.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-003, Q-012.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

Current slice plan (D-023, 2026-11-04), detailed in [design section 16](design.md#16-implementation-slices-and-status):
- 003-A1 data-class registry and 003-A2 log allowlist: implemented locally; see [evidence](evidence.md).
- 003-A3 credential-state lifecycle runner, 003-A4 mail expiry, and 003-A5 account closure and erasure: await the [decision packet](decision-packet-003a.md).
- 003-B consent and deletion contracts (with 004, 005, 014), 003-C provider rows and secrets (with 009-016), and 003-D restore verification (with 019, 020): proposed and dependent on later specifications.

## Validation
- [ ] Events that violate the approved consent policy enter neither prohibited storage nor an outbound delivery queue.
- [ ] Password and sensitive payment fields are excluded from form telemetry and logs. Log exclusion is implemented and tested (003-A2). Form telemetry waits for 004/005.
- [ ] Subject or connector deletion covers applicable raw data, derived data, caches, and exports, and prevents reintroduction through old event replay under the approved policy.
- [ ] Backup restoration reapplies deletion tombstones before making the service available.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
