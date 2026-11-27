# Spec 018 completion: implementation handoff

Prepared 2026-11-27 at the owner's request to prepare the specification and the implementation prompt of Spec 018. This handoff executes the [completion entry review](entry-review-completion.md) once the owner has approved its decisions D1-D12; until that approval is recorded it authorizes nothing. Communicate with the owner in Arabic, and write every project file, commit and pull request in formal English.

## Where to work

1. Use the existing worktree `.worktrees/spec-018-react-workspace`. Both 018 branches share its single `frontend/node_modules`, so switch branches in place instead of adding a worktree. Fetch `origin`.
2. The branches:
   - `codex/spec-018-react-workspace`: pull request 17, slice 018-A, head `1c4ee9e` on 2026-11-27;
   - `codex/spec-018-workspace-screens`: slices 018-B and 018-D, the A to Z designs and this preparation, stacked on the first.

   Check that both are clean and equal to their remote branches before the first change.
3. Note the heads of `origin/main` (`e3b3005` on 2026-11-27) and `origin/claude/keen-fermat-otlr9d` (`2a0deb1`, where D-096 is recorded), and report any newer commit before P0.
4. **Decision numbers.** A new record takes the next free number after the highest one on `main`, on the coordination branch, on these branches and in any open pull request. D-096 was the highest on 2026-11-27. Check again before every record.
5. Preserve owner files, other worktrees and the Compose projects of other sessions (for example `tracking-test-*`).

Read the following before the first change:
- **Project rules and decisions:** `AGENTS.md`, `README.md`, and in `docs/planning/decisions.md`: D-015, D-039, D-051, D-081 to D-087, D-091, `main`'s D-093 to D-095, D-096 on the coordination branch, this branch's D-093 and D-094, and the decision that approves this packet.
- **The packet:** the [completion entry review](entry-review-completion.md): D1-D12, section 4 (design) and section 5 (verification matrix).
- **Spec 018:**
  - the [spec](spec.md), the [entry review](entry-review.md) (D1-D15, especially the data-state rule and the date ranges);
  - the plans and evidence of [018-A](plan-018a.md) ([evidence](evidence-018a.md)), [018-B](plan-018b.md) ([evidence](evidence-018b.md)) and [018-D](plan-018d.md) ([evidence](evidence-018d.md)): how slices are built, checked and recorded here;
  - [screens-a-to-z.md](screens-a-to-z.md) for the screen codes;
  - the [frontend guide](../../frontend/README.md).
- **Design:** the [design README](../../docs/design/README.md) and the reference pages in `docs/design/preview/screens/`: `overview.html`, `overview-mobile.html`, `content.html`, `revenue.html`, `ad-spend.html`, `attribution.html`, `attribution-funnel.html`, `attribution-roas.html`, `agency-settings.html`, `agency-closure.html` and `agency-closing.html`. Where a reference page and the built shell differ (C01 to C06 were drawn with an earlier top bar and Settings and Help items), the built shell wins.
- **API, after P0:**
  - `contracts/openapi.json`;
  - `backend/app/api/reports.py` and `backend/app/reporting/` (states, reasons, bounds, CSV);
  - the [reporting guide](../../docs/engineering/reporting.md);
  - the entry reviews of 016-A (`specs/016-analytics-reporting/entry-review.md`), 016-B (`entry-review-016b.md`) and 016-C (`entry-review-016c.md`), with their design sections;
  - sections 4 to 6 of `specs/017-saas-lifecycle/design-017a.md` (usage view, closure, agreement record);
  - `report_ready_message` in `backend/app/services/mail.py` (the address a report email opens).
- **Frontend patterns:**
  - `frontend/src/api/` (client, errors, query keys, settled codes) and `frontend/src/app/` (router, shell, navigation, tenant scope);
  - `frontend/src/components/` and the features `links` (tabs kept in the address), `tracking` (values shown once, erasure) and `integrations`;
  - `frontend/tests/unit/` (tests that read backend rules) and `frontend/tests/browser/support/` (stack, tenants, collect, mail).

## Authority

- **Gate.** Before any application change, find the decision that approves D1-D12 of the packet and any amendment it names. If it is missing, stop and ask the owner in Arabic; do not ask again for approvals already recorded.
- **Drawings first (D9).** No code of P4 before the owner has approved its drawings. Record that approval with the next free number, or quote the owner's words in the P4 plan if the owner approves without a record.
- **Amendments.** An amendment named by the approval replaces the matching text of the packet and of this handoff.
- **Precedence.** The latest owner instructions take precedence over this handoff. A fact found during the work that changes a decision goes back to the owner before code depends on it: for example a needed API change, another package, or a resolution that differs from section 4.5 of the packet.
- **Publication.** Push verified commits after each phase (D-051). P0 updates pull request 17. At the end, open one pull request (D11). Do not merge: the merge is a separate owner decision after Claude's independent review.

