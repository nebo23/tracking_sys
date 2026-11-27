# Evidence: both 018 branches up to date with `main` (P0)

Status: complete on 2026-11-28. Part 1 was written on `codex/spec-018-react-workspace` (pull request 17); part 2 covers `codex/spec-018-workspace-screens` after it took that branch. The plan is [plan-018-update.md](plan-018-update.md).

Authority: D-091 (pull request 17 is brought up to date once, when the frontend work starts) and D-099 (the owner's approval of D1-D12 of the Spec 018 completion entry review and its implementation handoff, `specs/018-react-workspace/entry-review-completion.md` and `implementation-prompt-completion.md`). D-099 and those two files are recorded on `codex/spec-018-workspace-screens`, not on this branch.

## 1. Pull request 17

### 1.1 The merge
`git merge origin/main` at `e3b3005` into `1c4ee9e`. As the trial merge of the completion entry review predicted, only the four record files conflicted:

| File | Resolution |
|---|---|
| `AGENTS.md` | `main`'s line on D-081 to D-087, then this branch's lines D-081 to D-087, then `main`'s D-088 to D-095. |
| `README.md` | This branch's `docs/design/` row and `main`'s newer `specs/` row. |
| `docs/planning/decisions.md` | Both numbering notes: this branch's history of the 018 renumbering and `main`'s note that D-081 to D-087 join the register when pull request 17 merges. Rows D-081 to D-087, then D-088 to D-095. `main`'s Q-005 (the 017-A note) and this branch's Q-006 (the languages of D-083). The date of the register. |
| `specs/README.md` | `main`'s rows of 016 and 017, this branch's row of 018. |

Every other file merged without a conflict. This branch changes no backend, contract or infrastructure file, so after the merge `git diff origin/main -- backend contracts infra` is empty. The register holds D-001 to D-095, each number once.

### 1.2 The contract types
`npm run api:types` generated `frontend/src/api/schema.d.ts` again from `main`'s `contracts/openapi.json`, and `npm run api:check` answered "The contract types match contracts/openapi.json." `npm run typecheck` then failed only in unit-test fixtures that built an `AgencyAccess` without its new `status`; they now carry `status: 'active'`.

### 1.3 What 017-A changed in the screens of 018-A

| Change on `main` | Where | Behavior now |
|---|---|---|
| Agreement versions | `src/api/agreements.ts`, `src/api/session.ts`, the sign-in and registration pages | The page reads `GET /auth/agreements` when the person submits (a cached answer for five minutes, never retried, so a failure shows at once) and sends `agreements: {terms, privacy}` with `POST /auth/login` and `POST /auth/register`. Google sign-in opens `/auth/google/start?terms=...&privacy=...`. |
| `422 agreement_required` (A03) | The sign-in and registration pages | The cached versions are dropped, the box is unticked and focused, what was typed stays, and a warning above the form says "The terms changed while this page was open." with the sentence of the page. The next attempt reads the new versions. |
| `error=agreement_required` on the Google return | The route `/auth/google/complete` | Without a session it goes to `/sign-in?notice=termsChanged`, which shows the same warning. |
| The error table | `src/api/errors.ts` | `agreement_required` has a sentence in both languages; the unit test that reads the codes of `backend/app/api/google.py` requires it. |
| `Retry-After` readable by the browser | none | The sentence that names the wait ("Try again in 60 seconds.") now appears after too many attempts; journey 03 expected the sentence without a number and was updated. |
| The frontend guide | `frontend/README.md` | The agreement is recorded by the API; the legal texts are still missing. |

### 1.4 Checks
| Check | Result |
|---|---|
| `npm run api:check` | The types match the contract. |
| `npm run typecheck` | Passed. |
| `npm run lint` | Passed, no finding. |
| `npm test` | 14 files, 203 tests passed. |
| `npm run build`, then `npm run build:check` | Built: one script of 643.06 kB (195.96 kB compressed) and a stylesheet of 148.62 kB. "No secret, key, token or backend setting was found." |
| Journeys, Chromium | The first run passed 38 of 39: journey 03 failed on the sentence described in 1.3. After its expectation was updated it passed alone (18.4 s), and a full run then passed 39 of 39 (4.4 minutes). |
| Journeys, Firefox | 39 of 39 passed (3.9 minutes). |
| Accessibility | The 13 axe tests of the full Chromium run report 0 serious or critical and 0 moderate or minor findings. |
| `git diff --check` | Clean. |
| Backend suites | Not run on this branch, because its backend equals `main`'s; they run on `codex/spec-018-workspace-screens`, whose backend adds amendment B1 and B2 of the 018-B plan (members and archived clients). |
| `npm ci` | Not run on this branch: the update changes no package and the lockfile equals the stacked branch's, where it runs. |

### 1.5 V01 of the verification matrix
- **Sent and accepted.** Every journey that registers or signs in, on the screens or through `tests/browser/support/people.ts`, passes against `main`'s API, which refuses a request without the current versions. Journey 01 also checks that the body of the sign-in carries exactly the versions of `GET /auth/agreements`.
- **Refused and recovered.** A new journey in `01-first-visit.spec.ts` serves an outdated terms version on the first read of the versions. The API answers that sign-in with 422; the warning appears, the box is unticked and focused, and the email stays. With the box ticked again, the second sign-in carries the current versions, is answered 200 and opens the workspace. It passed in Chromium and in Firefox.
- **Registration and Google.** Registration recovers in the same way in a unit test. The disposable stack runs with Google sign-in switched off, so the Google start (its address carries the versions, a failed read stops it) and the Google return with `error=agreement_required` are covered by unit tests only.

## 2. The stacked branch

### 2.1 The merge
`git merge codex/spec-018-react-workspace` at `c68d444` into `09cc891`. Six files conflicted:

| File | Resolution |
|---|---|
| `AGENTS.md`, `docs/planning/decisions.md` | Both sides hold a D-093 and a D-094: `main`'s (the 017-A merge, the 016-C preparation) and this branch's (the remaining interface, amendment B1-B3). `main`'s D-088 to D-095 come first; this branch's two are renumbered (2.2) and follow D-099. |
| `README.md` | This branch's design row (it names 018-B) and `main`'s specifications row. |
| `frontend/src/api/errors.ts` | Both additions to the error table: this branch's plan, collection and integration codes and the `agreement_required` of part 1. |
| `frontend/tests/browser/support/people.ts` | This branch's version, whose API helpers moved to `support/api.ts`; those helpers now send the versions (commit `c6a637b`). |
| `frontend/tests/unit/features/signIn.test.tsx` | Both sides' imports, and this branch's landing page (Clients) with the versions in the body. |

The contract changes of both sides (amendment B1-B3 here, 016-B, 017-A and 016-C on `main`) merged without a conflict. The snapshot test `backend/tests/test_contract.py` passes, so the merged `contracts/openapi.json` equals the API's own document, and `npm run api:types` changed nothing.

### 2.2 The renumbering (V02)
Just before it, the highest numbers were: `main` at `e3b3005`, D-095; `claude/keen-fermat-otlr9d` at `dc92506`, D-098 (the approval of Spec 017-B, recorded while this phase ran; it reserves no later number); `codex/spec-018-react-workspace`, D-095 after its update; this branch, D-099. Pull request 17 was the only open pull request.

- As D-096 requires, this branch's D-093 (the remaining interface) became **D-100** and its D-094 (amendment B1-B3) became **D-101**.
- The merge commit `828ca92` renumbered the records: the two rows and lines, the references inside them and in D-099, and a new line of the numbering note. Commit `ed4fd0a` changed 33 references in 14 other files: the 018-B and 018-D plans and evidence, the spec, the tasks, the screen list, the 002 auth design, and the comments that the amendment added to `backend/app/api/schemas.py`, `backend/app/api/tenancy.py`, `backend/app/services/tenancy.py`, `backend/tests/integration/test_member_details.py`, `frontend/src/api/team.ts` and journey 16. The completion packet and its handoff name the new numbers where they mean these decisions.
- Every remaining D-093 and D-094 on this branch is `main`'s, or a sentence that describes the renumbering itself. Commit messages are not rewritten; those up to `09cc891` use the old numbers.
- The register now holds D-001 to D-095 and D-099 to D-101, each number once. D-096 to D-098 are recorded on `claude/keen-fermat-otlr9d`.

### 2.3 The rest of section 4.2

| Change on `main` | Where | Behavior now |
|---|---|---|
| `409 plan_limit_reached` with `limit`, `value` and `used` | `src/api/errors.ts`, `src/api/client.ts` | The error keeps the limit, and the sentence names it: "The agency's plan allows 10 seats, and 10 are in use, so no more can be added." Without the three values the existing sentence stays. The link to Plan and usage follows in P3. |
| `plan_limit_reached` on the return from a provider | `src/features/connections/returnErrors.ts` | Its own sentence; the unit test that reads `CALLBACK_ERRORS` of `backend/app/services/connectors.py` requires it. |
| `actor_kind` | The audit log (B11) | A row of the platform operator names "The Connect operator". The actions that 017-A and 016-C added (the plan, suspension, closure, report exports and schedules, branding) have sentences; the unit test that reads every audit action of the backend requires them. |
| `AgencyAccess.status` | The switcher, the start page, `/agencies/{a}/closing` | The switcher marks a closing agency. The start page prefers an agency that is not closing. A closing agency opens only its page at `/agencies/{a}/closing` (B15), because the API refuses its other routes; P3 adds the closing date and keeping the agency. An agency that is not closing has no such page. |

### 2.4 Checks
| Check | Result |
|---|---|
| `ruff check app tests migrations` | All checks passed. |
| `ruff format --check app tests migrations` | 325 files already formatted. |
| `pytest -m "not integration" -q` | 969 passed, 810 deselected (29 s). |
| `pytest -m integration -q` | The 810 cases in five foreground batches on one disposable database: 144 passed and 3 skipped; 159 passed and 3 skipped; 164 passed; 168 passed; 165 passed and 4 skipped. In all, **800 passed and 10 skipped**. The skipped cases are the opt-in measurements BV19 (3), AV16 (3) and the 006/007 review (1), and the tracker's browser journeys (3), whose Playwright copy is not installed in this worktree. |
| Disposable database | Windows reserves the ports 55365 to 55464 today (55433 included), and another session's disposable database held 56433. This session ran its own Compose project `tracking-018-p0-test` on 127.0.0.1:56435 with synthetic secrets kept in the scratchpad. Only the port number of the integration guard was changed, during each batch; it was restored byte for byte after each one (SHA-256 `2b5e486375383dabc55ed088f80e2c1aef6b1332826109d59c86ffcbbc107c68`), and `git status` shows the guard unchanged. The project was removed with `down --volumes`. |
| `npm ci` | Installed from the committed lockfile. `npm audit`: no critical or high finding; seven of moderate severity, all the `minimatch` advisory of the lint tooling that D-085 left open. |
| `npm run api:check`, `npm run typecheck`, `npm run lint` | The types match; passed; passed, no finding. |
| `npm test` | 26 files, 528 tests passed. |
| `npm run build`, then `npm run build:check` | One script of 1,052.32 kB (288.09 kB compressed). "No secret, key, token or backend setting was found." |
| Journeys, Chromium | 55 journeys in four groups. Files 01 to 09: 22 passed (1.7 minutes); 10 to 12: 22 passed (4.7 minutes); 13 to 16: 8 passed (1.5 minutes); 17 to 19: 2 passed and 1 failed. Journey 19 failed at its CRM step, where the figure "Won, payment not matched" showed 0 instead of 1 after the page was reloaded. It then passed alone (23.3 s) and in a second run of the group (3 passed, 36.8 s). The count is computed synchronously from the stored deals and the active stage rules (`deals_view` in `backend/app/services/integrations.py`), and the cause was not found; about 0.7 GB of memory was available on the workstation during the runs. It is recorded as an intermittent failure, not as a pass. |
| Journeys, Firefox | 55 passed in the same four groups (1.6, 6.8, 1.7 and 0.8 minutes). |
| Accessibility | The 17 axe tests of journey 10 report 0 serious or critical and 0 moderate or minor findings, in each browser. |
| `git diff --check` | Clean. |

### 2.5 V01 to V04
- **V01 Agreement.** Part 1, and on this branch the new test of journey file 01, which serves an outdated version once: it passed in Chromium and in Firefox and ends on the agency's clients.
- **V02 Records.** Section 2.2.
- **V03 Built screens after the merge.** The 54 journeys of 018-A, 018-B and 018-D, the new agreement journey and the 528 unit tests pass on this branch, with the one intermittent failure of section 2.4. The operator rows and closing agencies are covered by new unit tests in `audit.test.tsx`, `workspace.test.tsx` and `sessionLifecycle.test.ts`; their journey arrives with P3 (`22-agency-settings`).
- **V04 Backend after the merge.** The unit and integration suites pass on disposable PostgreSQL as section 2.4 records, and the OpenAPI snapshot matches.

### 2.6 Left for later phases
- The closing page B15 (the closing date and keeping the agency) and the link from the plan-limit sentence to Plan and usage: P3.
- The cause of the intermittent CRM count in journey 19, if it returns.
- The description of pull request 17 was not changed.
