# Spec 016-C entry review: retained exports, scheduled reports and the white-label delivery contract

Prepared: 2026-11-27 under D-094.
- **Baseline:** merged `main` at `06d6a19` (PR 19: Spec 017-A, plans, limits and agency closure).
- **Status:** approved. The owner approved D1-D14 as recommended, without amendment, on 2026-11-27 (D-095).
- **Handoff:** the [implementation handoff](implementation-prompt-016c.md) executes this packet after approval.

## 1. Intended result

016-C completes Spec 016 on the backend:
- **Retained exports.** A member saves a report as a file that stays available for a short time. Every download is authorized again, and an erasure, a disconnection or an archival revokes the file. This closes acceptance criterion 5 of the [spec](spec.md) and the export part of the 003 obligation (D-025).
- **Scheduled reports.** A manager schedules a report for a client. A worker builds it on time with its owner's permissions and tells each recipient that it is ready, inside the application and by email (PDF-070). This closes the background-generation part of acceptance criterion 1.
- **White-label delivery contract.** An agency keeps a branding profile: the name its clients see, an accent color and a logo. Report emails use it, and the frontend can apply it later to the screens of client viewers (PDF-097).

D-091 records the owner's plan to finish the backend before the frontend, with 016-C in the same round as 017-A. LinkedIn (012) and X (013) stay deferred under D-063. The visual application of a brand needs the owner's brief before any screen is built (D-039). It therefore belongs to the frontend round, together with printable pages and PDF files.

## 2. Baseline on `main`

| Area | Available | Consequence for 016-C |
|---|---|---|
| Reports (016-A, 016-B) | Six families for one client: social, spend, revenue, attribution, ROAS and funnel. A period is at most 31 days. The answer is JSON pages or a direct CSV of at most 5,000 rows and 2 MiB. Each answer is built in one snapshot, checked again before release (`release_check`) and sent with `Cache-Control: no-store`. Nothing is stored. | An export stores exactly the direct CSV. No new report logic is needed. |
| Permissions | Social, attribution and funnel need `client:read`; spend, revenue and ROAS need `finance:read`. Sale values of attribution and funnel also need `finance:read`. `resolve_scope` checks the user, the membership and the client grants each time. A `Principal` may come from a trusted job. | A download and a scheduled run resolve the scope again at the moment they act. |
| 003 export contract | Design section 11 defines `export_artifacts`: AES-GCM bound to the export, agency and client; downloads only through the authenticated API, with the scope resolved again; `includes_financials` needs `can_view_financials`; no public signed URL in development. Candidate lifetimes: 7 days for the file and 15 minutes for a download token. Section 10: a subject deletion revokes the unexpired exports created before it. | 016-C implements this contract. A download token is not needed for browser sessions (D6). |
| Encryption | `app.privacy.token_secrets` seals data under the local token keyring (`TRACKING_TOKEN_KEYRING`), used by 009, 014, 015 and 006. | Exports use the same envelope encryption with a new kind. No new keyring. |
| Erasure | The 004 subject erasure and the 006 person erasure record per-target outcomes (`target_outcomes`); 008-B added `attribution`. Both hold the client privacy lock. | A new target, `report_exports`. |
| Connectors and clients | Every disconnection goes through `start_disconnect`, whatever its cause: the member's request, lost authorization, a provider callback or `python -m app.connector_purge`. A client can be archived. | Each one revokes the exports it covers. |
| Mail | An encrypted outbox (`verify`, `reset`, `invitation`) with an expiry. In development, the worker writes `.eml` files that the lifecycle runner deletes after 7 days. The Gmail transport is opt-in and owner-operated (Q-008). | Report emails use the same outbox with a new purpose. |
| Workers | One-pass, bounded commands: `connector_worker`, `attribution_worker`, `mail_worker` and `lifecycle`. Production scheduling is decided in 020. | A new command, `python -m app.report_worker`. |
| Roles | Owner, Admin, Analyst and Client viewer. A client viewer sees one client through a grant, with optional financial and identity flags. | Client viewers are the audience of white-label reports. |
| Frontend (018) | The design has a client-level "Reports" page under Manage, and the brand is Connect. There is no white-label screen yet, and the 018-B to 018-D screens are not built. | 016-C publishes the API that those screens will use. |

## 3. Decisions for the owner

The recommendations are for synthetic data and disposable PostgreSQL. They are product and policy choices, not legal advice. They leave Q-003, Q-008, Q-011 and Q-012 open.

