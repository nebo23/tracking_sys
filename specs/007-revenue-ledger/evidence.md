# Specification 007-A evidence

Date: 2026-11-14. Authority: D-043 (decisions A1–A3 of the [entry review](entry-review.md) as recommended). Branch: `codex/spec-007-revenue-ledger`, based on `90fd33b`. The implementation, its tests and this record form one local commit. Nothing was pushed, published, merged, deployed or migrated. Slices 007-B and 007-C remain open.

**Update 2026-11-14:** the [independent review](pull-request-review-2026-11-14.md) of PR 6 at `0e4fca1` raised eleven findings (R007-01 to R007-11). They are corrected and verified in [Review corrections](#review-corrections-2026-11-14) below. The sections before it record the original implementation and its results; where the corrections changed a rule, the corrected rule applies.

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

## Review corrections (2026-11-14)

Authority: the owner's request to correct R007-01 to R007-11, handed off in the [review corrections prompt](review-corrections-prompt.md) at `b8b9d67`. The reviewed application commit is `0e4fca1`. The corrections form one local commit on `codex/spec-007-revenue-ledger`; nothing was pushed and PR 6 was not updated.

### Contract changes

- **Provisional calculation and movement journal.** `calculate()` now returns two views. Transactions, entries, adjustments, reconciliation items and totals are the provisional calculation over all evidence received so far; later evidence can change them. The new `LedgerCalculation.movements` journal (`Movement`, `MovementType`) is append-only: records are taken in receipt order and each change in the provisional postings becomes a `posting` or a `release` that names the triggering record and, for a release, the new status reason. The movements of each transaction sum to its provisional net. A caller that persists effects should commit movements rather than entries.
- **Operation terms.** Records of one operation must agree on kind, amount, currency and parent, and on effective instant within one evidence class. Capture and settlement keep their own effective times; the sale carries the capture time when one exists. Source reference, actor and reason are per-delivery provenance, except on an audited correction, where they are audit terms.
- **Chargeback normalization.** Reversals of a chargeback are accepted in canonical order up to its amount. The chargeback then consumes only its unreversed remainder of the balance before refunds and other chargebacks are judged.
- **Parent chains.** A parent of a disallowed kind is reconciled as `invalid_parent` as soon as the parent is known, even while it is pending. Operations on a cycle of parents are reconciled as `parent_cycle`. An absent parent remains `parent_missing`.
- **Delivery namespaces.** Verified and unverified records have separate delivery-ID namespaces. A shared ID produces one `delivery_id_shared` item and affects neither record.
- **One item per discrepancy.** Identical retries of one reused delivery ID, or of one conflicting operation claim, join one reconciliation item. Each delivery keeps its own outcome. Materially different payloads form separate items.
- **Tenant-confined validation.** `calculate()` no longer raises `currency_exponent_conflict`. Agency subscription records are excluded before any currency handling. `totals()` refuses only a client, or source account, whose own transactions use one currency code with two exponents.
- **Absolute instants.** All receipt-precedence, effective-ordering, quote-eligibility and quote-age decisions use `utc_instant()`. Python compares datetimes that share one `tzinfo` object by wall-clock time and ignores `fold`.
- **Conversion.** Same-currency amounts are added exactly before the output bound applies. Snapshots at the same latest instant conflict when they quote different rates or when one snapshot ID names different sources. Otherwise the smallest (snapshot ID, source) supplies the provenance.
- **Public surface.** The additions are `Movement`, `MovementType`, `LedgerCalculation.movements`, `ReconciliationReason.DELIVERY_ID_SHARED` and `ReconciliationReason.PARENT_CYCLE`. Existing names and the AC1–AC5 outcomes are unchanged. One existing test, `test_calculation_rejects_foreign_records_and_inconsistent_exponents`, now asserts the exponent conflict through the affected client's totals, because R007-04 removes the batch-wide failure.

### Findings and regressions

All regressions are in `backend/tests/test_ledger_corrections.py`. The reviewed column was obtained by running that file in a temporary detached worktree at `0e4fca1`, with no other change: 15 failed and 1 passed. The passing case is the control quote that is usable at both times. The worktree was removed afterwards.

| ID | Regression | Reviewed `0e4fca1` | Corrected |
|---|---|---|---|
| R007-01 | `test_r007_01_renotified_refund_with_an_earlier_time_keeps_800_and_the_200_posting`, `test_r007_01_capture_and_settlement_keep_their_own_times` | Fail. Nets after each delivery were 100,000, 80,000, 80,000 and **10,000**: the re-notified 900.00 refund displaced the 200.00 refund. A second capture with an earlier time moved the sale to 08:30 UTC. | Pass. Net stays **80,000** with the 200.00 posting and its evidence. The re-notification is `conflicting_evidence`, the original 900.00 claim stays `exceeds_outstanding` at its first time, and an agreeing copy is a duplicate. Capture and settlement keep 09:00 and the next day. |
| R007-02 | `test_r007_02_late_earlier_effective_refund_is_traced_by_a_release_movement` | Fail. No journal; the 200.00 refund disappeared without a movement. | Pass. Nets 100,000, 80,000 and 10,000. Movements: posting `sale-1`, posting `refund-200`, release `refund-200` (`exceeds_outstanding`, triggered by `dlv-refund-900`), posting `refund-900`. Each call's journal extends the previous one. The final postings, states, reconciliation and totals are identical in all 6 delivery orders. |
| R007-03 | `test_r007_03_full_chargeback_reversal_and_full_refund_leave_net_zero`, `test_r007_03_partial_reversal_and_a_refund_that_still_exceeds` | Fail. Successive nets 100,000, 0, 0 and **100,000**. The partial case gave 40,000 instead of 0. | Pass. Final net **0** in all 24 orders, with captured, refunded, charged back and reversed each 100,000. A 400.00 reversal with a 400.00 refund gives 0; a 500.00 refund is `exceeds_outstanding` (net 40,000); a reversal beyond the debit is `reversal_exceeds_debit`. |
| R007-04 | `test_r007_04_other_agencies_and_clients_cannot_interrupt_a_valid_client` | Fail. The whole call raised `currency_exponent_conflict`. | Pass. The valid client totals 105,000 across two source accounts. The other agency's AAA (exponent 3) totals are available, and the mixed client is refused with `currency_exponent_conflict` while its per-account totals remain available. |
| R007-05 | `test_r007_05_signal_and_capture_sharing_a_delivery_id_post_one_sale_in_either_order` | Fail. Signal first gave no verified sale. | Pass. One 100,000 sale in both orders; the signal remains unverified; one `delivery_id_shared` item holds both records. |
| R007-06 | `test_r007_06_quote_eligibility_and_age_use_absolute_instants` (3 cases), `test_r007_06_ledger_orders_effective_and_receipt_times_by_instant` | Fail. A 06:10 UTC quote was used as of 05:30 UTC; a stale quote was reported missing; refunds were ordered by wall clock; the later-received capture claim was retained. | Pass. `missing`, `converted` and `stale` are identical for local and UTC inputs. The 05:40 UTC refund posts before the 06:10 UTC refund, and the first-received claim is retained. |
| R007-07 | `test_r007_07_capture_and_settlement_references_attach_to_one_sale` | Fail. A settlement with another source reference was reported as conflicting. | Pass. One sale carries both references. An amount difference is still `conflicting_evidence`. A correction keeps its actor, reason and source, and a restated reason is reconciled. |
| R007-08 | `test_r007_08_identical_retries_of_a_reused_delivery_id_form_one_discrepancy` | Fail. Three items for one discrepancy. | Pass. One item with three records, each delivery with a reconciliation outcome. Two different payloads give two items; a repeated conflicting claim under new delivery IDs gives one. |
| R007-09 | `test_r007_09_cycles_and_invalid_parent_kinds_go_to_reconciliation` | Fail. Cycle members and the refund of a refund stayed pending. | Pass. `parent_cycle` for both corrections, `invalid_parent` for the refund of a refund, `parent_missing` for the refund of an absent sale. A later sale resolves that refund. |
| R007-10 | `test_r007_10_same_currency_inputs_accumulate_exactly_in_every_order` | Fail. `invalid_amount` for the order `MAX_MINOR - 1`, `+1`, `-1`. | Pass. `MAX_MINOR - 1` in all 6 orders; an unrepresentable final sum is still refused; the ledger net is `MAX_MINOR - 1` in all orders of two corrections. |
| R007-11 | `test_r007_11_snapshots_differing_only_in_source_give_the_same_record_in_both_orders` | Fail. The recorded source depended on input order. | Pass. One snapshot ID with two sources is `conflicting` in both orders; distinct IDs at one rate select `fx-1` in both orders; the complete records are equal. |

### Commands and results (corrections)

Run from `backend/` with the same environment as above. The earlier 92 focused and 429 unit results are historical baselines.

| Check | Result |
|---|---|
| Regression file against the reviewed commit (temporary worktree) | 15 failed, 1 passed, as listed above. |
| `python -m pytest tests/test_revenue_ledger.py tests/test_ledger_money.py tests/test_ledger_corrections.py -q` | **108 passed** (46, 46 and 16). |
| `python -m pytest -m "not integration" -q` | **445 passed**, 279 deselected, no failures, errors or skips. |
| `python -m ruff check` and `python -m ruff format --check` on the six changed Python files; `python -m ruff check .` | Clean; 6 files already formatted. |
| `git diff --check` and control-character scan of the correction diff | Clean. |

The PostgreSQL cases remain deselected for the reasons given above; the owner's native `tracking_sys` was not accessed.

### Policy for owner confirmation (R007-02)

The smallest conflicting case: capture 1,000.00; refund A of 200.00 (effective at minute 20) posts; refund B of 900.00 with an earlier effective time (minute 10) then arrives. Both refunds cannot fit.

- **Implemented, consistent with A3:** deterministic recomputation. B posts and A is released through an explicit `release` movement. Net is 100.00 whatever the delivery order, and the journal keeps A's posting and its release.
- **Alternative:** commitment first. A, once posted, stays and B is reconciled. Net is 800.00 if A arrives first and 100.00 if B arrives first, so delivery order would choose the result, contrary to A3 and the AC3 permutation requirement.

The implemented option is recommended. The owner should confirm it before 007-B persists the journal. No finding remains open.

### Limitations added by the corrections

- `calculate()` recomputes the provisional calculation after each arrival, so cost grows quadratically. Measured locally: 100 records 0.09 s, 200 records 0.35 s, 400 records 1.51 s. 007-B should persist the journal and recompute only the affected transaction.
- The journal of one call extends the journal of the previous call only when each new record has a later receipt instant than the records already received.
- A posting can later be released. Downstream consumers must follow movements or re-read totals rather than cache provisional entries.

### Readiness for Spec 008

- **Usable now for synthetic attribution examples:** per-client, per-currency verified net in minor units; signed entries with operation, transaction and effective instant; the append-only movement journal, which gives refunds and late events an explicit, timestamped change to allocate; unverified and excluded records kept apart from eligible revenue.
- **Still needed:** implemented 006 identity and journey contracts to link a sale to touchpoints (the ledger deliberately carries no person reference); persisted movements, concurrency and finance-read permissions from 007-B; identity association and attribution handoffs from 007-C; a reporting currency and rate source (Q-006) before allocations combine currencies.
- **Q-007 choices for the owner:** lookback window length and whether it is measured from the sale's effective instant; how direct or unknown traffic receives credit; the attribution timezone and the tie rule for equal timestamps; whether a refund or chargeback reduces credit proportionally or by touchpoint; and how late events and released postings re-run allocations under a versioned model.
