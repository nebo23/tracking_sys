# Spec 017-C evidence: subscription billing, prices and the trial

Prepared: 2026-11-28 under D-103. Branch: `codex/spec-017c-saas-billing`, created from `origin/claude/keen-fermat-otlr9d` at `72552f0`; merged `main` at `04dc323` (PR 21) is an ancestor and did not move. Scope: the [entry review](entry-review-017c.md) (D1-D14, approved without amendment), the [implementation handoff](implementation-prompt-017c.md) and the [design note](design-017c.md). Pull request: [PR 22](https://github.com/nebo23/tracking_sys/pull/22) against `main`, opened at `bd2deaf`. Synthetic data, the disposable PostgreSQL service and a synthetic Paddle-shaped server only; native `tracking_sys` was never used, no Paddle account was touched and no live Paddle call was made.

## 1. Commits

| Phase | Commit | Content |
|---|---|---|
| P0 | `bd8c4ef` | Design note: the provider facts V-1 to V-16 with their addresses, the DDL of `0034`, the transitions, event mapping, adapter, routes, worker, command, settings and the test inventory |
| P1 | `5e3f124` | Migration `0034_saas_billing` and its models, the seeded `billing_hold` plan, the widened assignment, audit and mail values, the new `purge_agency_batch`, the data policy rows; BL21 and the schema half of BL15 |
| P2 | `ad55f49` | The standing service and its hook in `create_agency`, `python -m app.billing_worker` (trials, grants, messages), `python -m app.agency_billing` (prices, registration, retirement, status, grants, trial extension, standings), the settings and the `paddle.billing` rule; BL01-BL04, BL18 for these subcommands, BL20 and the settings part of BL22 |
| P3 | `111b660` | The complete Paddle adapter, `POST /billing/paddle/webhook`, the event processing and records, the `events` and `duplicates` subcommands, the log events, the OpenAPI snapshot; `0034` amended in place for the binding of unmatched events; BL06-BL08, BL10, BL12, BL16, BL19 and the log part of BL22 |
| P4 | `f429369` | The Owner routes, the closure actions and the worker's action and reconciliation steps, the `reconcile` subcommand, the retention of events and checkouts, the journey and the OpenAPI snapshot; BL05, BL09, BL11, BL13-BL15, BL17, BL23 |
| P5 | `bd2deaf` and the next | Two tests corrected during the final verification and the mutation check, the evidence, the billing guide, the status lines; then the pull request number |

## 2. Environment and deviation

- **Database.** The disposable PostgreSQL 18 service of `backend/tests/README.md` (Compose project `tracking-system-foundation-test`, database `tracking_foundation_test`, synthetic credentials kept in the session's scratch directory). It was recreated empty (`down -v`, `up -d --wait database`) before the final run, so every migration ran from an empty schema.
- **Port.** Windows reserves the TCP range 55365-55464 on this workstation (`netsh interface ipv4 show excludedportrange protocol=tcp`; a Python `socket.bind` on 127.0.0.1:55433 failed with error 13). As the owner chose for 017-B the same day, the service ran on 127.0.0.1:56433, and the test runner patched the integration guard's port only for the duration of each pytest run and restored the file byte for byte (SHA-256 `580aeffd18512c7debd31fd947cf6d8e7f8d93015b62d623774b8b479b6fbec7` checked after every run). The committed guard says 55433; no commit contains 56433.
- **Tools.** Python 3.12.4 in the repository's `.venv` (`pip check`: no broken requirements), ruff 0.17.3, Node.js 24.17.0. The tracker's Playwright browsers (Chromium 1248, Firefox 1555) were reused through a junction to an earlier worktree's installed `packages/tracker-js/node_modules`, which is ignored by Git; the tracker package is unchanged.
- **Frontend.** `frontend/` holds only the placeholder README files, so the frontend checks of P5 did not apply.

## 3. Verification

| Check | Command (from `backend/` unless stated) | Result |
|---|---|---|
| Lint | `ruff check app tests migrations` | All checks passed |
| Format | `ruff format --check app tests migrations` | 360 files already formatted |
| Unit | `pytest -m "not integration" -q` | 1030 passed, 864 deselected |
| Integration | `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1`, in 15 batches (below) | 857 passed, 7 skipped, 0 failed (864 cases) |
| Tracker unit | `node --test test/unit/*.test.js` (from `packages/tracker-js`) | 73 passed |
| Tracker browser | `node --test --test-concurrency=1 test/browser/*.test.js` | 50 passed (Chromium and Firefox) |
| Dependencies | `pip check` | No broken requirements found |
| Whitespace | `git diff --check origin/main...HEAD`, and the working tree | clean |
| Links | relative links of the changed Markdown | 424 local targets in the 19 Markdown files that differ from `main`, none missing |
| Contract | regenerated `contracts/openapi.json`, semantic diff against `main` | 9 paths and 20 schemas added, nothing changed or removed; 150 paths and 185 operations |

The seven skipped cases are the opt-in measurements that need `TRACKING_REPORT_MEASURE`, `TRACKING_ATTRIBUTION_MEASURE` or `TRACKING_REVIEW_MEASURE`, the same seven that 017-B recorded.

| Batch | First module | Modules | Result | Time |
|---|---|---|---|---|
| 1 | `test_access_api.py` | 5 | 69 passed | 89 s |
| 2 | `test_agency_closure_stops.py` | 8 | 70 passed | 172 s |
| 3 | `test_attribution_models.py` | 5 | 58 passed, 6 skipped | 160 s |
| 4 | `test_auth.py` | 4 | 60 passed | 43 s |
| 5 | `test_billing_owner.py` | 4 | 48 passed | 156 s |
| 6 | `test_collection.py` | 4 | 62 passed | 97 s |
| 7 | `test_connector_sync.py` | 5 | 56 passed | 122 s |
| 8 | `test_conversion_delivery.py` | 6 | 65 passed | 99 s |
| 9 | `test_identity.py` | 8 | 53 passed | 107 s |
| 10 | `test_lifecycle.py` | 9 | 70 passed | 150 s |
| 11 | `test_report_exports.py` | 3 | 47 passed | 109 s |
| 12 | `test_reports.py` | 5 | 61 passed | 111 s |
| 13 | `test_review_001_015.py` | 5 | 63 passed, 1 skipped (rerun) | 151 s |
| 14 | `test_tenancy.py` | 3 | 61 passed | 37 s |
| 15 | `test_whatsapp.py` | 1 | 14 passed | 50 s |

Batch 13 first ended with 1 failed, 62 passed and 1 skipped: `test_saas_plans.py::test_sv08_operator_command_runs_as_its_own_process` expected the two seeded plans in creation order, but on a database migrated in one transaction both share one creation time and the listing orders them by key. The assertion became order-independent, the module passed (19 cases), and the whole batch was rerun with the result above. After the mutation check corrected BL19 (section 6), `test_billing_webhook.py` was rerun: 8 passed.

## 4. Provider facts (V-1 to V-16)

Read on 2026-11-28 on the official pages; the full record with every address is [section 2 of the design note](design-017c.md#2-provider-facts-v-1-to-v-16).

| ID | Result | Official source (excerpt) |
|---|---|---|
| V-1 | Egypt is not on Paddle's list of unsupported seller countries; the list may change. | paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle |
| V-2 | 5% + USD 0.50 per checkout transaction, no monthly fee; up to 1.5% conversion margin on payouts in another currency. | paddle.com/pricing |
| V-3 | Wire or Payoneer, monthly, from USD 100; balances in USD, EUR, GBP, AUD or CAD. | paddle.com/help/manage/get-paid/when-and-how-do-i-get-paid |
| V-4 | `ts=...;h1=...`, HMAC-SHA256 of `ts:body` under the destination secret; several `h1` during a rotation; SDK tolerance five seconds, check optional. | developer.paddle.com/webhooks/signature-verification |
| V-5 | 200 within five seconds; 3 attempts in sandbox, up to 60 over two days live; no ordering; `event_id` for deduplication. | developer.paddle.com/webhooks/respond-to-webhooks |
| V-6 | Event types and fields as used; `transaction_id` only on `subscription.created`; `custom_data` copied to the subscription. | developer.paddle.com/webhooks/subscriptions/subscription-created; .../build/transactions/custom-data |
| V-7 | `POST /transactions` with items, customer, `custom_data`, collection mode and currency; draft without customer and address; Paddle.js with `transactionId`. | developer.paddle.com/api-reference/transactions/create-transaction |
| V-8 | `PATCH /subscriptions/{id}` with `proration_billing_mode`; preview; `subscription_locked_renewal` within 30 minutes; `subscription_locked_pending_changes`; `subscription_update_when_past_due`. | developer.paddle.com/api-reference/subscriptions/update-subscription; .../errors/overview |
| V-9 | Cancel at the next billing period (default) or at once; paused only at once; removal by `scheduled_change: null`; no reinstatement. | developer.paddle.com/api-reference/subscriptions/cancel-subscription |
| V-10 | The payment-method transaction: the past-due transaction, or a zero-amount one. | developer.paddle.com/api-reference/subscriptions/get-subscription-update-payment-method-transaction |
| V-11 | `GET /transactions/{id}/invoice`, an address valid for an hour, completed and non-zero transactions only. | developer.paddle.com/api-reference/transactions/get-transaction-invoice |
| V-12 | Sandbox and live base addresses; Bearer keys `pdl_(sdbx|live)_apikey_...`, 90-day default expiry; `Paddle-Version: 1`; 240 requests per minute per IP; client tokens `test_`/`live_`. | developer.paddle.com/api-reference/about/authentication |
| V-13 | Up to seven retries over 30 days for every account since 2025-01-09, then canceled; Retain offers pause or cancel; no retries in sandbox. | developer.paddle.com/build/lifecycle/subscription-renewal-dunning |
| V-14 | Description, pricing, terms, refund and privacy pages, HTTPS; most domains approved automatically; only approved domains sell; SaaS accepted. | paddle.com/help/start/account-verification/what-is-domain-verification |
| V-15 | Cards everywhere, PayPal, Apple Pay and Google Pay (not IN, TR); Egypt's default currency USD; automatic conversion can be turned off. | developer.paddle.com/concepts/sell/supported-countries-locales; .../build/products/offer-localized-pricing |
| V-16 | Egypt is not on Stripe's country list; Managed Payments in 33 locations, not Egypt, 3.5% on top of payment fees. | stripe.com/global; docs.stripe.com/payments/managed-payments/eligibility |

No fact changed a decision. The differences from the entry review, each resolved in [section 2.3 of the design note](design-017c.md#23-differences-from-the-entry-review): the five-second SDK tolerance (D7 keeps 300 seconds), the 30-minute lock also covering updates, a scheduled change blocking other changes, no "stay past due" recovery option and no sandbox retries, Paddle's automatic currency conversion, the 90-day key lifetime, and the fee confirmed on Paddle's own page.

## 5. BL01-BL23

Every test is in `backend/tests/`; integration tests are under `integration/`. All passed in the final run.

| Case | Tests | Evidence |
|---|---|---|
| BL01 | `integration/test_billing_command.py::test_bl01_register_and_retire_prices`, `::test_bl01_price_rules`; `integration/test_billing_owner.py::test_bl01_price_list_offers_only_offered_prices` | Registration reads Paddle's price once and is audited without an agency; a second offered monthly price refuses `price_offered` unless `--replaces` retires the first atomically; `price_exists`, `price_retired`, `price_not_found`; Paddle's amount, currency, interval, frequency and status must match (`price_mismatch` with the field); `plan_not_found`, `reserved_plan`; a provider failure stores nothing; the runtime cannot update an amount or delete a price; the list shows offered prices only, with plan limits, the environment and the client token; keys and anonymous callers `401`, disabled billing `503`. |
| BL02 | `integration/test_billing_standing.py::test_bl02_new_agency_standing_follows_the_setting`; `integration/test_billing_migration.py::test_bl21_upgrade_from_a_populated_0033` | With billing enabled a new agency is `trialing` for 14 days (or the configured 3) on the default plan; disabled billing, or a stale `paddle.billing` rule, makes it `complimentary`; existing agencies become complimentary (`migration`) at the upgrade, purged agencies get no standing. |
| BL03 | `integration/test_billing_standing.py::test_bl03_trial_reminder_and_end` | No reminder four days before the end; one link-only `trial_ending` message within three days, sent once, to the active verified Owner, naming no agency; at the end the agency holds on `billing_hold` (assignment `billing`/`billing_hold`) and one `billing_hold` message follows; the worker changes nothing while billing is disabled. |
| BL04 | `integration/test_billing_standing.py::test_bl04_hold_refuses_creations_and_stops_nothing` | After a trial ends through the worker, new clients, invitations, managed links and connections answer `plan_limit_reached` with value 0; clients, members, invitations, links and the connection read the same, no row is removed; sign-in, reads, the revenue report, a report export and its download, a synchronization, a redirect and collection all work; the other agency's plan is unchanged. |
| BL05 | `integration/test_billing_owner.py::test_bl05_checkout_roles_and_refusals`, `::test_bl05_one_open_checkout_under_concurrency` | Admins, Analysts, client viewers and the other agency's Owner `403`, a key `401`, a missing CSRF token `403 csrf_failed`; the same price returns the same open transaction (one Paddle call), another price replaces it, one is open; `price_not_offered`, `billing_provider_unavailable` without a stored checkout, `billing_unavailable`, `already_subscribed`; a closing agency `403`. Two concurrent checkouts against a slow Paddle yield one transaction, one created and one returned. |
| BL06 | `test_billing_webhook_contract.py::test_bl06_signature_rules`; `integration/test_billing_webhook.py::test_bl06_webhook_signature_bound_and_rate` | Valid signatures within 300 seconds and a rotation's second `h1` are accepted; a wrong secret, a changed body, a timestamp 301 seconds old or ahead, a missing or malformed header `401`, nothing stored; a verified non-event `400`; a body above 256 KiB `413`; the per-peer rate `429` with `Retry-After`; disabled billing `503`. |
| BL07 | `integration/test_billing_webhook.py::test_bl07_repeated_and_older_events` | The same `past_due` event twice moves the standing once and is stored once; an older update after it is `stale` and changes neither the subscription nor the standing. |
| BL08 | `integration/test_billing_webhook.py::test_bl08_activation_ends_trial_and_hold` | A trialing and a held agency each become `subscribed` at once on the price's plan (`billing`/`subscription`), the checkout completes and the Paddle customer is recorded. |
| BL09 | `integration/test_billing_owner.py::test_bl09_plan_changes_and_preview`; `test_billing_webhook_contract.py::test_bl09_adapter_sends_the_documented_requests` | The preview returns Paddle's amounts and changes nothing; an upgrade is requested with `prorated_immediately` and the plan changes only with `subscription.updated`; a downgrade previews `prorated_next_billing_period`, monthly to annual `prorated_immediately`; `same_price`; Admins `403`; within 30 minutes of the renewal, while past due, and on Paddle's pending-change refusal `change_not_allowed`. The adapter's bodies are the documented ones. |
| BL10 | `integration/test_billing_webhook.py::test_bl10_past_due_recovery_and_cancellation` | `past_due` keeps the plan; the recovery returns to `subscribed` (`payment_recovered`); the cancellation after the retries holds on `billing_hold` and the worker sends the hold message; a pause holds and a resumption restores the plan. |
| BL11 | `integration/test_billing_owner.py::test_bl11_cancel_undo_and_resubscribe` | The cancellation is scheduled at the period end (origin `owner`, audited) and access stays until it takes effect; a second request answers without a call; the undo removes it (audited); `no_scheduled_cancel` once removed; the effective cancellation holds; a new checkout from hold subscribes again; the payment-method transaction; the billing view; an Analyst `403`. |
| BL12 | `integration/test_billing_webhook.py::test_bl12_payments_and_adjustments` | The payment is stored with status, origin, USD, 2900 + 290 = 3190 cents, billing time, invoice number and subscription; a refund is recorded and approved without a standing change; a credit that arrives before its renewal is linked when the payment is recorded; no reason, address, email or name is stored. |
| BL13 | `integration/test_billing_owner.py::test_bl13_invoice_redirect` | Owners and Admins are redirected (302) to the address Paddle answered; Analysts and another agency `403`; the address is in no log line and no billing, event or audit row; a zero-value payment `409 invoice_unavailable`. |
| BL14 | `integration/test_billing_owner.py::test_bl14_closure_actions` | A closure request queues the period-end cancellation and the worker executes it (origin `closure`); cancelling the closure queues and executes its removal; a cancellation never claimed is skipped without a call; an Owner's earlier cancellation is kept through a closure and its cancellation; the completion queues the immediate cancellation, a provider failure retries and the next due pass cancels. |
| BL15 | `integration/test_billing_owner.py::test_bl15_purge_keeps_financial_records`; `integration/test_billing_migration.py::test_bl15_purge_waits_for_actions_and_keeps_financial_records`; `integration/test_agency_offboarding_migration.py::test_ov09_function_covers_every_scoped_table` | Through the closure, offboarding and purge, the purge waits while a billing action is pending (`teardown_pending`); the superseded period-end cancellation is skipped and the immediate one done; then no standing, checkout, event or action of the agency remains and its subscription, payment and adjustment stay. The function deletes 85 tables, children first, and keeps the five named in the test with their reasons. |
| BL16 | `integration/test_billing_webhook.py::test_bl16_unmatched_and_duplicates` | Events of an unknown subscription are stored unmatched and listed; `custom_data` naming another agency is `binding_conflict`; an update that arrives before `subscription.created` is applied at binding; a second paid checkout is a duplicate whose cancellation changes no standing and which `duplicates` lists with the primary; nothing is canceled. |
| BL17 | `integration/test_billing_owner.py::test_bl17_reconciliation_corrects_a_missed_event` | A missed `past_due` is corrected by the worker's reconciliation within bounded batches of one, recorded as `subscription.reconciled`; nothing is due again within 24 hours; a read older than the last webhook is stored `stale` and changes nothing; the operator's `reconcile` corrects at once and is audited; a provider failure is counted. |
| BL18 | `integration/test_billing_command.py::test_bl18_operator_subcommands`, `::test_bl18_command_runs_as_its_own_process_and_requires_confirm`; `test_billing_command_parser.py` (15 cases); BL16 and BL17 for `events`, `duplicates` and `reconcile` | `status`, `grant` (`invalid_until`, `reserved_plan`), `end-grant` (`not_granted`), `extend-trial` (`not_trialing`), `agencies` by standing and hold age; every change audited as the platform operator; a closed agency refuses changes; the output has no agency name, email, key or secret; as its own process `prices` works, every change without `--confirm` exits 2 and with it needs enabled billing. |
| BL19 | `integration/test_billing_webhook.py::test_bl19_billing_never_touches_client_revenue` | After a subscription and a refund, no revenue evidence, ledger row, payment source, callback diagnostic or import exists; the Paymob callback still answers `503 payments_unavailable`; no billing module imports agency-client revenue. |
| BL20 | `integration/test_billing_standing.py::test_bl20_other_agencies_never_change`; the agency B checks of BL04 and BL15 | A hold, a grant and their audits of one agency leave the other agency's standing, version, time and plan unchanged. |
| BL21 | `integration/test_billing_migration.py::test_bl21_upgrade_from_a_populated_0033`, `::test_bl21_grants`, `::test_bl21_constraints`, `::test_bl21_downgrade_restores_0033_and_refuses_stored_state`; `test_tenancy.py::test_migration_matches_model_metadata`; `test_data_policy_schema.py` | The upgrade from a populated `0033` seeds `billing_hold` and the standings; the grants match design section 3.10 column by column; the checks refuse invalid prices, standings, a second primary subscription, a second open checkout, a checkout beyond 24 hours or of another agency's member, invalid events and action pairs; five kinds of stored state each refuse the downgrade, which then restores the `0033` function exactly. |
| BL22 | `test_billing_paddle.py::test_bl22_settings_validation`; `integration/test_billing_webhook.py::test_bl22_no_secret_in_logs_answers_or_outputs`; BL13 | Enabling billing without the key or the secret, or with credentials of the other environment, fails at startup without echoing them; the client never shows its key; no key, secret, signature, email or name appears in a formatted log line, an answer, the worker's or the command's output. |
| BL23 | `integration/test_billing_owner.py::test_bl23_journey`; every existing suite; the OpenAPI comparison | A new agency trials, holds, checks out, is activated, upgrades, fails a renewal and recovers, cancels at the period end, returns to hold and is closed through the purge, keeping its financial records; the existing suites pass; the API has additions only. |

Further cases: `integration/test_billing_owner.py::test_billing_retention` (events after 395 days and expired checkouts after 30 days are deleted by the lifecycle runner, completed checkouts stay, the periods cannot be extended), `test_billing_webhook_contract.py::test_event_envelope_and_allowlisted_snapshots`, and `test_billing_paddle.py` (the price read, 15 error mappings, 8 malformed answers, the transport's bound and failures against a local socket).

## 6. Mutation check

`mutations_017c.py` (kept outside the repository) disabled each safeguard in turn, ran its tests through the disposable database, and restored every file byte for byte (SHA-256 compared after each run). A migration mutation downgraded the database to `0033` before and after its run. 28 mutations, all caught:

| Safeguard | Mutation | Caught by |
|---|---|---|
| Signature | any signature accepted | BL06 (unit and route) |
| Timestamp tolerance | no window | BL06 (unit and route) |
| `event_id` uniqueness | a stored event applied again | BL07 |
| Order | an older event applied | BL07 |
| Binding | `custom_data` conflict ignored; binding through `custom_data` instead of the transaction | BL16 (two mutations) |
| Duplicates | no duplicate flag; a duplicate's events change the standing | BL16 (two mutations) |
| Owner-only checkout | Admins may check out | BL05 |
| Single open checkout | the same price opens another transaction | BL05 (both cases) |
| `already_subscribed` | a subscribed agency checks out again | BL05 |
| Hold's plan | a hold assigns no plan | BL03, BL04 |
| Disabled billing | the standing works while disabled; no rule check | BL02, BL03 (two mutations) |
| Webhook gate, bound and rate | the webhook runs while disabled; accepts 10 MiB; no per-peer rate | BL06 (three mutations) |
| Closure actions | no request action; no removal; an Owner's cancellation overridden; no completion action | BL14, BL15 (four mutations) |
| Purge | the standing left behind; the subscriptions deleted; no wait for a pending action | OV09, BL15 (three migration mutations) |
| Separation | a billing module imports agency-client revenue | BL19 |
| Redaction | the client shows its key; a refused setting names its value | BL22 (two mutations) |
| `--confirm` | a change runs without it | the parser tests |

The separation mutation first held: the BL19 import check read only the module of `from ... import ...`, so `from app.services import revenue` passed. The check now joins each imported name to its module; the mutation is caught and `test_billing_webhook.py` passed again (8 cases).

## 7. Details found during implementation

- **Binding.** A subscription is bound only through the checkout's transaction ID, as D6 requires; events that arrive before `subscription.created` are stored unmatched and applied at binding from their allowlisted fields. This needed `UPDATE (agency_id, subscription_id, outcome, error_code)` on `billing_events`, added to the unmerged `0034` in place (P3) and tested on the disposable database.
- **Reconciliation times.** A reconciliation is timed at the start of its read, so a webhook dated later wins (`stale`); a test that dated its events a few seconds ahead of the read showed exactly that, and the test now dates them in the past.
- **Closure actions.** The completion's immediate cancellation supersedes a period-end cancellation still pending, which is then skipped without a call; the worker settles one action of a subscription per pass.
- **Seeded plans.** The test teardown restores only the `development` plan as the default, because `billing_hold` is also seeded (`reason = 'seed'`).
- **Offboarding export.** The seven scoped billing tables are excluded from the offboarding export as agency administration; Paddle issues the receipts and invoices.

## 8. Limits

- No live Paddle call was made and no Paddle account was touched; the adapter's shapes come from Paddle's documentation (section 4) and are tested only against the synthetic server. The owner's sandbox check after the merge confirms them; Paddle retries no payments in the sandbox (V-13).
- The prices, the Paddle account (either company), turning off automatic currency conversion for USD-only checkouts, the recovery setting, and the published terms, refund and privacy pages are owner inputs before live use. Hosting, the HTTPS webhook address, the worker schedule, the 90-day key rotation and the live keys belong to 020; the pages and Paddle.js belong to 018.
- A provider action that fails eight times is listed for the operator, who cancels in Paddle. Duplicate subscriptions are never canceled or promoted automatically.
- Disabling billing after it was enabled freezes every standing; an agency on hold keeps the hold plan until the operator acts.
- `billing_events` are kept 13 months as a provisional period under Q-012.
- The integration guard ran with the port deviation of section 2.
