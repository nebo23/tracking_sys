# Plan: 009-connector-runtime
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Manage OAuth connection lifecycles, encrypted credentials, synchronization scheduling/workers, cursors/checkpoints, quotas and cost budgets, backfill, retries, and webhook verification.

## Design before implementation
- Connection, SyncRun, Checkpoint, Capability, ProviderError, and UsageRecord; keep the runtime contract independent of individual platforms.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001, Q-004, Q-009, Q-010.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

After repository authorization, combine slices for small changes or separate providers into individual PRs. Every PR must contain a reviewable change; no push is authorized now.

## Validation
- [ ] OAuth callbacks validate state and reject replay; tokens appear in neither the browser nor logs, and PKCE applies where required by the flow.
- [ ] Expired or revoked tokens produce an explicit disconnected state and stop affected ingestion without disrupting other clients.
- [ ] 429 responses respect provider backoff; 401 responses trigger reconnection; crash recovery resumes without duplicate records.
- [ ] Every connection exposes explicit metric availability, last synchronization, historical coverage, and cost states.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
