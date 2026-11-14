# Implement Spec 007-A · Client revenue ledger

Implement and verify the provider-independent revenue calculation contract under D-043. Work in `C:\Code\Tracking-system\.worktrees\spec-007-revenue-ledger` on the existing `codex/spec-007-revenue-ledger` branch. Read `AGENTS.md`, `README.md`, `docs/planning/decisions.md` and this specification's `spec.md`, `entry-review.md`, `plan.md` and `tasks.md`. The entry review contains the approved A1–A3 choices and the exact AC1–AC5 examples.

## Implementation

1. Build a pure Python domain module in the backend using the existing environment and standard library. Implement `Transaction`, `RevenueEntry`, `Adjustment` and `FxRateSnapshot` with a calculation entry point that the tests can call directly. Carry agency, client, source account, business operation and parent references, evidence classification, effective time and receipt time. Support sales with an unknown purchaser.
2. Count synthetic confirmed capture or settlement evidence once per economic capture, including when both stages arrive with different delivery IDs. Keep manual declarations and unverified `purchase_signal` events distinguishable from verified revenue. Exclude agency subscription receipts from client sales.
3. Preserve signed postings and their evidence. Compute net as captured value less posted refunds and chargebacks, plus valid reversals and signed corrections. Match operations within agency, client and source account. Keep unmatched adjustments pending. Route conflicting evidence and excessive reversals to reconciliation. A chargeback reversal can restore only the outstanding amount of its referenced debit. An audited correction adds a posting with actor, reason and source reference. Replays and reordered linked operations must converge on the same postings and totals.
4. Keep amounts in integer minor units with explicit currency exponents. Return separate original-currency totals. For synthetic conversion, record the exact decimal rate, pair, direction, effective time, source and rounding rule. Round once to the target currency using half-even. Expose missing or stale conversion evidence and preserve the original totals.

## Acceptance tests

| Case | Evidence to produce |
|---|---|
| AC1 | Replay a capture with the same and different delivery IDs, then deliver its settlement. Exactly one sale posts. Reuse its operation ID with a conflicting amount and show the reconciliation outcome with the posted balance preserved. |
| AC2 | Capture 1,000.00, refund 200.00, then refund 800.00. Assert successive balances of 100,000, 80,000 and zero minor units. Replay each refund. |
| AC3 | Deliver a refund before its capture and a chargeback reversal before its debit. Check pending states, ordering permutations, replay, reversal limits and an audited correction that preserves the original posting. |
| AC4 | With 10.00 A and 20.00 B at 2 B/A, reproduce 40.00 B from the same snapshot. Check missing and stale snapshots. Verify 0.03 A at 1.5 B/A rounds to 0.04 B when both exponents are two. |
| AC5 | Reuse operation IDs across clients, agencies and source accounts. Verify isolated amounts and adjustments. An agency subscription, an unconfirmed purchase signal and an unsupported manual declaration contribute zero verified sales. |

## Verification and delivery

Use synthetic fixtures throughout. The implementation scope ends at this in-memory calculation contract. Database tables, migrations, HTTP routes, live payment and FX integrations, identity association, attribution, and frontend work belong to separate reviews.

Run the focused ledger tests and the existing backend unit suite with the project virtual environment. From `backend`, run `python -m pytest -m "not integration"` and `python -m ruff check` on the changed Python files. Run `git diff --check`. Record actual commands, outcomes and any skipped or unavailable checks. Update this specification's plan, tasks and verification evidence. Keep 007-B and 007-C open.

Commit the verified slice locally on the existing branch and stop for owner review before publication. Report in Arabic with the commit SHA, the test results, one worked refund example and any outstanding decisions. Use formal English for maintained project files.
