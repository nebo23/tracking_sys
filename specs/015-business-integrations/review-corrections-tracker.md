# Spec 015 correction tracker

Prepared on 2026-11-22 under D-069. Source: [review report](../../reports/specs-001-015-review-2026-11-22.md), reviewed commit `db750d1b728f2ca352a999afe71c92a1b10730e1`. Execution instructions: [correction handoff](review-corrections-prompt.md). The report's IDs R001-R011 are cross-specification review IDs, not renumberings of historical R010/R011 specification findings.

All findings below are **OPEN** at preparation. The application has not been corrected by this documentation handoff. The baseline failures were observed in the review; the implementer must reproduce them and record the final results.

## Required closure evidence

Allowed status values: `OPEN`, `REPRODUCED`, `AWAITING_DECISION`, `FIXED_PENDING_REVIEW`, `CLOSED_VERIFIED`. Use `CLOSED_VERIFIED` only after the final second review pass. Add links to a concrete command/result or evidence section in every completed row; do not replace pending evidence with an unsupported checkmark.

| ID | Priority and affected spec | Baseline observation | Regression suffix after `test_review_` | Status | Fix commit and final evidence |
|---|---|---|---|---|---|
| R001 | P1 / 015 payments | Same signature permits test-to-live promotion and refund retargeting | `test_payment_cannot_become_verified_with_same_signature`; `refund_cannot_be_retargeted_with_same_signature` | OPEN | Pending; authenticate environment and parent relationship |
| R002 | P1 / 015 with 003/004 | Subject deletion violates `ck_bookings_valid_link` | `linked_booking_does_not_block_subject_erasure` | OPEN | Pending; explicit erasure and lifecycle expiry |
| R003 | P1 / 015 with 003/004 | Linked total stays 1 after consent withdrawal | `booking_link_stops_on_withdrawal` | OPEN | Pending; withdrawal, expiry and consumers |
| R004 | P1 / 015 WhatsApp | Unproven external number claim routes a signed message to the claimant | `whatsapp_number_requires_ownership_before_routing` | OPEN | Pending; trusted ownership binding and valid enrollment |
| R005 | P2 / 015 payments | Malformed callback type returns 500 rather than 401 | `malformed_unsigned_callback_stays_401` | OPEN | Pending; malformed and valid callback types |
| R006 | P2 / 015 bookings | Two independent sources produce one booking | `two_booking_sources_do_not_merge_local_identifiers` | OPEN | Pending; identities, cancellation and reschedule isolation |
| R007 | P2 / 015 CRM | Same event history gives different payment-verification states | `crm_payment_evidence_survives_out_of_order_events` | OPEN | Pending; stage and optional-field ordering |
| R008 | P2 / 015 CRM | 501 open deals are reported as 500 | `crm_totals_cover_more_than_500_deals` | OPEN | Pending; full aggregates and complete detail traversal |
| R009 | P2 / 015 WhatsApp | Malformed source type or timestamp rejects a valid sibling with 500 | `whatsapp_malformed_message_does_not_discard_valid_batch` (two cases) | OPEN | Pending; per-item isolation and storage-error handling |
| R010 | P2 / 014 advertising | Limit-1 pagination loses the second currency for the same object | `ad_spend_pagination_preserves_both_currencies` | OPEN | Pending; complete grouping cursor |
| R011 | P2 / 010 Instagram | Midnight resume returns November 24 after November 22 | `instagram_cursor_does_not_skip_day_at_midnight` | OPEN | Pending; stable day cursor and truthful coverage |

The regression patch contains twelve integration cases and one unit case. R001 has two cases; R009 has two parameter values. Additional adjacent cases are specified in the handoff and should appear in the correction evidence.

## Decisions required by the selected fixes

This table identifies decision risks, not pre-approved designs. Add a row only when a concrete implementation actually needs a decision under the working agreement; do not use it to block ordinary independent fixes.

| Area | Decision to resolve if required | Current state |
|---|---|---|
| R001 | Trustworthy environment/parent evidence and any change from callback-only verification | No new protocol selected by this handoff |
| R004 | Actor and evidence that authorize a provider-number-to-client binding | No new onboarding/security policy selected by this handoff |
| Schema | Exact necessary changes to unmerged integration migrations or a corrective migration; populated upgrade and role grants | No new schema selected by this handoff |

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
| All eleven findings individually verified against final code | Pending |
| Thirteen regressions and required adjacent cases | Pending |
| Full backend suite, including disposable DB and browser journeys | Pending |
| Tracker unit and Chromium/Firefox suites | Pending |
| Ruff, dependency consistency and OpenAPI contract | Pending |
| Fresh/populated migrations and restricted-role checks, if changed | Pending |
| Second review pass in R001-R011 order | Pending |
| A1 reconciled; A2/A3 and unchanged follow-ups accurately disclosed | Pending |
| GitHub required checks/reviews and current head/base verified | Pending |
| Final implementation SHA and published correction head | Pending |
| PR 13 merge SHA and observed merged state | NOT_MERGED |

Do not fill a result before executing or observing it. The final merge follows D-069 and every condition in the handoff; it is not authorized while any R001-R011 finding remains open.
