# Spec 008-B implementation: persisted attribution

Prepared 2026-11-25 under D-078. The owner approved decisions D1-D14 of the [008-B entry review](entry-review-008b.md) as recommended, without amendment, on 2026-11-25; the approval is recorded as D-079, so this handoff is ready to execute. Communicate with the owner in Arabic, and write every project file, commit and pull request in formal English. Save this handoff as `specs/008-attribution-engine/implementation-prompt-008b.md` on the branch below.

## Where to work

1. Fetch `origin`.
2. Create `codex/spec-008-attribution-persistence` from the current `origin/claude/keen-fermat-otlr9d`. That branch is merged `main` at `3187c70` (PR 15) plus this preparation, D-079 and the Spec 011 Phase 4 handoff. Verify that `git merge-base --is-ancestor 3187c70 HEAD` succeeds and that `origin/main` is still `3187c70`. If `main` moved, merge it first and report what changed.
3. Use a fresh worktree, and preserve owner files and other checkouts.

Read the following before the first change:
- **Project rules and decisions:** `AGENTS.md`, `README.md`, and in `docs/planning/decisions.md` D-046, D-047, D-074 to D-077 and D-079.
- **The packet:** the [008-B entry review](entry-review-008b.md), D1-D14, design section 4 and verification matrix section 5.
- **Spec 008:** the [008 spec](spec.md), the [plan](plan.md) and the [008-A evidence](evidence.md), including the pre-PR corrections and the open items.
- **The engine:** `backend/app/attribution/engine.py` (`attribute()`, `ModelVersion`, `AttributionRun`, `CreditAllocation`, `CreditDifference` and the history registry) and `backend/tests/test_attribution*.py`.
- **The persisted inputs:**
  - `backend/app/services/attribution_inputs.py`;
  - `backend/app/services/identity.py` (`journey_events`, `person_group`, `root_of` and the removal paths `remove_person` and `drop_subject_evidence`);
  - `backend/app/services/identity_feed.py`, with the reference consumer in `backend/tests/integration/test_identity_feed.py`;
  - `backend/app/services/ledger_store.py` (`published_state` and the stored journal);
  - `backend/app/services/revenue_identity.py`.
- **The joint 006/007 design:** sections 2 (R006-28 and the release barrier) and 6 of `specs/006-identity-journey/joint-design.md`, and the D-076 section of `specs/006-identity-journey/joint-evidence.md`.
- **Patterns to follow:**
  - `backend/app/connector_worker.py` (bounded worker pass);
  - `backend/app/services/lifecycle.py` and `backend/app/services/identity_lifecycle.py` (lifecycle steps and roles);
  - `backend/app/data_policy.py`;
  - migrations `0026` to `0028` (scoped FKs, grants, guarded downgrade);
  - `docs/engineering/identity-and-ledger.md`.

## Authority

- **Gate.** Before any application or migration change, find D-079 in the decision register approving D1-D14 and any amendment it names. If it is missing, stop and ask the owner in Arabic, citing this gate from `AGENTS.md`; do not ask again for approvals already recorded.
- **Precedence.** The latest owner instructions take precedence over this handoff. A fact found during implementation that changes a decision goes back to the owner before code depends on it.
- **Publication.** Push verified commits after each phase (D-051). At the end, open one pull request against `main` for review. Do not merge: the merge is a separate owner decision after review.

## Boundaries

- **Data.** Synthetic data only. Every database test runs on the disposable PostgreSQL 18 service of `backend/tests/README.md`; never point anything at native `tracking_sys`.
- **Schema and dependencies.** No new dependency. No migration other than the additive `0029_attribution_persistence`. No change to merged migrations. No native rollout.
- **Out of scope.** No frontend or React work, no live provider call, no 016-B or 016-C reports, no change to Specs 012 or 013.
- **Engine.** Keep `attribute()` and every 008-A safeguard unchanged. The R008-01 to R008-12 regressions must keep passing. Do not copy or fork the calculation.
- **Lock order.** The worker takes no revenue lock and never takes the privacy or agency lock while holding another lock. The D9 scrub runs inside the identity removal transactions, which already hold the client privacy lock.
- **Privacy.** No contact value, subject token, raw identifier or secret in any new row, response, error or log line.

