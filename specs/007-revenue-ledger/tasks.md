# Tasks: 007-revenue-ledger
Status: 007-A is implemented and verified locally under D-043 and awaits owner review before publication. See its [evidence](evidence.md). 007-B and 007-C remain open.

- [x] Record approval of A1–A3 for the synthetic calculation slice under D-043.
- [ ] Approve production sources for revenue, refunds, and exchange rates.
- [ ] Resolve Q-002, Q-006, Q-007 and record the owner decision.
- [x] Inspect the merged Spec 006 design at `ec9a09b` and record its outstanding runtime dependencies in the [entry review](entry-review.md).
- [x] Prepare the proposed contracts, financial access boundaries and synthetic acceptance cases for owner review.
- [x] Propose independently reviewable slices 007-A, 007-B and 007-C.
- [x] Implement the first approved slice: the 007-A calculation contract in `backend/app/ledger/` with AC1–AC5 tests (local commit).
- [x] Verify (007-A contract, synthetic): Duplicate payment/refund webhooks do not multiply amounts, regardless of delivery order.
- [x] Verify (007-A contract, synthetic): A sale of 1,000 followed by a partial refund of 200 produces net revenue of 800 in the same currency; a full refund produces zero.
- [x] Verify (007-A contract, synthetic): Refunds arriving before sales, chargeback reversals, and manual adjustments follow documented states and preserve history.
- [x] Verify (007-A contract, synthetic): Different currencies are not summed directly; exchange rates, sources, timestamps, and rounding policies are explicit and reproducible.
- [x] Verify (007-A contract, synthetic): Client revenue remains separate from agency subscription billing for the SaaS product.
- [x] Update documentation, limitations, and untested assumptions for 007-A.
- [ ] Present the 007-A result to the owner for review.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] 007-B: present persistence, audit, finance-write permission, retention and migration design; repeat AC1–AC5 against persisted postings and concurrent deliveries.
- [ ] 007-C: verify identity association and attribution handoffs against implemented dependencies.
- [ ] Record owner acceptance before progressing to dependent work.
