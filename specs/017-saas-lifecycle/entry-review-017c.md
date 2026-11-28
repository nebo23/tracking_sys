# Spec 017-C entry review: subscription billing, prices and the trial

Prepared: 2026-11-28 under D-102.
- **Baseline:** merged `main` at `04dc323` (PR 21: Spec 017-B, agency offboarding).
- **Status:** approved. The owner approved D1-D14 as recommended, without amendment, on 2026-11-28 (D-103).
- **Handoff:** the [implementation handoff](implementation-prompt-017c.md) executes this packet after approval.
- **Owner inputs (2026-11-28):** the first paying agencies are worldwide and pay in USD; the company that sells the subscriptions is registered in Egypt and also outside Egypt.

## 1. Intended result

017-C lets agencies pay for the platform:
- **Prices.** The platform operator publishes a price list in USD, monthly or annual, for the plans of 017-A.
- **Trial.** Every new agency starts with a 14-day trial, without a card.
- **Subscriptions.** Paddle Billing handles checkout, renewal, plan changes, cancellation and the recovery of failed payments. It acts as merchant of record: it collects and remits the sales taxes of each buyer's country and issues the invoices.
- **Standing.** Every agency has one billing standing, which decides its plan. A paying agency gets the limits of the plan it pays for. An agency whose trial or subscription has ended goes on hold: it cannot add clients, members, connections or links, but nothing else stops and nothing is deleted.

This closes acceptance criteria 1 and 3 of the [017 spec](spec.md): "Concurrent account creation does not duplicate agencies or subscriptions" and "Duplicate or delayed billing webhooks are idempotent; SaaS subscription billing remains separate from agency-client revenue." With the owner's decision it also settles Q-005 (subscription customer, trial and usage limits). The prices themselves stay the owner's data (D3).

D-091 set the order: the backend first, with 017-C last, after research and an owner decision. LinkedIn (012) and X (013) stay deferred under D-063.

## 2. Baseline on `main`

| Area | Available | Consequence for 017-C |
|---|---|---|
| Plans and limits (017-A) | Plans are immutable, and assignments are an insert-only history whose highest revision is the current plan. `create_agency` assigns the default plan. The four counted limits (clients, seats, connections, managed links) are hard on creation under the agency lock; the tracked-event allowance is soft. The operator command `app.agency_plans` creates plans, sets the default, assigns, suspends and reactivates. Plans carry no price. | A price is attached to a plan. Billing changes an agency's plan only through new assignments. A hold is a plan whose creation limits are zero, so the existing checks enforce it. |
| Agency statuses | `active`, `suspended` (operator), `closing` (30 days) and `closed`. Every existing check requires `active`. | Billing adds no agency status. It never suspends, closes or deletes an agency by itself (D5). |
| Closure and purge (017-A, 017-B) | The Owner's closure request, its cancellation and its completion. The guarded `purge_agency_batch` deletes every tenant table in a fixed order, and `test_ov09_function_covers_every_scoped_table` compares its list with every scoped table. Plan assignments stay after the purge "for 017-C billing". | Each new table is either deleted by the purge or kept as a financial record, and the function and its coverage test change with it (D10). |
| Agency-client revenue (015) | Paymob callbacks of each client's payment source, with sealed HMAC secrets, post revenue evidence to the ledger. | Platform billing has its own provider, route, tables and credentials. It never writes revenue evidence or the ledger. |
| Signed intake (015) | Gate (the setting is on and the provider rules are current), per-peer rate limits, the per-route body bound of `ROUTE_LIMITS`, the signature check, the record, then `200`. | The Paddle webhook follows the same order (D7). |
| Outbound calls | The live adapters use the standard library (`urllib`) and no HTTP client dependency (014 Meta, 011 YouTube, the Gmail sender). Tests run them against local synthetic servers. | The Paddle adapter does the same; no new dependency. |
| Provider rules (003) | `app/privacy/providers.py`: a live provider is usable only while its rules are current and within their review date. | A `paddle.billing` rule gates the adapter (D14). |
| Mail (002, 016-C) | Encrypted outbox, local `.eml` capture in development, link-only messages. | Two billing messages (D11). |
| Workers | One bounded pass per command; production scheduling belongs to 020. | `python -m app.billing_worker` (section 5.6). |
| Schema | 98 tables at `0033_agency_offboarding`; no billing table. | One additive migration, `0034_saas_billing` (D13). |

## 3. Provider research

