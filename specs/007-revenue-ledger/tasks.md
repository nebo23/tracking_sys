# Tasks: 007-revenue-ledger
Current continuation: [combined 006 and 007-B/C review](../006-identity-journey/joint-entry-review.md), prepared under D-074 on 2026-11-23.

- [x] Reconcile 007-B/C with the implemented 015 receipt store and 016-A reporting at `81977a3`.
- [x] Prepare proposed persistence, reconciliation, identity association, schema and verification in the joint packet.
- [ ] Obtain the joint J1-J12 decision, including explicit confirmation of deterministic release movements (J8).
- [ ] Implement and verify persisted financial behavior and actual-input identity/attribution handoffs.

Status: 007-A, the in-memory calculation contract, with the corrections of review findings R007-01 to R007-11, merged in [PR 6](https://github.com/nebo23/tracking_sys/pull/6) at `bc0ff40` after independent verification (D-044). See the [evidence](evidence.md#review-corrections-2026-11-14). 007-B and 007-C remain open.

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
- [x] Present the 007-A result to the owner for review.
- [x] Publish 007-A after the owner's upload approval: [PR 6](https://github.com/nebo23/tracking_sys/pull/6) (D-012).
- [x] Record the independent review of PR 6 at `0e4fca1` ([review](pull-request-review-2026-11-14.md)).

## Review corrections (regressions in `backend/tests/test_ledger_corrections.py`)
Each regression failed against `0e4fca1` and passes after the correction; see the [findings table](evidence.md#findings-and-regressions).

- [x] R007-01: an adjustment re-notified with another effective time is conflicting evidence; net stays 800.00 and the 200.00 posting is unchanged; capture and settlement keep their own times (`test_r007_01_*`).
- [x] R007-02: the append-only movement journal records a release when an earlier-effective refund displaces a posted one; final results are identical across delivery orders (`test_r007_02_*`).
- [x] R007-02 follow-up: records received at the same instant keep their supplied receipt order, so every returned movement keeps its sequence and content; a consumer reading after its last sequence reaches the recalculated balance (`test_r007_02_equal_receipt_*`, `test_r007_02_identical_resend_and_microsecond_receipts`).
- [x] R007-03: chargebacks are normalized with their reversals; a full reversal with a full refund leaves net zero in all orders (`test_r007_03_*`).
- [x] R007-04: other agencies' subscriptions and other clients' exponent conflicts cannot interrupt a valid client; the conflict is refused only in the affected client's totals (`test_r007_04_*`).
- [x] R007-05: a purchase signal and a capture sharing a delivery ID post exactly one sale in either order, with a `delivery_id_shared` diagnostic (`test_r007_05_*`).
- [x] R007-06: quote eligibility, quote age, receipt precedence and effective ordering use absolute instants across both folds of a repeated hour (`test_r007_06_*`).
- [x] R007-07: capture and settlement with different source references attach to one sale; amount conflicts and correction audit fields stay checked (`test_r007_07_*`).
- [x] R007-08: identical retries of one discrepancy form one reconciliation item (`test_r007_08_*`).
- [x] R007-09: parent cycles and known invalid parent kinds go to reconciliation; an absent parent stays pending until it arrives (`test_r007_09_*`).
- [x] R007-10: same-currency conversion inputs accumulate exactly in every order (`test_r007_10_*`).
- [x] R007-11: snapshot provenance does not depend on input order (`test_r007_11_*`).
- [ ] Owner confirmation of the R007-02 policy: deterministic recomputation with release movements (implemented, consistent with A3) or commitment first.
- [x] Owner review of the corrections, then update PR 6 (D-012): published to PR 6 and merged at `bc0ff40` under D-044.

## Subsequent work
- [ ] 007-B: present persistence, audit, finance-write permission, retention and migration design; persist the movement journal; repeat AC1–AC5 and the R007 regressions against persisted movements and concurrent deliveries.
- [ ] 007-C: verify identity association and attribution handoffs against implemented dependencies.
- [ ] Record owner acceptance before progressing to dependent work.
