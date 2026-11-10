# Tasks: 005-links-tracker
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for links, utm parameters, and website tracker.
- [ ] Resolve Q-001, Q-002, Q-003 and record the owner decision.
- [x] Verify the merged code dependency: 004-event-collection, PR 3 at `e8ef587`; 481 suite tests and two independent reproduction checks recorded before merge. Native rollout remains separate.
- [x] Prepare the [entry review](entry-review.md) on the fresh `codex/spec-005-links-tracker` branch (D-032).
- [ ] Prepare the detailed design and decision packet, including schema, tracker consent/storage, tooling and domain-verification boundaries, before implementation.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: A test link reaches its destination and preserves content/campaign provenance without exposing personal information in the URL.
- [ ] Verify: Disallowed destinations, unsafe protocols, and redirect loops are rejected; link management requires client permission.
- [ ] Verify: Analytics failure does not break redirects; bots and prefetch requests are not automatically counted as qualified human clicks.
- [ ] Verify: Custom domains require ownership verification; implementation verifies TLS and slug conflicts.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
