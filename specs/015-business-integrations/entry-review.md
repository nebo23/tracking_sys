# Specification 015 entry review: payments (Paymob) and the CSV and manual fallback

Prepared: 2026-11-21 on `claude/gallant-cray-b16xwk` from merged `main` at `73efae9` (PR 12; Spec 014 merged). Authority: D-066, preparation only. Status: **proposal**. D-066 records the owner's choices of 2026-11-21 for this first round of Spec 015:
- it covers payments and the CSV and manual fallback; bookings, CRM, WhatsApp and the other workflows are later rounds;
- Paymob is the first payment provider;
- the round runs against a synthetic Paymob-shaped sender and fixture tests only.

Decisions D1-D15 in section 6 are recommendations for the owner; their approval is to be recorded as D-067. This preparation contains no application code, migration or dependency. It makes no call to Paymob and involves no real payment. The [implementation handoff](implementation-prompt.md) carries the approved decisions to completion and a pull request.

## 1. Scope of this round

[Spec 015](spec.md) asks for one integration per approved workflow (bookings, payments, CRM, WhatsApp), with a defined import or manual fallback. This round takes two of its five acceptance criteria:
- **AC1.** Payment webhook signatures are verified; duplicates and out-of-order delivery are safe and reconcile with the revenue ledger.
- **AC5.** CSV imports include a preview, schema validation, row-level errors and client authorization.

AC2 (bookings), AC3 (CRM stage transitions) and AC4 (WhatsApp and ManyChat referral metadata) stay open for later rounds, each with its own provider decision.

**Specification 003 obligations (D-025).** These apply consent, collection minimization and tombstone admission to imported subjects (E6) and keep payment data within the payment-processor row. This round imports no person or subject, so E6 has nothing to admit. The obligation that remains is to keep payment data minimal under the `payments.processor_records` rule (D6, D12).

**Source features.** PDF-052 (payment integrations, MVP) and the import and manual fallback of the specification. PDF-008 (form tools), PDF-009 (inbound webhooks beyond payments), PDF-047 (booked calls), PDF-049 (CRM), PDF-051 (DM and chat), PDF-090 (automation tools), IDEA-03 and IDEA-12 wait for later rounds ([feature register](../../docs/product/feature-register.md)).

## 2. Sources

### 2.1 Official pages were not read in this preparation

As for Spec 014, this preparation environment cannot read provider documentation. Its network allows only two Meta hosts, and the page-reading tool fails to resolve external hosts. No Paymob page was read for this review. Section 2.2 lists what the repository already records. Section 2.3 lists the provider facts this design assumes. Phase 0 of the handoff verifies them against the official pages before any code relies on them. Each assumption below is marked as such; none is evidence.

### 2.2 Recorded sources

