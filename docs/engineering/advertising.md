# Advertising spend and conversion delivery (specification 014)
Status: 014-A (spend ingestion), 014-B (conversion delivery), 014-C (ROAS contract) and 014-D (live `meta_ads` and `meta_capi` adapters, off by default) are implemented under D-063 and D-064 against synthetic Meta-shaped providers and fixture tests. Meta is the initial provider. No live Meta call has been made, no customer account is connected, and native `tracking_sys` has received none of the migrations `0017` to `0019`. Sources: [entry review](../../specs/014-ad-spend-capi/entry-review.md) (section 2.4 records the official Meta pages read in Phase 0), [design](../../specs/014-ad-spend-capi/design-014.md), [evidence](../../specs/014-ad-spend-capi/evidence.md). The connector runtime underneath is described in the [connector guide](connectors.md).

## Connections
Advertising uses two connection kinds of one Meta integration, so read and delivery access never share a connection or a token (D2):

| Provider | Connects | Requires | Synchronized |
|---|---|---|---|
| `synthetic_meta_ads` (development), `meta_ads` (live) | One ad account, named by the connect request: `{"provider": ..., "account": "act_<digits>"}` | `ads_read` | Streams `account`, `ad_objects` and `ad_daily` |
| `synthetic_meta_capi` (development), `meta_capi` (live) | One dataset (Meta pixel ID), named by the connect request: `{"provider": ..., "account": "<digits>"}` | `ads_read` (V-14: it covers the Conversions API) | Never; the connection serves a destination |

After the code exchange the adapter describes the named account with the new grant. A grant that cannot read it ends the connect with `account_unavailable`. A reconnect always names the connection's own account. A connect without an account, or with one of the wrong form, answers `422 invalid_account`. Facebook Login for Business tokens do not expire and have no refresh token, and no revocation endpoint is documented (V-7). An invalid token therefore makes the connection `reconnect_required` at once, and a disconnect records the revocation as `unsupported`; the client business removes the integration under Connected apps.

## Spend (014-A)
- **Accounts.** The account's currency, time zone, status and name are kept in `ad_accounts`. The connection's day zone follows the account, and a changed currency or time zone is recorded with its time.
- **Objects.** Campaigns, ad sets and ads, with their parents, names and effective statuses, are kept in `ad_objects` and refreshed by each inventory read. Deleted and archived ads keep their facts.
- **Daily facts.** Each row of `ad_spend_facts` is one ad on one account-local day: exact minor units in the currency the day was reported in, impressions and clicks.
  - Days are read in windows of at most 7 days, 90 days back at connect, and backfilled up to 730 days.
  - Each incremental run re-reads the last 28 days, which stay provisional until 28 days after they end (V-4).
  - A changed value increments the row's revision count.
  - A value with extra decimal places (`unparseable_amount`) or in a currency outside the allow-list (`unsupported_currency`) is stored as a refusal without an amount. Nothing is rounded.
  - No zero row is stored, and a fact that a later read omits is kept, because Meta's documentation does not say whether deleted ads stay in insights.
- **Throttling.** Meta's throttling answers defer the run by the documented wait, otherwise 15 minutes. Permission errors fail the run as `forbidden`.
- **Reading.** `GET /agencies/{agency_id}/clients/{client_id}/ad-spend?connection_id=...&since=...&until=...&level=ad|adset|campaign` needs `finance:read`. Dates are account-local, inclusive, and at most 366 days apart. It answers:
  - the account;
  - totals and rows per currency (never summed across currencies);
  - the provisional dates;
  - the refused facts per reason;
  - the coverage of the daily stream.

  Spend is never stored in `connector_records`, so the `client:read` records route of a spend connection returns nothing.

## ROAS (014-C)
`app.advertising.roas.roas_report` is an in-memory contract with no route; read routes and reports belong to 016. Its rows per ad, ad set and campaign:
- name their model, version, window, period, currency and the `conversion_date` basis;
- credit revenue only through Meta's dynamic URL parameters (`utm_source=meta`, `utm_campaign={{campaign.id}}`, `utm_content={{ad.id}}`); other credit is reported as unmatched;
- give a value only when spend is above zero and one currency is involved; otherwise the reason is `zero_spend` or `currency_mismatch`.

Meta does not support dynamic URL parameters for collection ads on Instagram placements (V-18); their credit stays unmatched.

