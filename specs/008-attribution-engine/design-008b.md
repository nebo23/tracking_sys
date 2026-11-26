# Spec 008-B design note: persisted attribution

Status: design note under D-079, written 2026-11-25 as P0 on `codex/spec-008-attribution-persistence` (from `claude/keen-fermat-otlr9d` at `3d1a472`; `origin/main` is `3187c70`) and brought in line with the implementation in P5 (2026-11-26). The source is section 4 of the [008-B entry review](entry-review-008b.md); this note resolves its routine details and lists, in section 10, the resolutions that go slightly beyond the packet's wording. Test results are in the [008-B evidence](evidence-008b.md).

## 1. Inventory of the persisted inputs

The field names behind section 4 of the entry review, as they exist at `3d1a472`:

| Input | Source of truth | Fields used |
|---|---|---|
| Published ledger | `ledger_store.published_state(session, agency_id, client_id)` returns the `ledger_projection_state` row, `None` for a client without evidence, or raises `LedgerUnavailable` (`ledger_projection_unavailable`, 503) while the projection is not ready or is behind its evidence. | `generation`, `receipt_ordinal`. Only the operator backfill (`app.ledger_backfill`) changes `generation`; receipt ordinals restart at 1 in every generation. |
| Ledger journal | `ledger_receipts` of the published generation. | `receipt_ordinal`, `closing_states` (JSON items with `source_account_id`, `transaction_id`, `currency`, `exponent`, `effective_at`, `net_minor`). A receipt lists every sale transaction it moved or whose state changed. No function reads receipts after a cursor; the store adds one. |
| Verified sales | `ledger_transactions` of the published generation, one row per `(source_account_id, operation_id)`. | `currency`, `currency_exponent`, `sale_effective_at`, `net` (never negative; `attribution_inputs` clamps defensively). `LedgerTransaction.net` is a BIGINT, so the engine's `net_out_of_range` (10^30) cannot arise from the persisted ledger; the status is still supported. |
| Identity feed | `identity_changes` and `identity_feed_state`, read with `identity_feed.begin_snapshot`, `read_batch`, `verify` and `snapshot_watermark`. | `seq`, `person_id`, `kind`; `last_seq`, `pruned_through_seq`. |
| Journey | `identity.journey_events(session, client_id, person_id, now)`: events of the person's merge group, marked events (`identity_excluded_at`) excluded. | Through `attribution_inputs.touchpoints(...)`: `event_id` (touchpoint ID), `occurred_at`, `link_id`, campaign, `trust_rank`, attribution consent of the collection subject. |
| Trusted leads | `collected_events` with `event_type = 'lead_signal'` and `trust_rank = 2`, assigned to a person by `identity.owner_of` over the subject's segments. | `event_id`, `occurred_at`, `subject_id`, `first_received_at`. Nothing in `app/` built a lead `Conversion` before 008-B. |
| Associations | `revenue_identity_bindings`; qualification by `revenue_identity._qualifying` (open revision, state `active` or `pending`, `_segment_ok` with identity_link and attribution consent, verified sale). | `id`, `association_id` (one per sale: `association_id(client, account, operation)`), `owner_subject_id`, `collection_subject_id`, `closed_at`, `state`. `associate()` and `detach()` append revisions; `unlink()` (F1) and `follow_link_owner()` update in place. |
| Person roots | `identity.root_of`, `identity.person_group`. | `merged_into_id`. |

Change signals and their gaps:
- Receipts carry every financial change of a sale (refund, release, chargeback, correction, re-anchoring).
- The feed carries merges, unmerges, links, contests, W1, erasure, expiry and new, upgraded or expiring assigned events.
- The feed does not carry an attribution-only consent change, consent expiry over time, `associate()` or `detach()`. Section 4.3 covers each of these.

## 2. Schema: migration `0029_attribution_persistence`

Revision `0029_attribution_persistence`, revises `0028_revenue_identity`. Additive only. Conventions follow 0026-0028: scope columns first, a client FK `(agency_id, client_id)` to `client_workspaces(agency_id, id)`, scoped composite FKs `(agency_id, client_id, <column>)` to `<target>(agency_id, client_id, id)` backed by `uq_<table>_scope`, closed value checks named `valid_<column>`, no `ON DELETE` actions, and person, event and touchpoint references without FKs (the referenced rows are erasable).

### 2.1 `attribution_model_versions`

| Column | Type | Rule |
|---|---|---|
| `id`, `agency_id`, `client_id` | uuid | scope |
| `version_key` | varchar(64) | `^(first_click\|last_click\|linear)_[0-9]{1,2}d_v[0-9]{1,6}$`, unique per client; the client-scoped version ID of the engine (`ModelVersion.version_id`) |
| `model` | varchar(16) | `first_click`, `last_click`, `linear` |
| `window_seconds` | integer | 86,400 to 7,776,000 and a whole number of days |
| `rules` | varchar(16) | `= '008-A.1'` |
| `is_default` | boolean | default false; at most one per client (partial unique index `uq_attribution_model_versions_default` on `client_id` where `is_default`); `NOT is_default OR status = 'active'` |
| `status` | varchar(16) | `active`, `retired`; `(status = 'retired') = (retired_at IS NOT NULL)` |
| `created_by_membership_id` | uuid null | FK `(agency_id, created_by_membership_id)` to `agency_memberships(agency_id, id)`; null for the seeded defaults |
| `operations` | jsonb | default `'[]'`, an array; each item `{operation_id, action, fingerprint}` records an idempotent administrative request that targeted this row |
| `created_at`, `retired_at` | timestamptz | |

