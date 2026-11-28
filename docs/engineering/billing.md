# Platform billing
Specification 017-C under D-103: agencies pay for the platform through Paddle Billing as merchant of record, with prices in USD that the platform operator registers against the 017-A plans, monthly or annual. A new agency has a 14-day trial without a card; an agency whose trial, grant or subscription has ended goes on hold, which refuses new clients, members, connections and links and stops nothing else. Status: implemented and tested on the disposable database against a synthetic Paddle-shaped server; no live Paddle call has been made. Native `tracking_sys` rollout of `0034_saas_billing`, the Paddle account and its sandbox check, and the prices need their own owner decisions. See the [entry review](../../specs/017-saas-lifecycle/entry-review-017c.md), the [design note](../../specs/017-saas-lifecycle/design-017c.md) and the [evidence](../../specs/017-saas-lifecycle/evidence-017c.md), and the [plans and closure guide](plans-and-closure.md) for plans and limits.

Platform billing is separate from agency-client revenue (015): it has its own provider, routes, tables and credentials, and it never writes revenue evidence, the ledger or a Paymob source.

## Settings
Billing is off by default. While it is off, every new agency is complimentary on the default plan, exactly as before, and the billing routes, the webhook, the worker and the operator's changes answer that billing is unavailable.

| Setting | Default | Rule |
|---|---|---|
| `TRACKING_BILLING_ENABLED` | `false` | When true, the API key and the webhook secret are required at startup. |
| `TRACKING_BILLING_TRIAL_DAYS` | `14` | 1 to 30. |
| `TRACKING_BILLING_PADDLE_ENVIRONMENT` | `sandbox` | `sandbox` or `live`. |
| `TRACKING_BILLING_PADDLE_API_KEY` | blank | Paddle's API key of the same environment (`pdl_sdbx_apikey_...` or `pdl_live_apikey_...`). |
| `TRACKING_BILLING_PADDLE_WEBHOOK_SECRET` | blank | The notification destination's secret key (`pdl_ntfset_...`). |
| `TRACKING_BILLING_PADDLE_CLIENT_TOKEN` | blank | Optional, public, for Paddle.js (`test_...` for the sandbox, `live_...` for live). |

Keep the key and the secret only in the ignored `.env`. Billing also needs the `paddle.billing` provider rule to be current (verified 2026-11-28, review due 2027-11-28). Paddle's API keys expire after 90 days by default, so the key must be rotated before then (020).

## Standing
Every agency has one standing in `agency_billing`, and the standing acts only through the agency's plan assignments:

| Standing | Plan | How it starts |
|---|---|---|
| `trialing` | the default plan | a new agency while billing is allowed |
| `subscribed` | the plan of the subscribed price | the subscription becomes `active` (or `trialing` at Paddle) |
| `past_due` | unchanged | a renewal failed; Paddle retries |
| `hold` | `billing_hold` (zero clients, seats, connections and managed links) | the trial or a grant ended without a subscription, or the subscription was canceled or paused |
| `complimentary` | the operator's plan, or the current plan | existing agencies at the migration, new agencies while billing is disabled, and operator grants |

On hold, the 017-A plan checks refuse every new client, invitation, connection and managed link with `plan_limit_reached`. Sign-in, reads, reports, exports, synchronization, redirects, collection, erasure and the offboarding all go on, and nothing is deleted. A hold ends when a subscription becomes active or the operator grants a period. Billing never suspends, closes or deletes an agency by itself; the operator lists long holds (`agencies --held-days 60`) and decides.

An operator grant wins over the subscription until it ends. An event of a duplicate subscription changes no standing, and a closed agency's standing never changes. Disabling billing after it was enabled freezes every standing: an agency on hold keeps the hold plan until the operator grants it a period after billing is enabled again, or assigns a plan with `app.agency_plans`.

## Prices
```
python -m app.agency_billing register-price --plan K --price-id pri_... --amount-cents N --interval month --confirm
python -m app.agency_billing register-price --plan K --price-id pri_... --amount-cents N --interval month --replaces pri_... --confirm
python -m app.agency_billing retire-price --price-id pri_... --confirm
python -m app.agency_billing prices
```
The operator creates the price in Paddle first. Registration reads it from Paddle, which must report it active, in USD, of the same amount and with a one-month or one-year cycle (`price_mismatch` with the field otherwise). A plan has at most one offered monthly and one offered annual price; `--replaces` retires the offered one in the same transaction. A registered price never changes; existing subscriptions keep their price until the Owner changes plan. The `billing_hold` plan cannot be priced, made the default or assigned by `app.agency_plans` (`reserved_plan`). Turn off Paddle's automatic currency conversion if checkouts must stay in USD for every buyer.

## Routes
Browser sessions only; writes need the CSRF token. Owners act, Owners and Admins read, in an active agency.

| Route | Who | Answer |
|---|---|---|
| `GET /billing/prices` | any signed-in user | the offered prices with their plans and limits, the Paddle environment and the client token |
| `GET /agencies/{a}/billing` | Owners, Admins | the standing, the plan, the subscription and the last payment |
| `POST /agencies/{a}/billing/checkout` `{price_id}` | Owners | 201 with the transaction ID for Paddle.js, or 200 with the open checkout of the same price; 409 `already_subscribed`, `price_not_offered` |
| `POST /agencies/{a}/billing/change` `{price_id, preview}` | Owners | the preview's amounts, or 202 when requested; 409 `change_not_allowed`, `same_price`, `not_subscribed` |
| `POST` / `DELETE /agencies/{a}/billing/cancel` | Owners | the scheduled cancellation at the period end, or its undo; 409 `no_scheduled_cancel` |
| `POST /agencies/{a}/billing/payment-method` | Owners | the payment-method transaction ID for Paddle.js |
| `GET /agencies/{a}/billing/payments` | Owners, Admins | the payment history, newest first |
| `GET /agencies/{a}/billing/payments/{p}/invoice` | Owners, Admins | 302 to Paddle's invoice address (valid for an hour, never stored); 409 `invoice_unavailable` |

