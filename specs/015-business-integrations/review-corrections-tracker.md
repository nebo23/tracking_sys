# Spec 015 correction tracker

Prepared on 2026-11-22 under D-069. Source: [review report](../../reports/specs-001-015-review-2026-11-22.md), reviewed commit `db750d1b728f2ca352a999afe71c92a1b10730e1`. Execution instructions: [correction handoff](review-corrections-prompt.md). The report's IDs R001-R011 are cross-specification review IDs, not renumberings of historical R010/R011 specification findings.

All findings were **OPEN** at preparation. On 2026-11-22 the implementer reproduced all thirteen regression cases at `db750d1` in an isolated archive against the disposable PostgreSQL service (12 integration failures in 25.95 s and the Instagram failure, each at its intended assertion; [evidence](review-corrections-evidence.md#baseline-reproduction-at-db750d1)). D-070 decided the R001, R004 and schema questions the same day.

Independent partial review on 2026-11-22 at `a291bb6`: [review report](../../reports/spec-015-corrections-review-a291bb6-2026-11-22.md). The complete backend run produced **1,286 passed, 4 failed, 0 skipped**; the thirteen original regressions produced **9 passed and 4 failed**. R001-R008 and their adjacent cases pass. R009-R011 remain reproduced. The first eight rows stayed `FIXED_PENDING_REVIEW` until all corrections were complete and the final second pass was performed against that implementation head.

Final state on 2026-11-22: R009 to R011 were corrected on top of the reviewed head. The second review pass re-read all eleven findings against the final code, and the final run at `a42fba5` passed 1,309 backend cases with no failure or skip, plus 67 tracker unit and 44 Chromium and Firefox cases. Every row below is `CLOSED_VERIFIED`; the details are in the [final verification](review-corrections-evidence.md#final-verification) and the [second review pass](review-corrections-evidence.md#second-review-pass).

## Required closure evidence

Allowed status values: `OPEN`, `REPRODUCED`, `AWAITING_DECISION`, `FIXED_PENDING_REVIEW`, `CLOSED_VERIFIED`. Use `CLOSED_VERIFIED` only after the final second review pass. Add links to a concrete command/result or evidence section in every completed row; do not replace pending evidence with an unsupported checkmark.

| ID | Priority and affected spec | Baseline observation | Regression suffix after `test_review_` | Status | Fix commit and final evidence |
|---|---|---|---|---|---|
| R001 | P1 / 015 payments | Same signature permits test-to-live promotion and refund retargeting | `test_payment_cannot_become_verified_with_same_signature`; `refund_cannot_be_retargeted_with_same_signature` | CLOSED_VERIFIED | `b586287`; regression and adjacent cases (both regressions, declared-integration, refund-order and held-refund cases) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r001-p1-paymob-financial-meaning-from-signed-fields-only)) |
| R002 | P1 / 015 with 003/004 | Subject deletion violates `ck_bookings_valid_link` | `linked_booking_does_not_block_subject_erasure` | CLOSED_VERIFIED | `24097aa`; regression and adjacent cases (erasure, rollback, isolation and lifecycle expiry under the real role) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r002-p1-booking-detachment-and-subject-deletion-are-atomic)) |
| R003 | P1 / 015 with 003/004 | Linked total stays 1 after consent withdrawal | `booking_link_stops_on_withdrawal` | CLOSED_VERIFIED | `9e2e015`; regression and adjacent cases (withdrawal, denial, expiry, renewal, replay, merge and both lock orders) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r003-p1-booking-links-follow-the-current-attribution-consent)) |
| R004 | P1 / 015 WhatsApp | Unproven external number claim routes a signed message to the claimant | `whatsapp_number_requires_ownership_before_routing` | CLOSED_VERIFIED | `0813f4f`; regression and adjacent cases (hostile first claim, owner claim, transfer, database invariants and the operator command) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r004-p1-whatsapp-numbers-route-only-after-a-verified-binding)) |
| R005 | P2 / 015 payments | Malformed callback type returns 500 rather than 401 | `malformed_unsigned_callback_stays_401` | CLOSED_VERIFIED | `b4ed895`; regression and adjacent cases (malformed discriminators with valid and invalid signatures; both kinds still post) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r005-p2-malformed-paymob-callback-types-answer-the-uniform-401)) |
| R006 | P2 / 015 bookings | Two independent sources produce one booking | `two_booking_sources_do_not_merge_local_identifiers` | CLOSED_VERIFIED | `fe8ce8a`; regression and adjacent cases (cancellation and reschedule isolation, duplicates, out-of-order chains, other clients) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r006-p2-booking-identities-are-scoped-to-their-source)) |
| R007 | P2 / 015 CRM | Same event history gives different payment-verification states | `crm_payment_evidence_survives_out_of_order_events` | CLOSED_VERIFIED | `74bee1a`; regression and adjacent cases (all 24 orders, same-instant ties, omitted values, verified-sale match) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r007-p2-crm-optional-values-are-independent-of-delivery-order)) |
| R008 | P2 / 015 CRM | 501 open deals are reported as 500 | `crm_totals_cover_more_than_500_deals` | CLOSED_VERIFIED | `a291bb6`; regression and adjacent cases (1,203 deals, exact totals, complete traversal, permissions, cursor validation) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r008-p2-crm-totals-cover-the-full-authorized-scope)) |
| R009 | P2 / 015 WhatsApp | Malformed source type or timestamp rejects a valid sibling with 500 | `whatsapp_malformed_message_does_not_discard_valid_batch` (two cases) | CLOSED_VERIFIED | `806cd04`; regression and adjacent cases (malformed items first and last, shapes, extreme dates, unsigned batch, storage failure) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r009-p2-malformed-whatsapp-messages-stay-confined-to-themselves)) |
| R010 | P2 / 014 advertising | Limit-1 pagination loses the second currency for the same object | `ad_spend_pagination_preserves_both_currencies` | CLOSED_VERIFIED | `d2df620`; regression and adjacent cases (all levels, missing IDs, two currencies, limit 1, final and empty pages) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r010-p2-spec-014-spend-pages-follow-the-complete-grouping-key)) |
| R011 | P2 / 010 Instagram | Midnight resume returns November 24 after November 22 | `instagram_cursor_does_not_skip_day_at_midnight` | CLOSED_VERIFIED | `b769a29`; regression and adjacent cases (one and several midnights, resume, exhausted window, malformed cursors) pass in the final run at `a42fba5`; mutations caught; second pass closed ([evidence](review-corrections-evidence.md#r011-p2-spec-010-the-instagram-day-cursor-stays-stable-across-midnight)) |

The regression patch contains twelve integration cases and one unit case. R001 has two cases; R009 has two parameter values. Additional adjacent cases are specified in the handoff and should appear in the correction evidence.

The current command, results and per-finding review are in the [independent partial review](../../reports/spec-015-corrections-review-a291bb6-2026-11-22.md#independent-verification); implementation explanations and mutation results are in the [correction evidence](review-corrections-evidence.md). Final closure evidence remains pending for every row.

## Decisions required by the selected fixes

This table identifies decision risks, not pre-approved designs. Add a row only when a concrete implementation actually needs a decision under the working agreement; do not use it to block ordinary independent fixes.

| Area | Decision to resolve if required | Current state |
|---|---|---|
| R001 | Trustworthy environment/parent evidence and any change from callback-only verification | Decided by D-070 (2026-11-22): declared live integration IDs per source, and refund/void binding to the signed order ID; callback-only verification is kept and the shared order is confirmed by the live check |
| R004 | Actor and evidence that authorize a provider-number-to-client binding | Decided by D-070: a registration is a pending claim; a platform operator verifies one claim per number with `python -m app.whatsapp_binding` after an out-of-band check in Meta Business Manager; revocation and transfer go through the operator |
| Schema | Exact necessary changes to unmerged integration migrations or a corrective migration; populated upgrade and role grants | Decided by D-070: amend `0021`, `0023`, `0024` and `0025` in place on disposable PostgreSQL only (R001, R002, R004, R006, R007) |

## Repository follow-ups

| ID | Action | State at preparation | Closure evidence or remaining decision |
|---|---|---|---|
| A1 | Reconcile setup/API/migration documentation, provider selections and acceptance claims | DONE | `a42fba5`: README, backend README and setup guide name `0025_whatsapp` (63 application tables) and the generated 121 operations across 99 paths; index, next-review list, Spec 010/014/015 records and provider selections reconciled; open follow-ups kept open |
| A2 | Establish a minimal CI path using the approved stack; distinguish executed checks from proposed automation | NOT_CONFIGURED | No workflow, statuses or branch protection exist (checked on 2026-11-22); the minimal workflow on the pinned stack is described in `docs/engineering/quality-gates.md`; activation needs an owner decision; all recorded results are local runs |
| A3 | Preserve and assess the repeated ledger-calculation scaling risk without implementing unapproved 007-B | FOLLOW_UP | Bounded measurement in the [evidence](review-corrections-evidence.md#final-verification): `calculate()` 0.091 s, 3.984 s and 17.464 s at 100, 500 and 1,000 records, the journal 3.637 s at 100; the D-070 pre-pass costs milliseconds. Next decision: the 007-B design review with Q-004/Q-011 load figures; no service objective set |

The intentionally deferred 012/013 specifications and incomplete future product slices are not bugs to implement in this correction task. Live provider and rollout follow-ups remain as recorded.

## Final review and merge record

| Gate | Evidence |
|---|---|
| All eleven findings individually verified against final code | Done: all eleven rows `CLOSED_VERIFIED` above; R001-R008 also passed the independent partial review at `a291bb6` |
| Thirteen regressions and required adjacent cases | All 13 pass at `a42fba5`, with the adjacent cases listed per finding in the evidence |
| Full backend suite, including disposable DB and browser journeys | `a42fba5`: 1,309 passed, 0 failed, 0 skipped (808 unit and contract, 501 integration in four batches after a memory-pressure stop, including the 3 browser journeys) |
| Tracker unit and Chromium/Firefox suites | `a42fba5`: 67 unit and 44 Chromium/Firefox passed, none skipped |
| Ruff, dependency consistency and OpenAPI contract | `a42fba5`: Ruff check and format pass, `pip check` clean, the regenerated contract is byte-identical |
| Fresh/populated migrations and restricted-role checks, if changed | Fresh upgrade in every batch; populated `0019` predecessor upgrade with data intact; downgrade refusals and the runtime and lifecycle grants pass |
| Second review pass in R001-R011 order | Done by the implementer against the final code (evidence section); no finding reopened; independent partial review of R001-R008 at `a291bb6` |
| A1 reconciled; A2/A3 and unchanged follow-ups accurately disclosed | A1 done; A2 not configured, with the activation decision open; A3 measured and kept as a follow-up; live checks and the other follow-ups unchanged |
| GitHub required checks/reviews and current head/base verified | Observed with an authenticated read on 2026-11-22: `main` not protected, no required checks or reviews, no check runs or statuses, PR mergeable and clean on base `73efae9`; rechecked immediately before the merge |
| Final implementation SHA and published correction head | Code `50d739f`, tested at `a42fba5`; the published head adds only this documentation-only record |
| PR 13 merge SHA and observed merged state | Not merged at this commit. The merge of this head follows under D-069 with an expected-head check, and its observed SHA is reported to the owner; a commit cannot record the merge that includes it |

Do not fill a result before executing or observing it. The final merge follows D-069 and every condition in the handoff; it is not authorized while any R001-R011 finding remains open.
