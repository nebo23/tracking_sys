# Spec 017-B merge review (PR 21)

Reviewed 2026-11-28 under D-099 at head `d3cb66f` of `codex/spec-017b-agency-offboarding`, against `main` at `e3b3005`. The owner asked Claude to review the completed branch and approved its merge once the review and the verification succeeded.

## Scope of the review

The review checked the implementation against decisions D1-D14 of the [entry review](entry-review-017b.md), the [design note](design-017b.md) and the [evidence](evidence-017b.md):
- **The guarded function `purge_agency_batch` (D9), the most sensitive part:**
  - `SECURITY DEFINER`, owned by the migration role, with `search_path = pg_catalog, pg_temp`;
  - every table reference qualified with `public.`, so a temporary table cannot shadow one;
  - `EXECUTE` revoked from `PUBLIC` and granted to `tracking_lifecycle` only.
  - Its guard refuses an agency that is not closed, whose offboarding has not completed, that has a live connection, or that has a teardown before its deadline.
  - It deletes from all 81 tenant tables, children first, through NOT NULL paths, and keeps only the agency row, its plan assignments and its purge record.
  - It replaces the name only after a complete walk with budget to spare.
- **Migration `0033_agency_offboarding`:** the three tables, the progress check that ties a purge record's state to its times, the widened reasons and audit values, the grants, and the guarded downgrade.
- **The offboarding pass (D6):** the disconnection of every live connection with `agency_closed` through `start_disconnect`, so that the 009 teardown revokes tokens and purges provider data; the revocations and the disabled sources, destinations and numbers; idempotence, and two workers that skip each other.
- **The purge step (D7):** the lifecycle loop, its lock timeout, its refusals and its resumption.
- **The offboarding export (D2-D5):**
  - the Owner-only, reauthenticated and throttled request until 24 hours before the closing time;
  - the 36-table allowlist, with every left-out column declared and no secret, digest, token or provider data exported;
  - the bounds, the checks of the ZIP against its manifest, and the parts sealed and bound to the agency, the export and the part number;
  - the store only while the agency is still closing, under the agency lock;
  - the streamed download with the Owner resolved again.
- **The rest:** the operator command (D11), the data policy rows, the contract, the tests and the documentation.

## Verification run by the reviewer

All cases ran on a fresh disposable PostgreSQL 18.6 service (127.0.0.1:55433, `tracking_foundation_test`), with the repository's three roles and synthetic settings only. The committed integration guard still requires port 55433; the port the implementing model used on its workstation was never committed.

| Check at `d3cb66f` | Result |
|---|---|
| `ruff check app tests migrations`, `ruff format --check app tests migrations` | Clean (339 files) |
| `pytest -m "not integration"` | 986 passed |
| `pytest -m integration` with `TRACKING_RUN_BROWSER_TESTS=1`, Chromium | 824 passed, 7 skipped (the opt-in AV16, BV19 and D-076 measurements), none failed; the Firefox journey case not run |
| Tracker unit, and tracker browser with Chromium | 73 and 25 passed |
| `pip check`, `git diff --check`, relative links of the changed Markdown (409 in 19 files) | Clean |
| OpenAPI, semantic comparison with `main` | 2 paths and 3 schemas added; nothing removed or changed |
| Database privileges after the migration | Only `tracking_lifecycle` (and the owner) may execute the function; `tracking_app` may not. `tracking_lifecycle` has no direct delete right on `agencies`, `client_workspaces`, `agency_memberships`, `revenue_evidence`, `ledger_movements`, `connector_connections` or `audit_events`. |
| The stored function's body | 83 delete statements and no unqualified table reference |

Firefox is not installable in the review environment, so the Firefox cases were not run here. The implementing model's evidence records them passing.

## Findings

No defect was found. The following points are recorded limits, without a change:
- **Teardowns past their deadline.** A connection whose teardown has not settled by its 72-hour deadline is purged anyway, as D7 states. A token that its provider never confirmed revoked is then destroyed without that confirmation.
- **Queued mail.** Invitation and `report_ready` messages carry no agency reference, so the purge cannot select them. They expire with their invitation or export, and their links stop working at once.
- **Scale.** The two self-referencing tables and `bookings.subject_id` have no index on the referencing side, so very large purges are slower; production sizes come with Q-004 and 020.
- **Backups and live checks.** A restore must reapply the recorded purges (020). The teardown of live Meta and Google connections is an owner-operated check after the merge.

## Result

PR 21 merged into `main` as `04dc323`, a merge commit of `e3b3005` and `d3cb66f` whose tree equals the reviewed head `d3cb66f`.
