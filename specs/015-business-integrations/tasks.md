# Tasks: 015-business-integrations
Status: Completed for review under D-066, D-067 and D-068 (all five acceptance criteria). See the [evidence](evidence.md).

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