| ID | Recommended choice | Alternative and its effect |
|---|---|---|
| D1 Scope and delivery | 016-C has three parts: retained exports, scheduled reports with notifications, and the white-label delivery contract. Phases P0-P5 run on one branch, `codex/spec-016c-report-delivery`. Verified commits are pushed after each phase (D-051), and one pull request is opened for review. | Two slices: exports and schedules now, the branding profile with the frontend. Smaller now, but the frontend round would need a backend change and a migration. |
| D2 Retained export | A member who can read a report saves it as an export: the same family and parameters as the report routes, CSV only. It is built at once in the request, with the 016-A bounds, and stored encrypted. Browser sessions only; read keys keep the direct CSV. At most 50 unexpired exports per client. | Build exports in the background with a "pending" state. This only helps reports larger than today's bounds, and those do not exist. |
| D3 Visibility | Owners, Admins and Analysts see every export of a client they can read, as long as they hold its permissions. A client viewer sees only the exports they created and those of schedules they receive. Another agency or client never sees an export. | Everyone sees every export they could rebuild: simpler, but the agency could no longer choose what its clients receive. |
| D4 Storage and encryption | The ciphertext is stored in PostgreSQL in its own table and sealed like a connector token, under the token keyring with a new kind `report_export`. The seal is bound to the export, agency and client, so a copied ciphertext does not open. Plaintext is never written to disk. A missing keyring refuses exports with `503 not_configured`. Object storage and managed keys are chosen with hosting (020). | A local file directory, as the 003 sketch named `file_ref`. Files are not covered by transactions, so a crash can leave orphan files that need a cleanup job. |
| D5 Lifetime | An export lives 7 days, the 003 candidate, as a setting with that maximum. Q-012 stays open. Then the lifecycle runner deletes its content and its row. A revocation deletes the content at once. The row stays until the export would have expired, so that the list can show why it is gone. | Keep the metadata longer, for example 30 days: a longer history, but one more retention period to approve. |
| D6 Download | Downloads go through the authenticated API (`GET .../report-exports/{id}/download`). The downloader's scope and permissions are resolved again at that moment, with `finance:read` when the export holds sale values. A revoked or expired export answers `410 export_gone`. The response is the CSV attachment with `no-store`. Each download increments a counter on the export. No download token and no signed URL. | The 15-minute download token of the 003 sketch. It is only useful for a link that works without a session, such as object storage; 020 can add it then. |
| D7 Revocation | An export is revoked, and its content deleted at once, when: its creator or a manager revokes it; a subject or person erasure is accepted in its client (every export of that client created before the erasure, with the outcome `report_exports: done`); its connection is disconnected or purged (the social, spend and ROAS exports of that connection); or its client is archived. An export is never stored after the event that should revoke it. A closing agency needs no revocation: its exports are unreachable and expire before the closure completes. | Revoke only the attribution, ROAS and funnel exports at an erasure, because the others hold provider metrics or totals that the erasure keeps (F1). Narrower, but a harder rule to explain and to check. |
| D8 Schedules | An Owner or Admin schedules one report of a client. A schedule has a name; a family and its parameters; a cadence (daily for the previous day, weekly on a chosen weekday for the previous 7 days, monthly on the 1st for the previous calendar month); an hour and a time zone; an optional comparison with the previous period; and whether sale values are included. A schedule runs with its owner's permissions, checked at every run. If the owner loses them or leaves, the schedule pauses, and a manager who resumes it becomes its owner. At most 10 active schedules per client. | Free cron expressions: more flexible, but harder to validate, to explain and to display. |
| D9 Recipients and notification | Recipients are members of the agency, at most 20 per schedule. At each run, every recipient who still holds the export's permissions sees the export in the application, and gets an email from the outbox (purpose `report_ready`). The email holds the agency's display name, the schedule name, the report kind, the period and a link to the application, and nothing else: no figure, no client name, no token. Recipients without access are skipped and counted. A recipient can leave a schedule. There are no external addresses. In development, emails are only the local `.eml` capture; production delivery stays Q-008 and 020. | Emails with a digest of the main figures: more useful at a glance, but customer data would leave the application by email, which needs the production mail decision first. |
| D10 Worker | `python -m app.report_worker` runs one bounded pass, like the other workers. It claims due schedules with `SKIP LOCKED`, checks the agency, the client and the owner, builds and stores the export, queues the emails and moves the schedule to its next slot. A slot missed because the worker did not run is not repeated: the next run reports the latest period. A failed run is retried at most twice in the same pass. Then the schedule records the closed error code and moves to its next slot, and three consecutive failures pause it. A suspended or closing agency and an archived client get no run. | A long-running scheduler process: a decision for 020, with process supervision. |
| D11 White-label | Each agency may keep a branding profile: a display name for its clients (1-100 characters), an accent color (`#RRGGBB`) and an optional logo. The logo must be a PNG of at most 256 KiB and 1024 by 1024 pixels, checked by its signature and header; SVG is refused. Owners and Admins edit the profile; every member of the agency, client viewers included, can read it. Report emails use the display name, or the agency's name when there is no profile. Branded screens, printable pages and PDF files wait for the frontend round and the owner's brief (D-039). Whether a plan may hide the Connect brand is decided with the prices of 017-C. | Defer the whole branding profile to the frontend round. The emails would then carry the agency's internal name, and the frontend round would need a backend change. |
| D12 Schema | One additive migration, `0032_report_delivery`: `report_exports`, `report_export_contents`, `report_schedules`, `report_schedule_recipients` and `agency_branding`. The outbox purpose, the audit actions and resources, and the data policy rows are widened. Scoped keys, closed checks and restricted grants follow 0026-0031, and the lifecycle role may only delete expired exports. It is tested on disposable PostgreSQL only, and the downgrade refuses stored rows. | A table of schedule runs for history. Useful for support later, but it is a new retention period, and the last outcome on the schedule covers the need now. |
| D13 Boundaries | Backend only, synthetic data, disposable PostgreSQL, no new dependency and no live provider. No external email: the outbox writes `.eml` files in development, and Gmail stays owner-operated as today. No PDF, no printable page, no frontend change and no shared cache. No plan limit for exports or schedules (017-C may add one). The direct CSV of 016-A and every report answer stay unchanged. | Generate PDF files now. That needs a new rendering dependency and the owner's brand brief. |
| D14 Completion evidence | The [verification matrix](#5-verification-matrix) RV01-RV20 is executed with the existing suites, and every command and count is recorded. Each new safeguard is shown to fail its test when disabled. The completed branch is presented for independent review in its pull request. | Unit tests only: fast, but they would miss the locks, the concurrency and the revocation paths. |

## 4. Design for implementation after approval

The design note of P0 (`design-016c.md`) fixes the exact statements, answers and tests. It follows these lines.

### 4.1 Schema (`0032_report_delivery`, after `0031_saas_plans`)

- **`report_exports`:**
  - the agency and client (composite key), the family, the normalized parameters (JSONB) and the period;
  - whether sale values are included, the source (`manual` or `schedule`), the schedule and the requesting membership;
  - the status (`ready` or `revoked`), the revocation time and its closed reason (`manual`, `erasure`, `disconnection`, `connection_purged` or `client_archived`);
  - the creation and expiry times, the row count, the size, the report revision, the download count and the last download time.
- **`report_export_contents`:** one row per ready export, with the sealed ciphertext (KEK ID, wrap nonce, wrapped key, nonce, ciphertext, algorithm and AAD version). It is deleted at revocation and at expiry.
- **`report_schedules`:**
  - the agency and client, the name, the family, the parameters without dates, the sale-values flag and the comparison flag;
  - the cadence, the weekday, the hour and the time zone;
  - the status (`active` or `paused`) and the closed pause reason, the owner membership and the next run time;
  - the last run: time, outcome, error code, recipients notified and skipped, and the count of consecutive failures.
- **`report_schedule_recipients`:** the schedule and the membership, unique together.
- **`agency_branding`:** one row per agency, with the display name, the accent color, the optional logo bytes, its width and height, and the time and membership of the last change.
- **Changes:** the outbox purpose accepts `report_ready`. Audit actions: `report_export.created`, `report_export.revoked`, `report_schedule.created`, `report_schedule.updated`, `report_schedule.deleted` and `branding.updated`. Audit resources: `report_export`, `report_schedule` and `agency_branding`.

### 4.2 Exports

- **Create:** `POST /agencies/{a}/clients/{c}/report-exports` takes `{family, ...parameters}` with the same validation as the report route of that family. The build follows the direct CSV path: `build_report`, `report_csv` and `release_check`. The store happens under the client privacy lock: a build that started before an erasure of the client completed is discarded and rebuilt. The store also rechecks the connection of a connection report and the client's status. Audited.
- **Read:** `GET .../report-exports` lists the visible exports, newest first and paginated, and `GET .../report-exports/{id}` returns one.
- **Download:** `GET .../report-exports/{id}/download` (D6).
- **Revoke:** `DELETE .../report-exports/{id}`, by the creator or a manager. Audited.
- **Automatic revocation (D7):** one function, `revoke_exports(session, scope, reason, before)`. It is called by the 004 and 006 erasures (inside their transaction, after their other targets), by `start_disconnect` for every cause of disconnection, the purge included, and by the client archival.

### 4.3 Schedules and the worker

- **Routes:** `POST`, `GET`, `PATCH` and `DELETE /agencies/{a}/clients/{c}/report-schedules[/{id}]` for managers. A recipient may read the schedules they receive, and leaves one with `DELETE .../report-schedules/{id}/recipients/me`.
- **Periods:** computed from the run date in the schedule's time zone. The time-zone rules and the month ends are fixed in the design note, with tests. The report then applies its own source-native days and its partial, provisional and stale states, as today.
- **Worker:** `python -m app.report_worker` follows the pass of D10 and prints counts only: due, built, notified, skipped, failed and paused.
- **Email:** the outbox entry expires with its export. Its text and its link to the application (`{frontend_origin}/agencies/{a}/clients/{c}/reports/exports/{id}`) are fixed in the design note.

### 4.4 Branding

- **Profile:** `GET` and `PUT /agencies/{a}/branding` (read by members, written by managers, audited).
- **Logo:** `PUT /agencies/{a}/branding/logo` takes a raw `image/png` body, with a route size limit of 256 KiB; `DELETE` removes it. `GET` serves it to members with `Content-Type: image/png`, `nosniff` and `Content-Security-Policy: default-src 'none'`.

## 5. Verification matrix

| Case | Required observable evidence |
|---|---|
| RV01 Export creation | Every family can be exported with its parameters and bounds. A client viewer may export what they can read; a read key, an ingest key, another client and another agency are refused. The 51st unexpired export of a client is refused, and a missing keyring answers `not_configured`. |
| RV02 Encryption | No plaintext is stored. A ciphertext copied to another export, client or agency does not open. |
| RV03 Download | The scope is resolved again at download, including `finance:read` for sale values. A revoked or expired export answers `export_gone`. The response is an attachment with `no-store`, equal byte for byte to the direct CSV of the same revision. |
| RV04 Visibility | Staff see every export of a client they can read; a client viewer sees only their own and those of schedules they receive; another agency or client sees nothing. |
| RV05 Manual revocation | The creator or a manager revokes an export; anyone else is refused. The content is gone at once, and the revocation is audited. |
| RV06 Erasure | A 004 subject erasure and a 006 person erasure revoke the client's earlier exports and record `report_exports: done`. Later exports and other clients are untouched. An export whose build overlaps an erasure is never stored with pre-erasure data. |
| RV07 Disconnection and purge | Disconnecting or purging a connection revokes the exports built from it, and only those. |
| RV08 Archival | Archiving a client revokes its exports; a closing agency's exports are unreachable. |
| RV09 Expiry | The lifecycle runner deletes expired exports and their content in bounded, idempotent batches, as `tracking_lifecycle`. |
| RV10 Schedule rules | Cadence, weekday, hour, time zone and parameters are validated like the report routes. Only managers create schedules; at most 10 active schedules per client; recipients must be members who can read the report. |
| RV11 Periods | Daily, weekly and monthly periods are correct in several time zones, across daylight-saving changes and month ends. |
| RV12 Worker | Due schedules run once, also under two concurrent workers. The next slot follows the rules, and a missed slot is not repeated. A pass is bounded. |
| RV13 Run permissions | An owner without access pauses the schedule; a recipient without access is skipped; sale values reach only recipients with `finance:read`. |
| RV14 Email | One outbox entry per notified recipient, with purpose `report_ready` and the export's expiry. The text has no figure, client name or token. Only local `.eml` files are written in development. |
| RV15 Stop states | A suspended or closing agency and an archived client get no run. |
| RV16 Failures | `report_changed` is retried; a report too large, a source not ready or a missing keyring is recorded with its closed code; three failures pause the schedule. |
| RV17 Branding | Profile validation, a valid PNG accepted, SVG and malformed or oversized images refused. Members read the profile and managers write it; the logo is served with its safe headers; changes are audited. |
| RV18 Migration | Upgrade from a populated `0031`, grants and data policy rows as D12 states, model metadata matching, and a downgrade that refuses stored rows. |
| RV19 Isolation and logs | No figure, name, token or file content appears in a log line or in the worker output. Agencies and clients never see each other's exports, schedules or branding. |
| RV20 Existing behavior | Every existing suite passes, the direct CSV and every report answer are unchanged, and the OpenAPI snapshot has additions only. |

## 6. What remains after 016-C

- **The frontend:** the Reports pages, the branded screens of client viewers, printable pages and PDF files, after the owner's brief (D-039, 018).
- **Production:** object storage and managed keys for exports, the worker schedule and production email (020, Q-008).
- **Later options:** digests with figures in emails, external recipients, warehouse and Sheets synchronization (021), and plan limits for exports and schedules (017-C).