A partial unique index `uq_attribution_model_versions_active_definition` on `(client_id, model, window_seconds)` where `status = 'active'` refuses a duplicate active definition. The version key is `<model>_<days>d_v<n>`, where `n` is one more than the number of earlier versions with the same model and window, so a retired definition can be added again as a new version with its own history.

### 2.2 `attribution_conversions`

| Column | Type | Rule |
|---|---|---|
| `id`, `agency_id`, `client_id` | uuid | scope; `id` is the engine's `conversion_id` and the API's conversion ID |
| `generation` | bigint | the consumer generation that opened it, `>= 1` |
| `slot_key` | char(64) | SHA-256 hex of the slot (section 3); partial unique index `uq_attribution_conversions_open_slot` on `(client_id, slot_key)` where `superseded_generation IS NULL` (one open conversion per sale or lead) |
| `conversion_key` | varchar(80) | `<slot_key>.<n>`, unique per client (section 3) |
| `kind` | varchar(8) | `sale`, `lead` |
| `owner_person_id` | uuid null | the owner's visible root; scrubbable |
| `association_id` | uuid null | the qualifying association of a sale owner, else null |
| `binding_id` | uuid null | the open association revision that was examined, qualifying or not (change detection, section 4.3) |
| `source_account_id`, `sale_operation_id` | varchar(256) null | sale only |
| `lead_event_id` | uuid null | lead only; scrubbable |
| `effective_at` | timestamptz | the anchor when opened (sale instant or lead `occurred_at`) |
| `status` | varchar(16) | `active`, `superseded` (the published status) |
| `superseded_generation`, `superseded_at`, `superseded_reason` | bigint, timestamptz, varchar(24) | set together; reason `owner_changed`, `sale_removed`, `sale_changed`, `lead_removed`, `lead_changed`, `scrubbed`; `status = 'active' OR superseded_generation IS NOT NULL`; `superseded_generation >= generation` |
| `scrubbed_at` | timestamptz null | set by the scrub |
| `recheck_at` | timestamptz null | the earliest consent expiry the current result depends on (section 4.3) |
| `created_at` | timestamptz | |

Checks: a sale has both transaction references and no lead event; a lead has neither transaction reference nor association; an unscrubbed lead has an event and an owner; a scrubbed row (`scrubbed_at` set) has no owner, no lead event and `conversion_key = 'scrubbed.' || id`. Indexes: `(client_id, owner_person_id)` where not null, `(client_id, lead_event_id)` where not null, `(client_id, recheck_at)` where `status = 'active'`, and `(client_id, generation)`.

### 2.3 `attribution_runs`

| Column | Type | Rule |
|---|---|---|
| `id`, `agency_id`, `client_id` | uuid | scope |
| `generation` | bigint | `>= 1` |
| `conversion_id`, `model_version_id` | uuid | scoped FKs |
| `revision` | integer | `>= 1`; unique `(client_id, conversion_id, model_version_id, revision)` |
| `status` | varchar(24) | `complete`, `no_verified_revenue`, `net_out_of_range`, `superseded` |
| `basis` | varchar(24) null | `campaign`, `direct_fallback`, `unknown_fallback`; null exactly for `superseded` |
| `causes` | varchar(24)[] | non-empty, within `initial`, `revenue_changed`, `sale_time_changed`, `touches_changed`, `evidence_changed`, `superseded` |
| `currency`, `currency_exponent` | varchar(3), smallint null | together; `^[A-Z]{3}$`, 0 to 8 |
| `verified_net_minor` | bigint null | `>= 0`; the exact `SaleState.net_minor` of a sale run |
| `window_start`, `window_end` | timestamptz null | null exactly for `superseded`; `window_start <= window_end`; `window_end` is the conversion instant the run is anchored to |
| `ledger_generation`, `receipt_ordinal` | bigint null | together; the published ledger position the run observed |
| `identity_seq` | bigint | the feed watermark of the snapshot the run was computed in |
| `excluded_touchpoint_ids` | uuid[] | elements scrubbable to null |
| `excluded_reasons` | varchar(40)[] | the seven engine exclusion reasons; same cardinality as the IDs; stored in the engine's order |
| `touch_bound_exceeded` | boolean | D11 |
| `recorded_at` | timestamptz | the database clock of the pass |

Indexes: `(client_id, generation)` and a GIN index on `excluded_touchpoint_ids` for the scrub.

### 2.4 `attribution_allocations`

One row per eligible touch of the run in the engine's stable order (credited or not), plus one row for an unknown allocation. The uncredited rows keep the eligible touches of First and Last Click, which the engine compares when it decides whether a revision is new (section 5.2).

