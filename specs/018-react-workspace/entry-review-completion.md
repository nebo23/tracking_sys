# Spec 018 completion entry review: the remaining screens on the finished backend

Prepared: 2026-11-27, at the owner's request to prepare the specification and the implementation prompt of Spec 018 so that its work can start.
- **Baseline:** merged `main` at `e3b3005` (PR 20, Spec 016-C); the coordination branch `claude/keen-fermat-otlr9d` at `2a0deb1` (D-096); `codex/spec-018-react-workspace` (pull request 17, slice 018-A) at `1c4ee9e`; `codex/spec-018-workspace-screens` (slices 018-B and 018-D) at `1ffa841`.
- **Status:** approved by the owner on 2026-11-28 as recommended, without amendment (D-099). It was prepared as a proposal on 2026-11-27. D-097 was then the highest number in use, on the coordination branch, which reserves D-098 for the approval of Spec 017-B.
- **Handoff:** the [implementation handoff](implementation-prompt-completion.md) executes this packet after approval.
- **Screens:** every screen named here has a code (A01 to G06) on the "A to Z" page of the design canvas; [screens-a-to-z.md](screens-a-to-z.md) lists them.

## 1. Intended result

D-091 finished the backend before the frontend: 016-B (attribution reports), 017-A (plans, limits, agency closure and the agreement record) and 016-C (retained exports, scheduled reports and branding) are merged on `main`. D-091 also says that pull request 17 is brought up to date once, when the frontend work starts. This packet starts that work and completes Spec 018:

- **Up to date with `main`.** Both 018 branches take `main`, the 018 decisions D-093 and D-094 of the branch take free numbers as D-096 requires, and the built screens adopt what 017-A changed: the agreement versions at every sign-in (D-093 on `main`), operator rows in the audit log and closing agencies.
- **Analyze (018-C).** Overview, Content, Revenue and Ad spend on the 016-A reports, with charts.
- **Attribution (018-E).** Credit, funnel and return on ad spend on the 016-B reports.
- **Agency settings (018-F).** Plan and usage, the branding profile, and closing the agency, on 017-A and 016-C.
- **Reports (018-G).** Retained exports and scheduled reports on 016-C, drawn and approved before they are built.

After this round every screen of the A to Z page that has an API is built. The concepts without an API or a decision (section 3, D10) stay outside, and acceptance criteria 1 to 5 of the [spec](spec.md) can be checked for the whole interface.

## 2. Baseline

| Area | Available | Consequence |
|---|---|---|
| Branches | `main` is 34 commits ahead of both 018 branches. Pull request 17 holds 018-A (17 commits ahead of `main`); `codex/spec-018-workspace-screens` adds 018-B, 018-D and the A to Z designs on top of it (30 commits ahead). | A trial merge (`git merge-tree`) of `main` into each branch conflicts only in `AGENTS.md`, `README.md`, `docs/planning/decisions.md` and `specs/README.md`. The backend changes of D-094 (members and archived clients) and `contracts/openapi.json` merge without conflict, but the snapshot must be generated again. |
| Decision numbers | The branch recorded D-093 (the remaining interface) and D-094 (amendment B1-B3); `main` recorded its own D-093 (the 017-A merge), D-094 and D-095 (016-C), and the coordination branch D-096. | D-096 requires this branch to renumber its D-093 and D-094 to the next free numbers when it is brought up to date. |
| API added on `main` | `GET /auth/agreements`; `GET /agencies/{a}/plan`; `POST`, `GET` and `DELETE /agencies/{a}/closure`; `GET` and `PUT /agencies/{a}/branding`, and `GET`, `PUT` and `DELETE` of its logo; the attribution, funnel and ROAS reports; `GET .../attribution/conversions`; retained exports (`.../report-exports`, with `download`) and schedules (`.../report-schedules`, with `recipients/me`). | Every screen of this round has its API. No API change is planned. |
| API changed on `main` | `Login`, `Registration` and `GET /auth/google/start` take the agreement versions; a missing or outdated version answers `422 agreement_required`. `AgencyAccess` gains `status` (`active` or `closing`); `AuditResponse` gains `actor_kind`; creation routes may answer `409 plan_limit_reached`. | After the merge, the built sign-in is refused until it sends the versions. The interface already has sentences for `plan_limit_reached` and `rate_limited` with `Retry-After`; operator rows and closing agencies are new. |
| Reports | 016-A: social, spend and revenue. 016-B: attribution (groups or models, by campaign, content, link or recipient), funnel and ROAS (per ad account and level), each with freshness, finance and dependency states. All return object IDs, not names, for ads. | The 014 read `GET .../ad-spend` returns the names of campaigns, ad sets and ads; the screens join them in the browser. |
| Built interface | 018-A, 018-B and 018-D: 54 journeys pass in Chromium and Firefox, axe scans of 264 states, 517 unit tests ([018-D evidence](evidence-018d.md)). One script of 1,044 kB. | New pages must not grow the first load further; see D4. |
| Designs | C01 to C06 were drawn on 2026-11-25 with an earlier shell (search field, notifications, Settings and Help). C07 to C10 and B13 to B15 were drawn on 2026-11-27 on the 016-B and 017-A contracts and wait for the owner's review. E03 (Reports) is a concept drawn before 016-C existed. | The built shell wins over the older drawings. E03 is replaced by new drawings on the 016-C contract (D9). |
| Charts | D-083 approves Recharts as the chart family, not a version; D-093 keeps the package and its version a separate decision. The 018-A rule takes the newest release at least 14 days old. On 2026-11-27 that is `recharts` 3.10.1 (2026-07-25); 3.11.0 (2026-11-17), 3.11.1 and 3.11.2 (2026-11-27) are newer than 14 days. | A trial resolution in a scratch copy of the manifest (nothing installed) adds `recharts` 3.10.1 and its peer `react-is` 19.3.1 (the release of the approved `react`, replacing an older `react-is` that a test tool brought), and with them 35 further packages: all MIT, ISC or BSD-3-Clause, inside the licence list of the [018-A plan](plan-018a.md). |
| Workstation | The disposable stack of `frontend/tests/browser/support/stack.ts`; Playwright 1.64.1 browsers in a non-default folder; drive C: had 8.7 GB free on 2026-11-27 after reaching 4.4 GB earlier that day. | The handoff names the browser folder and asks for a free-space check before every journey run. |

