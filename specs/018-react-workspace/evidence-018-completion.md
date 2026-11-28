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
- On the design canvas, the screens built on 2026-11-28 (A03, B13 to B15, C01 to C10, E03 to E08) still show the reference page each was built from.
- Development email is the local `.eml` capture; production email, the report worker's schedule, hosting and deployment are decided in 020. No live provider was called; the journeys use the stand-in providers of the disposable stack.
- The backend's tracker browser journeys were skipped, as in P0 (see section 2).
