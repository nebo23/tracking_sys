# Review register for the Spec 006 preparation

This register records three independent reviews of the Spec 006 preparation and the corrections made for them. Owner decisions D1–D13 remain pending. Each evidence section describes the revision it names, and the tables of an earlier review describe that revision's corrections; where revision 4 changed one of them, the row says so.

## First review: published head `b9801de`

Reviewed the published branch head `b9801de` against merged `main` at `c251e20` on 2026-11-11. The published diff contains 13 documentation files. Revision 2 changed the proposal and its planned acceptance cases.

| Finding in revision 1 | Consequence | Proposed correction and verification |
|---|---|---|
| **R006-01 · P1** The raw-token path assumes the subject was created by the server. Existing collection subjects have no issuance-channel field. A handoff code also identifies a browser without identifying the client's verification transaction. | A trusted sender can associate the wrong browser or verified session with a person. | Record immutable issuance for new subjects. Require server issuance and the identity grant receipt for direct assertions. Bind a browser handoff to a backend session challenge. Verify legacy tokens, different sessions and a re-grant in C4/C5. |
| **R006-02 · P1** Open-ended segments derive their end from the next surviving link. An ambiguous assertion creates no owned link, and erasure can remove the link that marked a switch. | A prior user can acquire later events on a shared device. Expiry followed by re-grant also leaves an unconsented interval. | Store closed bounds, handle explicit denial and require fresh evidence after a gap. Invalidate pending tracker work at a known switch. Verify both erasure orders, ambiguous evidence and late responses in I4/I10/I11, P3/P4 and E2. |
| **R006-03 · P1** The erasure instructions include all persons merged into the target. The existing helper takes a token or event ID. A profile lookup supplies neither for an eventless subject. | An incorrect merge can destroy another person's history. An exclusive subject with zero events can survive a deletion marked complete. | Resolve original ownership, pause ambiguous scope and pass an authorized scoped subject to the internal erasure helper. Keep token-holder erasure limited to its device subject. Exercise E1–E4 and E6. |
| **R006-04 · P2** The first matching step rejects a consumed handoff before the documented duplicate check. | A committed assertion whose response was lost cannot be retried reliably. | Check replay tombstones and the authenticated receipt before requiring unused proof. A new operation still needs valid proof. C4 covers lost responses, expiry, cleanup and conflicting retries. |
| **R006-05 · P2** The inherited phone helper removes arbitrary characters. The proposed HMAC inputs also omit the normalizer version. | Invalid input can match a real number. A version label stored beside the digest cannot separate equal canonical strings. | Validate international input before the helper and use the normalizer label in the HMAC. Keep deletion checks compatible with retained versions. I8/I9 cover both. |
| **R006-06 · P2** Matching leaves contested-plus-new evidence unspecified. The reversal API omits expected versions, admits merge chains with only one edge ID on a link, and can lose the active ledger after two years. | Two implementations can assign different owners or produce different journeys after reversal. | Exclude contested anchors. Propose disjoint merge pairs in v1, bind reversals to a live edge and both versions, and retain active evidence for reversal. See I12 and M1/M2. |
| **R006-07 · P2** The change feed lists identity actions only. Event arrival, upgrade and expiry can change the timeline, and a consumer may miss the whole 30-day feed. | Downstream attribution can silently keep the old result, including after erasure. | Publish per-person revisions in the same transaction, preserve the feed watermark and rebuild a stale consumer's partition. Verify T1/M3. Specification 008 owns execution of the attribution calculation. |
| **R006-08 · P2** The write-only ingest role receives a person ID, and the first migration includes identity grants and merge structures before the original slice gates require D8/D10. | A writer learns person-level information, and partial approval could implement an unreviewed schema choice. | Use generic write acknowledgements, exercise the full invitation and grant path (P6), and align the migration gate with the choices represented in 0009. |

### Evidence for revision 2