## Boundaries

- **Packages.** Only the two of D3, at exact versions: `recharts` 3.10.1 and `react-is` 19.3.1. Anything else, or another version, needs a new decision. Install only inside `frontend/` with the committed lockfile (D-011).
- **API, contract and schema.** No change. The merge of P0 brings `main`'s API as it is.
- **Data and environments.**
  - Synthetic data only, on the disposable stack and the disposable PostgreSQL service; never the native `tracking_sys` (D-015).
  - No live provider and no external email: report emails stay local `.eml` files.
  - No deployment.
- **Out of scope.**
  - The concepts B12, C11 and F05 (D10), and the agency's brand on the screens of client viewers (D8).
  - PDF files and printable pages (D-095), and payments, prices and trials (017-B, 017-C).
  - Specs 012 and 013 (D-063).
- **Secrets.** Never print the sandbox's sign-in password. Never commit a key, token, signing secret, signed address, `.eml` file or captured customer value.

## Workstation

- **Node.js.** Version 24.15 or later; `npm ci` inside `frontend/`.
- **Browsers.** The Playwright 1.64.1 browsers are not in the default folder: before each journey run, `export PLAYWRIGHT_BROWSERS_PATH="C:/Code/Tracking-system/.worktrees/spec-005-links-tracker/packages/tracker-js/node_modules/playwright-core/.local-browsers"`. A scratch Node script that drives a browser imports `frontend/node_modules/playwright/node_modules/playwright-core/index.mjs` (the top-level `playwright-core` is another release).
- **Journeys.**
  - Run them from `frontend/` with `npx playwright test --project=chromium`, then `--project=firefox`, one browser per command, in the foreground, with the output in a scratch log.
  - On 2026-11-27 the 54 journeys took 8.1 minutes in Chromium and 12.3 in Firefox. When a run would pass ten minutes, run the files in groups.
- **The disposable stack.** Compose project `tracking-e2e-frontend`; PostgreSQL on 127.0.0.1:56434, the API on 8010 and the built application on 5183. A Playwright run removes it in its teardown. To stop a sandbox that was started in the background:
  1. In PowerShell, find the node process whose command line holds `sandbox.ts` and run `taskkill /pid <pid> /T /F`.
  2. Stop anything still listening on 8010 or 5183.
  3. Run `docker compose -p tracking-e2e-frontend down --volumes --remove-orphans`.
  4. Remove the literal path `frontend/.e2e`.
- **Backend suites (P0).**
  - Use the disposable PostgreSQL service of `backend/tests/README.md` and the project virtual environment.
  - Windows may reserve the port range that holds 55433. Check `netsh int ipv4 show excludedportrange protocol=tcp` and use the documented workaround port if it is reserved.
- **Disk.** Drive C: has run out before (0 bytes on 2026-11-18; 4.4 GB, then 8.7 GB free on 2026-11-27). Check the free space before every journey or integration run and after every few batches. Below about 3 GB, stop and ask the owner with sized options. Delete nothing except a run's own `test-results` and `dist` without the owner's consent.
- **Scratch tools.** One-time scripts stay outside the repository (D-010). A screenshot spec may sit in `frontend/tests/browser/` only while it runs.

## Phases

Each phase:
- starts with a short plan file (`plan-018-update.md`, `plan-018c.md`, `plan-018e.md`, `plan-018f.md` or `plan-018g.md`): routes, components, queries, tests, and any deviation from the packet. A deviation goes back to the owner;
- ends with its checks passing, an evidence file in the form of the [018-D evidence](evidence-018d.md), a commit and a push.

Record commands and exact counts as you go. A skipped case is reported as skipped, never as passed.

### P0: Up to date with `main`

1. On `codex/spec-018-react-workspace`, `git merge origin/main`. Resolve `AGENTS.md`, `README.md`, `docs/planning/decisions.md` and `specs/README.md` by keeping every decision and status line of both sides, in numeric order. `main` holds a numbering note saying that D-081 to D-087 are recorded on this branch and join the register when pull request 17 merges: keep that note and this branch's records of D-081 to D-087, so that the register reads correctly whichever merges first.
2. Generate the contract types again (`npm run api:types`, `npm run api:check`) and make `npm run typecheck` pass.
3. **Agreement versions** (packet section 4.2):
   - the sign-in, the registration and the Google start send the versions of `GET /auth/agreements`;
   - a `422 agreement_required`, or `error=agreement_required` on the Google return, shows the refused state A03 and recovers;
   - unit tests and the sign-in journeys cover it.
