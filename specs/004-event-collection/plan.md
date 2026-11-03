# Plan: 004-event-collection
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Define a versioned event envelope, limited-trust public ingestion, authenticated server ingestion, webhooks, deduplication, UTM/click IDs, bot/internal traffic filtering, and backend event diagnostics.

## Design before implementation
- EventEnvelope v1, idempotency scope, public/trusted credentials, and quarantine, retry, and dead-letter contracts.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-002, Q-004, Q-012.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] The same event_id delivered through browser and server paths is counted once within a client, using an explicit policy for preferring the more trusted source.
- [ ] An identical event_id in another client does not suppress that client's data; conflicting payloads for the same scoped ID are recorded as conflicts.
- [ ] Invalid signatures, oversized payloads, and invalid timestamps are rejected; duplicates are safe and 429 responses support retry.
- [ ] Late arrivals retain occurred_at and received_at and update reports without double counting.
- [ ] Denied consent blocks disallowed field collection, and personally identifiable information does not appear in logs.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
