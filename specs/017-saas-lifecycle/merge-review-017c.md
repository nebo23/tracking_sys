# Spec 017-C merge review (PR 22)

Reviewed 2026-11-28 under D-104 at head `b461f1e` of `codex/spec-017c-saas-billing`, against `main` at `04dc323`. The owner asked Claude to review the completed branch and to merge it if the review confirmed it. The review found two defects of the billing worker. The owner chose to have them corrected before the merge, and Claude corrected them on the branch at `bb1b1fd`, each with a regression that fails at `b461f1e`.

## Scope of the review

The review checked the implementation against decisions D1-D14 of the [entry review](entry-review-017c.md), the [design note](design-017c.md) and the [evidence](evidence-017c.md):
- **The webhook (D7):**
  - the gate, the per-peer rate limit and the 256 KiB body bound before the signature;
  - `Paddle-Signature` checked over the raw body: a bounded header, a digits-only timestamp within 300 seconds, and every `h1` value compared in constant time;
  - each `event_id` stored once, older events `stale`, and only allowlisted fields stored.
- **The binding (D6):**
  - a subscription bound to its agency only through the checkout's transaction ID, with `custom_data` checked against it;
  - earlier events of an unbound subscription replayed at binding;
  - a second live subscription flagged a duplicate, which changes no standing.
- **The standing (D4, D5):**
  - the trial, the hold through the seeded `billing_hold` plan, grants, closed agencies, and the inert machinery while billing is not allowed;
  - the widened assignment values, and the hold plan refused as a default or an operator assignment.
- **The Owner routes (D6, D8, D9, D11):**
  - Owners act and Owners and Admins read, in an active agency;
  - one open checkout per agency under the agency lock, and `already_subscribed`;
  - the proration modes of plan changes and their refusals, cancellation and its undo, and the payment-method transaction;
  - the invoice redirect, fetched at request time and never stored.
- **The closure (D10):**
  - the actions queued in the closure's own transactions and executed by the worker, with leases, retries and skip reasons;
  - the purge waiting while an action is pending.
- **Migration `0034_saas_billing` (D13):**
  - the eight tables, and the column-level grants of `tracking_app` and `tracking_lifecycle`;
  - the regenerated `purge_agency_batch`, still `SECURITY DEFINER` with `search_path = pg_catalog, pg_temp` and qualified table references;
  - the seeds, and the guarded downgrade that restores the function of `0033`.
- **The adapter:** standard-library HTTP with a 10-second timeout, a bounded answer, closed error codes and strict parsing of every field read.
- **The rest:** the operator command, the settings validation, the log allowlist, the data policy rows, the provider rule and the separation from agency-client revenue (no billing module reads or writes revenue evidence, the ledger or a 015 payment source).

## Verification run by the reviewer

All cases ran on fresh disposable PostgreSQL 18.6 services (127.0.0.1:55433, `tracking_foundation_test`), with the repository's three roles and synthetic settings only. The integration suite ran in two shards on two such services at once. The committed integration guard still requires port 55433.

| Check at `bb1b1fd` | Result |
|---|---|
| `ruff check app tests migrations`, `ruff format --check app tests migrations` | Clean (360 files) |
| `pytest -m "not integration"` | 1030 passed |
| `pytest -m integration` with `TRACKING_RUN_BROWSER_TESTS=1`, Chromium | 858 passed, 7 skipped (the opt-in AV16, BV19 and D-076 measurements), none failed, in two shards of 433 and 432 cases; the Firefox journey case not run |
| Tracker unit, and tracker browser with Chromium | 73 and 25 passed (the 25 Firefox cases were cancelled: Firefox is not installed in the review environment) |
| `pip check`, `git diff --check`, relative links of the changed Markdown (429 in 19 files) | Clean |
| OpenAPI, semantic comparison with `main` | 9 paths and 20 schemas added; nothing removed or changed |
| Database privileges after the migration | Only `tracking_lifecycle` (and the owner) may execute `purge_agency_batch`, which is still `SECURITY DEFINER` with its fixed `search_path`. `tracking_app` holds no delete right on any billing table. `tracking_lifecycle` deletes only `billing_events` and `billing_checkouts` and inserts `billing_actions`. The stored function has 87 delete statements, the four operational billing tables included, none for subscriptions, payments or adjustments, and no unqualified table reference. |
| Mutation check of the corrections | 3 of 3 caught: the trials step without its closed filter, the hold messages without their active filter, and the reconciliation without the record of a failed read; sources restored byte for byte (SHA-256) |