| Column | Type | Rule |
|---|---|---|
| `id`, `agency_id`, `client_id` | uuid | scope |
| `run_id` | uuid | scoped FK; unique `(run_id, ordinal)` |
| `ordinal` | integer | `>= 1` |
| `credited` | boolean | `credited = (share_numerator > 0)` |
| `recipient` | varchar(8) | `campaign`, `direct`, `unknown` |
| `basis` | varchar(24) | as for runs |
| `position` | integer | `>= 0`; `(recipient = 'unknown') = (position = 0)` |
| `share_numerator`, `share_denominator` | bigint | `>= 0`, `> 0`; the exact `Fraction` |
| `amount_minor` | bigint null | `>= 0`; null for a lead and for an uncredited touch |
| `touchpoint_id` | uuid null | scrubbable |
| `evidence_class` | varchar(24) null | `campaign_interaction`, `direct_visit`; set exactly for a touch row |
| `occurred_at` | timestamptz null | the touch instant; scrubbable |
| `source` | varchar(16) null | `tracker`, `trusted_sender` |
| `campaign_ref`, `content_ref` | varchar(256) null | provenance |
| `link_ref` | uuid null | provenance |

An unknown row has no touch field. Index `(client_id, touchpoint_id)` where not null.

### 2.5 `attribution_credit_changes`

The reporting ledger: summing one model version's rows by provenance and `effective_at`, up to a `recorded_at`, gives the credit as of that time.

| Column | Type | Rule |
|---|---|---|
| `id`, `agency_id`, `client_id` | uuid | scope |
| `run_id`, `model_version_id` | uuid | scoped FKs; unique `(run_id, ordinal)` |
| `generation` | bigint | copied from the run, for generation-bound reads |
| `ordinal` | integer | `>= 1` |
| `conversion_kind` | varchar(8) | `sale`, `lead` |
| `effective_at` | timestamptz | the reporting date (the conversion instant the change is booked at) |
| `recipient`, `source`, `campaign_ref`, `content_ref`, `link_ref` | as for allocations | provenance |
| `touchpoint_id` | uuid null | scrubbable |
| `delta_share_numerator`, `delta_share_denominator` | bigint | denominator `> 0` |
| `delta_minor` | bigint null | set exactly for a sale |
| `currency`, `currency_exponent` | null | set exactly for a sale |
| `recorded_at` | timestamptz | |

A change is never zero in both share and money. Indexes: `(client_id, model_version_id, effective_at)`, `(client_id, generation)` and `(client_id, touchpoint_id)` where not null.

### 2.6 `attribution_consumer_state`

One row per client, `client_id` primary key, client FK.

| Column | Type | Meaning |
|---|---|---|
| `version` | bigint | incremented by every update; the compare-and-swap token |
| `generation` | bigint | the published generation, 0 before the first publication |
| `status` | varchar(16) | `ready`, `building`, `failed`; `ready` needs `generation >= 1`; a rebuild unit implies `building` |
| `ledger_generation`, `receipt_ordinal`, `identity_seq` | bigint | the published checkpoint |
| `model_set_digest` | char(64) null | SHA-256 of the published active version set |
| `unit_kind` | varchar(16) null | `incremental`, `rebuild`; the unit of work in progress |
| `staging_generation` | bigint null | set exactly for a rebuild unit; `> generation` |
| `target_ledger_generation`, `target_receipt_ordinal`, `target_identity_seq`, `target_model_set_digest`, `unit_started_at` | null | the unit's fixed target; set exactly while a unit exists |
| `progress_key` | char(64) null | the last slot key the unit processed |
| `sweep_after_key` | char(64) null | the sweep cursor (section 4.5) |
| `scrub_epoch` | bigint | incremented by every scrub (section 6.3) |
| `failure_code` | varchar(40) null | `(status = 'failed') = (failure_code IS NOT NULL)`; a closed engine code |
| `published_at`, `updated_at`, `created_at` | timestamptz | |

### 2.7 Grants (D13)

`tracking_app`:
- `SELECT, INSERT` on the six tables.
- `UPDATE (is_default, status, retired_at, operations)` on model versions.
- `UPDATE (status, superseded_generation, superseded_at, superseded_reason, recheck_at, binding_id, owner_person_id, lead_event_id, slot_key, conversion_key, scrubbed_at)` on conversions: the publication and scrub columns.
- `UPDATE (excluded_touchpoint_ids)` on runs, `UPDATE (touchpoint_id, occurred_at)` on allocations, `UPDATE (touchpoint_id)` on credit changes: the scrub columns.
- `UPDATE` of every consumer state column except `client_id`, `agency_id` and `created_at`.
- No `UPDATE` of any share, amount, currency, provenance, revision, cause or time column, and no `DELETE`.

`tracking_lifecycle` (D12):
- `SELECT` on the six tables; `INSERT` and the column `UPDATE`s of the consumer state (it runs the identity expiry, which scrubs).
- The scrub `UPDATE`s listed for `tracking_app` on conversions, runs, allocations and credit changes, plus `UPDATE (status, superseded_generation, superseded_at, superseded_reason)` on conversions to undo a failed staging supersession.
- `DELETE` on conversions, runs, allocations and credit changes (failed staging rows only, by the code path of section 7).

The audit lists gain the actions `attribution.model_created`, `attribution.model_default_set` and `attribution.model_retired`, and the resource type `attribution_model` (both checks are swapped as 0028 does).

### 2.8 Downgrade

