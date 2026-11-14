# Plan: 007-revenue-ledger
Status: D-043 approves local implementation of 007-A. The [implementation prompt](implementation-prompt.md) covers the calculation contract and the five synthetic acceptance cases from the [entry review](entry-review.md). Planning for 007-B and 007-C remains provisional.

## Expected outcome
Maintain transactions and their evidence, audited manual revenue, payments, refunds, chargebacks, gross/net amounts, and original/reporting currencies.

## Design before implementation
- RevenueEntry, Transaction, Adjustment, and FxRateSnapshot; choose integer minor units or exact decimals explicitly, never floating point for money.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-002, Q-006, Q-007.

## Proposed review slices
1. 007-A: review A1–A3, then implement the approved provider-independent financial contract and its synthetic unit cases.
2. 007-B: review persistence, concurrency, scope, audit, privacy and migration design before database or API work.
3. 007-C: verify downstream identity and attribution handoffs with their implemented dependencies.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Duplicate payment/refund webhooks do not multiply amounts, regardless of delivery order.
- [ ] A sale of 1,000 followed by a partial refund of 200 produces net revenue of 800 in the same currency; a full refund produces zero.
- [ ] Refunds arriving before sales, chargeback reversals, and manual adjustments follow documented states and preserve history.
- [ ] Different currencies are not summed directly; exchange rates, sources, timestamps, and rounding policies are explicit and reproducible.
- [ ] Client revenue remains separate from agency subscription billing for the SaaS product.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
