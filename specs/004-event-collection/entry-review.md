# Specification 004 entry review

Prepared: 2026-11-10 following the owner's request to close predecessor work before 004. Status: design preparation; not approval of new tables, dependencies, policy values, or implementation.

## Dependency and branch gate

Specifications 001/002 are merged in PR 1. Specification 003 is completed at contract level under D-025, with corrections in open PR 2. Review [readiness evidence](../../docs/planning/spec-004-readiness.md), obtain the owner merge decision, then branch from updated merged main under D-023. Preserve unrelated local work. Do not restart 003 or treat its transferred consumers as missing predecessor implementation.

## Recommended first design slice

The concrete proposal is in [design.md](design.md); numeric, permission and retention choices are collected in the [decision packet](decision-packet.md). All remain proposals.

Design one versioned ingestion contract shared by limited-trust browser and authenticated server sources using synthetic fixtures. Keep FastAPI/PostgreSQL and approved dependencies. Propose transactional admission and scoped deduplication first; do not select a queue, broker, or paid provider merely to define retry/dead-letter behavior. Include webhook signature/replay contracts; a concrete adapter needs an identified source and approval.

Proposed envelope fields to review: schema version, event ID, event type, occurred time, server-assigned received time, source, client scope, consent reference/version, and an allowlisted payload. Trusted scope comes from authentication and stored grants. A public client identifier is routing information, never proof of authority. A browser purchase event is never financial proof.

Define the transaction order: validate bounds/credentials; resolve live client scope; evaluate consent and tombstone admission; sanitize fields; atomically resolve scoped event identity and persist only permitted content. Forbidden raw content must not enter diagnostic, conflict, quarantine, or dead-letter payloads. Specify what safe rejection metadata may be retained.

## Decisions before dependent implementation

| Decision | Recommendation to review | Required output |
|---|---|---|
| Sources and events (Q-002) | Start with explicit browser/server events and form-submission contracts using synthetic sources; distinguish lead claims from sale evidence. | Approved taxonomy and payload allowlists; named webhook provider or explicit adapter deferral consistent with scope. |
| Deduplication and precedence | Uniqueness by client plus event ID; retain arrival metadata and detect conflicts without double counting. Prefer verified server fields only under an explicit policy. | Concurrent retry, source upgrade, conflicting/immutable fields and cross-client rules. |
| Capacity and abuse (Q-004) | Establish a local workload before infrastructure selection; public and trusted paths need separate controls. | Owner workload/budget inputs and reviewed payload, field, timestamp-skew, lateness, rate, batch and retry bounds. |
| Retention and deletion (Q-012) | Apply J1 strict opt-in and workspace-lifetime tombstones from D-025. Do not copy credential retention onto events. | Approved raw/conflict/quarantine retention, deletion coverage and consent-withdrawal/replay behavior before real customer intake. |
| Schema and credentials | Reuse agency/client authorization; review public keys and trusted scopes instead of silently broadening service credentials. | Reviewed event, consent, deletion-request and tombstone schema, constraints/indexes/grants, additive migrations and data-preserving rollback. |

Resolve how consent and tombstones are loaded and enforced in the admission transaction. Caller-supplied consent flags or subject identifiers cannot bypass these checks. Identify the future restore journal boundary without claiming that journal custody or an operational restore pipeline exists.

## Acceptance matrix

| Contract | Required executable cases |
|---|---|
| Isolation | Two agencies/two clients each; forged client ID, missing scope, revoked credentials/membership and diagnostics access. |
| Deduplication | Browser/server same scoped ID, concurrent retries, same ID across clients, changed payload conflict and trusted-source upgrade. |
| Validation | Invalid signatures, webhook replay, oversized inputs, invalid timestamps, expired credentials, 429 retry guidance and rejection without side effects. |
| Privacy | Denied/missing/withdrawn consent prevents prohibited storage/outbound work; mapped free-text card variants absent from storage/logs/diagnostics; invalid mappings fail closed. |
| Deletion/replay | Tombstones block old and newly delivered copies; deletion is scoped and covers every store introduced by 004. |
| Late events | Preserve occurred_at/received_at without double counting; define later reporting behavior without implementing reports here. |
| Recovery | Atomic rollback, safe retry/conflict handling and no prohibited payload in quarantine/dead-letter storage. |

003 transfers C1/D2/M5 and ingestion enforcement E2 to 004. Library tests alone do not verify storage enforcement. Tracker remains 005; identity 006; financial truth 007; connector runtime 009; operational restore 019/020.

## Separate outstanding items

- Native 0005/0006 rollout requires separate approval and reviewed role/migration/readiness steps. Disposable storage supports 004 design/testing meanwhile.
- Legacy mail: proposed T1 exact-token expiry derivation, with T2 explicit retirement for unmatched messages; approve policy and review implementation before native execution. Never guess historical expiry.
- Production mail, live Google/Gmail checks, Facebook, hosting, durable scheduling and production restore retain their own gates.

These do not prevent synthetic design review. They are not completed and must remain visible before production.

## Preparation verification (2026-11-10)

All six preparation documents were checked for resolving relative links; the JSON example parses, all 12 source requirement IDs exist in the feature register, and the scoped whitespace check passes. No 004 code, migration or endpoint exists yet, so there is no claimed 004 runtime test result. The predecessor 381-test result belongs to the corrected 003 candidate recorded in the readiness review. This packet remains local and uncommitted pending completion of the interrupted publication workflow; PR 2 was not updated by this preparation.
