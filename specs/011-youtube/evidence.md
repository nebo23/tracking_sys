# Spec 011 evidence

## 011-B preparation (2026-11-18)

Scope: D-058, which approves entry review decisions D1-D14, D16 and D17 and runs 011-B before 011-A, with D15 decided by D-057. This section covers preparation only.

- The [feasibility checklist](feasibility-checklist.md) lists the owner's steps and questions F1-F14.
- The read-only tool `backend/app/youtube_feasibility.py` uses only the standard library, python-dotenv and the already pinned `tzdata`.
- No dependency was added, no live Google call was made, and native `tracking_sys` was not touched.

| Command (from `backend/`, project `.venv`) | Result |
|---|---|
| `python -m pytest -q tests/test_youtube_feasibility.py` | **15 passed**, offline with a fake transport (see the list below). |
| `python -m pytest -m "not integration" -q` | **563 passed**, 328 deselected. |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 142 files formatted. |

The 15 tests cover:

- the authorization request: read-only offline consent, and PKCE only on request;
- the Web client and loopback redirect checks, state checking, and closed consent-error codes;
- the loopback receiver on 127.0.0.1, which ignores other paths and logs nothing;
- redaction: no token, code, secret, channel or video ID, or metric value in the console or the evidence;
- the single-metric fallback when the combined day report is refused;
- the analytics-only consent;
- the stop on quota answers and the call budget;
- the token and refresh records;
- storing and forgetting tokens in the environment file;
- the refused consent and the wrong PKCE verifier;
- `revoke-test` with its confirmation;
- keyed day digests that show changed days on a later probe.

The test fixture also models Google's documented account-wide revocation (entry review G-1), so the expected `revoke-test` record is "slot b does not survive". The live answer is F12.

### Console setup recorded before the run

