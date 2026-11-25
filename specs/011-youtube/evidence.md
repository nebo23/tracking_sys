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
- **Large channels.** With the synthetic adapter's costs (1 Analytics request per `video_totals` page), a channel with more than about 1,450 videos exceeds the 30 Analytics requests a day of D10, so its `video_totals` run continues from its cursor the next Pacific day. The live adapter reads two reports per page, so its limit is about 700 videos a day (corrected by D-061, R011-17; see the [capacity](#capacity-of-the-live-adapter-r011-17)).
- **Not in this slice.** The D13 wording and any frontend work wait for the owner's brief (D-039). The disclosure version is the development identifier `dev-agent-approval-1`.

## 011-C: Live YouTube adapter (2026-11-18)

Scope: Phase 3 of the [completion prompt](completion-prompt.md), under D-058 and D-060.
- **Testing.** The tests run the adapter against `tests/youtube_api.py`, an in-memory Google API built from the 011-B answers. No test contacts Google, and no dependency was added.
- **Database.** Migration `0016` ran only on the disposable PostgreSQL 18 service (Compose project `tracking-system-foundation-test` on 127.0.0.1:55433), never on the owner's `tracking_sys`.
- **Live check (step 8):** run with the owner on 2026-11-18; see the [live check](#live-check-with-the-owners-test-channel-2026-11-18). It found the `video_totals` defect corrected there.
- **Secret rotation (step 7):** deferred by the owner on 2026-11-18.
- **After F3, under the access rule:** the live disconnect check.

### Policy rows re-verified (2026-11-18)

On 2026-11-18 the pages behind the `youtube.authorized_analytics` and `youtube.other_data` rows were read again (entry review sections 1.5 and 4.5).

| Source | Reading | Result |
|---|---|---|
| YouTube API Services Developer Policies (P-1, S-72) | III.D.2 verbatim. The fetched page was cut at about 40% of its length. III.E.2, III.E.3, III.E.4.b, III.E.4.c, III.E.4.g and III.E.4.h therefore come from the fetch tool's summary of the remainder, with short quotes. No revision date is shown. | Unchanged:<br>- **Revocation in the client:** revoke "right away" and delete within 7 calendar days.<br>- **Revocation in the Google security settings:** delete within 30 calendar days.<br>- **Tokens that cannot be refreshed:** delete those users' data.<br>- **Aggregation:** only within one content owner.<br>- **Display:** only to the authorizing user or agents that user expressly approved.<br>- **Statistics:** kept as long as necessary, with authorization confirmed and videos checked for deletion every 30 days.<br>- **Other data:** deleted or refreshed after 30 days.<br>- **Deletion request or account deletion:** within 7 calendar days.<br>- **Replacement data and derived data or metrics:** not allowed. |
| YouTube API Services Terms of Service (P-2, S-74) | Section 24.3 verbatim. No revision date is shown. | Unchanged. On termination, delete all API Data, including from servers. At YouTube's request, certify the deletion in a writing signed by an authorized representative. |
| Google API Services User Data Policy (P-8, S-71) | Verbatim; "Last updated: February 15, 2024". | Unchanged. Limited Use covers the raw data and data "aggregated, anonymized, or derived" from it. |

The revision history (S-73) and the Cross-Account Protection page (S-75) were not read again. The rows depend on them only for two things: the derived-metrics terms, which stay excluded, and not using RISC.

Both rows now carry the texts of entry review section 4.5:
- **Status:** `current`, verified 2026-11-18, review due 2027-11-18.
- **Sources:** `youtube.authorized_analytics` also cites S-74, for its termination rule.
- **Effect:** the live adapter is registered only while both rows are current and before their review date.

### Built

- **Adapter.** `app/connectors/youtube.py` (version `youtube-data-v3-analytics-v2`) uses the 011-A capability: scopes, buckets, streams and catalog. Live behavior:
  - **Authorization.** Google's web server flow with `access_type=offline`, `prompt=consent` and PKCE `S256`. The code exchange keeps the refresh token's reported lifetime as the grant's expiry (F1).
  - **Channel.** `channels.list?mine=true` with `part=id,snippet` and `fields=items(id,snippet/title)`.
    - A connection is installed only for exactly one channel (F4).
    - No channel (`no_channel`), several channels (`several_channels`) or a failed lookup (`channel_unavailable`) is a refusal.
    - A grant without the Data API scope comes back without a channel read, and the runtime refuses it as `scopes_missing` (D2).
  - **Tokens.** A refresh keeps the refresh token (F3). Revocation at `oauth2.googleapis.com/revoke` counts an already invalid token as done.
  - **Streams.** As in 011-A. The `fields` parameter keeps titles, descriptions, thumbnails, tags and other text out of every video answer. An inventory read resolves the uploads playlist once. A `video_totals` page reads two reports: the catalog by `video`, and the product type by `video,creatorContentType` with `views` only (see the live check).
  - **Errors (F14, YT-5):**
    - 401 is unauthorized.
    - A 403 with `quotaExceeded` or `dailyLimitExceeded` is `budget_exhausted` in the call's bucket.
    - 403 rate limits and 429 are rate limits, with `Retry-After`.
    - Other 403 answers are forbidden for the stream.
    - 5xx and network failures are retryable; everything else is permanent.
- **Settings.** `connector_youtube_enabled` (default false), `youtube_client_id` and `youtube_client_secret`, read from `TRACKING_CONNECTOR_YOUTUBE_ENABLED`, `TRACKING_YOUTUBE_CLIENT_ID` and `TRACKING_YOUTUBE_CLIENT_SECRET`. When the adapter is enabled:
  - the client ID must end in `.apps.googleusercontent.com` and differ from the Google sign-in and Gmail sender clients;
  - the secret must be 8 to 128 ASCII characters without surrounding spaces;
  - validation errors never contain the secret.
- **Registration.** `build_providers` registers `youtube` only when it is enabled and configured and both rows are current (`LIVE_RULES`).
- **Runtime.** A refusal for several channels or a failed channel lookup keeps the grant (`UNKNOWN_ACCOUNT_REFUSALS`, D5). Such an account cannot be told apart from a working connection's account, and Google would revoke that connection's tokens too.
- **Operator purge.** `python -m app.connector_purge --provider youtube --confirm` (entry review section 4.2):
  - disconnects every live YouTube connection with reason `operator_purged`;
  - brings forward the deadline of teardowns already under way to the time of the purge;
  - runs the teardowns in the same command, so neither a revocation that cannot be made nor an adapter removed by the kill switch delays the deletion;
  - reports a teardown that a running worker holds as `remaining`;
  - prints only counts.
- **Migration.** `0016_youtube_provider` admits `youtube` in connections, webhook deliveries and deletion requests, and admits the reason `operator_purged`. It changes no table, column, index or privilege. The downgrade refuses YouTube state in five tables and any operator-purged connection.
- **API and documents.** The connect input accepts `youtube`, and the OpenAPI snapshot was regenerated. The [connector guide](../../docs/engineering/connectors.md#youtube-providers-011-a-and-011-c) describes both YouTube providers.
- **Fixture.** `tests/youtube_api.py` serves the token, revocation, Data API and Analytics endpoints with synthetic values only.

Existing tests changed only where 011-C changes behavior:
- **`test_connector_youtube.py`:** a refusal for several channels now keeps the grant. The migration test compares the head before and after the refused downgrade instead of naming `0015`.
- **`test_privacy_secrets_restore.py`:** the two YouTube rows are current, with their new dates.

### Purge defect found by the mutation check

**What happened.** The first mutation run removed the purge-time deadline, and the run hung. With the normal deadline, a teardown whose revocation fails returns `pending` and releases its lease, and the purge loop ran until no YouTube connection remained `disconnecting`.

**Why it was a real defect.** The same loop would never end for a teardown already under way before the purge. Two examples: an owner's disconnect while Google's revocation endpoint fails, or a teardown after the kill switch has removed the adapter.

**Fix.** The purge now also brings forward the deadline of those teardowns, and it stops when a pass completes none. `test_011c_operator_purge_does_not_wait_for_an_unavailable_revocation` covers both cases, plus a teardown held by a worker.

**Recovery.**
- The hung run was stopped by ending its test process. The script then restored the source byte for byte.
- The disposable database was recreated, because the stopped test had left synthetic rows that the suite refuses.

### Tests

| Requirement | Test |
|---|---|
| Read-only scopes, offline access, consent and PKCE `S256` | `tests/test_connector_youtube_adapter.py::test_capability_requests_read_only_scopes_with_pkce_and_offline_access` |
| Code exchange: channel ID and title only, grant expiry kept; refusals named | `test_exchange_reads_the_channel_and_keeps_the_grant_expiry`, `test_exchange_refusals_name_their_reason` |
| A refresh keeps the refresh token; revocation ends every grant of the account | `test_refresh_keeps_the_refresh_token_and_revocation_ends_every_grant` |
| Channel snapshot with a hidden subscriber count `not_returned`; day reports with the days without rows `not_returned` | `test_channel_snapshot_and_day_reports` |
| Inventory pages, the uploads playlist resolved once, allow-listed attributes without titles, lifetime totals as two reports (the whole catalog by video, the product type with `views` only), deleted videos confirmed | `test_inventory_attributes_totals_and_deleted_videos` |
| Error mapping (7 cases), `Retry-After`, invalid tokens | `test_errors_map_to_runtime_kinds`, `test_rate_limits_carry_retry_after_and_invalid_tokens_are_unauthorized` |
| Settings validation, registration off by default, no registration with a stale row or after the review date | `test_settings_and_rule_gated_registration` |
| Connect through the API; one run per stream; 6 Data units and 5 Analytics requests for 4 videos and 90 days; a quota answer deferred to the Pacific midnight; a deleted video purged; the operator purge | `tests/integration/test_connector_youtube_live.py::test_011c_connect_read_every_stream_and_purge` |
| Operator purge with a revocation that cannot be made, a teardown under way with the adapter removed, and a teardown held by a worker | `test_011c_operator_purge_does_not_wait_for_an_unavailable_revocation` |
| Partial consent refused, and its grant revoked when no other connection holds the account | `test_011c_partial_consent_is_refused_and_revoked` |
| Migration `0016` downgrade refused with live YouTube state | `test_011c_migration_downgrade_refuses_live_youtube_state` |

| Command (from `backend/`, project `.venv`; database runs through the disposable service) | Result |
|---|---|
| `python -m pytest -m "not integration" -q` | **593 passed**, 342 deselected |
| `python -m pytest -m "integration or not integration" -q tests/test_connector_youtube_adapter.py tests/integration/test_connector_youtube_live.py tests/integration/test_connector_youtube.py` | **29 passed** (15, 4 and 10) |
| `python -m pytest -m integration -q` (full integration suite, after the purge and `video_totals` corrections) | **339 passed, 3 skipped**: the three browser journeys of `test_tracker_journey.py`, which need `TRACKING_RUN_BROWSER_TESTS=1` and are unrelated to connectors (skipped, not passed) |
| Migration `0016` | The suite upgrades to head (`0016_youtube_provider`). `test_postgresql_migration_cycle_and_runtime_permissions` downgrades to base and upgrades again on the empty database. The downgrade to `0015` is refused while a `youtube` connection exists. |
| OpenAPI snapshot | Regenerated; `tests/test_contract.py` passes |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed |
| Mutation check: each safeguard disabled in turn, the 29 YouTube tests rerun, the source restored byte for byte (SHA-256 compared) | **All 10 caught**, with no setup error in any run:<br>- rule-gated registration;<br>- the kept grant for unknown accounts (D5);<br>- the deadline at the time of the purge;<br>- the `remaining` report;<br>- a client of its own;<br>- titles kept out of video answers (3 failures);<br>- the content type read with `views` only (3 failures);<br>- the catalog read by `video` (3 failures);<br>- days without rows `not_returned`;<br>- no channel read without the Data scope (2 failures).<br><br>The first run hung on the deadline mutation (see the purge defect above). The two `video_totals` safeguards were added after the live check. |

### Limits and follow-ups

- **Live check.** Done on 2026-11-18 (below). The live disconnect check comes after F3 (Phase 4).
- **Secret rotation.** Deferred by the owner on 2026-11-18: the live check ran with the existing secret. It stays an open follow-up in the [tasks](tasks.md).
- **Policy wording.** Developer Policies III.E was confirmed from the fetch tool's summary, not word for word. A complete reading belongs to the review before production (011-D).
- **Operator purge deadline.** The deadline is the moment the purge starts, and the teardown ends a few milliseconds later. The connection view therefore reports `deadline_met: false` for every connection the purge completes.
- **Page costs are maxima.** Only the first page of a read resolves the uploads playlist:
  - later `videos` pages reserve 3 Data units but use 2;
  - later `video_totals` pages reserve 2 but use 1.

  Recorded usage can therefore exceed Google's count by one Data unit per later page.
- **Large channels.** A `video_totals` page reserves 2 Analytics requests and 2 Data units, and a `videos` page 3 Data units. Next to the daily `channel_daily` request, the 30 Analytics requests a connection may use per day (D10) cover 14 `video_totals` pages, about 700 videos, and the rest continues from its cursor the next Pacific day. The Data allocation alone would stop at 19 pages, about 950 videos. D10 estimated about 2,000 videos. See the [capacity](#capacity-of-the-live-adapter-r011-17) recorded with the D-061 corrections.
- **Several channels.** Not observable with the owner's account (F4). The refusal is tested with the fixture only.
- **Testing status.** While `connectapp` is in Testing, only its test users can authorize, and refresh tokens last 7 days. Use beyond the owner's test channels waits for 011-D.

### Live check with the owner's test channel (2026-11-18)

Completion prompt Phase 3 step 8, with the owner present. Only redacted facts are recorded: outcomes, counts, states and offsets, with no ID, label, token or metric value.

**Setup:**
- **Database.** A separate disposable database: Compose project `tracking-system-youtube-live`, `tracking_youtube_live` on 127.0.0.1:55434, at head `0016_youtube_provider`. Never `tracking_sys`.
- **API.** Ran in process with the adapter enabled only for this check, using the connector's Web client from the main `.env`.
- **Callback.** A loopback receiver on `127.0.0.1:8000` took Google's redirect to `/connectors/oauth/callback`. It passed the code and state to the API's callback, with the session and binding cookies of the client that had started the connect.
- **Access rule.** A guard replaced the adapter's revoke: it counts attempts and never calls Google. No disconnect was made.

**Consent and first sync.** At about 19:26 UTC the owner chose the test channel's account and granted both scopes.
- The callback answered `connected`.
- The connection is `active`, with both scopes and a label. Its grant expiry is 7.0 days ahead (Testing).
- One worker pass ran the first sync of each stream: 3 succeeded and 1 failed.

| Stream | Coverage | Records |
|---|---|---|
| `channel` | `complete` through the current Pacific day | 1 snapshot, 3 values observed |
| `channel_daily` | `complete` through 3 days before the read (the 72-hour rule) | 90 days, 4 of them provisional; all 1,170 values observed, so every day of the window had a row |
| `videos` | `complete` | 26 videos, 78 values observed; attributes only `duration`, `live_state`, `privacy_status` and `published_at` |
| `video_totals` | `not_synced`, sync `failed` with `permanent` | 0 |

**Defect.** Google answered the `video_totals` report with 400 `badRequest`: "The query is not supported". Read-only queries with the same connection showed the cause:
- **Refused:** the adapter's query, the 13 metrics by `video,creatorContentType`, whether it started on 2005-02-14 or 2008-07-01.
- **Accepted (24 rows each), as in F9:** the 13 metrics by `video` alone, and `views` by `video,creatorContentType`.
- **Each metric alone by `video,creatorContentType`:** accepted, except `videosAddedToPlaylists` and `videosRemovedFromPlaylists`, which were refused. Removing any single metric from the full query therefore still failed.
- **Single-metric answers** hold only the videos with a non-zero value: for example 6 rows for `dislikes` and none for `subscribersLost`.

F9 had tried both accepted shapes, but not the combination the adapter used.

**Correction**, within D7 and D8 (the catalog and product types are unchanged):
- **Adapter.** A `video_totals` page reads two reports: the catalog by `video`, and the content type by `video,creatorContentType` with `views` only. The page cost becomes 2 Data units and 2 Analytics requests.
- **In-memory API.** It now refuses the playlist metrics together with `creatorContentType`, as Google does.
- **Tests.** The adapter test checks both report shapes and the whole catalog in each record. Two mutations guard the shapes.

**Re-run.** With the corrected adapter on the same connection, without a new consent, `video_totals` succeeded and is `complete`:
- **Records:** 26, of which 24 have all 13 metrics (312 values). 2 have no data (`not_returned`, product type unknown), as in F9.
- **Product types:** 21 `SHORTS` and 3 `VIDEO_ON_DEMAND`.
- **Coverage:** all 32 metrics of the catalog `available`.
- **Usage on the Pacific day after both runs:** 8 Data units and 6 Analytics requests.

**Access rule.** The guard counted no revocation attempt in either run. The connection was not disconnected. The live-check database was removed afterwards (`down -v`). The grant stays at Google until it expires, 7 days after consent, or until Phase 4 revokes the account's grants.

## Merge review corrections (D-061) (2026-11-18)

Scope: the [merge review prompt](merge-review-prompt.md), recorded as D-061. Claude's independent review of the whole branch ran at `cd307d7`, and each finding was re-checked at `d8b6b5d`. That was still the head when the corrections started: no later commit existed, and the F8 next-day probe is not recorded yet.

- **No live access.** No live Google call was made, no token of the test account was revoked, and no live connection was disconnected (the access rule of the completion prompt).
- **Database.** Every check ran against fixtures and the disposable PostgreSQL 18 service (Compose project `tracking-system-foundation-test` on 127.0.0.1:55433), never the owner's `tracking_sys`.
- **Unchanged.** No migration, dependency, privilege or API field changed, so the OpenAPI snapshot is unchanged (`tests/test_contract.py` passes).
- **Platform.** Every run below, the regression runs against `d8b6b5d` included, was on Windows 11 with Python 3.12.4.

| Finding | Correction | Regression | At `d8b6b5d` |
|---|---|---|---|
| R011-13 | The worker's scheduling step `check_authorizations`, next to `expire_reconnects`, refreshes the access token of each active connection whose provider declares `authorization_check_days` and whose last refresh is older than that period, without reading data and whatever the state of the agency and client, the longest unchecked first (at most 100 a pass). It follows `_refresh`: nothing is reserved (a provider with the check must declare quota buckets, which `Capability` now enforces); the new token is stored with the same code (`_store_refreshed`) only while the connection is active under the generation read before the call and the refreshed version is current, and is otherwise discarded as `_refresh` discards it; and `invalid_grant` makes the connection `reconnect_required` (`credential_expired`) through the shared `_mark_reconnect_required`, after which the 14-day grace purge applies. The design note and the guide are corrected. | `tests/integration/test_connector_youtube.py::test_r011_13_authorization_is_checked_for_an_archived_client_and_a_suspended_agency`; `tests/test_connector_youtube_synthetic.py::test_r011_13_an_authorization_check_period_needs_quota_buckets` | fail: no check 8 days later (`({}, {})` instead of `({"checked": 2}, {})`); no `ValueError` |
| R011-14 | `_token_error` maps `invalid_client`, `unauthorized_client`, `deleted_client` and `disabled_client` to `PERMANENT` with the code `client_rejected`, at a refresh and at an exchange. Only `invalid_grant` is `UNAUTHORIZED`, and only at a refresh; any other refusal, an unexplained 401 included, is `PERMANENT` (`refused`). The adapter logs `connector_client_rejected` without fields, registered in `app.logging_config.EVENTS`. | `tests/test_connector_youtube_adapter.py::test_r011_14_only_invalid_grant_ends_the_authorization` (10 cases); `tests/test_logging.py::test_r011_14_client_rejected_event_is_registered_without_fields`; `tests/integration/test_connector_youtube_live.py::test_r011_14_a_rejected_client_fails_runs_and_keeps_the_connection_active` | fail: 6 of the 10 cases (client errors answered with 401 at a refresh, and an unexplained 401, were `UNAUTHORIZED`; `unauthorized_client` and a client error at an exchange were `refused`); the event was rejected as unregistered; with a rejected client the run made the connection `reconnect_required` (`{"stopped": 1}` instead of `{"failed": 1}`). The 4 unchanged cases (`invalid_grant` at a refresh and at an exchange, 429 and 503) pass at both revisions. |
| R011-15 | The live and synthetic adapters carry the read's first day in the `channel_daily` cursor (`<first-day>:<offset>`, after the `syt_cursor_` prefix in the synthetic adapter). A resumed page continues the day list that the first page fixed, while the end follows the latest 72-hour bound, so the days that became complete meanwhile are read too. Any other cursor, including a bare offset written before the correction, is refused as `invalid_cursor`. The Instagram `account` stream has the same pattern on UTC days; it is recorded as a [Spec 010 follow-up](../010-instagram/evidence.md#follow-ups-and-limits-after-010-c) and not changed. | `tests/test_connector_youtube_adapter.py::test_r011_15_a_resumed_day_read_continues_the_day_list_it_started_with`; `tests/test_connector_youtube_synthetic.py::test_r011_15_the_synthetic_day_cursor_carries_the_first_day`; `tests/integration/test_connector_youtube.py::test_r011_15_a_first_day_read_deferred_between_pages_skips_no_day` | fail: the page read after the Pacific midnight started at `day-2026-09-17` instead of `day-2026-09-16`, as reported; a bare synthetic offset was accepted; after the deferral across the Pacific midnight one day of the list was missing |
| R011-16 | A `channels.list?mine=true` answer without a channel raises `UNAUTHORIZED` with the code `channel_gone`, for the `channel` snapshot and for the uploads lookup of `videos` and `video_totals`. Several channels stay `PERMANENT` (`channel_unavailable`), and a failed request (a 5xx or a network error) stays retryable. | `tests/test_connector_youtube_adapter.py::test_r011_16_a_read_without_a_channel_is_unauthorized`; `tests/integration/test_connector_youtube_live.py::test_r011_16_a_deleted_channel_requires_reconnection_and_is_purged` | fail: `PERMANENT` `channel_unavailable` instead of `UNAUTHORIZED` `channel_gone`; both runs failed (`{"failed": 2}`) and the connection stayed `active` |
| R011-17 | (a) `README.md` and `docs/engineering/local-environment.md` name `0016_youtube_provider` and migrations 0005 to 0016; the table count stays 43, because 0015 and 0016 add none. (b) `.env.example` has the YouTube block. (c) The capacity is corrected in the design note, the guide and the 011-A and 011-C limits; see [below](#capacity-of-the-live-adapter-r011-17). | Documentation | n/a |

### Commands and results

| Command (from `backend/`, project `.venv`; the database runs through the disposable service) | Result |
|---|---|
| The 19 new regressions (`-k "r011_13 or r011_14 or r011_15 or r011_16"`) against a temporary checkout of `d8b6b5d`, made with `git archive` outside the repository, with the new test files copied in and removed afterwards | Unit: **11 failed, 4 passed** (the 4 unchanged `_token_error` cases above, kept as guards). Integration: **4 failed**. The reasons are in the table above. |
| The same 19 regressions at the corrected head | **19 passed** |
| `python -m pytest -m "not integration" -q` | **608 passed**, 346 deselected |
| `python -m pytest -m integration -q` (full integration suite, because R011-13 to R011-16 change shared runtime code) | **343 passed, 3 skipped**: the three browser journeys of `test_tracker_journey.py`, which need `TRACKING_RUN_BROWSER_TESTS=1` and are unrelated to connectors (skipped, not passed) |
| The YouTube tests: `tests/test_connector_youtube_adapter.py`, `tests/test_connector_youtube_synthetic.py`, `tests/test_logging.py`, `tests/integration/test_connector_youtube_live.py` and `tests/integration/test_connector_youtube.py` | **61 passed** |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 152 files formatted |
| Mutation check: each new safeguard disabled in turn, the 61 YouTube tests rerun, the source restored byte for byte (SHA-256 compared) | **All 6 caught**, each by its own regression:<br>- the authorization check removed from the scheduling step (`test_r011_13_...`, and `test_r011_14_a_rejected_client_...`, which expects `check_failed`);<br>- a refused check that no longer leads to `reconnect_required` (`test_r011_13_...`);<br>- a client error that ends the authorization again (`test_r011_14_a_rejected_client_...` and 4 cases of `test_r011_14_only_invalid_grant_...`);<br>- the first day recomputed on a resumed page of the live adapter (`test_r011_15_a_resumed_day_read_...`);<br>- the same in the synthetic adapter (`test_r011_15_a_first_day_read_deferred_...`);<br>- a read without a channel that is permanent again (both `test_r011_16_...`). |

### Capacity of the live adapter (R011-17)

Per connection and Pacific day, against the D10 allocations of 100 Data units and 30 Analytics requests:

| Stream | Reserved per page (50 videos for `videos` and `video_totals`) |
|---|---|
| `channel` | 1 Data unit; one page a day |
| `channel_daily` | 1 Analytics request; a daily incremental window fits one page |
| `videos` | 3 Data units: the first page uses 3 (the uploads playlist lookup, `playlistItems.list` and `videos.list`), later pages 2 |
| `video_totals` | 2 Data units and 2 Analytics requests: the first page uses 2 Data units (the lookup and `playlistItems.list`), later pages 1 |

- **Analytics bound.** 1 + 2 × 14 = 29 requests, so 14 `video_totals` pages: about **700 videos a day**. A larger channel's `video_totals` run continues from its cursor the next Pacific day.
- **Data bound.** 1 + 5 × 19 = 96 units, so 19 pages, about 950 videos. The review measured this at `cd307d7`: 950 videos complete in one day, and at 1,000 videos one run is deferred, although only 63 Data API calls were made.
- **D10's estimate** of about 2,000 videos is reached by neither bound.

### Proposal for the owner: actual page cost (D10)

Not part of this work, because it changes D10's accounting. Each page reserves its maximum cost, so recorded usage can exceed Google's count by one Data unit per later page. The proposal is to reserve each page's actual cost: 3 Data units for the first `videos` page and 2 for later ones, and 2 for the first `video_totals` page and 1 for later ones. The Data bound would then rise to 32 pages (3 + 3 × 32 = 99 units), about 1,600 videos, while the Analytics bound stays at about 700. Channels beyond that would also need a larger per-connection Analytics allocation than D10's 30 requests, which is a decision of its own.

### Q1 and Q2 (adopted by D-061)

- **Q1.** While the adapter is switched off, or a provider rule is past its review date (2027-11-18), the registry has no `youtube` provider: its connections are neither synced nor checked, and the grace purge skips them. The operator purge must follow within 30 days of switching the adapter off (P-1), and the rule review must be renewed before 2027-11-18. No code change; see the guide's [operator obligations](../../docs/engineering/connectors.md#operator-obligations-q1-and-q2-d-061) and the 020 follow-ups in [review-next](../../docs/planning/review-next.md).
- **Q2.** With client errors mapped to `PERMANENT`, connections keep their data while the client is broken. The operator repairs the client or runs the operator purge within the 30 days of P-1. It is documented next to Q1.

### Limits and observations after the D-061 corrections

- **Check retries.** A refresh in the scheduling step that fails other than with `invalid_grant` (a rejected client, a 5xx, a network error) leaves the connection unchanged and is tried again at the next pass. There is no backoff between passes; a pass makes at most one token call per due connection and at most 100 in all.
- **Worker invocation.** The check, like the grace purge, runs only when the worker's scheduling step runs; production scheduling is decided in 020.
- **Deleted videos in archived clients (observation for the owner).** The gating that R011-13 corrected for the authorization check also stops the D11 inventory sweep. No run is queued for a connection whose client is archived or whose agency is suspended, so the records of videos deleted on YouTube stay until the client is active again, the connection is disconnected, or the 730-day retention ends, while P-1 III.E.4.b asks for the check every 30 days. Correcting it needs a decision, for example an inventory check in the scheduling step, or the disconnect of a connection whose client has been archived for 30 days. It is recorded in the [tasks](tasks.md) and not changed.
- **Cursors written before R011-15.** A bare `channel_daily` offset is refused as `invalid_cursor` and fails its run, and the next scheduled run starts the read again. None exists outside disposable databases: there are no customer channels, and the live-check database was removed.
- **Several channels.** A read that finds several channels stays `PERMANENT` (`channel_unavailable`); only the absence of any channel is lost authorization.

## Claude's review of the D-061 corrections and the merge (D-062) (2026-11-18)

Claude reviewed `5ccb87a` independently. It ran on Linux with Python 3.12.3, on the pinned `postgres:18.6-bookworm` image as the disposable service, never on the owner's `tracking_sys`.

| Check | Result |
|---|---|
| `ruff check` and `ruff format --check` | All checks passed; 152 files formatted |
| `pytest -m "not integration"` | **608 passed**, 346 deselected |
| `pytest -m integration` (full suite) | **343 passed, 3 skipped** (the browser journeys) |
| The new regressions against a temporary checkout of `d8b6b5d` | Unit: 11 failed, 4 passed (the guard cases). Integration: 4 failed. These match the counts recorded above, now on Linux. |
| Mutation spot checks | The scheduled authorization check was removed from the scheduling step, and client errors were mapped to `UNAUTHORIZED` again. Both mutations were caught (2 and 5 failures), and the sources were restored byte for byte. |
| The review's reproductions at the corrected head | **Archived client:** the revocation is detected on day 8 (`reconnect_required`), and the connection is purged after the grace period. **Rejected client:** the run fails, and the connection stays `active`. **Resumed first read:** 91 contiguous days with no gap. |
| PR 11 | `mergeable_state` clean against `main` at `5d05153` |

Notes, none of which blocks the merge:

- **Capacity on the connect day.** The first `channel_daily` read uses 3 Analytics requests (90 days in 31-day windows), so on the day of the connect the limit is about 650 videos (3 + 2 × 13 = 29). Measured: 650 videos complete in one day, and at 700 one run is deferred to the next Pacific day. The steady state is about 700, as recorded above.
- **Checks before syncs.** The scheduling step makes its token calls before the pass's sync runs: at most 100, each bounded by the adapter's 20-second timeout. Production scheduling (020) should account for it.

The owner then decided to merge PR 11 before Phase 4 (D-062). The F8 next-day probe and Phase 4 are follow-ups after the merge, recorded on a fresh branch from the merged `main`. The access rule stays in force until F3 is recorded.

## Phase 4 (2026-11-25)

Scope: D-062, under the [Phase 4 handoff](phase4-prompt.md), on `codex/spec-011-youtube-phase4`, created from the merged `main` at `81977a3` in a fresh worktree. Only redacted facts are recorded: outcomes, counts, states, day offsets and error codes, with no token, code, channel or video ID, title or metric value. Nothing ran against native `tracking_sys`, and no call was made to Meta, Instagram or any provider other than Google.

### Step 0: preconditions

| Check | Result |
|---|---|
| Time | 2026-11-25 11:53 UTC, after 2026-11-24 23:57 UTC, when the slot a refresh token of 2026-11-17 23:57 UTC should have expired. Slot b, last stored at 2026-11-18 11:45 UTC, should have expired at about 11:45 UTC the same day. |
| `python -m pytest -q tests/test_youtube_feasibility.py` (offline; from `backend/` with the project `.venv`, on Windows 11 with Python 3.12.4) | **25 passed** |
| Owner confirmations | Since 2026-11-17, nothing has revoked a token, removed the app's access or run `authorize` on slot a. `connectapp` is still in Testing. The test channel's Google account is not the Gmail sender's. |

### Step 1: F3, the 7-day refresh check

At 12:04 UTC the owner ran `refresh` on slot a, then `refresh --slot b`. The token age counts from the start of the `authorize` command that stored the token, so it slightly exceeds the age since Google issued it.

| Slot | Consent | Token age | Status | Error | Description |
|---|---|---|---|---|---|
| a | 2026-11-17 23:57 UTC | 180.1 hours | 400 | `invalid_grant` | Google's fixed text for an expired or revoked token |
| b | 2026-11-18 11:45 UTC (the PKCE consent) | 168.3 hours | 400 | `invalid_grant` | The same |

- **Answer to F3.** A refresh works within the token's lifetime (the refresh two minutes after the first consent succeeded). Once the 7-day lifetime that the code exchange reported in `refresh_token_expires_in` (604,799 seconds, about 168.0 hours) has passed, the refresh is refused with `invalid_grant`: slot b about 0.3 hours after that lifetime ended, slot a about 12 hours after.
- **Expiry, not revocation.** Google's description does not tell an expiry from a revocation. The owner confirmed in step 0 that nothing revoked a token or removed access since 2026-11-17, so both refusals are expiries.
- **Not measured.** The exact moment of expiry: no refresh was made between 2 minutes and 168.3 hours after a consent.
- **Consequence for D4: none.** The grant keeps the reported `refresh_token_expires_in` as its expiry (`grant_expires_at`), and Google refuses the token once that time has passed. A connection made while `connectapp` is in Testing therefore needs a new consent within 7 days. The runtime already makes it `reconnect_required` (`credential_expired`) on `invalid_grant`, and the 14-day grace purge follows.
- **Access rule.** With F3 recorded, the access rule of the [completion prompt](completion-prompt.md#access-rule-for-the-test-account) ends (D-060, D-062).
