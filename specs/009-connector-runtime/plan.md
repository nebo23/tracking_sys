# Plan: 009-connector-runtime
Status: Draft. D-048 authorizes slice 009-A and D-049 slices 009-B to 009-D under decisions D11-D20 of the [decision packet](decision-packet-009bcd.md); no dependency is selected.

## Expected outcome
Manage OAuth connection lifecycles, encrypted credentials, synchronization scheduling/workers, cursors/checkpoints, quotas and cost budgets, backfill, retries, and webhook verification.

## Design before implementation
- Connection, SyncRun, Checkpoint, Capability, ProviderError, and UsageRecord; keep the runtime contract independent of individual platforms.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001, Q-004, Q-009, Q-010.

## Proposed review slices
The [entry review](entry-review.md) (2026-11-15) proposes this split. D-048 approves 009-A with decisions D1-D10 and the [follow-up](entry-review-follow-up.md) clarifications; it is implemented locally ([evidence](evidence.md)). D-049 approves 009-B to 009-D with decisions D11-D20 of the [decision packet](decision-packet-009bcd.md).
1. 009-A, connection lifecycle (implemented locally under D-048): OAuth connect with single-use state and PKCE, safe status, one single-page synthetic sync, `401` to `reconnect_required`, reconnect, and disconnect with provider revocation, secret destruction and scoped purge (003 case D3). Migration 0009 and disposable PostgreSQL concurrency checks. Acceptance criteria 1 and 2, the `401` part of 3.
2. 009-B, synchronization (implemented locally under D-049): pagination, checkpoints, backfill, overlapping runs, `403`, `429` with `Retry-After`, retryable `5xx`, crash recovery at the page/checkpoint boundary, UsageRecord and synthetic budget stops. Acceptance criterion 3. D11 settles worker scheduling for 009 on the PostgreSQL run table; production scheduling is 020.
3. 009-C, coverage and provenance (implemented locally under D-049): Capability catalog, metric availability, last successful sync, complete-through, historical coverage and cost state. Acceptance criterion 4.
4. 009-D, provider webhooks (implemented locally under D-049): adapter-specific signature and replay verification with scoped deduplication before data enters the runtime.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [x] OAuth callbacks validate state and reject replay; tokens appear in neither the browser nor logs, and PKCE applies where required by the flow. See the [acceptance summary](evidence.md#spec-009-acceptance-summary).
- [x] Expired or revoked tokens produce an explicit disconnected state and stop affected ingestion without disrupting other clients. See the [acceptance summary](evidence.md#spec-009-acceptance-summary).
- [x] 429 responses respect provider backoff; 401 responses trigger reconnection; crash recovery resumes without duplicate records. See the [acceptance summary](evidence.md#spec-009-acceptance-summary).
- [x] Every connection exposes explicit metric availability, last synchronization, historical coverage, and cost states. See the [acceptance summary](evidence.md#spec-009-acceptance-summary).

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