| ID | Source | Recorded finding | Where recorded |
|---|---|---|---|
| P-0 | [Paymob transaction callbacks](https://developers.paymob.com/paymob-docs/developers/transaction-callbacks) | A processed transaction POST callback differs from the browser response redirect. State comes from HMAC-verified processed callbacks; the redirect may never complete. The reference includes refund, partial refund, capture, void and order identifiers. | [Platform notes](../../research_notes/market-and-feasibility/platforms.md); [market report](../../reports/market-and-feasibility.md) |
| S-91 | [Paymob card tokens](https://developers.paymob.com/paymob-docs/developers/pay-with-saved-cards/create-card-token) (updated 2026-08-24) | Tokens and the masked PAN arrive through callbacks, and callbacks are verified with an HMAC. | [Privacy sources](../../research_notes/privacy-data-policy/sources.md); the `payments.processor_records` rule (stale) |
| S-89 | [PCI SSC FAQ 1154](https://www.pcisecuritystandards.org/faq/articles/Frequently_Asked_Question/for-pci-dss-can-sensitive-account-data-be-stored-before-authorization/) (2025-07) | Sensitive authentication data may not be stored after authorization, even if encrypted. | Same |
| S-90 | [Stripe integration security guide](https://docs.stripe.com/security/guide) (example) | Hosted checkout keeps card data off merchant servers; verify webhook signatures. | Same |

### 2.3 Facts to verify in Phase 0

The pages are on `developers.paymob.com` unless stated. "Record" means: add the page, its date and the finding to section 2.4, and apply a parameter-level difference in the design note.

| ID | Assumption used by this design | If the page differs |
|---|---|---|
| V-1 | Paymob sends a server-to-server "transaction processed" callback (POST, JSON with an `obj` transaction and a `type`) and a separate "transaction response" browser redirect (GET). Only the processed callback carries state this design trusts. | Record. If there is no signed server callback, D4 goes back to the owner. |
| V-2 | The processed callback carries an `hmac` query parameter: HMAC-SHA512, under the merchant's HMAC secret, of the concatenated values of a documented, ordered list of transaction fields. Booleans are written as `true` or `false`. The assumed list: `amount_cents`, `created_at`, `currency`, `error_occured`, `has_parent_transaction`, `id`, `integration_id`, `is_3d_secure`, `is_auth`, `is_capture`, `is_refunded`, `is_standalone_payment`, `is_voided`, `order.id`, `owner`, `pending`, `source_data.pan`, `source_data.sub_type`, `source_data.type`, `success`. | Use the documented algorithm, list, order and formatting; record. |
| V-3 | A transaction has `id`, `amount_cents` (minor units), `currency`, `created_at`, `success`, `pending`, `is_auth`, `is_capture`, `is_standalone_payment`, `is_voided`, `is_refunded`, `has_parent_transaction`, a parent reference, `order` (with `id` and `merchant_order_id`), `integration_id` and `source_data`. | Record and map (D5). |
| V-4 | Captures, refunds (including partial refunds) and voids each arrive as their own transaction callbacks that reference the original transaction. | Record. If they arrive only as flags on the original transaction, D5 and D7 go back to the owner. |
| V-5 | Paymob retries a callback that is not answered with a success status; the schedule is documented or observable. | Record; the idempotency of D7 holds either way. |
| V-6 | A callback body, with order items and billing data, stays well below 64 KiB. | Set the D13 bound from the documentation; record. |
| V-7 | `created_at` is an ISO 8601 timestamp; its offset or time zone is stated. | Record. If no offset is given, the zone of the merchant's region applies and D5 records it. |
| V-8 | The newer Intention (unified checkout) API keeps the same processed callback and HMAC. | Record. A different signature or payload for the newer API changes D4 and goes to the owner. |
| V-9 | Regions (Egypt, Saudi Arabia, United Arab Emirates, Oman, Pakistan) have their own base hosts and currencies. This round targets the Egypt region first. | Record. |
| V-10 | Chargebacks and disputes have no callback. | Record. If a callback exists, its mapping goes to the owner (D5). |
| V-11 | The merchant finds the HMAC secret in the Paymob dashboard and can replace it. | Record (D3). |
| V-12 | `source_data.pan` is a masked PAN or the last four digits, and the payload also carries billing and shipping data with personal fields. | Record; D6 discards them either way. |
| V-13 | Paymob's terms and the PCI scope of a platform that only receives callbacks (no card data entry). | Update the `payments.processor_records` rule and add `paymob.accept` (D12); record. |

### 2.4 Official sources read in Phase 0

To be completed by the handoff: one row per page with the URL, the date read, any last-updated date, and for each V row whether it was confirmed, corrected or not read.

## 3. Starting point

| Area | What exists | Where |
|---|---|---|
| Revenue ledger (007-A) | `calculate()` derives transactions, adjustments, reconciliation items and per-currency totals from `Evidence` records taken in receipt order, and `ledger_feed()` gives the append-only journal. Only `confirmed_capture` and `confirmed_settlement` post a sale. `manual_declaration` and `purchase_signal` never enter verified totals (A1). An `audited_correction` needs an actor, a reason and a source reference. Amounts are integer minor units per currency. The contract is in memory: no table, route or provider exists. | `backend/app/ledger/` |
| Consumers | 008-A attribution consumes a `LedgerCalculation` or the `ledger_feed` journal. 014-B enqueues conversions from a `LedgerCalculation` with synthetic journeys. | `backend/app/attribution/`, `backend/app/services/delivery.py` |
| Webhook intake (004) | Client-scoped `ingestion_sources` of kind `webhook` with a platform-generated secret, sealed under the D-025 keyring. Rotation keeps the previous secret for 24 hours. A Spec 004 signature scheme, per-source and per-peer rates, and deduplication apply. | `backend/app/services/collection.py`, [event collection guide](../../docs/engineering/event-collection.md) |
| Request bounds | Every POST, PUT, PATCH and DELETE body is limited to 16 KiB by the global `RequestBoundary` middleware. | `backend/app/api/middleware.py` |
| Access | `finance:read` with the explicit financial grant; Owner and Admin have financial access; read and ingest service keys. Manual financial writes "need an explicit policy in 007-B". | `backend/app/services/access.py`, [007 entry review](../007-revenue-ledger/entry-review.md) |
| Provider rules | `payments.processor_records` is stale (S-89 to S-91): provider IDs, brand, last four digits and expiry only; never a PAN, CVC or raw card posting. | `backend/app/privacy/providers.py` |
| Identity (006) | Designed, not implemented. No person or lead table exists. | [006 design](../006-identity-journey/design.md) |

## 4. Gaps and constraints

- **G1. No persisted evidence.** Payments must be stored to be reconciled. 007-B (persistence, finance-write permissions and reconciliation workflows) is not designed. This round needs the smallest piece of it: an append-only store of `Evidence` records, from which `calculate()` derives the ledger on read (D2).
- **G2. Paymob has no platform OAuth in this design.** Each client supplies its own merchant HMAC secret, and our endpoint receives callbacks. The connector runtime of 009 (OAuth, tokens, syncs) does not fit, and the 004 webhook source generates its own secret instead of accepting one (D3).
- **G3. Body bounds.** A CSV file and possibly a Paymob callback exceed the global 16 KiB bound (D13).
- **G4. Manual and imported entries are unverified.** Under 007-A A1, CSV rows and manual entries are declarations: they are shown, but never counted as verified revenue or delivered by 014 (D8, D9).
- **G5. No link to people.** A Paymob transaction is not linked to a lead or journey until 006. The ledger read is client-level, and attribution and conversion delivery keep their synthetic journeys.
- **G6. Live callbacks need HTTPS.** A Paymob account can only call a public HTTPS URL (020), so live intake is a follow-up with an owner sandbox account.

## 5. Proposed slices

1. **015-A, evidence store and ledger read.** An append-only receipt log of 007-A `Evidence` records per client, the ledger derived by `calculate()` on read, a `finance:read` route, and a service that gives 008-A and 014-B the client's calculation and journal. Migration `0020`.
2. **015-B, Paymob payments.** Client-scoped Paymob payment sources with the merchant's sealed HMAC secret. The public callback route verifies the documented HMAC, maps states to evidence, minimizes data and keeps diagnostics. The Paymob source type is off by default and gated by its rules. A synthetic Paymob-shaped sender and fixtures serve the tests. Migration `0021`.
3. **015-C, CSV import and manual declarations.** Preview and commit of transaction CSV files, and single manual declarations, both as unverified evidence with audit events. Migration `0022`.

Later rounds, each with its own decisions (section 8): bookings (Cal.com or Calendly), CRM, WhatsApp, automation webhooks, third-party form tools, Paymob API reads and backfill, and Stripe.

## 6. Decisions for the owner (D1-D15)

| ID | Decision | Recommendation | Alternative |
|---|---|---|---|
| D1 | Order and scope of this round | Complete 015-A, 015-B and 015-C in that order on one branch, against a synthetic Paymob-shaped sender and fixtures only (D-066). Push after each verified slice (D-051), and open one pull request against `main` at the end. Bookings, CRM, WhatsApp, automation webhooks, form tools, Paymob reads and Stripe stay later rounds. | Stop after 015-B. |
| D2 | Persisted evidence | An append-only `revenue_evidence` receipt log per client. **Contents:** the 007-A `Evidence` fields (delivery ID, source account, operation ID, kind, classification, amount in minor units and currency, effective time, server receipt time, parent operation, actor, reason, source reference), plus the intake provenance (Paymob source, CSV import or manual entry). **Ledger:** derived by `calculate()` over the client's records in receipt order on each read. **Duplicates:** an exact redelivery (same delivery ID and same content) is stored once; a reused delivery ID with other content is stored, so 007-A reports it for reconciliation. **Privileges:** `tracking_app` may only insert and read. **Deferred to 007-B:** persisted postings, movements, finance write workflows and audited corrections. | Pause Spec 015 and open the 007-B design review first. |
| D3 | Paymob source model | **Source:** a client-scoped `payment_sources` row (provider `paymob`, region `egypt` first, name, status), created by an Owner or Admin. **Secret:** the merchant's HMAC secret from the Paymob dashboard is entered once, sealed under the D-025 keyring and never returned. A new secret can be entered, and the previous one stays accepted for 24 hours (the 004 overlap). **Callback URL:** each source has one with an unguessable public key, which the client sets as Paymob's processed callback. **Not in this round:** OAuth, a Paymob API key and any outbound call. | Reuse the 004 `ingestion_sources` with a new kind, accepting a merchant-supplied secret. |
| D4 | Callback intake | `POST /payments/paymob/callback/{public_key}` is public. **Verification:** the `hmac` parameter is checked as documented (V-2) against the current and the previous secret, in constant time. A missing or invalid signature is answered 401 and nothing is stored, with the same answer for an unknown or disabled source. **Trusted channel:** only the processed callback; the browser response redirect is never evidence. **Answers:** a verified callback is answered 200, including duplicates and states that post nothing, so that Paymob stops retrying. **Rates:** per source and per peer, at the 004 trusted intake rate. **Diagnostics:** each verified callback leaves one row: source, delivery digest, receipt time and a closed outcome code. | Also store the raw payload, encrypted, for later re-mapping. |
| D5 | Mapping to 007-A evidence | Every rule is verified in Phase 0 (V-3, V-4, V-7, V-10). **Sale:** a successful, not pending, captured transaction (a standalone payment or a capture) is a `sale` with `confirmed_capture`. Its operation is the transaction ID of the economic capture, its amount `amount_cents` in its currency, and its effective time `created_at`. **Refund:** a refund transaction, partial ones included, is a `refund` with `confirmed_adjustment`, whose parent is the original transaction. **Void:** a void of a captured sale is a full `refund` adjustment with reason `void`. **Nothing posted:** authorizations, failed, pending and declined transactions post nothing and are counted as `not_posted`. Chargebacks are not mapped (no documented callback; a later manual or 007-B path). A state the rules do not cover posts nothing and is counted as `unmapped`; it is never guessed. | Post authorizations as pending sales. |
| D6 | Data minimization | Keep only the Paymob transaction, order and integration IDs, the amount, currency, state flags and times. Never store the PAN or masked PAN, card brand, card token, billing or shipping data, customer name, email or phone, order items, or the raw payload. Nothing personal enters the store or the logs. | Keep brand and last four digits, as the stale rule would allow. |
| D7 | Duplicates and order | **Delivery ID:** the Paymob transaction ID plus a digest of its mapped state. A repeated callback is then an exact redelivery, and a changed state is new evidence for the same operation, under 007-A rules. **Order:** a refund before its sale stays pending (`parent_missing`) until the sale arrives. **Conflicts:** conflicting content goes to 007-A reconciliation. **Tests:** AC1 cases cover duplicates, reordering and conflicts. | Deduplicate by transaction ID only, dropping later states. |
| D8 | CSV import (AC5) | **Content:** transaction rows only (sales and refunds), stored as unverified `manual_declaration` evidence under 007-A A1. They never enter verified totals and are never delivered by 014. **Columns:** a fixed set: operation ID, kind, amount, currency, effective time, parent operation, source reference and reason. **Flow:** a preview validates every row and returns closed row error codes without storing anything; a commit with an import ID stores the rows once, and a repeated commit is a no-op. **Limits:** 2 MiB and 10,000 rows per file. **Refusals:** cells beginning with `=`, `+`, `-` or `@` (formula injection); headers naming personal data (name, email, phone, address); anything outside the fixed columns. **Retention:** the file is not kept; only the evidence rows and an import record (counts and file digest) remain. **Roles:** Owner or Admin only, with audit events. | Accept imported rows as verified after a reviewer's approval (the A1 alternative; needs a reviewer policy). |
| D9 | Manual entry | One declaration at a time through a route, by an Owner or Admin, with the actor and a reason. It has the same validation and the same unverified classification as an imported row, and an audit event. Audited corrections, which change verified totals, stay in 007-B. | Allow audited corrections now. |
| D10 | Routes and permissions | **Payment sources:** create, list, replace the secret and disable, by an Owner or Admin, each audited. **Callback:** public, signature only. **Ledger read:** `finance:read`. **CSV and manual entry:** preview, commit and manual declaration, by an Owner or Admin, audited. **Service keys:** read keys only with their financial grant; ingest keys have no access. No answer returns a secret, a delivery digest, a raw field outside D6 or another client's data. | Let read service keys preview imports. |
| D11 | Ledger read | `GET /agencies/{a}/clients/{c}/revenue` returns the 007-A calculation over the client's stored evidence: transactions, per-currency totals, pending adjustments and reconciliation items. Verified and declared amounts are kept apart, and currencies are never summed. A service function gives 008-A and 014-B the client's `LedgerCalculation` and journal from the store; their journeys stay synthetic until 006. | No read route in this round. |
| D12 | Paymob gate and rules | **Setting:** the Paymob source type is off by default (`TRACKING_PAYMENTS_PAYMOB_ENABLED`). **Rules:** creating a Paymob source and accepting its callbacks are allowed only while the re-verified `payments.processor_records` rule and a new `paymob.accept` rule are current; a stale or overdue rule refuses both. **Tests:** fixtures built from the documented payloads and HMAC; there is no outbound call. A live callback needs HTTPS hosting (020) and an owner sandbox account (follow-up). | No gate, because nothing is called outbound. |
| D13 | Body bounds | Per-route bounds, checked while streaming and before parsing: the Paymob callback 64 KiB (V-6), the CSV preview and commit 2 MiB, and every other route keeps 16 KiB. | One higher global bound. |
| D14 | Retention (development, provisional) | **Evidence:** kept for the life of the client workspace, as financial records; legal retention is pending Q-012 and Q-003. **Callback diagnostics:** 30 days. **Import records:** 13 months. **Previous secrets:** 24 hours. **Raw payloads and files:** never kept. Every new table is registered in `app.data_policy`. | Delete evidence after 13 months, like 004 events. |
| D15 | Migrations and dependencies | Three additive revisions after `0019`, each with a downgrade that refuses existing state: `0020` (evidence store), `0021` (payment sources, sealed secrets, callback diagnostics), `0022` (import records). Tested on the disposable PostgreSQL service only. No new dependency: CSV parsing and HMAC come from the standard library. | One migration for the whole round. |

## 7. Verification plan

The handoff turns each case into at least one test. A mutation check accompanies each case marked (M): remove the safeguard and show that its test fails.

### 7.1 Evidence store and ledger (015-A)

| Case | Expected |
|---|---|
| T-01 | Stored evidence replayed in receipt order gives the same ledger as the in-memory 007-A calculation of the same records. |
| T-02 | An exact redelivery is stored once (M). A reused delivery ID with other content is stored and reported by 007-A as `delivery_id_reused`. |
| T-03 | Two agencies with two clients each: the ledger read needs `finance:read`; `client:read` and ingest keys are refused; read keys need the financial grant (M). |
| T-04 | `tracking_app` cannot update or delete evidence. |
| T-05 | The service's `LedgerCalculation` feeds 014-B `candidates_from_ledger` and 008-A attribution unchanged. |

### 7.2 Paymob (015-B, AC1)

| Case | Expected |
|---|---|
| T-10 | A callback signed as documented is accepted. A missing signature, an altered field or a wrong secret is answered 401 and stores nothing (M). |
| T-11 | After a secret is replaced, the previous one is accepted for 24 hours, then refused. |
| T-12 | A repeated callback leaves one evidence record, and the ledger counts the sale once (M). |
| T-13 | A refund received before its sale is pending, then posts when the sale arrives. Every delivery order gives the same totals. |
| T-14 | Partial refund, void of a captured sale, authorization only, failed, pending and declined each follow D5 (M: a failed or pending transaction never posts). |
| T-15 | An unmapped state posts nothing, is counted and answered 200. |
| T-16 | No PAN, masked PAN, brand, token, billing, shipping or customer field is stored or logged, and no raw payload is kept (M). |
| T-17 | The browser response redirect is never accepted as evidence. |
| T-18 | A callback up to 64 KiB is accepted and a larger one is answered 413; every other route keeps 16 KiB. |
| T-19 | An unknown or disabled source gets the same answer as an invalid signature (no enumeration). |
| T-20 | With the setting off, or a rule stale or overdue, Paymob sources cannot be created and their callbacks are refused (M). |
| T-21 | Per-source and per-peer rates apply. |

### 7.3 CSV and manual entry (015-C, AC5)

| Case | Expected |
|---|---|
| T-30 | A preview validates every row and reports closed row error codes; nothing is stored. |
| T-31 | A commit stores the valid rows as `manual_declaration` evidence. A repeated commit with the same import ID is a no-op (M). |
| T-32 | Declared rows never enter verified totals and are never enqueued by 014 (M). |
| T-33 | Formula-injection cells and personal-data headers are refused. |
| T-34 | Files above 2 MiB or 10,000 rows are refused. |
| T-35 | Only an Owner or Admin may preview, commit or declare; each commit and declaration has an audit event; clients are isolated. |
| T-36 | A manual declaration records its actor and reason and stays unverified. |

## 8. Out of scope and follow-ups

- **Later rounds of Spec 015.** Bookings (AC2: Cal.com or Calendly, rescheduling and cancellation without double counting), CRM (AC3), WhatsApp and ManyChat (AC4), automation webhooks (PDF-090), third-party form tools (PDF-008), Paymob transaction reads and backfill, and Stripe. Each needs its own provider decision.
- **Live checks.** A Paymob sandbox account sending callbacks to an HTTPS-hosted API (020); this is owner-operated and separately approved.
- **007-B.** Persisted postings and movements, finance write permissions, audited corrections, reconciliation workflows and the approval of declarations.
- **006.** Linking payments to people and journeys. The merchant order reference that a checkout could carry is an identity decision.
- **Excluded.** Card data of any kind, payouts and fees (profit needs explicit definitions), and refunds initiated from this product.

## 9. Owner decisions

D-066 (2026-11-21) merges Spec 014 and starts this round with the scope, provider and synthetic mode above. D1-D15 await the owner's approval, which is to be recorded as D-067 before implementation.