4. Run the P0 checks on this branch, then push it. This is the one update of pull request 17 (D-091).
5. On `codex/spec-018-workspace-screens`, merge the updated `codex/spec-018-react-workspace`. Then:
   - renumber this branch's D-093 (the remaining interface) and D-094 (amendment B1-B3), as D-096 requires, to the next free numbers. D-096 was the highest on 2026-11-27, and the approval of this packet takes a number before this step, so check again. Change every reference to them in `AGENTS.md`, `docs/planning/decisions.md`, `specs/018-react-workspace/` and `frontend/`; keep the existing numbering note of Spec 018 and add one line for this renumbering. Commit messages are not rewritten;
   - adopt the rest of section 4.2: operator rows in the audit log, closing agencies in the switcher and the agency list, and `plan_limit_reached` where a creation is refused;
   - run every check, then push.
6. **Checks of P0:**
   - backend, from `backend/` with the disposable database: `ruff check app tests migrations`, `ruff format --check app tests migrations`, `pytest -m "not integration" -q` and `pytest -m integration -q`;
   - frontend, from `frontend/`: `npm ci`, `npm run api:check`, `npm run typecheck`, `npm run lint`, `npm test`, `npm run build:check`, and the journeys in Chromium and Firefox;
   - `git diff --check`.
7. Write `evidence-018-update.md`: the merges, the conflicts and how each was resolved, the renumbering, the checks with counts, and V01 to V04 of the packet's matrix.

### P1: Analyze (018-C)

1. **Packages.**
   - Install the packages of D3 with `npm install --save-exact recharts@3.10.1 react-is@19.3.1`, then `npm ci` from the committed lockfile.
   - Compare the new lockfile entries with section 4.5 of the packet; record `npm audit`, the licences of the full tree and the size on disk.
   - Stop and ask the owner if anything differs.
2. **Loading by route (D4).**
   - Load the workspace pages with the router's lazy routes.
   - Record the size of each chunk.
   - Show that the sign-in page loads no workspace or chart code.
3. **The report layer.**
   - Typed queries for the 016-A social, spend and revenue reports.
   - Components for their states: availability, missing, unsupported, partial, stale, provisional, not comparable and the dependency states, with their reasons in words.
   - A range picker whose ranges end on the last complete day.
   - The comparison switch and the direct CSV download.
   - Tests that compare the states and reasons the interface knows with `backend/app/reporting/`, as `linkRules.test.ts` does for links.
4. **Charts.**
   - One chart module on `recharts`, styled with the reference chart classes and palette tokens.
   - Each chart has a table view and a one-sentence summary, can be used by keyboard, and keeps time left to right in Arabic.
5. **Pages.**
   - Overview (C01, C04 on a phone), Content (C05), Revenue (C06) and Ad spend (C07), in the built shell.
   - The navigation of packet section 4.3, the phone tab bar of D5 with its More menu, and the addresses of section 4.4.
   - Ad spend joins the names of the 014 read `GET .../ad-spend` to the report's IDs.
6. **Tests.** Unit tests for every rule of these pages. A journey `20-analyze` on the disposable stack, with synthetic connections, a worker pass, revenue and spend, that sees each state at least once. Accessibility scans of the new pages in the four looks and at 390 pixels, added to `10-accessibility`.
7. **Removed protections.** Remove each new protection alone and show that a unit test fails, then restore it byte for byte: financial gating, the last-complete-day rule, states named instead of 0, the name join and the client scope of every query.
8. Write `evidence-018c.md`; commit; push.

### P2: Attribution (018-E)

1. **Pages.** One page with the tabs Credit (C08), Funnel (C09) and Return on ad spend (C10) on the 016-B reports, as D6 describes. Every choice is kept in the address: model, group, view, account, level, range and comparison.
2. **States.** Freshness `behind`, `rebuilding` and `failed`; `permission_unavailable`; `not_ready`; ROAS reasons; and the reconciliation `difference`.
3. **Tests.** Unit tests that compare the models, groups, states and reasons with `backend/app/reporting/` and `backend/app/services/attribution_reports.py`. A journey `21-attribution` with synthetic journeys and verified sales, so that credit, the funnel and the return on ad spend have values. Accessibility scans of the three tabs.
4. **Removed protections:** the financial gating, the model in the request, the account and level in the request, and unmatched credit kept apart.
5. Write `evidence-018e.md`; commit; push.

### P3: Agency settings (018-F)