See [entry review section 10](entry-review.md#10-owner-decisions):

- `connectapp` is in Testing.
- `youtube.readonly` is classified sensitive and `yt-analytics.readonly` non-sensitive.
- A separate Web client with the loopback callback exists.
- The client credentials are in the ignored `.env`, used at the owner's instruction, and rotating the secret is a follow-up.

## 011-B first run (2026-11-18)

Scope: D-058 decision D16.

- **Consent.** The owner completed the consent with the test channel's Google account at 2026-11-17 23:57 UTC (2026-11-18 local time). Google redirected to the loopback callback, which carried `state`, `iss` (`https://accounts.google.com`) and `code`.
- **Read-only calls.** The tool stored the refresh token in the ignored `.env` without showing it. It then made only read-only calls: the first probe (20 calls), one refresh, and two probes after the tool correction below (24 and 26 calls). Nothing was throttled, no quota error occurred, and nothing on the channel was changed.
- **Evidence files.** The redacted files stay in the ignored `local-data/youtube-feasibility/` folder.

**Tool correction during the run.** The first probe's one-day history reads cannot tell a day without views from a day without data, and its month report was refused. The tool now reads 30-day windows at the same depths, the month report with first-of-month dates, and the day rows of the earliest month with views. It also runs a density check: the recent window with `views` only, and a window 365 days back with the whole catalog. It also sends a 50-ID control next to the 51-ID request. After the change, `tests/test_youtube_feasibility.py` passes (15), `python -m pytest -m "not integration" -q` passes (563), and ruff is clean.

| Question | Result |
|---|---|
| F1 token answer | The code exchange returned `access_token`, `expires_in` (3,599), `refresh_token`, `refresh_token_expires_in`, `scope` and `token_type` `Bearer`, with both requested scopes granted. `refresh_token_expires_in` was 604,799 seconds, which is the documented 7-day Testing limit. Google reported it in the answer even though the OAuth page describes the field only for time-based access. Partial consent is not yet checked. |
| F3 refresh | A refresh two minutes later succeeded and returned no new refresh token. It reported `refresh_token_expires_in` 604,693, so the 7-day limit counts from the consent and refreshes do not renew it. The failure after 7 days is checked after 2026-11-24 23:57 UTC. |
| F4 channel | `channels.list?mine=true` returned one channel. `viewCount`, `subscriberCount` and `videoCount` came as strings, `hiddenSubscriberCount` was false, and the channel had an uploads playlist and privacy status `public`. How the channel was chosen at consent is for the owner to confirm. |
| F5 inventory | The uploads playlist listed 26 videos in one page: 22 private, 1 unlisted and 3 public. `videoCount` equals the public count, so it counts public videos only. `videos.list` returned all 26, private ones included, and the `fields` filter kept titles out. All five statistics fields, including `dislikeCount` and `favoriteCount`, were present for every video, and all durations were ISO 8601; one video was an upcoming live broadcast. The same ID repeated 50 times was accepted (50 items), and 51 times was refused with `invalidFilters` (400), so the limit is 50 IDs per call. `videos:batchGetStats` with `id` returned all 26 items, with top-level keys `etag`, `items` and `kind` and no `summary`. |
| F8 day report | The whole 13-metric catalog was accepted in one `day` query. Columns are INTEGER except `averageViewPercentage`, which is FLOAT. At 15:57 Pacific on 2026-11-17 the last day returned was 2026-11-15, two days before today. Day rows are sparse: which days appear depends on the metrics requested and the underlying data. The recent 31-day window returned 29 rows with the catalog (9 of them all zero) but 20 with `views` only, and a 30-day window ending 365 days earlier returned 12 rows with the catalog. Three reads within five minutes returned identical rows; the next-day comparison is pending. |
| F9 video reports | `dimensions=video` with a filter of the 26 IDs accepted the whole catalog and returned 24 rows; 2 videos had no data. `video,creatorContentType` and the top-200 report sorted by views also worked. `creatorContentType` values come back as `shorts`, `videoOnDemand` and `creatorContentTypeUnspecified`, not as the documented `SHORTS`, `VIDEO_ON_DEMAND` and `UNSPECIFIED`. |
| F10 history | A month report needs both dates on the first day of a month; an end date on the last day was refused with "does not align to chosen date dimension". From 2008-07 the report returned all 220 months, zero months included. 52 months had views, the earliest 82 months back (about 6.8 years), and that month returned day rows. Day-level history therefore reaches at least 82 months for this channel, beyond the 730-day backfill of D9. A total from 2005-02-14 to today was accepted. |
| F6 analytics scope alone | A second consent, at 2026-11-18 00:04 UTC, requested only `yt-analytics.readonly`. It was granted alone, again with a 7-day refresh token. With that token, `channels.list` was refused with 403 `PERMISSION_DENIED` (reason `insufficientPermissions`, "insufficient authentication scopes"). Every Analytics read worked: the day report, the history windows, the monthly totals, the top-videos report and the content-type report. The banner of the `reports.query` page, which says `youtube.readonly` is now required, was therefore not enforced for these reads on that date. The video-filter report was not tried, because the video IDs come from the Data API. |
| F14 errors | An invalid token got 401 `UNAUTHENTICATED` with reason `authError` from both APIs. Missing scopes got 403 `PERMISSION_DENIED` with reason `insufficientPermissions` (F6). |
| F2, F7, F11, F12, F13 | Not yet checked. |

### Consequences for 011-A

| Area | Assumption so far | Evidence | Proposed change |
|---|---|---|---|
| Completeness (D9) | `complete_through` moves to the end of the last day returned | Day rows are sparse, so a channel without activity on its latest available days returns an earlier last row, and the last row cannot show availability. | **Needs owner approval as a D9 amendment.** `complete_through` follows the documented latency: it is the end of the last Pacific day that ended at least 72 hours before the read. A day of a read window without a row is `missing` with reason `not_returned`, never 0. The 4-day re-read and the provisional marking stay. |
| Product types (D8) | `creatorContentType` returns `SHORTS` and similar names | Values come back in lowerCamelCase | The adapter maps `shorts`, `videoOnDemand` and `creatorContentTypeUnspecified` to `SHORTS`, `VIDEO_ON_DEMAND` and `UNSPECIFIED`. Values not yet observed (live streams, stories) map to `UNSPECIFIED` until seen. This stays within D8. |
| Refresh token (D4) | Its lifetime is unknown | Google reports `refresh_token_expires_in` at consent and on refresh (7 days in Testing) and does not rotate the token | The grant keeps the reported expiry, so a connection created under Testing shows when it needs a new consent. No rotation handling is needed. |
| Inventory (D7, D11) | The inventory covers public counters | Private and unlisted uploads are listed and returned with statistics to the owner, while `videoCount` counts public videos only | The inventory covers every upload with its privacy status attribute, and no total is derived from `videoCount`. |
| Batches (D10) | 50 IDs per call | 51 IDs are refused with `invalidFilters` | 50 IDs per `videos.list` and `batchGetStats` call. |
| History (D9, D11) | Backfill up to 730 days unless the API offers less | Day rows reach at least 82 months back | No change: 730 days remains the product limit. |
| Errors | Assumed from documentation | Invalid token: 401 `authError`. Missing scope: 403 `insufficientPermissions`. Too many IDs: 400 `invalidFilters` | 401 maps to unauthorized (one refresh, then reconnect). 403 `insufficientPermissions` maps to forbidden for the stream that needs the scope. 400 maps to permanent. |
| Scopes (D2) | Both scopes are needed | The Analytics streams work with `yt-analytics.readonly` alone, and the Data API streams need `youtube.readonly` | No change: D2 installs a connection only with both scopes, because the inventory and the snapshot need the Data API. Installing with the Analytics streams only remains the documented alternative. |

Remaining in 011-B (owner steps of the [checklist](feasibility-checklist.md)): partial consent (F1), PKCE (F2), the console quota readings (F7, F11), the next-day stability probe (F8), the 7-day refresh check (F3), and the access-ending checks F12 and F13 last, then `forget`.

## 011-B review corrections (2026-11-18)

Scope: D-059, within D-058, from the [review corrections prompt](review-corrections-prompt.md).

- **Head at the start.** The independent review covered `bb3263e`. When the corrections started, the branch head was `7d66822`, which adds two later commits: `39c894f`, the first-run evidence with the history-probe correction, and `7d66822`, the F6 evidence. Both were kept, and no owner change was found. The corrections apply to the current tool. Each regression was run against temporary checkouts of `bb3263e` and of `7d66822`, outside the repository and removed afterwards.
- **Official page re-read.** The `videos:batchGetStats` reference was re-read on 2026-11-18. It documents `GET https://www.googleapis.com/youtube/v3/videos:batchGetStats` with a required comma-separated `id`, a required `part` (`contentDetails`, `id`, `snippet`, `statistics`) and no stated ID limit. The first run's call without `part` was nevertheless answered with 200, as recorded above. The tool now sends `part`.

| Finding | Correction | Regression (`tests/test_youtube_feasibility.py`) | At `bb3263e` and `7d66822` |
|---|---|---|---|
| R011-01 | The filtered video reports are sent with `sort=-views` and `maxResults=200`, the fallback included, and an unsorted `video_filter_unsorted` variant records whether these are required. | `test_r011_01_video_reports_send_sort_and_max_results` | fails: the filtered report is refused (`error`) |
| R011-02 | `videos.list` and `videos:batchGetStats` each get a 50-ID control and a 51-ID request, with IDs distinct where the uploads allow. Both record `ids_sent`, `distinct_ids` and `conclusive`. | `test_r011_02_id_limits_use_distinct_ids_and_say_whether_they_are_conclusive` | fails: no distinct-ID check (`KeyError`) |
| R011-03 | `revoke-test` records `wait_seconds`, and a surviving slot b is marked `provisional` in the evidence and the printed message, with slot b kept for `check-access --slot b` at least 30 minutes later. | `test_r011_03_a_surviving_slot_b_is_provisional_until_checked_again` | fails: no `wait_seconds` or conclusion |
| R011-04 | `Probe.get` catches a missing answer, stops with `no_answer`, and the probe evidence is still written, for `probe` and for `authorize`. | `test_r011_04_a_probe_without_an_answer_still_writes_what_it_read[probe]` and `[authorize]` | fail: exit code 1 and no evidence |
| R011-05 | The public items are compared with `videoCount` only when every upload was read in one batch. Otherwise the result is `null`, with the reason in `public_items_comparison_skipped`. | `test_r011_05_public_items_are_compared_only_when_the_inventory_fits_one_batch` | fails: 60 public uploads report `false` |
| R011-06 | `--max-calls` is also accepted after `authorize` and `probe` (`argparse.SUPPRESS` default), and the module docstring and checklist document it. | `test_r011_06_max_calls_is_accepted_after_the_command` | fails: `SystemExit: 2` |
| R011-07 | The plan's slice 2 names the existing project `connectapp` (D-057). | Documentation | n/a |
| R011-08 | Checklist Part D step 8 deletes `local-data\youtube-feasibility` once this summary is recorded. | Documentation | n/a |
| R011-09 | The receiver's server class leaves `SO_REUSEADDR` off on Windows and sets `SO_EXCLUSIVEADDRUSE`. | `test_r011_09_the_receiver_refuses_a_port_that_is_in_use`, `test_r011_09_the_receiver_does_not_reuse_addresses_on_windows` | fail: a second receiver bound the busy port, and `SO_REUSEADDR` was 1 |

| Command (from `backend/`, project `.venv`) | Result |
|---|---|
| `python -m pytest -q tests/test_youtube_feasibility.py` | **24 passed** (15 earlier tests, some updated to the corrected answers, and 9 regressions) |
| The 9 regressions (`-k r011`) against temporary checkouts of `bb3263e` and of `7d66822`, on Windows 11 with Python 3.12.4 | **9 failed** at each, for the reasons in the table |
| The same run on Linux, by the independent review of `c2a2cd4` | **8 failed and 1 passed** at each revision. `test_r011_09_the_receiver_refuses_a_port_that_is_in_use` passes there, because Linux refuses a second bind of a listening port even with `SO_REUSEADDR`; the bug and its regression are Windows-specific (R011-11). |
| `python -m pytest -m "not integration" -q` | **572 passed**, 328 deselected |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 142 files formatted |

The integration suite was not run, because these corrections change no shared code, migration or setting. No live Google call was made for the corrections.

### Corrected probe (2026-11-18 11:11 UTC)

One read-only `probe` with the corrected tool (27 calls, not throttled) recorded the following.

| Question | Result |
|---|---|
| F5 ID limits | `videos.list` accepted 50 IDs (26 distinct, repeated in order) and returned 50 items, so repeated IDs are not merged. It refused 51 with `invalidFilters` (400), a conclusive refusal. `videos:batchGetStats` with `part=statistics` returned all 26 videos. It also accepted 50 IDs (50 items) and refused 51 with 400 `INVALID_ARGUMENT` (`badRequest`). Both methods therefore take at most 50 IDs per call (D10). |
| F5 comparison | All 26 uploads were read in one batch, and the public items equal `videoCount`. |
| F9 sorting | The filtered video reports with `sort=-views` and `maxResults=200` returned 24 rows, and so did the unsorted `video_filter_unsorted` variant: a filtered video report needs neither `sort` nor `maxResults`. |
| F8 latency | At 03:11 Pacific on 2026-11-18, the last day returned was still 2026-11-15, three days earlier. The 28 days compared with the probe of eleven hours before were unchanged. |

## Corrections R011-10 to R011-12 and D-060 (2026-11-18)

Scope: the [completion prompt](completion-prompt.md), recorded as D-060, reviewed at `c2a2cd4`. D-060 also amends D9 as proposed above: `complete_through` follows the 72-hour latency, and omitted days are `not_returned`, never 0.

| Finding | Correction | Regression | At `c2a2cd4` |
|---|---|---|---|
| R011-10 | The combined day report's failure is recorded before any fallback, and no fallback runs once the probe has stopped (also applied to the video-report fallback). | `test_r011_10_a_day_report_without_an_answer_keeps_its_label_and_sends_no_fallback` | fails: `combined` was `not_requested` instead of `no_answer` (Windows) |
| R011-11 | The platform of the regression run is named above, with the Linux result of the review. | Documentation | n/a |
| R011-12 | The status lines of `spec.md`, `specs/README.md` and `docs/planning/review-next.md` name D-059, D-060 and the partial 011-B run. | Documentation | n/a |

| Command (from `backend/`, project `.venv`) | Result |
|---|---|
| `python -m pytest -q tests/test_youtube_feasibility.py` | **25 passed** |
| The R011-10 regression against a temporary checkout of `c2a2cd4` | **1 failed** |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed |
| `python -m pytest -m "not integration" -q` | **573 passed**, 328 deselected |

## 011-B Phase 1 steps (2026-11-18)

Under D-060, in the order of the [completion prompt](completion-prompt.md). Every consent used slot b; slot a, which F3 needs, was not touched.

| Question | Result |
|---|---|
| F1 partial consent | Two consents at 11:35 and 11:41 UTC requested both scopes with `prompt=consent`. On the second, the consent screen showed a checkbox for each scope, and the owner unticked one. Google still granted both: the `scope` field of the answer listed `youtube.readonly` and `yt-analytics.readonly`, with a new refresh token and `refresh_token_expires_in` 604,799. For an account that has already granted both scopes to the project, unticking one on a repeated consent does not narrow the grant, and the answer reports the account's whole grant. A first consent with a scope cleared (no earlier grant) is still unchecked. It can only be tried after access is revoked, so it moves to Phase 4, after F3, under the access rule. The F6 consent showed that a grant can carry one scope only. |
| F2 PKCE | At 11:45 UTC a consent with an `S256` code challenge was exchanged with the matching verifier: 200, both scopes and a refresh token (slot b). A second consent at 11:45 was exchanged with a different verifier and refused with 400 `invalid_grant` ("Invalid code verifier."), and nothing was stored. The Web client therefore accepts and enforces PKCE `S256`, although the web server guide (G-1) does not document it. The earlier attempt of 2026-11-18 00:05 UTC timed out because the consent was not completed. |
| F7 and F11 request counts (in part) | At 14:14 UTC the `connectapp` API dashboard counted 74 YouTube Analytics API requests (1% errors) and 25 YouTube Data API v3 requests (20% errors). The tool's own counts over the five probes are 74 Analytics calls, one of them the month report refused in the first probe, and 26 Data API calls, six of them refused (the five 51-ID requests and the 403 of the F6 probe). The Analytics count matches call for call: each `reports.query` is one request of the method `google.youtube.analytics.v2.TargetedQueriesService.Query`, and the one error is the refused month report (1 of 74, shown as 1.35% on the method page). The ten calls with an invalid token (two per probe) are in neither count. The Data API count is one lower than the tool's, with 5 errors where the tool saw 6. The Data API metrics page accounts for the difference: its 30-day traffic by response code has only 200 and 400 series, so the 403 `insufficientPermissions` call of the F6 probe does not appear. The page lists four methods: `youtube.api.v3.V3DataChannelService.List`, `V3DataPlaylistItemService.List`, `V3DataVideoService.List` and `V3DataVideoService.BatchGetStats`, so `batchGetStats` counts in the Data API as a method of its own. In the latest interval, which holds the 11:12 probe, the error rate was 33.33% for `videos.list` and for `batchGetStats` (the 51-ID request of three calls each) and 0 for the other two methods, and 200 and 400 stood at 3 to 1 (six accepted and two refused calls). The methods table gives the totals: `channels.list` 4 requests (0% errors), `playlistItems.list` 4 (0%), `batchGetStats` 6 (16.67%, one refused) and `videos.list` 11 (36.36%, four refused). These are exactly the tool's calls without the 403. |
| F7 and F11 quotas | At about 14:20 UTC the Quotas and system limits tabs showed the following, every row marked adjustable. YouTube Data API v3: Queries per day 10,000 (current usage 5), Video Batch Get Stats Queries per day 10,000 (3), Search Queries per day and per minute 100 each, and Video Uploads per day and per minute 100 each (0 for all four). Further rows, the first with the value 1,800,000, were below the screenshot. YouTube Analytics API: Queries per day 100,000 (17), Queries per minute 720 (0) and Queries per minute per user 720 (no usage shown). The current Pacific day (from 08:00 UTC) holds only the 11:12 probe: 17 Analytics calls and 8 Data API calls (`channels.list` 1, `playlistItems.list` 1, `videos.list` 3 and `batchGetStats` 3, the 51-ID call of each of the last two refused with 400). Both usage figures match that probe alone, while a UTC day would also hold the probes of 00:00 to 00:05 UTC, so both quota days follow Pacific time. Each Analytics query records one unit. The Data API's 5 units match one unit for each `channels.list`, `playlistItems.list` and `videos.list` call, the refused 51-ID call included. `batchGetStats` records nothing in the general bucket: its three calls, the refused one included, record one each in its own bucket. No limit was reached, so `quotaExceeded` and rate-limit answers were not observed, and their shape stays as documented (YT-5). |
| F4 channel choice | The owner reports that at the first consent Google showed its account chooser and the owner chose the test channel's Google account. No separate channel step was reported, and `channels.list?mine=true` then returned one channel (first run). How an account with several channels or brand-account channels selects one was not observable with this account, and a hidden subscriber count was not seen (`hiddenSubscriberCount` was false). |

Consequence: none for D2. The adapter installs a connection only when the `scope` field of the answer holds both scopes, which follows what Google actually grants, whatever was ticked on the screen. Under D3, the adapters declare PKCE `S256` (`Capability.pkce = "S256"`), with the single-use state, the session binding and the server-side exchange unchanged.

Consequence of F7 and F11, within D10: the runtime keeps daily buckets on the Pacific day: the Data API general bucket (D10 cap of 9,000 of the 10,000 units) and the Analytics API (100,000 queries), for which the 011-A design note sets the cap that D10 derives from the console value with the same 90% margin (90,000). The `batchGetStats` bucket (10,000 queries) is declared only if a stream uses that method; the 011-A streams do not, because `videos.list` returns the statistics with the attributes. The Analytics limit of 720 queries per minute is far above the 30 requests per connection per day of D10, but a scheduler that starts many connections at once must stay under it. Refused requests are charged, which supports refreshing the token before a call (D4) and checking the ID count before sending (D10). The per-video daily series of the D7 alternative can now be sized: at one request per video per day, the 90,000 cap covers about 180 channels of 500 videos. D7 stays as approved.

Consequence of F4: the connection's external account is the one channel that `channels.list?mine=true` returns for the account chosen at consent. The 011-A design note proposes that a connection is installed only when exactly one channel comes back; none or several refuse the installation with a stated reason instead of a guess. The several-channel case stays untested until an account with a brand-account channel is available.

## 011-A: YouTube-shaped synthetic adapter (2026-11-18)

Scope: D-058 (D2 to D14) and D-060 (D9 as amended), as planned in the [design note](design-011a.md). At the owner's request of 2026-11-18, 011-A started before the next-day probe (F8). F8 is recorded when it runs, and any change to D9 that it requires goes to the owner first. No live Google call was made, and no dependency was added. Migration `0015` ran only on the disposable PostgreSQL 18 service (Compose project `tracking-system-foundation-test` on 127.0.0.1:55433), never on the owner's `tracking_sys`.

**Built:**
- **Adapter.** `app/connectors/synthetic_youtube.py`, which reproduces the 011-B answers.
- **Runtime extensions.** In `contracts.py`, `services/connectors.py`, `connector_coverage.py` and `lifecycle.py`:
  - required scopes and adapter refusals;
  - account-wide grants;
  - refresh ahead of expiry, the 7-day authorization check and the 14-day grace purge;
  - quota buckets on the Pacific day, with deferral on `quotaExceeded`;
  - local-day overlaps;
  - allow-listed attributes and label refresh, cleared after 30 days;
  - the inventory sweep with deletion confirmation;
  - retention per provider;
  - the non-additive marker and definition-change dates;
  - the D13 approval.
- **Migration.** `0015_youtube_runtime`.
- **API fields.** The OpenAPI snapshot was regenerated for them.
- **Data policy.** Rules recorded under D-058.
- **Logged event.** `connector_grant_kept_shared` (no fields).

Existing tests were updated only for the new fields and the larger registry:
- `test_connectors.py`: the connection view has `grant_expires_at`.
- `test_connector_coverage.py`: the cost block has `buckets`.
- `test_connector_contracts.py` and `test_connector_instagram_login.py`: the registry includes `synthetic_youtube`.
- `test_data_policy.py`: the D-058 rules.

| Entry review section 6 case | Test (`tests/integration/test_connector_youtube.py`, unless stated) |
|---|---|
| Authorization parameters (offline access, consent, PKCE `S256`) and the D13 approval | `test_011a_authorization_parameters_and_agent_approval` |
| Partial consent refused without harming other connections; the F1 union grant; F4 refusals | `test_011a_partial_consent_and_unavailable_accounts_are_refused` |
| Account-wide grants: two clients, the shared disconnect, reconnect without revocation, a refused duplicate connect, the last connection revoking | `test_011a_account_wide_grants_are_revoked_only_by_the_last_connection` |
| Refresh ahead of expiry with no refused read; the 7-day check; the purge after 14 days in `reconnect_required` | `test_011a_refresh_ahead_authorization_check_and_grace_purge` |
| The Pacific quota day, a `quotaExceeded` deferral that is neither a retry nor a failure, separate buckets, the provider cap | `test_011a_quota_buckets_follow_the_pacific_day_and_quota_answers_defer` |
| Pacific days across the 25-hour 2026-11-01, `complete_through` at the 72-hour bound, provisional days, `not_returned` days, no zero filling, the local-day overlap and re-read | `test_011a_pacific_days_completeness_and_days_without_rows` |
| Product types, `not_returned` statistics, rounded counts, the non-additive marker, attributes allow-listed, a deleted video purged from every stream after confirmation, a hidden video kept | `test_011a_videos_attributes_product_types_and_deleted_videos` |
| Attributes and labels cleared after 30 days without refresh, the label refreshed again, 730-day and shorter provider retention, lifecycle privileges | `test_011a_lifecycle_clears_attributes_labels_and_keeps_provider_retention` |
| Error mapping (403 forbidden per stream, 400 permanent, 401 with one refresh, a second 401) and tenant isolation | `test_011a_error_mapping_and_tenant_isolation` |
| Migration `0015` downgrade refused with YouTube state | `test_011a_migration_downgrade_refuses_youtube_state` |
| Pure parts: Pacific days at both 2026 changes, the completeness bound, bucket days and resets, content types, rounded counts, the capability | `tests/test_connector_youtube_synthetic.py` (5 tests) |

| Command (from `backend/`, project `.venv`; database runs through the disposable service) | Result |
|---|---|
| `python -m pytest -m "not integration" -q` | **578 passed**, 338 deselected |
| `python -m pytest -m integration -q tests/integration/test_connector_youtube.py` | **10 passed** |
| `python -m pytest -m integration -q` (full integration suite) | **335 passed, 3 skipped**: the three browser journeys of `test_tracker_journey.py`, which need `TRACKING_RUN_BROWSER_TESTS=1` and are unrelated to connectors (skipped, not passed) |
| Migration `0015` | The suite upgrades to head (`0015_youtube_runtime`). `test_postgresql_migration_cycle_and_runtime_permissions` downgrades through `0015` to base and upgrades again on the empty database. The downgrade to `0014` is refused while a `synthetic_youtube` connection exists. After the `budget_exhausted` usage outcome was added to `0015`, the empty disposable database was downgraded to `0014` and upgraded again. |
| OpenAPI snapshot | Regenerated; `tests/test_contract.py` passes |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed |
| Mutation check: each safeguard disabled in turn, the YouTube tests rerun, the source restored byte for byte (SHA-256 compared) | **All 14 caught**, each by its own test: the scope check, the shared-revocation rule, the reconnect without revocation, refresh ahead, the 7-day check, the grace purge, the bucket reservation, the Pacific period, the quota deferral, the local-day overlap, the attribute allow-list, the deletion confirmation, the approval check (2 failures) and the lifecycle clearing |

**Limits and follow-ups:**
- **Synthetic only.** The adapter reproduces the documented shapes and the 011-B answers; the live adapter is 011-C.
- **Disconnect race.** A disconnect that races a new connect of the same channel can revoke the new grant, because Google revokes every token of the account at once. That connection then fails its first refresh and requires reconnection.
- **`batchGetStats` bucket.** Not declared, because no stream uses that method.
- **Large channels.** A channel with more than about 1,450 videos exceeds the 30 Analytics requests a day of D10, so its `video_totals` run continues from its cursor the next Pacific day.
- **Not in this slice.** The D13 wording and any frontend work wait for the owner's brief (D-039). The disclosure version is the development identifier `dev-agent-approval-1`.
