# Tasks: 010-instagram
Status: Not completed; preparation under D-052. This is a review checklist, not an implementation instruction.

- [x] Prepare the [entry review](entry-review.md) from the official Meta documentation read on 2026-11-17, with the 009 contract gaps and decisions D1-D10.
- [ ] Approve the scope and sources for instagram analytics.
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
