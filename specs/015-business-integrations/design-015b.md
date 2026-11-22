# 015 design, second round: bookings, CRM stage changes and WhatsApp referrals

Prepared: 2026-11-21 on `codex/spec-015-business-integrations`. Authority: D-068 (E1-E13 of the [second-round entry review](entry-review-round2.md) as recommended). Sources: entry review section 2 (W-1 to W-8). No dependency, no frontend change, no provider call. Migrations `0023` to `0025` run only on the disposable PostgreSQL service. Slices: **015-D** (integration sources, Cal.com bookings, the signed webhook and CRM deals; AC2 and AC3; migrations `0023` and `0024`) and **015-E** (WhatsApp referrals; AC4; migration `0025`).

## 1. Parameters from the sources

| Source | Parameter |
|---|---|
| W-1 | Cal.com: `x-cal-signature-256` is read as lowercase hexadecimal HMAC-SHA256 of the raw body under the client's secret (an optional `sha256=` prefix is accepted); unverified until a live check. |
| W-2, W-3 | Triggers mapped: `BOOKING_CREATED` (created), `BOOKING_REQUESTED` (requested), `BOOKING_RESCHEDULED` (rescheduled, with `rescheduleUid`), `BOOKING_CANCELLED`, `BOOKING_REJECTED`, `MEETING_ENDED` (completed, flat payload); every other trigger is `ignored`. The occurrence time is the envelope's `createdAt`. |
| W-4 | The subject token travels in the hidden booking field `ts_subject` (from `responses`) and must match the 004 format `sbj_` and 43 characters. |
| W-6 | WhatsApp: `X-Hub-Signature-256: sha256=<hex>` under the Meta app secret; the handshake returns `hub.challenge` only for `hub.mode=subscribe` and the verify token; the route bound is 3 MiB. |
| W-7 | WhatsApp referral: `source_type` (`ad`, `post`, any other value kept as `other`), `source_id` (digits) and the presence of `ctwa_clid`; the message key is SHA-256 of `messages[].id`. |

## 2. Integration sources (015-D)

**Tables (`0023_integration_bookings`).** `integration_sources` (kind `cal_com` or `signed_webhook`, name, status, `isk_` public key, creator, times), `integration_source_secrets` (sealed versions, kind `integration_signing`, 24-hour overlap), `integration_deliveries` (source, SHA-256 of the body unique per source, receipt time, outcome `applied`, `duplicate`, `ignored` or `invalid`, closed reason), `bookings` and `booking_events` (section 3). Audit actions `integration.created`, `integration.updated`, `integration.secret_replaced`, resource `integration_source`.

**Routes.**

| Route | Permission | Answer |
|---|---|---|
| `POST .../integration-sources` `{kind, name, secret?}` | Owner or Admin; audited | 201, the source and, for a signed webhook source, its issued secret once |
| `GET .../integration-sources` | Owner or Admin | The client's sources |
| `PUT .../integration-sources/{id}/secret` `{secret?}` | Owner or Admin; audited | A Cal.com source takes the client's new secret; a signed webhook source returns a new issued one |
| `PATCH .../integration-sources/{id}` `{name?, status?}` | Owner or Admin; audited | The source; re-activation needs the gate |
| `POST /integrations/cal-com/{key}` | Signature | 200 `received` |
| `POST /integrations/webhook/{key}` | 004 signature (`X-Tracking-Signature: t=,v1=`, five-minute window) | 200 `received` |

Callback steps: the gate (503 `integration_unavailable`), the per-peer and per-key rates, the keyring check (503 for every key), the source of that kind (401 `invalid_signature` for unknown, disabled, malformed or other-kind keys), the signature over the bounded body (64 KiB), the JSON object (a deeply nested body is unverifiable), then the intake under the client's 004 privacy lock. A delivery whose body digest was already recorded for the source is a `duplicate` and changes nothing.

**Gates (E11).** `TRACKING_INTEGRATIONS_CALCOM_ENABLED` and the `calcom.webhooks` rule (current from 2026-11-21, review 2027-11-21); `TRACKING_INTEGRATIONS_WEBHOOK_ENABLED` for the project's own contract, which has no provider terms.

## 3. Bookings (AC2)

