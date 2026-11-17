# Tasks: 010-instagram
Status: D1-D10 approved by D-053; 010-A implemented against the synthetic provider ([evidence](evidence.md)); 010-B awaits the owner's Meta app and test account. This is a review checklist, not an implementation instruction.

- [x] Prepare the [entry review](entry-review.md) from the official Meta documentation read on 2026-11-17, with the 009 contract gaps and decisions D1-D10.
- [x] Approve the scope and sources for instagram analytics: D-053.
- [x] Implement 010-A: the Instagram-shaped synthetic adapter, runtime extensions and migration 0013 ([evidence](evidence.md)).
- [x] Prepare the 010-B [feasibility checklist](feasibility-checklist.md) and the read-only tool `app.instagram_feasibility` with offline tests (no live call).
- [ ] 010-B: owner-operated feasibility check with an owner-created Meta app and professional test account (entry review section 6). First run 2026-11-17: F1, F2 (lifetime), F4, F5, F6, F9 and F10 answered ([evidence](evidence.md#010-b-first-run-2026-11-17)); F7 and F8 wait for media on the test account, F2 refresh for 24 hours, F3 and F11 for the follow-up steps.
- [ ] Resolve Q-001; exact Meta Insights metrics, access, and history require verification and record the owner decision.
- [ ] Verify dependencies: 009-connector-runtime.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: An authorized test-account feasibility check proves account type, OAuth scopes, and actual fields before the final contract is designed.
- [ ] Verify: Account/media metrics match verified reference fixtures with period, source, and version; unsupported metrics are not displayed as zero.
- [ ] Verify: Access failure, content deletion, and disconnection are explicit and apply the retention policy.
- [ ] Verify: The interface makes no metric or historical-coverage claim unsupported by documentation and API responses.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
