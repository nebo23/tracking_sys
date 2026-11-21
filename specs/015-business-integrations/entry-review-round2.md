# Specification 015 entry review, second round: bookings, CRM and WhatsApp

Prepared: 2026-11-21 on `codex/spec-015-business-integrations` after the first round (PR 13, head `60a31cd`). Authority: D-068, which approves E1-E13 below as recommended. Status: **approved**. This round completes the remaining acceptance criteria of [Spec 015](spec.md) within the same pull request, against synthetic senders and fixture tests only. No provider is called and no provider account is created or changed.

## 1. Scope

- **AC2.** Booking creation, cancellation and rescheduling do not count as multiple sales; links to leads require identifier evidence.
- **AC3.** A CRM stage transition does not become a paid transaction without an approved rule and supporting evidence.
- **AC4.** WhatsApp and ManyChat referral metadata is used when available; missing data remains unknown, and comment or DM correlation requires a valid grant.

The specification asks for one integration per approved workflow with a defined fallback. AC1 and AC5 were met in the first round ([evidence](evidence.md)).

**Dependency gap.** Spec 006 (people, leads and journeys) is designed but not implemented. No person or lead table exists, so a "link to a lead" in this round is a link to a pseudonymous 004 collection subject, and only with identifier evidence (E4). Person-level correlation stays with 006.

## 2. Sources read on 2026-11-21

Read by the implementing model, partly through the page reader. Nothing was sent to any provider.

