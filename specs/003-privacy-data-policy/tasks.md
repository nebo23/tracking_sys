# Tasks: 003-privacy-data-policy
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for consent, data protection, and lifecycle.
- [ ] Resolve Q-003, Q-012 and record the owner decision.
- [ ] Verify dependencies: 002-tenancy-access.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: Events that violate the approved consent policy enter neither prohibited storage nor an outbound delivery queue.
- [ ] Verify: Password and sensitive payment fields are excluded from form telemetry and logs.
- [ ] Verify: Subject or connector deletion covers applicable raw data, derived data, caches, and exports, and prevents reintroduction through old event replay under the approved policy.
- [ ] Verify: Backup restoration reapplies deletion tombstones before making the service available.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
