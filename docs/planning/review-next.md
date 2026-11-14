# Next specification review
Updated: 2026-11-14. Spec 006 design revision 4 merged through [PR 5](https://github.com/nebo23/tracking_sys/pull/5) at `ec9a09b`. Spec 007-A is implemented locally under D-043.

1. Review the local 007-A commit and its [evidence](../../specs/007-revenue-ledger/evidence.md): the in-memory calculation contract and acceptance cases AC1–AC5. Publication needs the owner's upload approval.
2. Decide when to open the 007-B design review. The [007 plan](../../specs/007-revenue-ledger/plan.md) places persistence, finance-write permissions, reconciliation handling and provider integration there.
3. Carry the [six deferred 006 findings](../../specs/006-identity-journey/preparation-review.md#deferred-at-merge) into their affected implementation reviews. Person-linked revenue depends on the identity contract and privacy behavior.
4. Customer-facing frontend work waits for the owner's brief, design and brand identity.
5. Keep native rollout (0005 to 0008 and the lifecycle role), live custom-domain checks, production deployment and real customer intake separate. Native tracking_sys was last documented at 0004_identity and was not inspected or changed during this preparation.
6. Keep predecessor items P1-P4 outside 006: the local 003 card-scan follow-up, remaining status/owner edits and legacy-mail policy. See the [004 decision packet](../../specs/004-event-collection/decision-packet.md).