- Read the merged [collection model](../../backend/app/models/collection.py), [consent, admission and erasure services](../../backend/app/services/collection.py), [lifecycle runner](../../backend/app/services/lifecycle.py), [access resolver](../../backend/app/services/access.py), [identity and deletion helpers](../../backend/app/privacy/deletion.py), and [tracker](../../packages/tracker-js/src/tracker.js). Checked relevant behavior against specifications 003–005.
- In the project virtual environment, the merged helper produced `+201000000101` for both the fictional input `+20 10 0000 0101` and malformed `+20oops10 0000 0101`. Model and function inspection confirmed the missing issuance field and the token/event-only erasure lookup.
- The inherited unit suites `test_privacy_deletion.py`, `test_privacy_consent.py` and `test_collection_contract.py` passed **77 tests**. The new 006 cases describe future behavior. No 006 application code or migration exists in the reviewed diff.

## Second review: revision 2 (`2274e6e`)

The second review accepted the direction of revision 2 and identified six remaining gaps. Revision 3 corrects them.

| Finding in revision 2 | Consequence | Correction in revision 3 |
|---|---|---|
| **R006-09** A single confirmed link was treated as evidence for whole-device erasure. | Erasing Sara could destroy events of an Omar/Ali interval whose evidence excludes her, and tombstone a shared token. | Persist ambiguous segments and a write-once shared marker. Classify each event as confirmed, excluded or unresolved for the person. Erase a subject whole only when exclusive; otherwise erase confirmed events, keep excluded ones and hold unresolved ones with the request `on_hold` until an Owner/Admin decides. |
| **R006-10** Reversal handled only links whose own evidence spans both participants. | A device linked only through a key created from the merged evidence would stay attributed after reversal. | Record the merge ID on every key and link whose anchoring evidence spans both participants or includes a merge-dependent key. Reversal re-evaluates these items with R5, so the dependent device leaves both timelines and an independent device stays attributed. |
| **R006-11** A rebuild copied current state and then stored a later watermark. | A concurrent erasure could be skipped permanently by the consumer. | Add `identity_feed_state`. Read the watermark and source rows in one `REPEATABLE READ` snapshot, publish the generation and checkpoint together, replay later records, and restart an interrupted rebuild from a new snapshot. |
| **R006-12** Proof routes were specified for some issuance channels only. | The public handoff could become an alternative route for a server-held token, and legacy rows had no defined behavior. | A six-cell matrix of `browser`, `server` and `unknown` issuance against handoff and direct-token proof. Only browser handoff on `browser` and direct token on `server` link. Legacy rows use neither route, with the cost and the alternative under D3/D11. |
| **R006-13** Suppressed assertions returned 422 with `replay_before_deletion`, `no_consent_after_deletion` or `subject_objected`. | A sender could learn an identifier's deletion or objection history from the status or body. | Every well-formed, authenticated, fresh and proven assertion receives 201 `accepted`. Tombstoned assertion IDs answer exact retries and conflicts exactly as live receipts, using a new `assertion_request` tombstone. Exact reasons stay internal. Revision 4 replaces the tombstone-based answer with a bounded retry receipt and renames the type `assertion_fp` (R006-15, R006-19). |
| **R006-14** `version` and `journey_revision` were not distinguished, and versions did not change on merge or reversal. | A request built on pre-merge versions could act again after a merge and its reversal. | `version` starts at 1 and increments for both participants on every successful merge or reversal; `journey_revision` is the downstream signal. Failures and exact retries change neither. The stale request returns 409 and the exact retry its recorded result. |

### Remaining gaps of R006-01 to R006-08 closed in revision 3

| Finding | Gap left in revision 2 | Correction |
|---|---|---|
| R006-01 | Challenge format and reuse were unspecified; the handoff route accepted any issuance; the worked A3 row omitted the challenge. | Challenges of at least 128 random bits, unique per client; the handoff route requires `browser` issuance; A3 uses handoff H3 with its session challenge. |
| R006-02 | Nothing persisted prevented a later link from reaching back over an erased or closed interval. | Monotonic `identity_floor_at`, raised at every closure and erasure; retrospective linking only when no closure or erasure occurred during the grant. |
| R006-03 | Pausing and partial completion did not use the 003 request states. | Two stages: `paused_for_clarification` before any deletion for an unresolved target; `on_hold` with a pending `unresolved_events` target after deleting confirmed scope. |
| R006-04 | The processing order was split across sections, and validation could depend on earlier use of the ID. | One ordered list (design section 4.2): validation, lock and keys, retry recognition, freshness, proof, consent, tombstones, matching, segments, commit. |
| R006-05 | The grammar was described in prose without the observed failure cases. | An exact ASCII grammar, a table of actual helper outputs for six inputs, and I9 vectors for each. |
| R006-06 | The retention cost of active edges and the effect of lifecycle removal of a participant were not stated. | Cost paragraph in design section 12.5 under D10/D12; lifecycle closure of the edge (generalized to every loss path in revision 4, R006-18); concurrent reversals in M2. |
| R006-07 | The watermark had no defined storage, so the feed count was eight tables. | `identity_feed_state` with `last_seq` and `pruned_through_seq`; nine tables in revision 3 (eleven in revision 4). |
| R006-08 | The 006-A gate named decisions without showing which 0009 elements encode them. | A table mapping every 0009 element to its decisions in the decision packet. |