## Phases

Each phase ends with its tests passing, ruff clean, a commit and a push. Record commands and counts as you go for the evidence file.

### P0: Inventory and design note

1. Verify the branch, `main` and D-079.
2. Inventory the inputs (journey, feed, ledger, associations, trusted leads) and confirm the real field names behind section 4 of the entry review.
3. Write `specs/008-attribution-engine/design-008b.md`. It covers:
   - the exact DDL of `0029`: columns, checks, FKs, indexes and grants for `tracking_app` and `tracking_lifecycle`;
   - the conversion keys;
   - the pass algorithm with its snapshot, batches and compare-and-swap;
   - the rebuild;
   - the scrub;
   - the routes with their request and response shapes and error codes;
   - a test inventory that maps every AV01-AV20 case to a test name.

   Section 4 of the entry review is the source. Resolve routine details here, and return only material new choices to the owner.
4. Commit and push.

### P1: Schema and model versions

- **Migration.** Write `0029_attribution_persistence` and its ORM models in `backend/app/models/attribution.py`, registered in `app.models`.
- **Data policy.** Add the `data_policy` rows for every new column (D12), and update the table counts in `tests/test_data_policy.py` and `tests/integration/test_data_policy_schema.py`.
- **Downgrade.** It refuses populated state, as `0027` does.
- **Grants (D13).** `tracking_app` may insert and select, and update only the publication and scrub columns. `tracking_lifecycle` may scrub and delete as D12 requires. Show in a test that the runtime role cannot rewrite allocations or amounts.
- **Model versions (D2, D3).** Write `backend/app/services/attribution_models.py`: idempotent default seeding (First, Last and Linear at 30 days, Linear as default, applied lazily the first time a client is read or processed); validated windows of 1 to 90 days; at most 6 active versions; one default; retirement, refused for the current default; audit events (extend the closed audit action and resource lists).
- **Routes.** `GET /attribution/models` and the Owner/Admin `POST` routes of D10, with idempotent `operation_id` values.
- **Tests and contract.** AV14 (upgrade from a populated `0028`, guarded downgrade, privileges) and AV19. Regenerate the OpenAPI snapshot with additions only.

### P2: Consumer core

- **Store.** Write `backend/app/services/attribution_store.py`:
  - **Conversion registry (D4):** verified sales from the published ledger, both associated and unassociated; trusted leads from `journey_events` (`lead_signal`, trust rank 2); supersession on an owner change.
  - **Run recording:** one run per changed outcome per active version, with its allocations and credit changes (shares as exact numerator and denominator).
  - **Consumer state** and the publication compare-and-swap on `(generation, ledger generation, receipt ordinal, identity checkpoint)`.
  - **Rebuild:** a staging rebuild with atomic publication, started by a pruned feed, a ledger generation change or a model-set change.
  - **Bounds (D11)** with explicit states.
- **Worker.** Write `backend/app/attribution_worker.py`: `python -m app.attribution_worker` runs one bounded pass over the clients and prints counts only, never IDs.
- **Tests.**
  - AV01 to AV07, AV11, AV13 and AV16 in `tests/integration/test_attribution_store.py`.
  - The AV05 seeded random comparison of incremental and rebuild after every step.
  - AV11 with two workers at the publication boundary, modeled on `test_identity_feed.py`.
  - Unit tests for the pure parts.

### P3: Privacy and freshness

