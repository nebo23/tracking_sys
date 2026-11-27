# Evidence: both 018 branches up to date with `main` (P0)

Status: part 1 of 2, written on `codex/spec-018-react-workspace` (pull request 17) on 2026-11-28. Part 2, for `codex/spec-018-workspace-screens`, is added on that branch after it takes this one.

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
| Backend suites | Not run on this branch, because its backend equals `main`'s; they run on `codex/spec-018-workspace-screens`, whose backend adds D-094's B1 and B2. |
| `npm ci` | Not run on this branch: the update changes no package and the lockfile equals the stacked branch's, where it runs. |

### 1.5 V01 of the verification matrix
- **Sent and accepted.** Every journey that registers or signs in, on the screens or through `tests/browser/support/people.ts`, passes against `main`'s API, which refuses a request without the current versions. Journey 01 also checks that the body of the sign-in carries exactly the versions of `GET /auth/agreements`.
- **Refused and recovered.** A new journey in `01-first-visit.spec.ts` serves an outdated terms version on the first read of the versions. The API answers that sign-in with 422; the warning appears, the box is unticked and focused, and the email stays. With the box ticked again, the second sign-in carries the current versions, is answered 200 and opens the workspace. It passed in Chromium and in Firefox.
- **Registration and Google.** Registration recovers in the same way in a unit test. The disposable stack runs with Google sign-in switched off, so the Google start (its address carries the versions, a failed read stops it) and the Google return with `error=agreement_required` are covered by unit tests only.