**Method and limits.** The preparation environment could not open the providers' pages directly. The facts below come from web searches of the official pages, and third-party sources are named as such. Every fact that a decision relies on is listed in [section 7](#7-provider-facts-to-verify-in-phase-0) and must be checked against the official page in Phase 0; a fact that changes a decision goes back to the owner first.

### 3.1 Comparison

| Provider | Role | Fit for worldwide USD | A seller in Egypt | Costs (to verify) | Notes |
|---|---|---|---|---|---|
| **Paddle Billing** | Merchant of record | Yes. It collects and remits the tax of each buyer's country, issues invoices and runs the recovery of failed payments. | Accepted unless the country is on Paddle's unsupported list, which the official help page ties to sanctions and partner policies (V-1). | 5% + USD 0.50 per transaction according to third-party guides (V-2). Monthly payouts above USD 100 by wire or Payoneer (V-3). | Live approval needs a live HTTPS website with terms, a refund policy, a privacy policy and prices (V-14), so it waits for 020. |
| Stripe Billing | Payment processor | Yes, but the seller registers for and remits the taxes itself. | No: an Egyptian business cannot open an account (consistent third-party reports; V-16). | Lower processing fees. | Possible only through the foreign company, if its country is supported. |
| Stripe Managed Payments | Merchant of record | Yes | No: available since April 2026 to businesses in a limited list of locations (V-16). | A merchant-of-record fee on top of processing (V-16). | A later option for the foreign company. |
| Dodo Payments | Merchant of record | Yes | Reported as accepted (vendor sources). | 4% + USD 0.40, plus 1.5% for cards issued outside the United States and 0.5% for subscriptions (vendor sources). | A newer provider; most facts come from its own blog. |
| Paymob Subscriptions | Payment gateway | No: it charges in local currencies (EGP in Egypt), and the seller handles every tax. | Yes | Gateway fees | Stays the agency-client revenue provider of 015, separately. |
| Lemon Squeezy | Merchant of record | No | No | None | Closed to new sellers on 2026-11-16 and stops processing payments on 2027-03-31 (third-party reports). |

**Recommendation:** Paddle Billing (D2). Both of the owner's companies can sell through it, and it settles the worldwide tax and invoicing that a USD price list to agencies in many countries would otherwise require. The design keeps the provider behind an adapter, so a second provider (for example Stripe through the foreign company) can be added later without changing the standing, the plans or the routes.

### 3.2 Paddle facts that the design uses

- **Merchant of record.** Paddle is the legal seller to the buyer and handles tax and its remittance. The seller is paid out by Paddle.
- **Countries and currencies.** Paddle's country table lists Egypt with USD as its currency. Items can be priced in more than 30 currencies. The payout (balance) currencies include USD, EUR, GBP, AUD and CAD.
- **Subscription statuses.** `trialing`, `active`, `past_due`, `paused` and `canceled`. A cancellation or pause set for the next billing period creates a `scheduled_change`, and the status changes when it takes effect. Paddle's guidance is to keep access until a scheduled change takes effect and to revoke it at `canceled`.
- **Failed payments.** Since 2025 every Paddle Billing account retries a failed renewal automatically, up to seven times over 30 days, while the subscription is `past_due`. By default the subscription is then cancelled; the seller can choose to pause it or leave it past due instead. A cancelled subscription cannot be reinstated, so a returning customer subscribes again. A subscription cannot be changed while it is `past_due` or within 30 minutes of its next billing date.
- **Checkout.** The server creates a transaction for a price, with `custom_data`. Its checkout URL must be on an approved domain or the default payment link, or the transaction's ID is passed to Paddle.js to open the checkout. A separate transaction updates a subscription's payment method.
- **Webhooks.** Each notification carries a `Paddle-Signature` header with a timestamp and an HMAC-SHA256 of the timestamp and the raw body, keyed with the destination's secret. Paddle expects a `200` within 5 seconds, retries failures and does not guarantee the order of delivery. Each event has an `event_id` and an `occurred_at` time.
- **Account approval.** Sandbox accounts are approved at once. Live domains are reviewed. Payments must go through the seller's own website or app, not through checkout links sent to buyers. Software sold as a service is accepted; human services unrelated to software are not.

### 3.3 Buyers who pay from Egypt

Several Egyptian banks stopped debit and prepaid cards for payments abroad, except cards linked to a foreign-currency account (Banque Misr since October 2023; HSBC Egypt states the same). Each bank sets its own cap on foreign spending with credit cards, for example EGP 100,000 a month for most HSBC Egypt credit cards; a 2025 report says the Central Bank eased some limits since. An Egyptian agency therefore pays a USD subscription with a credit card, a foreign-currency card or another payment method that Paddle offers in Egypt (V-15). This does not block a worldwide USD price list. For a customer who pays by bank transfer, the operator's grant (D12) records a manually paid period without the provider.

