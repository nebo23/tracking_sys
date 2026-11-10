# Specification 004 entry review

Prepared: 2026-11-10 following the owner's request to close predecessor work before 004. Updated 2026-11-10 after the PR 2 merge. Status: design preparation; not approval of new tables, dependencies, policy values, or implementation.

## Dependency and branch gate

Specifications 001/002 are merged in PR 1 (`98747a2`). Specification 003 and its D-026 corrections are merged in PR 2 (`bab3a33`, content identical to `21f0233`). Branch `codex/spec-004-event-collection` was created from `bab3a33` under D-023. The local 003 card-scan follow-up is not in `main`; it is tracked separately (decision packet item P1) and is not part of 004. Do not restart 003 or treat its transferred consumers as missing predecessor implementation.

## Recommended first design slice

The concrete proposal is [design.md](design.md) revision 2; the owner choices are collected in the [decision packet](decision-packet.md) as D1-D11. All remain proposals.

Design one versioned ingestion contract shared by limited-trust browser and authenticated server sources using synthetic fixtures. Keep FastAPI/PostgreSQL and approved dependencies. Propose transactional admission and scoped deduplication first; do not select a queue, broker, or paid provider merely to define retry/dead-letter behavior. Include webhook signature/replay contracts; a concrete adapter needs an identified source and approval.

Trusted scope comes from authentication and stored grants. A public key is routing information, never proof of authority. A browser purchase event is never financial proof.

Transaction order (design section 8): bound and parse (webhook signature first), resolve the source or key, rate-limit, take the client lock, re-resolve live scope, resolve the subject, check replay tombstones, evaluate consent, minimize and validate, then atomically resolve the scoped event identity. Forbidden raw content never enters diagnostics or any other store; only closed reason codes and counts are retained.

## Decisions before dependent implementation

| Decision | Revision 2 recommendation | Packet item |
|---|---|---|
| Sources and events (Q-002) | Fixed v1 event types; registered forms with non-identifying mapped fields; sender claims only, never sale evidence. | D1, D4 |
| Deduplication and precedence | Scoped `(client, event_id)`; duplicate, conflict counter, public-to-trusted upgrade with identical type and subject. | D5 |
| Capacity and abuse (Q-004) | Development limits within the existing 16 KiB boundary; separate public and trusted rate limits. | D6 |
| Retention and deletion (Q-012) | Provisional development periods; tombstones and requests for the workspace lifetime; synchronous erasure. | D7, D11 |
| Schema, credentials and keys | Nine-table migration 0007, ingestion credential kind, explicit grants, local keyrings. | D2, D8, D9, D10 |

Caller-supplied consent flags, receipts or subject identifiers cannot bypass admission. The future restore journal boundary is identified (019/020) without claiming journal custody or an operational restore pipeline.

## Acceptance matrix

| Contract | Required executable cases |
|---|---|
| Isolation | Two agencies/two clients each; forged agency or client path, wrong credential kind, missing grant, revoked or expired credentials, disabled creator, archived client, disabled source, diagnostics access. |
| Deduplication | Browser/server same scoped ID, concurrent retries, same ID across clients, changed payload conflict and trusted-source upgrade. |
| Validation | Invalid signatures, webhook replay, oversized inputs, invalid timestamps, 429 retry guidance and rejection without side effects. |
| Privacy | Denied/missing/withdrawn/expired consent prevents storage; click identifiers dropped without attribution; password, card and free-text variants absent from storage, logs and diagnostics; invalid mappings fail closed. |
| Deletion/replay | Tombstones block replays from every channel; deletion is scoped and covers every store introduced by 004. |
| Late events | Preserve occurred_at and received times without double counting; define later reporting behavior without implementing reports here. |
| Recovery | Atomic rollback, safe retry/conflict handling, no quarantine or dead-letter payload. |

003 transfers C1/D2/M5 and ingestion enforcement E2 to 004. Library tests alone do not verify storage enforcement. Tracker remains 005; identity 006; financial truth 007; connector runtime 009; operational restore 019/020.

## Separate outstanding items

- Native 0005/0006 rollout requires separate approval and reviewed role/migration/readiness steps. Disposable storage supports 004 design and testing meanwhile.
- Legacy mail: proposed T1 exact-token expiry derivation, with T2 explicit retirement for unmatched messages; approve the policy and review its implementation before native execution. Never guess historical expiry.
- Production mail, live Google/Gmail checks, Facebook, hosting, durable scheduling and production restore retain their own gates.

These do not prevent synthetic design review. They are not completed and must remain visible before production.

## Preparation verification (2026-11-10)

Revision 2 was checked against the code at `bab3a33`: credential and grant models, `resolve_scope`, request-body and CORS middleware, logging allowlist, lock order, audit constraints, migration grants, the data-policy registry and the 003 privacy contracts (design section 1). The full suite on `bab3a33` passed 380 tests with PostgreSQL enabled on fresh disposable storage. No 004 code, migration or endpoint exists yet, so there is no 004 runtime result.
