# Tasks: 015-business-integrations
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for forms, bookings, payments, crm, and whatsapp.
- [ ] Resolve Q-002, Q-003, Q-010; select providers before implementation and record the owner decision.
- [ ] Verify dependencies: 009-connector-runtime, 006-identity-journey, 007-revenue-ledger.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable PR slices once the repository is available.
- [ ] Implement the first approved slice.
- [ ] Verify: Payment webhook signatures are verified; duplicates and out-of-order delivery are safe and reconcile with the revenue ledger.
- [ ] Verify: Booking creation, cancellation, and rescheduling do not count as multiple sales; links to leads require identifier evidence.
- [ ] Verify: A CRM stage transition does not become a paid transaction without an approved rule and supporting evidence.
- [ ] Verify: WhatsApp/ManyChat referral metadata is used when available; missing data remains unknown, and comment/DM correlation requires a valid grant.
- [ ] Verify: CSV imports include a preview, schema validation, row-level errors, and client authorization.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Create or update a PR and push only after repository authorization.
- [ ] Record owner acceptance before progressing to dependent work.
