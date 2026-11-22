# Payments and declared revenue (specification 015, first round)
Status: 015-A (the evidence store and the ledger read), 015-B (Paymob sources and signed processed callbacks, off by default) and 015-C (transaction CSV imports and manual declarations) are implemented under D-066 and D-067 against a synthetic Paymob-shaped sender and fixture tests. No call to Paymob has been made, no real payment was involved, and no migration has run on the native `tracking_sys`. Live callbacks need an HTTPS-hosted API (020) and an owner sandbox account, which remain separate decisions. Design: [design-015a.md](../../specs/015-business-integrations/design-015a.md); evidence: [evidence.md](../../specs/015-business-integrations/evidence.md).

## Revenue evidence and the ledger read (015-A)
Every intake path appends 007-A evidence records to `revenue_evidence`, one row per received record of one client, under the client's revenue lock. The lock's database clock read is the receipt time, so the receipts of one client increase in commit order. The ledger is never stored: each read runs the 007-A calculation over the client's records in receipt order.

| Intake | Source account | Evidence class | Verified |
|---|---|---|---|
| Paymob processed callback | `paymob-egypt` | `confirmed_capture` (sales and captures), `confirmed_adjustment` (refunds and voids) | Yes |
| CSV import | `declared` | `manual_declaration` | No |
| Manual declaration | `declared` | `manual_declaration` | No |

An exact redelivery (same source account, delivery ID and content) is stored once. A reused delivery ID with other content is stored and reported as `delivery_id_reused`. The runtime role may insert and read evidence, never update or delete it. Evidence is kept for the life of the client workspace (D14, provisional; legal retention is pending Q-012 and Q-003).

`GET /agencies/{agency_id}/clients/{client_id}/revenue` needs `finance:read`: Owners and Admins, members with the financial grant, or read keys with their financial grant. Ingest keys are refused. The answer has:
- `verified`: per-currency totals (captured, refunded, charged back, reversed, corrected and net) and the transactions with their entries;
- `declared`: the declared items and per-currency declared sales and refunds, never part of `verified`;
- `pending`: adjustments waiting for their parent (`parent_missing`, `parent_unresolved`), and Paymob refunds held back because their stored parent sale carries another signed order ID (`parent_order_mismatch`, D-070);
- `reconciliation`: disagreements (`conflicting_evidence`, `delivery_id_reused`, `exceeds_outstanding` and the other 007-A reasons).

Amounts are decimal strings in their own currency; currencies are never added together. Lists are bounded to 1,000 items, newest first, with a `truncated` flag; totals cover every record.

## Paymob sources (015-B)
A Paymob source belongs to one client. Owners and Admins manage sources, and every change is audited:

| Route | Body | Audit |
|---|---|---|
| `POST /agencies/{a}/clients/{c}/payment-sources` | `{"provider": "paymob", "region": "egypt", "name": ..., "hmac_secret": ..., "live_integration_ids": [...]}` | `payment_source.created` |
| `GET /agencies/{a}/clients/{c}/payment-sources` | | |
| `PUT /agencies/{a}/clients/{c}/payment-sources/{id}/secret` | `{"hmac_secret": ...}` | `payment_source.secret_replaced` |
| `PATCH /agencies/{a}/clients/{c}/payment-sources/{id}` | Any of `{"name": ...}`, `{"status": "active" \| "disabled"}` and `{"live_integration_ids": [...]}`; `null` leaves a field unchanged | `payment_source.updated` |

**Live integration IDs (D-070).** Paymob's processed callback does not sign `is_live`, so a holder of one signed test-mode callback could otherwise change it to `true` without breaking the signature (review finding R001). Paymob issues separate integration IDs for test and live mode (the dashboard's integration table changes with the mode), and `integration_id` is signed. Each source therefore lists the merchant's live integration IDs: 1 to 20 positive integers, copied from the dashboard in live mode. Only a callback whose signed `integration_id` is in the list and whose `is_live` is true can post; any other verified callback counts as `test_mode` (with the reason `undeclared_integration` when the integration is not listed). Never list a test integration: its test payments would then count as verified revenue. The declaration is the source's owner's assertion, audited like every source change.

The merchant's HMAC secret comes from the Paymob dashboard (API keys page, visible to the main account user only). It is entered once, sealed under the token keyring, and never returned, logged or included in an error. A replaced secret stays valid for 24 hours, then the lifecycle runner deletes it. Each source answers with its `callback_path`, `/payments/paymob/callback/ppk_<43 characters>`. The client sets the API's HTTPS origin followed by that path as the processed callback (webhook) URL of its Paymob integration, or as the intention's `notification_url`. The key is unguessable; treat the full URL as confidential.

