# Spec 016-C merge review (PR 20)

Reviewed 2026-11-27 under D-096 at head `3678509` of `codex/spec-016c-report-delivery`, against `main` at `06d6a19`. The owner sent the completion report after Claude said that it would review the branch and merge it if the review confirmed it. The owner then approved the merge when the review result was presented.

## Scope of the review

The review checked the implementation against decisions D1-D14 of the [entry review](entry-review-016c.md), the [design note](design-016c.md) and the [evidence](evidence-016c.md):
- **Migration `0032_report_delivery`:**
  - the five tables and their closed checks: the export state machine, the 7-day lifetime, the sizes, the key material and the logo bounds;
  - the partial indexes;
  - the runtime and lifecycle column grants, and the wider outbox and audit checks;
  - the guarded downgrade.
- **Retained exports (`report_exports.py`):**
  - the reservation, build and store sequence, and the 50-export bound;
  - the seal bound to the export, agency and client;
  - the visibility of D3;
  - the download, which resolves the scope again, checks `finance:read` and answers `410 export_gone`;
  - the manual revocation.
- **Automatic revocation:**
  - the calls in the 004 and 006 erasures, including the erasure of held events, in `start_disconnect` for every cause of disconnection, in the purge and in the client archival.
  - The lock order: the agency lock, then the client privacy lock, then the export lock. A reservation inserts its row before it takes the export lock, and a store writes its audit row before it locks the export row.
  - The review found no deadlock path and no way for an export to be stored after the event that should revoke it.
- **Schedules and the worker (`report_schedules.py`, `reporting/schedules.py`):**
  - validation, and the 10-active bound under the agency lock;
  - the owner check at every run (the owner must still be an Owner or Admin);
  - the claim with `SKIP LOCKED`, which moves the schedule to its next slot before the build;
  - missed slots, retries, the pause after three failures, and the stop states;
  - the periods and the daylight-saving rules.
- **Email (`mail.py`):** the `report_ready` purpose and its fields, the expiry with the export, no figure, client name or token, and names without control characters.
- **Branding (`branding.py`, `api/branding.py`):** validation, the PNG structure check, the route size limit, the permissions and the response headers of the logo.
- **Lifecycle:** expired, discarded and stale pending exports are deleted content first, in bounded batches with a lock timeout.
- **The rest:** the contract, the data policy rows, the tests and the documentation.

## Verification run by the reviewer

All cases ran on a fresh disposable PostgreSQL 18.6 service (127.0.0.1:55433, `tracking_foundation_test`), with the repository's three roles and synthetic settings only.

| Check at `3678509` | Result |
|---|---|
| `ruff check app tests migrations`, `ruff format --check app tests migrations` | Clean (324 files) |
| `pytest -m "not integration"` | 969 passed |
| `pytest -m integration` with `TRACKING_RUN_BROWSER_TESTS=1`, Chromium | 791 passed, 1 failed (explained below), 7 skipped (the opt-in AV16, BV19 and D-076 measurements); the Firefox journey case not run |
| Replay of the first 127 integration cases in their suite order | 127 passed |
| Tracker unit, and tracker browser with Chromium | 73 and 25 passed |
| `pip check`, `git diff --check`, relative links of the changed Markdown (382 in 20 files) | Clean |
| OpenAPI, semantic comparison with `main` | 8 paths and 23 schemas added; nothing removed or changed |

Firefox is not installable in the review environment, so the Firefox cases were not run here. The implementing model's evidence records them passing.

### The failed case

`test_attribution_report_bounds.py::test_bv19_group_bound` belongs to 016-B, and this branch does not change it. In the full run it answered `503 temporarily_unavailable`. Its attribution report over 10,000 stored credit groups exceeded the runtime engine's 3-second statement timeout. The request took about 14 seconds in the full run; the whole test takes under 5 seconds alone.

The test then passed:
- alone;
- in its module, three times;
- in an exact replay of the 127 cases that precede and include it.

016-C does not change the report code, the credit tables or the statement timeout. The failure is a timing flake of a 016-B bound test, not a defect of this branch, and it is left as follow-up F1.

## Findings

No defect was found. The following points are observations, without a change:
- **O1, the schedule reference.** `report_exports.schedule_id` references `report_schedules.id` by itself, with `ON DELETE SET NULL`. Every other reference of `0032` is scoped by agency and client. The service writes only the schedule's own IDs, so no cross-tenant reference can be created today. A later migration can scope it with `ON DELETE SET NULL (schedule_id)` on the composite key (PostgreSQL 15 and later).
- **O2, archival during a build.** A client may be archived while one of its scheduled reports is being built. The release check then fails, and the run is recorded as `owner_access_lost`, which pauses the schedule. After the client is reactivated, a manager must resume it. Without that race, the worker simply does not claim the schedules of an archived client.
- **O3, caches.** The 003 obligation of Spec 016 also names caches. The platform has no cache (016-A D10, 016-C D13), so the cache part of 003 acceptance criterion 3 does not apply. RV06-RV08 close its export part.
- **O4, decision numbers.** The pushed branch `codex/spec-018-workspace-screens` numbers two Spec 018 decisions D-093 and D-094, which `main` already uses. That branch must renumber them to the next free numbers when it is brought up to date, as pull request 17 did under D-087.

**Follow-up F1.** Stabilize the BV19 bound test, so that the suite does not depend on machine load: for example, run `ANALYZE` after its bulk insert, or give the test its own statement timeout.

## Result

PR 20 merged into `main` as `e3b3005`, a merge commit of `06d6a19` and `3678509` whose tree equals the reviewed head `3678509`.
