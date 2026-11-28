# Evidence: Reports (018-G, phase P4)

Status: slice 018-G, Reports, is drawn, approved (D-104) and implemented as described here on 2026-11-28, under D-099 and the [plan](plan-018g.md), on `codex/spec-018-workspace-screens`. It is not accepted until the owner has reviewed it. A pull request follows at the end of the round (D11).

## 1. What was built

| Code | Screen | Address | Built on |
|---|---|---|---|
| E03 | Reports: exports | `/agencies/{a}/clients/{c}/reports` | `GET .../report-exports`, `GET .../report-exports/{id}/download`, `DELETE .../report-exports/{id}` |
| E04 | Reports: schedules | `/agencies/{a}/clients/{c}/reports?tab=schedules` | `GET`, `PATCH`, `DELETE .../report-schedules`, `DELETE .../report-schedules/{id}/recipients/me` |
| E05 | Save as export | every report page | `POST .../report-exports` |
| E06 | The schedule form | Reports, "New schedule" or "Edit" | `POST` and `PATCH .../report-schedules` |
| E07 | The export a report email opens | `/agencies/{a}/clients/{c}/reports/exports/{id}` | `GET .../report-exports/{id}` and its download |
| E08 | An export that is gone | the same address | `GET .../report-exports/{id}` (revoked or expired) |

- **Navigation.** Reports is the last item of the client's Manage group, for every member; on a phone it is under More.
- **Save as export.** Beside "Download CSV" on Content, Revenue, Ad spend and the three tabs of Attribution, with the same report, choices and days as the page's CSV; compared only where the API allows it. The dialog names the report, the model, the period, the comparison and, for attribution and the funnel, that sale values are kept only with financial access; a saved export is announced with its expiry and a link to it.
- **Exports.** Newest first, with the report and its choices, when and by whom or by which schedule it was made (names for owners and admins, who can read the team), its state (ready, revoked with its reason, expired), until when it is kept, its size and rows, and its downloads. A ready export downloads through the API as `report-<family>.csv`; a download that finds it gone says so and reads the list again. Its creator, or an owner or admin, can revoke it after a confirmation. The page says how many of the 50 the client keeps, and who sees an export.
- **Schedules.** Owners and admins see every schedule of the client: its report, when it runs and in which time zone, the next run, the last run (built with how many recipients were told and skipped, or failed with its reason), its state with the pause reason, and its recipients; they edit, pause, resume and delete them, and can stop receiving one they receive. Analysts and client viewers see the schedules they receive, each with "Stop receiving". A card says what each cadence reports.
- **The schedule form.** Name; report, with its account, view, level, grouping and model where the report has them; comparison; sale values for attribution and the funnel; daily, weekly with a weekday, or monthly; the hour and the time zone (the browser's first); and up to 20 members of the agency. A member who may not read the report is unavailable, with the reason, because the API refuses such a recipient. Each refusal of the API has its own sentence.
- **The export page.** The details, the download, and a link to the same days of the live report; a revoked or expired export says why and when; a reader who may not see the export gets "Page not found", as for an unknown one.
- **Messages.** 210 messages of Reports in each language.

## 2. Checks

| Check | Result |
|---|---|
| `npm run typecheck`, `npm run lint`, `npm run api:check` | Passed; no finding; "The contract types match contracts/openapi.json." |
| `npm test` | 33 files, 607 tests passed, twice in a row (587 after P3). The wait of the screen queries rose from 8 to 15 seconds: with the whole suite running at once, the first visit to a page that loads with its charts took just over 8 seconds on this workstation in two runs, and the Analyze tests load their pages before they start. |
| `npm run build`, then `npm run build:check` | Built; the Reports page is a chunk of 17.11 kB (4.81 kB compressed) and the export page one of 7.55 kB (2.23 kB). "No secret, key, token or backend setting was found." The first page loads seven script files, 769.85 kB (six, 735.35 kB, after P3): the messages of both languages, and the export query the router uses to answer "Page not found" for an export a reader may not see. |
| Journeys, Chromium | 64 journeys in four groups, all passed: files 01 to 09, 22 (2.3 minutes); 10 to 12, 27 (9.4 minutes, in the background); 13 to 16, 8 (1.8 minutes); 17 to 23, 7 (1.7 minutes). The explanatory cards of E03 and E04 came after group 10 to 12 started, so its Analyze and Reports scans, the phone scan and journey 23 ran again on the final code: 6 passed (4.0 minutes). |
| Journeys, Firefox | 64 journeys on the final code, all passed: 22 (2.2 minutes), 27 (9.9 minutes, in the background), 8 (2.2 minutes) and 7 (2.2 minutes). |
| Accessibility | The 22 axe tests of journey 10 in each browser report 0 serious or critical and 0 moderate or minor findings. The Analyze tests now also open the save-as-export dialog, the export, the list of exports, the revoke dialog, an export that is gone, the schedules and the schedule form with a problem, in the four looks; the phone test opens Reports at 390 pixels, no wider than the screen. |
| `git diff --check` | Clean. |

### 2.1 The journey `23-reports`
On the disposable stack: an owner with an agency, a client with a declared sale, and an analyst who may open the client without its financial data. The journey checks that:
- the Revenue page saves its report as an export ("21 days"), announces it and opens it; the export page says its download needs financial access;
- the download is `report-revenue.csv` with the CSV of the report;
- a revoked export reads "Revoked by a person" in the list, and its page says it was revoked and when;
- a schedule needs its name; the analyst cannot receive it (no financial access); with the owner as recipient it is created active and "Not run yet";
- once made due, one pass of `python -m app.report_worker` builds it and tells one recipient; the list reads "Built; 1 recipient told"; the captured email holds the address of the export, which opens "Made by the schedule “Weekly revenue”";
- the same address is "Page not found" for the analyst, whose list of exports is empty.

### 2.2 Removed protections
Each protection was removed alone with a scratch script, the named unit test failed, and the file was restored byte for byte (SHA-256 compared):

| Protection | Failing test |
|---|---|
| Schedules are managed by owners and admins only; a recipient may only leave | "let a recipient who is no manager stop receiving one, and nothing else" |
| Only members who may read the report can be chosen as recipients | "are created with a name and members who may read the report, as the API takes them"; "let only members who may read the report receive it" |
| A revoked export says why it is gone | "say how an export stands and how long it is kept"; "says why an export is gone"; "shows each export with its state, its expiry, its size and its downloads" |
| The recipient bound of the API | "keep the bounds of the API" |
| The export bound of the API | "keep the bounds of the API"; "shows each export with its state, its expiry, its size and its downloads" |
| The address of an email opens only an export the reader may see | "does not exist for a reader who may not see it" |

Unit tests also read `backend/app/services/report_exports.py`, `report_schedules.py`, `reporting.py` and `backend/app/api/report_delivery.py`, and fail when the bounds, the revocation and pause reasons, the failed-run codes, the financial rules or the name rule of the interface differ from them.

## 3. Limits
- Exports are CSV files; printable pages and PDF files are not part of this round (D-095).
- In development the report emails are the local `.eml` capture; production email is decided with hosting (Q-008, 020). The report worker runs only when it is started; production scheduling is decided in 020.
- The journey makes its schedule due by moving its next run into the past in the disposable database, because a new schedule first runs at its next slot.
- The agency's brand on the screens of client viewers waits for the owner's brief (D8).
- The Arabic copy is written by a model and marked for review by a native editor (D12).
