# Plan of P4: Reports (018-G)

Status: phase P4 of the [completion handoff](implementation-prompt-completion.md), approved with D1-D12 of the [completion entry review](entry-review-completion.md) by D-099 (2026-11-28). D9 asks for drawings first: they were made on 2026-11-28 (section 2) and the owner approved them the same day (D-104). Section 4 is the plan of the build.

## 1. The contract the drawings follow
Spec 016-C on `main` ([entry review](../016-analytics-reporting/entry-review-016c.md), [design](../016-analytics-reporting/design-016c.md)), below `/agencies/{a}/clients/{c}`:

| Need | Route | Rule that shapes the screen |
|---|---|---|
| Save a report as an export | `POST .../report-exports` | The family and parameters of the report page, with its days. Sale values of attribution and funnel are kept exactly when the person has financial access. At most 50 unexpired exports per client (`409 export_limit_reached`). |
| List and open exports | `GET .../report-exports`, `GET .../report-exports/{id}` | Newest first. Owners, admins and analysts see every export they may read; a client viewer sees the exports they saved and those of schedules they receive; exports with sale values need financial access. Anything else answers `403`, like an unknown export. |
| Download | `GET .../report-exports/{id}/download` | The CSV attachment, checked again at every download. A revoked or expired export answers `410 export_gone`, so the screen reads the export again to name the reason. |
| Revoke | `DELETE .../report-exports/{id}` | Its creator, or an owner or admin. |
| Schedules | `POST`, `GET`, `PATCH`, `DELETE .../report-schedules[/{id}]` | Owners and admins. Daily (the day before), weekly on an ISO weekday (the 7 days before) or monthly on the 1st (the previous calendar month), at an hour of a time zone; at most 10 active per client. A schedule runs with its owner's access; it pauses when the owner loses it (`owner_access_lost`), after three failed runs (`repeated_failures`) or by hand (`manual`). Resuming makes the manager its owner. |
| Recipients | part of the schedule; `DELETE .../report-schedules/{id}/recipients/me` | Up to 20 members of the agency, each able to read the report (with financial access when sale values are included), or the API refuses the schedule (`invalid_recipient`). Recipients are listed to managers only. A recipient can leave. |
| The email | written by `python -m app.report_worker` | Names the agency, the schedule, the kind of report and the period, with a link to `/agencies/{a}/clients/{c}/reports/exports/{id}`; no figure and no client name. |

Members are listed to owners and admins only (`GET /agencies/{a}/members`), so the names of the person who saved an export and of recipients are shown to them; others see the source without a name.

## 2. The drawings (D9)
Reference pages in `docs/design/preview/screens/`, and the same six artboards on the "A to Z" page of the design canvas in place of the concept E03, keeping every other code:

| Code | Page | What it shows |
|---|---|---|
| E03 | `reports.html` | Reports, Exports tab: report and its choices, when and by whom or by which schedule it was made, its state (ready, revoked with its reason, expired), until when it is kept, its size and rows, its downloads, and the download and actions; who sees an export and how a report is saved. |
| E04 | `reports-schedules.html` | Reports, Schedules tab: each schedule with its report, when it runs and in which time zone, the next run, the last run (built, with how many recipients were told or skipped, or failed with its reason), its state with the pause reason and the number of recipients; what a recipient sees and can do (stop receiving); what each cadence reports. |
| E05 | `report-save-export.html` | "Save as export" beside "Download CSV" on a report page (Attribution, credit), and its dialog: the report, model, period, comparison, sale values, until when it is kept, and how many exports the client keeps. |
| E06 | `report-schedule-form.html` | The schedule form: name, report and its parameters, comparison, sale values, daily, weekly or monthly with weekday, hour and time zone, and recipients, a member who could not receive it being unavailable. |
| E07 | `report-export.html` | The page the report email opens: the export, its details, the download, and the way to the same days of the live report. |
| E08 | `report-export-gone.html` | An export that is gone, and the sentence for each reason: revoked, erasure, disconnection, purge, archived client, expired; no access gives "Page not found". |

No PDF or printable page is drawn (D-095).

## 3. Checks of the drawings
The six pages rendered in Chromium at 1440 pixels and were reviewed as screenshots in light and dark; at 390, 768, 1024 and 1440 pixels, light and dark, none overflows and none logs a console error. The canvas artboards were not rendered: the canvas type does not allow it unless the owner asks.

## 4. After approval: the build
- **Address and navigation.** `/agencies/{a}/clients/{c}/reports` (tabs `exports` and `schedules`) and `/agencies/{a}/clients/{c}/reports/exports/{id}`; Reports joins the Manage group of the client.
- **Save as export.** On Content, Revenue, Ad spend and the three tabs of Attribution, with the parameters each page already sends for its CSV.
- **Rules.** Gone reasons, the bounds (50 exports, 10 active schedules, 20 recipients), pause reasons and run outcomes compared with `backend/app/services/report_exports.py`, `report_schedules.py` and `backend/app/api/report_delivery.py` by unit tests.
- **Journey `23-reports`.** Save an export from a report page and download it; revoke it and see it gone; create a schedule with a recipient; run `python -m app.report_worker` once on the stack; read the local `.eml` through `tests/browser/support/mail.ts`; open its address.
- **Removed protections.** The client viewer's visibility, the gone reasons, the bounds, and the email address that opens only an export the reader may see.
- **Evidence.** `evidence-018g.md`; commit; push.
