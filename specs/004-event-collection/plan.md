# Plan: 004-event-collection
Status: Reviewable delivery plan prepared 2026-11-10 and revised with design revision 2 on the same date. The [design](design.md) and [decision packet](decision-packet.md) (D1-D11) require approval before implementation. No schema or dependency is authorized by this plan.

## Expected outcome
Define a versioned event envelope, limited-trust public ingestion, authenticated server ingestion, webhooks, deduplication, UTM/click IDs, bot/internal traffic filtering, and backend event diagnostics.

## Design before implementation
- EventEnvelope v1, idempotency scope, public/trusted credentials, and retry behavior. Revision 2 proposes no quarantine or dead-letter store: rejected input is discarded and counted by reason only.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-002, Q-004, Q-012.

## Proposed review slices
1. **004-A, decisions and baseline (done for preparation):** branch from merged `bab3a33`, record the 380-test baseline, compare the design with the code (revision 2), and obtain the owner's D1-D11 decisions. Record them in the decision register before any code.
2. **004-B, schema and settings:** migration 0007 (nine tables, credential kind, audit checks, runtime and lifecycle grants), models, data-policy registry rules, keyring settings, test fixture table list. Test the upgrade, the populated-downgrade refusal, the grant matrix and the registry.
3. **004-C, smallest complete trusted path:** ingest-key issuance, trusted API consent with subject issuance, and trusted event intake through the full admission transaction (client lock, scope re-resolution, consent basis, minimization, form mapping, deduplication, conflicts, upgrades, rate limits, counters). Test database rows, isolation, rollback and concurrency with withdrawal.
4. **004-D, public and webhook paths:** browser sources (public key, Origin allowlist, simple requests, generic 202), public consent, webhook sources with sealed secrets, raw-body signatures, the time window and rotation overlap. Verify that limited trust never escalates and public outcomes are indistinguishable. No live provider.
5. **004-E, deletion, lifecycle and diagnostics:** admin and self-erasure with subject and replay tombstones, lifecycle expiry under the client try-lock, daily counters, metadata lookup, traffic labels. Test replay from every channel, expiry followed by a late retry, and that lifecycle grants cannot reach tombstones.
6. **004-F, review evidence:** full unit and PostgreSQL suite, Ruff, pip check, migration/grant/registry/OpenAPI checks, forbidden-data absence and deterministic concurrency. Review the final diff, then obtain publication approval and owner acceptance. Native and production rollout remain separate.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] The same event_id delivered through browser and server paths is counted once within a client, using an explicit policy for preferring the more trusted source.
- [ ] An identical event_id in another client does not suppress that client's data; conflicting payloads for the same scoped ID are recorded as conflicts.
- [ ] Invalid signatures, oversized payloads, and invalid timestamps are rejected; duplicates are safe and 429 responses support retry.
- [ ] Late arrivals retain occurred_at and received_at and update reports without double counting.
- [ ] Denied consent blocks disallowed field collection, and personally identifiable information does not appear in logs.

## Rollout and recovery
Propose new sources disabled until configured and existing service keys unchanged as `read`; permit client/source disablement and key revocation without deleting data. Migrations must be additive and tested on disposable storage. A failure before commit creates no event/receipt; an ambiguous response is retried with the same event ID. Preserve data during rollback by disabling ingestion and retaining schema rather than dropping populated tables. No backfill, native migration or production deployment is authorized during preparation.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
