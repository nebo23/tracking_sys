# Tasks: 007-revenue-ledger
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for revenue, refunds, and currencies.
- [ ] Resolve Q-002, Q-006, Q-007 and record the owner decision.
- [ ] Verify dependencies: 006-identity-journey.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: Duplicate payment/refund webhooks do not multiply amounts, regardless of delivery order.
- [ ] Verify: A sale of 1,000 followed by a partial refund of 200 produces net revenue of 800 in the same currency; a full refund produces zero.
- [ ] Verify: Refunds arriving before sales, chargeback reversals, and manual adjustments follow documented states and preserve history.
- [ ] Verify: Different currencies are not summed directly; exchange rates, sources, timestamps, and rounding policies are explicit and reproducible.
- [ ] Verify: Client revenue remains separate from agency subscription billing for the SaaS product.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
