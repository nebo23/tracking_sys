# 015-business-integrations — Forms, bookings, payments, CRM, and WhatsApp
Status: Implemented for review under D-066, D-067 and D-068 (2026-11-21): payments with Paymob, the revenue evidence store, CSV imports and manual declarations (first round), and Cal.com bookings, CRM stage changes through a provider-neutral signed webhook and WhatsApp referrals (second round), against synthetic senders and fixture tests only, with no provider call and no real payment. The initial AC1 to AC5 evidence is subject to the D-069 corrections; see the [evidence](evidence.md), the design notes ([first round](design-015a.md), [second round](design-015b.md)), the entry reviews ([first round](entry-review.md), [second round](entry-review-round2.md)), the [payments guide](../../docs/engineering/payments.md) and the [integrations guide](../../docs/engineering/integrations.md). Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Review status

Review update (2026-11-22, D-069): the acceptance evidence below describes the implementation at `db750d1`; the [cross-specification review](../../reports/specs-001-015-review-2026-11-22.md) subsequently found R001-R009 in this specification and R010/R011 in predecessors. These open findings supersede any implication that the existing passing acceptance tests establish merge readiness. Execute the [correction handoff](review-corrections-prompt.md), complete the [tracker](review-corrections-tracker.md), and apply its final verification and conditional merge requirements.
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

## Historical acceptance evidence
1. **AC1** (payment webhook signatures, duplicates, out-of-order delivery, reconciliation with the ledger): T-10 to T-21 and A1 in `backend/tests/integration/test_paymob.py`, the pure cases in `backend/tests/test_paymob_contract.py` (including the documented example string of Paymob's HMAC page), and T-01 to T-05 in `backend/tests/integration/test_revenue_evidence.py` for the stored ledger. The HMAC comparison, the exact-redelivery key, the failed and pending rules, the minimization step, the gate and the `finance:read` check are each backed by a caught mutation (M1 to M6 in the [evidence](evidence.md)). Met for Paymob against synthetic fixtures; a live callback check is a follow-up.
2. **AC2** (bookings without multiple sales; lead links only with identifier evidence): T-50 to T-55 in `backend/tests/integration/test_bookings_crm.py` and the pure cases in `backend/tests/test_integrations_contract.py`. Bookings never write revenue; every delivery order gives one booking; a link needs the pseudonymous subject token and granted attribution consent. Backed by caught mutations M11 to M14. Met for Cal.com and the signed webhook against synthetic senders.
3. **AC3** (no paid transaction from a stage change without an approved rule and evidence): T-56 to T-58 in `test_bookings_crm.py`; a won deal is verified only by a matching verified ledger sale and never writes evidence. Backed by mutation M15. Met.
4. **AC4** (referral metadata when available, unknown otherwise, correlation only with a valid grant): T-60 to T-64 in `backend/tests/integration/test_whatsapp.py` and `backend/tests/test_whatsapp_contract.py`; no conversation is correlated, because no grant exists before 006. Backed by mutations M17 to M19. Met for the WhatsApp Cloud API; ManyChat is a follow-up.
5. **AC5** (CSV preview, schema validation, row-level errors, client authorization): T-30 to T-36 in `backend/tests/integration/test_revenue_imports.py` and the pure cases in `backend/tests/test_revenue_csv.py`, with the import idempotency and the unverified classification backed by caught mutations (M7, M8). Met.

## Required design contracts
Provider-specific subcontracts; each provider becomes an independently reviewable specification or PR slice.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md), [006-identity-journey](../006-identity-journey/spec.md), [007-revenue-ledger](../007-revenue-ledger/spec.md)

Specification 003 obligations (D-025): apply consent, collection minimization, and tombstone admission to imported subjects (E6), and keep payment data within the payment-processor row.

Open decisions: Q-002, Q-003, Q-010; select providers before implementation. The first payment provider is Paymob (D-066); the providers of the later rounds are not selected. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
D-066 (2026-11-21) set the scope of the first round (payments with Paymob and the CSV and manual fallback, synthetic and fixtures only), and D-067 (2026-11-21) approved decisions D1-D15 of the [entry review](entry-review.md) with amendment A1. D-068 (2026-11-21) completed the specification with E1-E13 of the [second-round entry review](entry-review-round2.md). Live checks, the follow-ups outside the acceptance criteria, native migration and deployment need their own decisions.
