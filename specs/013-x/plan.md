# Plan: 013-x
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Retrieve account/post metrics under verified paid access; distinguish public and private metrics, historical windows, and per-client budgets.

## Design before implementation
- Public/private metric distinction, provider cost ledger, and rate-limit metadata.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001, Q-004; X budget and entitlement.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

After repository authorization, combine slices for small changes or separate providers into individual PRs. Every PR must contain a reviewable change; no push is authorized now.

## Validation
- [ ] Credit and usage budgets cap collection and explain any stop to the user, preventing uncontrolled spending.
- [ ] Private-metric permissions and history are verified on an authorized account; data outside the permitted window is unavailable.
- [ ] Synchronization uses verified checkpoints and retry behavior without retrieving the entire history on every cycle.
- [ ] Recheck pricing definitions and access entitlements before release.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
