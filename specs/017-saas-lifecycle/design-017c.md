# Spec 017-C design: subscription billing, prices and the trial

Prepared: 2026-11-28 under D-103. Revision: 1 (2026-11-28). Status: approved scope ([D1-D14](entry-review-017c.md#4-decisions-for-the-owner), D-103, without amendment), design of Phase 0. This note fixes the exact schema, transitions, event mapping, adapter calls, answers, error codes, grants and tests before any code. Section 5 of the [entry review](entry-review-017c.md) is its source. Section 2 records the provider facts V-1 to V-16 read on Paddle's and Stripe's official pages; no fact changes a decision, and section 2.3 lists the differences. Section 15 lists the routine details resolved here. No material new choice was found that needs the owner.

## 1. Inventory on the branch (P0)

### 1.1 Baseline

- **Branch.** `codex/spec-017c-saas-billing` was created from `origin/claude/keen-fermat-otlr9d` at `72552f0`; merged `main` at `04dc323` (PR 21) is an ancestor (`git merge-base --is-ancestor 04dc323 HEAD` succeeds).
- **`main`.** `origin/main` has not moved beyond `04dc323`, so nothing was merged into the branch. Pull request 17 (Spec 018) is still open, and `frontend/` holds only the placeholder README files, with no `package.json`, so the frontend checks of P5 do not apply.
- **Gate.** D-103 is recorded in `AGENTS.md` and `docs/planning/decisions.md`. It approves D1-D14 as recommended and names no amendment.
- **Decision numbers.** The highest number is D-103 on this branch; `main` ends at D-098, the open pull request 17 uses D-081 to D-087, and `codex/spec-018-workspace-screens` records D-099 to D-101. Its D-099 collides with the D-099 that this branch records for the 017-B merge; that branch is unchanged and the collision is reported, as the handoff asks. This work records no new decision.
- **Test database.** Windows reserves the TCP range 55365-55464 on this workstation (`netsh interface ipv4 show excludedportrange protocol=tcp`), which includes 55433. As the owner chose for 017-B on the same day, the disposable PostgreSQL 18 service of `backend/tests/README.md` runs on 127.0.0.1:56433, and the test runner patches the guard's port only for the duration of each run and restores the file byte for byte (SHA-256 compared). The committed guard always says 55433; the evidence records the deviation.

### 1.2 Schema at `0033_agency_offboarding`

The schema has 98 application tables (plus `alembic_version`); 83 carry `agency_id` or `client_id`. Migration `0034` adds 8 tables, 7 of them scoped (`billing_prices` is a platform catalog). The purge deletes 4 of the new scoped tables and keeps 3 as financial records (D10), so after `0034` the purge deletes 85 tables and keeps 5 (`agency_plan_assignments`, `agency_purges`, `agency_subscriptions`, `billing_payments`, `billing_adjustments`).

## 2. Provider facts (V-1 to V-16)

Every page below was read on 2026-11-28 on the official site named. Facts that a page did not state are marked "not stated" and are not relied on.

### 2.1 Record

| ID | Fact as read | Official addresses | Decision |
|---|---|---|---|
| V-1 | Paddle "works with software businesses anywhere in the world with the exception of the unsupported countries" it lists; Egypt is not on the help-center list or in the developer table of unsupported countries (AF, AN, AQ, BY, CD, CF, CS, CU, HT, IR, KP, LY, ML, MM, NI, RU, SD, SO, SS, SY, VE, YE, ZW). The list "is subject to change", and Paddle may request further information for risk and compliance before processing an order or releasing a payment. Common seats of a foreign company (GB, US, AE) are supported. | [Which countries are supported](https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle); [supported countries](https://developer.paddle.com/concepts/sell/supported-countries-locales) | D2 holds |
| V-2 | Pay-as-you-go: 5% + USD 0.50 per checkout transaction, no monthly fee; fraud protection, chargebacks and buyer support included. Payouts add no Paddle fee, but a conversion margin of up to 1.5% applies when the payout currency differs from the balance currency, and a mismatched SWIFT transfer has a USD/EUR/GBP 15 wire fee. No surcharge for subscriptions or international cards is listed. | [Pricing](https://www.paddle.com/pricing); [payout fees](https://www.paddle.com/help/manage/get-paid/is-there-a-fee-taken-for-payouts) | D2 holds |
| V-3 | Payouts by wire transfer or Payoneer, issued once a month (sent by the 15th), from a USD 100 minimum (adjustable up to USD 100,000; GBP 100 or EUR 100 for those balances); a smaller balance carries over. Payout currencies: AUD, GBP, CAD, CNY, CZK, DKK, EUR, HUF, PLN, ZAR, SEK, CHF and USD; balance currencies USD, EUR, GBP, AUD and CAD. | [When and how do I get paid](https://www.paddle.com/help/manage/get-paid/when-and-how-do-i-get-paid); [local currency payouts](https://www.paddle.com/help/manage/get-paid/can-i-be-paid-in-my-local-currency); [supported currencies](https://developer.paddle.com/concepts/sell/supported-currencies) | D2 holds |
| V-4 | `Paddle-Signature: ts=<unix seconds>;h1=<hex>`, parts separated by `;`. The signed string is the timestamp and the raw body joined with a colon (`ts:body`), HMAC-SHA256 keyed with the notification destination's secret key (example form `pdl_ntfset_...`). There is at least one `h1`; during a secret rotation, more than one may be sent. The raw body must not be transformed. The timestamp check is optional; Paddle's SDKs use a default tolerance of five seconds. | [Signature verification](https://developer.paddle.com/webhooks/signature-verification); [notification destinations](https://developer.paddle.com/webhooks/about/notification-destinations) | D7 holds (section 2.3) |
| V-5 | Answer `200` within five seconds; otherwise Paddle retries with exponential backoff: 3 attempts within about two minutes in sandbox, up to 60 attempts over about two days live. Delivery is at least once, and the order is not guaranteed. `event_id` (`evt_...`) is unique per event and is the deduplication key; `occurred_at` is the RFC 3339 time of the event, for out-of-order handling; `notification_id` (`ntf_...`) differs per delivery. | [Handle webhook delivery](https://developer.paddle.com/webhooks/respond-to-webhooks); [how webhooks work](https://developer.paddle.com/webhooks/about/how-webhooks-work); [overview](https://developer.paddle.com/webhooks/overview) | D7 holds |
| V-6 | Types: `subscription.{activated, canceled, created, imported, past_due, paused, resumed, trialing, updated}`, `transaction.{billed, canceled, completed, created, paid, past_due, payment_failed, ready, revised, updated}`, `adjustment.{created, updated}`. Payloads carry `event_id`, `event_type`, `occurred_at`, `notification_id` and `data`, the full entity. Only `subscription.created` carries `transaction_id`, the transaction that created the subscription. "If a transaction creates a new subscription, the custom data is copied to the new subscription." A checkout runs transaction.paid, then subscription.created and subscription.activated, then transaction.completed. Fields used: subscription `id`, `status` (active, canceled, past_due, paused, trialing), `customer_id`, `items[].price.id`, `current_billing_period.{starts_at, ends_at}`, `next_billed_at`, `scheduled_change.{action, effective_at}` (cancel, pause, resume), `canceled_at`, `currency_code`, `custom_data`; transaction `id`, `status` (draft, ready, billed, paid, completed, canceled, past_due), `origin`, `subscription_id`, `customer_id`, `currency_code`, `details.totals.{subtotal, tax, total}` (integer strings in the lowest denomination), `billed_at`, `invoice_number`, `custom_data`; adjustment `id`, `action` (credit, refund, chargeback, chargeback_reverse, chargeback_warning, chargeback_warning_reverse, credit_reverse), `status` (pending_approval, approved, rejected, reversed), `transaction_id`, `subscription_id`, `currency_code`, `totals.total`. Paddle's guidance: full access for trialing, active and past_due; revoke at canceled, keeping access until a scheduled cancellation takes effect. | [subscription.created](https://developer.paddle.com/webhooks/subscriptions/subscription-created); [subscription.updated](https://developer.paddle.com/webhooks/subscriptions/subscription-updated); [transaction.completed](https://developer.paddle.com/webhooks/transactions/transaction-completed); [adjustment.created](https://developer.paddle.com/webhooks/adjustments/adjustment-created); [custom data](https://developer.paddle.com/build/transactions/custom-data); [provision access](https://developer.paddle.com/build/subscriptions/provision-access-webhooks); [checkout scenario](https://developer.paddle.com/webhooks/simulator/subscription-created) | D6, D7 hold |
| V-7 | `POST /transactions` with `items[{price_id, quantity}]`, optional `customer_id`, `custom_data`, `collection_mode` (default `automatic`) and `currency_code`. A transaction without `customer_id` and `address_id` is created as `draft` ("typically the first stage of a checkout before customer details are captured"). Paddle.js opens a checkout with `transactionId`. Checkout URLs use the default payment link with `_ptxn`, or an approved domain; live domains must be approved, sandbox domains need no approval. | [Create a transaction](https://developer.paddle.com/api-reference/transactions/create-transaction); [pass a transaction to a checkout](https://developer.paddle.com/build/transactions/pass-transaction-checkout); [default payment link](https://developer.paddle.com/build/transactions/default-payment-link) | D6 holds |
| V-8 | `PATCH /subscriptions/{id}` with the complete `items` list and the required `proration_billing_mode` (`prorated_immediately`, `prorated_next_billing_period`, `full_immediately`, `full_next_billing_period`, `do_not_bill`); `on_payment_failure` `prevent_change` (default) or `apply_change`. `PATCH /subscriptions/{id}/preview` previews without applying and returns `immediate_transaction`, `next_transaction` and `update_summary`. A past_due subscription cannot be updated or previewed except to remove a scheduled change (`subscription_update_when_past_due`, 400); within 30 minutes of a renewal a subscription is locked (`subscription_locked_renewal`, 409, "Unable to update subscription within 30 minutes of renewal"); a subscription with a scheduled change takes no other change until it is resolved (`subscription_locked_pending_changes`, 400). At most 20 chargeable immediate updates per hour and 100 per day per subscription. | [Update a subscription](https://developer.paddle.com/api-reference/subscriptions/update-subscription); [preview an update](https://developer.paddle.com/api-reference/subscriptions/preview-subscription-update); [proration](https://developer.paddle.com/concepts/subscriptions/proration); [error codes](https://developer.paddle.com/errors/overview); [rate limits](https://developer.paddle.com/api-reference/about/rate-limiting) | D8 holds (section 2.3) |
| V-9 | `POST /subscriptions/{id}/cancel` with `effective_from` `next_billing_period` (default) or `immediately`; a scheduled cancellation is a `scheduled_change` with action `cancel`, and the status stays active until it takes effect. Paused subscriptions can only be canceled immediately; past_due subscriptions can be canceled; cancel and pause are refused within 30 minutes of the next billing date. Removing a scheduled change is `PATCH /subscriptions/{id}` with `scheduled_change: null`. `subscription.updated` covers scheduled changes being created or removed. "You can't reinstate a canceled subscription" (`subscription_is_canceled_action_invalid`). | [Cancel a subscription](https://developer.paddle.com/api-reference/subscriptions/cancel-subscription); [cancel subscriptions](https://developer.paddle.com/build/subscriptions/cancel-subscriptions); [subscription.updated](https://developer.paddle.com/webhooks/subscriptions/subscription-updated) | D9, D10 hold |
| V-10 | `GET /subscriptions/{id}/update-payment-method-transaction` returns a transaction to pass to a checkout: the most recent past_due transaction when the subscription is past_due, otherwise a new zero-amount transaction; automatic collection only. | [Update payment method transaction](https://developer.paddle.com/api-reference/subscriptions/get-subscription-update-payment-method-transaction) | D9 holds |
| V-11 | `GET /transactions/{id}/invoice` returns `data.url`, "not a permanent link. It expires after an hour"; available for completed transactions (billed or completed for manual collection), never for zero-value transactions. | [Get an invoice PDF](https://developer.paddle.com/api-reference/transactions/get-transaction-invoice) | D11 holds |
| V-12 | Base addresses `https://sandbox-api.paddle.com` and `https://api.paddle.com`; separate keys per environment. `Authorization: Bearer <key>`; keys are 69 characters, `^pdl_(live|sdbx)_apikey_[a-z\d]{26}_[a-zA-Z\d]{22}_[a-zA-Z\d]{3}$`, and expire after 90 days by default (at most one year). `Paddle-Version: 1` is the current version. Errors are `{"error": {"type", "code", "detail", "documentation_url"}, "meta": {"request_id"}}`. 240 requests per minute per IP; `too_many_requests` (429) carries `Retry-After`. Client-side tokens for Paddle.js match `^(test|live)_[a-zA-Z0-9]{27}$` (`test_` for sandbox). | [API quickstart](https://developer.paddle.com/api-reference/about); [authentication](https://developer.paddle.com/api-reference/about/authentication); [versioning](https://developer.paddle.com/api-reference/about/versioning); [errors](https://developer.paddle.com/api-reference/about/errors); [rate limits](https://developer.paddle.com/api-reference/about/rate-limiting); [client-side tokens](https://developer.paddle.com/paddlejs/client-side-tokens) | D14 holds |
| V-13 | Since 2025-01-09 failed renewals of automatically collected subscriptions are retried for every Paddle Billing account, "up to seven times over a 30-day window before they're canceled"; without Paddle Retain the subscription "is automatically canceled after 30 days". With Retain, the seller chooses pause or cancel after the last attempt; the default of that choice is not stated, and no "stay past due" option was found. Retries run on live accounts only: "No payment retries occur on sandbox accounts." | [Payment recovery and dunning](https://developer.paddle.com/build/lifecycle/subscription-renewal-dunning); [default payment retries](https://developer.paddle.com/changelog/2025/default-dunning-payment-recovery) | D9 holds (section 2.3) |
| V-14 | A live domain must show a product description, pricing (a screenshot is acceptable before launch), the key features, Terms and Conditions, a Refund Policy and a Privacy Policy in its navigation, the company or brand name in the terms, and be live over HTTPS. Most submissions are approved automatically; a manual review takes about 5-7 business days. The sandbox needs no domain approval. A seller may sell only through approved domains. Software, including B2B SaaS, is accepted; "human services that are not related to a software offering" are not. | [Domain verification](https://www.paddle.com/help/start/account-verification/what-is-domain-verification); [what you cannot sell](https://www.paddle.com/help/start/intro-to-paddle/what-am-i-not-allowed-to-sell-on-paddle) | Owner inputs (section 8 of the entry review) |
| V-15 | Buyers can pay with cards (all countries), PayPal, Apple Pay and Google Pay (all countries except IN and TR), wire transfer for USD 100 or more, and local methods elsewhere; no page names Egypt-specific methods. Egypt's row is "EG, Egypt, USD, Inclusive": USD is the currency Paddle uses for automatic price conversion there. Paddle localizes prices by default (an override, else an automatic conversion into the local currency, else the base price), and the seller can turn automatic conversion off in the dashboard or through the API; how a transaction-level `currency_code` interacts with localization is not stated. | [Payment methods](https://www.paddle.com/help/start/intro-to-paddle/which-payment-methods-do-you-support); [payment methods overview](https://developer.paddle.com/concepts/payment-methods/overview); [supported countries](https://developer.paddle.com/concepts/sell/supported-countries-locales); [localized pricing](https://developer.paddle.com/build/products/offer-localized-pricing); [supported currencies](https://developer.paddle.com/concepts/sell/supported-currencies) | D2, D3 hold (section 2.3) |
| V-16 | Egypt is not on Stripe's list of countries where a business can open an account. Stripe Managed Payments (merchant of record) arrived with API version 2026-04-22.dahlia, for businesses in 33 locations (CA, US, 27 European countries, AU, HK, JP, SG), not Egypt, at 3.5% per transaction on top of the payment fees. | [Stripe global](https://stripe.com/global); [Managed Payments eligibility](https://docs.stripe.com/payments/managed-payments/eligibility); [changelog 2026-04-22](https://docs.stripe.com/changelog/dahlia/2026-04-22/managed-payments); [Stripe pricing](https://stripe.com/pricing) | D2 holds |

### 2.2 Facts the code depends on

- **Signature (V-4).** Every `h1` value of the header is compared in constant time with the HMAC-SHA256 of `ts + ":" + raw body` under the webhook secret's UTF-8 bytes; a match of any `h1` is valid, which also covers a rotation.
- **Binding (V-6).** A subscription is bound to an agency through the checkout's transaction ID, which `subscription.created` carries; `custom_data`, which Paddle copies from the checkout transaction to the subscription, is checked against the checkout. Earlier events of the subscription are kept unmatched with their fields and replayed at binding (section 5.2).
- **Locks (V-8, V-9).** A plan change and a cancellation are refused within 30 minutes of `next_billed_at`; a plan change is also refused while a scheduled change exists, and a paused subscription is never canceled at the period end.
- **Currency (V-7, V-15).** The checkout transaction is created with `currency_code: "USD"`, and every payment stores the currency Paddle reports.

### 2.3 Differences from the entry review

No difference changes a decision. Each is resolved in this note:

1. **Timestamp tolerance (V-4).** Paddle's SDKs default to five seconds, and the check is optional. D7's 300 seconds stays: a delivery replayed within the window carries an `event_id` that is already stored and changes nothing, and a five-second window would refuse genuine deliveries under ordinary clock skew.
2. **The 30-minute lock (V-8).** The entry review placed it under subscription changes; the official pages place it on updates (`subscription_locked_renewal`) and on cancellation and pause. D8's refusal stays, and the same window is applied to the Owner's cancellation (D9) and retried by the closure actions (D10).
3. **A scheduled change blocks other changes (V-8).** Not in the entry review. A plan change is refused (`change_not_allowed`) while a cancellation is scheduled; the Owner undoes the cancellation first.
4. **Recovery settings (V-13).** "Stay past due" was not found as an option, and the default of Retain's pause-or-cancel choice is not stated. D9 configures cancellation, which is also the behavior without Retain. Retries run only on live accounts, so the owner's sandbox check cannot exercise them (section 16).
5. **Localized prices (V-15).** Paddle may convert a USD price into a buyer's local currency unless the seller turns automatic conversion off. The adapter sends `currency_code: "USD"`, payments record the reported currency, and turning automatic conversion off for a USD-only checkout is added to the owner's inputs before live use (section 16).
6. **Key lifetime (V-12).** API keys expire after 90 days by default, so key rotation becomes an operations task of 020 (section 16).
7. **Fees (V-2).** The fee is confirmed on Paddle's own pricing page, and the payout conversion margin and wire fee were found; neither changes D2.

## 3. Migration `0034_saas_billing` (after `0033_agency_offboarding`)

All times are `timestamp with time zone`. Provider IDs are checked against Paddle's documented form `<prefix>_[a-z0-9]{26}`. Named constraints follow the metadata naming convention (`ck_<table>_<name>`, `pk_<table>`, `fk_<table>_<column>_<referred>`).

### 3.1 `billing_prices` (platform catalog, D3)

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | uuid | no | primary key |
| `plan_id` | uuid | no | references `saas_plans.id` |
| `provider` | varchar(16) | no | `provider = 'paddle'` |
| `provider_price_id` | varchar(32) | no | `~ '^pri_[a-z0-9]{26}$'`; unique with `provider` (`uq_billing_prices_provider_price`) |
| `currency` | varchar(3) | no | `currency = 'USD'` |
| `amount_cents` | bigint | no | `BETWEEN 1 AND 100000000` |
| `billing_interval` | varchar(8) | no | `IN ('month', 'year')` |
| `offered` | boolean | no | default true |
| `registered_at` | timestamptz | no | default `now()` |
| `retired_at` | timestamptz | yes | `offered = (retired_at IS NULL)` and `retired_at IS NULL OR retired_at >= registered_at` |

Indexes: `uq_billing_prices_offered` unique on (`plan_id`, `billing_interval`) where `offered`, so a plan has at most one offered monthly and one offered annual price; `ix_billing_prices_plan_id`. A price is immutable apart from `offered` and `retired_at`, and retirement is final.

### 3.2 `agency_billing` (the standing, one row per agency, D5)

| Column | Type | Null | Rule |
|---|---|---|---|
| `agency_id` | uuid | no | primary key; references `agencies.id` |
| `standing` | varchar(16) | no | `IN ('complimentary', 'trialing', 'subscribed', 'past_due', 'hold')` |
| `reason` | varchar(24) | no | matches the standing (below) |
| `trial_ends_at` | timestamptz | yes | required while trialing; kept afterwards as history |
| `trial_reminded_at` | timestamptz | yes | only with `trial_ends_at` |
| `grant_ends_at` | timestamptz | yes | only for `complimentary` with reason `operator_grant`; null means no end |
| `hold_started_at` | timestamptz | yes | set exactly while on hold |
| `hold_notified_at` | timestamptz | yes | only with `hold_started_at` |
| `provider_customer_id` | varchar(32) | yes | `~ '^ctm_[a-z0-9]{26}$'`; not unique (one Paddle customer may pay for two agencies) |
| `version` | integer | no | default 1, `>= 1`; incremented by every transition |
| `created_at`, `updated_at` | timestamptz | no | default `now()` |

Reasons: `complimentary` (`migration`, `billing_disabled`, `operator_grant`), `trialing` (`new_agency`), `subscribed` (`subscription_active`, `payment_recovered`), `past_due` (`payment_failed`), `hold` (`trial_ended`, `grant_ended`, `subscription_canceled`, `subscription_paused`). Partial indexes for the worker: `ix_agency_billing_trial` on `trial_ends_at` where trialing, `ix_agency_billing_grant` on `grant_ends_at` where it is not null, and `ix_agency_billing_hold` on `hold_started_at` where on hold.

### 3.3 `agency_subscriptions` (kept after the purge, D10)

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | uuid | no | primary key; unique (`agency_id`, `id`) for scoped references |
| `agency_id` | uuid | no | references `agencies.id` |
| `provider` | varchar(16) | no | `'paddle'` |
| `provider_subscription_id` | varchar(32) | no | `^sub_...`; unique with `provider` |
| `provider_transaction_id` | varchar(32) | yes | `^txn_...`: the transaction that created it, from `subscription.created` |
| `price_id` | uuid | yes | references `billing_prices.id`; null when Paddle reports a price that is not registered |
| `provider_price_id` | varchar(32) | yes | `^pri_...` as reported |
| `status` | varchar(16) | no | `IN ('trialing', 'active', 'past_due', 'paused', 'canceled')` |
| `current_period_starts_at`, `current_period_ends_at` | timestamptz | yes | ends at or after the start |
| `next_billed_at` | timestamptz | yes | |
| `scheduled_action` | varchar(8) | yes | `IN ('cancel', 'pause', 'resume')`; null together with `scheduled_at` |
| `scheduled_at` | timestamptz | yes | the change's `effective_at` |
| `cancel_origin` | varchar(16) | yes | `IN ('owner', 'closure', 'provider')`: who scheduled the cancellation |
| `canceled_at` | timestamptz | yes | |
| `duplicate` | boolean | no | default false; set once, when it is bound |
| `last_event_at` | timestamptz | no | the `occurred_at` of the last applied event |
| `reconciled_at` | timestamptz | yes | |
| `created_at`, `updated_at` | timestamptz | no | default `now()` |

Indexes: `uq_agency_subscriptions_primary` unique on `agency_id` where `NOT duplicate AND status <> 'canceled'` (at most one primary subscription that has not ended); `ix_agency_subscriptions_agency` (`agency_id`, `created_at`); `ix_agency_subscriptions_reconcile` on `reconciled_at` where `status <> 'canceled'`. There is no reference to `billing_checkouts`, because checkouts are purged while subscriptions stay.

### 3.4 `billing_checkouts` (D6)

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | uuid | no | primary key |
| `agency_id` | uuid | no | references `agencies.id` |
| `price_id` | uuid | no | references `billing_prices.id` |
| `requested_by_membership_id` | uuid | no | (`agency_id`, `requested_by_membership_id`) references `agency_memberships` (`agency_id`, `id`) |
| `provider_transaction_id` | varchar(32) | no | `^txn_...`; unique |
| `status` | varchar(16) | no | `IN ('open', 'completed', 'expired')`, default `'open'` |
| `created_at` | timestamptz | no | default `now()` |
| `expires_at` | timestamptz | no | after `created_at` and at most 24 hours later |
| `completed_at` | timestamptz | yes | set exactly when completed |

Indexes: `uq_billing_checkouts_open` unique on `agency_id` where `status = 'open'`; `ix_billing_checkouts_agency` (`agency_id`, `created_at`); `ix_billing_checkouts_expires_at`.

### 3.5 `billing_events` (D7)

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | uuid | no | primary key |
| `provider` | varchar(16) | no | `'paddle'` |
| `provider_event_id` | varchar(40) | no | `evt_` + 26 for a webhook, `rec_` + 32 hexadecimal digits for a reconciliation; unique with `provider` (`uq_billing_events_provider_event`) |
| `source` | varchar(16) | no | `IN ('webhook', 'reconciliation')`, matching the ID prefix |
| `event_type` | varchar(48) | no | `~ '^[a-z_]{1,24}\.[a-z_]{1,23}$'` |
| `occurred_at` | timestamptz | no | |
| `received_at` | timestamptz | no | default `now()` |
| `agency_id` | uuid | yes | references `agencies.id`; null for `unmatched`, required for `applied` and `stale` |
| `subscription_id` | uuid | yes | (`agency_id`, `subscription_id`) references `agency_subscriptions` (`agency_id`, `id`) |
| `provider_subscription_id`, `provider_transaction_id` | varchar(32) | yes | the IDs read from the payload |
| `outcome` | varchar(16) | no | `IN ('applied', 'stale', 'ignored', 'unmatched')` |
| `error_code` | varchar(32) | yes | `IN ('unknown_price', 'unsupported_items', 'binding_conflict', 'invalid_payload', 'agency_closed')` |
| `fields` | jsonb | no | default `'{}'`, an object of allowlisted fields (section 5.3) |

Indexes: `ix_billing_events_received_at`; `ix_billing_events_agency` (`agency_id`, `occurred_at`); `ix_billing_events_unmatched` on `received_at` where `outcome = 'unmatched'`.

### 3.6 `billing_payments` (kept, D11)

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | uuid | no | primary key; unique (`agency_id`, `id`) |
| `agency_id` | uuid | no | references `agencies.id` |
| `subscription_id` | uuid | yes | (`agency_id`, `subscription_id`) references `agency_subscriptions` |
| `provider_transaction_id` | varchar(32) | no | `^txn_...`; unique |
| `status` | varchar(16) | no | `IN ('draft', 'ready', 'billed', 'paid', 'completed', 'canceled', 'past_due')` |
| `origin` | varchar(40) | yes | `IN ('api', 'subscription_charge', 'subscription_payment_method_change', 'subscription_recurring', 'subscription_update', 'web')` |
| `currency` | varchar(3) | no | `~ '^[A-Z]{3}$'` |
| `subtotal_cents`, `tax_cents`, `total_cents` | bigint | no | `>= 0` each |
| `billed_at` | timestamptz | yes | |
| `invoice_number` | varchar(64) | yes | `~ '^[A-Za-z0-9-]{1,64}$'` |
| `last_event_at` | timestamptz | no | |
| `created_at`, `updated_at` | timestamptz | no | default `now()` |

Index: `ix_billing_payments_agency` (`agency_id`, `created_at`, `id`).

### 3.7 `billing_adjustments` (kept, D11)

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | uuid | no | primary key |
| `agency_id` | uuid | no | references `agencies.id` |
| `payment_id` | uuid | yes | (`agency_id`, `payment_id`) references `billing_payments` (`agency_id`, `id`); linked when the payment is known |
| `provider_adjustment_id` | varchar(32) | no | `^adj_...`; unique |
| `provider_transaction_id` | varchar(32) | no | `^txn_...` |
| `action` | varchar(32) | no | the seven actions of V-6 |
| `status` | varchar(24) | no | `IN ('pending_approval', 'approved', 'rejected', 'reversed')` |
| `currency` | varchar(3) | no | `~ '^[A-Z]{3}$'` |
| `total_cents` | bigint | no | `>= 0` |
| `last_event_at` | timestamptz | no | |
| `created_at`, `updated_at` | timestamptz | no | default `now()` |

Indexes: `ix_billing_adjustments_payment` (`agency_id`, `payment_id`); `ix_billing_adjustments_transaction` on `provider_transaction_id`.

### 3.8 `billing_actions` (D10)

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | uuid | no | primary key |
| `agency_id` | uuid | no | references `agencies.id` |
| `subscription_id` | uuid | no | (`agency_id`, `subscription_id`) references `agency_subscriptions` |
| `action` | varchar(32) | no | `cancel_next_period` with reason `closure_requested`, `remove_scheduled_cancel` with `closure_cancelled`, `cancel_now` with `closure_completed` |
| `reason` | varchar(24) | no | as paired |
| `status` | varchar(16) | no | `IN ('pending', 'done', 'failed', 'skipped')`, default `'pending'` |
| `attempts` | smallint | no | default 0, `BETWEEN 0 AND 20` |
| `next_attempt_at` | timestamptz | no | default `now()` |
| `last_error` | varchar(32) | yes | a closed provider code |
| `created_at` | timestamptz | no | default `now()` |
| `completed_at` | timestamptz | yes | null exactly while pending |

Indexes: `ix_billing_actions_due` on `next_attempt_at` where pending; `ix_billing_actions_subscription` (`subscription_id`, `created_at`) where pending; `ix_billing_actions_agency` (`agency_id`, `created_at`).

### 3.9 Changes to existing tables and seeds

- **`saas_plans`.** Seeds `billing_hold` ("Billing hold"): 0 clients, 0 seats, 0 connections, 0 managed links and a tracked-event allowance of 0 (soft), not the default, reason `seed`.
- **`agency_plan_assignments`.** `valid_assigned_by` adds `billing`; `valid_reason` adds `subscription` and `billing_hold`; `reason_matches` becomes `(assigned_by = 'default' AND reason IN ('initial', 'new_agency')) OR (assigned_by = 'platform_operator' AND reason IN ('plan_change', 'correction')) OR (assigned_by = 'billing' AND reason IN ('subscription', 'billing_hold'))`.
- **`audit_events`.** Actions `billing_price.registered`, `billing_price.retired`, `billing.granted`, `billing.grant_ended`, `billing.trial_extended`, `billing.reconciled`, `billing.checkout_created`, `billing.plan_change_requested`, `billing.cancel_scheduled` and `billing.cancel_removed`; resources `billing_price`, `agency_billing`, `billing_checkout` and `agency_subscription`; the scope check accepts a platform-level event without an agency for resource `plan` or `billing_price`.
- **`mail_outbox`.** Purposes `trial_ending` and `billing_hold`.
- **Standings.** Every agency that is not purged receives `complimentary` with reason `migration`.

### 3.10 Grants

- **`tracking_app`:** `SELECT, INSERT` on the eight tables, and `UPDATE` only on: `billing_prices (offered, retired_at)`; `agency_billing` (every column except `agency_id` and `created_at`); `agency_subscriptions` (`price_id`, `provider_price_id`, `status`, the period, `next_billed_at`, the scheduled pair, `cancel_origin`, `canceled_at`, `last_event_at`, `reconciled_at`, `updated_at`); `billing_checkouts (status, completed_at)`; `billing_payments` (`subscription_id`, `status`, `origin`, `currency`, the three amounts, `billed_at`, `invoice_number`, `last_event_at`, `updated_at`); `billing_adjustments` (`payment_id`, `status`, `currency`, `total_cents`, `last_event_at`, `updated_at`); `billing_actions (status, attempts, next_attempt_at, last_error, completed_at)`; `billing_events (agency_id, subscription_id, outcome, error_code)`, so that an event stored unmatched before its subscription was bound is bound with it (section 5.2). `tracking_app` deletes none of the tables.
- **`tracking_lifecycle`:** `SELECT (id, received_at)` and `DELETE` on `billing_events`; `SELECT (id, status, expires_at)` and `DELETE` on `billing_checkouts`; `SELECT (id, agency_id, status)` on `agency_subscriptions` and `INSERT` on `billing_actions`, for the closure completion (section 10).

### 3.11 Data policy

New classes: `billing.price` (low, not personal, never deleted), `billing.standing` (medium, pseudonymous through the Paddle customer ID; deleted by the purge), `billing.subscription`, `billing.payment` and `billing.adjustment` (low, not personal: provider IDs, codes, amounts and times of a business record; kept after the purge, D10), `billing.checkout` (medium, pseudonymous through the requesting membership; 30 days after expiry, or the purge), `billing.event` (medium, pseudonymous through the customer IDs in its fields; 13 months after receipt, provisional under Q-012), and `billing.action` (low, not personal; deleted by the purge). Every column of the eight tables is classified. `KEPT_AFTER_PURGE` gains the three kept tables, so the purge rule is added to the other four scoped tables by construction.

### 3.12 `purge_agency_batch`

`0034` replaces the function body with `CREATE OR REPLACE FUNCTION`, which keeps its owner and grants. The steps become `billing_actions`, `billing_events`, `billing_checkouts` and `agency_billing` (each by `agency_id = p_agency`, through the indexes above), followed by the 81 steps of `0033` unchanged. In state `waiting`, a pending billing action of the agency raises `teardown_pending`, like a connection teardown before its deadline, so no provider action is deleted before the worker has settled it. The downgrade restores the `0033` body exactly; a test compares `pg_get_functiondef` before the upgrade and after the downgrade.

### 3.13 Guarded downgrade

It refuses any row of the seven tables other than `agency_billing`, any standing other than `complimentary` with reason `migration` or `billing_disabled`, any assignment by `billing` or to the `billing_hold` plan, any new audit value and any new mail purpose. Otherwise it restores the function, drops the tables, deletes the `billing_hold` plan and restores the checks.

## 4. Standing and plans (D4, D5)

Every transition runs in one transaction under the agency row lock (`SELECT ... FOR UPDATE` on `agencies`) and writes its plan assignment, when the plan changes, in the same transaction. A transition that changes nothing writes nothing. `version` is incremented on every change. Provider-driven transitions are audited by their stored event and their assignment; operator transitions by an audit event with `actor_kind = 'platform_operator'`. Messages are queued by the worker (section 8).

| From | Trigger | To (reason) | Plan assignment | Audit | Message |
|---|---|---|---|---|---|
| (new agency, billing allowed) | `create_agency` | `trialing` (`new_agency`), trial end = creation + `TRACKING_BILLING_TRIAL_DAYS` | the default plan, `default`/`new_agency` (unchanged 017-A) | `agency.created` (existing) | `trial_ending` 3 days before the end |
| (new agency, billing not allowed) | `create_agency` | `complimentary` (`billing_disabled`) | the default plan, as today | `agency.created` | none |
| (existing agency) | migration `0034` | `complimentary` (`migration`) | unchanged | none | none |
| `trialing` | worker: trial end without a subscription | `hold` (`trial_ended`) | `billing_hold`, `billing`/`billing_hold` | event-free; the assignment | `billing_hold` |
| `trialing`, `hold`, `past_due`, `subscribed`, `complimentary` (`migration`, `billing_disabled`) | the primary subscription is `active` or `trialing` | `subscribed` (`subscription_active`; `payment_recovered` from `past_due`) | the subscribed price's plan, `billing`/`subscription` | the stored event | none |
| `subscribed` | `past_due` | `past_due` (`payment_failed`) | unchanged | the stored event | none (Paddle notifies the buyer) |
| `subscribed`, `past_due`, `trialing` | `paused` or `canceled` | `hold` (`subscription_paused` or `subscription_canceled`) | `billing_hold` | the stored event | `billing_hold` |
| any but closed | operator `grant --plan [--until]` | `complimentary` (`operator_grant`), grant end as given | the operator's plan, `platform_operator`/`plan_change` | `billing.granted` | none |
| `complimentary` (`operator_grant`) | worker at the grant end, or `end-grant` | derived from the primary subscription: `subscribed`, `past_due`, or `hold` (`grant_ended`) | as derived | `billing.grant_ended` (command only) | `billing_hold` when it holds |
| `trialing` | operator `extend-trial --days N` | `trialing`, trial end + N days, reminder cleared | unchanged | `billing.trial_extended` | a new reminder |

Rules:
- **Grants win.** While an operator grant is in force, subscription events update the subscription record only.
- **Duplicates.** An event of a subscription flagged as a duplicate changes no standing.
- **Closed agencies.** A closed agency's subscription records still follow their events, but its standing never changes (`agency_closed` on the event). A suspended or closing agency's standing follows its events, because a suspension changes nothing in billing (D10).
- **Unknown prices.** An active subscription whose price is not registered (or which has more than one item) keeps the current plan, except that a `billing_hold` plan is replaced by the default plan, so a paying agency is never held; the event records `unknown_price` or `unsupported_items`.
- **Kill switch.** While billing is disabled, the standing machinery is inert: no transition happens, the webhook and routes answer 503, the worker prints `{"status": "disabled"}`, and an agency already on hold keeps the `billing_hold` plan until the operator grants it a period after billing is enabled again, or assigns a plan with `app.agency_plans`.

## 5. Webhook and events (D7, D9, D11)

### 5.1 Route `POST /billing/paddle/webhook`

In this order: the gate (`TRACKING_BILLING_ENABLED` and a current `paddle.billing` rule, else 503 `billing_unavailable`); the per-peer rate (`paddle-peer`, `TRACKING_INGEST_TRUSTED_PER_MINUTE` per minute, 429); the body bound of 256 KiB (`ROUTE_LIMITS`, 413); the signature over the raw body with the timestamp within 300 seconds of the server clock in either direction (401 `invalid_signature` for a missing, malformed, old or wrong signature); the JSON envelope (400 `invalid_payload` if the body is not an object with a valid `event_id`, `event_type`, `occurred_at` and an object `data`; nothing is stored); then the record and its effects in the request transaction, and `200 {"status": "received"}`. A verified event is answered 200 whatever its outcome, so Paddle stops retrying.

### 5.2 Processing

1. **Resolve** the agency without a lock: a stored subscription by `data.id` (subscription events) or `data.subscription_id`; a stored payment or checkout by the transaction ID; a checkout by `subscription.created`'s `transaction_id`. When `custom_data` names another agency or checkout than the checkout found, the event is `unmatched` with `binding_conflict`.
2. **No agency:** the event is stored `unmatched` (insert with `ON CONFLICT DO NOTHING`), and the log event `billing_event_unmatched` is written.
3. **Lock** the agency row, then re-resolve (a concurrent event of the same subscription may have bound it). A stored `event_id` means a repeated delivery: nothing changes.
4. **Bind** only through the checkout's transaction ID, which `subscription.created` carries (D6). An event of the subscription that arrived earlier was stored `unmatched` with its allowlisted fields; at binding, the newest of those events that is later than the binding event is applied, and the others are marked `stale`, with the agency and subscription set.
5. **Order:** an event whose `occurred_at` is earlier than the `last_event_at` of the same subscription, payment or adjustment is stored `stale` and not applied; an equal time is applied.
6. **Apply** by type, and store the event with its outcome and allowlisted fields.

| Type | Effect |
|---|---|
| `subscription.created`, `activated`, `updated`, `trialing`, `past_due`, `paused`, `resumed`, `canceled` | Bind (insert the subscription, flagged `duplicate` when the agency already has a primary subscription that has not ended; complete an open checkout), or update the stored state; set `cancel_origin` to `provider` for a scheduled cancellation of unknown origin and clear it when no cancellation is scheduled; record the customer ID on the standing when it has none; apply section 4. |
| `transaction.completed`, `paid`, `payment_failed` | Record or update the payment (status, origin, currency, subtotal, tax, total, billed time, invoice number, subscription); complete the matching open checkout when the status is `paid` or `completed`; link earlier adjustments of the transaction. No standing effect. |
| `adjustment.created`, `updated` | Record or update the adjustment. No standing effect (a refund changes no standing, D9). |
| any other type, and `subscription.imported` | `ignored`. |

A payload field that fails validation (an ID, a status, an amount, a currency or a time) stores the event `ignored` with `invalid_payload` and applies nothing.

### 5.3 Allowlisted fields

- **Subscriptions:** `status`, `customer_id`, `price_id`, `item_count`, `period_starts_at`, `period_ends_at`, `next_billed_at`, `scheduled_action`, `scheduled_at`, `canceled_at`, `currency`.
- **Transactions:** `status`, `origin`, `subscription_id`, `currency`, `subtotal`, `tax`, `total`, `billed_at`, `invoice_number`.
- **Adjustments:** `action`, `status`, `transaction_id`, `subscription_id`, `currency`, `total`.

Nothing else is stored: no name, email, address, business, card, payment method, discount code, `custom_data` or management URL.

## 6. Paddle adapter (`app/billing/paddle.py`)

- **Transport.** `urllib` with a 10-second timeout, at most 1 MiB of response read, the headers `Authorization: Bearer <key>`, `Paddle-Version: 1`, `Accept` and `Content-Type: application/json`; the base address is `https://sandbox-api.paddle.com` or `https://api.paddle.com` by `TRACKING_BILLING_PADDLE_ENVIRONMENT`. The transport is injectable; nothing logs a URL, header or body.
- **Calls.**

| Call | Method and path | Body | Answer used |
|---|---|---|---|
| create a transaction | `POST /transactions` | `items: [{price_id, quantity: 1}]`, `customer_id` when known, `custom_data: {agency_id, checkout_id}`, `collection_mode: "automatic"`, `currency_code: "USD"` | `data.id`, `data.status` |
| get a subscription | `GET /subscriptions/{id}` | | the subscription snapshot |
| preview an update | `PATCH /subscriptions/{id}/preview` | `items`, `proration_billing_mode` | `immediate_transaction` and `next_transaction` totals, `update_summary` |
| update | `PATCH /subscriptions/{id}` | `items`, `proration_billing_mode`, `on_payment_failure: "prevent_change"` | the snapshot |
| cancel | `POST /subscriptions/{id}/cancel` | `effective_from: "next_billing_period"` or `"immediately"` | the snapshot |
| remove a scheduled change | `PATCH /subscriptions/{id}` | `scheduled_change: null` | the snapshot |
| payment-method transaction | `GET /subscriptions/{id}/update-payment-method-transaction` | | `data.id` |
| invoice | `GET /transactions/{id}/invoice` | | `data.url` (HTTPS only) |
| get a price | `GET /prices/{id}` | | `status`, `unit_price.amount`, `unit_price.currency_code`, `billing_cycle` |

- **Errors.** A network failure, timeout, 5xx or oversized answer: `provider_unavailable`; 429: `provider_rate_limited` (with `Retry-After`); 401 or 403: `provider_unauthorized`; 404: `provider_not_found`; `subscription_locked_renewal` or `subscription_locked_processing`: `subscription_locked`; `subscription_locked_pending_changes`: `pending_change`; `subscription_update_when_past_due`: `past_due`; `subscription_is_canceled_action_invalid` or `subscription_update_when_canceled`: `subscription_canceled`; `subscription_immediate_charge_*`: `change_limit`; another 4xx: `provider_rejected`; an answer that fails validation: `provider_invalid_response`. The provider's message is never kept.
- **Synthetic server.** `tests/paddle_api.py` implements the nine calls in memory with the same shapes, records every request, can fail the next request with any status and error body, and its sender signs events with the documented header (`signed_event`).

## 7. Owner routes (D6, D8, D9, D11)

Every route needs a browser session (`BrowserDep`, which refuses bearer keys), and every write the session's CSRF token and an allowed origin. The agency must be active. Owners act; Owners and Admins read; Analysts, client viewers and other agencies get the uniform 403. While billing is disabled, every route answers 503 `billing_unavailable`. A provider failure answers 503 `billing_provider_unavailable` and the request transaction rolls back. Routes that call Paddle are throttled per user (`billing-user`, 20 per minute).

| Route | Who | Answer | Refusals |
|---|---|---|---|
| `GET /billing/prices` | any signed-in user | 200: the environment, the client token (or null) and the offered prices: ID, plan key, name and limits, amount in cents, currency, interval | 503 |
| `GET /agencies/{a}/billing` | Owner, Admin | 200: standing, reason, trial end, grant end, hold start, the plan's key and name, the primary subscription (status, price, period end, next billing, scheduled change), the last payment's status, total, currency and billing time, the version | 403, 503 |
| `POST /agencies/{a}/billing/checkout` `{price_id}` | Owner | 201 with a new checkout, or 200 with the open checkout of the same price: checkout ID, transaction ID, status, expiry | 409 `price_not_offered`, `already_subscribed`; 503 |
| `POST /agencies/{a}/billing/change` `{price_id, preview}` | Owner | preview 200: the proration mode, immediate and next totals and the update summary; request 202 `{"status": "requested", "proration": mode}` | 409 `not_subscribed`, `change_not_allowed`, `same_price`, `price_not_offered`; 503 |
| `POST /agencies/{a}/billing/cancel` | Owner | 200: the scheduled change (`cancel` with its time), from Paddle's answer | 409 `not_subscribed`, `change_not_allowed`; 503 |
| `DELETE /agencies/{a}/billing/cancel` | Owner | 204 | 409 `not_subscribed`, `no_scheduled_cancel`, `change_not_allowed`; 503 |
| `POST /agencies/{a}/billing/payment-method` | Owner | 200: the transaction ID for Paddle.js | 409 `not_subscribed`, `change_not_allowed`; 503 |
| `GET /agencies/{a}/billing/payments` (`limit`, `offset`) | Owner, Admin | 200: payments newest first: ID, status, origin, currency, subtotal, tax, total, billing time, invoice number, whether an invoice is available | 403, 503 |
| `GET /agencies/{a}/billing/payments/{p}/invoice` | Owner, Admin | 302 to Paddle's address, fetched at request time and never stored or logged | 403 (unknown or foreign payment), 409 `invoice_unavailable`; 503 |

- **Checkout (D6).** Under the agency lock: the price must be offered; any subscription of the agency that has not ended refuses `already_subscribed`; an open, unexpired checkout of the same price is returned; an open checkout of another price, or one past its expiry, is marked `expired`; then the transaction is created with the checkout's ID and the agency in `custom_data` and the standing's customer ID, and the checkout is stored for 24 hours and audited (`billing.checkout_created`).
- **Plan change (D8).** The primary subscription must be `active`, have no scheduled change, and not be within 30 minutes of `next_billed_at`; its price must be registered. A price of the same interval with a lower amount is a downgrade (`prorated_next_billing_period`); any other change, including monthly to annual and back, is charged at once (`prorated_immediately`). The preview calls Paddle's preview and changes nothing; a request calls the update and is audited (`billing.plan_change_requested`); the limits change only when `subscription.updated` arrives. Paddle's `past_due`, `subscription_locked`, `pending_change` and `change_limit` answers become `change_not_allowed`.
- **Cancellation (D9).** Allowed while `active`, `trialing` or `past_due` and not within 30 minutes of the renewal; an already scheduled cancellation answers the stored schedule without a call. On success the subscription's `cancel_origin` becomes `owner` (audited `billing.cancel_scheduled`). The undo needs a scheduled cancellation, or a stored `cancel_origin`, and clears the origin (audited `billing.cancel_removed`).

## 8. Worker (`python -m app.billing_worker [--limit N]`)

One bounded pass as `tracking_app`; `--limit` (1-100, default 25) bounds each step. While billing is not allowed it prints `{"status": "disabled"}` and changes nothing. Otherwise, in order:

1. **Trials and grants:** trialing standings whose trial has ended go on hold; operator grants whose end has passed are derived (section 4). Each agency in its own transaction under the agency lock (`SKIP LOCKED`; a busy agency waits for the next pass).
2. **Provider actions (D10):** due pending actions, oldest first, at most one per subscription at a time (an older pending action of the same subscription goes first). A claim (attempt counted, a five-minute lease) is committed before the call, and the result is recorded under the agency lock afterwards. Skipped without a call: a cancellation of a canceled subscription, a period-end cancellation when one is already scheduled or the subscription is paused, and a removal when the scheduled cancellation is not the closure's. `cancel_now` that meets `pending_change` removes the scheduled change and cancels. Failures retry after 5, 10, 20, 40, 80, 160 and 320 minutes; the eighth failure is `failed` (log `billing_action_failed`). A canceled subscription answer is `skipped`.
3. **Reconciliation (D7):** subscriptions that have not ended and were not reconciled in the last 24 hours, oldest first: the subscription is read from Paddle, and a difference from the stored state is applied as an event (`rec_...`, `source = 'reconciliation'`, `occurred_at` the time the read started) through the same processing, so it is `stale` if a webhook was newer.
4. **Messages (D11):** the `trial_ending` reminder for trials ending within 3 days that have none, and the `billing_hold` message for holds that have none, to every active, verified Owner, then the time is set. The messages are link-only (`{frontend}/agencies/{a}/billing`), name no agency or person, and expire at the trial end or after 7 days.

Output: `{"status": "completed", "trials_ended", "grants_ended", "actions": {"done", "skipped", "retried", "failed"}, "reconciliation": {"checked", "corrected", "failed"}, "messages": {"trial_ending", "billing_hold"}}`, counts only. The lifecycle runner deletes `billing_events` 395 days after receipt (provisional, Q-012) and open or expired checkouts 30 days after their expiry (`TRACKING_LIFECYCLE` settings `billing_event_retention_days` and `billing_checkout_retention_days`, each at most its default).

## 9. Operator command (`python -m app.agency_billing`, D12)

It runs as `tracking_app` with the application settings, prints one JSON document, and refuses with `{"error": code}` and exit code 1. Every change needs `--confirm`, needs billing to be allowed (`billing_unavailable` otherwise), and writes an audit event with `actor_kind = 'platform_operator'`.

| Subcommand | Effect | Refusals |
|---|---|---|
| `prices` | every registered price with its plan key, amount, interval, offer state and times | |
| `register-price --plan K --price-id pri_... --amount-cents N --interval month\|year [--replaces pri_...]` | reads the price from Paddle, which must be active, in USD, of the same amount and of a one-month or one-year cycle; stores it offered; `--replaces` retires an offered price of the same plan and interval in the same transaction; audited `billing_price.registered` (and `billing_price.retired`) | `plan_not_found`, `reserved_plan`, `price_exists`, `price_offered`, `price_mismatch`, `provider_unavailable` |
| `retire-price --price-id pri_...` | stops offering it; existing subscriptions keep it; audited | `price_not_found`, `price_retired` |
| `status --agency A` | the standing, the plan, every subscription with its flags, the checkouts, the open and failed actions, the last payment | `agency_not_found` |
| `grant --agency A --plan K [--until T]` | section 4; `T` must be in the future | `agency_not_found`, `agency_closed`, `plan_not_found`, `reserved_plan`, `invalid_until` |
| `end-grant --agency A` | section 4 | `not_granted` |
| `extend-trial --agency A --days N` (1-30) | section 4 | `not_trialing` |
| `agencies [--standing S] [--held-days N] [--after A] [--limit N]` | standings with plan keys and times; `--held-days` lists holds older than N days (the D5 review at 60 days) | |
| `events --unmatched [--limit N]` | unmatched events, newest first: IDs, type, times, error code | |
| `duplicates` | duplicate subscriptions with their agency, status and the primary subscription's ID | |
| `reconcile [--agency A] [--limit N]` | the reconciliation of section 8 at once (for one agency regardless of the 24-hour window); each correction audited `billing.reconciled` | `agency_not_found`, `provider_unavailable` |

The output holds IDs, keys, amounts, codes and times only. `app.agency_plans set-default` and `assign` refuse the `billing_hold` plan (`reserved_plan`).

## 10. Closure, purge and export (D10)

- **Request** (`ClosureService.request`, same transaction): a `cancel_next_period` action for every subscription of the agency that is `active`, `trialing` or `past_due` and has no scheduled cancellation and no `cancel_origin`.
- **Cancellation** (`ClosureService.cancel`, same transaction): a pending `cancel_next_period` that was never claimed is `skipped` (`closure_cancelled`); for a subscription whose cancellation came from the closure (`cancel_origin = 'closure'`) or whose closure action was already claimed, a `remove_scheduled_cancel` action is queued. An Owner's earlier cancellation (`owner`) is kept.
- **Completion** (`agency_lifecycle.complete_closures`, as `tracking_lifecycle`, in the transaction that closes the agency): a `cancel_now` action for every subscription of the agency that is not canceled, duplicates included, without an automatic refund.
- **Suspension:** no billing effect.
- **Purge:** section 3.12; the purge waits while an action is pending.
- **Export:** the seven scoped billing tables are agency administration and platform billing, not a client's first-party data, and Paddle issues the receipts and invoices, so the offboarding export excludes them (the reviewed exclusions of `tests/test_agency_export_contract.py`).

## 11. Settings

| Setting | Default | Validation |
|---|---|---|
| `TRACKING_BILLING_ENABLED` | `false` | when true, the key and the secret below are required |
| `TRACKING_BILLING_TRIAL_DAYS` | `14` | 1 to 30 |
| `TRACKING_BILLING_PADDLE_ENVIRONMENT` | `sandbox` | `sandbox` or `live` |
| `TRACKING_BILLING_PADDLE_API_KEY` | blank | Paddle's documented key form, whose environment part (`sdbx`, `live`) matches the environment |
| `TRACKING_BILLING_PADDLE_WEBHOOK_SECRET` | blank | `pdl_ntfset_` and 16 to 256 printable characters without spaces |
| `TRACKING_BILLING_PADDLE_CLIENT_TOKEN` | blank | optional; Paddle's client-token form, `test_` for sandbox and `live_` for live |

A failed validation names the setting, never its value. The provider rule `paddle.billing` (verified 2026-11-28, review 2027-11-28) gates the webhook, the routes, the worker and the command. The application builds the adapter only when billing is enabled (`app.state.billing_provider`); tests substitute one bound to the synthetic server.

## 12. Logs and outputs

Three registered log events, with no field other than a closed code: `billing_event_unmatched`, `billing_action_failed` and `billing_provider_failed` (`billing_code`). No API key, webhook secret, signature, header, body, URL, name, email, address, card detail or invoice address is logged, answered, stored or printed.

## 13. API changes

Additions only: the nine routes of section 7 and the webhook, their request and response schemas, and one sentence of the API description. No existing path or schema changes, apart from the agency creation, whose answer is unchanged.

## 14. Test inventory (BL01-BL23)

| Case | Tests |
|---|---|
| BL01 Prices | `test_billing_command.py::test_bl01_register_and_retire_prices`, `test_bl01_price_rules`; `test_billing_owner.py::test_bl01_price_list_offers_only_offered_prices` |
| BL02 Trial | `test_billing_standing.py::test_bl02_new_agency_standing_follows_the_setting`; `test_billing_migration.py::test_bl21_upgrade_from_a_populated_0033` (existing agencies) |
| BL03 Trial end | `test_billing_standing.py::test_bl03_trial_reminder_and_end` |
| BL04 Hold | `test_billing_standing.py::test_bl04_hold_refuses_creations_and_stops_nothing` |
| BL05 Checkout | `test_billing_owner.py::test_bl05_checkout_roles_and_refusals`, `test_bl05_one_open_checkout_under_concurrency` |
| BL06 Signature | `test_billing_paddle.py::test_bl06_signature_rules`; `test_billing_webhook.py::test_bl06_webhook_signature_bound_and_rate` |
| BL07 Idempotency and order | `test_billing_webhook.py::test_bl07_repeated_and_older_events` |
| BL08 Activation | `test_billing_webhook.py::test_bl08_activation_ends_trial_and_hold` |
| BL09 Plan changes | `test_billing_owner.py::test_bl09_plan_changes_and_preview`; `test_billing_paddle.py::test_bl09_adapter_sends_proration_modes` |
| BL10 Failed payments | `test_billing_webhook.py::test_bl10_past_due_recovery_and_cancellation` |
| BL11 Cancellation | `test_billing_owner.py::test_bl11_cancel_undo_and_resubscribe` |
| BL12 Records | `test_billing_webhook.py::test_bl12_payments_and_adjustments` |
| BL13 Invoice | `test_billing_owner.py::test_bl13_invoice_redirect` |
| BL14 Closure | `test_billing_owner.py::test_bl14_closure_actions` |
| BL15 Purge | `test_billing_owner.py::test_bl15_purge_keeps_financial_records`; `test_agency_offboarding_migration.py::test_ov09_function_covers_every_scoped_table` |
| BL16 Unmatched and duplicates | `test_billing_webhook.py::test_bl16_unmatched_and_duplicates` |
| BL17 Reconciliation | `test_billing_owner.py::test_bl17_reconciliation_corrects_a_missed_event` |
| BL18 Operator command | `test_billing_command.py` (every subcommand, `--confirm`, audit rows, output) and `tests/test_billing_command_parser.py` |
| BL19 Separation | `test_billing_webhook.py::test_bl19_billing_never_touches_client_revenue` |
| BL20 Isolation | `test_billing_standing.py::test_bl20_other_agencies_never_change` |
| BL21 Migration | `test_billing_migration.py` (upgrade, grants, function, downgrade) |
| BL22 Secrets and logs | `test_billing_paddle.py::test_bl22_settings_validation`; `test_billing_webhook.py::test_bl22_no_secret_in_logs_answers_or_outputs` |
| BL23 Existing behavior | every existing suite; `test_billing_owner.py::test_bl23_journey` (the end-to-end journey of P4) and the OpenAPI comparison |

## 15. Routine details resolved here

1. A checkout request for another price expires the open checkout and opens a new one; at most one checkout is open.
2. An expired checkout still binds a late payment of its transaction; a second live subscription is flagged a duplicate.
3. A subscription is bound only through the `transaction_id` of `subscription.created`, as D6 requires; `custom_data` is a check, and a conflict leaves the event unmatched. Events of the subscription that arrive before it are replayed from their stored fields at binding, so the order of delivery does not matter.
4. An event with the same `occurred_at` as the last applied one is applied; only an earlier one is stale.
5. Paddle's `trialing` status is treated as active, as Paddle advises.
6. An unregistered price keeps the plan but never leaves a paying agency on the hold plan.
7. Operator grants win over subscription events until they end; the complimentary standings of the migration and of a disabled billing end when the agency subscribes.
8. The closure actions cover every subscription that has not ended, duplicates included, as D10 speaks of any subscription that is still active.
9. The purge waits for pending billing actions.
10. The downgrade accepts the complimentary standings that hold no billing state.
11. `register-price` verifies the price with Paddle and allows one offered price per plan and interval, with `--replaces` for an atomic replacement.
12. `set-default` and `assign` of `app.agency_plans` refuse the `billing_hold` plan.
13. Disabling billing freezes every standing (section 4).
14. Routes that call Paddle are throttled per user, below Paddle's per-IP limit.
15. A verified body that is not a valid envelope is refused with 400 and stored nowhere; an event with an invalid field is stored `ignored`.
16. The worker settles one action per subscription at a time, with a claim lease; a removal waits for the claimed cancellation.
17. The messages are queued by the worker, not by the webhook, so the webhook stays within Paddle's five seconds.
18. Completed checkouts stay until the purge; open and expired ones leave 30 days after their expiry.
19. The billing tables are excluded from the offboarding export.
20. Every transaction of a known agency is recorded, zero-value ones included, which have no invoice.
21. An adjustment that arrives before its payment is linked when the payment is recorded.
22. Reconciliation events are `rec_` plus 32 hexadecimal digits, timed at the start of the read.

## 16. Limits

- No live Paddle call was made: the adapter is tested only against the synthetic server, whose shapes come from section 2. The owner's sandbox check after the merge confirms them; Paddle runs no automatic payment retries in the sandbox (V-13), so the recovery path is checked by simulated events there.
- Before live use the owner decides the prices, opens the Paddle account, turns off automatic currency conversion if checkouts must stay in USD (V-15), configures the recovery to cancel after the last retry (V-13), and publishes the terms, refund and privacy pages (V-14). Hosting, the HTTPS webhook address, the worker schedule, key rotation every 90 days (V-12) and the live keys belong to 020.
- A provider action that fails all its attempts is listed for the operator, who cancels in Paddle; billing never suspends, closes or deletes an agency by itself (D5).
- A duplicate subscription is never canceled or promoted automatically; the operator resolves it in Paddle.
- The prices, checkout and billing pages, and Paddle.js, belong to 018.
