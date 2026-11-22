# Spec 015 review correction evidence

Corrections of findings R001-R011 of the [001-015 review](../../reports/specs-001-015-review-2026-11-22.md) under D-069 and D-070, on `codex/spec-015-business-integrations` (PR 13). The per-finding status is in the [tracker](review-corrections-tracker.md); the execution instructions are in the [handoff](review-corrections-prompt.md). Every check ran against synthetic data on the disposable PostgreSQL service; nothing called Paymob, Cal.com, a CRM or Meta, and no migration ran on the native `tracking_sys`.

## Environment

- Worktree `.worktrees/spec-015-business-integrations`, project `.venv` with Python 3.12.4 (SQLAlchemy 2.1.6, Alembic 1.20.1, Psycopg 3.3.6, FastAPI 0.162.0, pytest 9.2.0).
- Disposable PostgreSQL 18.6 (`postgres:18.6-bookworm@sha256:5c4783a8...`) in the Compose project `tracking-system-foundation-test` on `127.0.0.1:55433`, started with a synthetic environment file kept outside the repository. The port was free and outside the Windows excluded port ranges on 2026-11-22, so the integration guard of `backend/tests/integration/conftest.py` ran unchanged (the review had used a private copy on 55434).
- Tests run through a runner that drops inherited `TRACKING_`, `PG` and `PYTHON` variables and sets `TRACKING_RUN_DB_TESTS=1`; the owner's `.env` is never read because the worktree has none.

## Baseline reproduction at `db750d1`

`git archive db750d1` was extracted into a scratch directory, and `reports/specs-001-015-review-regressions.patch` passed `git apply --check` and was applied there. Application code was unchanged.

