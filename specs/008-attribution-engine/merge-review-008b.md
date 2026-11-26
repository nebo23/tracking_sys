# Spec 008-B merge review (PR 16)

Reviewed 2026-11-26 under D-080 at head `91c7431` of `codex/spec-008-attribution-persistence`, against `main` at `3187c70`. The owner asked Claude to review the completed branch and merge it if the review confirmed it.

## Scope of the review

The review checked the implementation against decisions D1-D14 of the [entry review](entry-review-008b.md), its [design note](design-008b.md) and the [evidence](evidence-008b.md):
- **Migration `0029_attribution_persistence`:** the six tables, the closed checks, the runtime and lifecycle column grants, and the guarded downgrade.
- **The consumer (`attribution_store.py`):**
  - the slots, the candidates and supersession;
  - the units, with fixed targets and REPEATABLE READ chunks whose first write is the compare-and-swap;
  - the staging rebuild and its restart, the sweep, and the D11 bounds;
  - the failure states.
- **The engine mapping (`attribution_records.py`):** the slot and conversion keys, the exact reconstruction of the previous run, and the signed credit changes, including anchor moves and closing revisions.
- **The privacy scrub (`attribution_scrub.py`) and its call sites:**
  - `remove_person` and `drop_subject_evidence`;
  - the person erasure and the 004 subject erasure, including the `attribution` erasure target;
  - the identity lifecycle's link and event expiry, and the attribution lifecycle step.

  The review also checked the scrub's ordering against the worker through the consumer state row.
- **The reads and routes:** the status read; the runs read with its release barrier, recalculated at read time; the D10 permissions; the finance split; the scope recheck before release.
- **Model versions:** lazy defaults, Owner/Admin administration, idempotency, audit and the six-version limit.
- **Changes to existing modules:** the consent change signal in `record_consent` and the input adapter changes.

## Verification run by the reviewer

All cases ran on a fresh disposable PostgreSQL 18.6 service (127.0.0.1:55433, `tracking_foundation_test`), with the repository's three roles and synthetic settings only.

| Check | Result |
|---|---|
| `ruff check app tests migrations`, `ruff format --check app tests migrations` | Clean (282 files) |
| `pytest -m "not integration"` | 926 passed |
| `pytest -m integration` with `TRACKING_RUN_BROWSER_TESTS=1`, Chromium | 646 passed; 4 skipped (the three opt-in AV16 measurements and the opt-in D-076 measurement); the Firefox journey case not run. The first run reported two browser journey failures because the review environment's Chromium preload could not resolve Playwright; with the preload corrected, `test_tracker_journey.py` passed (2 passed) |
| Tracker unit, `node --test test/unit/*.test.js` | 73 passed |
| Tracker browser, Chromium | 25 passed (the Chromium cases) |
| `pip check`, `git diff --check`, relative links of the changed Markdown (281) | Clean |
| OpenAPI, semantic comparison with `main` | 5 paths and 15 schemas added; nothing removed or changed |

Firefox is not installable in the review environment, so the Firefox cases were not run here. The implementing model's evidence records them passing.

## Findings

No blocking defect was found. Two non-blocking observations are left as follow-ups:
- **O1, runs release.** The runs route builds its body in a REPEATABLE READ snapshot and then rechecks only the reader's scope (`backend/app/api/attribution.py`). An erasure that commits while the body is being built is therefore not seen, and the response can still carry the erased person ID and touchpoint IDs. The identity routes use the same scope-only recheck. A follow-up can re-read the consumer state's version and scrub epoch after building the body and answer `attribution_stale` if either moved.
- **O2, status read.** `GET /attribution/status` reads the consumer state, the ledger position, the feed watermark and the state-based slots as separate READ COMMITTED statements, so one response can mix two moments. The runs route re-evaluates staleness in its own snapshot, so no person data is released through this. A follow-up can run the status read in a report snapshot.

## Decision numbering

Pull request 17 (Spec 018) numbers its own decisions D-078 to D-083. With this merge, `main`'s D-078 and D-079 are the 008-B decisions, and D-080 records this review and merge. Pull request 17 therefore needs its entries renumbered to the next free numbers when it is brought up to date with `main`.

## Result

PR 16 merged into `main` as `f15b6e4`, a merge commit of `3187c70` and `91c7431` whose tree equals the reviewed head `91c7431`.
