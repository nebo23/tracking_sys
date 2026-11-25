# Spec 008-B entry review: persisted attribution

Prepared: 2026-11-25 under D-078.
- **Baseline:** merged `main` at `3187c70` (PR 15: 006, 007-B/C and the D-076 corrections).
- **Status:** proposals for the owner. Decisions D1-D14 are not approved until the owner approves them, which will be recorded as D-079.
- **Handoff:** the [implementation handoff](implementation-prompt-008b.md) executes this packet after approval.

## 1. Intended result

Every verified sale and every trusted lead of a client is attributed under the client's model versions and stored as immutable revisions, with exact shares, original-currency amounts and the campaign, content and link provenance of each credited touch.

The stored history stays correct as the inputs change:
- a refund or chargeback arrives;
- a late touch arrives;
- consent is withdrawn;
- ownership is corrected by a merge, unmerge or association;
- a person is erased.

Each such change produces a new revision. An erasure removes every identifying pointer while keeping the non-identifying credit history. Spec 016-B can then report attributed revenue, lead credit, model comparisons and ROAS from stored, revision-bound data instead of recalculating every journey on each read.

## 2. Baseline on `main`

| Area | Available | Consequence for 008-B |
|---|---|---|
| 008-A engine (`app.attribution`) | `attribute()` computes one revision of one conversion under one `ModelVersion`. It provides exact shares, largest-remainder amounts and signed `CreditDifference` values, and handles causes, windows, ties, consent and association exclusions, sale-state anchoring and currency checks. R008-01 to R008-12 are corrected. `AttributionHistory` and `IncrementalAttribution` are in memory. | Reuse `attribute()` unchanged as the calculation. Persist what `AttributionHistory` keeps in memory. Do not weaken any engine check. |
| 006 identity (PR 15) | Journeys come from `journey_events`, which excludes `identity_excluded_at` and applies segment ownership. The change feed in `identity_changes` (kinds `linked`, `unlinked`, `contested`, `merged`, `unmerged`, `merge_closed`, `erased`, `withdrawn`, `expired`, `events_changed`) carries a per-client `seq` and `pruned_through_seq`. The R006-28 protocol is proven by a test-only reference consumer. | The production consumer follows the same protocol: a REPEATABLE READ snapshot, gap and prune checks, a compare-and-swap on the generation and the checkpoint, and a release barrier. |
| 007-B ledger | `published_state` returns the generation, receipt ordinal and last sequence. The stored journal holds one receipt per evidence row with closing `SaleState` values. Reads fail closed while the projection is behind. | Sale states come from the published projection. The consumer checkpoints `(ledger generation, receipt ordinal)`. A changed generation rebuilds. |
| 007-C association | `revenue_identity_bindings` revisions are linked by `association_id`. `attribution_inputs.touchpoints()` and `sale_conversions()` build engine inputs from persisted data, and the conversion ID binds the association to the person's visible root. F1 unlinks on withdrawal, erasure and expiry. | Conversions are derived from the current associations at every pass. An ownership change creates a new conversion identity and never mutates an old one. |
| 014-C ROAS | An in-memory ROAS contract on a conversion-date basis per currency, joined to ad objects through URL parameters. | Stored credit keeps the campaign and link references and the conversion date that 016-B's ROAS join needs. |
| 016-A reports | Revision-bound, bounded, explicit-state reports over stored facts. | 008-B stores revisions and a reporting ledger. 016-B builds the reports and is not part of this packet. |

**Open items from 008-A:**
- the production defaults (Q-007);
- a report freeze cutoff;
- chargeback weighting;
- the scope of model version IDs;
- `net_out_of_range` reporting;
- persistence.

D2 to D5 and D9 resolve them. Q-007's production default is the main product choice.

## 3. Decisions for the owner

The recommendations are for synthetic data and disposable PostgreSQL. They are product and data-policy choices, not legal advice, and they leave Q-004, Q-006 and production Q-012 open.

