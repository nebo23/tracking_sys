# Spec 015 correction tracker

Prepared on 2026-11-22 under D-069. Source: [review report](../../reports/specs-001-015-review-2026-11-22.md), reviewed commit `db750d1b728f2ca352a999afe71c92a1b10730e1`. Execution instructions: [correction handoff](review-corrections-prompt.md). The report's IDs R001-R011 are cross-specification review IDs, not renumberings of historical R010/R011 specification findings.

All findings were **OPEN** at preparation. On 2026-11-22 the implementer reproduced all thirteen regression cases at `db750d1` in an isolated archive against the disposable PostgreSQL service (12 integration failures in 25.95 s and the Instagram failure, each at its intended assertion; [evidence](review-corrections-evidence.md#baseline-reproduction-at-db750d1)). D-070 decided the R001, R004 and schema questions the same day.

Independent partial review on 2026-11-22 at `a291bb6`: [review report](../../reports/spec-015-corrections-review-a291bb6-2026-11-22.md). The complete backend run produced **1,286 passed, 4 failed, 0 skipped**; the thirteen original regressions produced **9 passed and 4 failed**. R001-R008 and their adjacent cases pass. R009-R011 remain reproduced. The first eight rows stay `FIXED_PENDING_REVIEW` until all corrections are complete and the final second pass is performed against that implementation head; this partial review does not clear the merge gate.

## Required closure evidence

Allowed status values: `OPEN`, `REPRODUCED`, `AWAITING_DECISION`, `FIXED_PENDING_REVIEW`, `CLOSED_VERIFIED`. Use `CLOSED_VERIFIED` only after the final second review pass. Add links to a concrete command/result or evidence section in every completed row; do not replace pending evidence with an unsupported checkmark.

| ID | Priority and affected spec | Baseline observation | Regression suffix after `test_review_` | Status | Fix commit and final evidence |
|---|---|---|---|---|---|
| R001 | P1 / 015 payments | Same signature permits test-to-live promotion and refund retargeting | `test_payment_cannot_become_verified_with_same_signature`; `refund_cannot_be_retargeted_with_same_signature` | FIXED_PENDING_REVIEW | `b586287`; both regressions and adjacent cases pass at `a291bb6`; D-070 trust assumptions remain recorded |
| R002 | P1 / 015 with 003/004 | Subject deletion violates `ck_bookings_valid_link` | `linked_booking_does_not_block_subject_erasure` | FIXED_PENDING_REVIEW | `24097aa`; erasure, lifecycle, rollback and grants pass at `a291bb6` |
| R003 | P1 / 015 with 003/004 | Linked total stays 1 after consent withdrawal | `booking_link_stops_on_withdrawal` | FIXED_PENDING_REVIEW | `9e2e015`; withdrawal, expiry, renewal, merge and concurrency cases pass at `a291bb6` |
| R004 | P1 / 015 WhatsApp | Unproven external number claim routes a signed message to the claimant | `whatsapp_number_requires_ownership_before_routing` | FIXED_PENDING_REVIEW | `0813f4f`; claim isolation, operator verification and valid enrollment pass at `a291bb6` under D-070 |
| R005 | P2 / 015 payments | Malformed callback type returns 500 rather than 401 | `malformed_unsigned_callback_stays_401` | FIXED_PENDING_REVIEW | `b4ed895`; malformed and valid callback cases pass at `a291bb6` |
| R006 | P2 / 015 bookings | Two independent sources produce one booking | `two_booking_sources_do_not_merge_local_identifiers` | FIXED_PENDING_REVIEW | `fe8ce8a`; source identity, cancellation, duplicates and reschedule isolation pass at `a291bb6` |
| R007 | P2 / 015 CRM | Same event history gives different payment-verification states | `crm_payment_evidence_survives_out_of_order_events` | FIXED_PENDING_REVIEW | `74bee1a`; partial-field permutations, tie-breaks and verified-sale matching pass at `a291bb6` |
| R008 | P2 / 015 CRM | 501 open deals are reported as 500 | `crm_totals_cover_more_than_500_deals` | FIXED_PENDING_REVIEW | `a291bb6`; full totals, all detail pages, permissions and tenant separation pass |
| R009 | P2 / 015 WhatsApp | Malformed source type or timestamp rejects a valid sibling with 500 | `whatsapp_malformed_message_does_not_discard_valid_batch` (two cases) | REPRODUCED | Both cases still return HTTP 500 at `a291bb6`; no fix commit |
| R010 | P2 / 014 advertising | Limit-1 pagination loses the second currency for the same object | `ad_spend_pagination_preserves_both_currencies` | REPRODUCED | USD group still unreachable at `a291bb6`; no fix commit |
| R011 | P2 / 010 Instagram | Midnight resume returns November 24 after November 22 | `instagram_cursor_does_not_skip_day_at_midnight` | REPRODUCED | November 23 still skipped at `a291bb6`; no fix commit |

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
| A1 | Reconcile setup/API/migration documentation, provider selections and acceptance claims | OPEN | Final migration head, generated operation count and reviewed status records |
| A2 | Establish a minimal CI path using the approved stack; distinguish executed checks from proposed automation | NOT_CONFIGURED | Record actual workflow/check results or the specific remaining activation decision |
| A3 | Preserve and assess the repeated ledger-calculation scaling risk without implementing unapproved 007-B | FOLLOW_UP | Bounded measurement and the next load/persistence decision; no invented production SLO |

The intentionally deferred 012/013 specifications and incomplete future product slices are not bugs to implement in this correction task. Live provider and rollout follow-ups remain as recorded.

## Final review and merge record

| Gate | Evidence |
|---|---|
| All eleven findings individually verified against final code | Pending; R001-R008 pass the partial review at `a291bb6`; R009-R011 remain reproduced |
| Thirteen regressions and required adjacent cases | Partial run at `a291bb6`: 9 review cases pass, 4 fail; final corrected-head run pending |
| Full backend suite, including disposable DB and browser journeys | Partial run at `a291bb6`: 1,286 pass, 4 fail, 0 skip; all 3 backend browser journeys pass; final run pending |
| Tracker unit and Chromium/Firefox suites | Pending |
| Ruff, dependency consistency and OpenAPI contract | Pass at `a291bb6`; repeat for final implementation changes |
| Fresh/populated migrations and restricted-role checks, if changed | Pending |
| Second review pass in R001-R011 order | Partial independent review at `a291bb6` recorded above; final all-corrections pass pending |
| A1 reconciled; A2/A3 and unchanged follow-ups accurately disclosed | Pending |
| GitHub required checks/reviews and current head/base verified | Observed open PR at head `a291bb6`, base `73efae9`; no returned statuses or PR-triggered workflow runs; final required-check/review verification pending |
| Final implementation SHA and published correction head | Partial implementation `a291bb6`; final implementation pending |
| PR 13 merge SHA and observed merged state | NOT_MERGED |

Do not fill a result before executing or observing it. The final merge follows D-069 and every condition in the handoff; it is not authorized while any R001-R011 finding remains open.
