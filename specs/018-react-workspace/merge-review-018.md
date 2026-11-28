# Spec 018 merge review (PR 23)

Reviewed on 2026-11-28 at head `7554857` of `codex/spec-018-workspace-screens`, against `main` at `7c7b5b5`, for the owner's decision on the merge of [pull request 23](https://github.com/nebo23/tracking_sys/pull/23) after the completion round (D-106). The pull request also holds pull request 17 (slice 018-A, head `edc2d54`), so its merge merges 018-A as well.

While the review ran, the branch moved to `e141077`. That commit changes only `evidence-018-completion.md` and `screens-a-to-z.md`, where it records four display defects found when the design canvas was captured. `git diff 7554857 e141077 -- frontend backend contracts` is empty, so everything below holds at both heads.

**Result.** No defect was found in tenant isolation, in the session and secret rules, in the bundle or in the refusal of deep links. The review found six defects (R018-01 to R018-06), two of them P2:
- the overview states a report it could not read as "no revenue" or "no spend";
- a schedule whose recipient lost their membership can no longer be changed in the interface.

It also confirms the four display defects that `e141077` records (K1 to K4) and lists eight observations. Nothing was corrected: the corrections and the merge wait for the owner's decision.

## 1. Scope

The review read the frontend against:
- the decisions D-081 to D-087, D-100, D-101 and D-105 to D-107;
- D1-D12 of the [completion entry review](entry-review-completion.md), with its sections 4 and 5, and its [handoff](implementation-prompt-completion.md);
- the [frontend guide](../../frontend/README.md);
- the API of `main`: `contracts/openapi.json` and the services under `backend/app/`.

What was read, and how closely:
- **Read in full.** The completion round: Analyze, Attribution, Agency settings with the closing page, and Reports. Also the shell and its navigation, the router, the API layer (`client.ts`, `session.ts`, `errors.ts` and the query keys of every module), `linkToken.ts`, `safeNext.ts`, the bundle check, and the unit tests of these parts.
- **Read for the cross-cutting rules only.** Slices 018-A (the entry screens), 018-B and 018-D (clients, team, keys, audit log, connections, links, tracking, integrations): their cache keys, session handling and role gating, not line by line.
- **Compared with the backend:**
  - `services/report_exports.py`, `services/report_schedules.py`, `api/report_delivery.py` and `reporting/schedules.py`;
  - in `services/reporting.py`, the permissions, the finance split and the bounds; `reporting/credit.py`;
  - `api/plans.py`, `api/branding.py`, `services/branding.py` and `services/mail.py`;
  - the error answers of `main.py`, and the closure rules of the [017-A design](../017-saas-lifecycle/design-017a.md);
  - what 017-B and 017-C added on `main`.
- **The backend diff against `main`** is the D-101 amendment only: B1 (member details) and B2 (archived clients), in `api/schemas.py`, `api/tenancy.py` and `services/tenancy.py`, with their integration test and the contract.
- **Not reviewed:** the Arabic copy (D12 leaves it to a native editor) and the design canvas.

## 2. Verification run by the reviewer

| Check | Result |
|---|---|
| `npm run typecheck`, `npm run lint`, `npm run api:check` | Passed; no finding; "The contract types match contracts/openapi.json." |
| `npm test` | 33 files, 607 tests passed (37 s). |
| `npm run build`, then `npm run build:check` | Built. "No secret, key, token or backend setting was found." The first page loads seven script files, 774.11 kB. The entry script `index-CKDQalLk.js` has the hash that the completion evidence records. |
| Journeys `22-agency-settings` and `23-reports`, Chromium | 2 passed (59.8 s) on the disposable stack `tracking-e2e-frontend`, which the run removed. Firefox and the other 62 journeys were not run again; the completion evidence records them. |
| Scratch unit tests | Nine cases in a temporary file under `frontend/tests/unit/features/`, removed after the run. They draw the screens with the unit tests' stand-in API, and reproduced R018-01 to R018-06, K3 and O5 at `7554857` (sections 3 to 5). |
| Scratch integration test | One case, removed after the run, on this review's own disposable PostgreSQL: Compose project `tracking-018-review-test` on 127.0.0.1:55433, synthetic settings, removed with `down --volumes`. It confirmed the API behavior behind R018-05 and O4. |

The owner's database `tracking_sys` and the Compose projects of other sessions were not touched. Apart from this file, the working tree is as the branch left it.

## 3. Defects

### R018-01 (P2): the overview states a report it could not read as "no revenue" or "no spend"

