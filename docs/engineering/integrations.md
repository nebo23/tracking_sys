# Bookings, CRM stage changes and WhatsApp referrals (specification 015, second round)
Status: 015-D (integration sources, Cal.com bookings, the provider-neutral signed webhook and CRM deals) and 015-E (WhatsApp Cloud API referrals) are implemented under D-068 against synthetic senders and fixture tests. Every source type is off by default. No call to Cal.com, a CRM or Meta has been made, and no migration has run on the native `tracking_sys`. Live callbacks need an HTTPS-hosted API (020) and owner accounts, which remain separate decisions. Design: [design-015b.md](../../specs/015-business-integrations/design-015b.md); evidence: [evidence.md](../../specs/015-business-integrations/evidence.md). Payments are in the [payments guide](payments.md).

## Integration sources
Owners and Admins manage a client's integration sources; every change is audited (`integration.created`, `integration.updated`, `integration.secret_replaced`).

| Kind | Setting | Secret | Callback |
|---|---|---|---|
| `cal_com` | `TRACKING_INTEGRATIONS_CALCOM_ENABLED` and a current `calcom.webhooks` rule | The secret the client sets in Cal.com (16-256 printable characters), entered once and never returned | `POST /integrations/cal-com/isk_<43 characters>`, signed in `x-cal-signature-256` |
| `signed_webhook` | `TRACKING_INTEGRATIONS_WEBHOOK_ENABLED` | Issued by the platform (`whsec_...`) and returned once | `POST /integrations/webhook/isk_<43 characters>`, signed in `X-Tracking-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "t.body">` within five minutes |

Routes: `POST`, `GET .../integration-sources`, `PUT .../integration-sources/{id}/secret` (a Cal.com source takes `{"secret": ...}`; a signed webhook source sends `{}` and gets a new issued secret), `PATCH .../integration-sources/{id}` (`name`, `status`). A replaced secret stays valid for 24 hours. In Cal.com, the client adds a webhook with the API's HTTPS origin followed by the callback path, the triggers Booking Created, Requested, Rescheduled, Cancelled, Rejected and Meeting Ended, and the same secret.

Every callback answers `200 {"status": "received"}` once verified; an invalid signature, an unknown, disabled, malformed or other-kind key all answer `401 invalid_signature`; with the kind off, `503 integration_unavailable`; without the token keyring, `503` for every key. Bodies are limited to 64 KiB. Each verified delivery leaves one row in `integration_deliveries` (body digest, receipt time, outcome `applied`, `duplicate`, `ignored` or `invalid`, reason); a repeated delivery changes nothing.

## Bookings
A booking is a chain of provider booking IDs: a reschedule adds the new ID, a cancellation of the current ID cancels the booking, and a cancellation of an ID that was rescheduled away is ignored. The status (`requested`, `scheduled`, `cancelled`, `rejected`, `completed`) comes from the latest event about the current ID, so the order of deliveries never changes the result. A booking is never revenue and never a sale. Nothing personal is stored: no attendee, email, phone, answer, note or meeting link.

`GET /agencies/{a}/clients/{c}/bookings` (`client:read`) returns the totals by status, the linked count and the newest 500 bookings.

**Lead links.** To link a booking to a visitor, the booking page carries the visitor's 004 subject token (`sbj_...`) in a hidden booking field named `ts_subject` (the signed webhook contract uses `booking.subject_token`). The booking is linked only while that subject's `attribution` consent is granted; otherwise the delivery records `subject_unknown` or `consent_missing`. The token is never stored, and erasing the subject removes the link. Person-level leads wait for 006.

**Signed webhook bookings.** `{"type": "booking.created" | "booking.requested" | "booking.rescheduled" | "booking.cancelled" | "booking.rejected" | "booking.completed", "id": "<event id>", "occurred_at": "<ISO 8601 with offset>", "booking": {"id", "previous_id" (reschedules), "event_type", "start_at", "end_at", "subject_token"}}`. Use it for booking tools other than Cal.com, through an automation tool that can sign requests.

## CRM stage changes
A CRM or automation tool sends `{"type": "deal.stage_changed", "id", "occurred_at", "deal": {"id", "pipeline", "stage", "previous_stage", "amount", "currency", "payment_reference"}}` to a signed webhook source. Text values have 1-128 printable characters; an email address, an international phone number or a card number refuses the delivery (`invalid_deal`). Amounts are decimal strings in major units of an allow-listed currency. The latest change by occurrence time is kept.

A stage change never becomes revenue. Owners and Admins approve won and lost stages (`POST`, `GET`, `PATCH .../crm/stage-rules`, `{"pipeline", "stage", "outcome": "won" | "lost"}`, audited `crm_rule.created` and `crm_rule.updated`). `GET .../crm/deals` (`client:read`) shows each deal as `open` (no rule), `lost`, `won_unverified`, or `won_verified` when its `payment_reference` equals the operation ID of a posted sale in the client's verified revenue (for a Paymob sale, the Paymob transaction ID). `?include_amounts=true` needs `finance:read` and adds the amount, the currency and the linked sale.

## WhatsApp referrals
| Setting | Meaning |
|---|---|
| `TRACKING_WHATSAPP_ENABLED` | Off by default; usable only while the `whatsapp.cloud_api` rule is current |
| `TRACKING_WHATSAPP_APP_SECRET` | The Meta app secret that signs notifications (16-256 characters, ignored `.env` only) |
| `TRACKING_WHATSAPP_VERIFY_TOKEN` | The token of the endpoint handshake (16-256 characters, ignored `.env` only) |

In the Meta app, the webhook URL is the API's HTTPS origin followed by `/integrations/whatsapp/webhook`, with the verify token, subscribed to the `messages` field. `GET` answers the handshake only for `hub.mode=subscribe` and the verify token. `POST` verifies `X-Hub-Signature-256` (401 otherwise) and accepts bodies up to 3 MiB.

Owners and Admins register each client's WhatsApp Business phone number ID (`POST`, `GET`, `PATCH .../whatsapp-numbers`, audited). For every inbound message of a registered, active number, only the Click-to-WhatsApp referral is stored: the source type (`ad`, `post` or `other`), the ad ID and whether a click ID was present. A message without a referral is recorded as unknown. Phone numbers, names, sender IDs, message text, ad copy, media URLs and click IDs are never stored or logged, and no conversation is correlated with a person. Messages of unregistered numbers and status notifications store nothing; Meta's retries are deduplicated.

`GET .../whatsapp/referrals?since=YYYY-MM-DD&until=YYYY-MM-DD` (`client:read`, UTC days, at most 92, default the last 30) returns the total, the unknown count and the counts per source type and ad ID.

## Lifecycle
`python -m app.lifecycle` deletes, as `tracking_lifecycle`: integration deliveries 30 days after receipt (`TRACKING_INTEGRATION_DELIVERY_RETENTION_DAYS`), retired integration secrets, bookings with their events 395 days after their last update (`TRACKING_BOOKING_RETENTION_DAYS`), CRM deals 395 days after their last update (`TRACKING_DEAL_RETENTION_DAYS`) and WhatsApp messages 395 days after receipt (`TRACKING_WHATSAPP_MESSAGE_RETENTION_DAYS`). Each period may be shortened, not extended. Sources, rules and numbers stay until workspace deletion (017).

## Before any live use
- An HTTPS-hosted API (020) and owner Cal.com and WhatsApp accounts for live checks, separately approved. The Cal.com check confirms the signature encoding, the hidden-field prefill and whether an old ID is cancelled at a reschedule.
- Native `tracking_sys` migration of `0023` to `0025`, and deployment, which remain separate owner decisions.
