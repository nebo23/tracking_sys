# Specification 008-A evidence

Date: 2026-11-15. Authority: D-046, with corrections under D-047 (see [Pre-PR corrections](#pre-pr-corrections-2026-11-15), which supersede the statements marked below). Branch `codex/spec-008-attribution-engine`, local commit only. Nothing was pushed, and no PR was created or updated.

## Scope delivered

- `backend/app/attribution/` is a provider-independent, in-memory calculation that uses only existing dependencies. It has no table, migration, HTTP route, identity matching, live provider or dashboard.
- Journeys are synthetic, authorized touchpoint snapshots. Each test client has its own isolated journey. Revenue comes from the real 007-A contract: `app.ledger.calculate()` and its movement journal.
- `backend/tests/test_attribution.py` contains 27 acceptance tests and `backend/tests/test_attribution_corrections.py` 16 regressions.

## Contract

| Name | Content |
|---|---|
| `ModelVersion` | `version_id`, `model` (`first_click`, `last_click`, `linear`), `window` (default 30 days, must be positive) and `rules` (`008-A.1`). Each version is immutable. |
| `Touchpoint` | Stable `touchpoint_id`; agency, client and person scope; `EvidenceClass`; `occurred_at`; the current 006 `Association`; the current 003-B attribution `ConsentState`; and optional `source`, `campaign_ref`, `content_ref` and `link_ref`. A campaign interaction requires a campaign or link reference. A direct visit must have neither. |
| `EvidenceClass` | `campaign_interaction`, `direct_visit` or `aggregate_metric`. This enum is separate from `app.ledger.EvidenceClass`. |
| `Conversion` | A lead, or a sale that references one ledger transaction by its source account and sale operation ID. `effective_at` is the original sale instant. `sale_conversion()` builds a sale conversion from a posted `Transaction`. Superseded: `sale_state()` now returns the authoritative `SaleState` (currency, sale instant and exact net), which anchors the run. |
| `CreditAllocation` | Recipient (`campaign`, `direct` or `unknown`), basis, model, stable position, an exact `Fraction` share, and `amount` (a `Money` value for a sale, `None` for a lead). It also carries the credited touch and its references, and the rule, for example `linear/campaign`. |
| `AttributionRun` | One revision of one conversion under one model version. It holds the status, basis, ordered eligible touchpoint IDs, verified net, allocations, excluded touches with reasons, window bounds, ledger position, causes and signed `CreditDifference` values against the previous revision. |
| `AttributionHistory` | Keeps every revision for each agency, client, conversion and model version. Recalculating identical inputs returns the existing revision. |
| `IncrementalAttribution` | Consumes the receipt journal (`ledger_feed()` items) and journey updates in atomic steps. The checkpoint, the last completed receipt, advances only after the injected `commit` returns. |

## Rules as implemented (D-046)

1. First Click, Last Click and Linear are calculated independently, and results are never summed across models. A lead has one unit of credit, split into exact shares. A sale uses the verified net of its own transaction in its original currency and integer minor units. A purchase signal or manual declaration never posts in the ledger, so the run reports `no_verified_revenue` with no allocations.
2. The window is `[conversion - window, conversion]`, inclusive at both ends, and instants are compared in UTC. Eligible touches are ordered by instant and then by touchpoint ID. Retries of one touchpoint ID with identical content count once. Records of one ID that disagree are excluded as `conflicting_records`. Distinct IDs with the same content count separately.
3. A touch is eligible only when it is assigned to the person, its attribution consent is `granted`, and it is not an aggregate metric. Touches from another agency, client or person are ignored and never listed in the run. Sales in different source accounts stay separate even when they share an operation ID.
4. Eligible campaign interactions take precedence. A direct visit alongside a campaign is listed as `direct_superseded_by_campaign`. Without a campaign interaction, an eligible direct visit receives the credit (`direct_fallback`). Without either, unknown receives all of it (`unknown_fallback`).
5. Linear amounts use largest remainder. Equal remainders go to the earlier touch in the stable order.
6. Superseded by the corrections: the outcome now also includes the sale state, window, eligible touches and exclusions. A new revision is recorded only when the outcome (status, basis, net and allocations) changes. This happens when the transaction net changes, when a late eligible touch arrives, or when a consent withdrawal or ownership correction removes a touch. The window stays anchored to the original sale instant. Each revision names its causes (`revenue_changed` or `touches_changed`) and the signed share and minor-unit difference for each changed recipient. A changed model version starts its own history and leaves the earlier history unchanged.

## Acceptance cases

| Case | Tests | Result |
|---|---|---|
| Lead versus sale | `test_lead_credit_is_one_unit_split_into_exact_shares`, `test_sale_uses_the_verified_net_of_its_ledger_transaction`, `test_unverified_purchase_evidence_supplies_no_revenue` (purchase signal and manual declaration) | Lead: First A=1, Last B=1, Linear 1/2 each; three touches get 1/3 each. Sale of 100.00: A 100.00, B 100.00, 50.00 each. Unverified evidence: no transaction, `no_verified_revenue`, no allocations. |
| Direct, unknown and scope | `test_campaign_precedes_direct_and_direct_precedes_unknown`, `test_ineligible_evidence_cannot_identify_a_buyer`, `test_repeated_identifiers_in_other_scopes_supply_no_touchpoints`, `test_source_accounts_keep_repeated_transaction_ids_apart`, `test_retries_count_once_and_distinct_touches_with_one_content_count_separately`, `test_conflicting_records_of_one_touchpoint_are_excluded` | A campaign followed by direct credits the campaign. Direct-only credits direct. No eligible evidence credits unknown 100.00 under every model. Denied, withdrawn and unknown consent, ambiguous, unresolved and reassigned ownership, and aggregate views are all excluded. Identical IDs in another agency, client or person supply nothing. `sale-1` in two source accounts gives 50.00 and 330.00 per touch. |
| Time and precision | `test_window_is_inclusive_at_both_ends_in_utc`, `test_equal_instants_break_ties_by_touchpoint_id`, `test_one_minor_unit_goes_to_the_first_touch_in_stable_order`, `test_allocations_always_sum_to_the_net_and_ignore_input_order` | A touch exactly 30 days earlier and one at the conversion instant are included. Touches 1 µs before the window and 1 µs after the conversion are excluded. The same instants written at +02:00 and −05:00 give identical results. Equal instants are ordered by ID. 0.01 splits as 0.01/0.00, 1.00 across three touches as 0.34/0.33/0.33, and 0.005 (exponent 3) as 3/2. A seeded check of 200 random journeys under each model sums to the net exactly and does not depend on input order. |
| Real ledger replay | `test_refund_reduces_the_linear_allocation_of_each_touch`, `test_resuming_from_movement_two_equals_full_replay`, `test_incremental_consumer_matches_fresh_calculation_after_every_record`, `test_checkpoint_advances_only_after_the_allocation_commit`, `test_a_journal_gap_is_refused_without_any_change` | A 1,000.00 sale with a 200.00 refund gives 400.00 per touch. In the 007-A equal-receipt case, the consumer resumes from movement 2, applies movements 3 and 4, and reaches 50.00 per touch, equal to the full replay under all three models. Re-applying the journal or its suffix changes nothing. After each of six records, each applied twice, the incremental result equals a fresh calculation. A failed commit leaves the checkpoint, the net and the runs unchanged, and the retry applies each movement once. A gap is refused. |
| Revisions and evidence | `test_late_touch_creates_a_revision_that_explains_the_difference`, `test_a_changed_model_version_keeps_the_earlier_history`, `test_full_refund_revises_every_allocation_to_zero`, `test_withdrawal_and_ownership_correction_remove_matched_touches`, `test_identical_inputs_reproduce_identical_runs`, `test_contract_inputs_are_validated` | Under Last Click, a late B moves 100.00 from A to B in revision 2 (B +1/+10,000, A −1/−10,000). Identical inputs and touches outside the window return the same revision. A 7-day version has its own history, and the 30-day history is preserved. A full refund gives 0.00 each, a difference of −500.00 each. A consent withdrawal and then an ownership correction move credit to A and then to unknown. |

## Worked example: before and after the refund

The journey is the real 007-A equal-receipt case from `_tie_log()`. Touch A (campaign, 3 days before the sale) and touch B (campaign, 1 day before) are assigned to the person, with consent granted. These are the actual `IncrementalAttribution` outputs. Amounts are in AAA (exponent 2).

Ledger journal (`app.ledger.calculate()`):

| Sequence | Operation | Movement | Minor units | Trigger | Reason |
|---|---|---|---|---|---|
| 1 | `sale-1` | posting | +100,000 | `dlv-sale-1` | — |
| 2 | `refund-200` | posting | −20,000 | `dlv-b` | — |
| 3 | `refund-200` | release | +20,000 | `dlv-a` | `exceeds_outstanding` |
| 4 | `refund-900` | posting | −90,000 | `dlv-a` | — |

Allocations after each step:

| Step | Net | First Click | Last Click | Linear | Linear difference |
|---|---|---|---|---|---|
| Sale applied (checkpoint 1) | 1,000.00 | A 1,000.00 | B 1,000.00 | A 500.00, B 500.00 | — |
| Refund 200.00 (checkpoint 2) | 800.00 | A 800.00 | B 800.00 | A 400.00, B 400.00 | −100.00 each |
| Resume: movements 3–4 (checkpoint 4) | 100.00 | A 100.00 | B 100.00 | A 50.00, B 50.00 | −350.00 each |
| Fresh full replay of the log | 100.00 | A 100.00 | B 100.00 | A 50.00, B 50.00 | equal |

Each step records a new revision with cause `revenue_changed`. The window stays [2026-10-02 09:00Z, 2026-11-01 09:00Z], anchored to the sale.

## Commands and results

Run from `backend/` with the project virtual environment (`C:\Code\Tracking-system\.venv`).

| Check | Result |
|---|---|
| `python -m pytest tests/test_attribution.py -q` | **25 passed.** |
| `python -m pytest tests/test_attribution.py tests/test_revenue_ledger.py tests/test_ledger_money.py tests/test_ledger_corrections.py -q` | **136 passed** (25 attribution and 111 ledger). |
| `python -m pytest -m "not integration" -q` | **473 passed**, 279 deselected (integration tests need the disposable database). No failures, errors or skips. |
| `python -m ruff check app/attribution tests/test_attribution.py` and `python -m ruff check .` | All checks passed. |
| `python -m ruff format --check app/attribution tests/test_attribution.py` | 3 files already formatted. |
| `git diff --check` | Clean. |
| Mutation check (temporary script, not kept) | All 8 engine mutations were caught: the remainder tie sent to the last touch, an exclusive window start or end, the checkpoint advanced before the commit, direct counted with campaigns, retried movements re-applied, the ID tie-break reversed, and conflicting records kept. The first ID tie-break fixture did not catch its mutation, so it was strengthened before the final run. |

Exclusions: integration tests were not run because this slice adds no database code. The native `tracking_sys` database was not touched.

## Limitations and remaining dependencies for live use

- **006 identity and journey.** Touchpoints, associations and consent states are synthetic inputs. The live journey builder, the `journey_revision` that marks a run stale, and person-level consent reads must come from the implemented 006 contracts.
- **007-B persistence.** The checkpoint, history and `commit` are in memory. Durable receipt positions, the atomic write of a run together with its checkpoint, concurrency and finance-read permissions belong to 007-B.
- **007-C association.** The ledger carries no person reference. A sale conversion names its person synthetically until 007-C associates sales with identity keys.
- **Revision granularity (superseded by R008-04 and R008-05).** Each `apply()` call is one step, so a caller that splits one received record's movements across calls records an intermediate revision. Current allocations are unaffected. Callers should pass complete journal suffixes. A change in excluded touches alone does not create a revision.
- **Currency.** Allocations stay in the transaction's original currency. Combined reporting needs Q-006 (reporting currency and rate source).

## Decisions still open for the owner

- Production defaults: the default model and window, and whether a product default other than 30 days is needed.
- Whether reports freeze after a cutoff, or later eligible touch evidence keeps creating revisions indefinitely. The synthetic slice always revises.
- The weighting of chargebacks and corrections in reports. They currently change the net like refunds.
- Publication of this slice (push and PR) under D-012.

## Pre-PR corrections (2026-11-15)

Authority: D-047. The reviewed application commit is `3d772d1` and the findings are in the [pre-PR review](pre-pr-review-2026-11-15.md). Local commit only; nothing was pushed.

### Contract changes

- **Receipt journal.** `ledger_feed(log)` turns a 007-A receipt log into `JournalItem` values. A ledger receipt is the atomic unit. Each receipt has one item per movement, or a single item without a movement, and carries `receipt`, `index` and `count`. The closing item (`index == count`) carries the authoritative `SaleState` after the receipt for every transaction the receipt moved or changed: scope, sale operation ID, currency, sale effective instant and exact net. Completion therefore comes from the authoritative input, not from page endings or equal timestamps. The feed is built from `app.ledger.calculate()` over each receipt prefix.
- **Consumer.** `IncrementalAttribution.apply(items)` coalesces identical items. A different item at a known position is refused as `journal_mismatch`, and a missing position as `journal_gap`, with no state change in either case. Items of an incomplete receipt are buffered and never published. Each completed receipt is accumulated with exact integers, checked against its closing states, and yields its own revisions, even when several receipts arrive in one page. The runs of one call are committed together, and the checkpoint (the last completed receipt) advances only afterwards. A sale is anchored to the authoritative sale instant in its `SaleState`. Re-registering a corrected sale conversion is accepted. A consumer attached to a populated history publishes nothing for a sale until it has replayed to the recorded position.
- **Registry.** `AttributionHistory` registers conversions on writes and validates them on reads and writes. A conversion ID keeps one identity (person, kind and ledger transaction, plus the instant for a lead). A scoped sale belongs to one conversion: `sale_association_conflict` for another person, `sale_already_registered` for the same person. A model version ID has one definition across the whole history (`model_version_conflict`). A sale keeps its currency, including the exponent (`currency_changed`). Its ledger position never decreases (`stale_ledger_position`), and a different state at the same position is refused (`ledger_position_conflict`).
- **Run view.** `attribute()` takes `sale=SaleState` in place of `verified_net=Money`, and `sale_state(ledger, conversion)` replaces `verified_net()`. The outcome that decides a new revision now includes the sale state, window end, eligible touches with their content, and excluded touches with reasons. Causes add `sale_time_changed` and `evidence_changed`. Differences are keyed by recipient, touchpoint and source, campaign, content and link references, so a reassigned touch books −credit under its old campaign and +credit under the new one. `Touchpoint.occurred_at`, `Conversion.effective_at` and `SaleState.effective_at` are stored as UTC instants. An aware datetime that cannot be expressed in UTC is refused with the field's `invalid_*` code. A net at or above the `Money` bound yields a `net_out_of_range` revision without allocations. A window that reaches before the earliest representable instant starts there (`EARLIEST_INSTANT`). No instant can precede it, so the inclusive rule is unchanged.

### Findings, regressions and results

Regressions are in `backend/tests/test_attribution_corrections.py`. The module imports only names that existed at `3d772d1` and reaches the corrected interfaces through an adapter. At `3d772d1` it delivers raw movements, and after the correction it delivers journal items. The same file was run against an extracted copy of `3d772d1` and against the correction.

| Finding | Regression | At `3d772d1` | After the correction |
|---|---|---|---|
| R008-01 | `test_r008_01_one_scoped_sale_is_credited_once_per_model` | Fail: a second conversion for another person was accepted. Each model credited 200.00 in total (100.00 to `tp-a`, 100.00 to `tp-c`). | Pass: `sale_association_conflict` for another person, `sale_already_registered` for the same person, and an idempotent retry. Each model credits 100.00 once. The same sale reference in a second source account is credited 70.00 independently. |
| R008-02 | `test_r008_02_confirmed_capture_time_reanchors_the_sale` | Fail: re-registering the corrected conversion raised `conversion_conflict`, and the Nov 2 touch kept 100.00. | Pass: the capture receipt carries no movement but closes with the Nov 1 sale instant. The Nov 2 touch moves to `after_conversion` and unknown receives 100.00 under every model, matching a fresh calculation. Revision 2 still shows `tp-nov2` 100.00 with a window ending Nov 3. The cause is `sale_time_changed`. |
| R008-03 | `test_r008_03_stale_snapshots_cannot_restore_an_earlier_balance` and `test_r008_03_a_consumer_on_a_populated_history_publishes_no_spurious_zero` | Fail: the position-1 snapshot was accepted after position 2, and a restarted consumer published three new zero-revenue revisions at position 0. | Pass: `stale_ledger_position` is raised and the balance stays at 80.00. A journey update at position 2 is accepted (credited 100.00, 80.00, 80.00). A restarted consumer on the populated history adds no revision and ends with the same runs. |
| R008-04 | `test_r008_04_each_receipt_keeps_its_revision_in_one_batch` | Fail: one batch gave revisions for nets [none, 100.00] only, while separate deliveries gave [none, 100.00, 80.00, 100.00]. | Pass: every page split gives [none, 100.00, 80.00, 100.00], with Linear differences +50.00/+50.00, −10.00/−10.00 and +10.00/+10.00. The per-campaign report rebuilt from differences equals the fresh calculation. |
| R008-05 | `test_r008_05_paged_receipt_converges_without_a_negative_balance` | Fail: `invalid_net` when movement 3 (−100.00) arrived alone. In the example run, the next page then raised `movement_gap`. | Pass: for all 16 page splits of the 5 journal items, with a failed first commit on each page that commits, a retry and a repeated delivery, the consumer reaches checkpoint 4, net 0.00, no buffered items and no negative published amount. The result equals the fresh calculation under every model. |
| R008-06 | `test_r008_06_a_non_winning_touch_leaves_the_current_view` (consent and ownership) | Fail: the earlier run was returned unchanged, so B still looked eligible. | Pass: revision 2 keeps A's 100.00, excludes B as `consent_not_granted` or `association_not_assigned`, has no differences and has cause `touches_changed`. Revision 1 still lists A and B. |
| R008-07 | `test_r008_07_reassigned_campaign_transfers_credit_in_the_differences` | Fail: revision 2 had no causes and no differences. A report kept 100.00 on campaign A. | Pass: `campaign-tp-a` gets −1 share and −100.00, `campaign-c` gets +1 share and +100.00, content references `post-tp-a` and `post-c`, and the cause is `evidence_changed`. The lead version moves exactly one share. The rebuilt report equals the fresh allocations. |
| R008-08 | `test_r008_08_identical_copies_within_one_delivery_coalesce` and `test_r008_08_mismatched_replay_and_gap_are_refused_without_change` | Fail: two identical copies raised `movement_gap`. A different ledger prefix (90.00 capture and 20.00 refund) was accepted silently. A real gap raised `movement_gap`, the same code as a duplicate. | Pass: copies coalesce (net 100.00). The other prefix raises `journal_mismatch` and a hole raises `journal_gap`. Checkpoint, net and revisions are unchanged, and the genuine continuation reaches 50.00. |
| R008-09 | `test_r008_09_history_validates_conversions_and_model_definitions` | Fail: a conversion with the same ID but another person, transaction and account read the original run, and a redefined model version ID was accepted. | Pass: `conversion_mismatch` on `latest`, `revisions` and `calculate`. `model_version_conflict` on a read and on another conversion. Legitimate reads return the recorded run. |
| R008-10 | `test_r008_10_unrepresentable_intermediate_receipt_recovers` | Fail: `LedgerInputError: invalid_amount` while adding +1 to `MAX_MINOR - 1`; the checkpoint stayed at 0. | Pass: the statuses are `no_verified_revenue`, `complete`, `net_out_of_range` (receipt 2, exact net `MAX_MINOR`) and `complete`. The final Linear allocation is 5×10²⁹ and 5×10²⁹ − 1 minor units, summing to the ledger net of `MAX_MINOR - 1` and equal to the fresh calculation. |
| R008-11 | `test_r008_11_corrected_repeated_local_hour_is_a_new_revision` | Fail: the corrected New York 01:30 (second occurrence) reused the previous run at 05:30 UTC. | Pass: revision 2 identifies 06:30 UTC with cause `evidence_changed`. The same instant written in UTC returns revision 2 unchanged. |
| R008-12 | `test_r008_12_currency_change_is_refused_before_a_revision` | Fail: 10.000 BBB replaced 100.00 AAA without an error. | Pass: `currency_changed` for BBB and for AAA with exponent 3. The history keeps only the valid revision. |
| Window boundary | `test_window_boundary_at_the_earliest_representable_instant` | Fail: raw `OverflowError: date value out of range` for `timedelta.max`. | Pass: `window_start` is the earliest representable instant, both for `timedelta.max` with a 2026 lead and for a 30-day window ending on 0001-01-02. A touch whose offset cannot be expressed in UTC is refused as `invalid_occurred_at`. The 30-day inclusive boundary is unchanged. |

At `3d772d1` the regression file gave **16 failed** and nothing passed. The existing attribution and ledger tests of that commit gave **136 passed**.

### Required numerical demonstrations

| Statement | Evidence (actual output) |
|---|---|
| One sale of 100.00 credits exactly 100.00 per model, even when registered under two IDs | Before: each model credited 200.00 in total. After: the second registration is refused and each model credits 100.00 (`tp-a`). |
| Correcting the sale date removes credit from an interaction after the capture | After: the Nov 2 touch goes from 100.00 to 0.00, and unknown receives 100.00 at the Nov 1 anchor. |
| After a 20.00 refund of a 100.00 sale, an old record does not restore 100.00 | After: the position-1 snapshot is refused with `stale_ledger_position` and the latest balance stays at 80.00. |
| Batched and separate deliveries give the same balance and change history | Before: [none, 100.00] in one batch against [none, 100.00, 80.00, 100.00] separately. After: [none, 100.00, 80.00, 100.00] for every split. |
| Moving a touch from campaign A to C transfers its credit in the differences | After: A −100.00 and C +100.00. The report rebuilt from signed differences equals the fresh calculation. |

Paged refund replay (capture 100.00, refund 100.00, reversal 100.00, then chargeback 100.00, with the last receipt's two movements split across pages): at `3d772d1`, page 1 raised `invalid_net` and page 2 raised `movement_gap`, leaving the checkpoint at 0. After the correction, page 1 ends at checkpoint 3 with net 0.00 and 1 buffered item, and page 2 ends at checkpoint 4 with net 0.00 and nothing buffered.

### Updated existing checks

These checks in `backend/tests/test_attribution.py` documented superseded behavior and were replaced by the approved behavior:

- Consumer tests now feed `ledger_feed()` items. The checkpoint and `ledger_position` count receipts, so the equal-receipt case ends at 3 instead of movement 4.
- `test_checkpoint_advances_only_after_the_allocation_commit` now expects one revision per receipt within a page (four revisions, not three).
- The gap test expects `journal_gap`.
- A late out-of-window touch now records a revision with `touches_changed` and no differences (R008-06).

Added checks: `test_a_closing_state_that_disagrees_with_its_movements_is_refused` and `test_journal_items_and_feeds_are_validated`.

### Commands and results (corrections)

Run from `backend/` with the project virtual environment. The owner's native database was not used.

| Check | Result |
|---|---|
| Regression file against an extracted copy of `3d772d1` | **16 failed** (the baseline). That copy's own attribution and ledger tests: **136 passed**. |
| `python -m pytest tests/test_attribution.py tests/test_attribution_corrections.py -q` | **43 passed** (27 acceptance and 16 regression). |
| Attribution and ledger tests (`test_attribution.py`, `test_attribution_corrections.py`, `test_revenue_ledger.py`, `test_ledger_money.py`, `test_ledger_corrections.py`) | **154 passed** (43 and 111). |
| `python -m pytest -m "not integration" -q` | **491 passed**, 279 deselected. |
| `python -m ruff check` on the changed files and `python -m ruff check .`; `python -m ruff format --check` on the changed files | All checks passed; 4 files already formatted. |
| `git diff --check` | Clean. |
| Mutation check (temporary script, not kept) | All 10 mutations were caught: coalescing removed, catch-up skip removed, stale-position check removed, exclusions dropped from the outcome, provenance dropped from difference keys, sale registry disabled, sale-time anchoring ignored, net cross-check removed, currency check removed, and window clamp removed. The anchoring and net-check mutations were missed at first, so their tests were strengthened before the final run. |

### Open for review before publication

- A conflicting sale association is refused, and the first association stands. 006 and 007-C should decide whether such a conflict should instead make the sale ambiguous, which would credit unknown.
- Model version IDs are global to a history. The owner may prefer an agency scope.
- `ledger_feed()` recalculates every receipt prefix, so it is a reference adapter. 007-B must persist the receipt position, item count and closing sale states, as well as the buffered and applied items, which are in memory here.
- A `net_out_of_range` revision has no allocations. A reporting policy for that transient state is not yet defined.
- The earlier open decisions remain: production defaults, a report freeze cutoff, chargeback weighting and publication under D-012.