**Where.** `RevenueStat` and `SpendStat` in [OverviewPage.tsx](../../frontend/src/features/analyze/OverviewPage.tsx), lines 180-182 and 218-221.
- A `403` becomes "Needs financial access".
- Any other error falls through to the branch of an empty report, so the figure reads "No verified revenue" or "No spend is recorded for this range."
- Both queries are made with `retry: false` (lines 58-59), so one network failure or one `5xx` does the same.

**Why it matters.** The data-state rule (D-083, D9) and V05 of the completion matrix: nothing missing or unavailable is shown as a value it is not. The overview is the first page of every client.

**When it happens.**
- Always, for any client with more than 200 revenue evidence records. The revenue report then answers `409 report_requires_ledger_upgrade` (`revenue_digest` in `backend/app/services/reporting.py`, lines 545-552), as the bounds table of [the reporting guide](../../docs/engineering/reporting.md) states.
- For a spend read over 10,000 source rows (`422 report_too_large`).
- For any request that does not reach the API.

The Revenue and Ad spend pages are not affected: they show the error through `QueryStates` (see O3 for its wording).

**Reproduction at `7554857`.**
- `GET .../reports/revenue` answering `409 report_requires_ledger_upgrade`: the Net revenue figure read "No verified revenue".
- `GET .../reports/spend` answering `422 report_too_large`: the Ad spend figure read "No spend is recorded for this range."

**Regression that would fail.** In `tests/unit/features/analyze.test.tsx`: the revenue report of a client answers `409 report_requires_ledger_upgrade` and its spend report answers `422 report_too_large`. The overview must name both figures as not available, with a reason, and contain neither "No verified revenue" nor "No spend is recorded for this range."

**Correction (frontend only).** Tell an error from an empty report in both figures, as `SocialStat` already does for social figures: "Not available", with the sentence of the error.

### R018-02 (P3): the overview's spend figure is not marked provisional

**Where.** `SpendStat` in [OverviewPage.tsx](../../frontend/src/features/analyze/OverviewPage.tsx), lines 212-239. It shows the freshness badge and the status of the first total, but never `SpendReportTotal.provisional`. The Ad spend page (`AdSpendPage.tsx`, lines 174 and 246) and the ROAS tab mark the same value.

**Why it matters.** V05: "stale, partial and provisional values are marked". A spend fact stays provisional until its `provisional_until` (`backend/app/reporting/spend.py`, lines 118-139), so the last days of the default range usually are.

**Reproduction at `7554857`.** A spend total with `provisional: true` showed "EGP 42,300.00" without the "Provisional" badge.

**Regression that would fail.** The overview of a client whose spend total is provisional shows "Provisional" in the Ad spend figure.

### R018-03 (P3): without financial access, the models side by side show unlabeled lead counts

**Where.** `ModelsCard` in [CreditTab.tsx](../../frontend/src/features/attribution/CreditTab.tsx), lines 208-219. With financial access each cell holds credited revenue. Without it, the same cell silently holds credited leads, and the columns (Campaigns, Direct, Unknown) do not say so.

**Why it matters.** D6 of the completion entry review: "values without financial access say why". The [018-E evidence](evidence-018e.md) also says that sale values then read "Needs financial access". A reader can thus see "40.5" where another reader of the same page sees "EGP 1,200.00".

**Reproduction at `7554857`.** For an Analyst whose models view answered `finance: permission_unavailable`, the card read "Linear Default 40.5 3 18", with neither "Needs financial access" nor any mention of leads.

**Regression that would fail.** In `tests/unit/features/attribution.test.tsx`: without financial access the models card says "Needs financial access" for each model's revenue, or labels the values it shows as leads, and shows no bare number in a revenue column.

### R018-04 (P3): the closing page (B15) sits in the full shell, with five destinations that do not open and a name that never loads

**Where.**
- `Shell` ([Shell.tsx](../../frontend/src/app/shell/Shell.tsx), lines 65-100) and `agencyGroups` ([navigation.ts](../../frontend/src/app/shell/navigation.ts), lines 63-101) do not read `AgencyAccess.status`.
- For the Owner of a closing agency, the sidebar and the phone tab bar therefore keep Clients, Team and access, API keys, Audit log and Agency settings. Each of them leads back to `/closing`, because the agency route redirects every other page there (`router.tsx`, lines 236-239).
- The shell and the switcher also ask for `GET /agencies/{a}` and `GET /agencies/{a}/clients`, which the API refuses for a closing agency (017-A design, section 5.2). The agency's name in the top bar therefore stays a loading placeholder.

