# Tasks: 006-identity-journey
Status: Not completed; this is a review checklist, not an implementation instruction. Preparation under D-039 (2026-11-11).

- [x] Verify dependencies: 005-links-tracker (merged in PR #4 at `c251e20`; see the [entry review](entry-review.md)).
- [x] Prepare applicable contracts and synthetic data/permission examples ([design](design.md), sections 2, 10 and 13).
- [x] Define independently reviewable local changes for the approved specification (slices 006-A to 006-E, [plan](plan.md)).
- [x] Prepare the [decision packet](decision-packet.md) and [verification matrix](verification-matrix.md).
- [ ] Approve the scope and sources for lead identity and customer journey.
- [ ] Resolve Q-002, Q-008, Q-012 and record the owner decision (reconciled in the decision packet; owner selection of D1-D13 pending).
- [ ] Implement the first approved slice.
- [ ] Verify: Anonymous visits link to a verified identity only within the same client and under applicable consent.
- [ ] Verify: Shared or conflicting email addresses and phone numbers do not automatically merge people without an established policy.
- [ ] Verify: Switching users on a shared device does not silently transfer one person's visits to another.
- [ ] Verify: Merge/unmerge preserves provenance and recalculates attribution without losing the original evidence.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