Firefox is not installable in the review environment, so the Firefox cases were not run here. The implementing model's evidence records them passing.

## Findings

| ID | Defect at `b461f1e` | Correction at `bb1b1fd` | Regression (fails at `b461f1e`) |
|---|---|---|---|
| R017C-01 | The worker's steps selected agencies that the step then left unchanged, without recording them: closed agencies for the end of trials and grants, and agencies that are not active for the `trial_ending` and `billing_hold` messages. A batch is ordered by agency ID, so as many such agencies as the batch size kept every other agency from being reached. A suspended agency on hold held back every other agency's hold message for as long as it stayed suspended. With a batch of one, the reproduction showed an active agency on hold that was never notified. | Each step selects only the agencies that it can change: not closed for trials and grants, active for the messages. The guards under the agency lock are unchanged. An agency on hold is notified once it is active again. | `test_billing_standing.py::test_bl03_worker_batches_pass_agencies_that_a_step_skips` |
| R017C-02 | A failed Paddle read left the subscription's `reconciled_at` unchanged, so the subscription stayed at the head of the reconciliation batch (ordered by `reconciled_at`, nulls first). As many subscriptions that Paddle kept refusing as the batch size stopped the reconciliation of every other subscription. With a batch of one, the reproduction showed a healthy subscription that was never read. | A failed read counts as the subscription's reconciliation attempt, recorded under the agency lock (a busy agency is left for the next pass). The subscription is read again after 24 hours, like the others. | `test_billing_owner.py::test_bl17_a_failing_read_does_not_hold_back_the_reconciliation` |

The following points are recorded limits, without a change:
- **O1 Checkout replacement.** An Owner may pay an open checkout and then open a checkout for another price before Paddle's events arrive. That Owner can pay twice. The second subscription is flagged a duplicate and listed by `duplicates`, and the operator refunds and cancels it in Paddle.
- **O2 Calls under the agency lock.** The Owner routes call Paddle while they hold the agency row lock, which serializes the checkouts of one agency (D6), for up to the 10-second timeout. Meanwhile other writes of that agency wait, and so does its webhook processing. Paddle retries a webhook that it does not see answered within 5 seconds, and the retry is idempotent.
- **O3 Billing not allowed.** While billing is not allowed (disabled after use, or the `paddle.billing` rule past its review date of 2027-11-28), the worker executes no closure action. The purge of a closed agency with a pending action then waits until billing is allowed again. No command settles such an action.
- **O4 Redirects.** Like the other live adapters, the Paddle adapter follows HTTP redirects with the standard library's defaults, which keep the request's headers, the API key included. Paddle's API is not expected to redirect. Refusing redirects for every adapter belongs to the hardening of 019.
- **Provider facts.** The implementing model verified V-1 to V-16 on Paddle's pages. No fact changed a decision. The differences that matter before live use are in the [evidence](evidence-017c.md#4-provider-facts-v-1-to-v-16): disable the automatic currency conversion, configure the cancellation after the last retry, and rotate the API key, which expires after 90 days by default (020).

## Result

The corrections were verified at `bb1b1fd`. The next commit, `fbba3bf`, adds only the [evidence](evidence-017c.md#9-review-corrections-d-104) of the corrections and this review. PR 22 merged into `main` as `7c7b5b5`, a merge commit of `04dc323` and `fbba3bf` whose tree equals the corrected head `fbba3bf`.
