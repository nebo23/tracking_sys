# Evidence: Attribution (018-E, phase P2)

Status: slice 018-E, Attribution, is implemented and checked as described here on 2026-11-28, under D-099 and the [plan](plan-018e.md), on `codex/spec-018-workspace-screens`. It is not accepted until the owner has reviewed it. A pull request follows at the end of the round (D11).

## 1. What was built

| Code | Screen | Address | Built on |
|---|---|---|---|
| C08 | Credit | `.../attribution` | `GET .../reports/attribution` (`view=groups`, and `view=models` for the models side by side) |
| C09 | Funnel | `.../attribution?tab=funnel` | `GET .../reports/funnel` |
| C10 | Return on ad spend | `.../attribution?tab=roas` | `GET .../reports/roas` and the names of the 014 read |

- **Model.** The client's active model versions, its default first, with "30-day window. Linear is the default for this client."; the chosen version is in the address (`model`) and in every request (`model_version`). The models view sends neither a comparison nor a model version, as the API requires.
- **Credit.** Four figures (credited revenue in all, to campaigns, direct, unknown, per currency, with the leads credited), the table by campaign, content, link or recipient (registered or not in Connect, direct and unknown named), the models side by side, and the check against the ledger with its reason.
- **Funnel.** Page views, page views through a link, leads and sales, each counted on its own basis and never divided into one another; a group whose visits cannot be measured says "Not measured".
- **Return on ad spend.** Spend, credited revenue, the return and the cost per lead for the account, then per campaign, ad set or ad with the names of the account beside the IDs; a return that is not worked out says why ("No spend, so no return", "No leads, so no cost per lead", "Spend and revenue are in different currencies"); the credit that matched no ad of the account is shown apart.
- **States.** `behind`, `rebuilding` and `failed` are banners over the published values; `not_ready` says that attribution has not been calculated, never 0; without financial access sale values say "Needs financial access" and lead credit stays.
- **Navigation.** Attribution is the last item of Analyze; on a phone the client's tab bar holds Clients, Overview, Attribution and Links, and More holds the rest (D5).
- **Up to today.** The preset "Last 30 days, up to today" (D10 of the 018 entry review, D-083) lets a range end today, with a notice that today is provisional and never compared; the defaults still end on the last complete day, and no range may end after today. Journey 21 needs it for its lead of today.
- **Errors.** `report_changed` and `currency_exponent_conflict` have sentences of their own.

## 2. Checks

| Check | Result |
|---|---|
| `npm run typecheck`, `npm run lint` | Passed; no finding. |
| `npm test` | 30 files, 564 tests passed (549 after P1). |
| `npm run build`, then `npm run build:check` | Built; the Attribution page is a chunk of 24.33 kB (4.90 kB compressed). "No secret, key, token or backend setting was found." The first page loads seven script files, 719.89 kB: the entry script grew from 490.19 kB to 506.52 kB with the messages of both languages. |
| Journeys, Chromium | 62 journeys in four groups, all passed: files 01 to 09, 22 (1.3 minutes, after journey 06 was given more Tab presses to pass the longer client menu); 10 to 12, 27 (5.6 minutes); 13 to 16, 8 (1.4 minutes); 17 to 21, 5 (55.4 s). |
| Journeys, Firefox | 62 journeys, all passed: 22 (2.0 minutes), 27 (10.5 minutes, run in the background because it passed the ten-minute limit of a foreground command), 8 (1.7 minutes) and 5 (1.3 minutes). |
| Accessibility | The 22 axe tests of journey 10 in each browser report 0 serious or critical and 0 moderate or minor findings; the Analyze tests now also open the credit, funnel and return-on-ad-spend tabs, in the four looks and at 390 pixels. |

### 2.1 The journey `21-attribution`
On the disposable stack, through the API only: a campaign `ramadan-2026` and its managed link, a website source and an ingest key; a visitor who agrees to analytics, attribution and identity, is identified by a verified email, views the page through the link and sends a trusted lead signal from the shop's server; the stand-in ad account of journey 20; one pass of the attribution worker. The journey checks that:
- the range "Last 30 days, up to today" enters the address and the notice says that today is provisional;
- the default model is Linear with its 30-day window, and credit names `ramadan-2026` as "A Connect campaign" with 1 lead; the models side by side list three models;
- another model is kept in the address and the campaign stays credited;
- the funnel counts 1 page view through the link and 1 lead for the campaign, with the basis of each step;
- the return on ad spend names "Ramadan offers" beside 1201 and shows the lead that matched no ad of the account apart.

Verified sales credited to a campaign do not arise from these facts (a sale needs a verified payment associated with the person); unit tests cover the sale values, the reconciliation and the financial gating.

### 2.2 Removed protections (V21)
Each protection was removed alone with a scratch script, the named unit test failed, and the file was restored byte for byte (SHA-256 compared):

| Protection | Failing test |
|---|---|
| Financial gating of credit (the report's flag and each row's state, removed together: either alone keeps the values hidden) | "keeps lead credit and says what needs financial access when sale values are refused" |
| The model in the request | "send the model and the comparison with the groups view, and neither with the models view"; "reads under the client default model first, and names every group and the difference with the ledger"; "keeps the model and the grouping in the address and asks for them" |
| The account and the level in the request | "ask for the return on ad spend of one account and level, under the chosen model" |
| Unmatched credit kept apart | "names each campaign from the ad account, and says why a return is not worked out" |

A unit test also reads `backend/app/reporting/credit.py`, `funnel.py`, `roas.py` and `backend/app/advertising/roas.py` and fails when a reason they set has no sentence, or when the interface names one they never send.

## 3. Limits
- The conversions list and the journey of one conversion (C11) are not built (D6, D10).
- The Arabic copy is written by a model and marked for review by a native editor (D12).
- The intermittent CRM count of journey 19 (see the [018-C evidence](evidence-018c.md)) did not occur in these runs.
