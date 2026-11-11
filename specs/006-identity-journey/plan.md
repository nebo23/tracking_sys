# Plan: 006-identity-journey
Status: Draft prepared for owner approval under D-039 (2026-11-11). This plan does not authorize implementation, schema, migrations or dependency selection. Read the [entry review](entry-review.md), [design revision 1](design.md), [decision packet](decision-packet.md) and [verification matrix](verification-matrix.md).

## Expected outcome
Represent anonymous visitors, leads, and customers; support deterministic identity linking, sourced event timelines, and auditable merge/unmerge actions. An authorized agency user can see, for one client, which interactions are reliably associated with a person, in what order, and on what evidence.

## Design before implementation
- IdentityKey, Subject, IdentityLink, and Touchpoint; define normalization, versioning, and ambiguity policies. Proposed in design sections 3-5.
- Map agency/client authorization across every relevant resource, job, cache, and export. Proposed in design sections 7.1 and 12.3 (decision D8).
- Identify data classes, consent, retention, and field provenance before migrations. Proposed in design sections 6, 7 and 12.5 (D6, D7, D12).
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable. Proposed in design sections 12.2 and 12.4.
- Distinguish confirmed decisions from proposals and resolve Q-002, Q-008, Q-012. Reconciled in the decision packet.

## Proposed review slices
| Slice | Content | Gate |
|---|---|---|
| 006-A | Migration 0009, models, data-policy classes, per-client key custody, normalizers, tombstone/audit/grant extensions. | D1, D3, D4, D11, D12 |
| 006-B | Handoff route, trusted assertions, matching rules, segments, consent (E3), withdrawal, expiry and lifecycle integration. | 006-A; D2, D5, D6, D7 |
| 006-C | Profile, timeline, lead inbox and review read APIs with permissions. | 006-B; D8, D9, D13 |
| 006-D | Merge, unmerge, erasure by person or identifier, change feed for 007/008. | 006-C; D10 |
| 006-E | Tracker `identityHandoff()` and `restart()`; Node, Chromium and Firefox tests; end-to-end journey. | 006-B |

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Anonymous visits link to a verified identity only within the same client and under applicable consent.
- [ ] Shared or conflicting email addresses and phone numbers do not automatically merge people without an established policy.
- [ ] Switching users on a shared device does not silently transfer one person's visits to another.
- [ ] Merge/unmerge preserves provenance and recalculates attribution without losing the original evidence.

Each criterion maps to cases in the verification matrix; 006 also completes the transferred 003 obligations (E3 identity-link consent, deletion of identity links, unmerge provenance).

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Migration 0009 is additive with a guarded downgrade; no backfill is needed because no identity data exists. Native rollout and deployment require separate approval.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
