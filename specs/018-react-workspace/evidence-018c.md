# Evidence: Analyze (018-C, phase P1)

Status: slice 018-C, Analyze, is implemented and checked as described here on 2026-11-28, under D-099 and the [plan](plan-018c.md), on `codex/spec-018-workspace-screens`. It is not accepted until the owner has reviewed it. A pull request follows at the end of the round (D11).

## 1. What was built

| Code | Screen | Address | Built on |
|---|---|---|---|
| C01, C04 | Overview, also on a phone | `/agencies/{a}/clients/{c}` | `GET .../reports/social` (daily), `/revenue`, `/spend` |
| C05 | Content | `.../content` | `GET .../reports/social` (`daily` and `content_cohort`) |
| C06 | Revenue | `.../revenue` | `GET .../reports/revenue` |
| C07 | Ad spend | `.../ad-spend` | `GET .../reports/spend` and the 014 read `GET .../ad-spend` for the names |

- **The address** holds the range (`from` and `to`, both included), the comparison (`compare`), the account (`connection`), the metric (`metric`, or the currency on Revenue) and the level (`level`). A missing, malformed, reversed, too long or unfinished range opens the default: the last 30 days.
- **Ranges** end on the last complete UTC day (yesterday): the presets last 7, 28 and 30 days and this month, or a range of at most 31 days that the page checks before asking. "Up to today" (D10 of the 018 entry review) is not built.
- **Comparison.** A report holds the rows of its own days only, so the line of the previous period is drawn from its own report, asked for the period of equal length that ends where the range starts, without a comparison of its own. The change of a total is the API's; when the API does not compare, its reason is said.
- **States in words** (`src/features/analyze/states.ts`): availability (`missing`, `unsupported`, `not_synced`) with the stored reason, partial and unavailable totals with their reason, provisional values, freshness, a switched-off provider, a connection that needs reconnecting, and every comparison reason. Nothing that is not available is drawn as zero: a missing day is a gap in the chart and a sentence in its table.
- **Money** is the API's decimal text in its currency, formatted with `Intl.NumberFormat` from the text itself. Verified payments and declarations stay in separate blocks and are never added together.
- **Financial access.** The interface cannot know a member's financial flag before asking. A `403` of a revenue or spend report is said as "Needs financial access", with no amount and no CSV.
- **Names of ad objects** come from the 014 read of the same account, days and level, joined by ID; a name the read does not know is said so, and the ID is always shown.
- **CSV** is downloaded straight from the API with `format=csv` (no page, no stored link) and handed to the browser as a file named after the page, the level and the days.
- **Charts** (`src/components/charts/SeriesChart.tsx`, on `recharts`): a line or bars for this period and a thinner line for the previous one, the legend with each period's total, a table view of the same points, a one-sentence summary as the figure's caption, the chart's `title` and `desc`, keyboard access through the Recharts accessibility layer, and `dir="ltr"`, so time runs left to right in Arabic too.
- **Navigation** (section 4.3): Overview; Analyze with Content, Revenue and Ad spend; Collect; Manage. Attribution (P2) and Reports (P4) are absent, not disabled. On a phone the client's tab bar holds Clients, Overview and Links, and More opens the rest of its menu (D5). A new client still opens on its connections page, its first step.

## 2. Packages (D3)

| Check | Result |
|---|---|
| Installed | `npm install --save-exact recharts@3.10.1 react-is@19.3.1`, then `npm ci` from the committed lockfile: 441 packages. |
| Resolution | 37 new lockfile entries: `recharts` and the 35 packages of section 4.5 of the entry review, and `pretty-format`'s own `react-is` 17.0.2; the top-level `react-is` moved from 17.0.2 to 19.3.1. No other entry changed or left. |
| Licences | MIT (`recharts`, `react-is`, the Redux family, `immer`, the type packages and the six small packages), ISC (`d3-*`, `internmap`), BSD-3-Clause (`d3-ease`), "MIT AND ISC AND BSD-3-Clause" (`victory-vendor`); all inside the list of the 018-A plan. |
| Size on disk | 35.5 MB for the new packages; `node_modules` holds 329.6 MB. |
| `npm audit` | No critical or high finding; seven of moderate severity, all the `minimatch` advisory of the lint tooling that D-085 left open. |

## 3. Loading by route (D4)

- The shell and every page after sign-in load through `lazyRouteComponent`. The tab constants of Links and Integrations moved to `tabs.ts` files, so the router reads them without loading the pages; the address rules of Analyze are in `search.ts` for the same reason.
- `scripts/check-bundle.mjs` now also reads `index.html` and fails when a script the first page loads holds the chart package, the workspace shell or an Analyze page.
- **Sizes** (minified, compressed in brackets): the entry script 490.19 kB (138.70 kB); the chart chunk 387.60 kB (110.16 kB), loaded only with the Overview, Content and Revenue pages; Overview 7.98 kB, Content 8.98 kB, Revenue 4.93 kB, Ad spend 7.28 kB, the shared Analyze code 12.45 kB, the shell 13.01 kB; 50 script files in all; one stylesheet of 152.67 kB.
- **The first page** loads six script files, 702.03 kB in all, against the single script of 1,052.32 kB before this phase.

