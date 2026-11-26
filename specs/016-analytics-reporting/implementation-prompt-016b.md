# Spec 016-B implementation: attribution reports

Prepared 2026-11-26 under D-088. The owner approved decisions D1-D14 of the [016-B entry review](entry-review-016b.md) as recommended, without amendment, on 2026-11-26; the approval is recorded as D-089, so this handoff is ready to execute. Communicate with the owner in Arabic, and write every project file, commit and pull request in formal English. Save this handoff as `specs/016-analytics-reporting/implementation-prompt-016b.md` on the branch below.

## Where to work

1. Fetch `origin`.
2. Create `codex/spec-016b-attribution-reports` from the current `origin/claude/keen-fermat-otlr9d`. That branch is merged `main` at `f15b6e4` (PR 16) plus the D-080 records, this preparation and D-089. Verify that `git merge-base --is-ancestor f15b6e4 HEAD` succeeds.
3. Check `origin/main`. If it moved beyond `f15b6e4`, merge it into the branch first and report what changed. Pull request 17 (Spec 018) may have merged by then:
   - In `AGENTS.md` and `docs/planning/decisions.md`, keep both sets of decisions in numeric order. D-081 to D-087 belong to Spec 018, and D-088 and D-089 to this work. Remove the placeholder notes that say D-081 to D-087 are recorded elsewhere, and keep the numbering note of Spec 018.
   - If `frontend/` now exists, the contract drift check of the frontend applies to this work (see P5).
4. Use a fresh worktree, and preserve owner files and other checkouts.
5. A new decision record takes the next free number after the highest one on `main`, on this branch and on any open pull request. Check before recording.

Read the following before the first change:
- **Project rules and decisions:** `AGENTS.md`, `README.md`, and in `docs/planning/decisions.md` D-064, D-072, D-073, D-079, D-080, D-088 and D-089.
- **The packet:** the [016-B entry review](entry-review-016b.md), D1-D14, design section 4 and verification matrix section 5.
- **Spec 016:** the [spec](spec.md), the [016 entry review](entry-review.md), the [016-A design](design.md), its [verification matrix](verification-matrix.md), the [evidence](evidence.md) and the [merge review](merge-review-2026-11-23.md).
- **The 016-A code:**
  - `backend/app/reporting/` (common, periods, digest, catalog, the three families and `csv_export.py`);
  - `backend/app/services/reporting.py` (snapshot, inputs, revision and release check);
  - `backend/app/api/reports.py`;
  - `docs/engineering/reporting.md`.
- **Stored attribution (008-B):**
  - `docs/engineering/attribution.md`, above all "Reading credit (016-B)";
  - `specs/008-attribution-engine/design-008b.md`, `evidence-008b.md` and `merge-review-008b.md` (observations O1 and O2);
  - `backend/app/models/attribution.py`;
  - `backend/app/services/attribution_store.py`, `attribution_reads.py`, `attribution_models.py`, `attribution_records.py` and `attribution_inputs.py`;
  - `backend/app/api/attribution.py`.
- **ROAS and spend (014):** `backend/app/advertising/roas.py`, D11 and V-18 of `specs/014-ad-spend-capi/entry-review.md`, and `docs/engineering/advertising.md`.
- **The other inputs:**
  - `backend/app/models/ledger.py` and `backend/app/services/ledger_store.py` (`published_state`, `ledger_transactions`);
  - `backend/app/models/links.py` and `backend/app/models/collection.py` (`collected_events.link_id`);
  - `backend/app/models/connectors.py` (`connector_records`);
  - `backend/app/api/identity.py` (the person-level release pattern and cursor pages).
- **Patterns to follow:** migration `0029` (guarded downgrade, grants), `backend/tests/integration/attribution_support.py`, and the report tests of 016-A.

## Authority

- **Gate.** Before any application or migration change, find D-089 in the decision register approving D1-D14 and any amendment it names. If it is missing, stop and ask the owner in Arabic, citing this gate from `AGENTS.md`; do not ask again for approvals already recorded.
- **Amendments.** If D-089 names an amendment, it replaces the matching text of the entry review and of this handoff. For example, if D7 is approved with its alternative, skip the adapter change of P2 and report ad and ad set rows as `unavailable`.
- **Precedence.** The latest owner instructions take precedence over this handoff. A fact found during implementation that changes a decision goes back to the owner before code depends on it.
- **Publication.** Push verified commits after each phase (D-051). At the end, open one pull request against `main` for review. Do not merge: the merge is a separate owner decision after review.

## Boundaries

