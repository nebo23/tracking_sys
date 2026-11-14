# Specification 007-A evidence

Date: 2026-11-14. Authority: D-043 (decisions A1–A3 of the [entry review](entry-review.md) as recommended). Branch: `codex/spec-007-revenue-ledger`, based on `90fd33b`. The implementation, its tests and this record form one local commit. Nothing was pushed, published, merged, deployed or migrated. Slices 007-B and 007-C remain open.

## Scope delivered

| File | Content |
|---|---|
| `backend/app/ledger/money.py` | `Currency` (code and explicit minor-unit exponent), `Money` (integer minor units, exact decimal parsing, no cross-currency addition), `FxRateSnapshot` (pair, exact `Decimal` rate, direction, effective time, source, rounding rule) and `convert()` with explicit missing, stale and conflicting states. |
| `backend/app/ledger/calculation.py` | `Evidence`, `RevenueEntry`, `Adjustment`, `Transaction`, `CurrencyTotals`, `ReconciliationItem`, `DeliveryOutcome` and the entry point `calculate()`. |
| `backend/app/ledger/__init__.py` | The public surface of the contract. |
| `backend/tests/test_revenue_ledger.py` | AC1–AC5, the owner's worked refund example and evidence validation (46 cases). |
| `backend/tests/test_ledger_money.py` | Amount parsing, currency and snapshot validation, half-even rounding, exponent scaling, single rounding and snapshot selection (46 cases). |

The modules use only the standard library (`dataclasses`, `decimal`, `enum`, `heapq`, `datetime`, `uuid`). No dependency, table, migration, HTTP route, provider integration, identity association or frontend work was added.

## Contract

- **Evidence.** Each record carries agency, client, source account, delivery ID, business operation ID, operation kind, evidence classification, amount, effective time, receipt time, an optional parent operation and the revenue stream. A correction also requires actor, reason and source reference. The contract has no person reference, so a sale with an unknown purchaser is complete.
- **Qualifying evidence (A1).** `confirmed_capture` and `confirmed_settlement` records of one operation ID post one sale. `manual_declaration` and `purchase_signal` records are listed as unverified and never enter verified totals. Records of the `agency_subscription` stream are excluded from client revenue, even when they reuse a client or operation ID.
- **Amounts (A2).** Integer minor units with an explicit exponent. Totals are returned per original currency through `LedgerCalculation.totals(agency_id, client_id, source_account_id=None)`; no method aggregates across agencies, clients or currencies.
- **Replay and adjustments (A3).** Operations are matched within agency, client and source account. An exact redelivery is a no-op (`same_delivery`); a new delivery that agrees with a known operation is attached to the same posting as evidence (`same_operation`). Each operation posts once as a signed entry. Net is captured value less refunds and chargebacks, plus chargeback reversals and audited corrections.
- **Ordering.** An adjustment is pending until its parent is posted (`parent_missing`, or `parent_unresolved` when the parent is itself pending or in reconciliation). Ready adjustments are applied in canonical order (effective time, then operation ID), so delivery order cannot decide which adjustment exceeds a balance. The same evidence set therefore yields the same postings and totals.
- **Reconciliation.** `conflicting_evidence` (same operation, different terms), `delivery_id_reused`, `exceeds_outstanding`, `reversal_exceeds_debit`, `currency_mismatch`, `invalid_parent` and `correction_below_zero`. For the first two, the record received first keeps its effect and the later record never rewrites a posting. This is the one documented case in which receipt order matters.
- **Conversion.** `convert()` uses the latest snapshot effective at or before `as_of` in its recorded direction only, refuses snapshots older than `max_age`, computes each component exactly and rounds the combined total once, half-even, to the target exponent. Without usable evidence for every component, the combined amount is unavailable and the original amounts remain in the result.

## Acceptance cases