A booking is one **chain** of provider booking IDs. Each delivery adds one minimal event (`booking_events`: kind, ID, previous ID of a reschedule, event type, occurrence time, schedule; unique per booking, kind, ID and time). The state is derived from all events of the chain:
- the current ID is the end of the reschedule chain;
- the status is that of the latest event about the current ID (ties ordered requested, created, rescheduled, rejected, cancelled, completed): `requested`, `scheduled`, `cancelled`, `rejected` or `completed`;
- a cancellation of an ID that was rescheduled away is ignored;
- the reschedule count is the number of distinct rescheduled IDs.

Every delivery order of the same events therefore gives the same booking (T-52). **Correction R006 (D-070):** chains were looked up by client and provider kind, so every signed webhook source of a client shared one namespace of booking IDs, and two tools' `booking-1` became one booking. `bookings` and `booking_events` now carry `source_id` (migration `0023` amended in place), and chain lookup, extension and merging use the delivering source only (indexes on `source_id` with `ref` and with `previous_ref`). When a later event connects two chains (for example a cancellation received before its creation, then the reschedule), the events of the later chains move into the earliest, which is marked `merged` and never shown. A booking never writes revenue evidence and is never a sale (E3). The read `GET .../bookings` (`client:read`) gives totals by status, the linked count and the newest 500 bookings.

**Lead links (E4).** When an event carries a well-formed subject token and the booking is not linked, the client's collection subject with that token is looked up under the 004 privacy lock. The booking is linked (`subject_id`, `linked_at`) only while that subject's `attribution` consent is granted; otherwise the delivery records `subject_unknown` or `consent_missing`. **Correction R003:** consent was checked only when the link was created, so a withdrawal left the booking linked. Now `record_consent`, under the same lock, detaches the subject's bookings when attribution is withdrawn or denied, or granted after a lapse. `bookings_view` counts a stored link only while the subject's latest attribution record is an unexpired grant (`granted_subjects`, the 003 evaluation order). A chain merge carries a link only while it is effective. The token itself is never stored. Erasing the subject clears the link. **Correction R002 (D-070):** the foreign key's `ON DELETE SET NULL` alone left `linked_at` set and violated `ck_bookings_valid_link`, rolling back the erasure; `erase_subject` now clears `subject_id` and `linked_at` together under the privacy lock before deleting the subject (target outcome `booking_links`), and the lifecycle runner's `booking_links` target does the same, as `tracking_lifecycle` with `UPDATE (subject_id, linked_at)` only, before deleting an expiring subject.

**Signed webhook contract for bookings.** `{"type": "booking.<created|requested|rescheduled|cancelled|rejected|completed>", "id", "occurred_at", "booking": {"id", "previous_id"?, "event_type"?, "start_at"?, "end_at"?, "subject_token"?}}`; the same chain rules apply, with provider `signed_webhook`.

## 4. CRM stage changes (AC3)

**Tables (`0024_crm_deals`).** `crm_stage_rules` (pipeline, stage, outcome `won` or `lost`, status, creator, times; unique per client, pipeline and stage) and `crm_deals` (source, deal ID, pipeline, stage, previous stage, stage time, optional amount and currency, optional payment reference, times). Audit actions `crm_rule.created` and `crm_rule.updated`, resource `crm_rule`.

**Contract.** `{"type": "deal.stage_changed", "id", "occurred_at", "deal": {"id", "pipeline", "stage", "previous_stage"?, "amount"?, "currency"?, "payment_reference"?}}`. Text values have 1-128 printable characters and are refused (`invalid_deal`) when they contain an email address, an international phone number or a card number. The latest change by occurrence time wins (T-58). **Correction R007 (D-070):** an older change was discarded entirely, so a payment reference it supplied survived only one delivery order. A change is now a partial update. The stage, the amount pair and the payment reference each keep the value of the latest change that supplied them, with ties broken by the value. `amount_at` and `payment_reference_at` hold their occurrence times (migration `0024` amended in place).

**Status (E6).** Computed on each read: no active rule for the deal's pipeline and stage is `open`; a lost rule is `lost`; a won rule is `won_verified` only when the payment reference equals the operation ID of a posted sale in the client's verified ledger, otherwise `won_unverified`. A stage change never writes evidence. `GET .../crm/deals` needs `client:read`; `?include_amounts=true` needs `finance:read` and adds the amount, the currency and the linked sale. **Correction R008:** the totals were computed over the newest 500 deals only. They are now aggregated in SQL over every deal of the client, with the verified sale set from the ledger as an array parameter. The rows are a keyset page ordered by (`first_received_at` descending, `id` descending), with `limit` (1-500), `after` and the response fields `has_more` and `next_after`.