## Third review: revision 3 (`e264ae1`)

The third review found eight remaining defects in revision 3. Revision 4 corrects them and keeps the corrections for R006-01 to R006-14. New schema and retention choices stay proposals under D7, D11 and D12.

| Finding in revision 3 | Consequence | Correction in revision 4 |
|---|---|---|
| **R006-15** The proposed tombstone type `assertion_request` has 17 characters; `deletion_tombstones.match_type` is `VARCHAR(16)`. | The first erasure that writes this tombstone would fail in the database. | Use `assertion_fp` (12 characters) throughout. All proposed values were checked against the merged column widths. DB1 inserts and reads back every tombstone type after 0009. |
| **R006-16** Unresolved events of an erasure were held without recording which events they were. | After the person and evidence are deleted, the held set cannot be recomputed; a restart or a second request could resolve the wrong events. | `identity_erasure_holds` records client, request and exact event in the erasure transaction, before any deletion. A resolution settles only its own recorded rows. Expiry, erasure elsewhere and two pending requests are defined, and retaining for one request never restores an event or completes another request (E6). |
| **R006-17** A suppressed assertion for another person left the previous owner's segment open. | The objecting or erased person's later page views were added to the previous owner's journey, and the device could later count as exclusive to that owner. | The suppressed assertion ends the open segment at server receipt time and starts a neutral segment that names nobody; the floor rises and the shared marker is set. No link to the objecting person is stored and the acknowledgement stays generic (I13). |
| **R006-18** Only lifecycle expiry closed an active edge when a participant lost its last evidence. | Withdrawal or token-holder erasure could delete a participant under an active edge, leaving a dangling pointer and dependent items attributed to the other person. | One transactional rule (design section 10.4) for expiry, withdrawal and token-holder erasure: close the edge, clear the pointer, re-evaluate dependent keys and links, update the remaining participant's version, revision and feed, then remove the participant (M4). |
| **R006-19** Permanent `assertion_request` tombstones determined public retry answers indefinitely, while withdrawn assertions answered differently from erased ones. | The public status depended on permanent deletion records, and retry behavior differed by what had happened to the assertion. | A minimal keyed retry receipt (assertion ID, fingerprint, expiry) answers exact and changed retries for a proposed 24 hours, identically for ordinary, suppressed, withdrawn and erased assertions. Afterwards only the request's own freshness and proof decide the answer; tombstones only block writes (E3, C4). |
| **R006-20** The worked M1 assertion carried two emails. | The API rejects two identifiers of one kind with 422, so the reversal test could not run. | D4 asserts A's email, B's phone and a new `customer_ref` K by `account_login`; neither person owns a customer reference. M1 first checks that the assertion passes validation. |
| **R006-21** "Closed interval" was used both for an ended owned segment and for an unassigned interval. | A reader could conclude that ending Sara's segment unassigns her earlier events. | Design section 4.4 separates owned segments (events stay confirmed after the segment ends), unassigned intervals and erased intervals, with a worked event table that I10 and E2 follow, including the boundary timestamp and late arrivals. |
| **R006-22** Normal replay read the feed state and the batch separately and stored `last_seq` as the checkpoint. | Pruning between the two reads could remove a record, for example an erasure, that the consumer then skipped permanently. | Replay reads state and batch in one snapshot or verifies contiguity from `c + 1`, advances only to the last contiguous record applied, rebuilds on a gap, and commits derived changes with the checkpoint under a stale-worker guard (M3). |

## Finding coverage