A checkout lives 24 hours; one is open per agency, and another price replaces it. An upgrade is charged at once with proration; a downgrade of the same interval is credited on the next bill; monthly to annual is charged at once. The new limits apply when Paddle's `subscription.updated` arrives, never from the route's answer. Changes are refused while the subscription is past due, has a scheduled change or renews within 30 minutes. A Paddle failure answers 503 `billing_provider_unavailable` and changes nothing. While billing is disabled, every route answers 503 `billing_unavailable`.

## Webhook
Configure a Paddle notification destination for `subscription.*`, `transaction.completed`, `transaction.paid`, `transaction.payment_failed` and `adjustment.*` at `POST /billing/paddle/webhook` over HTTPS (020). The route checks, in order: billing is allowed (503), the per-peer rate (429), a body of at most 256 KiB (413), `Paddle-Signature` over the raw body with its timestamp within 300 seconds (401), and the event envelope (400). Every verified event answers 200.

Each event ID is stored once in `billing_events`, with its type, times, outcome and allowlisted fields (IDs, statuses, amounts, currencies and times). Outcomes: `applied`; `stale` (older than the last event applied to the same subscription, payment or adjustment); `ignored` (another type, or a field that fails validation); `unmatched` (no known subscription, payment or checkout). A subscription is bound to its agency only through the checkout's transaction ID, which `subscription.created` carries; `custom_data` must agree (`binding_conflict` otherwise). Earlier events of a subscription that arrive before it is bound are applied at binding. A second live subscription of an agency is flagged a duplicate. Payments and adjustments are recorded and change no standing.

## Worker
`python -m app.billing_worker [--limit N]` runs one bounded pass as `tracking_app`: trial and grant ends, the closures' provider actions, the reconciliation of subscriptions not read from Paddle for 24 hours, and the `trial_ending` (3 days before the end) and `billing_hold` messages to the agency's active, verified Owners, link-only, delivered by `python -m app.mail_worker`. Each step selects only the agencies it can change: closed agencies are not selected for the end of trials and grants, and only active agencies for the messages, so a suspended or closing agency on hold is notified once it is active again. A failed Paddle read counts as the subscription's reconciliation attempt and is read again after 24 hours, so it never holds back the others. It prints counts only, and `{"status": "disabled"}` while billing is not allowed. Production scheduling belongs to 020.

## Closure and purge
An agency closure never calls Paddle in its own transaction. The closure request schedules each subscription's cancellation at the period end (an Owner's own earlier cancellation is kept); cancelling the closure removes the closure's cancellation; the completion cancels every subscription that has not ended at once, without a refund. The worker executes these actions one per subscription at a time, retrying after 5 to 320 minutes; the eighth failure is `failed` and the operator cancels in Paddle. The 017-B purge waits while an action is pending, deletes the agency's standing, checkouts, events and actions, and keeps its subscriptions, payments and adjustments as financial records without personal data. The offboarding export does not include platform billing.

## Operator command
```
python -m app.agency_billing status --agency <uuid>
python -m app.agency_billing grant --agency <uuid> --plan K [--until 2027-01-31T00:00:00+00:00] --confirm
python -m app.agency_billing end-grant --agency <uuid> --confirm
python -m app.agency_billing extend-trial --agency <uuid> --days 7 --confirm
python -m app.agency_billing agencies [--standing hold] [--held-days 60]
python -m app.agency_billing events --unmatched [--limit 100]
python -m app.agency_billing duplicates
python -m app.agency_billing reconcile [--agency <uuid>] --confirm
```
A grant records a manually paid period (for example a bank transfer) or a partner. Every change needs `--confirm` and allowed billing, and is audited with `actor_kind = 'platform_operator'`. The output carries IDs, keys, amounts, codes and times only.

## Retention
The lifecycle runner deletes billing events 395 days after receipt (`TRACKING_BILLING_EVENT_RETENTION_DAYS`, at most 395, provisional under Q-012) and open or expired checkouts 30 days after their expiry (`TRACKING_BILLING_CHECKOUT_RETENTION_DAYS`, at most 30). See the [data lifecycle runner](data-lifecycle.md).

## Before live use
The owner decides the tiers and amounts in USD, opens the Paddle account (either company), turns off automatic currency conversion if checkouts must stay in USD, configures the payment recovery to cancel after the last retry, and publishes the terms, refund and privacy pages that Paddle's domain review requires. Hosting, the HTTPS webhook address, the worker schedule, key rotation and the live keys belong to 020; the 018 frontend opens Paddle.js with the transaction IDs. Paddle runs no automatic payment retries in the sandbox, so the sandbox check covers the recovery path with simulated events.

## Tests
`backend/tests/test_billing_paddle.py`, `test_billing_webhook_contract.py` and `test_billing_command_parser.py`; `backend/tests/integration/test_billing_migration.py`, `test_billing_standing.py`, `test_billing_command.py`, `test_billing_webhook.py` and `test_billing_owner.py`, with `billing_support.py` and the synthetic server `backend/tests/paddle_api.py`.