1. **Pages.** The Agency settings destination with the tabs Plan and usage (B13), Branding and Close the agency (B14), and the closing page B15, as D7 describes. The `plan_limit_reached` sentence links Owners and Admins to Plan and usage.
2. **Branding.**
   - Upload the logo as `image/png` with the body the API expects.
   - Refuse SVG and files that are too large or too big before sending, and show the API's own refusal too.
   - Preview the profile on the page only (D8).
3. **Closure.**
   - The exact name and the password; a Google account that must sign in again (`reauthentication_required`).
   - Keeping the agency during the grace period, and the API's 409 states (`closure_in_progress`, `closure_not_open`, `grace_period_ended`), each in words.
4. **Tests.**
   - Unit tests: the limits and their states, the PNG rules compared with the backend's checks, and the closure states.
   - A journey `22-agency-settings` that reads the plan, saves a branding profile with a PNG logo, refuses an SVG, requests a closure and keeps the agency, and checks that a member no longer sees a closing agency.
   - Accessibility scans of the tabs and the dialogs.
5. **Removed protections:** the Owner-only closure, the client viewer's absence from settings, and the PNG checks.
6. Write `evidence-018f.md`; commit; push.

### P4: Reports (018-G)

1. **Drawings (D9).**
   - Draw on the 016-C contract, as reference pages in `docs/design/preview/screens/` (the source of truth): the Reports page (retained exports and schedules), "Save as export" on a report page, the schedule form, the export page that the report email opens, and the gone states.
   - If your tools can reach the design canvas, add the drawings to its A to Z page in place of the concept E03, keeping the codes.
   - Show the drawings to the owner and wait for approval.
2. **Pages**, once approved: built on `.../report-exports` and `.../report-schedules`, with these rules from the 016-C entry review:
   - the download goes through the API as an attachment, and `410 export_gone` gives its reason;
   - the limits are 50 unexpired exports per client, 10 active schedules per client and 20 recipients per schedule;
   - pause reasons and the last run are shown;
   - a recipient can leave a schedule;
   - a client viewer sees only their own exports and those of schedules they receive.
3. **The address of the report email**, `/agencies/{a}/clients/{c}/reports/exports/{id}`, opens the export after sign-in. It is refused as not found for a reader without access.
4. **Tests.**
   - Unit tests for the export and schedule rules, compared with `backend/app/services/` and the 016-C constants.
   - A journey `23-reports` that saves an export from a report page and downloads it; revokes it and sees it gone; creates a schedule with a recipient; runs `python -m app.report_worker` once on the stack; reads the local `.eml` through `tests/browser/support/mail.ts`; and opens its address.
   - Accessibility scans.
5. **Removed protections:** the client viewer's visibility, the gone reasons, the bounds, and the email address that opens only an authorized export.
6. Write `evidence-018g.md`; commit; push.

### P5: Verification, evidence and the pull request

1. **Final update.** If `origin/main` moved, merge it again (as in P0) and report what changed.
2. **Full verification.**
   - The checks of P0 (backend and frontend).
   - The journeys of every phase in Chromium and Firefox.
   - The accessibility scans and the bundle search for secrets.
   - A relative-link check of the changed Markdown.
3. **Documentation.**
   - Bring up to date the [spec](spec.md), the [plan](plan.md) and the [tasks](tasks.md), the [frontend guide](../../frontend/README.md), [screens-a-to-z.md](screens-a-to-z.md) (the new states: built, design or concept) and the [design README](../../docs/design/README.md) if reference pages were added.
   - Update the status lines in `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md`.
4. **Pull request (D11).**
   - Push, then open one pull request from `codex/spec-018-workspace-screens` against `main`, following `.github/pull_request_template.md` if one exists.
   - Describe the decisions (the 018 decisions, the approval of this packet and the D9 approval), the scope by phase, the packages, the addresses, the permissions, the checks with counts, the limits, and what remains: D10, D8, PDF files and production.
   - Do not merge.
5. **Report.** Tell the owner in Arabic:
   - the pull request link and head commit, and the state of pull request 17;
   - what was built, screen by screen with the A to Z codes;
   - the checks actually run, with counts;
   - every limitation;
   - that the branch is ready for Claude's independent review.

## What success looks like

- The interface works against the API of `main`. A sign-in carries the agreement versions, and a change of terms is explained and recovered from.
- Every Analyze and Attribution figure names its source and state. Nothing missing, unsupported, partial or stale is shown as a number it is not, and money appears only to those allowed to see it.
- An Owner sees the plan, edits the brand and can close and keep the agency; other members see what their role allows and nothing more.
- A member saves and downloads a report for 7 days. A manager schedules one, and its email opens the export only for a reader who may see it.
- The sign-in page loads less than before, the charts load only where they are drawn, and no secret reaches the browser.
- Nothing outside the approved scope changes.
