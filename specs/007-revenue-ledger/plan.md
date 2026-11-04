# Plan: 007-revenue-ledger
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Maintain transactions and their evidence, audited manual revenue, payments, refunds, chargebacks, gross/net amounts, and original/reporting currencies.

## Design before implementation
- RevenueEntry, Transaction, Adjustment, and FxRateSnapshot; choose integer minor units or exact decimals explicitly, never floating point for money.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-002, Q-006, Q-007.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

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
