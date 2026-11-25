# 007-revenue-ledger — Revenue, refunds, and currencies
Review corrections (2026-11-25, D-076): the independent review findings of 007-B/C (R0607-03 to R0607-06, R0607-09 to R0607-15, R0607-17 and R0607-18) are corrected; see the [joint evidence](../006-identity-journey/joint-evidence.md#review-corrections-d-076-2026-11-25).

Current continuation (2026-11-23, D-074): prepare 007-B/C together with 006 using the [joint packet](../006-identity-journey/joint-entry-review.md). The proposal builds on the 015 receipt store and current 016-A reports; D-075 approved J1-J12 as recommended and authorizes implementing 007-B/C with 006. 007-A stays implemented and merged.

Status: 007-A, with the corrections of review findings R007-01 to R007-11, merged in PR 6 at `bc0ff40` under D-044; see the [evidence](evidence.md#review-corrections-2026-11-14). Slices 007-B and 007-C await review. Level: L3. Prepared: 2026-10-28. English revision: 2026-10-29. Entry review opened under D-042 from the PR 5 merge at `ec9a09b` on 2026-11-11.

## Sources
PDF-042,052,053,054,056. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Maintain transactions and their evidence, audited manual revenue, payments, refunds, chargebacks, gross/net amounts, and original/reporting currencies.

## Out of scope
Selecting a payment or FX provider without approval, or treating OCR results or payment intent as verified revenue.

## Acceptance criteria
1. Duplicate payment/refund webhooks do not multiply amounts, regardless of delivery order.
2. A sale of 1,000 followed by a partial refund of 200 produces net revenue of 800 in the same currency; a full refund produces zero.
3. Refunds arriving before sales, chargeback reversals, and manual adjustments follow documented states and preserve history.
4. Different currencies are not summed directly; exchange rates, sources, timestamps, and rounding policies are explicit and reproducible.
5. Client revenue remains separate from agency subscription billing for the SaaS product.

## Required design contracts
RevenueEntry, Transaction, Adjustment, and FxRateSnapshot; choose integer minor units or exact decimals explicitly, never floating point for money.

## Dependencies and open decisions
Dependencies: [006-identity-journey](../006-identity-journey/spec.md) The dependency is a merged design. The proposed financial calculation slice is independently reviewable, and the person association requires implemented 006 behavior. See the [entry review and first decision packet](entry-review.md).

Open decisions: Q-002, Q-006, Q-007. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
D-043 records the owner's 2026-11-14 decision to start 007-A with the recommended A1–A3 options. The [implementation prompt](implementation-prompt.md) defines the local deliverable and its verification.