## 3. Decisions for the owner

The recommendations are for synthetic data and disposable environments. They change no API, contract or schema.

| ID | Recommended choice | Alternative and its effect |
|---|---|---|
| D1 Scope and order | One round on `codex/spec-018-workspace-screens`, in phases: P0 up to date with `main` (pull request 17 first, then the stacked branch); P1 Analyze (018-C); P2 Attribution (018-E); P3 Agency settings (018-F); P4 Reports (018-G); P5 verification, evidence and the pull request. Each phase ends verified and pushed (D-051) with its own evidence file. | One packet, handoff and pull request per slice: smaller reviews, but four more rounds of approval and of bringing branches up to date. |
| D2 Up to date with `main` (P0) | Merge, never rebase: `main` into `codex/spec-018-react-workspace`, then that branch into `codex/spec-018-workspace-screens`. Resolve only the record files, keeping every decision of both sides in numeric order. Renumber the branch's D-093 and D-094 to the next free numbers and every reference to them. Generate the contract types again. Adopt 017-A in the built screens: the agreement versions at sign-in, registration and Google sign-in, with the refused state A03; operator rows in the audit log; closing agencies for their owners. Run the backend suites as well, because backend code is merged. Push pull request 17's branch (its one update under D-091), then the stacked branch. | Start a fresh branch from `main` and carry the 018 commits over: a cleaner history, but the reviewed commits and the discussion of pull request 17 are lost. |
| D3 Chart package | Approve `recharts` 3.10.1 and `react-is` 19.3.1 at exact versions, with the 35 packages they bring fixed by the lockfile ([section 4.5](#45-packages-of-d3)). Charts use the reference chart styles and palette tokens, appear only on Analyze and Attribution pages, and each has a table view and a one-sentence summary; time axes run left to right in Arabic too (D-083). | (a) Charts drawn by our own SVG components with the reference classes: no package, but scales, ticks, tooltips, keyboard focus and resizing are ours to write and test, a larger and riskier slice. (b) `recharts` 3.11.2, the newest: published on 2026-11-27, against the 14-day rule. |
| D4 Loading by route | Split the application by route with the router's own lazy loading (no new package): the sign-in pages load no workspace page, and only the Analyze and Attribution pages load the charts. The evidence records the size of every chunk, and the sign-in page loads less than today's single script. | Keep one script: simpler, but every visitor would download the charts and every page, more than 1 MB. |
| D5 Analyze (018-C) | Build C01 to C07 on 016-A, in the shell of the built application (Overview without a group; Analyze: Content, Revenue, Ad spend, Attribution; Manage gains Reports). Date ranges end on the last complete day, with an optional comparison and the direct CSV. Revenue and spend figures appear only with financial access; otherwise a sentence says why. Ad spend shows the names from the 014 read beside each ID. On a phone the tab bar keeps five places: Clients, Overview, Attribution, Links and More, which opens the rest of the client's menu. | Build Analyze with figures and tables first and charts later: no package now, but the overview and the daily views lose their main picture. |
| D6 Attribution (018-E) | Build C08 to C10 on 016-B as one page with three tabs: Credit (model picker with the client's default first, group by campaign, content or link, the three models side by side, the check against the ledger), Funnel (each step on its own basis; unmeasured visits named, not 0) and Return on ad spend (per ad account and level, credit not matched to the account, spend states and their reasons). Freshness `behind`, `rebuilding` or `failed` shows a banner; values without financial access say why. The conversions list and the journey of one conversion (C11) are not built in this round. | Add a fourth tab, Conversions, now: useful for support, but it shows pseudonymous person identifiers and needs its own drawing and privacy review. |
| D7 Agency settings (018-F) | A new agency destination, Agency settings, with three tabs: Plan and usage (Owners, Admins and Analysts; each limit and its state, the month's tracked events), Branding (read by every member; edited by Owners and Admins: display name, accent color, a PNG logo of at most 256 KiB and 1024 by 1024 pixels; SVG refused) and Close the agency (Owners: the agency's exact name and the password, or a fresh Google sign-in when the API answers `reauthentication_required`; keeping the agency during the 30 days). An Owner of a closing agency sees the closing page B15; other members no longer see the agency. Client viewers do not see Agency settings. | Put branding under Reports, closer to its use in emails: but the profile belongs to the agency, not to one client. |
| D8 Use of the branding profile | In this round the profile is edited and previewed only; the API already uses its display name in report emails. Showing it on the screens of client viewers waits for its own drawing and the owner's brief (D-039, 016-C D11), because it replaces the Connect brand on screen and an accent color must pass the contrast rules first. | Show the agency's display name and logo in the client viewer's sidebar now, without the accent color: white-label value at once, and one more drawing to approve before P3. |
| D9 Reports (018-G): drawn first | Before any code of P4, draw on the canvas, replacing the concept E03: the Reports page (retained exports with their state, expiry, size and downloads; schedules with cadence, next run, last run and pause reason), the "Save as export" action of every report page, the schedule form (name, report and parameters, daily, weekly or monthly, weekday, hour and time zone, comparison, sale values, up to 20 agency members as recipients), the page the report email opens (`/agencies/{a}/clients/{c}/reports/exports/{id}`) and the gone states (revoked with its reason, expired). Show them to the owner and wait for approval (D-039); then build them on the 016-C API. No PDF or printable page (D-095). | Build Reports from this description without drawings: faster, but a customer-facing screen would be built without the owner seeing it first, against D-039. |
| D10 Outside this round | The concepts B12 (Privacy and data: no API), F05 (Search: no decision) and C11 (the journey of one conversion) stay concepts. Each needs its own decision. | Add Search now: it needs no API (it searches what the person can already open), but it is a new feature to design, test and review. |
| D11 Pull requests | Push verified commits after each phase (D-051). P0 updates pull request 17. After P5, open one pull request from `codex/spec-018-workspace-screens` against `main` for 018-B to 018-G: the approval lifts the D-093 gate of the branch for this pull request. If pull request 17 is still open then, the new pull request also carries 018-A and the owner decides which one merges first. Merging stays the owner's decision after Claude's independent review. | One pull request per phase, stacked on pull request 17's branch: smaller reviews, but each needs a new base after every merge. |
| D12 Verification and boundaries | The bar of 018-A, 018-B and 018-D for every phase ([section 5](#5-verification-matrix)), and the backend suites in P0. No API, contract or schema change: a needed change goes back to the owner first. Disposable stack only: no native `tracking_sys`, no live provider, no external email (report emails stay local `.eml` files), no deployment. Synthetic data only. The Arabic copy is written by a model and marked for review by a native editor. | Run journeys in Chromium only, to save time: Firefox found real differences in 018-D, so both stay. |

## 4. Design for implementation after approval

### 4.1 Branch flow

1. `git merge origin/main` on `codex/spec-018-react-workspace`; resolve the four record files; renumber; regenerate `contracts`-based types (`npm run api:types`, `npm run api:check`); adopt the agreement versions (4.2) in the 018-A screens; run the checks of P0; push. This updates pull request 17.
2. `git merge codex/spec-018-react-workspace` on `codex/spec-018-workspace-screens`; adopt the rest of 4.2 in the 018-B screens; run every check again; push.
3. Phases P1 to P5 continue on `codex/spec-018-workspace-screens`. If `main` moves again, merge it before P5 and report what changed.

### 4.2 What 017-A changes in the built screens

| Change on `main` | Screen | Behavior |
|---|---|---|
| Agreement versions | A01, A05, Google sign-in | The page reads `GET /auth/agreements` and sends `{"terms", "privacy"}` with the login and the registration, and `?terms=&privacy=` with the Google start. The agreement box stays as approved (D-082). |
| `422 agreement_required` | A03 | The versions changed while the page was open: read them again, untick the box, keep the email, and say so above the form (the canvas shows the wording). Google sign-in returns with `error=agreement_required` and shows the same message. |
| `actor_kind` | B11 | A row whose actor is the Connect operator says so ("The Connect operator"), and a plan row without an agency member is shown, not dropped. |
| `AgencyAccess.status` | The switcher, B01, B15 | A closing agency is listed only to its Owners, marked as closing, and opens the closing page B15 instead of its clients. |
| `409 plan_limit_reached` | B03, B07, E02, D02 | The existing sentence names the limit, its value and its use, and links Owners and Admins to Plan and usage once it exists (P3). |

### 4.3 Navigation after this round

- **Agency:** Clients; Agency: Team and access, API keys, Audit log, Agency settings; at the end, Account.
- **Client:** Overview; Analyze: Content, Revenue, Ad spend, Attribution; Collect: Links, Website tracking, Integrations; Manage: Connections, Reports; at the end, Account.
- **Phone:** the client tab bar holds Clients, Overview, Attribution, Links and More (D5); the agency tab bar stays as built.

### 4.4 New addresses

| Address | Screen |
|---|---|
| `/agencies/{a}/clients/{c}` | Overview (C01), today a placeholder |
| `.../content`, `.../revenue`, `.../ad-spend` | C05, C06, C07 |
| `.../attribution?tab=credit`, `funnel` or `roas` | C08, C09, C10 |
| `.../reports?tab=exports` or `schedules`, and `.../reports/exports/{id}` | P4 drawings; the second address is the link of the report email (`backend/app/services/mail.py`, `report_ready_message`) |
| `/agencies/{a}/settings?tab=plan`, `branding` or `closure` | B13, B14 |
| `/agencies/{a}/closing` | B15 |

Every address keeps its state in the address (range, comparison, model, group, level, account), as the Links tabs do, so a link shared inside the agency opens the same view when the reader may see it.

### 4.5 Packages of D3

The trial resolution of 2026-11-27 (a scratch copy of `frontend/package.json` and its lockfile, `npm install --package-lock-only --ignore-scripts`, nothing installed) adds these packages: the two direct ones and 35 that they bring. The implementing model installs from the same manifest and records the result of `npm audit`, the licences of the full tree and the size on disk, as the 018-A evidence did. A different resolution, a high-severity finding or a licence outside the list goes back to the owner.

| Package | Version | Licence |
|---|---|---|
| `recharts` (direct) | 3.10.1 | MIT |
| `react-is` (direct, peer of `recharts`, the release of `react`) | 19.3.1 | MIT |
| `@reduxjs/toolkit`, `redux`, `redux-thunk`, `react-redux`, `reselect`, `immer` | 2.15.0, 5.0.1, 3.1.0, 9.3.1, 5.2.0, 11.2.13 | MIT |
| `victory-vendor` | 37.4.1 | MIT AND ISC AND BSD-3-Clause |
| `d3-array`, `d3-color`, `d3-format`, `d3-interpolate`, `d3-path`, `d3-scale`, `d3-shape`, `d3-time`, `d3-time-format`, `d3-timer`, `internmap` | 3.2.5, 3.1.1, 3.1.3, 3.0.2, 3.1.1, 4.0.3, 3.2.1, 3.1.1, 4.1.1, 3.0.2, 2.0.3 | ISC |
| `d3-ease` | 3.0.2 | BSD-3-Clause |
| The type packages `@types/d3-*` (nine) and `@types/use-sync-external-store` | as resolved | MIT |
| `es-toolkit`, `eventemitter3`, `decimal.js-light`, `tiny-invariant`, `@standard-schema/spec`, `@standard-schema/utils` | 1.53.2, 5.0.4, 2.5.1, 1.3.3, 1.1.0, 0.3.0 | MIT |

`pretty-format`, a test tool, keeps its own `react-is` 17.0.2 when the top-level `react-is` becomes 19.3.1.

### 4.6 Permissions by screen

| Screen | Owner | Admin | Analyst | Client viewer |
|---|---|---|---|---|
| Overview, Content | Yes | Yes | Granted clients | Their client |
| Revenue, Ad spend, ROAS, sale values | Yes | Yes | With financial access | With financial access |
| Attribution credit and funnel without sale values | Yes | Yes | Granted clients | Their client |
| Plan and usage | Read | Read | Read | No |
| Branding | Edit | Edit | Read | Read through the API; no settings page |
| Close or keep the agency | Yes | No | No | No |
| Retained exports | All of the client | All of the client | All they can read | Their own and their schedules' |
| Schedules | Create and manage | Create and manage | Leave one they receive | Leave one they receive |

The API decides every case; the interface hides what a role cannot do and shows the API's refusal when it happens anyway.

## 5. Verification matrix

| Case | Required observable evidence |
|---|---|
| V01 Agreement | Sign-in, registration and Google sign-in send the current versions and pass against the API of `main`; a changed version shows A03, and the next attempt with the box ticked succeeds. |
| V02 Records | No decision number is used twice across `main`, the coordination branch and this branch; the renumbered references resolve. |
| V03 Built screens after the merge | The 54 existing journeys and the existing unit tests pass on the updated branches, with the audit log's operator rows and closing agencies covered by new tests. |
| V04 Backend after the merge | The backend unit and integration suites pass on disposable PostgreSQL, and the OpenAPI snapshot matches. |
| V05 Overview | The four figures name their source, freshness and state; stale, partial and provisional values are marked; the comparison is offered only where the API says it is comparable. |
| V06 Content | Daily values with provisional days, the published-content list, and unsupported and missing values named, not shown as 0. |
| V07 Revenue | Verified, declared and unresolved amounts stay apart; without financial access the page says so and requests no amount. |
| V08 Ad spend | The range ends on the last complete day; names from the 014 read sit beside the IDs; the account's currency and time zone are shown; refused rows are counted. |
| V09 Charts | Each chart has a table view and a summary, is reachable by keyboard, and keeps time left to right in Arabic. |
| V10 Credit | Model, group and comparison change the request and the address; the models view and the ledger check show; `behind`, `rebuilding` and `failed` show their banners. |
| V11 Funnel | Each step shows its basis; unmeasured visits are named. |
| V12 Return on ad spend | The account and level change the request; credit not matched to the account and every missing return show their reason. |
| V13 Plan and usage | Each limit and its state, the month's events; a client viewer is refused. |
| V14 Branding | Owners and Admins save the name and color and upload a PNG; a large, oversized or SVG file is refused with its reason; Analysts read only. |
| V15 Closure | A wrong name or password is refused; a Google account is sent to sign in again; an Owner keeps the agency within 30 days; other members no longer see a closing agency. |
| V16 Exports | Every report page saves an export; the list shows state, expiry and downloads; a download carries the attachment; revoked and expired exports show their reason; a client viewer sees only theirs. |
| V17 Schedules | Create, change, pause, resume and delete; at most 20 recipients and 10 active schedules, refused with their reason; a recipient leaves; the email's address opens the export. |
| V18 Isolation | Switching the client or the agency drops the previous data; a deep link to another client or agency is refused by the API and shown as not found. |
| V19 Accessibility | axe-core finds nothing on the new pages and dialogs in the four looks and at 390 pixels; nothing spills past the edge. |
| V20 Bundle | No secret, key, token or backend setting in the bundle; the size of each chunk is recorded; the sign-in page loads no chart code. |
| V21 Removed protections | Each new protection, removed alone, makes a unit test fail. |
| V22 Journeys | New journeys for Analyze, Attribution, Agency settings and Reports pass in Chromium and Firefox on the disposable stack. |

## 6. What stays outside this round

- The concepts B12, C11 and F05 (D10), and the screens of client viewers with the agency's brand (D8).
- PDF files and printable pages (D-095), production email, hosting, scheduling and keys (020, Q-008), live providers, the native `tracking_sys` migration and deployment.
- Specs 017-B and 017-C (payments, prices, trials), 012 and 013 (D-063).
