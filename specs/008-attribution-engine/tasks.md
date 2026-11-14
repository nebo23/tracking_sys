# Tasks: 008-attribution-engine
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for lead and revenue attribution engine.
- [ ] Resolve Q-007 and record the owner decision.
- [x] Verify the merged 007-A calculation contract and identify the 006, 007-B and 007-C dependencies for live attribution in the [entry review](entry-review.md).
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: For touchpoints A then B and revenue of 100, the approved models produce First: A=100; Last: B=100; Linear: A=50 and B=50.
- [ ] Verify: With no eligible touchpoint, unknown receives 100; total allocated credit equals eligible net revenue exactly after rounding.
- [ ] Verify: Fixtures define expected results for window boundaries, timezones, timestamp ties, refunds, and late events.
- [ ] Verify: Recalculating identical inputs with the same model version produces identical results; model changes preserve history.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