## 5. WhatsApp referrals (015-E, AC4)

**Tables (`0025_whatsapp`).** `whatsapp_numbers` (phone number ID unique across clients, name, status, creator, times) and `whatsapp_messages` (number, SHA-256 of the message ID, message time, receipt time, `has_referral`, `source_type`, `source_id`, `click_id_present`). Audit actions `whatsapp_number.created` and `whatsapp_number.updated`, resource `whatsapp_number`.

**Routes.** `POST`, `GET` and `PATCH .../whatsapp-numbers` (Owner or Admin, audited); `GET` and `POST /integrations/whatsapp/webhook` (handshake and notifications); `GET .../whatsapp/referrals?since&until` (`client:read`, UTC days, at most 92): the total, the unknown count and the counts per source type and ad ID with the click-ID count.

**Intake.** The gate (`TRACKING_WHATSAPP_ENABLED`, the `whatsapp.cloud_api` rule), the per-peer rate, the signature, then every inbound message of a registered, active number of an active client is stored once with its referral only; messages of other numbers and status notifications store nothing. Every verified notification answers 200. No conversation is correlated with a person (E8).

**Correction R004 (D-070).** Registration activated a number at once and the phone number ID was unique across clients, so any agency that knew another business's ID could capture its signed notifications and block the real owner. `whatsapp_numbers` is now a table of claims (migration `0025` amended in place). The states are `pending` (the registration default, routes nothing), `active` and `disabled` (verified, with `verified_at`) and `revoked`. A partial unique index allows one verified binding per number, and another allows one unrevoked claim per client and number. The platform operator verifies or revokes a claim with `python -m app.whatsapp_binding` (`verify_claim`, `revoke_claim`) after an out-of-band check in Meta Business Manager. Agencies may switch only a verified binding between `active` and `disabled`.

## 6. Data policy and lifecycle

Classes `integration.source`, `integration.delivery`, `booking.record`, `crm.rule`, `crm.deal`, `whatsapp.number`, `whatsapp.referral`; `bookings.subject_id` is `collection.subject`. `python -m app.lifecycle` deletes, as `tracking_lifecycle`: integration deliveries 30 days after receipt, retired integration secrets, bookings (with their events) and CRM deals 395 days after their last update, and WhatsApp messages 395 days after receipt. Sources, rules and numbers stay until workspace deletion (017).

## 7. Tests

| Case | Test |
|---|---|
| T-50 (M) | `tests/integration/test_bookings_crm.py::test_signed_calcom_callback_and_refusals` |
| T-51, T-52 (M) | `test_bookings_crm.py::test_one_booking_through_reschedule_and_cancellation`, `::test_every_order_gives_the_same_booking_and_duplicates_count_once`; `tests/test_integrations_contract.py` |
| T-53 (M) | `test_bookings_crm.py::test_lead_links_need_identifier_evidence_and_consent` |
| T-54 | `test_bookings_crm.py::test_no_personal_field_is_stored_logged_or_returned` |
| T-55 | `test_bookings_crm.py::test_signed_webhook_contract` |
| T-56 (M) | `test_bookings_crm.py::test_stage_changes_never_become_revenue_without_rule_and_evidence` |
| T-57 | `test_bookings_crm.py::test_rules_sources_and_amounts_permissions` |
| T-58 | `test_bookings_crm.py::test_out_of_order_stage_changes_keep_the_latest` |
| T-60 to T-64 (M) | `tests/integration/test_whatsapp.py`; `tests/test_whatsapp_contract.py` |
| T-70 (M) | `test_bookings_crm.py::test_gates_and_rules`, `test_whatsapp.py::test_gates_and_rules` |
| T-71 | `test_bookings_crm.py::test_body_bounds`, `test_whatsapp.py::test_body_bound` |
| T-72 | `test_bookings_crm.py::test_lifecycle_deletes_bookings_deals_deliveries_and_secrets`, `test_whatsapp.py::test_lifecycle_deletes_messages_after_13_months` |
| Migrations | `tests/integration/test_integration_migrations.py` |

Mutation checks M11 to M20 are listed in the [evidence](evidence.md).
