# Next specification review
Updated: 2026-11-10. Specifications 001/002 are merged in PR 1 and specification 003 with its corrections in PR 2 (`bab3a33`). Specification 004 is implemented under D-027 on `codex/spec-004-event-collection` and published for owner review under D-028.

1. Review the [004 final independent review](../../specs/004-event-collection/final-review-2026-11-10.md), [design](../../specs/004-event-collection/design.md) and the [event collection guide](../engineering/event-collection.md). The latest verification passed 481 suite tests and two additional reproduction checks, covering the corrections as well as isolation, consent, erasure, lifecycle and privileges.
2. Corrections R004-01 to R004-04 and the query-value observation passed independent review; D-031 authorizes publication on the existing PR 3. The next owner decision is whether to merge the corrected pull request. Merge remains separate from publication.
3. Decide the separate predecessor items P1-P4 in the [decision packet](../../specs/004-event-collection/decision-packet.md) (local 003 card-scan follow-up, status reconciliation, owner edits, legacy mail).
4. Keep native rollout (0005 to 0007, lifecycle role) and real customer intake (Q-002, Q-004, Q-012) separate from synthetic verification.

Do not run native inspection, migrations, deletion, or live provider requests as a checklist shortcut. Native revision was last verified as 0004_identity on 2026-11-04; this branch expects 0007_event_collection. Do not silently choose markets, retention, capacity, hosting, or providers. See the [readiness review](spec-004-readiness.md).
