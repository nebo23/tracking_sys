# Specification 008-A evidence

Date: 2026-11-15. Authority: D-046. Branch `codex/spec-008-attribution-engine`, local commit only. Nothing was pushed, and no PR was created or updated.

## Scope delivered

- `backend/app/attribution/` is a provider-independent, in-memory calculation that uses only existing dependencies. It has no table, migration, HTTP route, identity matching, live provider or dashboard.
- Journeys are synthetic, authorized touchpoint snapshots. Each test client has its own isolated journey. Revenue comes from the real 007-A contract: `app.ledger.calculate()` and its movement journal.
- `backend/tests/test_attribution.py` contains 25 acceptance tests.

## Contract

| Name | Content |
|---|---|
| `ModelVersion` | `version_id`, `model` (`first_click`, `last_click`, `linear`), `window` (default 30 days, must be positive) and `rules` (`008-A.1`). Each version is immutable. |
| `Touchpoint` | Stable `touchpoint_id`; agency, client and person scope; `EvidenceClass`; `occurred_at`; the current 006 `Association`; the current 003-B attribution `ConsentState`; and optional `source`, `campaign_ref`, `content_ref` and `link_ref`. A campaign interaction requires a campaign or link reference. A direct visit must have neither. |
| `EvidenceClass` | `campaign_interaction`, `direct_visit` or `aggregate_metric`. This enum is separate from `app.ledger.EvidenceClass`. |
| `Conversion` | A lead, or a sale that references one ledger transaction by its source account and sale operation ID. `effective_at` is the original sale instant. `sale_conversion()` builds a sale conversion from a posted `Transaction`, and `verified_net()` reads that transaction's net. |
| `CreditAllocation` | Recipient (`campaign`, `direct` or `unknown`), basis, model, stable position, an exact `Fraction` share, and `amount` (a `Money` value for a sale, `None` for a lead). It also carries the credited touch and its references, and the rule, for example `linear/campaign`. |
| `AttributionRun` | One revision of one conversion under one model version. It holds the status, basis, ordered eligible touchpoint IDs, verified net, allocations, excluded touches with reasons, window bounds, ledger position, causes and signed `CreditDifference` values against the previous revision. |
| `AttributionHistory` | Keeps every revision for each agency, client, conversion and model version. Recalculating identical inputs returns the existing revision. |
| `IncrementalAttribution` | Consumes the movement journal and journey updates in atomic steps. The checkpoint advances only after the injected `commit` returns. |

## Rules as implemented (D-046)

1. First Click, Last Click and Linear are calculated independently, and results are never summed across models. A lead has one unit of credit, split into exact shares. A sale uses the verified net of its own transaction in its original currency and integer minor units. A purchase signal or manual declaration never posts in the ledger, so the run reports `no_verified_revenue` with no allocations.
2. The window is `[conversion - window, conversion]`, inclusive at both ends, and instants are compared in UTC. Eligible touches are ordered by instant and then by touchpoint ID. Retries of one touchpoint ID with identical content count once. Records of one ID that disagree are excluded as `conflicting_records`. Distinct IDs with the same content count separately.
3. A touch is eligible only when it is assigned to the person, its attribution consent is `granted`, and it is not an aggregate metric. Touches from another agency, client or person are ignored and never listed in the run. Sales in different source accounts stay separate even when they share an operation ID.
4. Eligible campaign interactions take precedence. A direct visit alongside a campaign is listed as `direct_superseded_by_campaign`. Without a campaign interaction, an eligible direct visit receives the credit (`direct_fallback`). Without either, unknown receives all of it (`unknown_fallback`).
5. Linear amounts use largest remainder. Equal remainders go to the earlier touch in the stable order.
6. A new revision is recorded only when the outcome (status, basis, net and allocations) changes. This happens when the transaction net changes, when a late eligible touch arrives, or when a consent withdrawal or ownership correction removes a touch. The window stays anchored to the original sale instant. Each revision names its causes (`revenue_changed` or `touches_changed`) and the signed share and minor-unit difference for each changed recipient. A changed model version starts its own history and leaves the earlier history unchanged.

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
- **Revision granularity.** Each `apply()` call is one step, so a caller that splits one received record's movements across calls records an intermediate revision. Current allocations are unaffected. Callers should pass complete journal suffixes. A change in excluded touches alone does not create a revision.
- **Currency.** Allocations stay in the transaction's original currency. Combined reporting needs Q-006 (reporting currency and rate source).

## Decisions still open for the owner

- Production defaults: the default model and window, and whether a product default other than 30 days is needed.
- Whether reports freeze after a cutoff, or later eligible touch evidence keeps creating revisions indefinitely. The synthetic slice always revises.
- The weighting of chargebacks and corrections in reports. They currently change the net like refunds.
- Publication of this slice (push and PR) under D-012.