| Case | Tests | Result |
|---|---|---|
| AC1 · Deduplication | `test_ac1_*` (5) | One sale posts for a capture, its same-ID replay, a new-ID notification and its settlement, in every delivery order. A conflicting 1,200.00 claim for the operation is a reconciliation item; the posted 100,000 and its entry are unchanged. A reused delivery ID with other content is also reconciled. |
| AC2 · Partial and full refund | `test_ac2_*` (3) | Successive balances 100,000, 80,000 and 0 minor units. Each refund replayed with the same and a new delivery ID posts once. Each refund entry keeps its parent and delivery evidence. A further 0.01 refund is reconciled as `exceeds_outstanding`. |
| AC3 · Out-of-order inputs | `test_ac3_*` (9) | A refund before its capture is pending, then converges in all permutations. A chargeback reversal before its debit is pending; without the sale the chargeback is `parent_missing` and the reversal `parent_unresolved`. Reversals restore at most the outstanding debit. Canonical order decides which of two 600.00 refunds is reconciled. A mixed transaction converges over 200 seeded shuffles. An audited correction adds a posting with actor, reason and source reference and leaves the original sale entry identical. Corrections without audit fields are refused; one that would take net below zero is reconciled. |
| AC4 · Reproducible conversion | `test_ac4_*` (3) and `test_ledger_money.py` | 10.00 AAA and 20.00 BBB at 2 BBB/AAA give 40.00 BBB, identical on repetition, with snapshot ID, pair, rate, direction, effective time, source and rounding recorded. Missing and stale snapshots make the total unavailable and preserve the originals. 0.03 AAA at 1.5 BBB/AAA is exactly 4.5 minor units and rounds to 0.04 BBB. |
| AC5 · Isolation and billing | `test_ac5_*` (3) | The same operation and delivery IDs in two clients, two agencies and two source accounts form four independent transactions with separate refunds; a refund whose parent exists only in another scope stays pending. An agency subscription receipt, an unconfirmed purchase signal and a manual declaration add zero verified sales. Two currencies of one client remain separate totals; a cross-currency refund is reconciled and adding the totals is refused. |

### Worked refund example

Recorded by running the synthetic sequence through `calculate()` after each delivery (currency AAA, exponent 2):

| Step | Delivery | Outcome | Net |
|---|---|---|---|
| 1 | Refund `refund-1` of 200.00 before its sale | pending, `parent_missing` | no transaction |
| 2 | The same refund delivery again | duplicate, `same_delivery` | no transaction |
| 3 | Capture `sale-1` of 1,000.00 | posted; the refund is now posted | 80,000 (800.00) |
| 4 | The refund with a new delivery ID | duplicate, `same_operation` | 80,000 (800.00) |

Entries after step 4: +100,000 and −20,000. `test_sale_of_1000_and_refund_of_200_net_800_despite_duplicates_and_early_refund` asserts the same result for all 24 delivery orders of these four records.

## Commands and results

Environment: worktree `.worktrees/spec-007-revenue-ledger` (no `.env`); the project virtual environment `C:\Code\Tracking-system\.venv`, Python 3.12.4, pytest 9.2.0, ruff 0.17.3. No inherited `TRACKING_`, `PG` or `PYTHON` variables were set.

| Check (from `backend/` unless noted) | Result |
|---|---|
| Baseline before any change: `python -m pytest -m "not integration" -q` | 337 passed, 279 deselected. |
| Focused ledger tests: `python -m pytest tests/test_revenue_ledger.py tests/test_ledger_money.py -q` | **92 passed.** |
| Unit suite: `python -m pytest -m "not integration" -q` | **429 passed**, 279 deselected, no failures, errors or skips. |
| `python -m ruff check` on the five changed Python files | All checks passed. |
| `python -m ruff format --check` on the same files | 5 files already formatted. |
| `python -m ruff check .` | All checks passed. |
| `git diff --check` (repository root) | Clean. |
| Control-character scan of the changed files | Clean. |

The 279 deselected cases need the disposable PostgreSQL environment. This slice changes no schema, model, route or service, so they were not run; the OpenAPI snapshot is unaffected and is part of the unit suite.

## Limitations and open items

- **Persistence and concurrency (007-B).** Postings are derived in memory from the complete evidence set. Atomic posting, uniqueness keys, concurrent duplicate notifications, retention, finance-write permissions and cross-tenant access tests need the 007-B design review.
- **Reconciliation workflow.** Items are reported but not resolved. Who may resolve them, and who may author a correction, is a 007-B permission decision; corrections are not yet permission-gated.
- **Conflict precedence.** For conflicting claims and reused delivery IDs, the first-received record stands. A provider that later confirms a different amount needs an audited correction.
- **Manual evidence (A1 deferral).** A manual declaration never becomes verified, and a confirmed refund whose only parent is a manual declaration or purchase signal stays pending, until the approval role and evidence rules are designed.
- **Settlement, fees and tax.** A settlement must state the captured amount. Fees, tax and payouts are not modelled; any difference is reconciled as conflicting evidence.
- **Conversion.** A currency with a zero total still needs a usable snapshot for a combined figure. Production rate sources and reporting currencies wait for Q-006.
- **Free-text fields.** Correction reasons and actor references are held only in memory here. Their data class and retention belong to the 007-B schema review.
- **Downstream use (007-C).** Identity association and attribution inputs remain open. Q-002, Q-006 and Q-007 remain open decisions.
