# Plan: 004-event-collection
Status: Reviewable delivery plan prepared 2026-11-10. The [design](design.md) and [decision packet](decision-packet.md) require approval before implementation. No schema or dependency is authorized by this plan.

## Expected outcome
Define a versioned event envelope, limited-trust public ingestion, authenticated server ingestion, webhooks, deduplication, UTM/click IDs, bot/internal traffic filtering, and backend event diagnostics.

## Design before implementation
- EventEnvelope v1, idempotency scope, public/trusted credentials, and quarantine, retry, and dead-letter contracts.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-002, Q-004, Q-012.

## Proposed review slices
1. **004-A, approved contracts and migration design:** resolve C004-01 to C004-06; specify per-field classes/purposes, canonical fingerprinting, credential scopes and key custody. Review schema/FKs/indexes/grants/retention and OpenAPI proposals. Establish merged 003 baseline on a new branch.
2. **004-B, privacy persistence:** implement approved consent/subject receipt issuance and deletion/tombstone storage with shared client-lock ordering. Test cross-client substitution, expiry, withdrawal/deletion races and replay before exposing intake.
3. **004-C, trusted intake:** implement explicit events:write and one transactional event/receipt path, minimization, bounded validation, canonical deduplication/conflicts and trusted upgrades. Test database state, concurrency and rollback on synthetic fixtures.
4. **004-D, public/webhook paths:** reuse the same admission path with limited-trust routing, origin/abuse controls and generic signed webhook validation. Verify raw-body signatures, time windows, replay, no trust escalation and indistinguishable public outcomes. No live provider required.
5. **004-E, lifecycle and diagnostics:** apply approved payload/metadata retention, deletion targets, bot/internal rules, redacted pagination and financial-field restrictions. Test deduplication after payload expiry and key rotation. No React or broker is introduced.
6. **004-F, review evidence:** full unit/PostgreSQL suite, migration/role/data-policy/OpenAPI checks, forbidden-data absence, deterministic concurrency and documented local workload. Review final diff, obtain publication approval and owner acceptance; native/production rollout remains separate.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] The same event_id delivered through browser and server paths is counted once within a client, using an explicit policy for preferring the more trusted source.
- [ ] An identical event_id in another client does not suppress that client's data; conflicting payloads for the same scoped ID are recorded as conflicts.
- [ ] Invalid signatures, oversized payloads, and invalid timestamps are rejected; duplicates are safe and 429 responses support retry.
- [ ] Late arrivals retain occurred_at and received_at and update reports without double counting.
- [ ] Denied consent blocks disallowed field collection, and personally identifiable information does not appear in logs.

## Rollout and recovery
Propose new sources disabled until configured; permit client/source disablement without deleting receipts. Migrations must be additive and tested on disposable storage. A failure before commit creates no event/receipt; an ambiguous response is retried with the same event ID. Preserve data during rollback by disabling ingestion and retaining schema rather than dropping populated tables. No backfill, native migration or production deployment is authorized during preparation.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