Only the `egypt` region exists in this round. Times without an offset are read as Cairo local time, the first occurrence for a repeated hour. The other regions (Oman, Saudi Arabia, the United Arab Emirates) need their own verification.

## Callbacks
`POST /payments/paymob/callback/{public_key}?hmac=<hex>` is public. The steps:
1. While `TRACKING_PAYMENTS_PAYMOB_ENABLED` is false, or the `payments.processor_records` or `paymob.accept` rule is stale or past its review date (2027-11-21), the route answers `503 payments_unavailable` before anything else.
2. The trusted intake rate (`TRACKING_INGEST_TRUSTED_PER_MINUTE`) applies per peer address and per key, known or not; a 429 carries `Retry-After`.
3. An unknown, malformed or disabled key, a body that is not a JSON object with `type` and `obj`, a missing field, and a signature that matches no live secret all answer `401 invalid_signature`. Nothing is stored.
4. A verified callback is reduced at once to the allowed fields: the transaction, order and integration IDs, the amount, the currency, the state flags and the time. Card, billing, shipping, customer, item and token data are never stored or logged.
5. Every verified callback answers `200 {"status": "received"}`, so Paymob stops retrying, and leaves one diagnostic row.

The signature is HMAC-SHA512 of the concatenated values of `amount_cents`, `created_at`, `currency`, `error_occured`, `has_parent_transaction`, `id`, `integration_id`, `is_3d_secure`, `is_auth`, `is_capture`, `is_refunded`, `is_standalone_payment`, `is_voided`, `order.id`, `owner`, `pending`, `source_data.pan`, `source_data.sub_type`, `source_data.type` and `success`, with booleans as `true` or `false`. The text of a null value is not documented; it is read as an empty string until the live check confirms it. Card token callbacks (`type` `TOKEN`) are verified with their own documented list and post nothing. The browser response redirect (GET) is never accepted.

## States and mapping

| Callback | Outcome |
|---|---|
| `is_live` not true (test mode) | `test_mode`, nothing posted |
| Signed `integration_id` not among the source's live integration IDs | `test_mode` (`undeclared_integration`), nothing posted |
| `success` false or `error_occured` true | `not_posted` (`failed`) |
| `pending` true | `not_posted` (`pending`) |
| `is_auth` true | `not_posted` (`authorization`) |
| Standalone payment, no parent | Sale (`confirmed_capture`), operation = transaction ID |
| Capture of an authorization (`is_capture`, with a parent) | Sale (`confirmed_capture`), operation = capture transaction ID |
| Refund or void (`is_refund` or `is_void`, with a parent) | Refund (`confirmed_adjustment`) of the parent; reason `void` for a void |
| Anything else, an amount, currency or time that cannot be read | `unmapped` with a closed reason, nothing posted |

The parent transaction re-sent after a refund or void maps to the same sale and is an exact redelivery. A refund that arrives before its sale stays pending until the sale arrives.

**Refund binding (D-070).** The `parent_transaction` that names a refund's or void's sale is not signed, so a holder of one signed refund could otherwise point it at another sale of the same client (review finding R001). The signed `order.id` binds them instead: a refund or void adjusts only a sale that carries the same signed order ID. When the named sale is already stored with another order ID, the callback is `unmapped` (`invalid_parent`) and stores nothing. When the refund arrives first and its sale then arrives with another order ID, every ledger read holds the refund back: it appears in `pending` as `parent_order_mismatch` and never reaches verified totals, the journal, attribution or conversion delivery. That a refund carries its parent's order ID is not stated in the Paymob pages read on 2026-11-22; the live check confirms it, and until then a refund whose order differs stays visibly pending rather than silently adjusting a sale. A refund that references an authorization instead of its capture, and a void of an authorization that was never captured, stay pending and never change verified totals. Chargebacks have no documented callback and are not mapped. Only currencies with two decimals are mapped from `amount_cents`.

## Diagnostics
`payment_callback_diagnostics` holds, per verified callback, the source, a SHA-256 digest of the received signature, the receipt time and the outcome (`stored`, `duplicate`, `not_posted`, `unmapped`, `test_mode`) with its reason. It holds no payload. The lifecycle runner deletes rows 30 days after receipt.

