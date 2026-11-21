# 015 design, first round: evidence store, Paymob payments, CSV import and manual declarations

Prepared: 2026-11-21 on `codex/spec-015-business-integrations`. Authority: D-066 and D-067 (D1-D15 of the [entry review](entry-review.md) as recommended, with amendment A1). The Phase 0 source verification is in [entry review sections 2.4 and 2.5](entry-review.md#24-official-sources-read-in-phase-0). This note applies its parameter-level results. It adds no dependency, makes no call to Paymob and involves no real payment. Migrations `0020` to `0022` run only on the disposable PostgreSQL service of `backend/tests/README.md`. No frontend change.

## 1. Parameters applied from Phase 0

| Source | Parameter | Where |
|---|---|---|
| V-1, V-8 | Only the JSON POST processed callback is accepted. A body whose `type` is `TRANSACTION` is mapped; a `TOKEN` body is verified with the card token list, then stores and posts nothing (`unmapped`). Any other type cannot be verified and is answered 401. | 015-B |
| V-2 | HMAC-SHA512 over the concatenated values of the 20 documented fields (section 4.3). Booleans `true` or `false`, integers in decimal, strings unchanged, null as an empty string (unverified). The `hmac` query parameter holds lowercase hexadecimal. | 015-B |
| V-2, N1 | `parent_transaction`, `is_refund`, `is_void` and `is_live` are unsigned. The mapping requires the signed flags to agree with the kind (section 4.4). | 015-B |
| V-3, V-4, A1 | The mapping table of section 4.4, with `test_mode` for `is_live` not true, and child refund, void and capture transactions. A parent's re-sent callback maps to the same sale and repeats its delivery ID. | 015-B |
| V-6 | The callback bound stays 64 KiB (no documented size). | 015-B |
| V-7 | `created_at` with an offset is used as given; without one it is local time in the source's region zone (Egypt: `Africa/Cairo`, from the pinned `tzdata`), first occurrence for a repeated hour. | 015-B |
| V-9 | Region `egypt` only; source account `paymob-egypt` (section 4.2). | 015-B |
| V-12, V-13 | No card, billing, shipping, customer, item or token field survives the mapping; `payments.processor_records` narrowed and current, `paymob.accept` added. | 015-B |

## 2. Shared pieces

### 2.1 Revenue lock and receipt clock

Every write to a client's evidence (Paymob callback, CSV commit, manual declaration) first takes a transaction-scoped advisory lock `pg_advisory_xact_lock(7007, client key)` (the 004 client key derivation, a new namespace), then reads `clock_timestamp()` as the receipt time. Receipts of one client are therefore increasing in commit order, which keeps the 007-A journal-prefix property: a journal returned earlier is a prefix of a later one. The lock is held only for the insert.

### 2.2 Evidence append

`app.services.revenue.append_evidence(session, evidence, intake, intake_id)` inserts one 007-A `Evidence` with the content digest of section 3.1, `ON CONFLICT DO NOTHING` on the exact-redelivery key, and reports `stored` or `duplicate`. It is the only writer of `revenue_evidence`, used by the three intake paths and by tests.

### 2.3 Body bounds (D13)

`RequestBoundary` keeps 16 KiB as its default and takes an ordered table of exceptions, each a method, a full-path regular expression and a limit:
- `POST ^/payments/paymob/callback/[^/]+$`: 65,536 bytes;
- `POST ^/agencies/[^/]+/clients/[^/]+/revenue-imports/(preview|[0-9a-f]{64})$`: 2,097,152 bytes.

A `Content-Length` above the route's limit is answered 413 before any body is read. Otherwise the body is counted while streaming, and the first chunk that passes the limit ends the request with 413; nothing is parsed. Every other route keeps 16 KiB.

## 3. 015-A: evidence store and ledger read

### 3.1 Table `revenue_evidence` (`0020_revenue_evidence`)

| Column | Type and check |
|---|---|
| `id` | UUID, primary key |
| `sequence` | bigint identity: the tie-break of equal receipt times |
| `agency_id`, `client_id` | composite foreign key to `client_workspaces (agency_id, id)` |
| `delivery_id`, `source_account_id`, `operation_id` | text, 1-256 characters (007-A `require_text`) |
| `kind` | `sale`, `refund`, `chargeback`, `chargeback_reversal`, `correction` |
| `classification` | the six 007-A classes, constrained to the kinds 007-A allows |
| `currency`, `currency_exponent` | `^[A-Z]{3}$`, 0-8 |
| `amount_minor` | bigint; above 0, except a correction, which is non-zero |
| `effective_at`, `received_at` | timestamptz; `received_at` is the database clock (section 2.1) |
| `parent_operation_id` | null exactly for a sale |
| `reason` (1-1024), `actor`, `source_reference` (1-256) | text or null |
| `intake` | `paymob`, `csv_import`, `manual_entry` |
| `intake_id` | UUID: the payment source or import record; null exactly for `manual_entry` |
| `content_digest` | 64 lowercase hexadecimal characters |

**Content digest.** SHA-256 of the canonical JSON of the 007-A payload: every `Evidence` field except `received_at`, with the effective time as a UTC instant with microseconds and the stream fixed to `client_revenue`. Intake and intake ID are excluded, so the same Paymob transaction delivered through two sources of one client is stored once.

**Keys.** Unique (`client_id`, `source_account_id`, `delivery_id`, `content_digest`): an exact redelivery inserts nothing, while a reused delivery ID with other content is a second row, which 007-A reports as `delivery_id_reused` (D2). Index (`client_id`, `received_at`, `sequence`) for the ordered load.

**Provenance without foreign keys.** `intake_id` has no foreign key: payment sources are never deleted, and an import record is deleted after 13 months while its evidence stays (D14), which a foreign key would block.

**Privileges.** `tracking_app`: `SELECT, INSERT` only, so no update or delete (T-04). `tracking_lifecycle`: none. Evidence is kept for the life of the client workspace (D14); workspace deletion belongs to 017 and 018.

**Data policy.** Class `revenue.evidence` (high sensitivity, pseudonymous, observed or provided; "kept for the life of the client workspace; legal retention pending Q-012 and Q-003"). The scope columns are `tenancy.configuration`, `actor` is `account.reference`. Row rule: `DEFERRED`, reference `D-067; 017`.

**Downgrade.** Refuses while any evidence row exists.

### 3.2 Service

- `load_evidence(session, agency_id, client_id)`: the client's rows ordered by (`received_at`, `sequence`), rebuilt as `Evidence`.
- `client_ledger(session, agency_id, client_id) -> ClientLedger`: `calculate()` and `ledger_feed()` over those records. 008-A (`sale_conversion`, `attribute`, `ledger_feed` consumers) and 014-B (`candidates_from_ledger`, `candidates_from_feed`) take them unchanged; journeys stay synthetic until 006.

### 3.3 Route (D11)

`GET /agencies/{agency_id}/clients/{client_id}/revenue` needs `finance:read` (`resolve_scope` with the browser session or a read key with its financial grant; ingest keys are refused by `ReaderDep`). The answer:

```json
{
  "verified": {
    "totals": [{"currency": "EGP", "captured": "1000.00", "refunded": "250.00", "charged_back": "0.00", "reversed": "0.00", "corrected": "0.00", "net": "750.00"}],
    "transactions": [{"operation_id": "...", "source_account_id": "paymob-egypt", "currency": "EGP", "effective_at": "...", "net": "750.00",
                      "entries": [{"operation_id": "...", "kind": "sale", "amount": "1000.00", "effective_at": "..."}]}]
  },
  "declared": {
    "totals": [{"currency": "EGP", "sales": "500.00", "refunds": "0.00"}],
    "items": [{"operation_id": "...", "kind": "sale", "amount": "500.00", "currency": "EGP", "effective_at": "...", "parent_operation_id": null,
               "intake": "csv_import", "reason": null, "source_reference": null}]
  },
  "pending": [{"operation_id": "...", "kind": "refund", "parent_operation_id": "...", "amount": "250.00", "currency": "EGP", "effective_at": "...", "reason": "parent_missing"}],
  "reconciliation": [{"operation_id": "...", "reason": "conflicting_evidence"}]
}
```

Amounts are decimal strings in their own currency (`decimal_text`); currencies are never summed. Declared totals add the declared sales and refunds per currency and are labeled unverified; they never enter `verified` (007-A A1). No answer carries a delivery ID, content digest, actor, intake ID or another client's data. At most 1,000 transactions and 1,000 declared items are returned, newest first, with a `truncated` flag; totals cover all evidence.

### 3.4 Tests (015-A)

| Case | Test |
|---|---|
| T-01 | `tests/integration/test_revenue_evidence.py::test_stored_ledger_equals_in_memory_calculation` |
| T-02 (M) | `test_revenue_evidence.py::test_exact_redelivery_is_stored_once`, `::test_reused_delivery_id_is_reported` |
| T-03 (M) | `test_revenue_evidence.py::test_revenue_read_needs_finance_access` |
| T-04 | `test_revenue_evidence.py::test_runtime_role_cannot_update_or_delete_evidence` |
| T-05 | `test_revenue_evidence.py::test_stored_ledger_feeds_delivery_and_attribution` |
| Migration | `tests/integration/test_revenue_migrations.py::test_0020_upgrade_privileges_and_refused_downgrade` |

## 4. 015-B: Paymob payments

### 4.1 Tables (`0021_payment_sources`)

**`payment_sources`**: `id`, `agency_id`, `client_id` (composite foreign key to the client), `provider` (`paymob`), `region` (`egypt`), `name` (1-200), `status` (`active`, `disabled`), `public_key` (`ppk_` and 43 URL-safe characters, unique), `created_by_membership_id`, `created_at`, `updated_at`. Unique (`agency_id`, `client_id`, `id`) for composite references.

**`payment_source_secrets`**: `id`, `agency_id`, `client_id`, `source_id` (composite foreign key), `version` (unique per source), the sealed secret (`kek_id`, `wrap_nonce`, `wrapped_dek`, `nonce`, `ciphertext`), `created_at`, `retires_at`. Sealed with the D-025 keyring under the context (agency, client, source, secret, `paymob_hmac`, version).

**`payment_callback_diagnostics`**: `id`, `agency_id`, `client_id`, `source_id` (composite foreign key), `delivery_digest` (64 hexadecimal: SHA-256 of the received `hmac` value, which repeats for a repeated signed state and reveals nothing without the merchant's secret), `received_at`, `outcome` (`stored`, `duplicate`, `not_posted`, `unmapped`, `test_mode`) and `reason` (null, or `authorization`, `failed`, `pending`, `card_token`, `unsupported_state`, `unsupported_currency`, `invalid_time`, `invalid_amount`, `invalid_parent`). Index (`received_at`).

**Audit.** Actions `payment_source.created`, `payment_source.updated`, `payment_source.secret_replaced`, resource `payment_source`.

**Privileges.** `tracking_app`: `SELECT, INSERT` on the three tables; `UPDATE (name, status, updated_at)` on sources and `UPDATE (retires_at)` on secrets; no delete. `tracking_lifecycle`: `SELECT (id, retires_at)` and `DELETE` on secrets (retired secrets, D14); `SELECT (id, received_at)` and `DELETE` on diagnostics (30 days, D14).

**Data policy.** `payment.source` (low, none, provided: name, provider, region, status, public key and times; kept until workspace deletion, 017), `credential.sealed_secret` for the sealed columns (existing class), `payment.callback_diagnostic` (low, none, observed; 30 days). Rules: secrets `APPROVED D-067` (deleted when retired, 24 hours after replacement), diagnostics `APPROVED D-067` (30 days), sources `DEFERRED D-067; 017`.

**Downgrade.** Refuses while any source, secret, diagnostic, `paymob` evidence or new audit action exists.

### 4.2 Sources and secrets (D3, D10)

| Route | Permission | Answer |
|---|---|---|
| `POST /agencies/{a}/clients/{c}/payment-sources` `{provider, region, name, hmac_secret}` | Owner or Admin session; audit `payment_source.created` | 201, the source with its `callback_path` |
| `GET /agencies/{a}/clients/{c}/payment-sources` | Owner or Admin session | The client's sources |
| `PUT /agencies/{a}/clients/{c}/payment-sources/{id}/secret` `{hmac_secret}` | Owner or Admin session; audit `payment_source.secret_replaced` | The source; the previous secret retires 24 hours later |
| `PATCH /agencies/{a}/clients/{c}/payment-sources/{id}` `{name?, status?}` | Owner or Admin session; audit `payment_source.updated` | The source |

The HMAC secret is 16-256 printable ASCII characters without spaces. It is sealed at once and is never returned, logged or included in an error. Creating a source and re-activating one need the gate (section 4.6). The source account of every Paymob evidence record is `paymob-egypt`: Paymob transaction IDs belong to the regional system, so a client with two sources for one merchant account still counts each transaction once.

### 4.3 Callback (D4, D7)

`POST /payments/paymob/callback/{public_key}?hmac=<128 hexadecimal>`, public. Steps:
1. **Gate.** With the setting off or a rule stale or overdue: 503 `payments_unavailable`, before any lookup.
2. **Rates.** The 004 trusted rate (`ingest_trusted_per_minute`) per peer address, then per public key as given (known or not), so a 429 reveals nothing about a source.
3. **Source.** Without the token keyring, 503 `collection_not_configured` for every key, before the lookup. Then an active source of an active client and agency, by public key. Unknown, disabled or malformed: 401 `invalid_signature`.
4. **Parse.** The bounded body as a JSON object with `type` and `obj`. Anything else, including a body nested beyond the decoder's depth: 401.
5. **Verify.** For `TRANSACTION`, the string is the concatenation, in order, of `amount_cents`, `created_at`, `currency`, `error_occured`, `has_parent_transaction`, `id`, `integration_id`, `is_3d_secure`, `is_auth`, `is_capture`, `is_refunded`, `is_standalone_payment`, `is_voided`, `order.id`, `owner`, `pending`, `source_data.pan`, `source_data.sub_type`, `source_data.type`, `success` of `obj` (`order` and `source_data` are objects). For `TOKEN`: `card_subtype`, `created_at`, `email`, `id`, `masked_pan`, `merchant_id`, `order_id`, `token`. HMAC-SHA512 under each live secret of the source (current, and previous ones until `retires_at`), compared with `hmac.compare_digest`; every secret is tried. A missing field, a float, list or object value, or no match: 401, nothing stored.
6. **Minimize (D6).** The verified object is reduced at once to `id`, `amount_cents`, `currency`, `created_at`, the flags `success`, `pending`, `error_occured`, `is_auth`, `is_capture`, `is_standalone_payment`, `has_parent_transaction`, `is_refund`, `is_void`, `is_live`, `parent_transaction`, `integration_id` and `order.id`. The full payload is dropped and never logged.
7. **Map** (section 4.4), then under the revenue lock: append the evidence if any, and one diagnostic row.
8. **Answer** 200 `{"status": "received"}` for every verified callback, whatever the outcome.

**Delivery ID (D7).** `paymob:<transaction id>:<first 32 hexadecimal characters of SHA-256 of the mapped state>`, where the mapped state is the canonical JSON of kind, classification, amount, currency, exponent, effective instant, parent and reason. A repeated callback, and the parent's re-sent callback after a refund or void, repeat it. A changed state for one transaction is a new delivery of the same operation, which 007-A attaches or routes to `conflicting_evidence`.

### 4.4 Mapping (D5, A1, N1)

Checked in order on the minimized object:

| Condition | Result |
|---|---|
| `is_live` is not `true` | `test_mode`, nothing posted |
| `success` not `true` or `error_occured` `true` | `not_posted` (`failed`) |
| `pending` `true` | `not_posted` (`pending`) |
| `is_auth` `true` | `not_posted` (`authorization`) |
| `has_parent_transaction` false, `is_standalone_payment` true, `is_capture`, `is_refund` and `is_void` not true | `sale`, `confirmed_capture`, operation `id` |
| `has_parent_transaction` true, `is_capture` true, `is_standalone_payment` false, `is_refund` and `is_void` not true | `sale`, `confirmed_capture`, operation `id` (the capture transaction) |
| `has_parent_transaction` true, `is_capture` and `is_standalone_payment` false, exactly one of `is_refund` and `is_void` true, `parent_transaction` a positive integer other than `id` | `refund`, `confirmed_adjustment`, parent `parent_transaction`, reason `void` for a void |
| anything else | `unmapped` (`unsupported_state`) |

A posting also needs `amount_cents` a positive integer, a currency with exponent 2 in the 014 allow list (`amount_cents` is a cent amount; other exponents are `unsupported_currency`), and a valid `created_at` (`invalid_time`); otherwise `unmapped`. The source reference is `paymob:<integration id>:<order id>` (D6 allows both IDs). Chargebacks are not mapped (V-10). A refund that arrives first stays `parent_missing` until its sale arrives (007-A). Notes N1 and N2 of entry review section 2.5 apply.

### 4.5 Synthetic sender

`tests/paymob_callbacks.py` builds processed callbacks with the documented structure, including the card, billing, shipping and merchant fields that must be discarded, and signs them with a test secret by the documented algorithm. It covers sales, captures, partial and full refunds, voids, authorizations, failures, pending, test mode, card tokens, unmapped states and oversized bodies. It never opens a network connection.

### 4.6 Gate and rules (D12)

`TRACKING_PAYMENTS_PAYMOB_ENABLED` defaults to false (listed as `false` in `.env.example`, like the other provider switches). The rules `payments.processor_records` (re-verified, narrowed to provider IDs, amounts, states and times; data class `revenue.evidence`) and `paymob.accept` (new; data class `revenue.evidence`) are current from 2026-11-21 with review on 2027-11-21. While the setting is off, or either rule is stale or past its review date, sources cannot be created or re-activated (503 `payments_unavailable`) and callbacks are answered 503.

### 4.7 Lifecycle (D14)

`python -m app.lifecycle` deletes, as `tracking_lifecycle`, callback diagnostics 30 days after receipt and payment source secrets once retired.

### 4.8 Tests (015-B)

| Case | Test |
|---|---|
| T-10 (M) | `tests/integration/test_paymob.py::test_signed_callback_is_accepted`, `::test_invalid_signatures_store_nothing`; `tests/test_paymob_contract.py::test_documented_hmac_string` |
| T-11 | `test_paymob.py::test_previous_secret_accepted_for_24_hours` |
| T-12 (M) | `test_paymob.py::test_repeated_callback_counts_once` |
| T-13 | `test_paymob.py::test_refund_before_sale_and_every_order` |
| T-14 (M) | `test_paymob.py::test_states_follow_the_mapping`; `tests/test_paymob_contract.py::test_mapping_table` |
| T-15 | `test_paymob.py::test_unmapped_state_is_counted_and_answered` |
| T-16 (M) | `test_paymob.py::test_no_card_or_customer_field_is_stored_logged_or_returned` |
| T-17 | `test_paymob.py::test_response_redirect_is_never_evidence` |
| T-18 | `test_paymob.py::test_body_bounds` |
| T-19 | `test_paymob.py::test_unknown_and_disabled_sources_answer_like_invalid_signatures` |
| T-20 (M) | `test_paymob.py::test_gate_and_rules`; `tests/test_paymob_contract.py::test_rules_gate` |
| Unit cases | `tests/test_paymob_contract.py` (pure verification, minimization and mapping; named apart from the integration module) |
| T-21 | `test_paymob.py::test_rates_per_source_and_peer` |
| A1 | `test_paymob.py::test_test_mode_posts_nothing` |
| Sources | `test_paymob.py::test_source_routes_permissions_and_audit` |
| Migration and lifecycle | `test_revenue_migrations.py::test_0021_*`, `test_paymob.py::test_lifecycle_deletes_diagnostics_and_retired_secrets` |

## 5. 015-C: CSV import and manual declarations

### 5.1 CSV format (D8)

UTF-8 (an initial byte order mark is ignored), comma separated, quoted as RFC 4180 (`csv` module), header row first. Required columns: `operation_id`, `kind`, `amount`, `currency`, `effective_at`. Optional columns: `parent_operation_id`, `source_reference`, `reason`. Order is free. At most 2 MiB and 10,000 data rows.

**File refusals** (422, nothing returned per row): `file_too_large` (a defence behind the 413 of the boundary), `invalid_encoding`, `invalid_csv`, `empty_file`, `missing_column`, `duplicate_column`, `unknown_column`, `personal_data_column` (a header that names, after lowercasing and removing spaces, hyphens and underscores, `name`, `firstname`, `lastname`, `fullname`, `customer`, `email`, `mail`, `phone`, `mobile`, `telephone`, `address`, `street`, `city` or `postcode`, or contains `email`, `phone` or `address`), `too_many_rows`. A larger body is answered 413 by the boundary.

**Row error codes** (closed; a row may carry several): `wrong_field_count`, `formula_cell` (a cell beginning with `=`, `+`, `-`, `@`, a tab or a carriage return), `missing_value`, `invalid_operation_id` (1-128 printable characters), `invalid_kind` (`sale` or `refund`), `invalid_amount` (a positive decimal in major units with at most the currency's exponent of decimals), `unsupported_currency` (the 014 allow list), `invalid_time` (ISO 8601 with an offset, not after the receipt time plus one day), `invalid_parent` (required for a refund, absent for a sale, not equal to the operation), `value_too_long` (reason above 1,024 or source reference above 256 characters), `invalid_text` (a non-printable character in the reason or source reference), `prohibited_value` (a card number, an email address or a phone number in international form in the reason or source reference), `duplicate_row` (an operation ID already used by an earlier row of the file).

### 5.2 Flow and records

| Route | Permission | Answer |
|---|---|---|
| `POST /agencies/{a}/clients/{c}/revenue-imports/preview` (body `text/csv`) | Owner or Admin session | `import_id` (the SHA-256 of the file), counts and each row's status and error codes; nothing is stored |
| `POST /agencies/{a}/clients/{c}/revenue-imports/{import_id}` (the same body) | Owner or Admin session; audit `revenue_import.committed` | 201 with the import record; 200 with the same record for a repeated commit (no-op); 422 `import_mismatch` when the body's digest differs |
| `POST /agencies/{a}/clients/{c}/revenue-declarations` `{operation_id, kind, amount, currency, effective_at, parent_operation_id?, source_reference?, reason}` | Owner or Admin session; audit `revenue.declared` | 201 with the declaration and `stored` or `duplicate` |

A commit validates the file again, stores each valid row once as `manual_declaration` evidence (intake `csv_import`, intake ID the import record, actor the committing user's ID) and records the counts. The file is never kept. The delivery ID of a declaration is `declaration:<operation id>:<32 hexadecimal characters of the mapped economic state>`, so a row committed again through another file is an exact redelivery; a declaration with the same terms from another actor is reported by 007-A as `delivery_id_reused`. A manual declaration (intake `manual_entry`) has the same validation, a required reason and the declaring user as actor. Declared rows are unverified: they never enter verified totals (007-A A1) and 014-B never enqueues them, because `candidates_from_ledger` reads only posted transactions. Audited corrections stay in 007-B.

**`revenue_imports` (`0022_revenue_imports`)**: `id`, `agency_id`, `client_id` (composite foreign key), `file_digest` (64 hexadecimal, unique per client), `total_rows`, `stored_rows`, `duplicate_rows`, `rejected_rows`, `committed_by_membership_id`, `committed_at`. `tracking_app`: `SELECT, INSERT`. `tracking_lifecycle`: `SELECT (id, committed_at)` and `DELETE`, 395 days (13 months) after the commit. Data class `revenue.import_record` (low, none, system), rule `APPROVED D-067`. Audit actions `revenue_import.committed` and `revenue.declared`, resources `revenue_import` and `revenue_evidence`. Downgrade refuses while any import record, declared evidence or new audit action exists.

### 5.3 Tests (015-C)

| Case | Test |
|---|---|
| T-30 | `tests/integration/test_revenue_imports.py::test_preview_reports_rows_and_stores_nothing`; `tests/test_revenue_csv.py` |
| T-31 (M) | `test_revenue_imports.py::test_commit_stores_once_and_repeats_as_no_op` |
| T-32 (M) | `test_revenue_imports.py::test_declared_rows_stay_out_of_verified_totals_and_delivery` |
| T-33 | `tests/test_revenue_csv.py::test_formula_and_personal_data_refusals` |
| T-34 | `test_revenue_imports.py::test_size_and_row_limits` |
| T-35 | `test_revenue_imports.py::test_permissions_audit_and_isolation` |
| T-36 | `test_revenue_imports.py::test_manual_declaration_records_actor_and_reason` |
| Migration and lifecycle | `test_revenue_migrations.py::test_0022_*`, `test_revenue_imports.py::test_lifecycle_deletes_import_records_after_13_months` |

## 6. Mutation checks

Each safeguard is disabled in turn, its tests are rerun, and the source is restored byte for byte, as in 009 to 014:
1. The exact-redelivery key (insert without the conflict clause): T-02, T-12.
2. The `finance:read` permission of the revenue route (`client:read`): T-03.
3. The HMAC comparison (any signature accepted): T-10.
4. The failed and pending rules of the mapping: T-14.
5. The minimization step (the source reference built from the raw payload, including the PAN): T-16.
6. The gate check of the callback and of source creation: T-20.
7. The import idempotency (a repeated commit stores again): T-31.
8. The unverified classification of declarations (`confirmed_capture`): T-32.
9. The nesting guard of the body parser (a deeply nested body raised a server error): T-19.
10. The keyring check before the source lookup (known and unknown keys answered differently without the keyring): T-19.