| ID | Recommended choice | Alternative and its effect |
|---|---|---|
| D1 Scope and delivery | 008-B is persisted attribution: per-client model versions, stored conversions, runs, allocations and credit changes, a bounded worker that consumes the ledger journal, the identity feed and the association registry, privacy propagation, and minimal read and administration routes. Phases P0-P5 run on one branch, `codex/spec-008-attribution-persistence`. Verified commits are pushed after each phase (D-051), and a pull request opens for review at the end; merge is a separate decision. 016-B reports, 016-C, React UI, native rollout and live providers stay outside. | Add 016-B reports in the same branch: one review instead of two, but a much larger change mixing calculation storage with report semantics. |
| D2 Production defaults (Q-007) | Every client starts with three model versions, First Click, Last Click and Linear, each with a 30-day window and the D-046 rules (`008-A.1`), all calculated for every conversion. The client's default, used when a request names no version, is **Linear**: it credits every content touch, which suits content evaluation. | Default **Last Click**: closest to ad-platform reporting and simpler to explain, but it ignores earlier content. Calculating only the default model is cheaper but makes model comparison (PDF-038) impossible without recalculation. |
| D3 Model versions | Versions are per client and immutable: model plus a window of 1 to 90 days, with the rules fixed at `008-A.1`. An Owner or Admin adds a version, changes the default or retires one, each with an audit event. A retired version stops receiving new revisions and keeps its history. A client has at most 6 active versions. Version IDs are client-scoped, which answers the 008-A question. | Agency-wide templates: fewer settings, but one client's change would affect others; this can be a later addition. |
| D4 Conversions | Sales: every verified sale transaction of the published ledger is one conversion. An associated sale uses its owner's journey; an unassociated sale credits unknown, so attributed revenue always reconciles with ledger revenue. Leads: every trusted `lead_signal` (trust rank 2) assigned to a person is one lead conversion of one unit. Browser lead signals, purchase signals, bookings, CRM stages and manual declarations never become conversions. Identity: a sale conversion is keyed by its source account, sale operation and owner root (or none), and a lead conversion by its event and owner root. An ownership change (association, detach, merge, unmerge, erasure) supersedes the old conversion and opens a new one; a conversion's identity is never mutated. | Attribute associated sales only: smaller, but attributed totals no longer equal verified revenue, and unassociated money disappears from content reports. |
| D5 Revisions | Any input change that changes a run's outcome records a new revision: a refund, release, chargeback, correction, late eligible touch, consent withdrawal, exclusion or ownership correction. Chargebacks and corrections change the net as in 007-A. There is no freeze cutoff in this slice; every revision stores its cause and recorded time, so reports can state "as of". A `net_out_of_range` run stores no allocations and is reported with that status. | Freeze revisions some days after the conversion: stabler reports, but known refunds and privacy changes would be ignored or need special handling. Privacy changes always apply. |
| D6 Schema | Migration `0029_attribution_persistence` adds six tables, described in section 4: model versions, conversions, runs, allocations, credit changes and consumer state. All have agency and client scope, scoped composite FKs and closed value checks. Shares are stored as exact integer numerator and denominator, and amounts in original-currency minor units. Person references are identity person IDs only: never contact values, subject tokens or raw identifiers. | Store each run as one JSON document: fewer tables, but 016-B could not aggregate credit in SQL, and scrubbing an erased person would mean rewriting documents. |
| D7 Consumer | `python -m app.attribution_worker` runs one bounded pass per client, as `app.connector_worker` does; production scheduling is 020. Each pass: (1) records the published ledger cursor; (2) reads the identity feed in a REPEATABLE READ snapshot; (3) reconciles the conversion registry against the current associations and trusted leads; (4) recalculates only affected conversions with `attribute()` and `attribution_inputs`; (5) publishes the new revisions and the consumer state through a compare-and-swap on `(generation, ledger generation, receipt ordinal, identity checkpoint)` (R006-28). A pruned feed, a changed ledger generation or a new model version starts a full rebuild into a staging generation that is published atomically. Intake never waits for attribution. | Recalculate inside the intake transactions: always fresh, but it couples identity and finance intake to attribution cost and locks, which A3 already strains. |
| D8 Freshness and release | Reads use the published generation and report its watermarks. While the consumer is behind the published ledger or the identity feed, a person-level read answers the retryable `503 attribution_stale`, never an older association. The status route says `behind`, `caught_up` or `rebuilding` with the watermarks. Every person-level release rechecks scope, consent and tombstones (the R006-28 release barrier). | Serve the last published runs while behind, with a staleness flag: more available, but an erased or withdrawn person could still appear in a response until the next pass. |
| D9 Privacy | The next pass removes the person's touches from new revisions, and the release barrier blocks stale reads before then. This applies to attribution withdrawal, identity withdrawal (W1), erasure and expiry. Erasure and expiry also scrub the person reference and every touchpoint ID from all stored revisions, allocations and credit changes of the affected conversions. The scrub runs in the same transaction that removes the person, as the F1 unlinking does, and the next pass records the changed outcome as a new revision. Only non-identifying campaign, content, link and source provenance, shares and amounts remain, as the aggregate history; amounts never change. | Delete every revision of the person's conversions: simpler, but past campaign totals lose credit retroactively. Keeping everything would retain identifying links after erasure, which the approved policy forbids. |
| D10 API and permissions | Below `/agencies/{a}/clients/{c}/attribution`: <br>• `GET /models` and `GET /status` need `client:read` and are open to read service keys with that client's grant. <br>• `POST /models`, `POST /models/{id}/default` and `POST /models/{id}/retire` are for Owner and Admin, idempotent and audited. <br>• `GET /conversions/{conversion_id}/runs?model_version=` needs `identity:read`; a sale run's amounts and transaction references also need `finance:read`. It is not open to service keys. <br>Aggregated credit reports belong to 016-B. | No route in 008-B: a smaller surface, but neither the owner nor the review could inspect stored results through the API. |
| D11 Bounds | Per pass: at most 2,000 conversions, in transactions of at most 200. At most 5,000 journey touches are read per person; a person above that is marked `touch_bound_exceeded` and credits unknown explicitly. At most 6 active versions per client. Rebuild and incremental costs are measured and reported; A3 stays open, and no SLO is set. | Unbounded passes: simpler, but one large client could block the worker indefinitely. |
| D12 Retention (development) | Person-linked pointers in attribution rows follow identity retention: they are scrubbed when the person or its evidence expires (395 days) or is erased. Non-identifying credit history and model versions follow the existing workspace-lifetime financial policy. Staging rows are discarded at publication or on failure. Q-012 stays open for real data. | Delete attribution rows at 13 months: aligned with the other provisional periods, but historical ROAS and model comparisons beyond 13 months become impossible. |
| D13 Boundaries | The migration is additive and tested on disposable PostgreSQL only, with no new dependency, synthetic data only and restricted grants. `tracking_app` may insert and select, and update only the publication and scrub columns. `tracking_lifecycle` may scrub and delete per D12. No native `tracking_sys` migration, no frontend, no live provider. | Native rollout in the same slice: needs its own decision with the pending 0005-0028 rollout and the ledger backfill. |
| D14 Completion evidence | The [verification matrix](#5-verification-matrix) AV01-AV20 is executed, together with the existing 008-A (R008), 006, 007 and 014-016 suites, and every command and count is recorded. The completed branch is presented for independent review in its pull request. | Unit tests only: fast, but they would miss migration, grant, concurrency and privacy behavior. |

## 4. Design for implementation after approval

### 4.1 Schema (`0029_attribution_persistence`, after `0028_revenue_identity`)

Every table carries `agency_id`, `client_id`, a client FK and scoped composite FKs (`(agency_id, client_id, id)` uniqueness as in 0026-0028).

| Table | Key and fields | Mutation |
|---|---|---|
| `attribution_model_versions` | Unique `(client_id, version_key)`. Fields: model (`first_click`, `last_click`, `linear`), `window_seconds` (86,400 to 7,776,000), `rules` (`008-A.1`), `is_default` (one per client, by partial unique index), status (`active` or `retired`), creator membership and times. | Insert; update only `is_default`, status and `retired_at` (audited). |
| `attribution_conversions` | Unique `(client_id, conversion_key)`. Fields: kind (`sale` or `lead`), owner person ID (nullable), source account and sale operation for a sale, the collected event ID for a lead, `effective_at`, association ID (nullable), status (`active` or `superseded`), `superseded_at` and reason, `scrubbed_at`. | Insert; supersede; scrub per D9. |
| `attribution_runs` | Unique `(client_id, conversion_id, model_version_id, revision)` and `(client_id, generation, conversion_id, model_version_id, revision)`. Fields: consumer generation, status, basis, currency and exponent, verified net in minor units, window start and end, ledger generation and receipt ordinal, the identity feed seq the run reflects, causes (closed array), excluded touch reasons (closed codes, touchpoint IDs scrubbable), `recorded_at`. | Insert; scrub. |
| `attribution_allocations` | Unique `(run_id, ordinal)`. Fields: recipient (`campaign`, `direct`, `unknown`), basis, position, share numerator and denominator, `amount_minor` (null for a lead), touchpoint ID (nullable, scrubbable), source, campaign, content and link references. | Insert; scrub. |
| `attribution_credit_changes` | Unique `(run_id, ordinal)`. Fields: model version, conversion kind, the conversion's `effective_at` (the reporting date), recipient and provenance, delta share numerator and denominator, `delta_minor`, currency and exponent, `recorded_at`. Summing a model version's changes by provenance and conversion date gives the current credit: the 016-B reporting ledger. | Insert; scrub the touchpoint ID only. |
| `attribution_consumer_state` | One row per client. Fields: generation, staging generation, status (`ready`, `building`, `failed`), ledger generation and receipt ordinal, identity feed checkpoint, the model-set digest, times. | Updated only by the publication compare-and-swap. |

`data_policy` classifies every new column, with row rules under D12. `test_data_policy` and `test_data_policy_schema` count the new tables. Downgrade refuses populated state.

### 4.2 Pass algorithm

The worker processes one client at a time, in bounded batches:
1. Read `published_state`. If the ledger is unavailable, skip the client with `ledger_unavailable` and change nothing.
2. In a REPEATABLE READ snapshot, read the identity feed after the checkpoint (`read_batch` and `verify`). `rebuild` (pruned or gapped), a changed ledger generation or a changed model-set digest starts a staging rebuild.
3. Build the affected set:
   - sale conversions whose transaction appears in a receipt after the ledger cursor (from the receipt closing states);
   - conversions of persons named by feed records;
   - conversions whose association owner changed (the registry reconciliation compares stored owners with current qualifying associations);
   - new trusted leads.
4. For each affected conversion and each active model version: build the inputs with `attribution_inputs` (touches with their current consent and association, and the published `SaleState`); call `attribute()` with the latest stored revision as `previous`; store a revision only when the outcome changed, with its allocations and credit changes. Supersede conversions whose owner changed, and open their successors.
5. Publish by compare-and-swap on the captured `(generation, ledger generation, receipt ordinal, identity checkpoint)`. On conflict, roll back the whole batch.
6. Before a person-level response, compare the consumer checkpoint with the current watermarks, and recheck scope, consent and tombstones.

**Lock order.** Follow the joint design: no code that holds the revenue lock takes the privacy or agency lock. The worker takes no revenue lock: it reads published ledger state only. The D9 scrub runs inside the identity removal paths (`remove_person`, `drop_subject_evidence` and the lifecycle), under the client privacy lock they already hold.

### 4.3 Routes

The routes are those of D10, with closed error codes (`attribution_stale`, `model_version_limit`, `model_version_conflict`, `invalid_window`). The OpenAPI snapshot is regenerated, with additions only.

## 5. Verification matrix

| Case | Required observable evidence |
|---|---|
| AV01 Acceptance 1 | Touches A then B and a verified sale of 100.00, through the worker: First A 100.00, Last B 100.00, Linear A 50.00 and B 50.00, read back from stored allocations. |
| AV02 Acceptance 2 | No eligible touch: unknown 100.00. Stored allocations sum exactly to the net, by random journeys under all three models. An unassociated sale credits unknown. |
| AV03 Acceptance 3 | Window boundaries (inclusive at both ends, UTC), time zones, equal instants (ID order), a refund and a late touch, through stored runs. |
| AV04 Acceptance 4 | A repeated pass with identical inputs stores nothing new. A new model version starts its own history, and the old history stays byte-identical. |
| AV05 Incremental equals rebuild | After every step of a seeded random sequence (sales, refunds, releases, touches, withdrawals, merges), the incremental state equals a fresh staging rebuild. |
| AV06 Ledger journal | Refund, release, chargeback and correction revisions from the stored journal. A held refund changes nothing until it posts. A changed ledger generation rebuilds. |
| AV07 Ownership | Association, detach, merge, unmerge and erasure supersede the old conversion and open a new one. No conversion identity is mutated, and money is unchanged. |
| AV08 Privacy | Attribution withdrawal, W1, erasure and expiry: touches leave new revisions. Erasure and expiry scrub the person and touchpoint IDs from every stored row, and a replay cannot restore them. |
| AV09 Exclusion | Events marked `identity_excluded_at` never become touches (R006-24). |
| AV10 Isolation | Identical IDs, campaigns and operations in two clients never mix, through routes, the worker and the lifecycle. |
| AV11 Publication | Two workers, a stale checkpoint, a concurrent rebuild, a pruned feed, and an erasure after the snapshot: publication follows the compare-and-swap, and no stale person result is released. |
| AV12 Permissions | Model administration is Owner/Admin and audited. Runs need `identity:read`, and sale amounts also `finance:read`. Service keys reach models and status only. |
| AV13 Currency | Original currencies kept apart; no FX, no mixed total. |
| AV14 Migration and grants | Upgrade from a populated `0028`, guarded downgrade, and runtime and lifecycle privileges limited as D13 states. |
| AV15 Retention | The lifecycle scrubs and deletes per D12 and never touches money or the non-identifying credit history. |
| AV16 Bounds | Pass, transaction and touch bounds enforced with explicit states. Measured costs are recorded. |
| AV17 Freshness | `attribution_stale` while behind; `status` reports watermarks; a caught-up pass releases. |
| AV18 Existing behavior | The 008-A suites (R008-01 to R008-12), 006 and 007 suites, 014 ROAS, 015 and 016-A all pass unchanged. |
| AV19 Defaults | A new client gets three versions with Linear as default (or the owner's choice). A retired default is refused until another is set. |
| AV20 Logs and values | No contact value, token or raw identifier in any new row, response or log line. |