Offline mode is refused. The downgrade locks the six tables and `audit_events`. It refuses with `Refuse to remove persisted attribution state; use a forward fix.` if any of the five data tables has a row or an audit event uses a new action or resource. Otherwise it revokes the lifecycle grants, drops the tables children first and swaps the audit checks back.

The consumer state is not part of that check: it is derived bookkeeping, which a removal path may create (section 6.3) without any attribution data existing.

## 3. Conversion identity and keys

- **Slot.** A sale slot is the transaction key, a lead slot is the lead event. `slot_key = sha256(json(["attribution-slot:v1", client_id, "sale", source_account_id, sale_operation_id]))` or `sha256(json(["attribution-slot:v1", client_id, "lead", event_id]))`, as hex.
- **Identity.** A conversion means one slot with one owner: the owner's visible root, or none for an unassociated sale (a lead always has an owner). The engine `Conversion` uses `conversion_id = str(row.id)`, `person_id = str(owner)` or `"unassociated"`, and for a lead `effective_at` equal to the lead event's `occurred_at`. A sale's anchor follows the ledger (`attribute()` re-anchors it), so `conversion.identity` stays fixed.
- **Key.** `conversion_key = <slot_key>.<n>`, where `n` is one more than the number of conversions ever opened in the slot. It contains no person reference, so an owner change (A, then B, then A again) opens a new key each time.
- **Change.** When the stored owner differs from the current candidate, when the conversion was scrubbed, or when the slot has no candidate any more, the conversion is superseded and, if a candidate exists, a successor is opened. A conversion's slot, kind and owner are never updated; only the publication and scrub columns change.

Candidates, computed in the pass snapshot:
- **Sale:** a `ledger_transactions` row of the published generation. Its owner is `root_of(binding.owner_subject_id)` when the open revision of `association_id(client, account, operation)` qualifies under `_qualifying`; otherwise none. Reasons: `sale_removed` (no transaction any more), `sale_changed` (the currency or exponent differs from the stored runs), `owner_changed`.
- **Lead:** an unmarked `lead_signal` event with `trust_rank = 2` whose `owner_of` over its subject's segments is a person; the owner is that person's root. Reasons: `lead_removed`, `lead_changed` (its `occurred_at` changed), `owner_changed`.

## 4. The pass

`python -m app.attribution_worker` runs one bounded pass over every active client (in client ID order) as `tracking_app`, and prints one JSON line of counts. Per client:

1. A short READ COMMITTED transaction ensures the consumer state row (`INSERT ... ON CONFLICT DO NOTHING`) and seeds the default model versions (section 8.1).
2. Units of work run in chunk transactions until the client is caught up, the pass budget (2,000 slots) is spent, or a conflict or failure stops it.

### 4.1 Units and chunks

A unit has a fixed target `(ledger generation, receipt ordinal, identity seq, model-set digest, start time)` captured when it starts, and a progress cursor over slot keys. Every chunk is one transaction:

1. `begin_snapshot` (REPEATABLE READ is the first statement), then read the consumer state without a lock.
2. Read `published_state`. `LedgerUnavailable` ends the client's pass with the count `ledger_unavailable` and changes nothing.
3. Without a unit: decide (section 4.2) and start one by compare-and-swap, or run the sweep, or finish.
4. With a unit: enumerate the unit's slot keys, sort them, take at most 200 after `progress_key`, and compute every change in memory (sections 4.4 and 5). Nothing is written yet.
5. Write phase. The first write is the compare-and-swap on the consumer state: `UPDATE ... SET version = version + 1, ... WHERE client_id = :c AND version = :v AND generation = :g AND ledger_generation = :lg AND receipt_ordinal = :ro AND identity_seq = :s`. A row count of 0, a serialization failure (the row changed after the snapshot) or a lock timeout rolls the whole chunk back and is counted as `conflict`. Then the supersessions are updated, and the new conversions, runs, allocations and credit changes are inserted.
6. The last chunk of a unit also publishes it in the same transaction: an incremental unit sets the checkpoint to the target; a rebuild unit sets `generation = staging_generation`, the checkpoint and the model-set digest to the target, `status = 'ready'`, marks `status = 'superseded'` on the conversions whose `superseded_generation` is the staging generation, and clears the unit.

The compare-and-swap is taken before any other row is written, so a worker never holds an attribution row lock while it waits for the consumer state row (section 6.3 relies on this).

### 4.2 Deciding the unit

- A rebuild unit (section 4.6) starts when the state was never published, the active model-set digest differs from the published one, the published ledger generation differs from the checkpoint's (a change from 0, the first evidence, is incremental), or `verify(read_batch(after = identity_seq))` answers `rebuild` (a pruned or gapped feed).
- An incremental unit starts when the ledger receipt ordinal or the feed is ahead of the checkpoint, when an association revision differs from what an active sale conversion recorded (section 4.3), when an active conversion was scrubbed, or when an active conversion's `recheck_at` has passed.
- Its target is the current watermarks, capped at 1,000 receipts and 500 feed records beyond the checkpoint so that each unit stays small; the rest is the next unit.
- Otherwise the client is caught up and the sweep runs (section 4.5).

### 4.3 The affected slots of an incremental unit

