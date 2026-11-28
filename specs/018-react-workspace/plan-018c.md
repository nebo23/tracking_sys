# Plan of P1: Analyze (018-C)

Status: phase P1 of the [completion handoff](implementation-prompt-completion.md), approved with D1-D12 of the [completion entry review](entry-review-completion.md) by D-099 (2026-11-28). Done on 2026-11-28: see the [evidence](evidence-018c.md).

## 1. Packages (D3)
`npm install --save-exact recharts@3.10.1 react-is@19.3.1`, then `npm ci`. The resolution is the one of section 4.5 of the entry review: 37 new lockfile entries (the two direct packages and the 35 they bring), the top-level `react-is` moves from 17.0.2 to 19.3.1, and `pretty-format` keeps its own 17.0.2. Licences: MIT, ISC, BSD-3-Clause, and "MIT AND ISC AND BSD-3-Clause" for `victory-vendor`. No other package changes.

## 2. Loading by route (D4)
- The shell and every workspace page load through the router's `lazyRouteComponent`; the screens before sign-in stay in the first chunk.
- `scripts/check-bundle.mjs` also fails when the first chunk holds chart or workspace code. The evidence records the size of each chunk.

## 3. The report layer
- `src/api/reports.ts`: typed queries of `GET .../reports/social`, `/spend` and `/revenue` and of the 014 read `GET .../ad-spend`, keyed under the agency and the client, so leaving a client drops them; the direct CSV through the same address with `format=csv`.
- `src/features/analyze/`: the range in the address (`from` and `to`, both included; the API's `end` is the day after `to`), presets that end on the last complete UTC day (yesterday), a custom range of at most 31 days, and the comparison switch (`compare=previous`).
- `src/features/analyze/states.ts` and their components: availability (`missing`, `unsupported`, `not_synced` with their reasons), total status (`partial`, `unavailable` with reasons), provisional values, freshness (`stale`, `never_synced`), `adapter_state`, comparisons that are not comparable (with their reason) and the dependency states, each in words. A unit test reads the reason codes of `backend/app/reporting/` and fails when one has no sentence, as `linkRules.test.ts` does for links.
- Money is the API's decimal text with its currency, never recomputed; percentages are the API's text.
- Financial access: the interface does not know a member's financial flag before asking. Owners and Admins have it; for others a `403` of a financial report is shown as "needs financial access", and no amount is shown.

## 4. Charts
- `src/components/charts/`: a time-series chart (this period and, when compared, the previous one) and a bar chart, on `recharts`, with the reference classes (`c-chart-wrap`, `c-legend`, `c-tip`) and the palette tokens of `docs/design/tokens.css`.
- Each chart is a `figure` with a one-sentence summary, a table view of the same points, keyboard access (the Recharts accessibility layer) and `dir="ltr"`, so time runs left to right in Arabic too.

## 5. Pages and navigation
| Address | Screen | Content |
|---|---|---|
| `/agencies/{a}/clients/{c}` | Overview, C01 (C04 on a phone) | Four figures: views and interactions of a social account, net revenue, ad spend; the daily chart of a chosen metric; the sources with their freshness. |
| `.../content` | Content, C05 | The daily metrics of a social account (chart and table) and the content published in the range (`view=content_cohort`). |
| `.../revenue` | Revenue, C06 | Verified and declared blocks per currency, kept apart; the daily net; the unresolved items of the client. |
| `.../ad-spend` | Ad spend, C07 | Spend, impressions and clicks per level, with the names of the 014 read beside each ID; the account's currency and time zone; refused facts counted. |

- Every choice is in the address: range, comparison, account (`connection`), metric, level.
- Client navigation (section 4.3 of the entry review): Overview; Analyze: Content, Revenue, Ad spend (Attribution follows in P2); Collect; Manage (Reports follows in P4).
- Phone tab bar (D5): Clients, Overview, Links and More, which opens the rest of the client's menu; Attribution takes its place in P2.

## 6. Tests and evidence
- Unit tests for every rule above: ranges, states and reasons against the backend, comparisons, money, financial access, the name join, the client scope of every query key, the CSV request.
- Journey `20-analyze` on the disposable stack: synthetic Instagram, YouTube and Meta ads connections, a worker pass, revenue through a declaration, and each state seen at least once. Accessibility scans of the new pages in the four looks and at 390 pixels, in `10-accessibility`.
- Removed protections (V21): the financial gating, the last-complete-day rule, states named instead of 0, the name join and the client scope of the queries, each removed alone so that a unit test fails, then restored byte for byte.

## 7. Deviations from the packet
None planned. "Up to today" (D10 of the 018 entry review) is not built in this phase; ranges always end on the last complete day.