- **Scrub (D9).** Inside `remove_person`, `drop_subject_evidence` and the lifecycle expiry steps, in their transactions, scrub the person reference and every touchpoint ID from stored conversions, runs, excluded touches, allocations and credit changes. Keep campaign, content, link and source provenance, shares and amounts.
- **Erasure target.** An erasure request reports its attribution target done only after the scrub.
- **Release barrier and staleness (D8).** A person-level response is released only while the consumer checkpoint covers the current ledger and identity watermarks, with scope, consent and tombstones rechecked. Otherwise the answer is the retryable `503 attribution_stale` with `Retry-After`.
- **Lifecycle (D12).** Steps in `identity_lifecycle` or `lifecycle` for derived rows; they never touch money or the non-identifying history.
- **Tests.** AV08, AV09, AV10, AV15, AV17 and AV20. Show that a replay after erasure cannot restore a scrubbed pointer, and that the log and value scan finds nothing.

### P4: Read routes and permissions

- **Routes.** `GET /attribution/status`, with watermarks and `behind`, `caught_up` or `rebuilding`; and `GET /attribution/conversions/{conversion_id}/runs?model_version=`, giving revisions with allocations and differences.
- **Permissions (D10).**
  - The runs route needs `identity:read`; a sale run's amounts and transaction references also need `finance:read`.
  - Without finance access, a sale run answers the explicit `permission_unavailable` for its amounts.
  - Service read keys reach models and status only.
  - Every release rechecks scope (R0607-14 pattern).
- **Tests.** AV12, including a mid-request revocation.
- **Contract.** Regenerate the OpenAPI snapshot with additions only, and compare it semantically with `main`.

### P5: Verification, evidence and pull request

1. **Full verification.** From `backend/`, with the disposable database:
   - `ruff check app tests migrations` and `ruff format --check app tests migrations`;
   - `pytest -m "not integration" -q`;
   - `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1` and the tracker's local browsers (all modules, the three browser journeys included);
   - from `packages/tracker-js`, `node --test test/unit/*.test.js` and `node --test --test-concurrency=1 test/browser/*.test.js` (Chromium and Firefox);
   - `pip check` and `git diff --check`;
   - a relative-link check of the changed Markdown.

   Record exact counts. A skipped case is reported as skipped, never as passed.
2. **Mutation check.** Disable each new safeguard in turn and show that its test fails, then restore the source byte for byte (compare SHA-256). The safeguards are: the compare-and-swap; the release barrier; the scrub; supersession on an owner change; the rebuild trigger; the bounds; the model-version limit; the finance permission on amounts.
3. **Measurements (AV16).** One pass, one incremental step and one rebuild at 50, 200 and 1,000 conversions, with the statement counts. These are observations, not SLOs; A3 stays open.
4. **Documentation.**
   - `specs/008-attribution-engine/evidence-008b.md`: commits, AV01-AV20 with test names and results, commands and counts, measurements, mutation results and limits.
   - A developer guide `docs/engineering/attribution.md`, linked from the identity and ledger guide.
   - The 008 spec, plan and tasks.
   - The status lines in `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md`.
5. **Pull request.** Push, then open one pull request from `codex/spec-008-attribution-persistence` against `main`. Follow `.github/pull_request_template.md` if one exists. Describe:
   - the decisions (D-078, D-079);
   - the scope;
   - the schema;
   - the routes;
   - the verification counts;
   - the API additions;
   - the limits;
   - what remains (016-B, 016-C, native rollout, live providers).

   Do not merge.
6. **Report.** Tell the owner in Arabic:
   - the pull request link and head commit;
   - what was built;
   - the tests actually executed with their counts;
   - every limitation;
   - that the branch is ready for Claude's independent review.

## What success looks like

- Every verified sale and trusted lead of a synthetic client is attributed under each active model version.
- Stored allocations equal a fresh calculation, and the incremental state equals a rebuild after every step.
- Refunds and late touches create revisions with exact signed differences.
- Ownership changes supersede conversions without mutating them.
- Erasure leaves no identifying pointer while the campaign credit history and money stay intact.
- Readers never receive a stale person result.
- Nothing outside the approved scope changes.
