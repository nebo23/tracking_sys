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

Consequence: none for D2. The adapter installs a connection only when the `scope` field of the answer holds both scopes, which follows what Google actually grants, whatever was ticked on the screen. Under D3, the adapters declare PKCE `S256` (`Capability.pkce = "S256"`), with the single-use state, the session binding and the server-side exchange unchanged.
