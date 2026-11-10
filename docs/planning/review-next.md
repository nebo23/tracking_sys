# Next specification review
Updated: 2026-11-10. Specifications 001/002 are merged in PR 1 and specification 003 with its corrections in PR 2 (`bab3a33`). Specification 004 is implemented locally under D-027 on `codex/spec-004-event-collection` and awaits owner review.

1. Review the [004 evidence](../../specs/004-event-collection/evidence.md), [design revision 2](../../specs/004-event-collection/design.md) and the [event collection guide](../engineering/event-collection.md); the 455-test run covers isolation, deduplication, consent, minimization, webhook signatures, erasure/replay, concurrency, lifecycle and privileges.
2. Decide upload: push the branch and open a PR only after the owner approves (D-012). Merge remains a separate owner decision.
3. Decide the separate predecessor items P1-P4 in the [decision packet](../../specs/004-event-collection/decision-packet.md) (local 003 card-scan follow-up, status reconciliation, owner edits, legacy mail).
4. Keep native rollout (0005 to 0007, lifecycle role) and real customer intake (Q-002, Q-004, Q-012) separate from synthetic verification.

Do not run native inspection, migrations, deletion, or live provider requests as a checklist shortcut. Native revision was last verified as 0004_identity on 2026-11-04; this branch expects 0007_event_collection. Do not silently choose markets, retention, capacity, hosting, or providers. See the [readiness review](spec-004-readiness.md).
