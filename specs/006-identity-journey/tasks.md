# Tasks: 006-identity-journey
Current continuation: [combined 006 and 007-B/C review](joint-entry-review.md), prepared under D-074 on 2026-11-23. The historical checklist below remains open where implementation is not verified.

## Joint preparation

- [x] Inspect merged main `81977a3`, the 015 receipt store, 016-A reporting and deferred identity findings.
- [x] Prepare J1-J12, the joint design addendum, verification matrix and conditional handoff.
- [x] Record the owner's joint decision and any amendments (D-075: J1-J12 as recommended, no amendment).
- [x] Implement and verify phases P0-P5 with the joint and original acceptance matrices (commits `3c89110` to `c7467d7`; [joint evidence](joint-evidence.md)).
- [x] Close each deferred finding with implementation evidence; proposed resolutions alone do not close findings (R006-23 to R006-28, [joint evidence](joint-evidence.md)).

## Historical checklist

Status: Not completed; this is a review checklist, not an implementation instruction. Preparation under D-039 (2026-11-11).

- [x] Verify dependencies: 005-links-tracker (merged in PR #4 at `c251e20`; see the [entry review](entry-review.md)).
- [x] Prepare applicable contracts and synthetic data/permission examples ([design](design.md), sections 2, 10 and 13).
- [x] Define independently reviewable local changes for the approved specification (slices 006-A to 006-E, [plan](plan.md)).
- [x] Prepare the [decision packet](decision-packet.md) and [verification matrix](verification-matrix.md).
- [x] Correct review findings R006-01 to R006-14 in design revision 3 and map each to its sections and acceptance cases (D-041; see the [review register](preparation-review.md#finding-coverage)).
- [x] Present revision 4, record the outstanding findings, and obtain owner authorization to merge the preparation and proceed to 007 (D-042).
- [ ] Approve the scope and sources for lead identity and customer journey.
- [x] Record the owner's choices on D1–D13 for the applicable slices (through J1-J12, D-075). Q-002 and production Q-012 remain open for real intake. Q-008 has no dependency in 006.
- [x] Implement the first approved slice (and 006-A to 006-E, D-075).
- [x] Verify: Anonymous visits link to a verified identity only within the same client and under applicable consent. ([joint evidence](joint-evidence.md))
- [x] Verify: Shared or conflicting email addresses and phone numbers do not automatically merge people without an established policy. ([joint evidence](joint-evidence.md))
- [x] Verify: Switching users on a shared device does not silently transfer one person's visits to another. ([joint evidence](joint-evidence.md))
- [x] Verify: Merge/unmerge preserves provenance and emits the revision and change needed by 008 to recalculate attribution without losing the original evidence (recalculation verified through the in-memory 008-A engine; production 008 persistence stays open).
- [x] Update documentation, limitations, and untested assumptions ([guide](../../docs/engineering/identity-and-ledger.md), [joint evidence](joint-evidence.md)).
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