| Run | Result |
|---|---|
| `pytest tests/integration/test_review_001_015.py -q --tb=line` | **12 failed** in 25.95 s (repeated: 23.87 s). Every case failed at its intended assertion: line 39 (R001, test-to-live promotion stored a verified EGP 1,000.00 sale), line 50 (R001, refund retargeted, answered `received`), line 58 (R005, `500 Internal Server Error`), `CheckViolation` on `ck_bookings_valid_link` (R002), line 97 (R003, `linked` stayed 1 after withdrawal), line 110 (R006, one booking instead of two), line 138 (R007, `won_unverified` for the reversed order), line 165 (R008, `open: 500` for 501 deals), line 204 (R010, USD group unreachable), line 222 (R004, the claimant's number was `active` and received the message), line 235 twice (R009, `500` for the list `source_type` and for the 12-digit timestamp). No fixture, connectivity or dependency failure. |
| `pytest tests/test_review_instagram_cursor.py -q` | **1 failed** in 0.15 s (R011): the resumed page returned `2024-11-24` after `2024-11-22`. |

The same thirteen cases were then applied to the correction branch unchanged (`git apply`), so the permanent suite carries them.

## Corrections

Each section below records the root cause, the correction, the regression and adjacent cases, and the commit. Sections are completed as each correction lands; the final verification and the second review pass follow at the end. A "mutation" disables the new safeguard in the working tree, reruns the named tests on the disposable database and restores the file byte for byte (SHA-256 checked); "caught" means the tests failed.

### R001 P1: Paymob financial meaning from signed fields only

**Root cause.** Paymob's processed-callback HMAC covers 20 documented fields (V-2); `is_live`, `parent_transaction`, `is_refund` and `is_void` are outside it. The mapper still took the environment from `is_live` and the refunded sale from `parent_transaction`. Note N1's signed-flag rule only constrained the operation's shape, so an unchanged signature allowed both reproduced changes.

**Decision.** D-070 (owner, 2026-11-22). The Paymob pages read that day state that integration IDs differ between test and live mode ("the table will refresh with a different set of Integration IDs depending on the mode"; "The mode is controlled by the keys and integration IDs you use") and list `integration_id` and `order.id` among the signed fields. They do not show a refund response, so the shared order of a refund and its sale is recorded as an assumption for the live check.

**Correction.**
- `payment_sources.live_integration_ids` (migration `0021` amended in place): 1 to 20 positive bigints without nulls, required at creation, changeable by an Owner or Admin with the existing `payment_source.updated` audit event, and returned by the source routes.
- `map_transaction` posts only when `is_live` is true and the signed `integration_id` is declared; otherwise `test_mode` with the new diagnostic reason `undeclared_integration`.
- `receive_callback` refuses a refund or void whose stored parent sale carries another signed order ID (`unmapped`, `invalid_parent`, nothing stored).
- `client_ledger` holds back, before the 007-A calculation, a Paymob refund whose parent arrived later with another order (`unbound_refunds`). It never reaches the calculation, the journal, attribution, conversion delivery or CRM verification; the revenue read lists it as pending with `parent_order_mismatch`.
- The synthetic sender now gives each payment its own order (every transaction previously shared order `810000001`, which would have hidden a cross-order retargeting), gives children their parent's order, and gives test-mode transactions a test integration ID, as Paymob documents.

**Tests.** The two regressions pass. New cases:
- `test_paymob.py`: `test_only_declared_live_integrations_post` (tampered `is_live`, undeclared live integration, audited declaration), `test_live_integration_ids_are_validated`, `test_refund_cannot_move_to_a_sale_of_another_order` (refused moved copy, then the genuine refund still posts), `test_refund_before_a_sale_of_another_order_stays_held` (held refund absent from totals, journal and 014-B candidates; an own-order refund still posts).
- `test_revenue_migrations.py::test_0021_live_integration_check`.
- `test_paymob_contract.py`: `test_only_a_declared_live_integration_posts`, `test_refund_and_sale_share_the_signed_order`.

The existing T-10 to T-21 and A1 cases, including duplicates, every delivery order, voids, captures and the unchanged HMAC example, pass unchanged in substance. Three fixtures were adapted to the D-070 contract, each still asserting the same property: `test_revenue_evidence._record` gives its Paymob-intake records a Paymob-shaped source reference with the sale's order, `test_no_card_or_customer_field_is_stored_logged_or_returned` expects the sale's own order in the reference, and the mapping-table unit case expects the generated order.

**Results.**
- Integration: the two regressions with `test_paymob.py`, `test_revenue_evidence.py`, `test_revenue_migrations.py` and `test_revenue_imports.py`, 53 passed in 93.76 s.
- Unit: `test_paymob_contract.py`, `test_revenue_ledger.py`, `test_revenue_csv.py` and `test_contract.py` (with the regenerated OpenAPI snapshot), 112 passed.
- Mutations: R001-a (integration check removed), R001-b (intake parent check removed) and R001-c (read-time hold removed) are each caught by a regression or a new case.

**Remaining limits.** A merchant who lists a test integration as live makes its test payments count; that is the source owner's audited assertion. The live check confirms that test and live integration IDs differ and that a refund or void carries its sale's order ID; a refund whose order differs meanwhile stays visibly pending rather than adjusting a sale.

### R002 P1: Booking detachment and subject deletion are atomic

**Root cause.** `bookings.subject_id` references the subject with `ON DELETE SET NULL`, while `ck_bookings_valid_link` requires `subject_id` and `linked_at` to be null together. Deleting a linked subject nulled only `subject_id`, so the check failed and the whole erasure transaction rolled back. The lifecycle runner hit the same constraint when it deleted an expiring subject. At `db750d1` the new lifecycle case below aborted the run with `CheckViolation`, and the owner's erasure route answered `409 state_conflict`, both verified on the disposable database.

**Correction.**
- `erase_subject` clears `subject_id` and `linked_at` together, under the client privacy lock it already holds, before deleting the subject. The deletion request records the booking store as `booking_links` (`done`, or `not_applicable`). The runtime role already had this column update.
- The lifecycle runner gains the client-scoped clearing target `booking_links`. In the batch that deletes an expiring subject (idle, without events or consent records), it clears both link columns of the subject's bookings. The subject is deleted only once no booking references it, so a bounded batch can never reach the constraint.
- `tracking_lifecycle` receives `SELECT (id, updated_at, client_id, subject_id)` and `UPDATE (subject_id, linked_at)` on `bookings` (migration `0023` amended in place, D-070), and nothing else on that table.
- The consistency constraint and the foreign key are unchanged; the foreign key stays a fail-closed backstop.

**Tests.** The regression passes. New cases in `test_bookings_crm.py`:
- `test_erasure_detaches_linked_bookings_and_blocks_replay`: the owner route with two linked bookings; another subject's and another client's links stay; every booking is kept; one tombstone; a later delivery with the erased token records `subject_unknown`; the token cannot record consent again; a subject without bookings reports `not_applicable`.
- `test_failed_erasure_keeps_the_link`: a rolled-back erasure leaves the link, the subject and no tombstone.
- `test_lifecycle_expiry_detaches_a_newer_booking_from_an_old_subject`: the real `tracking_lifecycle` role. Two recent bookings of a subject past retention are detached and kept, the subject and its consent are deleted, an active subject keeps its link, and a second run does nothing.

`test_integration_migrations.py::test_0023_and_0024_privileges` checks the exact new grant. Two exact-value expectations in `test_collection.py` now include the new key with value `0` or `not_applicable`; the store is new, not a changed outcome.

**Results.**
- Integration: the regression with `test_bookings_crm.py`, `test_integration_migrations.py`, `test_collection.py` and `test_lifecycle.py`, 90 passed in 140.16 s.
- Baseline proof: the new lifecycle and erasure cases, copied into the `db750d1` archive, fail there (lifecycle `CheckViolation`; erasure `409 state_conflict`).
- Mutations: R002-a (erasure detach removed) and R002-b (lifecycle clearing removed) are caught.

### R003 P1: Booking links follow the current attribution consent

**Root cause.** `_link` checked consent only when it created a link, and `bookings_view` counted any stored `subject_id`. A withdrawal or an expiry therefore left a booking attributable, and a chain merge copied a stored link without a check. D-068 E4 requires a link only while attribution consent is granted.

**Correction.** No schema change.
- Withdrawal and denial: `record_consent`, under the client privacy lock that booking intake also takes, detaches the subject's bookings (both columns) when attribution is withdrawn or denied.
- Grant after a lapse: it also detaches them when attribution is granted while it was not granted before (expired, withdrawn, denied or unknown). A stored link therefore survives only an uninterrupted grant, and a new grant restores nothing until a later delivery carries the token and the required evidence again.
- Reads: `bookings_view` computes `totals.linked` and each row's `linked` from one rule, `effective_link`: the subject's latest attribution record (receipt time, then ID, as `app.privacy.consent.current_state`) is an unexpired grant. This covers an expiry with no consent change, and records removed by the lifecycle.
- Merges: a chain merge carries a link only while its subject's consent is granted.
- Other readers: the booking reads are the only reader of the relation (no attribution or delivery path consumes bookings yet), and erasure and expiry clear it (R002).

**Tests.** The regression passes. New cases in `test_bookings_crm.py`:
- `test_withdrawal_detaches_and_a_new_grant_restores_nothing`: an immediate detach; a later delivery while withdrawn records `consent_missing`; exact replays before and after a new grant are no-ops; the new grant alone restores nothing; a later delivery with the token links again; a denial detaches.
- `test_expiry_stops_the_link_and_a_renewal_after_the_lapse_restores_nothing`: an expired grant stops counting on reads; a renewal after the lapse detaches instead of reviving; a renewal before expiry keeps the link.
- `test_a_merge_never_carries_an_ineffective_link`: both the granted and the expired case.
- `test_withdrawal_and_a_delivery_serialize_on_the_privacy_lock`: concurrency in both orders, with the waiting transaction detected through `pg_locks`. A withdrawal holding the lock makes the delivery record `consent_missing`; a delivery holding the lock is detached by the waiting withdrawal.

**Results.**
- Integration: both regressions with `test_bookings_crm.py` and `test_collection.py`, 71 passed in 141.23 s.
- Mutations: R003-a (consent-change detach removed), R003-b (read-time rule removed) and R003-c (merge check removed) are caught.

### R004 P1: WhatsApp numbers route only after a verified binding

**Root cause.** An agency Owner's registration created an `active` routing entry for any unused numeric phone number ID. The number was unique across clients, and the authority checked was only the agency's own workspace authority. Every client's notifications reach the platform's one Meta app, so another agency that knew a business's ID could capture its authentic notifications and block the real owner's later registration.

**Decision.** D-070: the registration is a claim, and a platform operator outside the agency roles verifies it after an out-of-band ownership check in Meta Business Manager. Revocation and transfer go through the operator; nothing calls Meta, and no message data is stored for the proof.

**Correction** (migration `0025` amended in place).
- `whatsapp_numbers` holds claims: `pending` (the registration default, routes nothing), `active` and `disabled` (verified, with `verified_at`, enforced by `ck_whatsapp_numbers_valid_verification`) and `revoked`.
- The global uniqueness is replaced by two partial unique indexes: one verified binding per number, and one unrevoked claim per client and number.
- `verify_claim` refuses a second verified binding (`number_already_bound`; a concurrent conflict on the index maps to the same code), and `revoke_claim` ends a claim or binding. The new operator command `python -m app.whatsapp_binding` exposes both with `list`, needs `--confirm`, and prints identifiers and states only.
- Agencies may switch only a verified binding (`409 verification_required` for pending, `409 claim_revoked` for revoked). Routing still requires an active binding of an active client and agency. `tracking_app` may also update `verified_at`; operator actions are recorded on the claim row.

**Tests.** The regression passes. New cases in `test_whatsapp.py`:
- `test_unproven_claims_route_nothing_and_cannot_block_the_owner`: another agency's first claim routes nothing; the owner can still claim; neither agency can self-activate; only the operator's verification routes; a second verification fails.
- `test_disabled_and_revoked_bindings_and_transfer`: disable and re-activate; revocation; transfer to another client's pending claim; stored messages keep their client; operator refusals; a re-claim after revocation.
- `test_one_verified_binding_per_number_in_the_database`: the partial index and the verification check refuse direct writes.
- `test_operator_command`: list, verify and revoke with closed errors; refused without `--confirm` or with a malformed ID.

The `wa` fixture now verifies its number through the operator function. `test_numbers_permissions_audit_and_isolation` had asserted that a second client's registration of a registered number answers `409`. That was the defect, the global uniqueness that let a first claimant block the owner. The test now asserts the reviewed contract: the second client's claim is accepted as pending and routes nothing until verified, and only the same client's second claim answers `409`. `test_0025_privileges_and_downgrade` checks the `verified_at` grant.

**Results.**
- Integration: the regression with `test_whatsapp.py` and `test_integration_migrations.py`, 18 passed in 40.14 s.
- Mutations: R004-a (pending claims route) is caught by the regression's assertion, and R004-b (agency self-activation) by the new owner-claim case.

**Remaining limits.** Verification relies on the operator's out-of-band check. A provider-verified binding through Meta's own onboarding (Embedded Signup) needs live Meta access and app review and remains a later production option.

### R005 P2: Malformed Paymob callback types answer the uniform 401

**Root cause.** `parse_body` tested `type` for membership in a set before checking that it was a string. A list or object raised `TypeError` before the signature was checked, so the route answered `500` instead of the uniform `401`.

**Correction.** `type` must be a string before the membership test; anything else raises `Unverifiable("unsupported_type")`, which the route answers with the uniform `401 invalid_signature` and stores nothing. The signature, size, rate, keyring and source-lookup steps are unchanged and still run in their documented order.

**Tests.** The regression passes. New cases:
- `test_paymob_contract.py::test_malformed_type_is_unverifiable_not_an_error`: nine discriminator shapes (list, objects, null, number, fraction, boolean, lowercase string), each with a valid and an invalid signature.
- `test_paymob.py::test_malformed_callback_types_answer_the_uniform_401`: the real application without exception passthrough, eight shapes with valid and invalid signatures plus a missing `type`, all `401` and nothing stored; afterwards both documented kinds (`TRANSACTION` and `TOKEN`) are still accepted with their diagnostics.

**Results.**
- Unit: `test_paymob_contract.py`, 32 passed.
- Integration: the regression with `test_paymob.py`, 23 passed in 64.50 s.
- Mutation: R005-a (membership test without the type check) is caught by the regression, which answers `500` again.

### R006 P2: Booking identities are scoped to their source

**Root cause.** Chain discovery looked up booking events by client and provider kind. Every signed webhook source of a client therefore shared one namespace of booking IDs: two tools' local `booking-1` became one booking, and a reschedule or cancellation from one tool could move or cancel the other's booking.

**Correction** (migration `0023` amended in place, D-070).
- `bookings` and `booking_events` carry `source_id`, with composite foreign keys to the delivering integration source. The lookup indexes are now (`source_id`, `ref`) and (`source_id`, `previous_ref`).
- Chain discovery, extension and merging use the delivering source only. The namespace is the source for both kinds; the integrations guide says to replace a Cal.com source's secret rather than create a second source for the same account.
- The delivery digest was already unique per source; the event uniqueness within a booking and the derived state rules are unchanged.

**Tests.** The regression passes. New cases in `test_bookings_crm.py`:
- `test_each_source_keeps_its_own_booking_identities`: a reschedule and a cancellation from the second source leave the first source's `booking-1` scheduled; the first source's cancellation of an ID it never used starts its own chain; a cancellation of a moved-away ID stays ignored.
- `test_duplicates_and_out_of_order_chains_stay_within_one_source`: a repeated delivery and a re-sent event with a new envelope ID stay one event; an out-of-order cancellation, creation and reschedule end in one booking; another client's source with the same IDs is separate; two Cal.com sources of one client keep separate bookings.

**Results.**
- Integration: the regression with `test_bookings_crm.py` and `test_integration_migrations.py`, 27 passed in 84.20 s.
- Unit: `test_data_policy.py` and `test_integrations_contract.py`, 22 passed.
- Mutation: R006-a (lookup by client and provider again) is caught by the regression (`1 == 2`).

### R007 P2: CRM optional values are independent of delivery order

**Root cause.** `receive_deal` discarded an older change entirely and applied optional values only with a newer stage. A 09:00 change with a payment reference followed by a 10:00 won change without one gave `won_verified`; the reverse order dropped the reference and gave `won_unverified`.

**Contract.** The published contract already marks `amount`, `currency` and `payment_reference` optional, and the in-order behavior kept a supplied reference. The reviewed fix therefore keeps partial updates, so the public contract does not change, and makes them order-independent rather than adopting complete snapshots.

**Correction** (migration `0024` amended in place, D-070).
- `amount_at` and `payment_reference_at` record the occurrence time of the change that supplied the current value, with a check that each is null exactly when its value is.
- The stage (with its pipeline and previous stage), the amount pair and the payment reference are each replaced only by a later change, compared on (occurrence time, value), so ties at the same instant resolve the same way in every order. The amount and currency are written together.
- `updated_at` moves only when something changed. Stage changes still never write revenue evidence.

**Tests.** The regression passes. New cases in `test_bookings_crm.py`:
- `test_every_delivery_order_gives_the_same_deal`: four changes, two without optional values, in all 24 orders; one final state with the latest stage, the latest amount pair and the latest reference, shown as `won_verified` with the linked sale; the only revenue evidence is the synthetic sale.
- `test_changes_at_the_same_instant_resolve_the_same_way`: same-instant ties in both orders, omitted values kept, and an older amount losing.
- `test_the_latest_payment_reference_decides_verification`: a later non-matching reference wins in both orders.

`test_0023_and_0024_privileges` checks the two new update grants.

**Results.**
- Integration: the regression with `test_bookings_crm.py` and `test_integration_migrations.py`, 30 passed in 107.11 s.
- Unit: `test_data_policy.py` and `test_integrations_contract.py`, 22 passed.
- Mutation: R007-a (optional values applied only with a newer stage) is caught by the regression.

### R008 P2: CRM totals cover the full authorized scope

**Root cause.** `deals_view` selected the newest 500 deals and computed `totals` from that list, with no continuation or truncation indicator. With 501 open deals it reported 500, and older won and lost deals disappeared from the totals.

**Correction.** No schema change.
- The totals are a SQL aggregate over every deal of the client. Deals are grouped by pipeline, stage and whether the payment reference is one of the client's verified ledger sales (passed as one array parameter), then mapped through the active rules.
- The detail rows are a keyset page in a stable order: `first_received_at` descending, then `id` descending, so later updates never move a deal between pages.
- The route takes `limit` (1-500, default 500) and an opaque `after` cursor carrying the complete key, and answers `has_more`, plus `next_after` when another page follows. A malformed cursor or limit answers `422`.
- The OpenAPI snapshot is regenerated. Permissions are unchanged: totals and rows need `client:read`, and amounts `finance:read`.

**Tests.** The regression passes. New case in `test_bookings_crm.py`: `test_deal_totals_cover_every_deal_and_every_row_is_reachable`. It has 1,203 deals of one client in every outcome (open, won with a matching verified sale, won with another or no reference, lost), USD and EGP amounts, and 30 deals of another client. The totals are exact on every page and for `limit=1`; five pages of 250 reach every deal exactly once and no other client's deal. Amounts stay hidden from a `client:read` reader, finance readers see per-deal currencies, and malformed cursors and limits are refused.

**Results.**
- Integration: both CRM regressions with `test_bookings_crm.py`, 27 passed in 108.19 s.
- Unit: `test_contract.py` with the regenerated snapshot passes.
- Mutations: R008-a (totals over a bounded subset) is caught by the regression (`open: 500`), and R008-b (a cursor without the ID tie-break) by the traversal case.

The independent partial review of `a291bb6` ([report](../../reports/spec-015-corrections-review-a291bb6-2026-11-22.md)) found no further blocking defect in R001-R008: full backend suite 1,286 passed and 4 failed, the failures being exactly R009 (two cases), R010 and R011. The sections below complete those three findings on top of that reviewed head, without changing the reviewed corrections.

### R009 P2: Malformed WhatsApp messages stay confined to themselves

**Root cause.** The route parsed every message of a verified batch before storing any of them. `_message` tested a list or object `source_type` for set membership (`TypeError`). `_moment` passed a twelve-digit timestamp to `datetime.fromtimestamp`, which raises `OSError` on Windows and `ValueError` or `OverflowError` elsewhere. Either error answered 500, so the valid sibling was lost and Meta would retry the whole batch for days.

**Correction.** No schema change.
- A source type counts as `ad` or `post` only when it is that string, and every other value is `other`, as the design already says.
- A timestamp is bounded to 2015-2099 as Unix seconds and converted arithmetically, so no platform call can raise; values outside the range are unknown.
- Each item is read through `_read`, which skips non-objects and keeps a narrow guard (`TypeError`, `ValueError`, `OverflowError`) around the pure parsing of one message only.
- The parser has no database access; storage stays outside the guard, and its errors still fail the request. The acknowledgement contract is unchanged: every verified batch is 200, an invalid signature is 401, and no diagnostic row or person field is added.

**Tests.** Both regression cases pass. New cases:
- `test_whatsapp_contract.py::test_malformed_items_never_raise_and_keep_their_siblings`: six source-type shapes, three out-of-range timestamps, a non-object referral, a missing or oversized ID, three non-object items, with valid messages first and last.
- `test_whatsapp_contract.py::test_message_times_are_bounded_before_conversion`: the range edges.
- `test_whatsapp.py::test_malformed_messages_never_discard_valid_siblings`: the real application without exception passthrough, malformed messages first and last, unsupported entry, change and value shapes, a second change, extreme dates and a repeat. Seven messages are stored once, two with unknown times.
- `test_whatsapp.py::test_unsigned_batches_and_storage_failures_are_never_acknowledged`: an unsigned batch is 401; a simulated database error while storing is a server error with nothing stored.

**Results.**
- Unit: `test_whatsapp_contract.py`, 5 passed.
- Integration: the three WhatsApp regressions with `test_whatsapp.py`, 17 passed in 36.77 s.
- Mutations: R009-a (membership test without the type check) is caught by the new application case and the unit cases. R009-b (the unbounded `fromtimestamp`) is caught by the timestamp regression, which answers 500 again on this Windows workstation, and by the unit cases.

### R010 P2 (Spec 014): Spend pages follow the complete grouping key

**Root cause.** `read_spend` groups rows by (object ID, currency) and sorts them by that pair, but its cursor and filter used the object ID alone. With two currencies for one ad and `limit=1`, the first page ended at `(111, EGP)` with cursor `111`, and the filter `object_id > 111` skipped `(111, USD)`. D-064 D4 deliberately keeps each fact's reported currency after an account currency change, so this is a supported stored state. Facts without an ad set or campaign ID also produced the cursor `""`, which the route's object-ID parameter could not accept.

**Correction.** No schema change; existing facts keep their currencies.
- The cursor is the last row's complete key, `"<object ID>:<currency>"`, with an empty object ID for a missing one.
- The next page starts strictly after that pair in the same tuple order as the sort.
- The route validates the cursor's format (`^(?:[1-9][0-9]{0,31})?:[A-Z]{3}$`). An old object-only cursor is refused, which is safe because no client of the unreleased API exists.
- Totals, the financial permission and the row contents are unchanged. The OpenAPI snapshot and the advertising guide are updated.

**Tests.** The regression passes. New case `test_ad_spend.py::test_spend_pages_follow_object_and_currency`: six facts with two currencies for one ad, a fact without an ad set or campaign, and one without a campaign. At the ad, ad set and campaign levels, limit-1 traversal reaches every (object, currency) group exactly once in order, including the missing-ID groups. The totals (EGP 160, USD 570) are equal on every page; the final page has no cursor; a page after the last cursor is empty; a full page matches the traversal. Seven malformed cursors are refused, and a reader without the financial grant is refused.

**Results.**
- Integration: the regression with `test_ad_spend.py` and `test_roas.py`, 16 passed in 28.64 s.
- Unit: `test_advertising_spend.py` and `test_advertising_roas.py`, 39 passed; `test_contract.py` passes with the regenerated snapshot.
- Mutation: R010-a (filter on the object ID only) is caught by the regression.

### R011 P2 (Spec 010): The Instagram day cursor stays stable across midnight

**Root cause.** `_account_page` built the list of UTC days from a start that `fetch_page` recomputes from the current time on every page (`max(since, now - 729 days)`). The cursor was a numeric offset into that list. After a UTC midnight the list started one day later, so the same offset pointed one day further: the regression read 2024-11-22, then 2024-11-24. This is the Spec 010 follow-up already recorded from R011-15 (YouTube) in the [010 evidence](../010-instagram/evidence.md).

**Correction.** The adapter only; the Instagram API calls and the token and access follow-ups are unchanged, and nothing called Meta.
- The cursor is `day:<first day>:<next day>`, both ISO dates (`day_cursor`, `parse_day_cursor`). The first day is fixed by the first page and is the start of the read's gapless coverage; the next day is absolute.
- Each page recomputes the history limit (the day of `now - 729 days`). When the next day is still within it, that day is read, so one midnight changes nothing.
- When a long deferral has left the next day behind the limit, those days can no longer be read. The read continues at the limit and reports `covered_from` from there, instead of claiming the skipped days, as the reasoning of the YouTube correction does for a moving bound.
- The end still follows the latest complete day. A malformed or old-format cursor is a permanent `invalid_cursor`; no stored cursor of the old format exists outside disposable databases.

**Tests.** The regression passes. New file `tests/test_connector_instagram_day_cursor.py`, each page using a new provider object so the cursor alone carries the position:
- `test_one_midnight_continues_with_the_next_day`: November 22 to 25 without a gap, covered from the 22nd.
- `test_several_midnights_restart_coverage_at_the_history_limit`: after three days, continue at the 25th, covered from the 25th.
- `test_resume_within_the_limit_keeps_the_fixed_first_day`: the first day is kept, and the end moves to the newly complete day.
- `test_an_exhausted_window_ends_the_read`: an exhausted window ends the read with truthful watermarks.
- `test_malformed_cursors_are_refused`: eight shapes, including the old offset format.

The existing adapter, feasibility and Instagram runtime tests pass unchanged.

**Results.**
- Unit: the new file with the regression, 13 passed; `test_connector_instagram_adapter.py`, `test_instagram_feasibility.py` and the regression, 41 passed.
- Integration: `test_connector_instagram.py` and `test_connector_instagram_login.py`, 11 passed in 19.51 s.
- Mutations: R011-a (the offset applied to a day list recomputed from now) is caught by the regression, and R011-b (no coverage restart behind the limit) by the several-midnights case.

## Second review pass

After the last correction, R001 to R011 were re-read in order against the complete diff from `db750d1` and the final code, not from the notes above. This is the implementer's own second pass; the only external review is the independent partial review of R001-R008 at `a291bb6`.

| ID | Failure mechanism rechecked | Positive counterpart rechecked | Verdict |
|---|---|---|---|
| R001 | `map_transaction` takes the environment only from a declared signed `integration_id` together with `is_live`. The refund parent is bound to the signed order in `_parent_bound`, at intake, and in `unbound_refunds`, before `calculate()`. The only ledger computation in the application is `client_ledger`; `load_evidence`, the raw receipt log, has no consumer outside tests. | Declared live sales and own-order refunds post in every order; duplicates and the parent's re-sent callback stay exact redeliveries. | Closed |
| R002 | `erase_subject` and the lifecycle `booking_links` target clear both link columns before the subject row is deleted. The subject predicate waits for the links, so no path leaves only the foreign key's `SET NULL`. Booking events still cascade as table owner, with no added lifecycle grant. | Bookings are kept; other subjects, sources and clients are untouched. | Closed |
| R003 | `record_consent` evaluates the previous attribution state before appending records, and detaches on a non-grant or a re-grant after a lapse. `bookings_view` derives the total and each row from one `effective_link` expression scoped to the client. A merge copies a link only through `_granted`. | Continuous renewals keep links; a later delivery with the token links under a new grant. | Closed |
| R004 | Registration inserts `pending`. Routing selects `active` only. Agency updates refuse pending and revoked claims. Only `verify_claim` sets `verified_at`, and the partial indexes back it against a concurrent writer. | A verified binding routes, and disable, re-enable, revoke and transfer behave as recorded. | Closed |
| R005 | The discriminator is type-checked before membership; the 401 path stores nothing. | Transaction and token callbacks post as before. | Closed |
| R006 | Every chain lookup and insert carries the delivering `source_id`; merges stay inside the source. | Duplicates and out-of-order chains within a source still form one booking. | Closed |
| R007 | Each part of a deal compares (time, value) on its own, so no part depends on another part's order, and `updated_at` moves only on change. | All 24 orders converge; amounts and currencies move together. | Closed |
| R008 | Totals are aggregated over the client's whole scope with the ledger sale set as one array parameter. Rows use an immutable keyset, so the totals never come from the page. | Every row is reachable once; amounts stay behind `finance:read`. | Closed |
| R009 | No platform time call remains, and source types are type-checked. The narrow per-item guard covers pure parsing only; storage errors still fail the request. | Valid siblings are stored once; the signature and acknowledgement contract are unchanged. | Closed |
| R010 | The filter and the cursor use the same (object, currency) tuple as the sort. | Totals and permissions are unchanged; the final and empty pages are explicit. | Closed |
| R011 | The day comes from the cursor's absolute next day; the moving limit can only restart coverage, never shift a day. | Pages within the limit are unchanged in content and watermarks. | Closed |

**Cross-feature effects.**
- Erasure, consent and bookings: erasure and expiry detach in every source, a withdrawal detaches across sources, and reads count only links whose consent is granted now. The three use the client privacy lock taken by booking intake, consent changes, erasure and lifecycle batches.
- Payments, CRM, ledger and conversion eligibility: a held Paymob refund is outside the calculation, so CRM verification (sales only), 014-B candidates and 008-A see one consistent ledger. Test-mode and undeclared-integration callbacks store no evidence at all. Declared CSV and manual rows remain unverified.
- Provider cursors and coverage: the Instagram watermarks come only from the final page, which now reports a gapless start. The spend and deal cursors encode their complete sort keys.

## Final verification

**Tested tree.** Head `a42fba5`. Its code is identical to `50d739f`, the last code commit (the second review hardening and the populated-upgrade test); `a42fba5` changes documentation only. The checks used:
- a fresh disposable PostgreSQL 18.6 database on `127.0.0.1:55433`, with the repository guard unchanged;
- Python 3.12.4 from the project `.venv`;
- Node 24.17.0 with the pinned Playwright 1.64.1, through a temporary junction to the existing local installation of the unchanged tracker dependencies.

**Batched run.** A first complete run at `b769a29` was stopped at about 35%, with no failure, to include the second review change. The next complete run at `a42fba5` was stopped by Claude Code at about 35%, with no failure, because the workstation ran low on memory. With the owner's approval, the suite then ran in five sequential batches against the same fresh database.

| Check | Result at `a42fba5` |
|---|---|
| Unit and contract suite (`-m "not integration"`) | **808 passed**, 0 skipped, in 15.57 s; includes the Instagram review regression and the OpenAPI snapshot comparison |
| Integration batch 1 (access, account closure, advertising migrations and spend, authentication, bookings and CRM) | **134 passed** in 213.47 s |
| Integration batch 2 (collection, connectors, conversion delivery) | **139 passed** in 248.33 s |
| Integration batch 3 (data policy, domains, links, Google, integration migrations, lifecycle, Paymob, PostgreSQL cycle) | **108 passed** in 135.70 s |
| Integration batch 4 (revenue, the 12 integration review regressions, ROAS, tenancy, browser journeys, verification codes, WhatsApp) | **120 passed** in 126.52 s, including the 3 browser journeys (Chromium and Firefox) |
| **Backend total** | **1,309 passed, 0 failed, 0 skipped**; the collection of 1,309 cases equals the sum of the batches; all 13 review regressions pass |
| Tracker unit suite (`npm test`) | **67 passed**, 0 skipped |
| Tracker Chromium and Firefox suite (`npm run test:browser`) | **44 passed**, 0 skipped |
| `ruff check` and `ruff format --check` | Passed; 222 files formatted |
| `pip check` | No broken requirements |
| OpenAPI contract | Regenerated from the application into a scratch file; byte-identical to `contracts/openapi.json` (121 operations, 99 paths) |
| Migrations | Fresh upgrade in every batch. A populated predecessor database at `0019` upgrades through the amended `0021` and `0023` to `0025` with its data intact (`test_amended_migrations_upgrade_a_populated_predecessor_database`). Every downgrade refuses populated state, and the empty cycle passes. The runtime and lifecycle grant cases pass. |
| `git diff --check db750d1 HEAD`, control characters, link targets | Clean; 271 local Markdown link targets in the 25 changed documents resolve |
| Secret scan of the full diff from `db750d1` | No secret pattern. The only matches are four non-secret identifiers from the owner's ignored `.env`: the local host, the database and role names, and the local API docs URL. No ignored environment, key or `local-data` file is tracked. |

The backend total grows from the review's 1,243 existing cases to 1,309: the 13 review regressions plus the adjacent cases recorded above.

**A3: ledger read scaling (bounded measurement).** Synthetic in-memory records, half sales and half partial refunds with their sale's signed order, timed on this workstation. These are observations, not a benchmark or a service objective.

| Records | D-070 pre-pass (`unbound_refunds`) | 007-A `calculate()` | `ledger_feed()` journal |
|---|---|---|---|
| 100 | 0.0329 s (first call, warm-up included) | 0.091 s | 3.637 s |
| 500 | 0.0020 s | 3.984 s | not measured |
| 1,000 | 0.0037 s | 17.464 s | not measured |

The journal recalculates every receipt prefix, so it was timed at 100 records only; a first attempt at 500 did not finish within 10 minutes and was stopped. The pre-pass that R001 added is linear and costs milliseconds. The calculation remains super-linear, matching the review's observation (0.096 s, 2.383 s and 15.249 s). The revenue read and the CRM deal read call it once per request, and the journal is computed only when a consumer asks for it. The constraint remains a production blocker for large clients. The next decision is the 007-B design review (persisted postings or an incremental calculation) together with realistic load figures (Q-004, Q-011). No service objective is set here.

**Note without a change of behavior.** `_live_integrations` in `app/services/payments.py` checked element types only after building a set. A mixed-type list could therefore raise `TypeError` instead of the validation error. The route's strict Pydantic validation rejects such a list first, so no request reached it. The check now runs before the set is built (defense in depth, covered by a unit case), in the same final commit as the populated-upgrade migration test.