**Why it matters.** The approved drawing B15 (`docs/design/preview/screens/agency-closing.html`) has a top bar and the page only, without a sidebar. The frontend guide also requires that "A destination appears when it works." No data is exposed: the API refuses each of these routes.

**Reproduction at `7554857`.** An Owner of a closing agency opened `/agencies/{a}/team` and landed on `/agencies/{a}/closing`. The primary navigation listed the five agency links, `GET /agencies/{a}` was requested once and refused, and the breadcrumb held only the placeholder `c-skel a-skel--name`.

**Regression that would fail.** On the closing page, the Owner of a closing agency sees no link to the agency's clients, team, keys, audit log or settings, and the page requests neither `GET /agencies/{a}` nor `GET /agencies/{a}/clients`.

### R018-05 (P2): a schedule whose recipient lost their membership cannot be changed in the interface

**Where.**
- In [ScheduleDialog.tsx](../../frontend/src/features/reports/ScheduleDialog.tsx), the form lists as possible recipients only the members whose membership and account are active (line 137), but it keeps every recipient of the schedule in its draft.
- A recipient who is not in that list counts as not allowed (lines 138-141 and 170-175) and has no checkbox to untick (lines 332-358).
- [SchedulesTab.tsx](../../frontend/src/features/reports/SchedulesTab.tsx) has no sentence for `invalid_recipient` (lines 23-26).

**Backend behavior it meets (unchanged `main`).**
- Recipient rows are not removed when a membership is disabled or an account is closed; the worker skips such recipients at each run.
- `ScheduleService.update` (`backend/app/services/report_schedules.py`, lines 275-311) validates every current recipient on every change. A pause or a rename of such a schedule therefore answers `422 invalid_recipient`, while a change that replaces the recipients succeeds (O4).

**Why it matters.** Disabling a member and closing one's own account are ordinary actions, and the form's own hint promises that "Someone who loses access later is skipped at each run." After either action the schedule can only be deleted: the interface can no longer edit, pause or resume it.

**Reproduction at `7554857`.** A weekly schedule had two recipients, the second of them a disabled Analyst.
- The edit form showed one recipient checkbox (the Owner) and "2 of 20 chosen".
- Save was refused before any request with "Untick the people who may not read this report."
- Pause from the row menu sent the change, which the API refused with `422 invalid_recipient` (confirmed on PostgreSQL), and the page said "Something went wrong. Try again."

**Regressions that would fail.** In `tests/unit/features/reports.test.tsx`:
- the edit form lists a recipient whose membership is disabled, marks them as unable to receive, and once they are unticked sends the recipients without them;
- a pause refused with `invalid_recipient` shows the sentence `reports.schedule.error.invalid_recipient`.

**Correction (frontend only).** Show every recipient of the schedule in the form, including those who are no longer members (by name while it is known, otherwise as a former member), so that they can be unticked. On the schedules tab, name `invalid_recipient` and point to the recipients of the schedule.

### R018-06 (P3): the ROAS tab offers the CSV and the export after the report was refused for want of financial access

**Where.** [AttributionPage.tsx](../../frontend/src/features/attribution/AttributionPage.tsx), lines 45-52 and 63. On the ROAS tab, the page head offers the CSV and the export whenever the client has an ad account and a model version. It does not read the refusal that [RoasTab.tsx](../../frontend/src/features/attribution/RoasTab.tsx) reads (line 43). The Revenue and Ad spend pages hide both buttons when their report is refused.

**Why it matters.** The frontend guide's rule on roles: "The interface shows a person what their role may do and hides the rest." The API refuses the CSV and the export with `403`, so nothing is exposed.

**Reproduction at `7554857`.** An Analyst whose ROAS report was refused with `403` saw the sentence that financial access is needed, together with "Download CSV" and "Save as export".

**Regression that would fail.** Without financial access, the ROAS tab shows neither "Download CSV" nor "Save as export".

## 4. Display defects recorded at `e141077` (confirmed)

`e141077` lists four display defects in section 4 of the [completion evidence](evidence-018-completion.md), found when the design canvas was captured from the running application. They are not corrected yet. The review confirms each of them (P3):

