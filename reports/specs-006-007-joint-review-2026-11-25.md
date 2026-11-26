# Independent review of the combined 006 and 007-B/C branch

Reviewed on 2026-11-25 at the owner's request to review the changes independently. The branch's own suites pass, but the review reproduced nineteen defects that those suites do not exercise: three P1, eight P2 and eight P3. Most concern consent withdrawal, erasure, retention and the sale-to-person association. Correct at least the P1 and P2 findings, with the companion regressions, before a pull request or merge decision. This report is not merge approval, and it changes no application code.

Status (2026-11-25, D-076): the owner authorized the correction of all nineteen findings with the recommended options for R0607-10 and R0607-11. They are corrected on the reviewed branch; see the [correction evidence](../specs/006-identity-journey/joint-evidence.md#review-corrections-d-076-2026-11-25).

## Reviewed revisions and boundaries

- **Branch:** `codex/spec-006-007-identity-ledger`.
- **Head:** `8b03b1c3721b52146edec63b17073672658dd95b`, the phases P1-P5 of D-075.
- **Base:** merged `main` `81977a38110458a75838baa47c73029a0495c2ae` (PR 14). The branch contains `main` unchanged, so it merges without conflicts.
- **Scope:** the approved packet of D-074 and D-075 at that head:
  - [J1-J12](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/specs/006-identity-journey/joint-entry-review.md);
  - the [joint design addendum](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/specs/006-identity-journey/joint-design.md);
  - the [joint verification matrix](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/specs/006-identity-journey/joint-verification.md);
  - 006 design revision 4;
  - the [joint evidence](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/specs/006-identity-journey/joint-evidence.md).
- **Method:**
  1. Four focused code reads ran in parallel: ledger persistence, the identity core, identity administration and lifecycle, and the sale association.
  2. Every candidate was then reproduced on a disposable database or in the tracker's fake environment.
  3. Only reproduced behavior is reported as a finding. Candidates that were not executed are listed separately.
- **Environment:**
  - Linux, Python 3.12.3 and the hash-pinned `backend/requirements*.txt` in the project `.venv`.
  - A disposable `postgres:18.6-bookworm@sha256:5c4783a8…a2c8` container: Compose project `tracking-review-0607` on `127.0.0.1:55433`, with synthetic passwords and the repository's restricted-role initialization.
  - Inherited `TRACKING_`, `PG` and `PYTHON` variables were removed, and only synthetic settings were supplied.
- **Not touched:** the owner's native `tracking_sys`, `.env` and provider credentials. No provider was called, and nothing was pushed to the reviewed branch.

## Verification results

| Check | Result |
|---|---|
| `ruff check app tests migrations`; `ruff format --check` | Clean; 265 files formatted |
| `git diff --check 81977a3 8b03b1c` | Clean |
| `pytest -m "not integration"` | **886 passed**, 580 deselected |
| `pytest -m integration` (47 modules, 580 cases) | **577 passed, 3 skipped**, 918 s; the skips are the browser journeys, which need `TRACKING_RUN_BROWSER_TESTS=1` |
| Browser journeys with `TRACKING_RUN_BROWSER_TESTS=1`, Chromium only | **2 passed** (journey and payload parity); the Firefox case was not run |
| Tracker unit (`node --test test/unit/*.test.js`) | **71 passed** |
| Tracker browser, Chromium only | **25 passed**; the 25 Firefox cases were not run |
| OpenAPI, compared semantically with `main` | All 102 existing paths unchanged; 17 paths added. Of the existing schemas, only `ClientGrantInput` and `FinancialGrant` changed, each gaining the optional `can_view_identities`; 11 schemas added |
| Migrations | One head, chained `0025_whatsapp`, then `0026`, `0027`, `0028`; the populated-upgrade and guarded-downgrade tests pass |
| Review regressions (companion patch) | **22 failed** at `8b03b1c` as intended and 1 opt-in measurement was skipped. Tracker review test: **2 failed** as intended |

Browser downloads are blocked in the review environment. The Chromium runs therefore used the pinned Playwright 1.64.1 with the pre-installed Chromium build through an `executablePath` preload, a version mismatch. Firefox was not available, and the Firefox results remain those of the branch's own evidence.

## Findings

Priorities:
- **P1:** a data-subject right refused, another person's data deleted, or the retention run stopped.
- **P2:** wrong results, or refused requests, against an approved rule.
- **P3:** narrower conditions or operator-only paths.

Sources link to the reviewed head. Each regression is in the [companion patch](specs-006-007-joint-review-regressions.patch).

### R0607-01 P1 Consent withdrawal and erasure fail when an ambiguous segment loses its last candidate

**Withdrawal.**
1. Two persons, A and B, share a family email but have different customer references, so the email is contested.
2. A third device asserts the email alone, which opens an ambiguous segment with candidates A and B.
3. Withdrawing `identity_link` for A's device succeeds. The same withdrawal for B's device answers `409 state_conflict`.

**Erasure.** In the design 7.2 tablet example, erasing Omar puts the request on hold, and erasing Ali then answers `409`.

**Cause.** `remove_person` removes the person from `identity_links.candidate_ids` with `array_remove` before converting the segment. This violates `ck_identity_links_ambiguous_candidates` (an ambiguous link needs at least one candidate).

**Effect.**
- The whole transaction rolls back, so the visitor's withdrawal is never recorded, and every retry fails the same way.
- The same path runs in the lifecycle persons sweep. It also lets an assertion insert an ambiguous link with no candidates.

**Rules:** J3 (withdrawal acts transactionally on every path), J6, and design 7.2.

**Correct by:** converting or closing a segment, key or assertion that loses its last candidate in the same step; never storing an ambiguous record without candidates; covering the lifecycle path.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity.py#L515-L582), [constraint](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/migrations/versions/0026_identity_journey.py#L561-L565). Regressions: `test_review_r0607_01_withdrawal_of_the_last_ambiguous_candidate`, `test_review_r0607_01_erasure_of_the_last_ambiguous_candidate`.

### R0607-02 P1 Erasure deletes another person's data on a device that was never marked shared

**Case 1: a device reassigned by unmerge.**
1. During a merge of S8 into S7, S7's device D1 asserts S8's phone and a merge-dependent reference.
2. Reversing the merge reassigns D1's open segment to S8. An event on D1 then belongs to S8.
3. Erasing S7 deletes that event and the whole collection subject of D1, which is now S8's device.

**Case 2: an ambiguous segment created by unmerge.** After a merge-dependent switch on a tablet and a reversal, the tablet holds an ambiguous segment, but `identity_shared_at` is still NULL.
- The event before the first assertion stays in S7's journey.
- Erasing S7 completes at once and deletes the event of the ambiguous interval instead of holding it.

**Cause.**
- `_apply` marks a subject shared only when an earlier owner drops out (`previous - keep`), so a merge-dependent owner set containing the earlier owner is missed.
- `reevaluate_dependents` never sets the marker.
- Erasure decides that a device is exclusive from the marker alone.

**Rules:** design 4.4 (a second original owner or an ambiguous segment marks the subject shared), 7.2 stage 2, R006-27 (a switch retracts the provisional prefix), J6.

**Correct by:** setting the marker on every such transition, reversal included, and classifying erasure from the device's recorded segments.

[Share check](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity.py#L1404-L1416), [reversal](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity.py#L408-L492), [erasure](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity_admin.py#L441). Regressions: `test_review_r0607_02_erasure_keeps_another_persons_reassigned_device`, `test_review_r0607_02_unmerge_marks_the_device_shared`.

### R0607-03 P1 Expiring an associated identity assertion aborts the lifecycle run

**Reproduction.** Associate a verified sale, age the person's link and assertion by 400 days, and run `run_lifecycle`. It raises `ForeignKeyViolation` on `fk_revenue_bindings_assertion`, and the binding stays `active` with its identifying pointers.

**Cause.** The 395-day step deletes links and assertions without the F1 unlinking. `run_lifecycle` catches only `OperationalError`.

**Effect.** Every run stops at this client, so retention also stops for every later client in UUID order. The branch's JV19 claim that expiry is covered has no executed test.

**Rules:** J6, and joint design section 3 F1 (expiry clears every identifying pointer of every revision).

**Correct by:** unlinking with reason `expired` before the deletes, and considering per-client failure isolation in the lifecycle run.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity_lifecycle.py#L173-L209), [foreign key](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/migrations/versions/0028_revenue_identity.py#L174-L182). Regression: `test_review_r0607_03_expiry_of_an_associated_assertion`.

### R0607-04 P2 A conflicting owner takes over a sale on its second request

1. Person one holds revision 1.
2. Person two's assertion with `expected_revision` 1 correctly produces revision 2, `ambiguous`, but it stores person two as `owner_subject_id`.
3. Person two's next request with `expected_revision` 2 therefore matches the stored owner and becomes revision 3, `active` for person two.

Person two becomes a customer and person one loses the sale.

**Rules:** joint design sections 3 and 5 (a conflicting assertion never transfers a sale; conflicts need review).

**Correct by:** not storing a challenger as the owner of an ambiguous revision, and requiring a review action to leave that state. Also expose ambiguous associations in the review queue, because no route currently shows them.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/revenue_identity.py#L189-L221). Regression: `test_review_r0607_04_a_conflicting_owner_never_takes_over`.

### R0607-05 P2 A request from before an attribution withdrawal restores the binding later

1. An association is active, and a further same-owner request is answered 201 without being recorded.
2. Attribution is withdrawn, which unlinks the revision correctly.
3. Attribution is granted again. The earlier request, replayed unchanged, creates an active revision from the assertion made before the withdrawal.

**Rule:** joint design section 3 F1: a replay with withdrawn proof cannot restore a binding, and a new association needs a new request, new proof and current consent.

**Correct by:** requiring proof received within the current attribution grant, and recording the request ID of answered no-op requests.

[Qualification](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/revenue_identity.py#L168-L191), [unlink](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/revenue_identity.py#L231-L265). Regression: `test_review_r0607_05_no_restore_after_attribution_returns`.

### R0607-06 P2 The association answer discloses an objected identifier

**Reproduction.**
1. A person is erased with an objection.
2. The same email is asserted again, and 006 answers 201 as for anyone.
3. An association naming that assertion answers `422 proof_invalid`, while a fresh email answers 201.

**The same oracle** exposes contested and ambiguous identifiers. An `expected_revision` of null answers 409 when the sale had any earlier association, including one unlinked by erasure.

**Rules:** design 7.1, JV09 and joint design section 5 (generic acknowledgement; no response reveals a tombstone, contest or erasure).

**Correct by:** answering these cases with the same generic acknowledgement and keeping them unlinked internally.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/revenue_identity.py#L174-L187). Regression: `test_review_r0607_06_the_association_answer_hides_an_objection`.

### R0607-07 P2 Withdrawn identifiers keep linking to the old person

**Case 1: a key left behind.**
1. Person P owns an email and a phone from device X, and device Y asserts the email alone.
2. After W1 on X, P survives through Y, which is correct, but the phone key stays owned by P with no assertion presenting it.
3. A later subject that asserts only that phone is linked to P.

**Case 2: a person left behind.**
1. Y owns a phone on D2, and D3 asserts X's email with Y's phone, which is R4, ambiguous.
2. After W1 on D2 and then on D3, Y and the phone key remain with no evidence.
3. A later phone assertion links to Y.

**Cause.**
- `remove_orphan_keys` skips owned keys.
- `_people_of_links` re-checks only persons with active links, so the persons of ambiguous assertions are never re-checked.

**Rules:** design 6 W1 (remove keys and persons left without evidence), J3, R006-25.

[Keys](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity.py#L641-L649), [people](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity.py#L681-L688). Regressions: `test_review_r0607_07_withdrawn_keys_and_people_do_not_link_again`, `test_review_r0607_07_a_person_kept_only_by_a_withdrawn_device_is_removed`.

### R0607-08 P2 A paused objected erasure can never complete once its person is gone, and the objection is lost

**Reproduction.**
1. An erasure with an objection is paused because the person is in an active merge.
2. W1 on the person's only device removes them.
3. The resolution then answers `403 access_denied`, so the request stays paused permanently.
4. Because no objected identifier tombstone was written, a fresh consent and an assertion of the same email create a new person.

**Rules:** design 7.2 and 7.3 (objection tombstones), J6.

**Correct by:** completing a paused request whose target was removed by another path, and writing its objection tombstones.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity_admin.py#L563-L600). Regression: `test_review_r0607_08_a_paused_objection_survives_withdrawal`.

### R0607-09 P2 Customer status reads "not_customer" while the ledger cannot be read

`has_verified_purchase` turns `LedgerUnavailable` into False.

**Reproduction.**
1. Add one unprojected receipt, as every CSV commit above 200 rows does.
2. `GET /revenue` and the person revenue route correctly answer 503.
3. The profile of a real customer instead shows stage `known` with `not_customer`, and the buyer disappears from the leads list.

**A second trigger.** One ordinary receipt committed between the evidence read and the projection read gives the same wrong answer, so a profile read can be wrong at any moment of concurrent intake.

**Rules:** joint design sections 2 and 4.6 (fail closed, or return an explicit unavailable state), and the explicit-state rule of `AGENTS.md`.

**Correct by:** propagating the 503, or returning an explicit unavailable qualification, and reading the evidence and the projection in one snapshot.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/revenue_identity.py#L302-L310), [stage](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity_admin.py#L725-L731). Regressions: `test_review_r0607_09_customer_status_while_the_projection_is_behind`, `test_review_r0607_09_customer_status_during_a_concurrent_receipt`.

### R0607-10 P2 An account switch on a shared device removes the first buyer's sale (owner decision)

**Reproduction.**
1. Person A asserts on a tablet, and A's verified sale is associated.
2. When person B signs in on the same tablet, A's segment ends.
3. From then on, A's profile shows `not_customer`, A's revenue route lists no sale, and the 008 conversion disappears. The binding is still active revision 1, and no revision or audit records the change.

**The cause** is that every read requires an open segment (`segment.end is not None` disqualifies).

**The approved texts differ:**
- J10 asks for "a presently valid ownership segment".
- J5 makes customer status historical.
- Design 4.4 says that ending a segment never unassigns it.

**Recommendation:** an association qualified at link time stays with its owner after a segment ends normally, and is removed only by withdrawal, erasure, expiry, ambiguity or review. The regression asserts this reading; confirm or amend it before the correction.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/revenue_identity.py#L98-L130). Regression: `test_review_r0607_10_an_account_switch_keeps_the_first_buyer`.

### R0607-11 P2 A 200-row CSV commit on a client with history holds the agency and revenue locks for tens of seconds

Each inline receipt reloads and recalculates the client's whole history.

**Measured on the review host:**
- A client with 1,000 stored rows took 28.2 s to backfill.
- A 200-row CSV commit on it then took **43.3 s**.

**Effect.** During that time the agency row lock (`_manager(write=True)`) and the client revenue lock are held.
- Other Owner and Admin writes in the agency (3 s lock timeout) answer 503.
- The client's Paymob callbacks (2 s lock timeout) answer 503 and depend on provider retries.

On `main` the same commit took well under a second.

**Not covered by the joint evidence.** It measured only small totals (250 rows in one bulk commit, 2.44 s), and the 200-row threshold bounds the file, not the history. A re-uploaded file above 200 rows with one new row also leaves the projection behind.

**Rules:** J11 (current intake bounds), joint design section 4 (large imports keep their intake behavior). A3 is open, but this cost is not stated.

**Correct by:** bounding the inline work by total cost, or catching up after the commit outside the agency lock; this needs a design choice.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/declarations.py#L109-L120). Measurement: `test_review_r0607_11_a_200_row_commit_on_a_client_with_history` (opt-in, `TRACKING_REVIEW_MEASURE=1`).

### R0607-12 P3 Ledger reads in API sessions fail with an unhandled error during a concurrent receipt

**Readers affected:** `GET /revenue`, the reconciliation view and the CRM deals list. They read the evidence, the projection state, the movements and the receipts in separate READ COMMITTED statements.

**What happens.** A receipt that commits between the state read and the movement read raises `KeyError` on the new trigger evidence, which is an HTTP 500. The 016-A reports are not affected, because they read in one REPEATABLE READ snapshot.

**Correct by:** reading in one snapshot, or bounding every query by the published cursors and answering 503.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/revenue.py#L254-L269), [movements](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/ledger_store.py#L444-L468). Regression: `test_review_r0607_12_a_receipt_committed_between_ledger_reads`.

### R0607-13 P3 A database clock behind the receipt log refuses verified callbacks with 422 and loses them

**The status code.**
- The guard raises `LedgerInputError`, a `ValueError`, and `main.py` answers every `ValueError` with `422 validation_failed`.
- A verified Paymob callback is rolled back with its diagnostic row and answered with a client error, although D4 answers every verified callback 200 so that Paymob stops retrying.
- Whether Paymob retries a 4xx is not documented (V-5).

**The incomplete check.** A row stored without a projection, or while a backfill is building, skips the check. A row stored earlier than published receipts is later served as current without a receipt of its own: 5 evidence rows and 4 receipts.

**Rule:** joint design section 4.1.

**Correct by:** answering a retryable 503, and applying the ordering check on every path.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/ledger_store.py#L352-L383). Regressions: `test_review_r0607_13_a_clock_behind_the_log_is_retryable`, `test_review_r0607_13_an_out_of_order_row_is_never_served_without_a_receipt`.

### R0607-14 P3 Finance-derived customer status is released after finance access is removed

**Reproduction.** The profile and leads responses compute `customer_qualification` with the finance access read at the start, and `_release` rechecks only `identity:read`. A financial grant removed during the request is not noticed, and the member still receives `customer`.

**Rules:** joint design section 5 (customer status is a financial disclosure); JV03 (a live grant removal blocks release).

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/api/identity.py#L287-L310). Regression: `test_review_r0607_14_finance_is_rechecked_before_release`.

### R0607-15 P3 A sale associated through a merge-dependent link belongs to nobody after unmerge

**Reproduction.**
1. A link created during a merge records the merge root as its owner, and the association copies that root into `owner_subject_id`.
2. After reversal, the link returns to its original owner, but the binding still names the root.
3. Neither person is then a customer.

**Rule:** joint design section 3 (bindings store no merge-root ownership; unmerge recomputes ownership from the original evidence).

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/revenue_identity.py#L188-L221). Regression: `test_review_r0607_15_unmerge_keeps_the_sale_with_its_original_owner`.

### R0607-16 P3 A tracker retry scheduled before restart() sends the old subject token

**Reproduction.** After a 503 on `withdraw()` or `erase()`, the retry waits on a plain timer. Calling `restart()` meanwhile does not stop it, and the retry sends the previous session's subject token.

**Rules:** design section 8 and JV23 (no old token is transmitted after restart). The joint evidence lists no gap for JV23.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/packages/tracker-js/src/tracker.js#L824-L836). Regression: `packages/tracker-js/test/unit/review-restart.test.js`.

### R0607-17 P3 Conflicting deliveries share one reconciliation issue ID

**Reproduction.** Three deliveries of one operation with different amounts produce two open issues that share an ID. A review action binds to the first, and the second can never show a current review.

**Also:** "latest review" is ordered by transaction start time, so of two serialized reviews the later one can appear superseded.

**Rules:** J9 and JV17.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/ledger_store.py#L598-L629). Regression: `test_review_r0607_17_conflicting_deliveries_have_distinct_issues`.

### R0607-18 P3 A backfill with the wrong agency publishes an empty generation

**Reproduction.** `python -m app.ledger_backfill` selects the state by client but loads evidence by the given agency. With a wrong `--agency` it loads nothing, publishes an empty generation, prints `published` and exits 0. Every later read of that healthy client then answers 503 until a correct backfill.

**Correct by:** refusing an agency that does not own the client.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/ledger_backfill.py#L54-L82). Regression: `test_review_r0607_18_a_backfill_with_the_wrong_agency_changes_nothing`.

### R0607-19 P3 An erased candidate's ID remains in identity rows

After erasing a person who was a candidate of an ambiguous segment, the person's ID remains in one link and one assertion row: the link's `original_owner_ids` and the assertion evidence. No route exposes it, but it ties the erased ID to the shared device.

**Rules:** design 7.2 and F1.

[Source](https://github.com/nebo23/tracking_sys/blob/8b03b1c3721b52146edec63b17073672658dd95b/backend/app/services/identity.py#L515-L582). Regression: `test_review_r0607_19_an_erased_candidate_leaves_no_reference`.

## Effect on the branch's recorded closures

The findings reopen the following claims of the joint evidence:
- JV05 (W1 on every path): R0607-01.
- JV08 and R006-25: R0607-07.
- JV09: R0607-06.
- JV10 and R006-27, for merge transitions: R0607-02.
- JV16: R0607-18.
- JV17: R0607-17.
- JV18: R0607-04 and R0607-15.
- JV19: R0607-03 and R0607-05.
- JV20: R0607-09 and R0607-10.
- JV23: R0607-16.
- JV24: R0607-11 and R0607-12.

R006-23, R006-24, R006-26 and R006-28 were checked and no defect was found.

## Candidates not reproduced

Check these while correcting. They were reported by the code reads but not executed in this review:
- **Retained events after expiry.** Expiring an owned link leaves no floor, so a later assertion's provisional prefix could adopt the expired owner's retained events (R006-27).
- **Early expiry.** `last_evidence_at` is not refreshed when a reversal or closure reassigns a link or key, which could expire a person early.
- **Lifecycle variant of R0607-01.** The lifecycle persons sweep can reach R0607-01, through the same root cause.
- **Minor schema notes:**
  - `ledger_projection_state.algorithm` is never compared, so the rule-change guard is unenforced.
  - The movement-to-receipt FK ignores the generation.
  - `ledger_transactions.evidence_ids` is not refreshed for an agreeing delivery.
  - The movements cursor is generation-bound only when the caller passes the generation.

## Observations for the owner

These are not defects:
- **Rollout.** Every existing client needs the operator backfill before its financial reads work, because reads fail closed until then. Native rollout remains separately gated.
- **No automatic catch-up.** After a CSV commit above 200 rows, the client's revenue route, reports, reconciliation and CRM deals list answer 503 until an operator runs the backfill. Nothing catches up automatically or raises an alert. The CRM deals list loses availability for `client:read` readers compared with `main`. Production scheduling (020) should decide the catch-up.
- **Identity read cost.** Identity reads reload the client's whole evidence for each association they check, once per person in the leads list. This belongs to A3.
- **Confirmed sound in this review:**
  - Proof by issuance channel, freshness and normalization; retry receipts (R006-26); the exclusion marker (R006-24); the feed's gap checks (R006-28).
  - Tenant scope on every query and foreign key, and the read permissions.
  - The reconciliation policy, and the lock order: no holder of the revenue lock takes the privacy or agency lock.
  - Ledger equality with `calculate()` and `ledger_feed()` for logs without holds. The suite tests and a separate simulation of 50 random logs and 300 logs with holds agree.

## Merge readiness and next decisions

The branch is not ready for a pull request or merge. Three owner decisions follow:
1. **Corrections.** Authorize corrections of R0607-01 to R0607-19 on `codex/spec-006-007-identity-ledger`, each with a regression that fails at `8b03b1c`.
2. **R0607-10.** Confirm the recommended reading of J10, or amend it.
3. **R0607-11.** Choose the approach for bounded inline projection: a cost bound, or a catch-up outside the agency lock.

The correction of R0607-01 needs no new schema decision if it keeps the existing constraint. A pull request, the merge, native rollout and deployment remain separate decisions.

## Using the regression patch

Apply the [companion patch](specs-006-007-joint-review-regressions.patch) only in a disposable checkout of `8b03b1c` or of the correction branch:

```bash
git apply reports/specs-006-007-joint-review-regressions.patch
```

It adds `backend/tests/integration/test_review_006_007.py` and `packages/tracker-js/test/unit/review-restart.test.js`, and it changes no application code, schema, dependency or guard.

**Backend.** From `backend/`, with the repository's disposable-database configuration (`TRACKING_RUN_DB_TESTS=1`, `tracking_foundation_test` on 127.0.0.1:55433), run:

```bash
python -m pytest tests/integration/test_review_006_007.py -q --tb=line
```

Set `TRACKING_REVIEW_MEASURE=1` to include the R0607-11 measurement.

**Tracker.** From `packages/tracker-js/`, run:

```bash
node --test test/unit/review-restart.test.js
```

Never point these tests at native `tracking_sys`.