## Destinations (014-B)
A destination belongs to one delivery connection. It holds the event name (`Purchase` by default, or a custom name such as `VerifiedPurchase` when the site's pixel already sends `Purchase`), an optional test event code, and an enabled flag that is off when created.

| Route | Who |
|---|---|
| `POST /agencies/{agency_id}/clients/{client_id}/conversion-destinations` with `connection_id`, `event_name`, `test_event_code` | Owner or Admin; audit `destination.created` |
| `GET .../conversion-destinations` | Readers with `client:read` (no amounts) |
| `PATCH .../conversion-destinations/{id}` with `enabled`, `event_name`, `test_event_code` or `clear_test_event_code` | Owner or Admin; audit `destination.updated` |

Disabling a destination cancels its open deliveries (`destination_disabled`) and destroys their payloads. When a delivery connection's disconnect completes, its open deliveries are cancelled (`connection_ended`) and its destination is disabled; the destination keeps its configuration.

## Deliveries
**Source.** There is no enqueue route. A service call (`app.services.delivery.enqueue_conversions`) takes candidates from a 007-A ledger calculation or its `ledger_feed` journal (`candidates_from_ledger`, `candidates_from_feed`) together with a journey: the converting person, the collection subjects, the click identifiers (an `fbclid` with its first receipt and its 004 event ID) and the action source. Until 006 and 007-B exist, journeys are synthetic.

**Enqueue (E4).** Each candidate becomes one delivery per enabled destination of its client, only when every check passes. Otherwise nothing is stored and the closed reason is counted:

| Check | Refusal |
|---|---|
| The sale's evidence is a confirmed capture or settlement | `not_verified` |
| The net is above zero | `sale_reversed` |
| The deadline (event time plus 7 days less 1 hour) has not passed | `too_old` |
| The value fits the exact JSON range | `value_out_of_range` |
| The action source is supported | `unsupported_action_source` |
| A click identifier was received at or before the sale; it becomes `fbc` = `fb.1.<ms>.<fbclid>` | `no_match_key` |
| The action source is not `website` (website events need `client_user_agent`, which is never collected; V-9) | `provider_field_missing` |
| No replay tombstone matches the sale's 004 event IDs | `replay_before_deletion` |
| Every subject exists and is not tombstoned | `subject_deleted`, `subject_unknown` |
| `ads.measurement` and `sale_or_share` are granted for every subject (a GPC signal denies both) | `consent_unknown`, `consent_denied`, `consent_withdrawn`, `consent_expired` |
| Admission after a deletion | `subject_objected`, `no_consent_after_deletion` |

A delivery keeps:
- a deterministic event ID, so every attempt sends the same ID (see the delivery key below);
- the event time (the authoritative sale instant, never moved), the deadline, and the value in minor units of the sale's currency;
- the consent basis (consent record IDs) and the policy version;
- a payload sealed under the D-025 keyring (the `fbc`, the subject references and the replay keys), destroyed when the delivery ends.

**Delivery key (D9 as amended by D-065).** A sale reaches a dataset at most once. Its event ID is the SHA-256 digest of a length-prefixed encoding of the domain `conversion-event:v2`, the client, the dataset (the delivery connection's account at enqueue), the source account and the sale operation. It uses no destination and no secret, so a reconnection of the dataset, a second destination of it or a rotation of `TRACKING_AUTH_SECRET` never gives the sale a second ID there. At most one delivery per client and event ID holds that ID, enforced by the partial unique index `uq_conversion_deliveries_event`. The one exception is a delivery cancelled before any attempt because its destination was disabled or its connection ended, which never reached Meta: the sale may then be enqueued again through the re-enabled destination or a new destination of the same dataset, with the same event ID. A delivery cancelled after an attempt keeps the ID, because that attempt may have reached Meta.

A repeated enqueue is otherwise a no-op (`unchanged`). For the same destination, while a delivery waits, a changed net updates its value and a net of zero cancels it (`sale_reversed`). A delivered sale is never resent, through any destination, and a later refund is not sent (V-11).

**States.**

| Status | Meaning | Reasons |
|---|---|---|
| `queued` | Waiting, possibly until `next_attempt_at` | After a failed attempt: `retryable`, `rate_limited`, `count_mismatch`, `invalid_token` |
| `sending` | Claimed under a 2-minute lease | — |
| `delivered` | Meta answered `events_received` = 1 | — |
| `blocked` | The claim's recheck (E5) denied it | As at enqueue |
| `cancelled` | Destination disabled, connection ended or sale reversed | `destination_disabled`, `connection_ended`, `sale_reversed` |
| `expired` | No attempt possible before the deadline | `deadline_passed` |
| `rejected` | A permanent answer, with a class: `configuration` (token, permission or dataset) keeps the payload for a requeue; `payload` (an invalid parameter) ends the delivery | `permission_missing`, `dataset_unavailable`, `invalid_parameter`, `invalid_event` |
| `undeliverable` | Five attempts in a cycle failed | `retries_exhausted` |
| `dismissed` | An Owner or Admin dismissed a rejected or undeliverable delivery | The original reason |

**Requeue and dismiss.** `POST .../conversion-deliveries/{id}/requeue` (Owner or Admin, audit `delivery.requeued`) returns a `configuration` rejection to the queue after its cause is repaired. It works at most 3 times, before the deadline, and while the destination is enabled and the connection active, with the same event ID; otherwise it answers `409 requeue_not_available`. `POST .../dismiss` (audit `delivery.dismissed`) ends a rejected or undeliverable delivery and destroys its payload. Nothing requeues automatically. `GET .../conversion-deliveries` lists deliveries with their values for readers with `finance:read`. No answer or log contains `fbc`, `fbclid`, a payload, the event ID or a provider trace ID.

## Worker step
`python -m app.connector_worker` runs, after the connector teardowns, scheduling and syncs, one bounded delivery step (`run_deliveries`). It prints counts only:
1. It expires deliveries whose deadline has passed, which needs no key and destroys their payloads. Claims need both the token keyring and the tombstone keyring (`TRACKING_TOMBSTONE_KEYRING`, `TRACKING_TOMBSTONE_KEYRING_ACTIVE`). Without either, the step stops here and reports `"not_configured": 1` next to the expired count; the command still prints every step's counts and exits 0 (R014-02).
2. It claims at most 10 deliveries. Each claim takes a due delivery of an enabled destination, an active delivery connection of a registered delivery provider and an active agency and client, with `FOR UPDATE SKIP LOCKED`.
3. In the claiming transaction it takes the client's privacy lock and repeats E5 (tombstones and consent) from the payload. A denial makes the delivery `blocked` and destroys the payload.
4. It validates the event locally (value, currency and the action source's fields) and sends it with no lock held. `user_data` carries `fbc` only, never hashed.
5. It writes the result only while the delivery is still `sending` under the same attempt; a superseded attempt writes nothing. Each attempt stores an acknowledgement (time, outcome, closed provider code, `events_received`, trace ID).
6. Retryable answers (5xx, network, throttling, an `events_received` other than 1) retry after 30 seconds doubling to 15 minutes, or the provider's wait, at most 5 attempts in a cycle and never after the deadline.
7. An invalid token makes the delivery connection `reconnect_required`. Its deliveries wait for the reconnect and otherwise expire.

A crash after a send repeats the same event ID on the next attempt; Meta keeps the first copy within 48 hours (V-12). Every send of a sale to a dataset carries that same ID, and once a delivery has been attempted no other delivery of the sale is created for the dataset. The step is not a scheduler: deliveries move only when the command runs (production scheduling is 020).

## Lifecycle
`python -m app.lifecycle`, as `tracking_lifecycle`, deletes spend facts 730 days after their spend date, and ended deliveries with their acknowledgements 30 days after they end. Spend accounts, objects and facts are also purged when their connection's disconnect completes. These are provisional development periods (D13); no production retention is approved (Q-012).

## Settings
| Setting | Meaning |
|---|---|
| `TRACKING_CONNECTOR_SYNTHETIC_STATE` | Also selects `synthetic_meta_ads` (`<state>-meta-ads`) and `synthetic_meta_capi` (`<state>-meta-capi`) in development. |
| `TRACKING_CONNECTOR_META_ADS_ENABLED` | Registers `meta_ads` and `meta_capi` when true, the three values below are set, and their rules are current (`meta.platform_data` with `meta.marketing_api` for spend, with `meta.conversions_api` for delivery; re-verified 2026-11-20, review due 2027-11-20). Default false. |
| `TRACKING_META_ADS_APP_ID`, `TRACKING_META_ADS_APP_SECRET`, `TRACKING_META_ADS_CONFIG_ID` | The Meta app's ID (digits), its secret and the Facebook Login for Business configuration ID (digits), kept only in the ignored `.env`, separate from the Instagram values. |
| `TRACKING_AD_SPEND_RETENTION_DAYS`, `TRACKING_DELIVERY_RETENTION_DAYS` | Lifecycle periods (at most 730 and 30 days). |

The live adapters use Graph API `v27.0`. The tests drive them through the in-memory `backend/tests/meta_graph.py`; nothing in the suite contacts Meta.

## Before any live use
Live use needs the follow-ups of the [evidence](../../specs/014-ad-spend-capi/evidence.md):
- a read-only spend check with the owner's Meta app and an ad account the owner controls (014-E);
- test events to an owner dataset (014-F), which writes to Meta and needs its own approval;
- App Review, Business Verification and HTTPS hosting with a registered redirect (014-G, 020);
- the owner's decision on browser fields for website events.
