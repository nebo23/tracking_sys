# Tasks: 008-attribution-engine
Status: 008-A implemented locally under D-046; owner review and publication pending.

- [x] Approve the scope and sources for lead and revenue attribution engine.
- [x] Resolve Q-007 for the synthetic slice and record the owner decision (D-046; production defaults remain open).
- [x] Verify the merged 007-A calculation contract and identify the 006, 007-B and 007-C dependencies for live attribution in the [entry review](entry-review.md).
- [x] Prepare applicable contracts and synthetic data/permission examples.
- [x] Define independently reviewable local changes for the approved specification.
- [x] Implement the first approved slice (008-A, [evidence](evidence.md)).
- [x] Verify: For touchpoints A then B and revenue of 100, the approved models produce First: A=100; Last: B=100; Linear: A=50 and B=50.
- [x] Verify: With no eligible touchpoint, unknown receives 100; total allocated credit equals eligible net revenue exactly after rounding.
- [x] Verify: Fixtures define expected results for window boundaries, timezones, timestamp ties, refunds, and late events.
- [x] Verify: Recalculating identical inputs with the same model version produces identical results; model changes preserve history.
- [x] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
