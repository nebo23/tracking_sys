# 015-business-integrations — Forms, bookings, payments, CRM, and WhatsApp
Status: Draft; implementation is not approved. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

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

## Required design contracts
Provider-specific subcontracts; each provider becomes an independently reviewable specification or PR slice.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md), [006-identity-journey](../006-identity-journey/spec.md), [007-revenue-ledger](../007-revenue-ledger/spec.md)

Specification 003 obligations (D-025): apply consent, collection minimization, and tombstone admission to imported subjects (E6), and keep payment data within the payment-processor row.

Open decisions: Q-002, Q-003, Q-010; select providers before implementation. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
