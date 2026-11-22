# Tasks: 015-business-integrations
Status: Implemented under D-066 to D-068, with open review corrections under D-069. The historical implementation checks below do not close the findings of the [001-015 review](../../reports/specs-001-015-review-2026-11-22.md). Follow the [handoff](review-corrections-prompt.md) and [tracker](review-corrections-tracker.md); merge waits for their verified closure.

## Review correction completion

- [x] Save the review report and reusable regression patch in the repository.
- [x] Prepare the per-finding correction handoff and tracker under D-069.
- [x] Reproduce every R001-R011 case at `db750d1` in an isolated disposable environment ([evidence](review-corrections-evidence.md#baseline-reproduction-at-db750d1)).
- [x] Resolve concrete decisions needed by the selected fixes without blocking independent work (D-070).
- [x] Correct and verify all eleven findings, retaining regression and adjacent-case coverage ([evidence](review-corrections-evidence.md), [tracker](review-corrections-tracker.md)).
- [x] Reconcile A1 documentation and explicitly record A2/A3 repository follow-ups.
- [x] Run final suites and re-read all eleven findings against the final code (1,309 backend, 67 tracker unit and 44 browser cases at `a42fba5`; [second review pass](review-corrections-evidence.md#second-review-pass)).
- [ ] Publish verified corrections and update the existing PR 13 evidence. (The corrections are pushed; the PR description is updated right after this record.)
- [ ] Satisfy D-069 merge conditions, merge the reviewed head and record the observed merge SHA. (After this record; the merge SHA is reported to the owner.)

## Historical implementation tasks

- [x] Approve the scope and sources for forms, bookings, payments, crm, and whatsapp. (Payments and the CSV fallback: D-066 and D-067; bookings, CRM and WhatsApp: D-068; form tools are a follow-up.)
- [ ] Resolve Q-002, Q-003, Q-010; select providers before implementation and record the owner decision. (Paymob, Cal.com and WhatsApp selected under D-066 and D-068; the questions stay open.)
- [x] Verify dependencies: 009-connector-runtime, 006-identity-journey, 007-revenue-ledger (007-A consumed; 006 linking and 007-B are follow-ups).
- [x] Prepare applicable contracts and synthetic data/permission examples (the synthetic Paymob sender and the CSV fixtures).
- [x] Define independently reviewable local changes for the approved specification (015-A, 015-B, 015-C).
- [x] Implement the first approved slice (the first round: 015-A to 015-C).
- [x] Verify: Payment webhook signatures are verified; duplicates and out-of-order delivery are safe and reconcile with the revenue ledger.
- [x] Verify: Booking creation, cancellation, and rescheduling do not count as multiple sales; links to leads require identifier evidence.
- [x] Verify: A CRM stage transition does not become a paid transaction without an approved rule and supporting evidence.
- [x] Verify: WhatsApp/ManyChat referral metadata is used when available; missing data remains unknown, and comment/DM correlation requires a valid grant.
- [x] Verify: CSV imports include a preview, schema validation, row-level errors, and client authorization.
- [x] Update documentation, limitations, and untested assumptions (the evidence and the payments guide).
- [x] Present a reviewable result to the owner (the first-round pull request).
- [x] Obtain owner review and upload approval, then push and create or update a PR (D-012). (D-067 authorizes the pull request after successful verification.)
- [ ] Record owner acceptance before progressing to dependent work.