| ID | Defect | Confirmation |
|---|---|---|
| K1 | Table cells carry the utility `u-num`, which `docs/design/ui/connect-ui.css` sets to `display: inline-block`. Those cells stop being table cells, and their columns drift from their headers. | 30 `<td>` elements in 13 files have `u-num` in their class: `SeriesChart.tsx`, `AdSpendPage.tsx`, `ContentPage.tsx`, `RevenuePage.tsx`, `CreditTab.tsx`, `FunnelTab.tsx`, `RoasTab.tsx`, `ConversionsTab.tsx`, `WhatsappTab.tsx`, `ExportsTab.tsx`, `SchedulesTab.tsx`, `PlanTab.tsx` and `DiagnosticsCard.tsx`. |
| K2 | The Content destination asks for the icon `image`, which the icon set does not define. | `navigation.ts`, line 129; `connect-icons.css` has no `c-icon--image`. Of the 80 names of `IconName`, it is the only one missing. |
| K3 | The Net revenue and Ad spend figures of the overview, and the Ad spend total, write the currency twice. | `OverviewPage.tsx` (lines 186 and 225) and `AdSpendPage.tsx` (line 177) put the currency before an amount that `money()` already formats with its currency. The scratch render of the spend figure read "EGPEGP 42,300.00". |
| K4 | The Sources card of the overview shows the API's stream name. | `OverviewPage.tsx`, line 246, shows `stream.stream` (for example `account`), untranslated in Arabic. |

Regressions that would fail:
- K1: a scan of `src` for table cells that carry `u-num`, or a browser check that each value cell lines up with its header;
- K2: a unit test that every `IconName` exists in `connect-icons.css`;
- K3: the overview's figures with the currency written once;
- K4: the Sources card naming each stream in words.

## 5. Observations

These are not defects of this pull request. Each is either outside its scope, a limit of the API it uses, or a question for the owner.

- **O1. Revoke for an export that someone else saved.** The exports list offers "Revoke" on every ready export (`ExportsTab.tsx`, lines 313-323). The API allows it only to the export's creator and to Owners and Admins; an Analyst or a client viewer who tries is told why (`reports.revoke.error.access_denied`). The contract gives a person who is not a manager no way to know their own membership (`AgencyAccess` has none), so the interface cannot hide the action without an API change, which this round excludes.
- **O2. The count of kept exports.** "N of 50 kept" (`ExportsTab.tsx`, line 164; `keptExports` in `rules.ts`) counts the ready exports the reader can see, but the limit of 50 applies to the whole client. For a client viewer, or for a reader without financial access, the count can be far below the real one. A save can then be refused with `export_limit_reached` while the page shows room.
- **O3. Report refusals without a sentence.** `errors.ts` names only `report_changed` and `currency_exponent_conflict` (lines 74-77). Several other refusals of the reporting guide read "Something went wrong. Try again." with a retry button, although retrying cannot change a bound:
  - `report_requires_ledger_upgrade`;
  - `report_too_large`;
  - `export_too_large`, from "Download CSV" and "Save as export";
  - `source_unavailable`, `unsupported_currency` and `unsupported_declaration`.

  A correction of R018-01 will show this wording unless sentences are added.
- **O4. The schedule rule on `main` (016-C).** As R018-05 records, `ScheduleService.update` refuses every change while a current recipient may not read the report, a pause included, and nothing removes such a recipient. The interface can work with this rule (R018-05). Whether a pause or a rename should need valid recipients is a backend question of 016-C (D-095, D8 and D9), outside this pull request. No backend test covers a change after a recipient lost access.
- **O5. 017-C: the address of a billing email.** `billing_message` (`backend/app/services/mail.py`, lines 149-150) links to `/agencies/{a}/billing`. The application has no such route, so the trial and hold emails open "Page not found". Billing is off by default and its screens are outside D-106; the billing screens must take that address.
- **O6. 017-B: closing an agency.** The closure dialog and the closing page say that the agency is closed for good after 30 days. Since 017-B merged, the completion of a closure also disconnects every connection, and the agency's data is then purged. Until 24 hours before the closing time, an Owner may ask for an offboarding export (D-098). The interface says neither, and cannot ask for the export; the completion evidence records the missing export. The wording should be revisited with the 017-B screens, before an Owner closes a real agency.
- **O7. 017-C: an agency on hold.** While billing is enabled, the hold refuses new clients, seats, connections and links through plan limits of 0. The interface then says "The agency's plan allows 0 clients...", without naming the hold, and Plan and usage says "The Connect team changes plans for now." Both sentences are true while billing stays off; the completion evidence records the first.
- **O8. When the agreement versions are read.** Sign-in, registration and Google sign-in read `GET /auth/agreements` when the person submits, cached for five minutes (`currentAgreements` in `agreements.ts`), and send what they read. A change of terms between the opening of the page and the first submission is therefore sent as accepted, without the notice A03. A03 appears only when a cached read is out of date, as in a second attempt. Section 4.2 of the completion entry review describes A03 as "The versions changed while the page was open". The legal texts are still `draft-1`. Before real users, read the versions when the box is ticked, or when the page opens, and send those.