Cursor-based inputs, bounded by the target:
- the sale slots named in the closing states of the receipts in `(receipt_ordinal, target_receipt_ordinal]`;
- for each person in the feed records `(identity_seq, target_identity_seq]`: the open conversions it owns, its current root's open conversions, the current sale candidates of the root's group (`_qualifying`) and the trusted lead events of the root's journey.

State-based inputs, recomputed at every chunk:
- **Association changes:** open association revisions (`closed_at IS NULL`, `active` or `pending`) are compared with the `binding_id` that each open sale conversion recorded. A new, detached, closed or unlinked revision makes its slot affected. `associate()` and `detach()` therefore need no feed record.
- **Scrubbed conversions:** open conversions with `scrubbed_at` set.
- **Consent expiry:** open conversions whose `recheck_at` has passed. `recheck_at` is the earliest `expires_at` of the current attribution and identity_link grants of the owner group's collection subjects and of the association's subject.

Feed emission for consent (section 10, item 1): `record_consent` appends an `events_changed` record for the owners of a collection subject's active links when that subject's effective attribution state changes (granted to not granted, or back), or when identity_link is granted again after it lapsed. The record is appended before W1 removes the links; W1 records its own changes. The next pass therefore removes or restores the touches (D9), and the release barrier sees the feed watermark move.

Because the cursor-based inputs are fixed by the target and the state-based ones are re-evaluated by every unit, a change committed while a unit runs is applied by the next unit at the latest.

### 4.4 One slot

1. Compute the candidate (section 3) and load the open conversion of the slot.
2. Keep the conversion when the owner and, for a lead, the anchor match, it is not scrubbed and the stored currency matches. Otherwise supersede it: under every active model version that has runs, append a closing revision (section 5.3), set `superseded_generation` (and, in an incremental unit, `status`) and the reason, then open the successor.
3. For the kept or new conversion and every active version: build the inputs with `attribution_inputs` (touches of the owner root, cached per person in the chunk; the `SaleState` of the published transaction; `ledger_position` = the published receipt ordinal), reconstruct the latest stored revision as the engine's `AttributionRun` (section 5.2) and call `attribute(..., previous=reconstructed)`. A run whose revision differs from the previous one is stored with its allocations and credit changes; an unchanged outcome stores nothing.
4. Update `recheck_at` when it changed.

**Touch bound (D11).** Before loading a journey, the store counts the unmarked events of the collection subjects with an active link to the owner group, limited to 5,001 rows. Above 5,000, the person's touches are not loaded: the engine receives no touch, credits unknown, and the stored run has `touch_bound_exceeded = true`.

**Engine refusals.** A closed `AttributionInputError` other than `stale_ledger_position` stops the unit: a separate compare-and-swap sets `status = 'failed'` and `failure_code`. `stale_ledger_position` means another worker published after the snapshot and is a `conflict`.

### 4.5 Sweep

When a client is caught up, the sweep recalculates at most 200 open conversions after `sweep_after_key` (wrapping around) through the same slot path. It writes only what changed, and its compare-and-swap leaves the checkpoint unchanged. It repairs changes that no signal reports, and an identical pass therefore stores nothing (AV04).

### 4.6 Rebuild

A rebuild unit allocates `staging_generation = generation + 1`, sets `status = 'building'` and enumerates every slot:
- every `ledger_transactions` row of the published generation;
- every trusted lead event;
- every open conversion, so that slots without a candidate are superseded.

Slot keys are enumerated cheaply; the per-slot work is done only for the chunk. Staged rows carry the staging generation and stay invisible; staged supersessions set `superseded_generation` but keep `status = 'active'` until publication.

History is preserved: every slot is recalculated with its latest stored revision as `previous`, so a version whose outcomes are unchanged gains no row (AV04), a new version starts its own history, and the rebuild of a correct incremental state stores nothing (AV05). After a ledger generation change, a stored run's `receipt_ordinal` belongs to another journal: the reconstructed `previous` then carries `ledger_position = None`, which keeps the engine's currency and state checks and skips only the position comparison across journals.

If the target becomes obsolete while the rebuild runs (another ledger generation or another model set), the unit restarts in place: same staging generation, new target, cursor reset. A publication needs the compare-and-swap like every chunk.

## 5. Mapping to the engine

### 5.1 Inputs

- `ModelVersion(version_key, AttributionModel(model), timedelta(seconds=window_seconds), "008-A.1")`.
- Touches come from `attribution_inputs.touchpoints`. It now also fills `content_ref` from the managed link's content reference, the way `identity_admin._provenance` does, and ignores a `utm_campaign` value the engine would refuse (empty, longer than 256 characters, padded or unprintable) instead of failing the person's whole journey (section 10, item 3).
- `SaleState(LedgerScope(agency, client, account), operation, Currency(currency, exponent), sale_effective_at, max(net, 0))`, as `attribution_inputs.sale_conversions` builds it.

### 5.2 Reconstructing the previous revision

