# Tasks: 004-event-collection
Status: Design preparation complete for owner review, 2026-11-10; implementation has not started. Unchecked gates below remain explicit.

- [x] Prepare the [entry review](entry-review.md) and [predecessor closure matrix](../../docs/planning/spec-004-readiness.md), 2026-11-10. This is design preparation, not implementation approval.
- [x] Prepare [design](design.md), [decision packet](decision-packet.md), synthetic acceptance examples and the 004-A to 004-F delivery plan.

- [ ] Approve the scope and sources for event collection and contracts.
- [ ] Resolve Q-002, Q-004, Q-012 and record the owner decision.
- [ ] Verify dependencies: 003-privacy-data-policy.
- [ ] Approve/revise the proposed contracts, per-field purposes/classes, credential scopes, key custody, schema and retention before implementation.
- [ ] Confirm the proposed implementation slices against the approved decisions.
- [ ] Implement the first approved slice.
- [ ] Verify consent receipt issuance/binding, withdrawal/deletion serialization, tombstone replay and no prohibited storage side channels.
- [ ] Verify generic webhook raw-body signature, replay window, source disablement and public-to-trusted isolation.
- [ ] Verify payload expiry with retained deduplication, approved metadata cleanup, key rotation and safe deletion outcomes.
- [ ] Verify redacted diagnostics, bot/internal exclusion rules, financial access and bounded cursor pagination.
- [ ] Verify: The same event_id delivered through browser and server paths is counted once within a client, using an explicit policy for preferring the more trusted source.
- [ ] Verify: An identical event_id in another client does not suppress that client's data; conflicting payloads for the same scoped ID are recorded as conflicts.
- [ ] Verify: Invalid signatures, oversized payloads, and invalid timestamps are rejected; duplicates are safe and 429 responses support retry.
- [ ] Verify: Late arrivals retain occurred_at and received_at and update reports without double counting.
- [ ] Verify: Denied consent blocks disallowed field collection, and personally identifiable information does not appear in logs.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
