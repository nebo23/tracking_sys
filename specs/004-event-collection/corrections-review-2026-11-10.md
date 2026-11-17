# Specification 004 correction review

Date: 2026-11-10. Recommendation: **request changes; do not merge yet**.

Reviewed local commit: `c229ac74d23d4c3f425a085a1456782122dee13a`, on `codex/spec-004-event-collection` in `.worktrees/spec-004-event-collection`.
Comparison: `b90fa530a60425d39e3fe57659ceb7207896d55a..c229ac74d23d4c3f425a085a1456782122dee13a` (21 files).
PR: https://github.com/nebo23/tracking_sys/pull/3

At review time PR 3 remained open at `b90fa53`. The correction commit was local only, consistent with D-029. The correction worktree was clean. This review did not change implementation, commit, push, update the PR, merge, or perform native migrations. Unrelated root-worktree changes were preserved.

## Disposition of the previous review

| Item | Result |
|---|---|
| R004-01: browser cannot read issued consent token | Corrected at the HTTP/CORS contract level. Registered origins receive a response grant and valid JSON preflights; customer origins remain outside credentialed platform CORS. New tests cover grants, denials, media types and platform CSRF. |
| R004-02: lifecycle races admission | The original simultaneous-transaction race is corrected by the shared client lock and fresh eligibility checks. **Closure is blocked by R004-04 below:** partial committed batches can change the effective consent state. |
| R004-03: rotation drops still-valid secrets | Corrected. The count limit is removed, and all unexpired versions remain eligible. Regression tests cover four versions, expiry and source/client isolation. |
| Sensitive retained query values | The reported card/email patterns, including the tested encoding forms, are removed before storage. Tests assert payloads, counters and captured output. This remains pattern-based minimization, not comprehensive personal-data detection. |

## R004-04 — P1: partial lifecycle cleanup can resurrect withdrawn consent

Primary location: `backend/app/services/lifecycle.py:219-224`.
Related locations: the subject predicate at `162-166` and the per-batch commit at `318`.

The client privacy lock protects one transaction, but each consent batch deletes rows in **UUID order**, independently of consent chronology. When a subject has more consent rows than fit in the batch, its latest withdrawal can be deleted while an older, still-valid grant remains. The new subject predicate retains that subject until every consent row is gone. After the batch commits, admission therefore sees the historical grant as the current consent and accepts an event without renewed permission.

This is reproducible through the actual `run_lifecycle` function with supported configuration, without disabling locks or calling a mock cleanup implementation. A bounded run or interruption after a commit leaves this state observable; even an unbounded run releases the client lock between batches.

### Deterministic reproduction

Use the existing disposable PostgreSQL integration fixture `c` and separate runtime/migration/lifecycle roles:

1. Create a subject with an analytics grant, then withdraw that purpose through the real consent endpoint.
2. Use synthetic historical times: grant received 33 days ago and still valid, withdrawal and last activity 31 days ago. Set `subject_retention_days=30`, which the configuration supports. No event exists for the subject.
3. Fix the withdrawal UUID to `00000000-0000-4000-8000-000000000001` when issuing it, so it deterministically sorts before the grant UUIDs. This selects a valid random-ID ordering; it does not alter consent chronology or admission logic.
4. Test with batch sizes **1 and 500**. Use respectively 1 and 500 historical grant records, followed by that newer withdrawal. The 500-row case exercises the default batch size with a 501-row history. Extra synthetic grants are inserted with the migration fixture, all preceding the withdrawal in receipt time.
5. Confirm an event is initially refused with **422 `consent_withdrawn`**.
6. Run `run_lifecycle(lifecycle_engine, settings, max_batches=1)`.
7. Submit a fresh event using the same token, without recording any new grant.
8. Resume lifecycle and inspect stored rows.

Observed results in both cases:

| Stage | Result |
|---|---|
| Before cleanup | 422 `consent_withdrawn`; no event |
| First cleanup | `partial`; 1 or 500 consent rows deleted; subject retained |
| Remaining consent history | One older `granted` record; withdrawal gone |
| New event without renewed consent | **201 `accepted`; one event stored** |
| Resumed cleanup | `completed`; zero consent/subject deletions, because the accepted event and refreshed activity now protect them |

The diagnostic assertions failed twice: **2 failed in 2.58 seconds**. The preceding run also reproduced both cases (2 failed in 3.40 seconds); the final run additionally checked that resuming cleanup does not repair the problem.

The reproduction requires shortened retention relative to grant validity; it does not claim that a valid 365-day grant survives 395 days of inactivity under the default retention. Both retention values and both tested batch sizes are supported by the application.

### Required correction and regression coverage

Preserve effective consent at **every committed batch boundary**, not only while a transaction holds its client lock. Cleanup must never remove the latest denial/withdrawal while retaining an older grant that admission can use. Keep the shared lock and bounded work.

An implementation can preserve the latest record per subject/purpose while removing older history, then remove the remaining consent and subject consistently, or use another design that establishes the same invariant. Any chronological strategy must match the consent evaluator's receipt-time and UUID tie-breaking order. Do not silently add a schema or policy change.

Add deterministic regressions for both `withdrawn` and `denied`, batch size 1 and default 500, histories spanning batches, a request between committed batches, bounded/interrupted runs, and resume behavior. Assert both the response and absence of stored events without a new consent grant. Keep the existing admission-versus-lifecycle concurrency tests.

Update the correction evidence and operating documentation after this is fixed; the current claim that the lifecycle correction is complete misses this state transition.

## Independent verification

An exact `git archive` of `c229ac7` was tested in a temporary directory without `.env`, using the existing project `.venv`. Inherited `TRACKING_`, `PG` and `PYTHON` variables were removed; only synthetic settings were supplied. Collection keyrings were generated by the corrected test fixture.

Database: fresh Docker Compose project `tracking-review004b`, PostgreSQL `tracking_foundation_test` at `127.0.0.1:55433`, with separate runtime, migration and lifecycle roles. Native `tracking_sys` was not used.

| Check | Actual result |
|---|---|
| `python -m pytest -q -p no:cacheprovider -rs` on the unchanged correction archive | **474 passed, 1 warning in 129.82 seconds**, no skips |
| `python -m ruff check app migrations tests` | Passed |
| `python -m ruff format --check app migrations tests` | 83 files already formatted |
| `python -m pip check` | No broken requirements |
| `git diff b90fa53..c229ac7 --check` | Passed |
| Independent partial-batch diagnostics, added only to the temporary archive after the full suite | **2 failed**, demonstrating R004-04 |

The suite includes migration cycles, database grants, metadata consistency and OpenAPI checks. The warning was Pydantic `UnsupportedFieldAttributeWarning` concerning the `X-CSRF-Token` alias during the concurrent invitation test; it did not fail the test and is not classified here as a correction regression.

No independent real-browser rerun, load test, API-container smoke test, live provider call, or production validation was performed in this review. The implementing model's documented headless Chrome run remains its evidence; this review independently verified the HTTP contract and database tests.

Temporary test code, the archive and synthetic settings are removed after review. Only the dedicated review Compose resources are removed. The previous review report is preserved as historical evidence.
