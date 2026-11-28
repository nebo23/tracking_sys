# Evidence: the end of the Spec 018 completion round (P5)

Status: phase P5 of the [completion handoff](implementation-prompt-completion.md), under D-106, on `codex/spec-018-workspace-screens`, on 2026-11-28. It records the last update with `main`, the renumbering, what the update changed in the built screens, the checks of the whole and the pull request. Nothing is accepted until the owner has reviewed it.

## 1. The last update with `main`
`main` had moved from `e3b3005`, which P0 took, to `7c7b5b5`. It brought the merge of Spec 016-C (D-096), Spec 017-B and its merge (D-097 to D-099: the copy of an agency's data while it closes, the disconnection of its connections when the closure completes and the guarded purge, migration `0033_agency_offboarding`) and Spec 017-C (D-102, D-103: Paddle billing, a 14-day trial and a hold, migration `0034_saas_billing`, off by default).

| Step | Commit | Result |
|---|---|---|
| Merge of `main` at `7c7b5b5` | `634b6bc` | Conflicts only in `AGENTS.md`, `docs/planning/decisions.md` and `specs/README.md`, where both sides had added lines; both sides kept. `contracts/openapi.json` merged without a conflict, and the contract test of the backend passes against the merged application. `frontend/src/api/schema.d.ts` was generated again from it (the billing and offboarding paths); `npm run api:check` and `npm run typecheck` pass. |
| Renumbering | `634b6bc`, `9e6aeed` | `main` holds its own D-099 (the 017-B merge), and `claude/keen-fermat-otlr9d` holds D-104 (the 017-C merge). This branch's D-099 (the completion approval) became D-106 and its D-104 (the Reports drawings) became D-107; D-105 (the sign-in picture) kept its number. The records were renumbered in the merge, and every other reference in `9e6aeed`. The plan and evidence of P0 keep D-099 where they describe the renumbering of that phase, and say so. Commit messages up to `a77b3eb` keep the old numbers; the register's numbering note lists them. |
| Adoption | `86a384a` | The unit test that reads the audit calls of the API found twelve actions without a sentence: the copy of the agency's data (requested, revoked), the subscription (checkout, plan change, cancellation and its removal, correction from the payment provider), the operator's grants and trial extension, and the operator's prices, which are platform rows that no agency's log lists. Each has a sentence in English and Arabic. |

No other screen needed a change. The unit tests that compare the rules of the interface with the backend sources (error codes, audit actions, plan limits, report bounds and reasons, financial rules) pass against the merged backend.

## 2. Checks
Every check ran on the final code of the branch, on 2026-11-28, on this workstation.

| Check | Result |
|---|---|
| Backend: `ruff check .` and `ruff format --check .` | No finding; 362 files already formatted. |
| Backend unit tests | 1,030 passed (969 after P0). |
| Backend integration tests | 876 cases in nine batches of 72 to 110 cases (2 to 5 minutes each) on this session's own disposable Compose project `tracking-018-p5-test` on 127.0.0.1:55433, removed afterwards: 866 passed and 10 were skipped: the opt-in measurements (BV19, AV16 and the 006/007 review measurement) and the three tracker browser journeys, whose Playwright copy is not installed in this worktree, as in P0. Windows no longer reserved 55433 that day, so the committed integration guard ran unchanged. |
| `npm ci` | 441 packages from the lockfile; the lockfile is unchanged. ESLint 9 reports its end of support, as recorded under D-085. |
| `npm audit` | 7 moderate findings, all one `minimatch` advisory reached through `typescript-eslint`, development only (as in 018-A); none in the runtime packages. |
| `npm run api:check`, `npm run typecheck`, `npm run lint` | "The contract types match contracts/openapi.json."; no type error; no finding. |
| `npm test` | 33 files, 607 tests passed. |
| `npm run build`, then `npm run build:check` | Built. "No secret, key, token or backend setting was found." The first page loads seven script files, 774.11 kB (769.85 kB after P4; the difference is the twelve audit sentences in both languages). |
| Journeys, Chromium | 64 journeys in four groups, all passed: files 01 to 09, 22 (2.4 minutes); 10 to 12, 27 (9.6 minutes, in the background); 13 to 16, 8 (1.9 minutes); 17 to 23, 7 (1.8 minutes). |
| Journeys, Firefox | 64 journeys in the same groups, all passed: 22 (2.7 minutes), 27 (11.5 minutes, in the background), 8 (1.6 minutes) and 7 (1.4 minutes). Each run removed its disposable stack (`tracking-e2e-frontend`) in its teardown. A comment of the navigation was corrected while the Chromium group 10 to 12 ran; the build after it has the same content hash (`index-CKDQalLk.js`), so every journey ran against the final application. |
| Accessibility | The 22 axe tests of journey 10 in each browser report 0 serious or critical and 0 moderate or minor findings, in the four looks (English and Arabic, light and dark) and at 390 pixels. |
| Relative links | 41 Markdown files that differ from `main`, 583 relative links and their anchors: none broken. Before it was trusted, the check found a planted missing file and a planted missing heading. |
| `git diff --check` | Clean. |

## 3. What the pull request holds
[Pull request 23](https://github.com/nebo23/tracking_sys/pull/23), opened at `4fb1806` from `codex/spec-018-workspace-screens` against `main` (D11 of the completion entry review), without a further upload request (D-106). It holds the commits of pull request 17 (slice 018-A, head `edc2d54`, open), on which this branch is stacked, so merging it also merges 018-A. Its description lists the decisions, the scope by phase, the packages, the addresses, the permissions, the checks with their counts, the limits and what remains. It is not merged: the merge is the owner's decision, after Claude's independent review.

## 4. Limits
- The concepts B12 (privacy and data), C11 (a journey of one person) and F05 (search) are not built (D10); the agency's brand on the screens of client viewers waits for the owner's brief (D8); PDF files and printable pages are not part of this round (D-095).
- Main's 017-B and 017-C have no screens yet: an Owner cannot ask for the copy of the agency's data from the closing page, and the subscription, the trial and the hold are not shown. While billing is enabled, an agency on hold is refused new clients, seats, connections and links by the existing plan limits, whose values are zero; the interface then shows its plan-limit message, which does not say that the reason is the hold. Billing is off by default and on the disposable stack.
- The legal texts are not written (the agreement versions are `draft-1`), so no real user may be given the application before they exist.
- The Arabic copy is written by a model and marked for review by a native editor (D12).
- Four display defects were found on 2026-11-28 after these checks, when the design canvas was captured from the running application, and were corrected the same day: see section 5.
- The design canvas shows the screens built in the completion round, and the website-tracking boards, as captured from the corrected application.
- Development email is the local `.eml` capture; production email, the report worker's schedule, hosting and deployment are decided in 020. No live provider was called; the journeys use the stand-in providers of the disposable stack.
- The backend's tracker browser journeys were skipped, as in P0 (see section 2).

## 5. Corrections after P5
The four display defects of section 4 were corrected on 2026-11-28 at the owner's request ("Yes, fix them"), within D-106 and without any change to the API, the contract or the schema, in commit `d29ac00`. Claude's [merge review](merge-review-018.md) confirmed them as K1 to K4.

| ID | Defect | Correction |
|---|---|---|
| K1 | Thirty table cells in thirteen files carried `u-num`, which makes a cell an inline block. | No table cell carries `u-num`; the numbers inside are wrapped in `<span class="u-num">`, so an Arabic sentence in a cell keeps its own order. Cells that hold a sentence (the plan's use, an export's size and rows) keep the cell's direction. |
| K2 | The Content destination asked for the icon `image`, which the icon set does not draw. | It uses `chart-column`, as the design does, and `image` left the icon union. |
| K3 | Three money figures wrote the currency twice. | `MoneyFigure` splits the formatted amount into the number and the currency as its unit, in the order of the language: `EGP` before the amount in English, the pound after it in Arabic, as the designs draw them. |
| K4 | The Sources card of the overview showed the API's stream name. | Each stream of `backend/app/reporting/catalog.py` has a sentence in both languages; an unknown stream shows none, and a time zone stays left to right. |

The regressions fail at `e141077`, whose application equals `7554857`, and pass at `d29ac00`:
- `tests/unit/lib/markup.test.ts`: every name of the icon union exists in `connect-icons.css`, and no table cell in `src` carries `u-num`;
- `tests/unit/lib/analyzeRules.test.ts`: the money parts in English and Arabic, and the stream sentences compared with the reporting catalog;
- `tests/unit/features/analyze.test.tsx`: the overview writes each currency once and names its stream in a sentence.

| Check | Result |
|---|---|
| `npm run typecheck`, `npm run lint`, `npm run api:check` | No error, no finding; the contract types match. |
| `npm test` | 34 files, 611 tests passed (607 before, and four new). |
| `npm run build`, then `npm run build:check` | Built; no secret found. The first page loads seven script files, 774.83 kB (the stream sentences in both languages). |
| Journeys, Chromium | 64 passed: 22 (1.7 minutes), 27 (6.9 minutes, in the background), 8 (1.4 minutes) and 7 (1.3 minutes). |
| Journeys, Firefox | 64 passed: 22 (1.7 minutes), 27 (8.7 minutes, in the background), 8 (1.6 minutes) and 7 (1.5 minutes). |
| Accessibility | The 22 axe tests of journey 10 in each browser: 0 findings of any severity. |

The checks ran in a separate worktree at the corrected commit, on a disposable stack of its own (Compose project `tracking-e2e-fix` on 127.0.0.1:56444, API on 8020, application on 5193), so the merge review, which shares this branch's worktree, was not disturbed; the ports were changed only in that worktree and never committed. The commit was then applied on top of the review's own commits; the review file is the only difference.

The design canvas was captured again from the corrected application: A03, B13 to B15, C01 to C10 and E03 to E08, and the website-tracking boards D09 to D12 and G03, whose diagnostics table showed K1.

The other findings of the merge review, R018-01 to R018-06, were not part of this correction; section 6 records theirs.

## 6. Corrections of the merge review
At the owner's request of 2026-11-28, the six defects of Claude's [merge review](merge-review-018.md), R018-01 to R018-06, were corrected the same day, frontend only, within D-106 and without any change to the API, the contract or the schema: in commit `0900d44`, completed for R018-04 by `6159bfd`. Journey 20 was adjusted in `0b6e50a`.

| ID | Correction |
|---|---|
| R018-01 | The overview tells a revenue or spend report it could not read from an empty one: such a figure is "Not available", with the sentence of the error. `report_requires_ledger_upgrade` and `report_too_large` gain sentences in the error table, which the Revenue and Ad spend pages also use. |
| R018-02 | The overview's spend figure carries the Provisional badge while a spend total is provisional, as the Ad spend page does. |
| R018-03 | Without financial access, the models side by side say that their values are credited leads, because sale values need financial access. |
| R018-04 | The closing page is drawn as B15, with its top bar and the page only. Nothing asks for the profile or the clients of a closing agency, which the API refuses while an agency is not active (`TenancyService._membership`): the switcher, which stays on the account page to reach another agency, calls a closing agency "Your agency", marked Closing (`6159bfd`), and the closing agency offers no destination of its own. |
| R018-05 | The schedule form keeps listing recipients who are no longer active members (by name, or as a former member for a closed account or a removed membership), chosen and marked, so that they can be unticked; the schedules tab names `invalid_recipient` when a pause is refused for that reason. |
| R018-06 | The return tab offers neither the CSV nor an export once its report was refused for want of financial access. |

Seven regressions, in `analyze.test.tsx`, `attribution.test.tsx`, `settings.test.tsx` and `reports.test.tsx`, fail at `6fd3754` and at `7554857`, the head the review examined, and pass at `0900d44`. The run at `7554857` used a scratch worktree with the new test files copied in, removed afterwards; there, as expected, the rewritten closing test and the K4 assertion that `d29ac00` added to an overview test fail as well. Two tests of `workspace.test.tsx` fail at `0b6e50a` and pass at `6159bfd`: the closing test, which had asserted the switcher, and the request the API refuses, on the closing page, now asserts B15 and, on the account page, the switcher's "Your agency" with no name left loading; the test of another closing agency in the switcher no longer serves the profile that the API refuses.

| Check | Result |
|---|---|
| `npm run typecheck`, `npm run lint`, `npm run api:check` | No error, no finding; the contract types match. Again at `6159bfd`. |
| `npm test` | 34 files, 618 tests passed (611 before, and seven new), at `0900d44` and at `6159bfd`. |
| `npm run build`, then `npm run build:check` | Built; no secret found. The first page loads seven script files, 776.69 kB (the new sentences in both languages), at both commits. |
| Journeys, Chromium | 64 passed: 22 (1.7 minutes), 27 (6.8 minutes, in the background), 8 (1.4 minutes) and 7 (1.3 minutes). In the first run of the last group, journey 20 looked for the spend figure by the exact text of its label, which the new Provisional badge extends; `0b6e50a` matches the label by its text, and the group then passed. After `6159bfd` the last group, whose journey 22 closes an agency and keeps it, passed again: 7 (1.3 minutes). |
| Journeys, Firefox | 64 passed: 22 (1.6 minutes), 27 (8.7 minutes, in the background) and 8 (1.6 minutes) at `0b6e50a`, and the last group, 7 (1.6 minutes), at `6159bfd`. Two earlier runs of that group are not counted: one at `0b6e50a`, which named journey 22 by a wrong file name, so it did not run, and one at `6159bfd`; journey 19 failed in both. |
| Accessibility | The 22 axe tests of journey 10 in each browser: 0 findings of any severity. Commit `6159bfd` changes none of the pages they check: the closing page is drawn the same, and the other pages belong to an agency that is not closing. |

Journey 19 failed in three of the six runs of the last group in this round, each time at its CRM step: after a signed stage change and a reload, the figure "Won, payment not matched" showed 0 instead of 1. This is the intermittent failure of section 2.4 of the [P0 evidence](evidence-018-update.md), more frequent now; its cause is still open there. The corrections do not touch the integrations pages or the API, and the failed runs' traces were not kept.

The checks ran in a separate worktree at the corrected commits, on a disposable stack of its own (Compose project `tracking-e2e-fix` on 127.0.0.1:56444, API on 8020, application on 5193); the ports were changed only in that worktree and never committed. The branch was then fast-forwarded to those commits, so the commits verified are the commits on the branch.

The design canvas shows B15 and the overview boards C01 to C04 captured again from the application at `6159bfd`.