## CSV import (015-C)
A transaction CSV file is UTF-8 (a leading byte order mark is ignored), comma separated and quoted as RFC 4180, with a header row. Columns:

| Column | Required | Content |
|---|---|---|
| `operation_id` | Yes | 1-128 printable characters, unique within the file |
| `kind` | Yes | `sale` or `refund` |
| `amount` | Yes | A positive decimal in major units, at most the currency's decimals (`1500.00`) |
| `currency` | Yes | An allow-listed ISO 4217 code (the 014 currency table) |
| `effective_at` | Yes | ISO 8601 with an offset, not later than one day after receipt |
| `parent_operation_id` | For refunds | The refunded sale; absent for a sale |
| `source_reference` | No | At most 256 characters |
| `reason` | No | At most 1,024 characters |

The file is refused as a whole (`422`) with `invalid_encoding`, `invalid_csv`, `empty_file`, `missing_column`, `duplicate_column`, `unknown_column`, `personal_data_column` (a header naming a name, email, phone, address, street, city or postal code) or `too_many_rows` (above 10,000 data rows). A body above 2 MiB is answered `413` before it is parsed. Row error codes: `wrong_field_count`, `formula_cell` (a cell beginning with `=`, `+`, `-`, `@`, a tab or a carriage return), `missing_value`, `invalid_operation_id`, `invalid_kind`, `invalid_amount`, `unsupported_currency`, `invalid_time`, `invalid_parent`, `value_too_long`, `invalid_text`, `prohibited_value` (an email address, an international phone number or a card number in the reason or source reference) and `duplicate_row`. No answer echoes a rejected value.

| Route | Answer |
|---|---|
| `POST /agencies/{a}/clients/{c}/revenue-imports/preview` (body `text/csv`) | `import_id` (the SHA-256 of the file), the counts and each row's status and codes; nothing is stored |
| `POST /agencies/{a}/clients/{c}/revenue-imports/{import_id}` (the same body) | `201` with the import record and the row results; `200` with the same record for a repeated commit, which stores nothing; `422 import_mismatch` when the body differs |

Both need an Owner or Admin session. A commit stores each valid row once as unverified evidence and records an audit event `revenue_import.committed`. The file is never kept: `revenue_imports` holds its digest and counts, and the lifecycle runner deletes the record 13 months (395 days) after the commit. The evidence stays. A row committed again through another file is an exact redelivery.

## Manual declarations
`POST /agencies/{a}/clients/{c}/revenue-declarations` with `{"operation_id", "kind", "amount", "currency", "effective_at", "parent_operation_id"?, "source_reference"?, "reason"}` declares one sale or refund. It has the CSV row rules, a required reason, the declaring user as actor and an audit event `revenue.declared`, and answers `201` with `stored` or `duplicate`. A refusal answers `422` with the first closed code. Declarations are unverified: they never enter verified totals, and conversion delivery (014-B) never enqueues them. Audited corrections, which change verified totals, belong to 007-B.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `TRACKING_PAYMENTS_PAYMOB_ENABLED` | `false` | The Paymob source type; off is the kill switch for source creation and callbacks |
| `TRACKING_TOKEN_KEYRING`, `TRACKING_TOKEN_KEYRING_ACTIVE` | blank | Seal merchant HMAC secrets; routes that need them answer 503 while unset |
| `TRACKING_INGEST_TRUSTED_PER_MINUTE` | 600 | The callback rate per peer and per key |
| `TRACKING_PAYMENT_DIAGNOSTIC_RETENTION_DAYS` (lifecycle runner) | 30 | Diagnostic rows; a deployment may shorten it, not extend it |
| `TRACKING_REVENUE_IMPORT_RETENTION_DAYS` (lifecycle runner) | 395 | Import records; a deployment may shorten it, not extend it |

## Lifecycle
`python -m app.lifecycle` deletes, as `tracking_lifecycle`: callback diagnostics 30 days after receipt, retired payment source secrets, and revenue import records 395 days after the commit. It never reads or deletes evidence.

## Before any live use
- An HTTPS-hosted API (020) and an owner Paymob sandbox account for a live callback check, separately approved. The check confirms the null text form in the signature, the references of refunds after captures, that a refund or void carries its parent's order ID (D-070), that test and live integration IDs differ, and the retry behavior.
- A legal review (Q-012) of whether a merchant may direct callbacks that carry the last four digits of a card to this platform under Paymob's terms.
- Native `tracking_sys` migration of `0020` to `0022`, and deployment, which remain separate owner decisions.
