# Next specification review
Updated: 2026-11-10. Specifications 001-004 are merged; PR 3 merged at `e8ef587` under D-032. Specification 005 is implemented locally under D-033 on `codex/spec-005-links-tracker` and awaits independent review.

1. Independently review the local 005 commits and the [evidence](../../specs/005-links-tracker/evidence.md) against the approved [design revision 1](../../specs/005-links-tracker/design.md), [decision packet](../../specs/005-links-tracker/decision-packet.md) (D-033) and [verification matrix](../../specs/005-links-tracker/verification-matrix.md).
2. Decide separately on publication of the branch and its pull request; push, merge and deployment are not authorized by D-033.
3. Plan, as separate gated work, any owner-authorized live custom-domain smoke test (real hostname, CNAME service target, operator certificate). Synthetic DNS/TLS evidence does not establish live readiness.
4. Keep native rollout (0005 to 0008 and lifecycle role), production deployment and real customer intake separate. Native tracking_sys was last documented at 0004_identity and was not inspected or changed during this transition.
5. Keep predecessor items P1-P4 outside 005: the local 003 card-scan follow-up, remaining status/owner edits and legacy-mail policy. See the [004 decision packet](../../specs/004-event-collection/decision-packet.md).

The final 004 verification passed 481 suite tests and two independent reproduction checks; see its [final review](../../specs/004-event-collection/final-review-2026-11-10.md). The 005 results are recorded in its evidence.