The engine decides on a new revision by comparing `previous.outcome` with the fresh outcome: status, basis, sale state, verified net, window end, the eligible touches, the allocations and the excluded touches. The store therefore rebuilds the latest run exactly:
- the eligible touches from the allocation rows in position order (`Association.ASSIGNED`, `ConsentState.GRANTED`, the conversion's scope and person, the stored class, instant and provenance);
- the allocations from the credited rows;
- the excluded touches from the two arrays;
- the sale state from the run's currency, `window_end` and `verified_net_minor`;
- `ledger_position` from `receipt_ordinal` when the run's ledger generation is the published one, else `None`.

A unit test round-trips engine runs of all three models through rows and back and compares `outcome`, `causes` input and `ledger_position`.

### 5.3 Credit changes

For each stored run of a version:
- an initial revision books its credited allocations;
- a later revision with an unchanged anchor books the engine's `differences` at that anchor;
- a later revision whose anchor moved (`sale_time_changed`) reverses the previous credited allocations at the old anchor and books the new ones at the new anchor, so the ledger by date stays exact;
- a closing revision (`status = 'superseded'`, cause `superseded`, no allocations) reverses the latest credited allocations at their anchor.

The sum of a conversion's changes always equals its latest allocations, and the sum over a sale's successive conversions equals the latest one's; money is never changed or created (AV07).

## 6. Privacy

### 6.1 Scrub (D9, D12)

`scrub(session, client_id, conversion_ids, now)` sets, for each listed conversion:
- `owner_person_id`, `lead_event_id` to null, `conversion_key` to `scrubbed.<id>`, a lead's `slot_key` to `sha256(["attribution-scrubbed:v1", id])`, and `scrubbed_at`;
- every element of `excluded_touchpoint_ids` of its runs to null;
- `touchpoint_id` and `occurred_at` of its allocations to null;
- `touchpoint_id` of its credit changes to null.

Shares, amounts, currencies, the reporting dates and the campaign, content, link and source provenance stay. A scrubbed conversion is never recalculated: the next pass supersedes it (reason `scrubbed`) with a closing revision built from its stored, scrubbed allocations, and opens a successor for the slot's current candidate. A replay of the same inputs then reaches the successor, never the scrubbed rows.

### 6.2 Where the scrub runs

The scrub runs in the removal transactions, after the F1 unlinking:

| Path | Affected conversions |
|---|---|
| `remove_person` (any kind; it deletes the person) | those owned by the person, and for `erased` and `expired` also every conversion that references one of the person's events (event IDs of the events its active segments cover, read before its links are deleted) |
| person erasure (`IdentityAdmin._run_erasure`), before its confirmed events are deleted | every conversion that references one of the person's confirmed or held events |
| `drop_subject_evidence` with `erased` or `expired` (004 token erasure, person erasure of an exclusive subject, lifecycle expiry of a subject) | every conversion that references an event of the subject, as a touch or as its lead event |
| identity lifecycle expiry of links and assertions (395 days) | every conversion that references an event covered by an expiring link's segment |
| identity lifecycle step for collected events leaving retention (the 13-month event retention of D-027) | every conversion that references one of those events |

A withdrawal (W1 or attribution) that leaves the person in place scrubs nothing: its touches leave the next revision (D9).

### 6.3 Ordering against the worker

The scrub first makes sure the consumer state row exists, then updates it (`scrub_epoch + 1`, `version + 1`), and only then updates attribution rows:
- **The removal commits after a worker's snapshot.** The worker's compare-and-swap then fails, by row count or serialization failure, and its rows from the stale snapshot are never committed.
- **A worker is in its write phase.** It already holds the state row from its compare-and-swap. The removal waits for that short phase (inserts only), then its READ COMMITTED scrub statements see and scrub the rows just committed.

Lock order:
- Worker: consumer state row, then attribution rows. It takes no advisory lock (privacy, agency or revenue) and no identity, ledger or association row lock.
- Removal: privacy lock and identity rows as before, then the consumer state row, then attribution rows.

No cycle is possible. The identity lifecycle's 100 ms lock timeout makes it retry a batch rather than wait.

### 6.4 Erasure targets

- A person erasure reports `"attribution": "done"` when its transaction scrubbed a stored conversion (one whose `scrubbed_at` is the transaction's instant), and `not_applicable` otherwise. The scrub has run in the same transaction when the targets are written.
- A 004 token erasure adds the `attribution` target only in the first case, so the existing 004 outcome set is unchanged otherwise.

### 6.5 Release barrier (D8)

A person-level read (the runs route) runs in a REPEATABLE READ read-only snapshot and answers `503 attribution_stale` with `Retry-After: 1` unless all of these hold:
- the state is `ready` with no unit in progress, and its checkpoint equals the published ledger position and the current feed watermark;
- the published model-set digest equals the current active set;
- no state-based change is pending (an association revision, a scrubbed conversion or a passed `recheck_at`); the status route reports `caught_up` on the same conditions;
- for an open, unscrubbed conversion: the slot's current candidate is this conversion (same owner, lead still assigned, sale still verified), and recalculating the requested version with `attribute(previous = latest)` returns the stored revision unchanged.

This last check covers consent, tombstones, associations and consent expiry at read time.
- The scope (`identity:read`, and `finance:read` when amounts are included) is resolved again immediately before the response (R0607-14).
- A superseded or scrubbed conversion is released as stored history.

## 7. Lifecycle (D12)

A new attribution step in `run_lifecycle` runs as `tracking_lifecycle`, bounded by the batch size, and reports only non-zero counts:
1. **`attribution_staging`.** For a consumer in `failed` status, delete the rows of its staging generation (credit changes, allocations, runs, then conversions), undo the staged supersessions, then reset the state: `ready` or `building`, unit and failure cleared.
2. **`attribution_scrubbed`.** A safety net: scrub open or superseded conversions whose owner no longer exists.

The identity expiry steps scrub through section 6.2. Nothing in the lifecycle updates a share, amount, currency, reporting date or provenance column, and nothing deletes a published row.

## 8. Model versions and routes

### 8.1 Model versions (D2, D3)

`attribution_models.ensure_defaults(session, agency_id, client_id)` inserts `first_click_30d_v1`, `last_click_30d_v1` and `linear_30d_v1` (default) with `INSERT ... ON CONFLICT DO NOTHING` when the client has no version at all. It runs lazily on the first read of the models, the status or the runs, and on the first pass.

Administration runs as Owner or Admin:
1. `TenancyService._manager(agency_id, write=True)` takes the agency row lock.
2. The client's version rows are then locked `FOR UPDATE`.
3. The idempotency fingerprint is `sha256(json([action, version or request fields, actor membership]))`.
4. A replay with the same fingerprint returns the stored result with 200; a different fingerprint answers 409 `operation_conflict`.
5. Each change writes one audit event.

The rules:
- `window_days` must be an integer from 1 to 90 (`invalid_window`, 422).
- At most 6 versions may be active (`model_version_limit`, 409).
- A duplicate active definition, retiring the default, retiring a retired version, and making a retired version the default each answer `model_version_conflict` (409).

### 8.2 Routes below `/agencies/{agency_id}/clients/{client_id}/attribution`

| Route | Access | Request | Response |
|---|---|---|---|
| `GET /models` | `client:read`; users and read keys with the client grant | | `{versions: [{id, version_key, model, window_days, rules, is_default, status, created_at, retired_at}], default_version_id, active_limit}` |
| `POST /models` | Owner, Admin (browser session) | `{operation_id, model, window_days}` | 201 version; 200 replay |
| `POST /models/{version_id}/default` | Owner, Admin | `{operation_id}` | 201 version; 200 replay |
| `POST /models/{version_id}/retire` | Owner, Admin | `{operation_id}` | 201 version; 200 replay |
| `GET /status` | `client:read`; read keys with the grant | | `{state: caught_up \| behind \| rebuilding, consumer: {generation, status, failure_code, unit, ledger_generation, receipt_ordinal, identity_seq, model_set_current, published_at}, current: {ledger: available \| unavailable \| none, ledger_generation, receipt_ordinal, identity_seq}}` |
| `GET /conversions/{conversion_id}/runs?model_version=` | `identity:read`; never a service key | `model_version` is a version ID, the client default when omitted | `{generation, conversion: {...}, model_version: {...}, runs: [...]}` |

Conversion fields: `id`, `kind`, `status`, `effective_at`, `superseded_at`, `superseded_reason`, `scrubbed`, `person_id`, `lead_event_id`, and `transaction: {state, source_account_id, sale_operation_id}`.

Run fields:
- `revision`, `status`, `basis`, `causes`, `recorded_at`, `window_start`, `window_end`, `currency`, `currency_exponent`, `ledger_generation`, `receipt_ordinal`, `identity_seq`, `touch_bound_exceeded`;
- `amounts` (`available`, `permission_unavailable` or `not_applicable`) and `verified_net_minor`;
- `allocations`: `ordinal`, `credited`, `recipient`, `basis`, `position`, `share {numerator, denominator}`, `amount_minor`, `touchpoint_id`, `evidence_class`, `occurred_at`, `source`, `campaign_ref`, `content_ref`, `link_ref`;
- `differences`: the stored credit changes of the run;
- `excluded`: `[{touchpoint_id, reason}]`.

Without `finance:read`, a sale's `transaction.state`, every run's `amounts`, and the amount fields answer `permission_unavailable` or null; shares, provenance and touches stay. A lead has `amounts: not_applicable`.

Errors: 403 `access_denied` (including an unknown or other-client version or conversion), 409 `operation_conflict`, `model_version_conflict` and `model_version_limit`, 422 `invalid_window` and `validation_failed`, and 503 `attribution_stale` with `Retry-After: 1`. The OpenAPI snapshot gains these paths and schemas only; new schema names avoid every existing component name.

## 9. Test inventory

Module abbreviations:
- `store`: `tests/integration/test_attribution_store.py`
- `privacy`: `tests/integration/test_attribution_privacy.py`
- `api`: `tests/integration/test_attribution_api.py`
- `models`: `tests/integration/test_attribution_models.py`
- `unit`: `tests/test_attribution_persistence.py`

| Case | Test |
|---|---|
| AV01 | `store::test_av01_first_last_and_linear_from_stored_allocations` |
| AV02 | `store::test_av02_unknown_and_unassociated_sales_reconcile_with_the_net`, `store::test_av02_random_journeys_allocate_the_exact_net` |
| AV03 | `store::test_av03_window_boundaries_zones_ties_refund_and_late_touch` |
| AV04 | `store::test_av04_an_identical_pass_stores_nothing`, `store::test_av04_a_new_version_keeps_the_old_history_byte_identical` |
| AV05 | `store::test_av05_incremental_equals_rebuild_after_every_random_step` |
| AV06 | `store::test_av06_refund_release_chargeback_and_correction_revisions`, `store::test_av06_a_held_refund_changes_nothing_until_it_posts`, `store::test_av06_a_ledger_generation_change_rebuilds` |
| AV07 | `store::test_av07_ownership_changes_supersede_without_mutation` |
| AV08 | `privacy::test_av08_withdrawals_remove_touches_from_new_revisions`, `privacy::test_av08_a_surviving_person_keeps_its_history_after_w1`, `privacy::test_av08_erasure_and_expiry_scrub_every_pointer`, `privacy::test_av08_a_replay_after_erasure_restores_no_pointer` |
| AV09 | `privacy::test_av09_marked_events_never_become_touches` |
| AV10 | `privacy::test_av10_identical_references_in_two_clients_never_mix` |
| AV11 | `store::test_av11_two_workers_publish_once`, `store::test_av11_a_stale_checkpoint_never_publishes`, `store::test_av11_a_concurrent_rebuild_wins_once`, `store::test_av11_a_pruned_feed_forces_a_rebuild`, `privacy::test_av11_an_erasure_after_the_snapshot_is_never_restored`, `privacy::test_av11_an_erasure_after_the_snapshot_never_reaches_a_new_conversion` |
| AV12 | `api::test_av12_model_administration_is_owner_admin_and_audited`, `api::test_av12_runs_need_identity_read_and_amounts_need_finance_read`, `api::test_av12_service_keys_reach_models_and_status_only`, `api::test_av12_a_revocation_during_the_request_releases_nothing` |
| AV13 | `store::test_av13_currencies_stay_apart` |
| AV14 | `models::test_av14_populated_upgrade_guarded_downgrade_and_privileges`, `models::test_av14_runtime_role_cannot_rewrite_allocations_or_amounts` |
| AV15 | `privacy::test_av15_lifecycle_scrubs_and_discards_without_touching_money`, `privacy::test_av15_an_event_leaving_retention_is_scrubbed_from_stored_attribution` |
| AV16 | `store::test_av16_pass_transaction_and_touch_bounds`, `store::test_worker_command_prints_counts_only`, `store::test_a_database_error_for_one_client_does_not_stop_the_pass`; measurements `store::test_av16_measurements` (opt-in, `TRACKING_ATTRIBUTION_MEASURE=1`) |
| AV17 | `privacy::test_av17_stale_while_behind_then_released`, `api::test_stale_reads_answer_the_retryable_code` |
| AV18 | the existing suites, unchanged |
| AV19 | `models::test_av19_defaults_and_a_retired_default_is_refused`, `models::test_model_administration_codes_idempotency_and_audit`, `models::test_service_read_keys_reach_the_models_of_granted_clients_only` |
| AV20 | `privacy::test_av20_no_contact_value_token_or_identifier_in_rows_responses_or_logs` |

Unit tests in `unit` (40 cases): slot and conversion keys, the model-set digest, window validation, run reconstruction round trips for every model, basis and kind, the refusal to reconstruct a scrubbed run, and credit-change derivation (initial, differences, moved anchor, closing) over seeded random sequences.

## 10. Resolutions beyond the packet's wording

These follow from the approved decisions, and none changes a product choice. They are listed for the review.

1. **Feed record for a consent change.** The feed did not carry attribution-only consent changes, so neither D9's "next pass" nor D8's watermark comparison would see an attribution withdrawal. `record_consent` now appends `events_changed` for the owners of the subject's active links when the effective attribution state changes, or when identity_link is granted again after it lapsed (`identity.on_consent_changed`). The alternative, a timestamp cursor over consent records, needs a new index and is not gap-safe against a clock step.
2. **Scrub on every person deletion.** D9 names erasure and expiry; D12 says person-linked pointers follow identity retention. A person deleted after a W1 withdrawal therefore also loses its pointers, as F1 already does for every removal kind. A W1 withdrawal that leaves the person in place scrubs nothing.
3. **Input robustness.** `attribution_inputs.touchpoints` adds content provenance and drops an unusable `utm_campaign` value (the touch becomes a direct visit unless it has a managed link). Without this, one malformed URL would make a client's attribution fail.
4. **History-preserving rebuild.** A rebuild recalculates every slot against its stored history in a staging generation that becomes visible atomically. It does not copy history into a new generation and discard the old one, which would break D3 ("keeps its history") and AV04. Staged rows are discarded only when the rebuild fails, by the lifecycle step, because the runtime role has no `DELETE`.
5. **Additional columns.** `binding_id`, `recheck_at`, the allocation rows for uncredited eligible touches, the unit and sweep fields of the consumer state, and `operations` on model versions are needed for change detection, exact revisions, resumable bounds and idempotency. They hold no contact value, token or raw identifier.
6. **Lead credit.** A lead conversion is the trusted `lead_signal` event itself. Its later attribution consent does not remove it, because consent governs touches. Its owner's merges, unmerges, W1 and erasure do.
7. **One client's error.** A database error in one client's pass is counted as `unavailable` and logged as the registered event `attribution_client_failed`, without any value; the pass continues with the next client, and the failed client stays behind, so its readers keep answering `attribution_stale`.
