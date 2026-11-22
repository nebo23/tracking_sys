# Specification 015 evidence

The first round (payments and the CSV and manual fallback, D-066 and D-067) is recorded first, then the second round (bookings, CRM and WhatsApp, D-068).

Branch `codex/spec-015-business-integrations`, created from `c81d506` (the D-066 preparation on top of merged `main` at `73efae9`). Authority: D-066 and D-067, decisions D1-D15 of the [entry review](entry-review.md) as recommended, with amendment A1. Design: [design-015a.md](design-015a.md).

No call was made to Paymob, no real payment was involved, and no Paymob account, integration or secret was created, changed or requested. Phase 0 read public documentation pages only. No card data, billing or shipping data, customer data or raw payload is stored. Every migration ran on the disposable PostgreSQL 18 service of `backend/tests/README.md` (Compose project `tracking-system-foundation-test`, `127.0.0.1:55433`), never on the native `tracking_sys`. No dependency was added and no frontend file changed.

## Baseline

At `c81d506` (with the Phase 0 and D-067 record commits, which change no code), in the worktree `.worktrees/spec-015-business-integrations` with the project `.venv` (Python 3.12.4):
- unit suite: 703 passed, 391 deselected;
- integration suite on the disposable service: 388 passed and 3 skipped (the browser journeys, which need `TRACKING_RUN_BROWSER_TESTS=1`).

## Phase 0: sources and D-067