## 6. Checked and found consistent

- **Tenant keys.**
  - Every query of an agency's data is keyed under `['tenant', agency, ...]`.
  - Every query of a client's data is keyed under `['tenant', agency, 'client', client, ...]`: reports, exports, schedules, model versions, connections, links, tracking and integrations.
  - The shell removes the data of other agencies and of the client the person left; a sign-in and the end of a session empty the cache.
  - Outside that root are only the session, the agreement versions, the list of the person's own agencies and each agency's profile.
- **Session.**
  - The request-forgery token is a module variable, set from the sign-in and from `GET /auth/me`, and sent on mutations only.
  - The session cookie is never read.
  - `localStorage` holds only the last agency's ID and the preferences; `sessionStorage` holds only the two IDs of a pending connection.
- **Mail links.**
  - The reset and invitation tokens leave the address bar before the router reads it (`main.tsx`, the `hashchange` listener and the two routes), and are kept in memory only.
  - The report email carries no token.
  - `safeNext` accepts only paths of the application, never an entry page.
- **Bundle.** No secret, key, token or backend setting (`build:check`). The first page loads no chart, shell or Analyze code, and the `VITE_` settings are public.
- **Deep links.** These all answer "Page not found": an agency the person does not belong to, a client the API refuses, an export the API refuses (`/reports/exports/{id}`), and the managers' and settings pages for the roles that may not open them.
- **Financial gating.**
  - Revenue and Ad spend answer a `403` with "Needs financial access", no amount and no CSV.
  - Credit, funnel and the reconciliation keep lead credit and say "Needs financial access" for sale values, apart from R018-03.
  - An export with sale values is invisible without financial access (`visible()` in `report_exports.py`).
  - Schedule recipients follow `may_read`, which `mayReceive` mirrors.
- **Reports against 016-C.**
  - The limits of 50 exports, 10 active schedules and 20 recipients.
  - The rule for a schedule's name: 1 to 100 characters, without control characters.
  - ISO weekdays, and `weekday: null` for every cadence but weekly.
  - The five revocation reasons and expiry, the three pause reasons, and the run errors of `RUN_ERRORS` with `build_failed`.
  - The download through the API, after which a `410 export_gone` reads the list again.
  - The revocation rights (see O1).
  - What a client viewer sees: their own exports and those of the schedules they receive, as the API filters them.
- **Roles.**
  - Team and access, API keys and Audit log for Owners and Admins.
  - Agency settings for every role but client viewers, and its closure tab for Owners.
  - "New schedule" and every schedule change for Owners and Admins.
  - The branding profile edited by Owners and Admins, read by Analysts.
- **017-A on `main`.**
  - The agreement versions on every sign-in, registration and Google start.
  - Audit rows by the operator (`actor_kind`).
  - Closing agencies listed to their Owners and opened on B15, apart from R018-04.
  - `plan_limit_reached` named with its limit.
- **The backend.** Its diff against `main` is B1 and B2 of D-101 only.

## 7. Limits of this review

- Firefox and 62 of the 64 journeys were not run again. The backend suites were not run again either: the backend equals `main` apart from B1 and B2, which the P0 and P5 evidence covers.
- The scratch unit tests used the unit tests' stand-in API. The `409 report_requires_ledger_upgrade` of R018-01 comes from the backend code and the reporting guide, and `test_report_bounds.py` covers it on the backend. The API half of R018-05 was confirmed on PostgreSQL.
- Slices 018-A, 018-B and 018-D were read for the cross-cutting rules only. The Arabic copy and the design canvas were not reviewed.

## 8. Recommendation

Do not merge at `e141077` yet.
- None of the defects exposes data or crosses a tenant.
- R018-01, however, shows a wrong state on the first page of every client that has more than 200 revenue records.
- R018-05 leaves schedules that can only be deleted.

All ten corrections (R018-01 to R018-06, K1 to K4) are frontend-only and fit D-106: no API, contract or schema change. The recommended path:
1. Correct them on `codex/spec-018-workspace-screens`, each with a regression that fails at `7554857`.
2. Run the unit tests, `build:check`, and the journeys of the pages they touch (at least 18 to 23, and 10 for accessibility) in Chromium and Firefox.
3. Hold a short review of the corrections, then merge. The merge also merges pull request 17.

Outside that path:
- O4 and O8 each need an owner decision of their own.
- O5 to O7 belong to the screens of 017-B and 017-C.

If the owner prefers to merge first, R018-01 and R018-05 should be the first corrections after the merge, and nothing should reach real users before them.