- **Data.** Synthetic data only. Every database test runs on the disposable PostgreSQL 18 service of `backend/tests/README.md`; never point anything at native `tracking_sys`.
- **Schema and dependencies.** No new dependency, table or column. The only migration is the additive `0030_reporting_indexes` of D12. No change to merged migrations. No native rollout.
- **Out of scope.** No frontend or React work, no live provider call, no 016-C work (retained, scheduled or white-label reports), no agency-wide rollup, no channel dimension, no exchange rate, no change to Specs 012 or 013.
- **Engine and stored attribution.** Keep `attribute()` and every 008-A and 008-B safeguard unchanged. The only changes to 008-B are the adapter and its one-time rebuild of D7 and the two release corrections of D11. The AV and R008 regressions must keep passing.
- **ROAS contract.** Reuse the rules of `app/advertising/roas.py`; do not copy or fork them. `roas_report` keeps its behavior.
- **016-A families.** They change only in their dependency block and contract version.
- **Reads only.** A report writes nothing, takes no advisory lock, calls no provider and starts no worker pass.
- **Privacy.** No person ID, touchpoint ID, event ID, subject token, contact value, name, label or secret in any aggregate report, CSV, error or log line. The conversions list is the only person-level answer.

## Phases

Each phase ends with its tests passing, ruff clean, a commit and a push. Record commands and counts as you go for the evidence file.

### P0: Inventory and design note

1. Verify the branch, `main` and D-089.
2. Inventory the inputs and confirm the real field names behind section 4 of the entry review.
3. Write `specs/016-analytics-reporting/design-016b.md`. It covers:
   - the exact statements that aggregate stored credit, with the published-generation filter and the exact fraction sums;
   - the answer shape of each family, its totals, states, reasons and error codes;
   - the reconciliation rule and its states;
   - the ROAS entry point, the adapter change, the digest revision and the rebuild it causes;
   - the funnel's visit count and client totals;
   - the conversions list, its cursor and its barrier;
   - the revision inputs and the release check of each family;
   - the fixed CSV columns of each family;
   - the DDL of `0030_reporting_indexes`;
   - a test inventory that maps every BV01-BV20 case to a test name.

   Section 4 of the entry review is the source. Resolve routine details here, and return only material new choices to the owner.
4. Commit and push.

### P1: Attribution report

- **Family.** Add the `attribution` family to `backend/app/reporting/` and its route to `backend/app/api/reports.py`: the `groups` view with `compare=previous`, and the `models` view (D3, D4, D5).
- **Read.** Read the consumer state, the model versions and the aggregated credit in the report snapshot (section 4.2). Sum shares exactly; never use floating point.
- **Groups.** Direct and unknown credit are rows of their own. Add the registered flags, and the social content pointer on exact ID equality within the client (D4).
- **Reconciliation.** Compare the credited total with the persisted ledger per currency (D5).
- **Freshness.** Report the attribution state and watermarks; null values with `attribution_not_ready` before the first publication; no authoritative comparison while behind (D6).
- **Permissions.** `client:read` for lead credit; `finance:read` for sale values and the reconciliation, otherwise `permission_unavailable` (D9). Bind the finance flag into the revision, and recheck both scopes before release.
- **Consistency.** Revision, pages, release check, bounds and CSV as section 4.6 (D10).
- **Dependency block.** The four capabilities become `available` and name their family; the contract version becomes `016b.1`.
- **Tests.** BV01 to BV10 and BV16 to BV18 for this family, with pure tests for the aggregation and the fraction arithmetic. Regenerate the OpenAPI snapshot.

### P2: ROAS and cost per lead

- **Adapter (D7a).** `attribution_inputs.touchpoints()` reads `utm_content` as the content reference when the event has no managed-link content reference, under `usable_reference`. A managed link's content reference wins, and the class of a touch does not change.
- **Rebuild.** Add an input-adapter revision to the model-set digest, so that the first pass after the change rebuilds each client once. Show that history stays byte-identical, that credit moves only by signed changes and that totals do not change.
- **Entry point (D7b).** Extend `app/advertising/roas.py` with an entry point over aggregated credit that shares the row rules and roll-up with `roas_report`. Credit matches an ad on its campaign ID and ad ID, for an ad stored under the connection.
- **Family.** Add the `roas` family and route: one spend connection, account-local dates, levels `ad`, `adset` and `campaign`, credited leads and the cost per lead, unmatched credit per currency. Reuse the spend read of 016-A for coverage, bounds and states.
- **Tests.** BV11, BV12 and BV13, and BV01, BV02, BV05, BV06, BV16 to BV18 for this family.

### P3: Funnel and indexes

