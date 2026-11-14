# Tasks: 007-revenue-ledger
Status: D-043 approves the first calculation slice. Its [implementation handoff](implementation-prompt.md) is ready for execution.

- [x] Record approval of A1–A3 for the synthetic calculation slice under D-043.
- [ ] Approve production sources for revenue, refunds, and exchange rates.
- [ ] Resolve Q-002, Q-006, Q-007 and record the owner decision.
- [x] Inspect the merged Spec 006 design at `ec9a09b` and record its outstanding runtime dependencies in the [entry review](entry-review.md).
- [x] Prepare the proposed contracts, financial access boundaries and synthetic acceptance cases for owner review.
- [x] Propose independently reviewable slices 007-A, 007-B and 007-C.
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