## 4. Checks

| Check | Result |
|---|---|
| `npm run api:check` | The types match the contract. |
| `npm run typecheck`, `npm run lint` | Passed; no finding. |
| `npm test` | 28 files, 549 tests passed (528 before this phase). |
| `npm run build`, then `npm run build:check` | Built. "No secret, key, token or backend setting was found." The first page loads none of the marked code. |
| Journeys, Chromium | 61 journeys in four groups, all passed: files 01 to 09, 22 (1.3 minutes); 10 to 12, 27 (5.6 minutes); 13 to 16, 8 (1.4 minutes, after journey 13 was updated for the overview, section 5); 17 to 20, 4 (49.4 s). |
| Journeys, Firefox | 61 journeys, all passed: 22 (1.7 minutes), 27 (8.5 minutes), 8 (1.6 minutes) and 4 (48.2 s). The first run of files 17 to 20 failed once in journey 19, as in P0: its CRM figure "Won, payment not matched" showed 0 instead of 1 after a reload. The group then passed. |
| Accessibility | The 22 axe tests of journey 10 in each browser report 0 serious or critical and 0 moderate or minor findings, including the four Analyze pages in the four looks, a chart as a table, the range choice open, a custom range with a problem, and the Analyze pages and the More menu at 390 pixels with nothing past the edge. |

### 4.1 The journey `20-analyze`
On the disposable stack, a client gets a stand-in Instagram account, a stand-in Meta ad account with a campaign, an ad set and an ad that spends 125.50 EGP a day, one worker pass and a declared sale of 1,500.00 EGP. The pages are opened on the days that hold these facts (20 October to 9 November 2026), so the journey sees the same states on any later date. It checks that:
- the views figure is a number marked partial, with "Some days have no value.", its account and "Days in UTC"; net revenue says "No verified revenue"; ad spend shows EGP; the sources are fresh;
- the comparison enters the address and partial periods are "Not compared";
- the content table says "Not synced: outside the synced days" for those days, reach is "Not available" because "This metric cannot be added up over days.", a reel's follows are "Not supported: not reported for this kind of content", and the content list "may be incomplete";
- the declared sale stays out of the verified block;
- ad spend names "Ramadan offers" beside 1201 and, at the ad level kept in the address, "Reel: new menu" beside 1203, with the account's time zone; its CSV downloads under its own name and holds the ad;
- a custom range of more than 31 days is refused before it is asked for.

Stale and provisional values, an unavailable provider and a connection to reconnect do not arise from these facts; unit tests cover them.

### 4.2 Removed protections (V21)
Each protection was removed alone with `p1_mutations.py` (a scratch script, not kept), the named unit test failed, and the file was restored byte for byte (SHA-256 compared):

| Protection | Failing test |
|---|---|
| Financial gating (`financeRefused`) | "says that financial access is needed, with no amount and no download"; "says what needs financial access and shows no amount without it" |
| The last complete day (`lastCompleteDay`) | "end on the last complete day, yesterday in UTC, whichever preset is chosen"; "come from the address only when they are real, in order, at most 31 days and ended" |
| Missing days named, not drawn as 0 (`dailySeries`) | "names each day without a value in the table, never drawing it as zero" |
| Unavailable totals named, not shown as 0 (Overview) | "names a total that is partial or unavailable instead of showing it as a number, with its source" |
| The name join (`namedRows`) | "join the names to the report rows by ID and keep every ID"; "names each object from the ad account beside its ID, and keeps the level in the address" |
| The client scope of the report queries (`reportKey`) | "are kept under the agency and the client, so leaving the client drops them all" |

A unit test also reads `backend/app/reporting/` for every reason the API sets and fails when one has no sentence, or when the interface names one the API never sends; another compares the metric names with the catalog of `catalog.py`.

## 5. Changes to earlier slices
- The first page of a client is its overview: the unit tests of the workspace and journey 13 now expect it, and opening a client from the switcher or the list lands there.
- Wide Analyze tables scroll inside a box that takes the keyboard focus and is named (`TableScroll`), as axe requires at 390 pixels.

## 6. Limits and observations
- **Journey 19.** Its CRM figure failed once in P0 (Chromium) and once here (Firefox), and passed on every rerun. The count is computed synchronously from the stored deals and the active rules (`deals_view`), and the request's transaction commits before the response (`get_session` with function scope). The signed webhook answers 200 even for a delivery it ignores or finds invalid, so a delivery the API did not store would look the same; the cause was not found. It predates this phase and is left for its own investigation.
- The workstation had little memory available during the runs (under 1 GB at times), which slows the stack; no run was cut short.
- The Arabic copy is written by a model and marked for review by a native editor (D12).
- Not built in this phase: "Up to today", the agency's brand on client viewers' screens (D8), Attribution (P2) and Reports (P4).