[Entry review section 2.4](entry-review.md#24-official-sources-read-in-phase-0) lists every page read on 2026-11-21, with the result for V-1 to V-13. In summary:
- **Confirmed:** V-1, V-2 (the assumed field list and order), V-8, V-10, V-12 and V-13.
- **Corrected at parameter level:** V-3 (the child and test-mode flags), V-4 (refunds, voids and captures are their own transactions, and the parent is re-sent with flags), V-7 (`created_at` has no offset in the processed callback) and V-9 (four regions; Pakistan is not listed).
- **Partly confirmed:** V-5 (retries implied, no schedule) and V-11 (no documented secret regeneration).
- **Not stated:** V-6 (no size; 64 KiB kept).

One fact raised a decision: test-mode transactions (`is_live`). It was presented to the owner with D1-D15 as amendment A1 (section 2.5), and D-067 approves D1-D15 and A1 as recommended. Notes N1 (unsigned fields) and N2 (authorization and capture references) are recorded in section 2.5. The design note applies the parameters (section 1).

## 015-A: evidence store and ledger read

**Scope (D2, D11, D14, D15).**
- `revenue_evidence`, the append-only receipt log of 007-A `Evidence` records per client, with intake provenance and a content digest; an exact redelivery is stored once and a reused delivery ID with other content is a second row (migration `0020_revenue_evidence`).
- The client revenue lock (namespace 7007) and the database clock as receipt time, so a client's receipts increase in commit order.
- `append_evidence`, `load_evidence` and `client_ledger` (the 007-A calculation, and the `ledger_feed` journal on first use).
- `GET /agencies/{a}/clients/{c}/revenue` with `finance:read`: verified totals and transactions, declared items and totals apart, pending adjustments and reconciliation items, currencies never summed.

**Tests.**
- `tests/integration/test_revenue_evidence.py`: T-01 to T-05.
- `tests/integration/test_revenue_migrations.py`: the `0020` privileges (insert and read only for `tracking_app`, nothing for `tracking_lifecycle`), the refused and empty downgrades, and the check constraints.

Existing expectations updated: the table counts (`test_data_policy.py`, `test_data_policy_schema.py`), the known tables of `test_postgres.py` and the cleanup order of `tests/integration/conftest.py`.

**Verification of 015-A** (from `backend/` with the project `.venv`, 2026-11-21):
- `python -m ruff check .` and `python -m ruff format --check .`: clean.
- `python -m pytest -m "not integration" -q`: 703 passed, 407 deselected (015-A adds no unit case).
- The integration suite on the disposable service (`run_db.py`, the `backend/tests/README.md` procedure with the variables of the guarded environment): 404 passed and 3 skipped (the browser journeys).
- `contracts/openapi.json` regenerated with the unit-test settings; its contract test passes.

**Mutation checks (015-A).** Each safeguard was disabled, its test rerun on the disposable service, and the source restored byte for byte (SHA-256 checked):

| Mutation | Test | Result |
|---|---|---|
| M1: the exact-redelivery key also covers the row ID | T-02 `test_exact_redelivery_is_stored_once` | Caught: three stored rows instead of one stored and two duplicates |
| M2: the revenue route checks `client:read` instead of `finance:read` | T-03 `test_revenue_read_needs_finance_access` | Caught: the analyst read answered 200 instead of 403 |

## 015-B: Paymob payments

**Scope (D3 to D7, D10, D12 to D14, A1).**
- `payment_sources`, `payment_source_secrets` and `payment_callback_diagnostics` (migration `0021_payment_sources`), with the `payment_source.*` audit actions.
- Owner and Admin routes to create, list, rename, disable or re-activate a source and to replace its merchant HMAC secret, which is sealed under the D-025 keyring (kind `paymob_hmac`), never returned, and kept valid for 24 hours after a replacement.
- `POST /payments/paymob/callback/{public_key}`: the gate first, then the per-peer and per-key rates (applied to any key, known or not), the source, the bounded JSON body and the documented HMAC-SHA512 against every live secret in constant time; one 401 answer for every unverifiable callback; 200 for every verified one.
- Minimization to the allowed fields at once, the D5 mapping with A1 (`test_mode`) and the signed-flag agreement of note N1, the D7 delivery ID, and one diagnostic row per verified callback.
- `RequestBoundary` with per-route limits: 64 KiB for the callback and 2 MiB for the CSV routes, a declared `Content-Length` above the limit refused before reading, and 16 KiB everywhere else.
- `TRACKING_PAYMENTS_PAYMOB_ENABLED` (default false), the re-verified `payments.processor_records` rule and the new `paymob.accept` rule (current from 2026-11-21, review 2027-11-21), and the lifecycle deletion of diagnostics after 30 days and of retired secrets.
- The synthetic sender `tests/paymob_callbacks.py`.

**Tests.**
- `tests/test_paymob_contract.py`: the documented example string of the HMAC page (T-10), verification with current and previous secrets, altered fields and unsupported bodies, card token callbacks, minimization (T-16), the mapping table (T-14) and unmapped states (T-15), the parent re-sent after a refund or void, Cairo local time and offsets (V-7), and the rules gate (T-20).
- `tests/integration/test_paymob.py`: T-10 to T-21, A1, the source routes with permissions and audit events, and the lifecycle deletion.
- `tests/integration/test_revenue_migrations.py`: the `0021` privileges and its refused and empty downgrades.

Existing expectations updated: the table counts, the known tables of `test_postgres.py`, the cleanup order, the approved data-policy rules (`test_data_policy.py`) and the reverified provider rules (`test_privacy_secrets_restore.py`).

**Verification of 015-B** (from `backend/` with the project `.venv`, 2026-11-21):
- `python -m ruff check .` and `python -m ruff format --check .`: clean.
- `python -m pytest -m "not integration" -q`: 723 passed, 426 deselected.
- The integration suite on the disposable service: 423 passed and 3 skipped (the browser journeys).
- `contracts/openapi.json` regenerated; its contract test passes.

**Mutation checks (015-B).**

| Mutation | Tests | Result |
|---|---|---|
| M1: the exact-redelivery key also covers the row ID, through the callback | T-12 `test_repeated_callback_counts_once` | Caught: the repeated sale was stored three times |
| M3: the HMAC comparison accepts any signature | T-10 `test_invalid_signatures_store_nothing`, `test_verify_accepts_current_and_previous_secrets_only` | Caught: an invalid signature answered 200 |
| M4: the failed and pending rules removed from the mapping | T-14 `test_states_follow_the_mapping`, `test_mapping_table` | Caught: failed and pending transactions posted |
| M5: the raw payload kept and the source data in the source reference | T-16 `test_no_card_or_customer_field_is_stored_logged_or_returned`, `test_minimize_keeps_only_allowed_fields` | Caught: the brand reached a stored source reference |
| M6: the gate always open | T-20 `test_gate_and_rules`, `test_rules_gate` | Caught: a source was created with the setting off |

## Self-review hardening before the pull request

A review of the callback route before the pull request found two gaps, both corrected with regressions that fail without the fix and pass with it:
- A body nested beyond the JSON decoder's depth raised `RecursionError`, an unauthenticated server error, instead of the uniform 401. The parser now treats it as unverifiable (`tests/test_paymob_contract.py::test_deeply_nested_body_cannot_be_verified`, `tests/integration/test_paymob.py::test_unreadable_bodies_and_a_missing_keyring_reveal_nothing`).
- Without the token keyring, a known source key answered 503 while an unknown one answered 401, which revealed key existence in that misconfiguration. The keyring is now checked before the source lookup, so every key answers 503 (`test_unreadable_bodies_and_a_missing_keyring_reveal_nothing`).

| Mutation | Tests | Result |
|---|---|---|
| M9: the `RecursionError` guard removed | both tests above | Caught: `RecursionError` reached the test client |
| M10: the keyring check removed | the integration test above | Caught: the unknown key answered 401 while the known one answered 503 |

## 015-C: CSV import and manual declarations

**Scope (D8 to D10, D14, D15).**
- `app.declarations`: the fixed CSV columns, the file refusals (personal-data headers and any column outside the fixed set refuse the whole file), the 10,000-row limit and the closed row error codes, including formula-injection cells; the manual declaration rules with a required reason.
- Preview (nothing stored), commit by import ID (the SHA-256 of the file; a repeated commit returns the record with 200 and stores nothing; a different body answers `import_mismatch`) and manual declarations, each commit and declaration with an audit event (`revenue_import.committed`, `revenue.declared`).
- Declared rows stored once as unverified `manual_declaration` evidence under the source account `declared`, with the committing or declaring user as actor; a row committed again through another file is an exact redelivery.
- `revenue_imports` (migration `0022_revenue_imports`) with the digest and counts only; the file is never kept. The lifecycle runner deletes import records 395 days after the commit; the evidence stays.

**Tests.**
- `tests/test_revenue_csv.py`: valid rows, optional columns and the byte order mark, every row code (T-30), order numbers that are not phones, duplicate rows, the header refusals (T-33), the file refusals, the size and row limits (T-34) and the manual declaration rules (T-36).
- `tests/integration/test_revenue_imports.py`: T-30 to T-36 and the 13-month lifecycle deletion.
- `tests/integration/test_revenue_migrations.py`: the `0022` privileges and its refused and empty downgrades; the `0020` refusal now starts at `0020`, because later revisions refuse their own intakes first.

**Mutation checks (015-C).**

| Mutation | Test | Result |
|---|---|---|
| M7: the repeated-commit check removed | T-31 `test_commit_stores_once_and_repeats_as_no_op` | Caught: the repeated commit answered 409 instead of the 200 no-op |
| M8: declarations stored as confirmed evidence | T-32 `test_declared_rows_stay_out_of_verified_totals_and_delivery` | Caught: declared rows entered the verified totals |

## First-round verification (Phase 5)

At the final code of the branch, from `backend/` with the project `.venv` (Python 3.12.4), on 2026-11-21:
- `python -m ruff check .` and `python -m ruff format --check .`: clean.
- `python -m pytest -m "not integration" -q`: 766 passed, 437 deselected.
- The integration suite on the disposable PostgreSQL 18 service (`run_db.py`, the variables of the guarded environment of `backend/tests/README.md`, `127.0.0.1:55433`): 434 passed and 3 skipped. The skipped cases are the three browser journeys, which need `TRACKING_RUN_BROWSER_TESTS=1`; they are reported as skipped, not passed. The documented port was available, so no guard change was needed.
- `contracts/openapi.json` regenerated with the unit-test settings; its contract test passes.
- Every new regression passes, including the two hardening regressions.
- The mutation checks M1 to M10 were run again at the final code: 11 of 11 caught (M1 twice), each source restored byte for byte.

An integration run was stopped once, on purpose, to add the hardening fixes; the guard then refused the populated disposable database, which was recreated (`down -v`, `up -d --wait database`) before the final run.

## Limitations of the first round

- Every Paymob case runs against the synthetic sender built from the documented pages. No live callback has been received. The text form of a null value in the signature is not documented and is read as an empty string. The references of refunds after captures and the retry behavior are also unconfirmed.
- `parent_transaction`, `is_refund`, `is_void` and `is_live` are outside Paymob's signature (note N1). The mapping requires the signed flags to agree with the kind, and the callback URL's key is a second barrier.
- A refund that references an authorization instead of its capture, and a void of an authorization that was never captured, stay pending and never change verified totals (note N2).
- Only the `egypt` region exists. Only currencies with two decimals are mapped from `amount_cents`.
- The phone check of declarations recognizes international numbers (a plus sign), so a local number in a reason is not refused. Card numbers are detected with the 003 rule, which may refuse an order number that happens to pass the Luhn check.
- Retention values are provisional development values (D14). Legal retention is pending Q-012 and Q-003.

## Second round: D-068

After the first-round pull request, the owner asked to finish the whole of Spec 015 in the same pull request for one review. The provider pages read on 2026-11-21 are recorded in the [second-round entry review](entry-review-round2.md) (W-1 to W-8), and D-068 approves its decisions E1-E13 as recommended. Design: [design-015b.md](design-015b.md). No provider was called and no provider account was created or changed.

## 015-D: bookings and CRM stage changes

**Scope (E2 to E6, E9 to E12).**
- `integration_sources`, `integration_source_secrets`, `integration_deliveries`, `bookings` and `booking_events` (migration `0023_integration_bookings`), with the `integration.*` audit actions; `crm_stage_rules` and `crm_deals` (migration `0024_crm_deals`), with the `crm_rule.*` audit actions.
- Cal.com sources (the client's write-only secret, `x-cal-signature-256`) and provider-neutral signed webhook sources (a platform-issued secret, the 004 signature), sealed, replaceable with a 24-hour overlap, off by default (`TRACKING_INTEGRATIONS_CALCOM_ENABLED` with the `calcom.webhooks` rule, and `TRACKING_INTEGRATIONS_WEBHOOK_ENABLED`) and audited.
- Bookings as chains of provider booking IDs whose state is derived from their minimal events, independent of delivery order; a later event that connects two chains merges them; bookings never write revenue and store nothing personal; a booking is linked to a collection subject only through its pseudonymous token with granted attribution consent.
- CRM deals from the signed webhook contract, the latest change by occurrence time; Owner and Admin won and lost stage rules; a won deal is verified only when its payment reference matches a posted sale of the client's verified ledger; amounts need `finance:read`.

**Tests.**
- `tests/test_integrations_contract.py`: Cal.com parsing and minimization, the refusals, the subject token format, every delivery order of a chain, a cancellation of a superseded ID, chains received backwards, and the deal contract.
- `tests/integration/test_bookings_crm.py`: T-50 to T-58, T-70 to T-72 for bookings and CRM.
- `tests/integration/test_integration_migrations.py`: the `0023` and `0024` privileges, the refused and empty downgrades.

**Verification of 015-D** (2026-11-21): ruff clean; unit 778 passed; integration on the disposable service 450 passed and 3 skipped (the browser journeys).

**Mutation checks (015-D).**

| Mutation | Tests | Result |
|---|---|---|
| M11: the Cal.com signature comparison accepts any signature | T-50 `test_signed_calcom_callback_and_refusals` | Caught: an invalid signature answered 200 |
| M12: every event decides the status, not only those of the current ID | `test_cancelling_a_superseded_id_keeps_the_booking` (and T-52) | Caught: the cancellation of a rescheduled ID cancelled the booking |
| M13: the booking event key also covers the row ID, and the delivery check is removed | T-52 `test_every_order_gives_the_same_booking_and_duplicates_count_once` | Caught: 36 events stored instead of 18 |
| M14: the attribution consent check of a lead link removed | T-53 `test_lead_links_need_identifier_evidence_and_consent` | Caught: a subject without attribution consent was linked |
| M15: any payment reference verifies a won deal | T-56 `test_stage_changes_never_become_revenue_without_rule_and_evidence` | Caught: deals with unmatched references counted as verified |
| M16: the gate of the integration kinds always open | T-70 `test_gates_and_rules` | Caught: a source was created with the settings off |

## 015-E: WhatsApp referrals

**Scope (E7 to E12).**
- `whatsapp_numbers` and `whatsapp_messages` (migration `0025_whatsapp`), with the `whatsapp_number.*` audit actions.
- `GET /integrations/whatsapp/webhook` (the handshake with the verify token) and `POST` (notifications signed with the Meta app secret, `X-Hub-Signature-256`), off by default (`TRACKING_WHATSAPP_ENABLED`, `TRACKING_WHATSAPP_APP_SECRET`, `TRACKING_WHATSAPP_VERIFY_TOKEN`, the `whatsapp.cloud_api` rule), with a 3 MiB body bound.
- For each inbound message of a registered number, only the referral is kept (source type, ad ID, click-ID presence), keyed by a SHA-256 of the message ID; a message without a referral is unknown; no person field is stored and no conversation is correlated with a person.
- Owner and Admin number registration with audit events; `GET .../whatsapp/referrals` with `client:read`.

**Tests.**
- `tests/test_whatsapp_contract.py`: the signature, a correctly signed but deeply nested body, the referral minimization, status notifications and malformed bodies.
- `tests/integration/test_whatsapp.py`: T-60 to T-64, T-70 to T-72 for WhatsApp.
- `tests/integration/test_integration_migrations.py`: the `0025` privileges and its refused downgrade.

**Mutation checks (015-E).**

| Mutation | Tests | Result |
|---|---|---|
| M17: the WhatsApp signature comparison removed | T-60 `test_signed_notifications_and_the_handshake`, `test_signature_is_verified_in_constant_time` | Caught: an invalid signature answered 200 |
| M18: messages without a referral are dropped instead of counted as unknown | T-61 `test_referrals_and_unknown_messages` | Caught: 3 messages and 0 unknown instead of 4 and 1 |
| M19: the message key also covers the row ID | T-63 `test_repeats_and_unregistered_numbers` | Caught: 6 messages stored instead of 2 |
| M20: the WhatsApp gate always open | T-70 `test_gates_and_rules` | Caught: a notification was accepted with the setting off |

**Environment note.** During the 015-E checks the workstation's Docker Desktop stopped (the session resumed on 2026-11-22), so two mutation runs met connection timeouts. Every mutated source was confirmed restored, Docker Desktop was started again, the disposable Compose project was recreated (`down -v`, `up -d --wait database`), and the 015-E mutation checks were rerun in full.

## Final verification (whole specification)

At the final code of the branch, from `backend/` with the project `.venv` (Python 3.12.4), on 2026-11-22:
- `python -m ruff check .` and `python -m ruff format --check .`: clean.
- `python -m pytest -m "not integration" -q`: 781 passed, 462 deselected.
- The integration suite on the disposable PostgreSQL 18 service (`127.0.0.1:55433`): 459 passed and 3 skipped. The skipped cases are the three browser journeys, which need `TRACKING_RUN_BROWSER_TESTS=1`; they are reported as skipped, not passed.
- `contracts/openapi.json` regenerated; its contract test passes.
- The mutation checks M1 to M20 were run again at the final code: 21 of 21 caught (M1 runs twice), each source restored byte for byte.

## Limitations of the second round

- Every booking, CRM and WhatsApp case runs against synthetic senders built from the documented pages. The Cal.com signature encoding over the raw body, the hidden-field prefill that carries the subject token, and whether Cal.com also cancels the old ID of a reschedule are unverified until a live check.
- A booking is linked only to a pseudonymous collection subject; person-level links and WhatsApp conversation correlation wait for 006.
- The signed webhook is the fallback for booking tools other than Cal.com and for any CRM; a named CRM connector (for example HubSpot) is a follow-up with its own decision.
- A WhatsApp referral's `source_type` values other than `ad` are kept as reported (`post`) or as `other`; the documentation shows only `ad`.

## Follow-ups

- A live Paymob check with an owner sandbox account and an HTTPS-hosted API (020), separately approved; live Cal.com and WhatsApp checks with owner accounts, likewise.
- A legal review (Q-012), before live intake, of whether a merchant may direct callbacks that carry the last four card digits to this platform under Paymob's terms.
- 007-B: persisted postings and movements, finance write permissions, audited corrections, reconciliation workflows and the approval of declarations.
- 006: linking payments, bookings and WhatsApp conversations to people and journeys.
- Outside the acceptance criteria (E1): Stripe, Paymob reads and backfill, third-party form tools, ManyChat and a named CRM connector, each with its own decision.
- Native `tracking_sys` migration of `0020` to `0025`, and deployment, which remain separate owner decisions.