| Finding | Design sections (revision 4) | Decisions | Acceptance cases |
|---|---|---|---|
| R006-01 | [4.1](design.md#41-evidence-sources), [4.2](design.md#42-deterministic-matching-within-one-client) steps 5–6, [8](design.md#8-tracker-additions-specification-005-package), [8.1](design.md#81-proof-route-by-issuance-channel), [12.1](design.md#121-schema-migration-0009_identity_journey-proposed) | D3, D11 | I1, P1, C4, C5 |
| R006-02 | [4.4](design.md#44-shared-device-and-account-switching), [6](design.md#6-consent), [7.2](design.md#72-what-erasure-removes), [8](design.md#8-tracker-additions-specification-005-package) | D5, D6, D7 | I4, I10, I11, P3, P4, E2 |
| R006-03 | [7.2](design.md#72-what-erasure-removes), [7.3](design.md#73-minimal-replay-protection), [12.2](design.md#122-api-proposed-11-operations) | D7 | E1–E4, E6 |
| R006-04 | [4.2](design.md#42-deterministic-matching-within-one-client) steps 1–3, [12.2](design.md#122-api-proposed-11-operations), [12.4](design.md#124-transactions-ordering-and-idempotency) | D2, D3, D7 | C4, E3 |
| R006-05 | [5](design.md#5-canonicalization-and-normalization-versions), [5.1](design.md#51-review-of-the-candidate-trunk-zero-rule) | D4 | I8, I9 |
| R006-06 | [4.2](design.md#42-deterministic-matching-within-one-client) R5, [10.1](design.md#101-rules), [10.3](design.md#103-ownership-during-a-merged-period), [12.5](design.md#125-data-classes-and-retention-development-provisional) | D5, D10, D12 | I12, M1, M2 |
| R006-07 | [11](design.md#11-recalculation-and-handoff-to-007008), [11.1](design.md#111-feed-state-and-consistent-rebuild) | D10, D11 | T1, M3 |
| R006-08 | [7.1](design.md#71-tenant-scope), [12.2](design.md#122-api-proposed-11-operations), [12.3](design.md#123-permissions); [006-A gate](decision-packet.md#decisions-that-actually-block-the-next-step) | D8, D11 | P6, DB1 |
| R006-09 | [4.4](design.md#44-shared-device-and-account-switching) event classes, [7.2](design.md#72-what-erasure-removes) | D5, D7 | E2, E6 |
| R006-10 | [10.2](design.md#102-worked-mistaken-merge-synthetic), [10.3](design.md#103-ownership-during-a-merged-period), [12.1](design.md#121-schema-migration-0009_identity_journey-proposed) | D10 | M1 |
| R006-11 | [11.1](design.md#111-feed-state-and-consistent-rebuild), [12.1](design.md#121-schema-migration-0009_identity_journey-proposed) | D10, D11 | M3 |
| R006-12 | [8.1](design.md#81-proof-route-by-issuance-channel), [12.1](design.md#121-schema-migration-0009_identity_journey-proposed) | D3, D11 | C5 |
| R006-13 | [4.2](design.md#42-deterministic-matching-within-one-client) step 7, [7.1](design.md#71-tenant-scope), [7.3](design.md#73-minimal-replay-protection), [12.2](design.md#122-api-proposed-11-operations), [12.4](design.md#124-transactions-ordering-and-idempotency) | D2, D7 | E3, E4, P6 |
| R006-14 | [9.1](design.md#91-profile), [10.1](design.md#101-rules), [10.2](design.md#102-worked-mistaken-merge-synthetic), [12.2](design.md#122-api-proposed-11-operations), [13](design.md#13-example-api-responses-synthetic-outcome-a) | D10 | M2, M1, I1 |
| R006-15 | [7.3](design.md#73-minimal-replay-protection), [12.1](design.md#121-schema-migration-0009_identity_journey-proposed) | D7, D11 | DB1, E1 |
| R006-16 | [7.2](design.md#72-what-erasure-removes) held events, [12.1](design.md#121-schema-migration-0009_identity_journey-proposed), [12.5](design.md#125-data-classes-and-retention-development-provisional) | D7, D11, D12 | E6 |
| R006-17 | [4.2](design.md#42-deterministic-matching-within-one-client) step 7, [4.4](design.md#44-shared-device-and-account-switching) suppressed switch | D5, D7 | I13, E4 |
| R006-18 | [10.4](design.md#104-loss-of-a-merge-participant), [6](design.md#6-consent), [7.2](design.md#72-what-erasure-removes), [12.4](design.md#124-transactions-ordering-and-idempotency) | D7, D10, D12 | M4 |
| R006-19 | [4.2](design.md#42-deterministic-matching-within-one-client) steps 3 and 7, [7.3](design.md#73-minimal-replay-protection), [12.2](design.md#122-api-proposed-11-operations), [12.4](design.md#124-transactions-ordering-and-idempotency), [12.5](design.md#125-data-classes-and-retention-development-provisional) | D7, D12 | E3, C4, P3 |
| R006-20 | [10.2](design.md#102-worked-mistaken-merge-synthetic) | D10 | M1, I8 |
| R006-21 | [4.4](design.md#44-shared-device-and-account-switching) kinds of time and worked event table | D5 | I10, E2, I4, P4 |
| R006-22 | [11.1](design.md#111-feed-state-and-consistent-rebuild) normal replay | D10, D11 | M3 |

## Evidence for revision 3

Checked on `codex/spec-006-identity-journey` from `182f51b` (merged `main` at `c251e20`) on 2026-11-11. The change set contains documentation only; no application code, migration, dependency or native database was touched.

- **Inherited checks, executed.** From `backend/`, in the project virtual environment (Python 3.12.4) with inherited `TRACKING_`, `PG` and `PYTHON` variables removed, `python -m pytest -q tests/test_privacy_deletion.py tests/test_privacy_consent.py tests/test_collection_contract.py` reported **77 passed** in 0.13 s. These suites exercise the merged 003/004 contracts that 006 inherits.
- **Phone helper probe, executed.** `canonical_identifier("phone", value)` from the merged `app.privacy.deletion` produced the six outputs tabled in [design section 5](design.md#5-canonicalization-and-normalization-versions) for fictional inputs.
- **Re-read merged contracts.** `erase_subject` still accepts only `subject_token` or `event_id` and tombstones the whole subject. The 003 request states already provide `paused_for_clarification` before acceptance and `on_hold` with pending targets after it, which design section 7.2 uses. Admission, consent writes, erasure and lifecycle runs all take the transaction-scoped client lock, which design section 11.1 relies on.
- **Document checks, executed.** A temporary script, removed after use (D-010), checked the 006 documents, `docs/planning/review-next.md` and `README.md`: 131 local links and fragments resolve, 47 tables have consistent column counts, 4 JSON examples parse, the 37 case IDs are unique, every decision D1–D13 is cited by at least one case, and every finding R006-01 to R006-14 maps to existing cases. `git diff --check` reported no problems.
- **Planned, not executed.** Every case in the [verification matrix](verification-matrix.md), including the new and extended E2, E3, E4, E6, M1, M2, M3, C4, C5, I9 and P6, describes future 006 behavior. No 006 implementation exists to run them against.

## Evidence for revision 4

The inherited unit suites `test_privacy_deletion.py`, `test_privacy_consent.py` and `test_collection_contract.py` passed 77 tests. Document checks validated the internal links and fragments, Markdown table widths, four JSON examples, 39 distinct planned cases and the mapping of findings R006-01 through R006-22. `git diff --check` passed. The 006 behavior remains specified for future implementation.

## Deferred at merge

D-042 authorizes progression with these revision 4 findings open. Revisit them when implementing the affected contracts.

| Finding | Follow-up |
|---|---|
| R006-23 | Align the erasure hold's scoped foreign key with a unique key on the collected event. |
| R006-24 | Preserve a held or retained event's anonymity through a trusted event upgrade. |
| R006-25 | Define independent evidence for a merge participant without counting links that depend on the same merge. |
| R006-26 | Specify atomic renewal of expired retry receipts and distinguish ordinary expiry from early handoff removal in C4. |
| R006-27 | Distinguish provisionally linkable pre-identification time from permanently unassigned intervals. |
| R006-28 | Guard rebuild publication against changes to both the consumer generation and its checkpoint. |

The choices that most affect the owner are legacy subject handling (D3/D11), shared-device erasure of unresolved events and the table that records them (D5/D7/D11), the retry window and its short-lived receipt (D7/D12), and the unlimited retention of active merges (D10/D12). Their costs and alternatives are in the [decision packet](decision-packet.md).
