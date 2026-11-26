# Persisted attribution

Specification 008-B, implemented under D-079 on `codex/spec-008-attribution-persistence` (migration `0029_attribution_persistence`).
- Design: [design note](../../specs/008-attribution-engine/design-008b.md) over the [entry review](../../specs/008-attribution-engine/entry-review-008b.md).
- Evidence: [008-B evidence](../../specs/008-attribution-engine/evidence-008b.md).
- The calculation is the unchanged 008-A engine (`app.attribution.attribute`).
- Its inputs are the identity journey, the persisted ledger and the sale associations described in the [identity and ledger guide](identity-and-ledger.md).
- Every example below is synthetic.

## What is stored

Every verified sale of the published ledger and every trusted `lead_signal` (trust rank 2) assigned to a person is a **slot**. A **conversion** is one slot with one owner: the visible root of the person who owns it, or none for an unassociated sale.

Every conversion is calculated under every active model version of its client, and each change of outcome is stored as an immutable revision:

| Table | Content |
|---|---|
| `attribution_model_versions` | Per client: model (`first_click`, `last_click`, `linear`), a window of 1 to 90 whole days, the `008-A.1` rules, the default flag and retirement. |
| `attribution_conversions` | Kind, slot, owner, the sale key or the lead event, the anchor, and `active` or `superseded` with a closed reason. |
| `attribution_runs` | One revision of one conversion under one version: status, basis, causes, the verified net in original-currency minor units, the window, the observed ledger position and feed sequence, and the excluded touches. |
| `attribution_allocations` | One row per eligible touch in the engine's order (credited or not), or one unknown row: exact share numerator and denominator, amount, touchpoint, and campaign, content, link and source provenance. |
| `attribution_credit_changes` | The signed reporting ledger of every revision (see [Reading credit](#reading-credit-016-b)). |
| `attribution_consumer_state` | One row per client: the published generation, its checkpoint over the ledger journal and the identity feed, the unit of work in progress and counters. |

**Conversion identity.**
- An owner change supersedes a conversion and opens a successor; the old conversion is never mutated. Owner changes are an association, a detach, a merge, an unmerge, an erasure and an F1 unlinking.
- The successor's `conversion_key` is the slot digest followed by its ordinal in the slot, so a returning owner gets a new key.
- An unassociated sale credits `unknown` with its full net, so attributed revenue always reconciles with ledger revenue.

## Model versions

Every client starts with `first_click_30d_v1`, `last_click_30d_v1` and `linear_30d_v1`. Linear is the default (Q-007, D-079). The defaults are seeded lazily, the first time the client's models, status or runs are read or the client is processed.

Routes below `/agencies/{a}/clients/{c}/attribution`:

| Route | Who | Body |
|---|---|---|
| `GET /models` | `client:read`; read keys with the client grant | |
| `POST /models` | Owner/Admin session | `{"operation_id": "...", "model": "linear", "window_days": 7}` |
| `POST /models/{version_id}/default` | Owner/Admin session | `{"operation_id": "..."}` |
| `POST /models/{version_id}/retire` | Owner/Admin session | `{"operation_id": "..."}` |

Answers:
- `201` for a new change, and `200` with the stored result for a replay.
- `409 operation_conflict` for a reused operation ID with another request.
- `409 model_version_conflict` for a duplicate active definition, a retired version, or retiring the default.
- `409 model_version_limit` above six active versions, and `422 invalid_window` outside 1 to 90 days.

Each change writes one audit event: `attribution.model_created`, `attribution.model_default_set` or `attribution.model_retired`.

A retired version keeps its history and receives no new revision. Re-adding a retired definition creates a new version, for example `linear_7d_v2`, with its own history. Adding or retiring a version changes the active set, so the next pass rebuilds.

## The worker

```
python -m app.attribution_worker
```

It runs one bounded pass over every active client as `tracking_app`, and prints one JSON line of counts:

```json
{"clients": 4, "caught_up": 4, "rebuilds": 4, "slots": 1, "opened": 1, "revisions": 3, "swept": 1}
```

Other keys:
- `bounded`: the pass bound was reached, and the next pass continues;
- `conflict`: another worker or a removal won the compare-and-swap, so nothing was written;
- `ledger_unavailable`: the published ledger is behind its evidence, and nothing changed;
- `failed`: an engine refusal (see [Failure](#failure));
- `unavailable`: a database error stopped that client; the event `attribution_client_failed` is logged, and the pass continues;
- `superseded`.

There is no scheduler: stored attribution is as fresh as the last invocation, and production scheduling is Spec 020.

**Bounds (D11).**
- At most 2,000 slots per client and pass, in transactions of at most 200.
- At most 1,000 receipts and 500 feed records per incremental unit.
- At most 200 open conversions verified again by the sweep of a caught-up pass.
- A person whose linked collection subjects hold more than 5,000 unmarked events gets no touches: the run credits unknown and is marked `touch_bound_exceeded`.

**What a pass does.**
- An incremental unit recalculates the slots named by new ledger receipts and feed records, up to a fixed target. It also recalculates the slots whose stored state no longer matches what the feed does not report: changed association revisions, scrubbed conversions, and consent grants that expired (`recheck_at`).
- A rebuild unit recalculates every slot in a staging generation that is invisible until it is published atomically. It starts for a client's first pass, a new active model set, a new ledger generation, or a pruned or gapped feed. It recalculates against the stored history, so unchanged outcomes store nothing and old revisions stay byte-identical.
- Each chunk is one REPEATABLE READ transaction. It calculates first; its first write is the compare-and-swap on the consumer state.
- The worker takes no advisory lock and no row lock on an identity, ledger or association row.

**Change signals.** Since 008-B, a consent change marks the owners of the subject's active links changed in the identity feed (`events_changed`), so attribution follows on the next pass. This covers a change of the subject's effective attribution grant, and a new identity_link grant after it lapsed. `associate()` and `detach()` need no feed record; the pass compares the open association revisions with the ones the conversions recorded.

### Failure

An engine refusal (a closed `AttributionInputError`) sets the client's consumer to `failed` with its code. The worker then skips the client. The lifecycle runner discards the failed staging rows and resets the state, and the next pass starts again from the published state.

`stale_ledger_position` is not a refusal: it means another worker published first, and it counts as a conflict.

## Reading

| Route | Who | Answer |
|---|---|---|
| `GET /status` | `client:read`; read keys with the client grant | `state` (`caught_up`, `behind`, `rebuilding`), the consumer's generation, status, failure code, unit and checkpoint, and the current ledger and feed watermarks |
| `GET /conversions/{conversion_id}/runs?model_version=` | `identity:read`; never a service key | The conversion and every stored revision under one version (the client default when none is named), with allocations, differences and excluded touches |

**The runs route is a person-level read.**
- It is built in a REPEATABLE READ snapshot and answers `503 attribution_stale` with `Retry-After: 1` unless the consumer is caught up.
- For an open, unscrubbed conversion it also refuses unless recalculating the conversion from the current inputs changes nothing. That check covers consent withdrawal and expiry, tombstones and association changes, which move no watermark.
- Superseded and scrubbed conversions are released as stored history.
- The reader's scope is resolved again just before the response.

**Finance.** Without `finance:read`, a sale's `transaction.state`, the run's `amounts` and the amount fields answer `permission_unavailable` or null. Shares, touches and provenance stay. A lead has `amounts: not_applicable`.

## Reading credit (016-B)

Summing one model version's credit changes by provenance and `effective_at` gives the current credit. Restricting the sum to `recorded_at <= T` gives the credit as of `T`.

- Read only rows with `generation <= ` the published generation of the consumer state, so a rebuild in progress is never half-visible.
- An initial revision books its allocations, and a later one books the engine's signed differences.
- A later revision whose anchor moved reverses the old allocations at the old date and books the new ones at the new date.
- A superseded conversion's closing revision reverses its credit, so a sale is credited exactly once.
- Amounts stay in their original currency: never add rows of different currencies.

```sql
SELECT campaign_ref, content_ref, currency,
       SUM(delta_minor) AS credited_minor
FROM attribution_credit_changes
WHERE client_id = :client AND model_version_id = :version
  AND generation <= :published_generation
  AND effective_at >= :from AND effective_at < :to
GROUP BY campaign_ref, content_ref, currency;
```

Shares are exact fractions. Sum `delta_share_numerator / delta_share_denominator` exactly, for example in Python with `fractions.Fraction`, not as floating-point values.

## Privacy

**Withdrawal.** An attribution withdrawal, or a W1 withdrawal that leaves the person in place, removes the touches from the next revision and keeps the earlier revisions (D9).

**Erasure and expiry.** These scrub in the removal transaction, after the F1 unlinking:
- `remove_person` (any kind; a removed person keeps no pointer);
- `drop_subject_evidence` for erasure and expiry;
- the person erasure (its confirmed and held events);
- the identity lifecycle steps for expiring links and for events leaving retention.

**What the scrub changes.**
- It clears the person, the lead event, the person-derived keys and every touchpoint ID and touch instant of the affected conversions, across their runs, allocations and credit changes.
- Shares, amounts, currencies, reporting dates and provenance never change.
- The next pass supersedes a scrubbed conversion (reason `scrubbed`) and opens its successor from the current inputs, so a replay never restores a pointer.

**Ordering against the worker.** Every removal first changes the client's consumer state row, then scrubs:
- a worker whose snapshot predates the removal loses its compare-and-swap;
- a worker that already holds the row finishes its short write phase first, and the scrub then sees those rows.

The erasure request reports the target `attribution` as `done` when the transaction scrubbed a stored conversion, and `not_applicable` otherwise. A 004 token erasure adds the target only in the first case.

## Retention (development, D12)

The lifecycle runner adds two steps, reported only when non-zero:
- `attribution_staging` deletes the rows of a failed consumer's staging generation and resets the state.
- `attribution_scrubbed` scrubs a conversion whose owner no longer exists, as a safety net.

Person pointers otherwise follow identity retention through the identity steps above. The non-identifying credit history and the model versions follow the workspace-lifetime financial policy. Q-012 stays open for real data.

## Limits

- A3 stays open: these are measurements, not SLOs. A pass at 1,000 conversions took about 16 seconds, and a rebuild about 15 seconds, on the development workstation (see the evidence).
- No route lists conversions; 016-B reports will expose them.
- A campaign, content or link change that no signal reports is repaired by the sweep, which verifies at most 200 conversions per pass. Until then, the runs route answers stale for the affected conversion.
- The native `tracking_sys` migration, live providers, 016-B/C and the React UI are not part of 008-B.