| Page | Result |
|---|---|
| [Cal.com webhooks](https://cal.com/docs/developing/guides/automation/webhooks) and the [Cal.com documentation index](https://cal.com/llms.txt) | Read |
| [Cal.com booking fields](https://cal.com/docs/atoms/guides/booking-fields.md) and [embed events](https://cal.com/help/embedding/embed-events) | Read |
| [Calendly: receive data with webhook subscriptions](https://developer.calendly.com/docs/api-guides/receive-data-from-scheduled-events-in-real-time-with-webhook-subscriptions.md) and [webhook signatures](https://developer.calendly.com/api-docs/overview/webhooks/webhook-signatures.md) | Read |
| WhatsApp webhooks: [overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview?locale=en_US), [create an endpoint](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint?locale=en_US), the [messages reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages?locale=en_US) and the [text message reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text?locale=en_US) | Read |
| [Graph API webhooks: getting started](https://developers.facebook.com/docs/graph-api/webhooks/getting-started?locale=en_US) | Read |
| ManyChat help center and developer pages | Not read: HTTP 403 and 404 |

| ID | Finding | Consequence |
|---|---|---|
| W-1 | Cal.com webhooks are configured in the Cal.com dashboard with an optional secret that "is write-only". The `x-cal-signature-256` header carries an HMAC-SHA256 of the payload under that secret; the hexadecimal encoding is not stated. Payloads are versioned in `x-cal-webhook-version` (2021-10-20 and 2026-07-27). | E2: the client supplies its secret, sealed like the Paymob secret. The signature is read as lowercase hexadecimal over the raw body (unverified until a live check). |
| W-2 | The `BOOKING_RESCHEDULED` example carries a new `uid` and `rescheduleUid` (the previous booking). Whether `BOOKING_CANCELLED` also fires for the original is not stated. Booking triggers include created, requested, rejected, rescheduled and cancelled; `MEETING_ENDED` uses a flat payload. | E3: one booking per chain of uids; a reschedule moves the chain; a cancellation of an earlier uid of a rescheduled chain is ignored. |
| W-3 | Retries, duplicates and ordering are documented only for registration triggers ("can retry and arrive more than once or out of order"). | E3: every delivery is deduplicated and the latest event per booking wins, whatever the order. |
| W-4 | No page documents passing `metadata[...]` or UTM parameters into a booking. Booking fields (`responses`) can be prefilled. | E4: the subject token travels in a hidden booking field named `ts_subject` (read from `responses`); the prefill path is unverified until a live check. |
| W-5 | Calendly webhook subscriptions are created through its API with a token, and deliveries carry `Calendly-Webhook-Signature: t=...,v1=...`. | E2: Calendly would need outbound calls; it is not chosen. |
| W-6 | WhatsApp notifications are signed in `X-Hub-Signature-256` (`sha256=` and an HMAC-SHA256 of the body under the app secret); the endpoint is verified with `hub.mode`, `hub.verify_token` and `hub.challenge`. Meta retries for up to 7 days, which "can result in duplicate webhook notifications". Payloads can be up to 3 MB, with up to 1,000 updates per batch. | E7: platform-level app secret and verify token; the route bound is 3 MiB; messages are deduplicated by a digest of their ID. |
| W-7 | A message carries `referral` "only ... if message sent via a Click to WhatsApp ad", with `source_url`, `source_id` (the ad ID), `source_type` (example `ad`), `body`, `headline`, `media_type`, media URLs, `ctwa_clid` (omitted for Status ad placements) and `welcome_message`. Messages also carry `from`, `from_user_id`, contacts with `wa_id`, `user_id` and profile names. | E8: only `source_type`, `source_id` and the presence of `ctwa_clid` are kept; every person field is discarded. |
| W-8 | ManyChat pages could not be read; no signing of its outgoing requests is documented in what was reachable. | E1: ManyChat is a follow-up. |

## 3. Decisions (D-068)

| ID | Decision | Approved recommendation |
|---|---|---|
| E1 | Scope | One integration per workflow for AC2 to AC4 on the same branch and PR 13. Stripe, Paymob reads and backfill, third-party form tools and ManyChat are follow-ups. |
| E2 | Booking provider | Cal.com, with signed webhooks and a secret the client sets. |
| E3 | Booking model | A booking is a booked-call conversion, never revenue. A reschedule moves the same booking, a cancellation cancels it, and nothing personal is stored. |
| E4 | Lead links | Only with identifier evidence: the pseudonymous 004 subject token in a hidden booking field, and only while that subject's attribution consent is granted. Otherwise the booking stays unlinked until 006. |
| E5 | CRM and other tools | A provider-neutral signed webhook source with the project's own documented contract for CRM stage changes and for booking tools other than Cal.com, usable from any CRM or automation tool. |
| E6 | Stage rules | A stage change never becomes revenue. An Owner or Admin approves won and lost stage rules, audited. A won deal is linked to a sale only when its payment reference matches a verified ledger sale of the same client; otherwise it stays won and unverified. |
| E7 | WhatsApp | WhatsApp Cloud API with signed webhooks, platform-level settings off by default, and per-client numbers registered by an Owner or Admin. |
| E8 | WhatsApp data | Only the Click-to-WhatsApp referral is stored (source type, ad ID, presence of a click ID). A message without a referral is unknown. No conversation is correlated with a person without a valid grant, which does not exist before 006. |
| E9 | Retention (development, provisional) | Bookings, deals and WhatsApp messages 13 months (395 days) after their last update; diagnostics 30 days. |
| E10 | Permissions | Owner and Admin management with audit events; reads with `client:read`; deal amounts with `finance:read`. |
| E11 | Gates | Each provider type is off by default and usable only while its provider rule is current. |
| E12 | Migrations | Additive `0023` to `0025` on disposable PostgreSQL only; no new dependency. |
| E13 | Mode | Synthetic senders and fixtures only; no live call and no provider account. |

## 4. Verification plan

(M) marks a case with a mutation check.

| Case | Expected |
|---|---|
| T-50 | A Cal.com callback signed with the client's secret is accepted; a missing or wrong signature, an unknown or disabled source and an unreadable body all answer 401 and store nothing (M). |
| T-51 | Creation, a reschedule and a cancellation of one booking leave one booking: rescheduled once, then cancelled; no ledger evidence is written (M). |
| T-52 | Every delivery order of created, rescheduled and cancelled gives the same final booking; repeated deliveries are counted once (M). |
| T-53 | A booking with a valid subject token and granted attribution consent is linked; without a token, with an unknown token, or without consent it stays unlinked; the token is never stored (M). |
| T-54 | No name, email, phone, answer, note, meeting link or token is stored, logged or returned. |
| T-55 | The signed webhook source accepts the documented contract for bookings and deal stage changes with the 004 signature and refuses everything else with 401. |
| T-56 | A stage change without an approved won rule leaves the deal open; with the rule and without a matching verified payment it is won and unverified; with a matching verified sale it is won and verified; no case writes ledger evidence (M). |
| T-57 | Stage rules and sources need an Owner or Admin, are audited and isolated per client; deal amounts need `finance:read`. |
| T-58 | Out-of-order stage changes keep the latest by occurrence time. |
| T-60 | A WhatsApp notification signed with the app secret is accepted; an invalid signature is refused; the verification handshake answers the challenge only with the verify token (M). |
| T-61 | A message with a referral stores its source type and ad ID; one without a referral is counted as unknown; status notifications store nothing (M). |
| T-62 | No phone number, name, sender ID, message text, headline, body, media URL or click ID is stored, logged or returned (M). |
| T-63 | A repeated notification stores each message once; an unregistered phone number ID stores nothing. |
| T-64 | Numbers need an Owner or Admin, are audited and isolated per client; the referral read needs `client:read`. |
| T-70 | With a setting off or a rule stale or overdue, the provider type cannot be used (M). |
| T-71 | Body bounds: 64 KiB for the Cal.com and signed webhook routes, 3 MiB for WhatsApp, 16 KiB elsewhere. |
| T-72 | The lifecycle runner deletes bookings, deals and WhatsApp messages 395 days after their last update and diagnostics after 30 days. |

## 5. Out of scope and follow-ups

Stripe, Paymob reads and backfill, third-party form tools, ManyChat, live checks with provider accounts and HTTPS hosting (020), person-level correlation (006), 007-B, native migration and deployment.
