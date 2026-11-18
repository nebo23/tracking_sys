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
