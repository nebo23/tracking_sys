# Spec 007 entry review and first decision packet

Prepared on 2026-11-11 under D-042 from merged `main` at `ec9a09b` on `codex/spec-007-revenue-ledger`. [PR 5](https://github.com/nebo23/tracking_sys/pull/5) merged the Spec 006 design. The application baseline is still migration `0008_links_tracker`. All ledger choices below are proposals.

## What constitutes a sale?

A client reports a purchase of 1,000 and later refunds 200. The ledger should show which evidence establishes the sale, count each financial operation once and explain the resulting 800 in its original currency. A client can have verified revenue even when the purchaser's identity is unknown.

| Input or consumer | Handoff |
|---|---|
| 004 collection | `purchase_signal` already accepts a reference, minor-unit amount and currency. Even a server-ranked signal remains a reported purchase until independent qualifying evidence arrives. [Event contract](../../backend/app/collection/contract.py) |
| 002 access | Reads of client amounts use `resolve_scope(..., "finance:read")` on the current agency and client. Restricted members and read credentials require their financial grant. An ingest credential has a distinct purpose. Manual financial writes need an explicit policy in 007-B. [Access resolver](../../backend/app/services/access.py) |
| 003 privacy and 006 identity | Keep the financial operation addressable independently of a person. An eventual association needs its original evidence, permitted scope and current ownership. F1 (detach identifying links and preserve amounts) remains a proposed financial-erasure policy. Test unlinking and stale feed recovery before exposing person-level results. [Privacy proposal](../003-privacy-data-policy/design.md) · [Deferred identity findings](../006-identity-journey/preparation-review.md#deferred-at-merge) |
| 008, 015 and 017 | 008 consumes ledger amounts for allocation. 015 verifies provider evidence and maps it to business operations. 017 owns agency subscription charges. Its receipts never enter client revenue totals. [Attribution](../008-attribution-engine/spec.md) · [Business integrations](../015-business-integrations/spec.md) · [SaaS billing](../017-saas-lifecycle/spec.md) |

## First reviewable slice

**Proposed 007-A** is a provider-independent calculation contract with synthetic examples and unit tests. It can be reviewed before any database schema, HTTP write route, live payment service, FX subscription or person-level association. Its inputs carry agency, client, source account, business reference, evidence classification, effective time and receipt time.

| Contract | Proposed responsibility |
|---|---|
| `Transaction` | Group one sale and its linked adjustments within an agency, client, source account and original currency. Keep the provider's business reference distinct from a notification delivery ID. |
| `RevenueEntry` | Record a signed posting in integer minor units with its operation type, source evidence and effective time. The original entry remains available after a correction. |
| `Adjustment` | Identify one refund, chargeback, reversal or audited correction, its immutable business operation ID, parent operation and reason. An unmatched parent stays pending. |
| `FxRateSnapshot` | For a converted view, record the currency pair, exact decimal rate, direction, effective time, source and rounding policy. Missing or stale conversion evidence is visible and original totals remain available. |

### Decisions for the owner

| Item | Recommended for 007-A | Alternative and effect |
|---|---|---|
| A1 · Qualifying evidence (Q-002) | Use synthetic confirmed capture/settlement evidence. Map both stages of the same economic capture to one sale. Keep manual declarations distinguishable from independently verified sales. Defer the manual approval role and named provider to their own design review. | Count an audited manual entry as verified once an authorized reviewer accepts the evidence. This requires a decision on reviewers, evidence requirements, reversals and how a later provider confirmation reconciles with the declaration. |
| A2 · Amounts and currency (Q-006) | Use integer minor units with an explicit currency exponent. Report original-currency totals first. Use an exact decimal snapshot and one documented rounding step for the synthetic conversion example. | Use fixed-scale decimal postings per currency. This also requires precision, validation and rounding rules and changes the persistence contract. |
| A3 · Adjustments and replay (Q-007) | Use append-only signed movements. Match by tenant, source account and operation ID. Treat exact redelivery as a no-op. Different delivery IDs for the same operation post once. Conflicting evidence or a total reversal above the captured balance goes to reconciliation. Normalize linked reversals before deriving final totals so delivery order cannot choose the result. | Publish provider balances as the primary view. Historical changes would need a separate reconstruction policy to explain prior reported totals. |

The proposed net for 007-A is captured value less posted refunds and chargebacks, plus valid reversals and signed corrections. A chargeback reversal references the original debit and restores only its outstanding amount. Fees, tax and payout settlement need explicit definitions before a report presents profit or payout figures.

### Acceptance cases for implementation

All figures are synthetic. Rows with different currencies have separate totals.

| Case | Input | Observable result |
|---|---|---|
| AC1 · Deduplication | Deliver the same capture twice, then in a different notification. Reuse its operation ID with a different amount. | One capture posting. The conflicting claim is visible for reconciliation and leaves posted totals unchanged. |
| AC2 · Partial and full refund | Capture 1,000.00, refund 200.00, then refund the remaining 800.00 in the same two-decimal currency. | Net moves from 100,000 to 80,000 to zero minor units. Both refunds and their evidence remain traceable. |
| AC3 · Out-of-order inputs | Deliver the 200.00 refund before its 1,000.00 capture. In a separate case deliver a chargeback reversal before its debit; replay each input. | While unpaired, the adjustment is pending. Once reconciled, every delivery order gives the same entries and totals. A manual correction adds an entry with actor, reason and source reference. |
| AC4 · Reproducible conversion | Keep 10.00 in currency A and 20.00 in B. A synthetic snapshot quotes 1 A = 2 B; both exponents are 2. Repeat using the same snapshot, then remove it. | Original totals remain separate. Converted total under that snapshot is 40.00 B. Without a usable snapshot the combined amount is unavailable. A rounding fixture converts 0.03 A at 1.5 B/A to 0.04 B under the proposed half-even rule. |
| AC5 · Isolation and billing | Give two clients the same external operation ID. Add an agency subscription payment and a client `purchase_signal` without qualifying sale evidence. | Clients reconcile independently. Neither the subscription nor the unverified signal enters a client sale total. |

## Subsequent slices

- **007-B — Persistence, audit and permissions.** Present the schema, uniqueness keys, atomic posting and retry rules, finance-write permissions, erasure/retention and migration plan for approval. Include concurrent duplicate notifications, conflicting evidence and cross-tenant access tests.
- **007-C — Downstream use.** Exercise identity association against an implemented 006 contract, including R006-24, R006-25 and R006-28 where they affect anonymous events, ownership and stale checkpoints. Preserve transaction amounts and reconcile attribution inputs after association changes. Choose live sources and reporting currencies only after their owner decisions.

The immediate decision is whether to implement 007-A with A1–A3 as proposed. The five acceptance cases above are planned; 007 has no implementation or executed ledger suite yet.
