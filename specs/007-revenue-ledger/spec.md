# 007-revenue-ledger — Revenue, refunds, and currencies
Status: Draft; implementation is not approved. Level: L3. Prepared: 2026-10-28. English revision: 2026-10-29.

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
Dependencies: [006-identity-journey](../006-identity-journey/spec.md)

Open decisions: Q-002, Q-006, Q-007. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
