# Spec 016-C design: retained exports, scheduled reports and the white-label delivery contract

Prepared: 2026-11-27 under D-095. Revision: 1. Status: approved scope ([D1-D14](entry-review-016c.md#3-decisions-for-the-owner), D-095, without amendment). This note fixes the exact schema, requests, permission checks, locks, periods, worker pass, email text, image checks and tests before any application code. Section 4 of the entry review is its source. Section 12 lists the routine details resolved here; no material new choice was found that needs the owner.

## 1. P0 inventory

**Branch.** `codex/spec-016c-report-delivery` was created from `origin/claude/keen-fermat-otlr9d` at `5541091`. `git merge-base --is-ancestor 06d6a19 HEAD` succeeds, and `origin/main` is still `06d6a19` (PR 19), so no merge was needed. D-095 is in the register and approves D1-D14 without amendment. Pull request 17 (Spec 018) is still open, and `frontend/` holds only placeholder README files, so the frontend checks of P5 do not apply.

**Decision numbers.** The register on this branch ends at D-095. The pushed but unopened branch `codex/spec-018-workspace-screens` reuses D-093 and D-094 for Spec 018 work; this slice records no new decision, and the collision is reported to the owner, not changed here.

### 1.1 Report parameters by family

The six routes of `app/api/reports.py` accept `start`, `end`, `compare=previous`, `page`, `page_size`, `expected_revision` and `format`, plus:

| Family | Permission | Family parameters | Rules from `ReportQuery.periods()` |
|---|---|---|---|
| `social` | `client:read` | `connection_id` (required), `view` (`daily`, `content_cohort`; required), `metrics` (1-25 names `^[A-Za-z_]{1,64}$`) | no comparison for `content_cohort` |
| `spend` | `finance:read` | `connection_id` (required), `level` (`ad`, `adset`, `campaign`; default `ad`) | |
| `revenue` | `finance:read` | none | |
| `attribution` | `client:read`, sale values with `finance:read` | `group_by` (`campaign`, `content`, `link`, `recipient`; default `campaign`), `view` (`groups`, `models`; default `groups`), `model_version` | no comparison and no `model_version` for `models` |
| `roas` | `finance:read` | `connection_id` (required), `level` (default `ad`), `model_version` | |
| `funnel` | `client:read`, sale values with `finance:read` | `group_by` (`campaign`, `content`, `link`; default `campaign`), `model_version` | |

A period is at most 31 days (`Period`), and the CSV is bounded to 5,000 rows and 2 MiB (`MAX_ROWS`, `MAX_BYTES`).

### 1.2 Paths that must revoke (D7) and the locks they hold

| Path | Entry point | Locks held before the new revocation call |
|---|---|---|
| 004 subject erasure | `erase_subject` (manager route through `CollectionAdmin.request_erasure`, and the data subject's public route) | agency row `FOR UPDATE` on the manager route; the client privacy lock (`pg_advisory_xact_lock(4004, key)`, `lock_timeout` 2 s); the subject row |
| 006 person erasure | `IdentityAdmin.erase` and `resolve` (`_run_erasure`, `_decide_holds`) | agency row `FOR UPDATE`; the client privacy lock; person, key and request rows |
| Disconnection, every cause | `start_disconnect`: the member's request (`ConnectorAdmin.disconnect`: agency and connection rows `FOR UPDATE`), lost authorization in the worker (connection rows `FOR UPDATE SKIP LOCKED`), provider callbacks (`connector_callbacks`: connection rows `FOR UPDATE`) and `app.connector_purge` (every connection of the provider `FOR UPDATE`, several clients in one transaction) | as listed |
| Client archival | `TenancyService.update_client` with `status="archived"` | agency row `FOR UPDATE`; the client row update |

Every database connection runs with `lock_timeout=3000` and `statement_timeout` (`app.database`); the pool has no overflow. A browser request's own transaction holds its user and session rows `FOR UPDATE` from authentication until it commits (`AuthService.authenticate`).

## 2. Schema: migration `0032_report_delivery`

Revises `0031_saas_plans`. All tables are new; the only changes to existing tables widen two check constraints.

### 2.1 `report_exports`

| Column | Type | Rule |
|---|---|---|
| `id` | `uuid` | primary key |
| `agency_id`, `client_id` | `uuid` | `(agency_id, client_id)` references `client_workspaces (agency_id, id)` |
| `family` | `varchar(16)` | one of the six families |
| `parameters` | `jsonb` | the normalized report parameters (section 3), a JSON object |
| `connection_id` | `uuid` null | required exactly for `social`, `spend` and `roas`; `(agency_id, client_id, connection_id)` references `connector_connections (agency_id, client_id, id)` |
| `period_start`, `period_end` | `date` | `period_end > period_start`, at most 31 days |
| `includes_financials` | `boolean` | true for `spend`, `revenue` and `roas`, and for `attribution` and `funnel` built with sale values |
| `source` | `varchar(16)` | `manual` or `schedule` |
| `schedule_id` | `uuid` null | references `report_schedules (id)` `ON DELETE SET NULL`; null for `manual` |
| `requested_by_membership_id` | `uuid` | the creator, or the schedule owner; `(agency_id, requested_by_membership_id)` references `agency_memberships (agency_id, id)` |
| `status` | `varchar(16)` | `pending`, `ready`, `revoked` or `discarded` |
| `revoked_at` | `timestamptz` null | |
| `revoked_reason` | `varchar(24)` null | `manual`, `erasure`, `disconnection`, `connection_purged` or `client_archived` |
| `created_at` | `timestamptz` | default `now()` |
| `stored_at` | `timestamptz` null | when the content was stored |
| `expires_at` | `timestamptz` | after `created_at`, at most 7 days after it |
| `row_count` | `integer` null | 0-5,000 records after the header |
| `byte_size` | `integer` null | 1 to 2,097,152 |
| `report_revision` | `varchar(64)` null | `^[0-9a-f]{64}$` |
| `download_count` | `integer` | default 0, never negative |
| `last_downloaded_at` | `timestamptz` null | set when `download_count > 0` |

The state check: `pending` has no `stored_at`, revocation or content metadata; `ready` has `stored_at`, `row_count`, `byte_size` and `report_revision` and no revocation; `revoked` has `stored_at`, `revoked_at` and a reason; `discarded` has `revoked_at` and no `stored_at`. Keys and indexes: unique `(agency_id, client_id, id)`; `ix_report_exports_listing (agency_id, client_id, created_at, id)`; `ix_report_exports_open_connection (client_id, connection_id) WHERE status IN ('pending', 'ready')`; `ix_report_exports_expires_at (expires_at)`; `ix_report_exports_schedule_id (schedule_id) WHERE schedule_id IS NOT NULL`.

`pending` and `discarded` are internal: a `pending` row reserves a place among the 50 while its export is built, and a `discarded` row is one that never became ready (its build failed, or it was revoked while it was built). Neither is ever listed, read or downloaded.

### 2.2 `report_export_contents`

One row per ready export: `export_id` (primary key), `agency_id`, `client_id`, `kek_id` (`varchar(32)`, `^[a-z0-9][a-z0-9-]{0,31}$`), `wrap_nonce` (12 bytes), `wrapped_dek` (48 bytes), `nonce` (12 bytes), `ciphertext` (17 bytes to 2 MiB plus 16), `alg` (`A256GCM-ENV-v1`), `aad_version` (1) and `created_at`. `(agency_id, client_id, export_id)` references `report_exports (agency_id, client_id, id)`. The row is deleted at revocation and at expiry.

### 2.3 `report_schedules`

| Column | Type | Rule |
|---|---|---|
| `id`, `agency_id`, `client_id` | `uuid` | `(agency_id, client_id)` references `client_workspaces`; unique `(agency_id, client_id, id)` |
| `name` | `varchar(100)` | not blank, no control character |
| `family` | `varchar(16)` | one of the six families |
| `parameters` | `jsonb` | normalized parameters without dates, a JSON object |
| `sale_values` | `boolean` | true only for `attribution` and `funnel` |
| `compare` | `boolean` | |
| `cadence` | `varchar(8)` | `daily`, `weekly` or `monthly` |
| `weekday` | `smallint` null | ISO weekday 1 (Monday) to 7, required exactly for `weekly` |
| `hour` | `smallint` | 0-23 |
| `time_zone` | `varchar(64)` | an IANA zone name, checked by the application |
| `status` | `varchar(8)` | `active` or `paused` |
| `pause_reason` | `varchar(24)` null | `manual`, `owner_access_lost` or `repeated_failures`; set exactly when paused |
| `owner_membership_id` | `uuid` | references `agency_memberships (agency_id, id)` |
| `next_run_at` | `timestamptz` null | required while active |
| `last_run_at` | `timestamptz` null | |
| `last_outcome` | `varchar(16)` null | `built` or `failed` |
| `last_error_code` | `varchar(32)` null | set exactly when the last outcome is `failed`; closed set in section 7 |
| `last_notified`, `last_skipped` | `integer` | default 0, never negative |
| `consecutive_failures` | `smallint` | 0-3 |
| `created_at`, `updated_at` | `timestamptz` | |

Indexes: `ix_report_schedules_due (next_run_at) WHERE status = 'active'` and `ix_report_schedules_client (agency_id, client_id, created_at)`.

### 2.4 `report_schedule_recipients`

`schedule_id`, `agency_id`, `client_id`, `membership_id` and `created_at`; primary key `(schedule_id, membership_id)`. `(agency_id, client_id, schedule_id)` references `report_schedules (agency_id, client_id, id)` `ON DELETE CASCADE`; `(agency_id, membership_id)` references `agency_memberships (agency_id, id)`. Index `(agency_id, membership_id)`.

### 2.5 `agency_branding`

`agency_id` (primary key, references `agencies`), `display_name` (`varchar(100)`, not blank, no control character), `accent_color` (`varchar(7)`, `^#[0-9A-F]{6}$`, stored in upper case), `logo` (`bytea` null, 67 bytes to 256 KiB), `logo_width` and `logo_height` (`smallint` null, 1-1024, null exactly when the logo is), `updated_at` and `updated_by_membership_id` (references `agency_memberships (agency_id, id)`).

### 2.6 Existing tables

- `mail_outbox.purpose` accepts `report_ready`.
- `audit_events.action` accepts `report_export.created`, `report_export.revoked`, `report_schedule.created`, `report_schedule.updated`, `report_schedule.deleted` and `branding.updated`; `resource_type` accepts `report_export`, `report_schedule` and `agency_branding`.

### 2.7 Grants

- **`tracking_app`:** `SELECT, INSERT` on the five tables. `UPDATE (status, revoked_at, revoked_reason, stored_at, row_count, byte_size, report_revision, download_count, last_downloaded_at)` on `report_exports`; it never deletes an export row. `DELETE` on `report_export_contents`. `UPDATE` of every column except the keys, `family`, `created_at` and the owner's agency and client on `report_schedules`, and `DELETE` on `report_schedules` and `report_schedule_recipients`. `UPDATE (display_name, accent_color, logo, logo_width, logo_height, updated_at, updated_by_membership_id)` on `agency_branding`.
- **`tracking_lifecycle`:** `SELECT (id, status, created_at, expires_at)` and `DELETE` on `report_exports`; `SELECT (export_id)` and `DELETE` on `report_export_contents`. Nothing else.

### 2.8 Data policy and downgrade

`app/data_policy.py` classifies every new column with five new classes: `report.export` (metadata), `report.export_content` (sealed file, high sensitivity), `report.schedule`, `report.recipient` (references only) and `branding.profile`. The export tables carry an approved row rule (D-095: content and row deleted 7 days after creation, content at once on revocation); schedules and recipients are deleted by managers or when a recipient leaves, otherwise kept with the client (017); branding is kept with the agency, whose purge belongs to 017-B.

The downgrade takes `ACCESS EXCLUSIVE` locks and refuses when any of the five tables has a row, an outbox row has the purpose `report_ready`, or an audit row has a new action or resource. Otherwise it revokes the grants, drops the tables and narrows the checks again.

## 3. Requests

### 3.1 Parameters

Each family has a parameter object with `extra` fields forbidden, the same names, values and defaults as its report route (section 1.1), and `compare` as `"previous"` or null. `metrics` is a JSON array of 1-25 names instead of the route's comma-separated text; its order is kept, as the route keeps it. The object is turned into the same `ReportQuery` as the route, and `ReportQuery.periods()` applies the same comparison and model-version rules. The stored `parameters` are `ReportQuery.normalized()` without `family`, `start` and `end`, with identifiers as text.

### 3.2 Export creation

`POST /agencies/{a}/clients/{c}/report-exports` takes one flat object discriminated by `family`: the family's parameter object plus `start` and `end` (dates). Example:

```json
{"family": "social", "connection_id": "…", "view": "daily", "start": "2026-11-01", "end": "2026-11-08", "compare": "previous", "metrics": ["reach", "views"]}
```

### 3.3 Schedule creation and change

`POST /agencies/{a}/clients/{c}/report-schedules` takes `name` (1-100 characters, no control character), `report` (the family's parameter object, without dates), `sale_values` (default false; true only for `attribution` and `funnel`), `cadence`, `weekday` (1-7, exactly for `weekly`), `hour` (0-23), `time_zone` (IANA name) and `recipients` (0-20 distinct membership IDs). `PATCH .../report-schedules/{id}` accepts any of these fields, except that `report` keeps its family, and `status` (`active` or `paused`). A change of timing, a resumption or a new report recomputes `next_run_at`; a resumption makes the resuming manager the owner and clears the failure count.

## 4. Visibility and download checks (D3, D6)

Every export route is for browser sessions (`BrowserDep`); a service key of either kind is refused before any lookup. For an actor in agency `a` and client `c`:

1. `resolve_scope(user, a, c, "client:read")` must succeed, and `finance` is whether `resolve_scope(user, a, c, "finance:read")` succeeds. Both are read again at every request.
2. The visible exports are those of `(a, c)` with status `ready` or `revoked`, without `includes_financials` unless `finance` holds, and, for a client viewer, only those whose `requested_by_membership_id` is the viewer's membership or whose `schedule_id` is a schedule that lists the viewer as a recipient. Owners, Admins and Analysts see every export that passes the permission filter.
3. An export outside this set answers `403 access_denied`, the same answer as an unknown ID.
4. A download of a visible export that is revoked or expired answers `410 export_gone`. Otherwise `UPDATE report_exports SET download_count = download_count + 1, last_downloaded_at = now() WHERE id = :id AND agency_id = :a AND client_id = :c AND status = 'ready' AND expires_at > now()` must return the row (it serializes with a concurrent revocation; no row also answers `410 export_gone`). The content is then read and opened for exactly this export, agency and client, and returned as `text/csv; charset=utf-8` with `Content-Disposition: attachment; filename="report-<family>.csv"` and `Cache-Control: no-store`. A content that does not open answers `500 export_unreadable`.
5. Revocation (`DELETE`) is allowed to the creator and to Owners and Admins who can see the export; anyone else gets `403`.

## 5. Store-time lock and recheck (D7)

An export is built and stored in three steps:

1. **Reservation (its own short transaction).** Insert the `pending` row, then take the client's export lock `pg_advisory_xact_lock(16016, client_key)`, then count the client's unexpired rows that are `ready`, or `pending` and created in the last hour; more than 50 rolls back with `409 export_limit_reached`. Commit, which releases the lock.
2. **Build (outside any write transaction).** `build_report`, `report_csv` and `release_check` exactly as the direct CSV path, with fresh snapshots that begin after the reservation committed.
3. **Store.** In the request's own transaction (or the worker's transaction): insert the audit event first, then `UPDATE report_exports SET status = 'ready', … WHERE id = :id AND status = 'pending'`, then insert the sealed content. No row means the reservation was revoked during the build: the store is undone (savepoint), the reservation is discarded, and the export is built again once from step 1; a second failure answers `409 report_changed`. A build that fails marks its reservation `discarded`.

Every revoking path calls `revoke_exports(session, agency_id, client_id, reason, at, connection_id=None, export_id=None)` in its own transaction after its other effects. It takes the same export lock, then runs one statement `UPDATE report_exports SET status = CASE WHEN status = 'ready' THEN 'revoked' ELSE 'discarded' END, revoked_at = :at, revoked_reason = :reason WHERE <scope> AND status IN ('pending', 'ready') RETURNING id, status`, then deletes the content of the rows that became `revoked`. It returns the number of ready exports revoked.

Why no export escapes a revocation `R`:

| Order | What happens |
|---|---|
| `R` holds the export lock before the reservation takes it | The reservation waits until `R` commits, so the build's snapshots, which begin later, see `R`'s effects: an erased subject is gone, a disconnected connection is refused (`source_unavailable`), an archived client is refused (`access_denied`). |
| The reservation holds the lock before `R` | `R` waits until the reservation commits; its `UPDATE` then sees the `pending` row and discards it. The store finds no `pending` row and builds again after `R`, as above. |
| `R` runs while the store holds the row | `R`'s `UPDATE` waits for the store to commit, then rereads the row as `ready` and revokes it; its content is deleted in the same transaction. |
| `R` runs after the store | `R` revokes the `ready` export. |

The reservation inserts its row before taking the lock, so while it waits for the lock it holds only key-share locks on the client and membership rows, which no revoker needs; it never waits for anything once it holds the lock. The store writes the audit event before it locks the export row, so it waits for an agency row lock, if at all, before holding anything a revoker needs. The store runs in the request's transaction because that transaction already holds the user row `FOR UPDATE`, which the audit event's foreign key would otherwise wait for. No build ever runs while a lock is held, so a revoker waits at most for a reservation, and the 2-second privacy-lock timeout of the erasures and the 3-second connection timeout are not reached. The dedicated export lock is used instead of the client privacy lock because every event admission takes the privacy lock and the disconnection paths must not take it.

Scope of each call:

| Path | Call | Outcome |
|---|---|---|
| 004 `erase_subject` | every export of the client (reason `erasure`) | `report_exports: done` only when at least one ready export was revoked |
| 006 `_run_erasure` (an accepted erasure, also when a paused request is resolved) and `_decide_holds` with `erase` | every export of the client (reason `erasure`) | as above; `_decide_holds` adds the outcome to the request before it completes |
| `start_disconnect`, every cause | the exports of that connection (`connection_purged` for `operator_purged`, otherwise `disconnection`) | none |
| `update_client` to `archived` | every export of the client (`client_archived`) | none |
| `DELETE .../report-exports/{id}` | that export (`manual`) | audited `report_export.revoked` |

A closing agency needs no call: its members fail `resolve_scope` once the agency leaves `active`, and its exports expire 7 days after creation, before the 30-day grace period ends.

## 6. Periods (D8)

A schedule runs at local `hour:00` in its time zone: every day (`daily`), on its ISO weekday (`weekly`) or on the 1st (`monthly`). The run's instant on a local date `D` is `datetime.combine(D, time(hour), ZoneInfo(zone))` with `fold=0`, converted to UTC: an hour skipped by a daylight-saving change runs at the instant of the change, and an hour that occurs twice runs at its first occurrence. The period is computed from `D`:

| Cadence | Period (`start` inclusive, `end` exclusive) |
|---|---|
| `daily` | `D - 1 day` to `D` |
| `weekly` | `D - 7 days` to `D` |
| `monthly` | the 1st of the previous month to `D` (28-31 days) |

The report then reads those calendar dates on its source's own day (Instagram UTC, YouTube Pacific, advertising account time, revenue and credit UTC), with its partial, provisional and stale states, as today. Examples:

| Zone and rule | Run | Period |
|---|---|---|
| `Africa/Cairo`, daily 06:00 | 2026-11-27 04:00 UTC | 2026-11-26 to 2026-11-27 |
| `America/New_York`, daily 02:00, DST start 2026-03-08 | 2026-03-08 07:00 UTC (02:00 does not exist; 03:00 EDT) | 2026-03-07 to 2026-03-08 |
| `America/New_York`, daily 01:00, DST end 2026-11-01 | 2026-11-01 05:00 UTC (first 01:00, EDT) | 2026-10-31 to 2026-11-01 |
| `Asia/Tokyo`, weekly Monday 09:00 | 2026-11-30 00:00 UTC | 2026-11-23 to 2026-11-30 |
| `UTC`, monthly 00:00 | 2026-03-01 00:00 UTC | 2026-02-01 to 2026-03-01 (28 days) |
| `Pacific/Kiritimati` (UTC+14), monthly 08:00 | 2026-11-30 18:00 UTC (local 2026-12-01) | 2026-11-01 to 2026-12-01 |

`next_run_at` is the first run instant strictly after the current time when a schedule is created, resumed or retimed, and after each claimed run.

## 7. Worker (D10)

`python -m app.report_worker` runs `run_pass(engine, settings, registry, now, limit=25)` once and prints `{"due", "built", "notified", "skipped", "failed", "paused"}` as JSON counts only. For each of at most `limit` schedules:

1. **Claim (short transaction).** Select one schedule with `status = 'active'` and `next_run_at <= now`, joined to an active agency and an active client, ordered by `next_run_at, id`, `FOR UPDATE OF report_schedules SKIP LOCKED`. A suspended, closing or closed agency and an archived client are never claimed (RV15); their schedule runs once, for the latest period, after they become active again. Under the row lock: if the owner membership is no longer an active Owner or Admin of an active, verified user, pause it (`owner_access_lost`) and commit. Otherwise compute the latest run instant `L <= now` and its period, set `next_run_at` to the first run instant after `now` (a missed slot is never repeated), and commit. A second worker skips the locked row and, after the commit, no longer sees it as due.
2. **Build.** As the owner (`Principal("user", owner.user_id)`), with `finance` set to `sale_values` for `attribution` and `funnel`. The steps of section 5 run with `source = 'schedule'` and the owner as the requester; no audit event is written for a worker-built export. `report_changed`, and a reservation revoked during the build, are retried at most twice in the same run. An `access_denied` from the owner's scope pauses the schedule (`owner_access_lost`).
3. **Notify (in the store transaction).** For each recipient membership, active in the agency with an active, verified user: `resolve_scope` with the family's permission, plus `finance:read` when the export includes financials. A recipient who passes gets one `report_ready` outbox entry (section 8) that expires with the export; anyone else is skipped and counted.
4. **Outcome (short transaction).** `last_run_at`, `last_outcome`, `last_notified`, `last_skipped`; a failure records its closed code and adds one to `consecutive_failures`, and the third consecutive failure pauses the schedule (`repeated_failures`); a success resets the count.

Closed error codes: `report_changed`, `report_too_large`, `source_unavailable` (also `not_a_social_connection` and `not_a_spend_connection`), `source_not_ready` (`report_requires_ledger_upgrade`, `day_zone_unknown`), `not_configured` (no token keyring), `export_limit_reached`, `export_refused` and `build_failed` (anything else). The worker logs only these codes and counts.

## 8. Email (D9)

`queue_report_mail` adds an encrypted outbox row with purpose `report_ready` and `expires_at` equal to the export's expiry, delivered by the existing mail worker (local `.eml` files in development). Its content is fixed:

```text
Subject: Report ready: <schedule name>

<agency display name>

The scheduled report "<schedule name>" is ready.

Report: <kind>
Period: <start> to <last day>

Open it in the application:
<frontend_origin>/agencies/<agency_id>/clients/<client_id>/reports/exports/<export_id>

The report can be downloaded until <expiry date and time> UTC. You receive this message because you are a recipient of this schedule.
```

`<kind>` is `Social`, `Advertising spend`, `Revenue`, `Attribution`, `ROAS` or `Funnel`. The display name is the agency's branding profile name, or the agency's name without a profile. The email holds no figure, no client name and no token; the identifiers in the link are not secrets, and the application authorizes the reader again (section 4).

## 9. Branding (D11)

- `GET /agencies/{a}/branding`: any active member, client viewers included. Without a profile the answer is `{"configured": false}` with null fields, so a client viewer never learns the agency's internal name.
- `PUT /agencies/{a}/branding`: Owners and Admins; `display_name` (1-100 characters, no control character) and `accent_color` (`#RRGGBB`, stored in upper case). Audited `branding.updated`.
- `PUT /agencies/{a}/branding/logo`: Owners and Admins, a raw body with `Content-Type: image/png` (anything else, SVG included, answers `415 unsupported_media_type`), at most 256 KiB (route limit 262,144 bytes). A profile must exist (`409 branding_profile_required`). Audited.
- `DELETE /agencies/{a}/branding/logo`: Owners and Admins; audited.
- `GET /agencies/{a}/branding/logo`: any active member; `404 logo_not_found` without a logo; otherwise the stored bytes as `image/png` with `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'`, `Content-Disposition: inline; filename="logo.png"` and `Cache-Control: no-store`.

The PNG check (`422 invalid_png` on any failure) reads the bytes without decoding the image: the 8-byte signature; then chunks of length (at most the remaining bytes), a four-letter type and a CRC-32 that must match; `IHDR` first, 13 bytes long, with a width and a height of 1-1024, a valid bit depth for its color type (0: 1, 2, 4, 8, 16; 2, 4 and 6: 8, 16; 3: 1, 2, 4, 8), compression and filter method 0 and interlace 0 or 1; at least one `IDAT`; `IEND` last, empty, with nothing after it.

## 10. Routes and errors

Below `/agencies/{agency_id}/clients/{client_id}`: `POST` and `GET /report-exports`, `GET` and `DELETE /report-exports/{id}`, `GET /report-exports/{id}/download`, `POST` and `GET /report-schedules`, `GET`, `PATCH` and `DELETE /report-schedules/{id}`, and `DELETE /report-schedules/{id}/recipients/me`. Lists take `limit` (1-100, default 50) and `offset`, newest first. Schedule routes are for Owners and Admins; a recipient may read a schedule it receives and leave it.

New error codes: `export_limit_reached` (409), `export_gone` (410), `export_unreadable` (500), `not_configured` (503), `schedule_limit_reached` (409, more than 10 active schedules of a client), `invalid_recipient` (422), `invalid_time_zone` (422), `invalid_png` (422), `unsupported_media_type` (415), `branding_profile_required` (409) and `logo_not_found` (404). Report parameter errors keep the 016-A and 016-B codes.

## 11. Encryption

`app.privacy.token_secrets` gains `seal_bytes` and `open_bytes`, which `seal` and `open_secret` now call with UTF-8 text, so existing secrets are unchanged. An export's context is `SecretContext(agency_id, client_id, connector_id=export_id, secret_id=export_id, kind="report_export", version=1)`: the associated data binds the ciphertext to the export, the agency and the client, and the wrap to the KEK and the export. A missing token keyring refuses export creation, and a scheduled run, with `not_configured` before any row is written.

## 12. Routine details resolved here

1. The export lock (namespace 16016) and the `pending` and `discarded` states make D7 exact without holding a lock during a build (section 5); the entry review's "discarded and rebuilt" is kept.
2. `metrics` is a JSON array in requests (section 3.1).
3. A worker-built export and an automatic revocation write no audit event; the export row records its source, its schedule and its revocation reason, and an erasure records `report_exports: done`.
4. `_decide_holds` with `erase` also revokes, since it deletes events that an export built in between could count.
5. `sale_values` is a schedule choice only for `attribution` and `funnel`; the other families' permissions already decide it. A manual export of those two families includes sale values exactly when the creator holds `finance:read`, as the direct CSV does.
6. Recipients are listed only to managers; a recipient sees whether it receives the schedule.
7. The lifecycle runner deletes expired rows of every state, `discarded` rows and `pending` rows older than one hour, content first, and reports these counts only when they are not zero.
8. Export lifetime setting: `TRACKING_REPORT_EXPORT_LIFETIME_DAYS`, default and maximum 7.

## 13. Test inventory

| Case | Tests |
|---|---|
| RV01 | `test_report_exports.py`: `test_rv01_every_family_exports`, `test_rv01_parameters_and_bounds`, `test_rv01_client_viewer_exports_what_it_reads`, `test_rv01_keys_and_foreign_scopes_refused`, `test_rv01_fifty_unexpired_exports`, `test_rv01_missing_keyring_not_configured` |
| RV02 | `test_report_delivery_contract.py`: `test_rv02_seal_is_bound_to_export_agency_and_client`; `test_report_exports.py`: `test_rv02_no_plaintext_stored`, `test_rv02_copied_ciphertext_does_not_open` |
| RV03 | `test_report_exports.py`: `test_rv03_download_matches_direct_csv`, `test_rv03_scope_resolved_again`, `test_rv03_sale_values_need_finance`, `test_rv03_revoked_or_expired_export_gone` |
| RV04 | `test_report_exports.py`: `test_rv04_visibility` |
| RV05 | `test_report_exports.py`: `test_rv05_manual_revocation` |
| RV06 | `test_report_revocation.py`: `test_rv06_subject_erasure_revokes_earlier_exports`, `test_rv06_person_erasure_revokes_earlier_exports`, `test_rv06_held_event_erasure_revokes`, `test_rv06_reservation_during_erasure_is_rebuilt`, `test_rv06_erasure_waits_for_reservation` |
| RV07 | `test_report_revocation.py`: `test_rv07_disconnection_revokes_its_exports_only`, `test_rv07_every_disconnection_cause_revokes`, `test_rv07_purge_revokes` |
| RV08 | `test_report_revocation.py`: `test_rv08_archival_revokes`, `test_rv08_closing_agency_exports_unreachable` |
| RV09 | `test_report_exports.py`: `test_rv09_lifecycle_deletes_expired_exports` |
| RV10 | `test_report_schedules.py`: `test_rv10_schedule_validation`, `test_rv10_managers_only`, `test_rv10_ten_active_schedules`, `test_rv10_recipients` |
| RV11 | `test_report_delivery_contract.py`: `test_rv11_periods`, `test_rv11_daylight_saving_runs`, `test_rv11_month_ends` |
| RV12 | `test_report_schedules.py`: `test_rv12_due_schedule_runs_once_under_two_workers`, `test_rv12_next_slot_and_missed_slot`, `test_rv12_pass_is_bounded` |
| RV13 | `test_report_schedules.py`: `test_rv13_owner_without_access_pauses`, `test_rv13_recipients_without_access_skipped` |
| RV14 | `test_report_schedules.py`: `test_rv14_report_ready_email`; `test_report_delivery_contract.py`: `test_rv14_email_text` |
| RV15 | `test_report_schedules.py`: `test_rv15_stop_states_get_no_run` |
| RV16 | `test_report_schedules.py`: `test_rv16_failures` |
| RV17 | `test_report_branding.py`: `test_rv17_profile`, `test_rv17_logo`; `test_report_delivery_contract.py`: `test_rv17_png_checks` |
| RV18 | `test_report_delivery_migration.py`: `test_rv18_upgrade_from_populated_0031`, `test_rv18_grants`, `test_rv18_downgrade_refuses_stored_rows`; the existing metadata comparison (`test_tenancy.py`) and data policy tests |
| RV19 | `test_report_branding.py`: `test_rv19_isolation`; `test_report_schedules.py`: `test_rv19_no_data_in_logs_or_output` |
| RV20 | every existing suite; `test_report_exports.py`: `test_rv03_download_matches_direct_csv`; the OpenAPI snapshot compared with `main` (additions only) |