- **Migration (D12).** Write `0030_reporting_indexes` with its two indexes and a downgrade that drops them. Test the upgrade from a populated `0029` and the downgrade, and update the head pins of the existing migration tests.
- **Family.** Add the `funnel` family and route: tracked visits, credited leads, credited sales and credited revenue per group, and the client totals (D8). A group without a managed link has `unsupported` visits. The answer has no rate field.
- **Tests.** BV14, and BV01, BV02, BV06, BV16 to BV18 for this family.

### P4: Conversions list

- **Route.** Add `GET /attribution/conversions` to `backend/app/api/attribution.py` with its filters and cursor (D11).
- **Barrier.** Build the list in the report snapshot; answer `attribution_stale` unless the 008-B status read says `caught_up`; resolve the scope again before the response.
- **Change token.** After the answer is built, compare the consumer state's generation, version and scrub epoch in a fresh read with those of the snapshot, and answer `attribution_stale` on a difference. Give the existing runs route the same check (observation O1 of the 008-B merge review), and make the status route read inside one snapshot (O2).
- **Finance.** Without `finance:read`, list lead conversions only and say that sales are withheld.
- **Tests.** BV15, with a revocation during the request, a withdrawal between two passes, and an erasure and a worker pass that commit while the list and a runs answer are being built.
- **Contract.** Regenerate the OpenAPI snapshot and compare it semantically with `main`: additions only, apart from the documented dependency change.

### P5: Verification, evidence and pull request

1. **Full verification.** From `backend/`, with the disposable database:
   - `ruff check app tests migrations` and `ruff format --check app tests migrations`;
   - `pytest -m "not integration" -q`;
   - `pytest -m integration -q` with `TRACKING_RUN_BROWSER_TESTS=1` and the tracker's local browsers (all modules, the browser journeys included);
   - from `packages/tracker-js`, `node --test test/unit/*.test.js` and `node --test --test-concurrency=1 test/browser/*.test.js` (Chromium and Firefox);
   - `pip check` and `git diff --check`;
   - a relative-link check of the changed Markdown.

   If `frontend/` exists on the branch, also run there, with Node.js 24.15 or later: `npm ci`, `npm run api:types`, `npm run api:check`, `npm run typecheck`, `npm run lint` and `npm test`. Commit the generated `src/api/schema.d.ts`.

   Record exact counts. A skipped case is reported as skipped, never as passed.
2. **Mutation check.** Disable each new safeguard in turn and show that its test fails, then restore the source byte for byte (compare SHA-256). The safeguards are: the published-generation filter; the finance split; the scope recheck before release; the change token in the release check; the stale barrier of the list; the change token recheck of the list and of the runs route; the `id:` prefix; the group bound; the match on both the campaign ID and the ad ID; the client scope of the visit count; the zero floor of the reconciliation.
3. **Measurements (BV19).** One report of each family at 1,000, 10,000 and 100,000 stored credit rows, with elapsed time and statement counts. These are observations, not SLOs; A3 stays open.
4. **Documentation.**
   - `specs/016-analytics-reporting/evidence-016b.md`: commits, BV01-BV20 with test names and results, commands and counts, measurements, mutation results and limits.
   - `docs/engineering/reporting.md`: the four new parts, their parameters, answers, states, bounds and CSV columns.
   - `docs/engineering/attribution.md`: the adapter change, the one-time rebuild and the conversions list.
   - The 016 spec, plan and tasks.
   - The status lines in `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md`.
5. **Pull request.** Push, then open one pull request from `codex/spec-016b-attribution-reports` against `main`. Follow `.github/pull_request_template.md` if one exists. Describe:
   - the decisions (D-088, D-089);
   - the scope and the four parts;
   - the change to 008-B's adapter and its rebuild;
   - the routes and permissions;
   - the migration;
   - the verification counts;
   - the API additions and the dependency block change;
   - the limits;
   - what remains (016-C, the React UI, native rollout, live providers).

   Do not merge.
6. **Report.** Tell the owner in Arabic:
   - the pull request link and head commit;
   - what was built;
   - the tests actually executed with their counts;
   - every limitation;
   - that the branch is ready for Claude's independent review.

## What success looks like

- A reader sees which campaigns, content items and links earned a synthetic client's verified revenue and leads, under each model, and the totals reconcile with the ledger.
- Direct, unknown and unmatched credit is always visible, and a missing value is never 0.
- ROAS from stored credit equals the 014-C contract, per ad, ad set and campaign, with the cost per lead.
- The funnel shows its four stages with their bases and no invented rate.
- A reader with person-level access can list conversions and open one, and never receives a stale association.
- No aggregate report, CSV or log line carries a person, a touch or a name.
- Nothing outside the approved scope changes.
