# Next specification review
Updated: 2026-11-11. Specifications 001-005 are merged; PR 4 merged Spec 005 at `c251e20` from reviewed head `3bdcc89`. Specification 006 is prepared for owner decision under D-039 on `codex/spec-006-identity-journey`.

1. Review the 006 [entry review](../../specs/006-identity-journey/entry-review.md), [design revision 3](../../specs/006-identity-journey/design.md), [decision packet](../../specs/006-identity-journey/decision-packet.md), [verification matrix](../../specs/006-identity-journey/verification-matrix.md) and [review register](../../specs/006-identity-journey/preparation-review.md).
2. Under D-041, Claude applied the [fourteen-finding correction handoff](../../specs/006-identity-journey/review-corrections-prompt.md) as design revision 3, verified the documents and published them in the pull request for `codex/spec-006-identity-journey` against `main` for independent review.
3. Review the corrected PR, then decide D1-D13 (Groups A-D) or name the subset approved. The changed recommendations are listed in the review register. Implementation, schema, dependencies and migrations wait for that decision.
4. Customer-facing frontend work waits for the owner's brief, design and brand identity.
5. Keep native rollout (0005 to 0008 and the lifecycle role), live custom-domain checks, production deployment and real customer intake separate. Native tracking_sys was last documented at 0004_identity and was not inspected or changed during this preparation.
6. Keep predecessor items P1-P4 outside 006: the local 003 card-scan follow-up, remaining status/owner edits and legacy-mail policy. See the [004 decision packet](../../specs/004-event-collection/decision-packet.md).
