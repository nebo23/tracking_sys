# Tasks: 004-event-collection
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for event collection and contracts.
- [ ] Resolve Q-002, Q-004, Q-012 and record the owner decision.
- [ ] Verify dependencies: 003-privacy-data-policy.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: The same event_id delivered through browser and server paths is counted once within a client, using an explicit policy for preferring the more trusted source.
- [ ] Verify: An identical event_id in another client does not suppress that client's data; conflicting payloads for the same scoped ID are recorded as conflicts.
- [ ] Verify: Invalid signatures, oversized payloads, and invalid timestamps are rejected; duplicates are safe and 429 responses support retry.
- [ ] Verify: Late arrivals retain occurred_at and received_at and update reports without double counting.
- [ ] Verify: Denied consent blocks disallowed field collection, and personally identifiable information does not appear in logs.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
