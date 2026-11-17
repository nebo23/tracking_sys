# Specification 010 entry review: Instagram analytics

Prepared: 2026-11-17 on `codex/spec-010-instagram` from merged `main` at `4039600` (PR 9; Spec 009 merged in PR 8 at `4abcbc6`). Authority: D-052, preparation only. Status: proposals for owner decision. Nothing here approves implementation, schema, dependencies, a Meta app, live calls or customer data.

## 1. Sources and what they establish

Official Meta developer pages read on 2026-11-17. None shows a last-updated date; the account insights page names Graph API v27.0 as the latest version. Documentation is not acceptance evidence: acceptance criterion 1 still requires an owner-authorized test account (section 6).

| ID | Source | Established from the page |
|---|---|---|
| IG-1 | [Instagram Platform overview](https://developers.facebook.com/docs/instagram-platform/overview) | Three setups: Unified Login (recommended for new integrations), Instagram Login (`graph.instagram.com`, no Facebook Page) and Facebook Login (`graph.facebook.com`, a linked Facebook Page). Professional accounts only: business or creator; personal accounts are not supported. Standard Access covers accounts the app owns or manages; Advanced Access, through App Review and Business Verification, is needed for other accounts. Instagram Business Use Case rate limit: calls within 24 hours = 4,800 x the account's impressions in the last 24 hours, per app and app-user pair. Webhooks are recommended to reduce calls. |
| IG-2 | [Account insights reference](https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights) | Permissions: Instagram Login `instagram_business_basic` and `instagram_business_manage_insights`; Facebook Login `instagram_basic`, `instagram_manage_insights` and `pages_read_engagement`. Metrics: `accounts_engaged`, `comments`, `engaged_audience_demographics`, `follows_and_unfollows`, `follower_demographics`, `likes`, `profile_links_taps`, `reach`, `replies`, `reposts`, `saves`, `shares`, `total_interactions`, `views`; `impressions` deprecated from v22.0 and for all versions from 2025-04-21, replaced by `views`. `since`/`until` are inclusive Unix times (default: the last 24 hours); no maximum look-back is stated. Demographics need a `timeframe`, return the top 45 values, and need at least 100 followers or engagements. Data can be delayed up to 48 hours. Missing data returns an empty data set, not 0. |
| IG-3 | [Media insights reference](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights) | Metrics per media product type: FEED, REELS and STORY lists (for example `reach`, `views`, `likes`, `comments`, `saved`, `shares`, `total_interactions`; REELS adds `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time` and `reels_skip_rate`; STORY adds `navigation`, `link_clicks` and `replies`). `facebook_views`, `total_comments`, `total_likes` and `total_views` are Facebook Login only. `impressions` is deprecated for media created after 2024-07-02. The returned period is always `lifetime`. Metrics are kept up to 2 years and may be delayed up to 48 hours. Album children have no insights. Story metrics exist for 24 hours only (longer if added to a highlight); fewer than 5 viewers returns error 10. |
| IG-4 | [Business Login for Instagram](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login) | Authorization code valid 1 hour, single use. Short-lived token 1 hour; long-lived token 60 days, obtained server-side; it is refreshed itself (`ig_refresh_token`) when at least 24 hours old and unexpired; an unrefreshed token expires and cannot be refreshed. There is no separate refresh token. |
| IG-5 | [Instagram webhooks](https://developers.facebook.com/docs/instagram-platform/webhooks) | Notifications for comments, mentions, `story_insights`, messages and other activity; availability depends on the setup; the insights webhook is not supported with Instagram Login; no historical store, so deliveries must be deduplicated. |
| S-61 to S-66 | Existing [privacy sources](../../research_notes/privacy-data-policy/sources.md) | Meta Platform Terms and data deletion callback, Developer Policies, Data Use Checkup. Basis of the `meta.platform_data` and `instagram.login_api` rows, still `stale` in `app.privacy.providers`. |

Not established by any page read: PKCE support on Instagram Login, a token revocation endpoint, the exact webhook field names (the [fields matrix](https://developers.facebook.com/docs/instagram-platform/webhooks/fields) was not read), the maximum history of account insights, and rate-limit response headers. These go to the feasibility check.

## 2. What Spec 009 provides and where Instagram differs

| 009 runtime contract | Instagram fact | Consequence for 010 |
|---|---|---|
| `Capability.pkce` is always `S256` | Not documented for Instagram Login | Allow `pkce: None` only where the provider documents none, keeping single-use state and the session binding (D3) |
| Separate access and refresh tokens; one refresh attempt at expiry | One long-lived token, refreshed itself after 24 hours and before 60 days | A refresh that replaces the access token, scheduled before expiry rather than at failure (D4) |
| `revoke(token)` with `done`, `unsupported` or failure | No revocation endpoint documented; deauthorize and data deletion callbacks are required app settings | Report `unsupported` revocation and add the signed deauthorize and deletion callbacks (D5) |
| One stream per capability | Account daily insights, media objects with lifetime insights, and 24-hour stories | Several streams per connection, each with its own checkpoint and interval (D6) |
| Metric support by account kind | Support by media product type and login path; thresholds (100 followers, 5 story viewers); empty data instead of 0 | `MetricSpec` gains media product types; empty or threshold answers are stored as `missing` with a reason, never 0 (D7) |
| Fixed daily quota and per-connection allocation | Rolling 24-hour limit proportional to the account's impressions; 48-hour data delay | Defer on the provider's rate-limit answer; overlap of at least 2 days; freshness judged against the 48-hour delay (D8) |
| Synthetic per-grant revocation and webhook scheme | `story_insights` webhook only on some setups; other webhooks deduplicated by event | Reuse the 009-D delivery table; stories polled when the webhook is unavailable (D6) |

The 009 lifecycle, teardown and purge (Spec 003 case D3), attempt fencing, usage records, coverage states and tenant isolation apply unchanged.

## 3. Privacy and retention

- Meta Platform Data, including derived and aggregated values, may be kept only while necessary and must be deleted on user, client or Meta request (S-61). The existing purge on disconnect covers the connection; the deletion callback must purge the same data for the account it names, in every client connected to it (D5).
- Demographic metrics (`follower_demographics`, `engaged_audience_demographics`) are aggregates about other people. They are excluded from the proposed launch catalog until Q-012 retention and a display rule exist (D2).
- Media captions, images and comments are not stored: records hold the provider object ID, product type, timestamps and metric values only, as in 009 (S-65 forbids mere import or backup of content).
- Retention of stored metric values remains Q-012. The proposal keeps them for the life of the connection, never longer than the provider's 2-year window, and purges them on disconnect, deauthorization or deletion request.

## 4. Proposed slices

1. **010-A: Instagram-shaped synthetic adapter and runtime extensions.** A second synthetic adapter that reproduces the documented shapes (long-lived token refresh, several streams, media product types, empty data, thresholds, 48-hour delay, rate-limit answers, signed deauthorize and deletion callbacks), with the 009 contract extensions of D3 to D8 and their migration, tested on disposable PostgreSQL. No live call, no Meta app.
2. **010-B: feasibility check (acceptance criterion 1).** Owner-operated, with an owner-created Meta app in development mode and an owner-controlled professional test account. Records dated evidence of the login route, granted scopes, returned fields per account kind and media type, history window, token behavior, revocation behavior and rate-limit signals. Only synthetic or redacted values enter the repository.
3. **010-C: Instagram adapter.** Implements the real adapter against the 010-B evidence, with recorded-response fixtures whose values are replaced by synthetic ones, and re-verifies the `meta.platform_data` and `instagram.login_api` rows. Live use stays limited to the owner's test account.
4. **010-D: access for customer accounts.** App Review, Advanced Access and Business Verification are owner business actions and a production gate (020); they are listed, not performed.

## 5. Decisions for the owner

| ID | Decision | Recommendation | Main alternative |
|---|---|---|---|
| D1 | Login path for launch | **Instagram Login** (`instagram_business_basic`, `instagram_business_manage_insights`): business and creator accounts without a Facebook Page, the broadest reach for agency clients | Facebook Login, which needs a linked Page but adds the `story_insights` webhook and shares the Meta app with Spec 014 ads; or Unified Login, which needs a Business Manager system user |
| D2 | Launch metric catalog | Account: `reach`, `views`, `accounts_engaged`, `total_interactions`, `likes`, `comments`, `shares`, `saves`, `replies`, `follows_and_unfollows`, `profile_links_taps`. Media: FEED `reach`, `views`, `likes`, `comments`, `saved`, `shares`, `total_interactions`, `profile_visits`, `follows`; REELS adds `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time`, `reels_skip_rate`; STORY `reach`, `views`, `replies`, `navigation`, `link_clicks`. Exclude deprecated `impressions`, Facebook-Login-only metrics and demographics. Names stay provisional until 010-B confirms them | Add the demographic metrics now with a retention rule; or start with account metrics only |
| D3 | OAuth hardening without PKCE | Keep single-use state, the HttpOnly session binding and server-side exchange; use PKCE when the feasibility check shows support | Block launch until PKCE is confirmed |
| D4 | Token refresh | Refresh the long-lived token once it is 24 hours old and at least 7 days before expiry, in the worker; a failed or late refresh moves the connection to `reconnect_required` with history kept | Refresh only on a `401`, which risks silent expiry of idle connections |
| D5 | Deauthorization and deletion | Treat revocation as `unsupported` and tell the owner to remove access in Instagram settings; add signed deauthorize and data deletion callback routes that disconnect and purge every connection of the named account and return Meta's confirmation code and status URL | Disconnect only, without a deletion status page |
| D6 | Streams and stories | Three streams per connection: account insights daily, media objects and lifetime insights daily with a 2-day overlap, stories every 2 hours while they are live; on Instagram Login stories are polled because the insights webhook is not available | Exclude stories from launch |
| D7 | Metric availability | Extend `MetricSpec` with media product types; store an empty answer, a threshold refusal (fewer than 100 followers, fewer than 5 story viewers) or an unsupported metric as `missing` or `unsupported` with a reason code, never as 0 | Hide such metrics entirely, which loses the explanation |
| D8 | Limits and freshness | Use the provider's rate-limit answers for deferral (009 policy), keep a per-connection daily call allocation as a safety cap, overlap 2 days for the 48-hour delay, and show data newer than 48 hours as provisional | Keep the 009 fixed quota model unchanged |
| D9 | Retention (Q-012 proposal for this data) | Keep metric values for the life of the connection, at most 2 years, purge on disconnect, deauthorization or deletion request; store no media content | Shorter fixed retention, such as 13 months like Spec 004 events |
| D10 | Feasibility check (010-B) | Approve that the owner creates a Meta app in development mode and connects one owner-controlled professional test account; Claude prepares the checklist and a local script, keeps all credentials in the ignored `.env`, and records only redacted evidence | Defer all live access until after 010-A, accepting that the adapter design rests on documentation only |

## 6. Owner steps required before any live call (010-B)

1. Create or choose a Meta developer account and a Meta app in development mode; add the Instagram product with Instagram Login.
2. Convert an owner-controlled Instagram account to a professional (business or creator) account and add it as an app tester.
3. Put the app ID and secret in the ignored `.env` only; never in chat, Git or screenshots.
4. Approve the feasibility run. Without this approval nothing contacts Meta.

## 7. Not authorized by this preparation

Implementation, migrations, new dependencies, a Meta app, any live Meta call, App Review or Business Verification submissions, customer accounts, native `tracking_sys` migration, pull request, merge and deployment.
