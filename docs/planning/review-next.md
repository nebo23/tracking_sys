# Next specification review
Updated: 2026-11-10. Specifications 001-004 are merged; PR 3 merged at `e8ef587` under D-032. Specification 005 is in preparation on `codex/spec-005-links-tracker`.

1. Review the [005 entry packet](../../specs/005-links-tracker/entry-review.md): current capabilities, inherited 003/004 contracts, the proposed link/tracker journey and unresolved design choices.
2. Prepare the detailed 005 design and decision packet before implementation. Preserve all draft acceptance criteria, including consent-before-identification, outgoing-field minimization, safe redirects, bot/prefetch treatment and domain ownership/TLS verification.
3. Review schema/grants, tracker consent/storage, tooling and domain infrastructure choices explicitly. No 005 application code, dependencies or schema are approved by preparation.
4. Keep native rollout (0005 to 0007 and lifecycle role), production deployment and real customer intake separate. Native tracking_sys was last documented at 0004_identity and was not inspected or changed during this transition.
5. Keep predecessor items P1-P4 outside 005: the local 003 card-scan follow-up, remaining status/owner edits and legacy-mail policy. See the [004 decision packet](../../specs/004-event-collection/decision-packet.md).

The final 004 verification passed 481 suite tests and two independent reproduction checks; see its [final review](../../specs/004-event-collection/final-review-2026-11-10.md). No new code tests are claimed for this documentation-only transition.