### 3.4 Price benchmarks

These prices were observed on 2026-10-28 for the [market research](../../research_notes/market-and-feasibility/market.md). They are historical observations, not quotes, and they are not a price proposal.

| Product | Observed offer |
|---|---|
| AgencyAnalytics | USD 20 per client per month, billed annually |
| DashThis | USD 54 a month for 3 dashboards; USD 164 for 10 |
| WhatConverts (agency) | USD 500, 800 and 1,250 a month, plus usage |
| Whatagraph | From EUR 699 a month, billed annually |
| Metricool | From USD 20 a month, billed annually |
| VidWorth | USD 99 a month, or USD 69 a month billed annually |

## 4. Decisions for the owner

The recommendations are for synthetic data and disposable PostgreSQL. They are product and policy choices, not legal or tax advice. They leave Q-003, Q-004 and Q-012 open.

| ID | Recommended choice | Alternative and its effect |
|---|---|---|
| D1 Scope and delivery | 017-C has one provider-neutral billing core (prices, standing, trial, hold and the operator command) and one provider adapter, Paddle Billing, built against a synthetic Paddle-shaped API and signed webhook sender. Phases P0-P5 run on one branch, `codex/spec-017c-saas-billing`. Verified commits are pushed after each phase (D-051), and one pull request is opened for review. | Two slices: the core and manual billing first, the Paddle adapter later. Smaller, but the backend would still lack a payment path. |
| D2 Provider | Paddle Billing as merchant of record, with prices in USD. Either of the owner's companies may be the Paddle seller; the choice is made when the account is opened, not in code. Paymob stays the agency-client revenue provider of 015, separately. | Stripe Billing through the foreign company: lower fees, but that company must then register for and remit sales taxes in every buyer's country, and the Egyptian company cannot use it. |
| D3 Catalog and prices | A price is operator data. The operator creates it in Paddle and registers its Paddle price ID against an existing plan, with the amount in cents, the currency `USD` and the interval (`month` or `year`). A registered price is immutable: to change one, the operator registers a new price and stops offering the old one. Existing subscriptions keep their price until the Owner changes plan. No amount appears in code or in the migration; the owner sets the tiers and amounts before live use. | Prices set in code or in the migration: fewer steps, but every price change would need a release. |
| D4 Trial | 14 days from the agency's creation, without a card, on the default plan, once per agency. A reminder goes out 3 days before the end. Subscribing ends the trial at once. The trial runs only while billing is enabled: an agency created while it is disabled is complimentary. The operator may extend a trial. | A Paddle trial with a card at sign-up: fewer idle trials and automatic billing at the end, but every agency must enter a card before trying the product. |
| D5 Standing and its effects | Each agency has exactly one standing: `complimentary` (an operator grant, with an optional end date), `trialing`, `subscribed`, `past_due` or `hold`. The standing acts only through the plan: a trial has the default plan; `subscribed` and `past_due` have the plan of the subscribed price; `complimentary` keeps the plan the operator assigned; `hold` has the seeded `billing_hold` plan, whose clients, seats, connections and managed links are all zero, so every new creation is refused with `plan_limit_reached`. Nothing else stops on hold: sign-in, reads, reports, synchronization, redirects, collection, exports and the offboarding all continue, and no member or row is removed. A hold ends as soon as a subscription becomes active or the operator grants a period. Billing never suspends, closes or deletes an agency by itself; the operator command lists agencies on hold for more than 60 days, and the operator decides. While billing is disabled, the standing changes nothing. Agencies that exist at the migration are complimentary. | Suspend an agency automatically after a period on hold: it stops its clients' redirects and collection, which acceptance criterion 4 allows only under an agreed policy. |
| D6 Checkout | `POST /agencies/{a}/billing/checkout` with a price, for an active Owner of an active agency in a browser session. It is refused while the agency has a subscription that has not ended (`already_subscribed`; plan changes use D8). The server creates the Paddle transaction with the agency and the checkout in `custom_data` and the agency's Paddle customer, if any. Only one checkout per agency is open at a time, under the agency lock; a second request while it is open returns the same transaction. A checkout expires after 24 hours. The subscription is bound to the agency through the checkout's transaction ID, and `custom_data` is checked as well. The 018 frontend opens Paddle.js with the transaction ID. | Let the browser open Paddle.js with a price and the agency ID in `custom_data`: no server step, but the binding of the payment to the agency would then come from the browser. |
| D7 Webhook intake | `POST /billing/paddle/webhook` follows the 015 order: gate, per-peer rate limit, a 256 KiB body bound, then `Paddle-Signature` checked over the raw body in constant time, with the timestamp within 300 seconds. An invalid signature answers `401`. Each `event_id` is stored once with its type, time, IDs and outcome; a repeated delivery answers `200` and changes nothing. An event older than the last one applied to the same subscription or transaction is recorded as `stale` and not applied. Events are applied in the same request under the agency lock, with no outbound call, within Paddle's 5 seconds. An unknown subscription or transaction is recorded as `unmatched`, answers `200` and is listed for the operator. Only allowlisted fields are stored: IDs, statuses, amounts, the currency and times, never names, emails, addresses or card details. | Queue the events and apply them in the worker: more tolerant of load, but the standing would lag every payment by a worker interval. |
| D8 Plan changes | `POST /agencies/{a}/billing/change` with a price and an optional preview, for an active Owner while the subscription is `active`. An upgrade is charged at once with proration (`prorated_immediately`). A downgrade is credited on the next bill (`prorated_next_billing_period`). A switch between monthly and annual is charged at once. The preview returns Paddle's amounts without changing anything. The new limits apply when Paddle's `subscription.updated` event arrives, never from the route's own answer. A change is refused while the subscription is `past_due` or within 30 minutes of its renewal (`change_not_allowed`). A downgrade below current use removes nothing (017-A). | Apply every change at the next renewal (`full_next_billing_period`): simpler bills, but an upgrade would wait up to a full period. |
| D9 Cancellation and failed payments | The Owner cancels for the end of the paid period and may undo it before then. A failed renewal makes the subscription `past_due`: the agency keeps its plan while Paddle retries, up to seven times over 30 days with Paddle's default settings, and the Owner can update the card through Paddle's payment-method transaction. Paddle is configured to cancel after its last retry. A cancelled or paused subscription puts the agency on hold, and a resumed one restores it. Refunds and credits are made only by the operator in Paddle; they are recorded and change no standing. | Pause the subscription after the last retry instead of cancelling it: the customer can resume without a new checkout, but the agency stays tied to a subscription it no longer pays. |
| D10 Closure, suspension and purge | An Owner's closure request (017-A) schedules the subscription's cancellation at the end of the paid period. Cancelling the closure removes that cancellation, but not one that the Owner scheduled earlier. When the closure completes, a subscription that is still active is cancelled at once, without an automatic refund. These provider calls run in the billing worker as recorded actions, never inside the closure's own transaction. An operator suspension changes nothing in billing. The 017-B purge deletes the agency's standing, checkouts, events and pending actions, and keeps its subscriptions, payments and adjustments as financial records without personal data. The purge function and its coverage test change accordingly. | Cancel at once when the closure is requested: billing stops earlier, but a cancelled closure would then need a new checkout. |
| D11 Records, invoices and notifications | Payments and adjustments are recorded from Paddle's transaction and adjustment events: the Paddle IDs, the status, the currency and the subtotal, tax and total in cents. Active Owners and Admins read the standing, the subscription and the payment history; only Owners act. An invoice is fetched from Paddle when it is asked for and answered with a redirect to Paddle's temporary address, which is never stored or logged. Paddle sends the receipts, invoices and payment-failure messages as merchant of record. The platform sends two link-only messages to active Owners: `trial_ending` (3 days before the end) and `billing_hold` (when a hold starts). | Platform receipts as well: more control over their wording, but every buyer would receive two receipts. |
| D12 Operator command | `python -m app.agency_billing` runs as `tracking_app`, prints one JSON document and audits every change with `actor_kind = 'platform_operator'`. Every change needs `--confirm`. Subcommands: `prices`, `register-price`, `retire-price`, `status`, `grant --plan [--until]` (a complimentary period, for example a bank transfer or a partner), `end-grant`, `extend-trial`, `agencies --standing`, `events --unmatched`, `duplicates` and `reconcile`. The output carries IDs, keys, amounts, codes and times only, never a name, email, token or secret. | Manage billing only in Paddle's dashboard: no command, but the operator could not grant manually paid periods or see the platform's own state. |
| D13 Schema | One additive migration, `0034_saas_billing`, with eight tables: `billing_prices`, `agency_billing`, `agency_subscriptions`, `billing_checkouts`, `billing_events`, `billing_payments`, `billing_adjustments` and `billing_actions`. It also seeds the `billing_hold` plan, widens the plan assignment values to `assigned_by = 'billing'` with the reasons `subscription` and `billing_hold`, adds the billing audit actions, data policy rows and restricted grants, updates the purge function, and gives every existing agency a `complimentary` standing. It is tested on disposable PostgreSQL only, and the downgrade refuses stored rows. | Keep the standing as columns on `agencies`: fewer tables, but every agency query and the 017-B purge would carry billing state. |
| D14 Boundaries and evidence | Backend only, synthetic data, disposable PostgreSQL, no new dependency and no live Paddle call. Billing is off by default. The Paddle API key and webhook secret are kept only in the ignored `.env`. The `paddle.billing` provider rule gates the adapter. The [verification matrix](#6-verification-matrix) BL01-BL23 is executed with the existing suites, every new safeguard is shown to fail its test when disabled, and the completed branch is presented for independent review in its pull request. | Test against a Paddle sandbox account now: closer to production, but it needs an owner account, live keys in the environment and outbound access, which are an owner-operated check after the merge. |

## 5. Design for implementation after approval

The design note of P0 (`design-017c.md`) fixes the exact statements, payload fields, answers and tests. It follows these lines.

### 5.1 Schema (`0034_saas_billing`, after `0033_agency_offboarding`)

- **`billing_prices`:** the plan, the provider (`paddle`), the provider's price ID (unique per provider), the currency (`USD` only), the amount in cents (positive), the interval (`month` or `year`), whether it is offered, and the registration and retirement times. Immutable apart from `offered` and the retirement time.
- **`agency_billing`:** one row per agency. It holds the standing, its reason, the trial end and the time of its reminder, the grant's end, the start of the hold, the agency's Paddle customer ID and a version.
- **`agency_subscriptions`:** the agency, the provider's subscription ID (unique), the price, the provider's status, the current period's start and end, the scheduled action (`cancel` or `pause`) and its time, the cancellation time, a duplicate flag, the `occurred_at` of the last applied event and the time of the last reconciliation.
- **`billing_checkouts`:** the agency, the price, the requesting membership, the provider's transaction ID (unique), the status (`open`, `completed` or `expired`), and the creation, expiry and completion times. A partial unique index allows one `open` checkout per agency.
- **`billing_events`:** the provider and its event ID (unique together), the type, `occurred_at`, the receipt time, the agency and subscription when known, the outcome (`applied`, `stale`, `ignored` or `unmatched`), an error code and the allowlisted fields (JSONB).
- **`billing_payments`:** the agency, the subscription, the provider's transaction ID (unique), the status, the origin, the currency, the subtotal, tax and total in cents, the billing time and the invoice number.
- **`billing_adjustments`:** the payment, the provider's adjustment ID (unique), the action (refund, credit or chargeback), the status, the currency and the total in cents.
- **`billing_actions`:** the agency, the subscription, the action (`cancel_next_period`, `cancel_now` or `remove_scheduled_cancel`), the reason (`closure_requested`, `closure_cancelled` or `closure_completed`), the status (`pending`, `done`, `failed` or `skipped`), the attempts, the next attempt and the last error code.
- **Changes:**
  - the seeded `billing_hold` plan (zero clients, seats, connections and managed links; a tracked-event allowance of zero, which is soft);
  - `agency_plan_assignments`: `assigned_by` adds `billing`, and the reasons add `subscription` and `billing_hold`;
  - audit actions for prices, grants, trials, checkouts, plan changes and cancellations;
  - a `complimentary` standing for every existing agency (reason `migration`);
  - grants: `tracking_app` reads and writes the billing tables and deletes none of them; `tracking_lifecycle` deletes `billing_events` past their retention and expired checkouts;
  - the purge function and its table lists (D10).

### 5.2 Standing and plans

| From | Event | To | Plan assignment |
|---|---|---|---|
| (new agency, billing enabled) | creation | `trialing`, trial end = creation + 14 days | the default plan (as today) |
| (new agency, billing disabled) | creation | `complimentary` (reason `billing_disabled`) | the default plan |
| `trialing` | trial end without a subscription (worker) | `hold` | `billing_hold` |
| `trialing`, `hold` | subscription `active` | `subscribed` | the subscribed price's plan, reason `subscription` |
| `subscribed` | `subscription.updated` with another price | `subscribed` | the new price's plan |
| `subscribed` | `subscription.past_due` | `past_due` | unchanged |
| `past_due` | payment recovered (`active`) | `subscribed` | unchanged |
| `subscribed`, `past_due` | `subscription.canceled` or `subscription.paused` | `hold` | `billing_hold` |
| any | operator grant | `complimentary` until the grant's end | the operator's plan |
| `complimentary` with an end | grant end without a subscription (worker) | `hold` | `billing_hold` |

Every transition runs under the agency lock and writes its plan assignment in the same transaction. An event for a subscription flagged as a duplicate changes no standing.

### 5.3 Routes

| Route | Who | Effect |
|---|---|---|
| `GET /billing/prices` | any signed-in user | The offered prices with their plan's key, name and limits, the amount, the currency and the interval, and the Paddle environment and client token that Paddle.js needs. |
| `GET /agencies/{a}/billing` | active Owners and Admins | The standing, the trial end, the plan, the subscription's price, status, period end and scheduled change, and the last payment's status. Never card details, provider secrets or customer contact data. |
| `POST /agencies/{a}/billing/checkout` | active Owners | D6. |
| `POST /agencies/{a}/billing/change` | active Owners | D8, with `preview`. |
| `POST` and `DELETE /agencies/{a}/billing/cancel` | active Owners | D9: schedule or undo the cancellation at the period end. |
| `POST /agencies/{a}/billing/payment-method` | active Owners | Paddle's payment-method transaction ID for Paddle.js. |
| `GET /agencies/{a}/billing/payments` | active Owners and Admins | The payment history, paged. |
| `GET /agencies/{a}/billing/payments/{p}/invoice` | active Owners and Admins | A `302` redirect to Paddle's temporary invoice address, fetched at request time. |
| `POST /billing/paddle/webhook` | Paddle | D7. |

Every write route needs a browser session with the CSRF token, and an active agency. Client viewers, other agencies and every bearer key are refused. A provider failure on a user request answers `503 billing_provider_unavailable` and changes nothing.

### 5.4 Webhook processing

- **Subscription events** (`created`, `activated`, `updated`, `trialing`, `past_due`, `paused`, `resumed`, `canceled`): bind to the agency through the checkout's transaction ID or a stored subscription. Store the subscription's state, and apply section 5.2.
- **Transaction events** (`completed`, `paid`, `payment_failed`): record or update the payment, and complete the matching checkout.
- **Adjustment events** (`created`, `updated`): record the adjustment.
- **Any other type:** recorded as `ignored`.
- **Order:** an event is applied only if its `occurred_at` is later than that of the last event applied to the same entity.

### 5.5 Paddle adapter

- **Calls:**
  - create a transaction;
  - get a subscription;
  - preview an update, and update one;
  - cancel, and remove a scheduled change;
  - get the payment-method transaction;
  - get an invoice;
  - get a price, when it is registered.
- **Transport:** `urllib` with a 10-second timeout, a bounded response size, the API key as a bearer token and the API version header that P0 confirms. The sandbox or live base address is chosen by a setting.
- **Errors:** they map to closed codes. A synthetic Paddle-shaped server in the tests implements the same calls and signs the webhook events that it sends.

### 5.6 Billing worker

`python -m app.billing_worker` runs one bounded pass as `tracking_app`:
1. Trial reminders, the end of trials and the end of grants.
2. Pending provider actions (D10), with bounded retries.
3. Reconciliation: it reads each subscription that has not ended and was not reconciled in the last 24 hours, in a bounded batch, and applies any difference as an event with its outcome.
4. The two messages of D11.

The lifecycle runner deletes `billing_events` older than 13 months (provisional, Q-012) and expired checkouts older than 30 days. Production scheduling belongs to 020.

### 5.7 Settings

All new settings are off or blank by default:
- `TRACKING_BILLING_ENABLED=false`;
- `TRACKING_BILLING_TRIAL_DAYS=14` (1 to 30);
- `TRACKING_BILLING_PADDLE_ENVIRONMENT=sandbox` (`sandbox` or `live`);
- `TRACKING_BILLING_PADDLE_API_KEY`, `TRACKING_BILLING_PADDLE_WEBHOOK_SECRET` and `TRACKING_BILLING_PADDLE_CLIENT_TOKEN`.

When billing is enabled, the API key and the webhook secret are required. The secrets never appear in a log, an error or an answer.

## 6. Verification matrix

| Case | Required observable evidence |
|---|---|
| BL01 Prices | `register-price` and `retire-price` with `--confirm`; only `USD`, `month` and `year`; a registered price cannot change; `GET /billing/prices` lists offered prices only. |
| BL02 Trial | With billing enabled, a new agency is `trialing` for 14 days on the default plan; with billing disabled it is `complimentary`; after the migration, existing agencies are `complimentary`. |
| BL03 Trial end | The reminder is sent once, 3 days before the end; at the end without a subscription the agency is on hold and the `billing_hold` message is sent. |
| BL04 Hold | New clients, seats, connections and links are refused with `plan_limit_reached`. Sign-in, reads, reports, synchronization, redirects, collection and exports still work, and no row is removed. |
| BL05 Checkout | Only an active Owner of an active agency; Admins, Analysts, client viewers and keys are refused. One open checkout per agency under concurrent requests; a second request returns the same transaction; `already_subscribed` while a subscription has not ended. |
| BL06 Signature | A valid signature is accepted. A wrong secret, a changed body, an old timestamp or a missing header answers `401`; a body over the bound answers `413`; the rate limit applies. |
| BL07 Idempotency and order | The same event twice has one effect. An older event after a newer one is `stale` and changes nothing. |
| BL08 Activation | An active subscription makes the agency `subscribed` with the plan of its price, and ends a hold or a trial at once. |
| BL09 Plan changes | Upgrades and downgrades send their proration modes to the synthetic Paddle; the preview changes nothing; the limits follow the `subscription.updated` event only; `change_not_allowed` while `past_due`. |
| BL10 Failed payments | `past_due` keeps the plan; a recovered payment restores `subscribed`; a cancellation after the last retry puts the agency on hold. |
| BL11 Cancellation | Cancel at the period end and undo; the effective cancellation puts the agency on hold; the Owner can subscribe again from hold. |
| BL12 Records | Payments and adjustments are stored with their amounts, tax and currency; a refund is recorded and changes no standing. |
| BL13 Invoice | Owners and Admins are redirected to the address fetched at request time; it is never stored or logged. |
| BL14 Closure | A closure request queues the cancellation at the period end and the worker executes it; a cancelled closure removes it but keeps an Owner's earlier cancellation; the completion cancels at once. |
| BL15 Purge | After the 017-B purge, no standing, checkout, event or action of the agency remains; its subscriptions, payments and adjustments stay; the function's coverage test lists both groups. |
| BL16 Unmatched and duplicates | Unmatched events and duplicate subscriptions are listed by the command; nothing is cancelled automatically. |
| BL17 Reconciliation | A missed event is corrected by the worker's reconciliation in a bounded batch, with its recorded outcome. |
| BL18 Operator command | Every subcommand; `--confirm` is required for changes; audit rows; JSON without a name, email or secret. |
| BL19 Separation | No billing path writes revenue evidence, the ledger or a 015 payment source, and the 015 routes behave as before. |
| BL20 Isolation | Another agency's standing, plan and records never change. |
| BL21 Migration | Upgrade from a populated `0033`: the `billing_hold` plan, complimentary standings, grants and data policy rows as D13 states; the downgrade refuses stored rows. |
| BL22 Secrets and logs | No API key, webhook secret, signature, email, name, card detail or invoice address appears in a log line, an answer, the worker's output or the command's output; enabling billing without the key or the secret fails at startup. |
| BL23 Existing behavior | Every existing suite passes, and the OpenAPI snapshot has additions only. |

## 7. Provider facts to verify in Phase 0

Each fact is checked against Paddle's official page (developer.paddle.com or paddle.com) and recorded with its address and date. A fact that differs and changes a decision goes back to the owner before code depends on it.

| ID | Fact | Decisions |
|---|---|---|
| V-1 | Egypt, and the country of the owner's foreign company, are not on Paddle's list of unsupported seller countries. | D2 |
| V-2 | The standard fee and any surcharge (international cards, subscriptions, currency conversion). | D2 |
| V-3 | Payout methods, frequency, minimum and currencies. | D2 |
| V-4 | The `Paddle-Signature` format: the timestamp and `h1` fields, the signed string, the destination secret and its rotation. | D7 |
| V-5 | Delivery: the 5-second answer, the retry schedule, the absence of ordering, the uniqueness of `event_id` and the meaning of `occurred_at`. | D7 |
| V-6 | The subscription, transaction and adjustment event types and the fields used; whether a transaction's `custom_data` is copied to the subscription created from it. | D6, D7 |
| V-7 | Creating a transaction for a price with `custom_data` and a customer; opening Paddle.js with a transaction ID; approved domains and the default payment link. | D6 |
| V-8 | Updating a subscription's items with `proration_billing_mode`, the allowed values, and the preview. | D8 |
| V-9 | Cancelling at the next billing period, cancelling at once, and removing a scheduled change. | D9, D10 |
| V-10 | The payment-method update transaction. | D9 |
| V-11 | The invoice endpoint and the lifetime of its address. | D11 |
| V-12 | The sandbox and live base addresses, the API key format, the authentication header and the version header. | D14 |
| V-13 | The recovery settings: the default retries and the action after the last retry (cancel, pause or stay past due). | D9 |
| V-14 | The website and domain review requirements for a live account. | Owner inputs |
| V-15 | The payment methods offered to buyers in Egypt, and whether USD is the checkout currency for every country. | D2, D3 |
| V-16 | Stripe's availability for Egyptian businesses and the business locations of Stripe Managed Payments (alternatives only). | D2 |

## 8. Owner inputs before live use

None of these blocks the implementation, which uses synthetic data:
- **The seller.** Which of the two companies opens the Paddle account, and its USD bank account or Payoneer account for payouts (V-1, V-3).
- **The catalog.** The tiers (017-A plans with their limits) and their monthly and annual amounts in USD (D3).
- **Policies.** The refund policy, and the published Terms of Service and Privacy Policy, whose agreement versions 017-A already records. Paddle's review requires all three on the website (V-14).
- **Hosting.** A live HTTPS website and webhook address (020).
- **The live check.** An owner-operated check with a Paddle sandbox account after the merge.

## 9. What remains after 017-C

- **The frontend (018):** the prices, checkout, billing and invoice pages, with Paddle.js loaded as Paddle documents; that frontend dependency is decided in 018.
- **020:** hosting, the webhook address over HTTPS, the worker schedule and the live keys.
- **The live check** with a Paddle sandbox account and then the live account approval.
- **Later options:** a second provider, for example Stripe through the foreign company, behind the same adapter; usage-based prices; and an automatic policy for agencies that stay on hold.

## Sources

Official Paddle pages, as found by the searches of 2026-11-28 (to be read again in Phase 0):
- [Supported countries](https://developer.paddle.com/concepts/sell/supported-countries-locales) and [supported currencies](https://developer.paddle.com/concepts/sell/supported-currencies)
- [Intro to Paddle (help center, unsupported seller countries)](https://www.paddle.com/help/start/intro-to-paddle)
- [What you cannot sell](https://www.paddle.com/help/start/intro-to-paddle/what-am-i-not-allowed-to-sell-on-paddle) and [domain review](https://www.paddle.com/help/start/account-verification/what-is-domain-verification)
- [Provision access and handle subscription state](https://developer.paddle.com/build/subscriptions/provision-access-webhooks/), [cancel subscriptions](https://developer.paddle.com/build/subscriptions/cancel-subscriptions/) and [pause a subscription](https://developer.paddle.com/api-reference/subscriptions/pause-subscription/)
- [Payment recovery and dunning](https://developer.paddle.com/build/lifecycle/subscription-renewal-dunning) and [default payment retries (2025)](https://developer.paddle.com/changelog/2025/default-dunning-payment-recovery/)
- [Create a transaction](https://developer.paddle.com/api-reference/transactions/create-transaction/) and [payment-method update transaction](https://developer.paddle.com/api-reference/subscriptions/get-subscription-update-payment-method-transaction/)
- [Respond to webhooks](https://developer.paddle.com/webhooks/about/respond-to-webhooks)

Other sources (third-party, used only where marked):
- Paddle fees and payouts: [agentaos.ai](https://agentaos.ai/answers/paddle-fees), [cfopresso.com](https://cfopresso.com/blog/paddle-pricing)
- Paddle webhooks in production: [hookdeck.com](https://hookdeck.com/webhooks/paddle/guide-duplicates-ordering-retries-timeouts)
- Stripe and Egypt: [startglobal.co](https://startglobal.co/us/international/egypt/stripe/); Stripe Managed Payments: [Stripe changelog, 2026-04-22](https://docs.stripe.com/changelog/dahlia/2026-04-22/managed-payments)
- Lemon Squeezy closure: [checkoutpage.com](https://checkoutpage.com/blog/lemon-squeezy-shutting-down)
- Dodo Payments fees: [tiun.io](https://tiun.io/blog/merchant-of-record-fees-2026)
- Paymob subscriptions: [developers.paymob.com](https://developers.paymob.com/paymob-docs/developers/subscription/create-subscription-plan)
- Egyptian card limits: [HSBC Egypt](https://www.hsbc.com.eg/credit-cards/foreign-usage-limits/), [Banque Misr](https://www.banquemisr.com/-/media/Usage-limits-and-fees/Usage-limits-and-Fees-EN.ashx)
