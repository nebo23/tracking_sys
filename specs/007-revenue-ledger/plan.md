# Plan: 007-revenue-ledger
Current planning (2026-11-23, D-074): the owner chose combined preparation with 006. The [joint plan and decisions](../006-identity-journey/joint-entry-review.md) and [design addendum](../006-identity-journey/joint-design.md) replace the old baseline for this proposed continuation. Reuse the implemented 015 evidence store. Implementation awaits the joint decision; production 008 persistence is a successor.

Status: 007-A, with the corrections of the independent review findings R007-01 to R007-11, merged in PR 6 at `bc0ff40` under D-044. The [implementation prompt](implementation-prompt.md) defined the calculation contract and the five synthetic acceptance cases from the [entry review](entry-review.md); the [evidence](evidence.md) records the delivered contract, commands and results. Planning for 007-B and 007-C remains provisional.

## Expected outcome
Maintain transactions and their evidence, audited manual revenue, payments, refunds, chargebacks, gross/net amounts, and original/reporting currencies.

## Design before implementation
- RevenueEntry, Transaction, Adjustment, and FxRateSnapshot; choose integer minor units or exact decimals explicitly, never floating point for money.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-002, Q-006, Q-007.

## Proposed review slices
1. 007-A: review A1–A3, then implement the approved provider-independent financial contract and its synthetic unit cases. Implemented in `backend/app/ledger/` with AC1–AC5 in `backend/tests/test_revenue_ledger.py` and `backend/tests/test_ledger_money.py`.
2. 007-B: review persistence, concurrency, scope, audit, privacy and migration design before database or API work.
3. 007-C: verify downstream identity and attribution handoffs with their implemented dependencies.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
Each criterion below is met for the 007-A in-memory contract with synthetic evidence (see the [evidence](evidence.md)). Persisted postings, concurrent deliveries and live sources must repeat them in 007-B and 007-C before the criteria are closed for the specification.
- [x] Duplicate payment/refund webhooks do not multiply amounts, regardless of delivery order. (007-A: AC1, AC2, AC3)
- [x] A sale of 1,000 followed by a partial refund of 200 produces net revenue of 800 in the same currency; a full refund produces zero. (007-A: AC2)
- [x] Refunds arriving before sales, chargeback reversals, and manual adjustments follow documented states and preserve history. (007-A: AC3)
- [x] Different currencies are not summed directly; exchange rates, sources, timestamps, and rounding policies are explicit and reproducible. (007-A: AC4, AC5)
- [x] Client revenue remains separate from agency subscription billing for the SaaS product. (007-A: AC5)
- [ ] Repeat the five criteria against persisted postings and concurrent deliveries (007-B).

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
