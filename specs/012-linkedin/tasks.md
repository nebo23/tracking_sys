# Tasks: 012-linkedin
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for linkedin analytics.
- [ ] Resolve Q-001; account type and program approval and record the owner decision.
- [ ] Verify dependencies: 009-connector-runtime.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable PR slices once the repository is available.
- [ ] Implement the first approved slice.
- [ ] Verify: Record the organization/member scope decision and verify Community Management access before launch.
- [ ] Verify: Do not collect from unauthorized accounts; revoked grants prompt reconnection and stop affected collection.
- [ ] Verify: API version changes do not silently change metric semantics; contract fixtures cover unavailable and empty responses.
- [ ] Verify: Document tier, role, and historical-coverage limits using an authorized test connection.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Create or update a PR and push only after repository authorization.
- [ ] Record owner acceptance before progressing to dependent work.
