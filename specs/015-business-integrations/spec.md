# 015-business-integrations — Forms, bookings, payments, CRM, and WhatsApp
Status: First round implemented for review under D-066 and D-067 (2026-11-21): 015-A (the revenue evidence store and the ledger read), 015-B (Paymob sources and signed processed callbacks, off by default) and 015-C (transaction CSV imports and manual declarations), against a synthetic Paymob-shaped sender and fixture tests only, with no call to Paymob and no real payment; see the [evidence](evidence.md), the [design note](design-015a.md), the [entry review](entry-review.md) and the [payments guide](../../docs/engineering/payments.md). AC1 and AC5 are met for this round; AC2 to AC4 (bookings, CRM, WhatsApp and ManyChat) stay open for later rounds. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
PDF-008,009,047,049,050,051,052,090; IDEA-03,12 candidates. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Select one integration for each approved workflow; map booking, payment, CRM, and WhatsApp events, with a defined import/manual fallback.

## Out of scope
Every integration at launch, OCR-based payment verification, treating AI message intent as payment, or automatic call recording.

## Acceptance criteria
1. Payment webhook signatures are verified; duplicates and out-of-order delivery are safe and reconcile with the revenue ledger.
2. Booking creation, cancellation, and rescheduling do not count as multiple sales; links to leads require identifier evidence.
3. A CRM stage transition does not become a paid transaction without an approved rule and supporting evidence.
4. WhatsApp/ManyChat referral metadata is used when available; missing data remains unknown, and comment/DM correlation requires a valid grant.
5. CSV imports include a preview, schema validation, row-level errors, and client authorization.

## Acceptance evidence (first round)
1. **AC1** (payment webhook signatures, duplicates, out-of-order delivery, reconciliation with the ledger): T-10 to T-21 and A1 in `backend/tests/integration/test_paymob.py`, the pure cases in `backend/tests/test_paymob_contract.py` (including the documented example string of Paymob's HMAC page), and T-01 to T-05 in `backend/tests/integration/test_revenue_evidence.py` for the stored ledger. The HMAC comparison, the exact-redelivery key, the failed and pending rules, the minimization step, the gate and the `finance:read` check are each backed by a caught mutation (M1 to M6 in the [evidence](evidence.md)). Met for Paymob against synthetic fixtures; a live callback check is a follow-up.
2. **AC2** (bookings): open for a later round with its own provider decision.
3. **AC3** (CRM stage transitions): open for a later round.
4. **AC4** (WhatsApp and ManyChat referral metadata): open for a later round.
5. **AC5** (CSV preview, schema validation, row-level errors, client authorization): T-30 to T-36 in `backend/tests/integration/test_revenue_imports.py` and the pure cases in `backend/tests/test_revenue_csv.py`, with the import idempotency and the unverified classification backed by caught mutations (M7, M8). Met.

## Required design contracts
Provider-specific subcontracts; each provider becomes an independently reviewable specification or PR slice.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md), [006-identity-journey](../006-identity-journey/spec.md), [007-revenue-ledger](../007-revenue-ledger/spec.md)

Specification 003 obligations (D-025): apply consent, collection minimization, and tombstone admission to imported subjects (E6), and keep payment data within the payment-processor row.

Open decisions: Q-002, Q-003, Q-010; select providers before implementation. The first payment provider is Paymob (D-066); the providers of the later rounds are not selected. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
D-066 (2026-11-21) set the scope of the first round (payments with Paymob and the CSV and manual fallback, synthetic and fixtures only), and D-067 (2026-11-21) approved decisions D1-D15 of the [entry review](entry-review.md) with amendment A1. The later rounds, the live Paymob check, native migration and deployment need their own decisions.
