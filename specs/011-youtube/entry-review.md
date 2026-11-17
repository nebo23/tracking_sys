# Specification 011 entry review: YouTube analytics

Prepared: 2026-11-18 on `codex/spec-011-youtube` from merged `main` at `5d05153` (PR 10; Spec 010 merged). Authority: D-056, preparation only. Status: **proposal**. Decisions D1-D17 in section 5 are recommendations for the owner. D15 was decided on 2026-11-18 with its alternative by D-057 (section 10); the others are not approved. This preparation contains no application code, migration or dependency. It creates no Google Cloud project and makes no live Google call.

## 1. Sources and what they establish

These official Google pages were read on 2026-11-18 with a page-reading tool. Long pages were read in sections. A few statements rest on the tool's summary rather than on page text, and they are marked (summary). Most pages show no last-updated date; the dates that do appear are noted. Documentation is not acceptance evidence: acceptance criterion 1 still needs a channel the owner authorizes (section 7, D16).

### 1.1 YouTube Data API v3

| ID | Source | Established from the page |
|---|---|---|
| YT-1 | [Getting started](https://developers.google.com/youtube/v3/getting-started); [quota costs](https://developers.google.com/youtube/v3/determine_quota_cost) | A project gets 10,000 units per day by default, "combined for all other endpoints" and subject to change. `search.list` and `videos.insert` have separate buckets of 100 calls per day (2026-06-01), and `videos.batchGetStats` has its own bucket with a default of 10,000 units (2026-06-03). "Daily quotas reset at midnight Pacific Time (PT)". Every request costs at least one unit, invalid requests included, and each additional page costs the method's cost again. `channels.list`, `playlistItems.list` and `videos.list` cost 1 unit whatever parts are requested. |
| YT-2 | [channels resource](https://developers.google.com/youtube/v3/docs/channels); [channels.list](https://developers.google.com/youtube/v3/docs/channels/list) | `mine=true` returns channels owned by the authenticated user and works only in an authorized request. `contentDetails.relatedPlaylists.uploads` is the playlist of the channel's uploads. `statistics.subscriberCount` "is rounded down to three significant figures". `hiddenSubscriberCount` indicates whether that count is publicly visible. `videoCount` counts public videos only, "even to owners". `viewCount` covers every format, counts from the start of playback, and includes co-views. |
| YT-3 | [playlistItems.list](https://developers.google.com/youtube/v3/docs/playlistItems/list); [resource](https://developers.google.com/youtube/v3/docs/playlistItems) | `maxResults` takes 0 to 50 (default 5) and pages with `pageToken`. Items carry `status.privacyStatus`. The page does not say whether the uploads playlist lists private and unlisted videos to the owner. |
| YT-4 | [videos resource](https://developers.google.com/youtube/v3/docs/videos); [videos.list](https://developers.google.com/youtube/v3/docs/videos/list); [videos.batchGetStats](https://developers.google.com/youtube/v3/docs/videos/batchGetStats) | `videos.list` reads a comma-separated ID list (`maxResults` does not apply to `id`, and no maximum ID count is stated). It returns `statistics.viewCount`, `likeCount` and `commentCount` (definitions from the summary). `dislikeCount` is returned only to the owner (since 2021-12-15), and `favoriteCount` is deprecated (summary). `contentDetails.duration` is an ISO 8601 duration. `snippet.publishedAt` may differ from the upload time. `snippet.liveBroadcastContent` is `live`, `upcoming` or `none`. No field identifies a Short. `batchGetStats` returns view, like and comment counts and durations for 1 unit in its own bucket. It needs authorization only for non-public videos, and its maximum ID count is not stated. |
| YT-5 | [Errors](https://developers.google.com/youtube/v3/docs/errors) | `quotaExceeded` is HTTP **403**, as are `forbidden` and `insufficientPermissions` (scopes insufficient for the data). The rate-limit reasons of the read methods were not established (summary only). |
| YT-6 | [Quota and compliance audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) | Quota above the default requires a completed API compliance audit through the "YouTube API Services - Audit and Quota Extension Form". A project audited within the last 12 months may request a further extension. YouTube also runs periodic audits, and there are appeal and change-of-control forms. |
| YT-7 | [Data API revision history](https://developers.google.com/youtube/v3/revision_history) (to 2026-11-16) | Shorts views count when playback starts from 2025-03-31. Public views count from the first frame (2026-08-27) and include co-views (2026-11-16). Granular quota buckets arrived on 2026-06-01 and `batchGetStats` on 2026-06-03. |

### 1.2 YouTube Analytics API

| ID | Source | Established from the page |
|---|---|---|
| YT-8 | [Analytics overview](https://developers.google.com/youtube/analytics) (last updated 2026-11-03) | Targeted queries of channel reports go through `reports.query`; bulk reports go through the Reporting API. |
| YT-9 | [reports.query](https://developers.google.com/youtube/analytics/reference/reports/query) | The endpoint is `GET https://youtubeanalytics.googleapis.com/v2/reports`. Required: `ids` (`channel==MINE`), `startDate`, `endDate` and `metrics`. Optional: `dimensions`, `filters` (a video filter takes up to 500 IDs), `sort`, `maxResults`, `startIndex` and `currency`. Listed scopes: `yt-analytics.readonly`, `yt-analytics-monetary.readonly` (revenue and ad metrics), `youtube` and `youtubepartner`. A banner says requests "now require access to the `youtube.readonly` scope", but the scope table does not list it. Data is returned "up until the last day for which all metrics in the query are available". When there is no data, the `rows` element is omitted. |
| YT-10 | [Dimensions](https://developers.google.com/youtube/analytics/dimensions) | A day runs from 12:00 AM to 11:59 PM Pacific time, so daylight-saving changes produce 23-hour and 25-hour days. `creatorContentType` (`LIVE_STREAM`, `SHORTS`, `STORY`, `VIDEO_ON_DEMAND`, `UNSPECIFIED`) has data from 2019-01-01. No overall history limit is stated; queries without the `audienceType` filter work for dates after 2008-07-01. |
| YT-11 | [Metrics](https://developers.google.com/youtube/analytics/metrics) | Metrics: `views` (includes co-views), `engagedViews`, `estimatedMinutesWatched`, `averageViewDuration` (seconds), `averageViewPercentage`, `likes`, `dislikes`, `comments`, `shares`, `subscribersGained` and `subscribersLost` (both count the watch page only in video reports), and `videosAddedToPlaylists` and `videosRemovedFromPlaylists` (from 2014-10-01). Revenue metrics need the monetary scope and a YouTube Partner Program channel, otherwise HTTP 403. Thumbnail impressions are not Analytics API metrics. |
| YT-12 | [Data model](https://developers.google.com/youtube/analytics/data_model) | "Data processing typically introduces a latency of 48 to 72 hours." Each request counts as one unit of the Analytics API quota, whose limits appear only in the Cloud console. |
| YT-13 | [Channel reports](https://developers.google.com/youtube/analytics/channel_reports) | Only fixed dimension and metric combinations are supported; others return HTTP 400. Top-videos reports need `maxResults` of 200 or less and a `sort`. Time-based reports take `day` with zero or one video in the filter. Demographic and geographic data are limited at thresholds that are "not published". |
| YT-14 | [Analytics revision history](https://developers.google.com/youtube/analytics/revision_history) (to 2026-11-16) | Targeted queries count Shorts views differently from 2025-04-30, and `engagedViews` keeps the earlier method. Views count from the first frame (2026-08-27). A latency section and the Partner Program rule were added (2026-09-09). Age groups include users estimated to be under 18 (2026-03-09). Co-views are included (2026-11-16). |

### 1.3 YouTube Reporting API

| ID | Source | Established from the page |
|---|---|---|
| YT-15 | [Reporting overview](https://developers.google.com/youtube/reporting); [bulk reports guide](https://developers.google.com/youtube/reporting/v1/reports) | Each job (`jobs.create` with a report type) produces daily CSV reports. The first report is available within 48 hours, and a new job backfills the 30 days before its creation. Reports stay available for 60 days, historical ones for 30 days. Corrected data arrives as a new report with the same `startTime` and `endTime` and a newer `createTime`, and it replaces the earlier report. Days run from 12:00 AM to 11:59 PM Pacific Standard Time (UTC-8). The API is meant for "high-volume applications", and "Quota usage is not an issue". |
| YT-16 | [Channel bulk reports](https://developers.google.com/youtube/reporting/v1/reports/channel_reports) | `channel_basic_a3` rows are keyed by date, channel, video, live or on demand, subscribed status and country. The reach reports (`channel_reach_basic_a1`, with thumbnail impressions and click-through rate, from 2026-01-15) exist only in this API. |
| YT-17 | [Authorization guide](https://developers.google.com/youtube/reporting/guides/authorization) | The Reporting API uses `yt-analytics.readonly` and `yt-analytics-monetary.readonly`. Service accounts serve content owners only and cannot act as a channel. Offline access returns refresh tokens, and revocation goes to `https://oauth2.googleapis.com/revoke`. Neither API accepts API-key-only requests. |
| YT-18 | [Reporting revision history](https://developers.google.com/youtube/reporting/revision_history) (to 2026-11-16) | Report versions `a3`, with `engaged_views`, apply from 2025-06-30, and the earlier versions were deprecated on 2025-10-31. Reach reports were added on 2026-01-15. |

### 1.4 Google OAuth 2.0 and app verification

| ID | Source | Established from the page |
|---|---|---|
| G-1 | [OAuth 2.0 for web server applications](https://developers.google.com/identity/protocols/oauth2/web-server) | Authorization goes to `https://accounts.google.com/o/oauth2/v2/auth`, and the code exchange goes to `https://oauth2.googleapis.com/token` with the client secret. `access_type=offline` returns a refresh token at the first exchange only; `prompt=consent` obtains a new one. The token answer has `access_token`, `expires_in`, `refresh_token`, `scope` (the granted scopes) and `token_type` `Bearer`. Redirect URIs must use HTTPS, but "Localhost URIs (including localhost IP address URIs) are exempt". PKCE is not mentioned for this flow. Revocation takes an access or a refresh token: "If the token is an access token and it has a corresponding refresh token, the refresh token will also be revoked". Also: "Revocation removes all OAuth 2.0 scopes previously granted to a project, invalidating any issued access or refresh tokens for all clients registered under that project". Success returns 200 and an error 400, and the revocation may take some time to take full effect. |
| G-2 | [OAuth 2.0 overview](https://developers.google.com/identity/protocols/oauth2) | A refresh token stops working when the user revokes access or when it is unused for six months. The limit is 100 refresh tokens per Google Account per client ID, and a new one invalidates the oldest "without warning". Expired time-based access and an administrator restriction also end it. An External project in "Testing" receives refresh tokens "expiring in 7 days" unless it requests only name, email and profile scopes. |
| G-3 | [OAuth 2.0 for installed apps](https://developers.google.com/identity/protocols/oauth2/native-app) | The same authorization endpoint documents PKCE: `code_challenge`, `code_challenge_method` `S256` or `plain`, and `code_verifier` at the exchange. |
| G-4 | [OAuth scopes](https://developers.google.com/identity/protocols/oauth2/scopes) | `youtube.readonly`: "View your YouTube account". `yt-analytics.readonly`: "View YouTube Analytics reports for your YouTube content". `yt-analytics-monetary.readonly` adds monetary reports. |
| G-5 | [Granular permissions](https://developers.google.com/identity/protocols/oauth2/resources/granular-permissions) | "users may not grant all scopes your app requests". An app must check the `scope` field and disable features whose scopes were not granted. |
| G-6 | Cloud help: [sensitive scope verification](https://support.google.com/cloud/answer/13464321), [restricted scopes](https://support.google.com/cloud/answer/13464325), [security assessment](https://support.google.com/cloud/answer/13465431), [unverified apps](https://support.google.com/cloud/answer/7454865), [submission](https://support.google.com/cloud/answer/13461325) | Sensitive or restricted scopes need brand verification (a homepage on a verified domain, a privacy policy and contact details), a demo video of the OAuth flow and a scope justification. The annual security assessment (CASA) applies to restricted scopes only, and the restricted list names no YouTube Data or Analytics scope. Verification "might require several months". An unverified app is limited to 100 new users after its unverified screen. Testing and internal use need no verification. Whether the two YouTube scopes are sensitive is shown in the console and was not established. |
| G-7 | Cloud help: [OAuth clients](https://support.google.com/cloud/answer/15549257) | "OAuth 2.0 clients that have been inactive for six months are automatically deleted". An email arrives 30 days before deletion, and a deleted client can be restored for about 30 days. |
| G-8 | [Cross-Account Protection (RISC)](https://developers.google.com/identity/protocols/risc) | Google sends signed security events (token revoked, sessions revoked, account disabled) to a registered HTTPS endpoint once the RISC terms are accepted. Events come only for users who granted profile or email scopes. |

### 1.5 Policies

| ID | Source | Established from the page |
|---|---|---|
| P-1 | [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies) | **III.D.1**: one API project per API client; credentials may be shared only with agents bound to confidentiality. **III.D.2**: a revocation made in the client must be revoked programmatically "right away", and its Authorized Data deleted "within 7 calendar days". After a revocation in the Google security settings, data must be deleted "within 30 calendar days". Clients must reconfirm tokens periodically and delete the data of users "whose authorization tokens cannot be refreshed". **III.D.3**: extra quota serves only the approved use case, and a change of use case means resubmitting the audit. **III.D.4**: a project inactive for 90 consecutive days may be curtailed. **III.E.2**: aggregate only channels "under the same content owner", viewable only by that owner, and never to gain insights into YouTube's business. **III.E.3**: show Authorized Data only to "the authorizing user or agents expressly approved by that user". **III.E.4.b**: Analytics API data, Reporting API data and statistics such as view counts may be stored "for as long as is necessary". The client "must still ensure every 30 days that it is still authorized" and must verify every 30 days that a video has not been deleted. Non-authorized statistics may be kept for at most 30 days. **III.E.4.c**: all other Authorized Data may be kept "no longer than 30 calendar days", then deleted or refreshed. **III.E.4.g**: delete data on a user's request, or when the user deletes their account, "within 7 calendar days". **III.E.4.h**: no replacement or derived data or metrics. Non-YouTube metrics shown next to API Data need "a clear and prominent disclosure" that they are not from YouTube; for example, a percentage of total likes is not permitted. **III.E.6**: no scraping. **III.F.2**: YouTube must be shown as the source. **III.G.1**: no sale or sublicensing of the API services, and advertising on pages with API Data only when other data offers enough independent value. **III.H**: audits, including accounts that give access to the production client on request. **III.A**: privacy policy and Terms of Service link (the individual items from the summary). |
| P-2 | [YouTube API Services Terms of Service](https://developers.google.com/youtube/terms/api-services-terms-of-service) | Section 6: YouTube may monitor and audit at any time. Section 10.3: attribution follows the Branding Guidelines. Section 24.3: on termination, stop and delete all API Data immediately, with written certification on request. Section 25.9: notice of a change of control within 15 days. |
| P-3 | [Developer Policies guide](https://developers.google.com/youtube/terms/developer-policies-guide) | Simple calculations are permitted ("addition, subtraction, averages, multiplication, division") without external data, for example "Average daily views in a month" and "Total views in a group of videos/channels". Without the additional terms, the following are prohibited: merging YouTube data with other data; showing it next to other platforms' data without clarifying the difference; custom scores; ranking views between channels; and estimating demographics, watch time, unique reach or monetization. A user's authorization that cannot be verified must be resolved within 30 days. |
| P-4 | [Additional policies on derived metrics and data storage](https://developers.google.com/youtube/terms/derived-metrics-policy) | From 2026-06-01, these apply to audited analytics developers who applied through the quota extension form (Section 5, "Analytics & Reporting") and accepted the amendment. Such developers may offer derived metrics (custom scores, ratios, leaderboards, estimates), distinguished from API data. They may also store statistics and derived metrics for up to 36 calendar months. Titles, names, descriptions and comments stay under the 30-day rule. |
| P-5 | [Terms revision history](https://developers.google.com/youtube/terms/revision-history) (to 2026-06-01) | The additional policies were announced on 2026-05-04 and clarified on 2026-06-01. |
| P-6 | [Branding Guidelines](https://developers.google.com/youtube/terms/branding-guidelines) | A YouTube logo must link back to YouTube content. "YouTube" and its variants must never be used in the application's name. When content comes from several sources, the YouTube icon goes next to each element. Logos must not be modified, must meet the minimum sizes, and must not be the most prominent element. |
| P-7 | [Required Minimum Functionality](https://developers.google.com/youtube/terms/required-minimum-functionality) | It covers players, uploads and comments; nothing in it applies to read-only analytics. |
| P-8 | [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy) (last updated 2024-02-15) | Limited Use applies to sensitive and restricted scopes "unless stated otherwise in the product's" policy, and it covers "data aggregated, anonymized, or derived". Data may be used only for user-facing features. It may be transferred only in the listed cases and with consent, and people may read it only with the user's agreement, for security or legal reasons, or as aggregated internal operations. No sale or advertising use is allowed. Apps must request minimum scopes in context, make a prominent disclosure and publish a privacy policy. A security assessment may apply, depending on the API and the number of users. |
| P-9 | [Google APIs Terms of Service](https://developers.google.com/terms) (last modified 2021-11-09) | No sublicensing of an API for third-party use. The privacy policy must describe how data is used and shared. |
| S-71 to S-75 | Existing [privacy sources](../../research_notes/privacy-data-policy/sources.md) | These are the basis of the stale `youtube.authorized_analytics` and `youtube.other_data` rows in `app.privacy.providers`. Today's reading agrees with the rows' texts; see section 4.5. |

The pages read do not establish the following; each goes to the feasibility check in section 7:

- PKCE with a Web application client.
- Whether revoking one token also invalidates the tokens of a separate consent by the same user, as G-1's project-wide wording suggests.
- Whether the two scopes are classified as sensitive (answered by the console on 2026-11-18; see section 10).
- Whether `reports.query` needs `youtube.readonly` in addition to `yt-analytics.readonly`.
- The Analytics API quota.
- How far back channel day reports go.
- Whether days without activity return zero rows or no rows, and whether a day's values change after they first appear.
- Whether a filter of several videos works with the `video` dimension and with `creatorContentType`.
- Whether the uploads playlist lists private and unlisted videos.
- What a hidden subscriber count does to the owner's own read.
- The maximum number of IDs per `videos.list` and `batchGetStats` call.
- How a Google account with several channels or brand accounts selects one channel.
- The error shapes of rate limits.
- Whether past values are restated after the view-counting changes of 2025 and 2026.
- The verification timeline beyond "several months".

Upload push notifications (PubSubHubbub) were not read and are not relied on.

## 2. What Specs 009 and 010-A provide and where YouTube differs

| 009 or 010-A contract | YouTube fact | Consequence for 011 |
|---|---|---|
| `Capability.pkce` is `S256` or `None` (010-A) | PKCE is documented on the shared endpoint for installed apps (G-3), not for web server apps (G-1) | No contract change. The adapter declares `S256` only if 011-B shows that the Web client accepts and enforces it (D3). |
| `refresh_mode` `refresh_token`: one refresh after a `401` | Access tokens are short-lived (sample `expires_in` 3,920 seconds). A refresh token comes only with `access_type=offline`, and only at the first consent unless `prompt=consent` is sent. Refresh tokens end on revocation, after six months unused, at the 100-token limit, or after 7 days in Testing (G-1, G-2). | Refresh before a call when the access token has expired or is about to, so that no invalid request spends quota (YT-1). Send `prompt=consent` on every connect and reconnect (D4). |
| The runtime never reads `revocation_scope`. A reconnect revokes the previous tokens once the new grant passes its checks, and a refused new grant is revoked by `dispose_grant`. | Revoking any token "removes all OAuth 2.0 scopes previously granted to a project" for all of the project's clients (G-1). | Unchanged, a reconnect would revoke its own new grant. A refused duplicate connect, or one client's disconnect, would also break every other connection of the same channel. This needs a new `revocation_scope` value for account-wide grants with runtime rules (D5) and a dedicated Cloud project (D15). |
| `reconnect_required` keeps the connection's history (D-048) | Clients must delete the data of users whose tokens cannot be refreshed, within 30 days of a revocation in the Google settings, and confirm authorization every 30 days (P-1 III.D.2, III.E.4.b) | Check authorization at least every 7 days, and disconnect and purge automatically after 14 days in `reconnect_required` (D6). |
| One cost unit, with `daily_quota` per UTC day counted across tenants. The runtime's own budget stop lasts until the next UTC day, an adapter `BUDGET_EXHAUSTED` fails the run, and a `403` fails without retry. | The Data API gives 10,000 units per project per day in buckets, resets at midnight Pacific Time, and charges for invalid requests. The Analytics API charges one unit per request against a quota shown only in the console. `quotaExceeded` is HTTP 403 (YT-1, YT-5, YT-12). | Quota buckets per API with the Pacific day boundary. `quotaExceeded` defers the run to the next reset instead of failing it or reading as `forbidden` (D10). |
| Streams with `history_days`, `overlap_days` and `data_delay_hours`; watermarks are instants | Days are Pacific Time days, 23 or 25 hours long at daylight-saving changes. Latency is 48 to 72 hours, and data comes only through the last day with all requested metrics. `rows` is absent when there is no data, and no history limit is stated (YT-9, YT-10, YT-12). | Records are keyed by Pacific date with zone-correct instants. `complete_through` comes from the last day returned. Values stay provisional inside the re-read window, and history limits come from 011-B (D9). |
| `MetricSpec` by stream and product type; the database checks `product_type` against `FEED`, `REELS` and `STORY` | `creatorContentType` has data from 2019-01-01, and the Data API has no Shorts field. Averages are not additive, and `subscriberCount` is rounded (YT-2, YT-10, YT-11). | A migration widens the product types. The catalog gains a non-additive marker and a rounded-count unit (D8). |
| Records hold metric values only, and the account label is kept while the connection lives | Non-statistical Authorized Data (titles, publish times, durations) must be refreshed or deleted within 30 days. Statistics may stay, subject to the 30-day checks, and deleted videos must be checked for every 30 days (P-1 III.E.4.b, III.E.4.c). | Allow-listed record attributes and the label carry a refresh time and are deleted after 30 days without refresh. Records of deleted videos are purged in every stream (D11). |
| `connector_record_retention_days` is 730 for every provider | Statistics may be kept "for as long as is necessary"; 36 months applies only under the additional terms (P-1, P-4) | Retention per provider, with 730 days proposed for YouTube (D11, Q-012). |
| Signed deauthorize and deletion callbacks and webhooks (009-D, 010-A) | The pages read show no deletion callback and no analytics webhook. RISC needs profile or email scopes, HTTPS and its own terms (G-8). | No callbacks in 011. External revocation is detected through refresh failures (D6), and RISC is not used. |
| Members with client visibility and read keys (`client:read`) see records | Authorized Data is only for the authorizing user or agents "expressly approved by that user", and aggregation only within one content owner (P-1 III.E.2, III.E.3) | The connect records an agent approval (D13). No aggregation across clients (D12). |
| HTTP redirect only on loopback (009 setting) | Google exempts localhost IP URIs from the HTTPS rule (G-1) | Unlike Meta, Google accepts the API callback on `127.0.0.1`, so a full browser connect can run locally in 011-B and 011-C. |
| `external_account_id` | `channels.list?mine=true` returns the authorized channel (YT-2) | The channel ID is the account reference. 011-B checks how an account with several channels selects one (F4). |

Everything else applies unchanged: the 009 lifecycle, teardown and purge (Spec 003 case D3), attempt fencing, usage records, coverage states, the 010-A streams and tenant isolation.

## 3. Proposed streams, metrics, history and completeness

### 3.1 Streams (D7)

| Stream | Source and call | Records | Interval, re-read and history | Cost per run |
|---|---|---|---|---|
| `channel` | Data API `channels.list?mine=true` with `id`, `statistics`, `contentDetails` and `snippet/title` (for the label only) | One snapshot per Pacific day: `subscriberCount`, `viewCount`, `videoCount` | Daily. A snapshot describes the day it was read and cannot be backfilled. | 1 unit |
| `channel_daily` | Analytics `reports.query`, `ids=channel==MINE`, `dimensions=day` | One record per Pacific day (`day-YYYY-MM-DD`) with the channel metrics of section 3.2 | Daily, re-reading the last 4 days. 90 days are read at connect, and backfill goes up to 730 days (F10). | 1 request per window of up to 31 days |
| `videos` | Data API: the uploads playlist through `playlistItems.list` (50 per page), then `videos.list` for those IDs (`contentDetails`, `status`, `statistics`, `snippet/publishedAt`, `snippet/liveBroadcastContent`), with `fields` limiting the answer so that titles and descriptions are never received | One record per video, holding the lifetime public counters and the allow-listed attributes of D11 | Daily, over the whole inventory. A video that is no longer returned and that `videos.list` confirms gone is purged. | About 2 units per 50 videos |
| `video_totals` | Analytics `reports.query`, `dimensions=video` (with `creatorContentType` if F9 allows), from the earliest supported date to the last complete day. It uses a filter of up to 500 IDs if F9 confirms that; otherwise the top 200 by views. | One record per video with lifetime analytics totals and the content type as product type | Daily. Lifetime totals have no history window. | 1 request per 200 or 500 videos |

Per-video daily series are left out of the launch. They cost one Analytics request per video per window, about 500 requests a day for a channel of 500 videos, against a quota that is not yet known (F11). The Reporting API is deferred (D1). Its reach reports (thumbnail impressions and click-through rate) remain a later option.

### 3.2 Metric catalog (D8)

| Stream | Metric (provider name) | Unit | Notes |
|---|---|---|---|
| `channel` | `subscriberCount` | rounded count | Rounded down to three significant figures. `not_returned` if hidden from the owner (F4). |
| `channel` | `viewCount`, `videoCount` | count | `videoCount` counts public videos only. |
| `channel_daily`, `video_totals` | `views`, `engagedViews` | count | `views` changed definition on 2025-04-30 (Shorts), 2026-08-27 (first frame) and 2026-11-16 (co-views); the catalog records these dates for reports (016). |
| `channel_daily`, `video_totals` | `estimatedMinutesWatched` | minutes | |
| `channel_daily`, `video_totals` | `averageViewDuration` | seconds | Not additive. |
| `channel_daily`, `video_totals` | `averageViewPercentage` | percent | Not additive. |
| `channel_daily`, `video_totals` | `likes`, `dislikes`, `comments`, `shares` | count | |
| `channel_daily`, `video_totals` | `subscribersGained`, `subscribersLost` | count | In video totals, these count the watch page only. |
| `channel_daily`, `video_totals` | `videosAddedToPlaylists`, `videosRemovedFromPlaylists` | count | |
| `videos` | `viewCount`, `likeCount`, `commentCount` | count | Lifetime public counters. `not_returned` when the owner hides likes or turns comments off (F5). |

Product types in `video_totals`: `SHORTS`, `VIDEO_ON_DEMAND`, `LIVE_STREAM`, `STORY` and `UNSPECIFIED`. The pages read show no metric difference between them, so the metrics apply to every type. `videos` records carry no product type, because the Data API has none; they carry the live state as an attribute instead.

Excluded from the launch catalog:

- Revenue and ad metrics, which need the monetary scope and a Partner Program channel.
- Demographics: age groups have included estimated minors since 2026-03-09, and the thresholds are unpublished.
- Geography, traffic sources and playback locations.
- Audience retention, which allows one video per query.
- Cards and annotations, and thumbnail impressions, which exist only in the Reporting API.
- `dislikeCount` and `favoriteCount` from the Data API, and `uniques`, which is undefined.

A metric the API omits is `missing` with reason `not_returned`, never 0. A value the API returns as 0 is observed as 0. `below_threshold` is not used, because the thresholds concern the excluded demographics.

### 3.3 Time, delay and completeness (D9)

- **Pacific days.** Records are keyed by Pacific date (America/Los_Angeles). `observed_at` is the start of that day as a UTC instant, and day boundaries always come from the zone, never from a fixed offset, so 23-hour and 25-hour days are correct.
- **End of a read.** A read ends at the last complete Pacific day. `complete_through` moves to the end of the last day the API returned, not to the requested end. When no rows come back, the watermarks stay where they are until F8 settles what an empty answer means.
- **Re-read and provisional values.** Each incremental run re-reads the last 4 days, which covers the 72-hour latency plus one day. A day stays `provisional` while it is inside that window, so a value the next run may replace is never shown as final; this means `data_delay_hours` of 120, counted from the day's start. Lifetime totals of videos published in the last 4 days are provisional for the same reason.
- **Incomplete coverage.** Days after `complete_through` are not yet available: coverage shows the date, and nothing is filled with zeros. A run that stopped between pages leaves the stream `partial` (009). A snapshot that was missed stays missing.
- **History.** 90 days are read at connect, and a backfill reaches up to 730 days unless F10 shows less. Freshness turns `stale` 36 hours after the last successful run.

## 4. Policy constraints

### 4.1 Storage and refresh

- **Analytics and statistics.** Analytics (`channel_daily`, `video_totals`) and statistics (`channel`, the `videos` counters) come from the owner's authorization. They are kept for the life of the connection, at most 730 days (D11). Authorization is confirmed at least every 7 days, where the policy requires 30 (D6), and the daily inventory checks every 30 days that each video still exists (P-1 III.E.4.b).
- **Other Authorized Data.** This covers the channel title used as label, and each video's publish time, duration, privacy status and live state. The daily runs refresh it, and `tracking_lifecycle` deletes anything not refreshed within 30 days (P-1 III.E.4.c).
- **Never stored.** Titles, descriptions, thumbnails, tags, comments, captions and media are never stored, and `fields` keeps them out of the answers.
- **No non-authorized data.** The product makes no public lookup of other channels, so no competitor or benchmark reads take place.
- **Additional terms.** The 36-month window and derived metrics need the P-4 application (D17).

### 4.2 Deletion and revocation flow

| Trigger | Required by | Proposed handling |
|---|---|---|
| Disconnect in the product (Owner or Admin) | P-1 III.D.2: revoke right away, delete within 7 days | The 009 teardown revokes (subject to the D5 rule for account-wide grants), destroys the tokens and purges within the teardown deadline of at most 72 hours. |
| Revocation in Google account settings, or a token that can no longer be refreshed | P-1 III.D.2: delete within 30 days | Detected at the next refresh (`invalid_grant`), at most 7 days later (D6). The connection is `reconnect_required` for at most 14 days, then disconnected and purged automatically; in the worst case the purge completes within about 24 days. |
| The channel owner asks for deletion | P-1 III.E.4.g: within 7 days | Handled by an agency disconnect or the Spec 003 deletion-request flow. Google sends no deletion callback, so a documented support procedure (020) covers requests that reach the operator. |
| A client, agency or user account is closed | P-1 III.E.4.g: within 7 days | 017 offboarding disconnects every connection of the closed scope (dependency recorded here). |
| A video is deleted on YouTube | P-1 III.E.4.b: verify every 30 days | The daily inventory detects it, and the video's records are purged from every stream of the connection. |
| Termination or loss of API access | P-2 section 24.3: immediately | An operator command disconnects and purges every YouTube connection (011-C), and the adapter setting is the kill switch. |

### 4.3 Visibility, aggregation and derived metrics

- **Visibility.** Data is shown only inside the client that connected the channel, to members with client visibility. The connect records the authorizing person's express approval of the agency and the client's members as agents (D13, P-1 III.E.3).
- **No aggregation or comparison.** Nothing is aggregated across clients or agencies, which belong to different owners. There are no cross-channel rankings, benchmarks or scores, and no derived metrics or ratios (P-1 III.E.2, III.E.4.h).
- **Calculations.** Only simple sums over periods within one channel are allowed (P-3), and YouTube's averages are never averaged again. Anything more needs the P-4 terms (D12).
- **Tagged-link attribution.** Evidence from Spec 005 links and Spec 008 attribution stays separate. It is shown in its own section with a clear disclosure that it does not come from YouTube. There is no revenue per view, no cross-source score, and no joining of YouTube metrics with lead or revenue records (spec acceptance criterion 4).
- **Limited Use (P-8).** Data serves only the user-facing analytics: no sale, advertising use or transfer. Platform staff read it only under the P-8 exceptions, a constraint for the support tooling of 019 and 020.

### 4.4 Obligations outside 011

The product's privacy policy and terms need the III.A content: the use of YouTube API Services, links to the YouTube Terms of Service and the Google Privacy Policy, and revocation through the Google security settings page. Other obligations:

- YouTube attribution, with the YouTube icon next to YouTube data and no "YouTube" in the product name (P-6).
- Production accounts for YouTube audits (III.H).
- A change-of-control notice (P-2).

These belong to 016, 018 and 020 and are listed so they are not lost.

### 4.5 Re-verification of the policy rows

The stale rows `youtube.authorized_analytics` and `youtube.other_data` (researched 2026-11-03) agree with today's reading. Under D-025 they become current only in 011-C, before the live adapter runs, with a review date. The proposed text is:

- `youtube.authorized_analytics`:
  - **Retention:** "While necessary, at most 730 days (Q-012 proposal); authorization confirmed at least every 30 days; videos checked for deletion every 30 days".
  - **Deletion:** "In-app revocation: revoke at once, delete within 7 days; revocation in Google settings or an unrefreshable token: within 30 days; user request or account deletion: 7 days; termination: immediately".
  - **Callback:** "No deletion callback; refresh failures detect revocation; RISC not used".
  - **Use limits:** "Limited Use; the authorizing user and expressly approved agents only; aggregation within one content owner; no derived metrics without the additional terms; non-YouTube data disclosed".
- `youtube.other_data`: "Labels and video attributes refreshed or deleted within 30 days; non-authorized statistics at most 30 days; none collected at launch".

## 5. Decisions for the owner

| ID | Decision | Recommendation | Main alternatives | Evidence |
|---|---|---|---|---|
| D1 | Data sources for launch | The YouTube Analytics API (`reports.query`) for channel and video analytics, and the Data API v3 for the channel snapshot and the video inventory. Channels are authorized by their owner or a manager; content owner (CMS) reports are excluded. The Reporting API is deferred. | Reporting API bulk reports: only 30 days of history when a job is created, 48 hours to the first report, CSV ingestion and replacement reports, and thumbnail impressions in addition. Or the Data API alone, with public counters only. | YT-8, YT-9, YT-15, YT-16 |
| D2 | Scopes and partial consent | Request only `youtube.readonly` and `yt-analytics.readonly`, with no monetary, identity or write scopes. Install a connection only when both are granted. Otherwise refuse it with a fixed error that asks the user to grant both. | Install with the analytics streams `unsupported`. Or add `yt-analytics-monetary.readonly` for revenue metrics, which serve Partner Program channels only. | G-4, G-5, P-8, YT-9 |
| D3 | OAuth hardening | Keep the 009 protections: single-use state, session binding, and a server-side exchange with the client secret. Add PKCE `S256` when 011-B shows that the Web client accepts and enforces it. | Block the launch until PKCE is confirmed. | G-1, G-3 |
| D4 | Token refresh | Request offline access with `prompt=consent` on every connect and reconnect. Refresh before a call when the access token expires within 5 minutes. After an unexpected `401`, make one refresh, then mark the connection `reconnect_required`. | Refresh only after a `401`, which spends quota on an invalid request on almost every run. | G-1, G-2, YT-1 |
| D5 | Account-wide Google grants | Add a `revocation_scope` value for grants shared by every token of an account. A reconnect destroys the previous tokens without revoking them. A refused new grant, or a disconnect, revokes only when no other live connection holds tokens for that channel. Otherwise the tokens are destroyed and the revocation is recorded as `shared`, and the last such connection revokes. | Always revoke: one client's disconnect then forces every other client with that channel to reconnect, and a refused duplicate connect breaks the working connection. Or allow one live connection per channel across all agencies, which reveals other tenants' connections. | G-1, P-1 III.D.2, D-048 |
| D6 | Authorization checks and lost access | Refresh at least every 7 days, even without a sync. `invalid_grant` makes the connection `reconnect_required`. After 14 days without a reconnect, disconnect and purge automatically with reason `authorization_lost`. | Purge at the first failed refresh. Or keep the 009 behavior, which keeps data without valid authorization. | P-1 III.D.2, III.E.4.b, P-3 |
| D7 | Streams | Four streams (section 3.1): `channel`, `channel_daily`, `videos` and `video_totals`. No per-video daily series at launch. | Add per-video daily series for recent videos once 011-B shows the Analytics quota. Or launch with the channel streams only. | Section 3.1, YT-2 to YT-4, YT-13 |
| D8 | Metric catalog | The section 3.2 catalog, using the provider's metric names, with the exclusions listed there. Product types come from `creatorContentType`. A missing value is `not_returned`, never 0, and the dates of the view-count definition changes are recorded. | Add demographics and geography with a display rule and a retention period. Or start with channel metrics only. | YT-10, YT-11, YT-14, P-3 |
| D9 | Time and completeness | Section 3.3: Pacific days with zone-correct boundaries, `complete_through` at the last day returned, and values provisional inside the 4-day re-read window. History is 90 days at connect, with backfill up to 730 days unless 011-B shows less. | UTC days, which do not match YouTube's daily totals. | YT-10, YT-12, YT-15 |
| D10 | Quota budget | Buckets per API with the Pacific reset. Data API: a provider cap of 9,000 of the 10,000 units and 100 units per connection per day, enough for a channel of about 2,000 videos. Analytics: 30 requests per connection per day, with a provider cap set from the console value seen in 011-B. `quotaExceeded` defers the run to the next reset. A quota extension waits for the audit (011-D) and for Q-004 load figures. | Keep the 009 model of one unit per UTC day. Or request a quota extension now. | YT-1, YT-5, YT-6, YT-12 |
| D11 | Retention and stored data (Q-012 proposal) | Analytics and statistics for the life of the connection, at most 730 days, under the D6 checks. Attributes are limited to the video ID, publish time, duration, privacy status and live state, plus the channel title as label; each is deleted when not refreshed for 30 days. No titles, descriptions, thumbnails, tags, comments or captions are stored. Records of deleted videos are purged, and an operator purge command covers the loss of API access. | Keep everything for only 30 days, which is simplest but loses history. Or keep 36 months after a P-4 approval. | P-1 III.E.4, P-2 section 24.3, P-4 |
| D12 | Display and combination rules (for 016 and 018) | Data is shown per channel inside the connecting client, and only simple sums within one channel are allowed. No aggregation across clients or agencies, and no rankings, scores or ratios. Tagged-link evidence goes in a separate section, disclosed as not coming from YouTube. YouTube attribution follows the Branding Guidelines, and the product name does not use "YouTube". | Apply for the P-4 additional terms to allow derived metrics and benchmarks. | P-1 III.E.2, III.E.4.h, P-3, P-4, P-6 |
| D13 | Agent approval | The connect request carries an explicit approval, recorded with its time and the disclosure version: the person who authorizes the channel approves the agency and the client's members as agents. The wording waits for the owner's brief (D-039). | Rely on the agency's own contract with its client, which the policy does not mention. | P-1 III.E.3 |
| D14 | Synthetic adapter first | 011-A: a YouTube-shaped synthetic adapter and the runtime extensions of D2 to D13, with migration 0015 tested on disposable PostgreSQL and no live call. | Build the live adapter directly after 011-B. | 010-A precedent |
| D15 | Google Cloud project | A new project used only for the YouTube connector: External user type, Testing status, the owner as test user, the YouTube Data API v3 and YouTube Analytics API enabled, and a Web application client with the loopback callback. It stays separate from the project of the Google sign-in and the Gmail sender. | Reuse the existing project: revoking a YouTube grant would also revoke any Gmail sender token issued to the same Google account under that project, and verification would cover both uses. | G-1, G-2, P-1 III.D.1 |
| D16 | Feasibility check (011-B) | An owner-operated check with a test channel the owner controls. Claude prepares a checklist and a read-only local tool that uses only the standard library and python-dotenv (already a dependency). Credentials stay only in the ignored `.env`, and only redacted evidence enters the repository. | Defer live access until after 011-A and design on documentation only. | 010-B precedent, section 7 |
| D17 | Verification and audit (011-D) | Listed now, not started. Brand and sensitive-scope verification follow once HTTPS hosting and a privacy policy exist (020). The compliance audit and quota extension follow when Q-004 load needs them. The P-4 application follows only if the owner wants derived metrics. | Start verification now, which needs a verified domain and production URLs that do not exist yet. | G-6, YT-6, P-4 |

Open questions: Q-001 (YouTube part) is answered by D1, D7 and D8 if they are approved. Q-004 stays open for budgets and quota extension, and Q-012 for the retention proposal in D11.

## 6. Proposed slices

1. **011-A: YouTube-shaped synthetic adapter and runtime extensions** (D14).
   - **Scope:** a synthetic adapter `synthetic_youtube` that reproduces the documented shapes.
   - **Runtime extensions:** refresh ahead of expiry; the D2 scope check; the D5 rules for account-wide grants; the D6 authorization check and grace purge; quota buckets per API with a Pacific day and deferral on `quotaExceeded`; Pacific-day watermarks; wider product types; record attributes and label refresh times with 30-day deletion; deleted-object purge; retention per provider; the non-additive marker; and the D13 agent approval.
   - **Migration:** `0015` with the columns these need, specified in a design note after approval, on disposable PostgreSQL only.
   - **Tests:** `backend/tests/integration/test_connector_youtube.py`, covering:
     - the authorization parameters (offline access, consent, PKCE only when declared);
     - partial consent refused without harming other connections;
     - refresh ahead of expiry with no failed call;
     - account-wide grants: two clients with the same channel, disconnect, reconnect, and a refused duplicate connect;
     - the 7-day check and the purge after 14 days in `reconnect_required`;
     - the Pacific quota day and a `quotaExceeded` deferral that is not counted as a failure;
     - separate buckets;
     - Pacific days across a daylight-saving change, with `complete_through`, provisional values and no filling with zeros;
     - product types and `not_returned`;
     - attributes and labels deleted after 30 days without refresh;
     - a deleted video purged from every stream;
     - 730-day retention and privileges;
     - tenant isolation;
     - a mutation check of each safeguard.
   - **Evidence:** commands and counts, migration upgrade and downgrade, the OpenAPI snapshot, ruff, and the full suite.
2. **011-B: feasibility check** (D15, D16, acceptance criterion 1).
   - **Preparation:** a checklist (`feasibility-checklist.md`) and a read-only tool `backend/app/youtube_feasibility.py`. Its offline tests use a fake transport and cover read-only scopes, redaction, the call budget and the loopback receiver.
   - **Run:** the owner runs it after the console steps of section 8. Dated, redacted evidence answering F1 to F14 goes into `evidence.md`, and any answer that differs from this review becomes a proposed amendment for the owner (like D-054).
3. **011-C: live adapter.**
   - **Adapter:** `app.connectors.youtube`, off by default. It is registered only while the re-verified `youtube.authorized_analytics` and `youtube.other_data` rows are current. Migration `0016` admits the provider.
   - **Tests and checks:** fixture tests against an in-memory Google API; a browser connect through the loopback API callback with the owner's channel; a read-only adapter check; and the full suite on disposable PostgreSQL. No customer channel is connected.
4. **011-D: verification and quota** (owner business actions, D17).
   - **Actions:** brand and sensitive-scope verification (demo video, a homepage and privacy policy on a verified domain), the "In production" publishing status, the compliance audit with a quota extension, and the optional P-4 application.
   - **Prerequisites:** HTTPS hosting and the legal pages (020).
   - **Evidence:** dates and outcomes only.

## 7. Feasibility questions for 011-B

| ID | Question |
|---|---|
| F1 | What does the token answer contain (`refresh_token`, `scope`, `expires_in`), and what happens when the user clears one of the two scopes on the consent screen? |
| F2 | Does the Web client accept PKCE `S256`, and does it refuse a wrong verifier? |
| F3 | Does refresh work, and in Testing does it fail with `invalid_grant` after 7 days? |
| F4 | What does `channels.list?mine=true` return? How is the channel chosen for an account with several channels or brand accounts, and what does a hidden subscriber count look like to the owner? |
| F5 | Does the uploads playlist list private and unlisted videos? What is the maximum number of IDs per `videos.list` and `batchGetStats` call? Does `fields` work as described, and how do hidden likes and disabled comments appear? |
| F6 | Does `reports.query` succeed with `yt-analytics.readonly` without `youtube.readonly`? |
| F7 | How many units does each call record in the console, where does `batchGetStats` count, and what shape do `quotaExceeded` and rate-limit errors take? |
| F8 | In day reports, which is the last day returned relative to the current Pacific day? Are days without activity returned as zero or omitted? Do recent days change on later reads, and is the whole catalog accepted in one query? |
| F9 | Does `dimensions=video` work with a filter of several IDs and with `creatorContentType`, and how does the top-200 sorted report behave? |
| F10 | What is the earliest date that returns data for the test channel, and what happens to a start date before the channel existed? |
| F11 | What Analytics API quota does the console show? |
| F12 | With two consents for the same channel, does revoking one token stop the other? |
| F13 | After the owner removes access in the Google account settings, what does a refresh answer? |
| F14 | What do an invalid or expired token and insufficient scopes return? |

The tool receives the redirect on a loopback address, so the owner does not need to paste the redirect URL as in 010-B.

## 8. Owner steps in the Google Cloud console (before 011-B, after D15 and D16 are approved)

Console labels can change; the names below are those in use at the time of writing.

1. **Project.** Create a new Google Cloud project used only for the YouTube connector, and do not reuse the Google sign-in or Gmail project (D15). Project inactivity of 90 days and OAuth client inactivity of six months lead to curtailment or deletion (P-1 III.D.4, G-7).
2. **APIs.** Under APIs and Services, Library, enable **YouTube Data API v3** and **YouTube Analytics API**. The Reporting API is not needed.
3. **Consent screen.** Under Google Auth Platform (the OAuth consent screen), set:
   - **Branding:** an app name that does not contain "YouTube" or a variant (P-6), and a support email.
   - **Audience:** user type **External**, publishing status **Testing**, and the owner's Google account as test user.
   - **Data access:** only `https://www.googleapis.com/auth/youtube.readonly` and `https://www.googleapis.com/auth/yt-analytics.readonly`. Note whether the console labels them sensitive.
4. **Client.** Under Clients, create an OAuth client of type **Web application** with the authorized redirect URI `http://127.0.0.1:8000/connectors/oauth/callback`. The 011-B checklist may add one more loopback URI for the tool.
5. **Credentials.** Put the client ID and secret only in the ignored `C:\Code\Tracking-system\.env` under names that the 011-B checklist fixes. Never paste them in the chat, Git or screenshots.
6. **Test channel.** Use a channel the owner controls and uses only for testing, preferably a brand account channel. It should have at least one public long-form video, one Short, and one unlisted or private video; a few days of activity help F8.
7. **Nothing to submit.** Do not submit verification, the audit form or a quota request. Refresh tokens issued in Testing expire after 7 days, which is expected.
8. **Report.** Tell Claude that the steps are done, without any value.

## 9. Not authorized by this preparation

This preparation does not authorize:

- implementation, migrations or new dependencies;
- a Google Cloud project, any live Google call, or verification, audit or quota submissions;
- customer channels;
- native `tracking_sys` migration;
- push, pull request, merge or deployment.

## 10. Owner decisions

### D15 decided: the existing project `connectapp` (D-057, 2026-11-18)

The owner chose the alternative of D15: the YouTube connector's development work uses the existing Google Cloud project `connectapp`, which also holds the Google sign-in and the Gmail sender. The owner had already enabled the YouTube Data API v3 and the YouTube Analytics API there. This decision is about the project only; D1-D14, D16 and D17 remain pending.

Consequences accepted with this choice (G-1, G-6):

- **Revocation.** Revoking a YouTube grant revokes every token that Google issued to the same Google account under this project. That includes a Gmail sender refresh token held by the same account.
- **Verification.** The project's consent screen and its verification cover the sign-in, the Gmail sender and the YouTube scopes together.
- **Quota and inactivity.** All three uses share the project's quotas and inactivity rules.

Safeguards that follow from it:

1. **A separate client.** The connector uses its own Web application OAuth client, never the sign-in Web client or the Gmail sender's Desktop client. The proposed 011-C settings refuse a client ID equal to either of them, as the Gmail sender settings already refuse the sign-in client's ID.
2. **A separate test account.** The test channel belongs to a Google account other than the one that authorized the Gmail sender. If it cannot, the owner accepts that a YouTube revocation test (F12, F13) also ends the Gmail sender's refresh token, which then needs the sender helper again.
3. **Unchanged consent screen.** The consent screen keeps its current name and user type; only the two YouTube scopes are added under Data access. The sign-in keeps requesting identity scopes only.
4. **Production review.** The project used in production is reviewed again before verification and the quota audit (011-D), because P-1 III.D.1 binds the API client to exactly one project and the audit is tied to it.

The console steps of section 8 change as follows: skip step 1, keep the existing branding, confirm in Audience that the publishing status is Testing and that the test channel's account is a test user, and create a new Web application client in step 4.

### Console setup observed (2026-11-18)

The owner's screenshots of `connectapp` show the following. No identifier or credential is recorded here.

- **APIs.** The YouTube Data API v3 and the YouTube Analytics API are enabled.
- **Audience.** The publishing status is Testing, with one test user, and Branding states that verification is not required while the app is in Testing.
- **Scope classification.** The console lists `youtube.readonly` under sensitive scopes and `yt-analytics.readonly` under non-sensitive scopes, with no restricted scope. This answers the classification item of section 1. Production needs sensitive-scope verification for `youtube.readonly` (demo video, scope justification, privacy policy), and the CASA assessment for restricted scopes does not apply (G-6, D17).
- **Scopes still to complete.** The latest Data access screenshot lists only `yt-analytics.readonly`, so `youtube.readonly` has to be added again and saved before 011-B.
- **Client.** A separate Web application client for the connector was created with the redirect URI `http://127.0.0.1:8000/connectors/oauth/callback`.
- **Secret rotation.** The client ID and secret were pasted into the conversation on 2026-11-18. They were not used or stored. The owner rotates the secret and keeps the new values only in the ignored `.env`; no live call uses the exposed secret.
