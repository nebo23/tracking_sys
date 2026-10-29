# Plan: 019-quality-security
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Verify end-to-end workflows, security, performance under agreed load, failure recovery, data reconciliation, dependencies, and owner acceptance testing.

## Design before implementation
- A test evidence matrix; instrumentation starts in earlier specifications, while this stage verifies the complete system.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-004, Q-011, Q-012.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

After repository authorization, combine slices for small changes or separate providers into individual PRs. Every PR must contain a reviewable change; no push is authorized now.

## Validation
- [ ] A content-to-visit-to-lead-to-payment-to-refund journey is displayed alongside social data in two isolated agencies.
- [ ] Replaying events/jobs after a crash does not duplicate counts or money; one failed connector does not disable others.
- [ ] Evidence demonstrates the agreed load and service objectives; performance targets are not invented.
- [ ] Consent, revocation, export, deletion, backups, restoration, and the authorization matrix are actually tested.
- [ ] Critical defects are resolved or block release with documented evidence; owner acceptance testing is recorded.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
