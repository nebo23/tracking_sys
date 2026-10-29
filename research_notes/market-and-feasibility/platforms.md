# Platform feasibility and tracking limitations
Research checked: 2026-10-28. English revision: 2026-10-29; this editorial revision does not refresh API terms or pricing.

Status: official-source research, not scope approval or proof that our application has access. No customer accounts were connected, developer credits purchased, or payment accounts created. Design proposals require owner review.

## Social platforms
Authorized account reporting is feasible within provider-specific permissions, history, quotas, cost, and policies. Public competitor data is more limited. No reviewed source establishes the ability to observe every viewer action or link every view to a lead.

### Instagram and Meta
Meta's official Postman collection describes Business and Creator accounts. The Facebook Login path requires a professional Instagram account linked to a Facebook Page; it does not support consumer/personal accounts. Some public professional-account metadata is available, which does not grant private competitor insights. [Meta Instagram API](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-894be833-d0b6-4877-859e-c61ae6474d64)

Instagram Login is a separate path without advertising or tagging access in the referenced collection. Published permissions included instagram_business_basic, instagram_business_manage_messages, and instagram_business_manage_comments; publishing needs a separate permission. [Instagram Login](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-3fe78620-2258-44b6-893f-42d76c7200d7)

Messaging requires the Instagram user to initiate contact, appropriate permission, and a valid token. The collection states that group messaging is unsupported, inactive message requests older than 30 days are not returned, and shared-post webhooks provide the content URL rather than complete content. [Messaging](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-3a63181c-e5c6-4890-96dd-e4d425bef5e0)

Direct Meta documentation could not be fully retrieved in this research round. Exact Insights permissions, metric names, history, quotas, freshness, Advanced Access, App Review, and business verification remain unverified. Recent secondary descriptions of instagram_manage_insights or instagram_business_manage_insights are verification candidates, not final contracts. Recheck the official references and actual application dashboard. [Overview](https://developers.facebook.com/docs/instagram-platform/overview), [Insights](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/insights), [permissions](https://developers.facebook.com/docs/permissions/reference)

### YouTube
The Data API offers public metadata for certain operations and authorized private information where permitted. Analytics/Reporting APIs require the channel or content owner's authorization; knowing a channel name does not grant private analytics. [Data API](https://developers.google.com/youtube/data/getting-started), [Analytics](https://developers.google.com/youtube/analytics/)

Analytics uses OAuth 2.0 with user consent. Relevant scopes include yt-analytics.readonly and yt-analytics-monetary.readonly; reports.query also documents youtube.readonly requirements. A service account does not substitute for the supported channel-owner authorization flow. Public applications may require verification. [Authorization](https://developers.google.com/youtube/reporting/guides/authorization), [reports.query](https://developers.google.com/youtube/analytics/reference/reports/query)

September 2026 documentation updates described 48-72 hours of analytics processing latency. Queries return through the last date complete for all requested metrics, not necessarily the requested final date. On-demand query execution does not make underlying data real time. Analytics days use Pacific time and daylight-saving boundaries. [Revision history](https://developers.google.com/youtube/reporting/revision_history), [data completeness](https://developers.google.com/youtube/analytics/data_model?hl=en), [dimensions](https://developers.google.com/youtube/analytics/dimensions)

The quota reference updated on October 15, 2026 described separate daily limits of 100 calls each for search.list and videos.insert, with 10,000 units for the remaining endpoints combined. channels.list and videos.list cost one unit; additional pages and invalid requests consume quota. These observations must be rechecked against the actual project Console rather than treated as guaranteed entitlements. [Quota reference](https://developers.google.com/youtube/data/determine_quota_cost)

Views, watch time, average viewing duration, and retention are aggregate metrics. They do not provide an individual viewer log that can be directly matched to a purchaser. [Metrics](https://developers.google.com/youtube/analytics/metrics), [data model](https://developers.google.com/youtube/analytics/data_model)

### LinkedIn
Community Management is a vetted product with Development and Standard access; Standard review requires a video demonstrating use cases. Page and member analytics depend on authentication, authorization, and program approval. Closure of r_member_social to new requests does not imply that all member analytics is unavailable. [Community Management](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview?view=li-lms-2026-10)

The researched documentation listed r_member_postAnalytics from version 202506 and r_member_profileAnalytics from 202504. Organization permissions and Lead Sync permission r_marketing_leadgen_automation are separate. [Access guide](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2025-11)

memberCreatorPostAnalytics provides authorized-member metrics such as impressions, reactions, comments, and reposts. DAILY aggregation is restricted for some metrics, and documented API/UI differences must be disclosed rather than silently treated as application errors. memberFollowersCount provides lifetime/daily followers under the relevant profile permission. [Post statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics?tabs=http&view=li-lms-2026-03), [follower statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/follower-statistics?tabs=http&view=li-lms-2026-04)

Version sunset dates require operational tracking. The researched overview warned that 202511 would sunset on November 16, 2026; choose and recheck a supported version before implementation. Exact Standard-tier quotas and per-metric history remain access-check tasks.

### X
Public metrics provide counts; non-public, organic, and promoted metrics require user context and owned content. The metric reference limited those private categories to posts within the previous 30 days. Click counts do not identify individual viewers or clickers. [Metric reference](https://docs.x.com/x-api/fundamentals/metrics)

The researched pay-per-use pricing listed USD 0.005 per Post resource read, USD 0.010 per User read, and a three-million Post-read limit per billing cycle. The USD 0.001 owned-read rate required the authenticated user to be the developer-app owner; it cannot be assumed for every agency client on one application. Spending caps can stop requests. Some activity webhooks are billed per event, and UTC-day billing deduplication was described as a soft guarantee. This does not replace our ingestion deduplication. Revalidate all prices before release. [Pricing](https://docs.x.com/x-api/getting-started/pricing)

### Proposed connector approach
Maintain account type, scopes, API version, metric definitions, historical window, freshness, status, and reason for each connection. Distinguish unavailable, pending, restricted, and stale data from zero. Preserve social aggregates, first-party touchpoints, and business outcomes separately; cross-platform reach is not unique people.

Run an authorized access check per platform before promising delivery. The first connector should follow approved customer workflows, not the order platforms were mentioned. Use polling, backfill, and webhooks only where supported. Maintain provider changelog and API sunset review as an ongoing operating responsibility.

No customer grant has been verified. Account types, account counts, history needs, and budgets remain unknown. The research does not establish that every native dashboard metric is available through an API.

## Connecting content, conversations, bookings, and sales
### Findings
GA4 User-ID is an internal identifier assigned to an authenticated user to connect supported sessions/devices. It is not a platform-viewer identity lookup or an identifier inferred from a name or IP address. [User-ID](https://developers.google.com/analytics/devguides/collection/ga4/user-id?hl=en)

Measurement Protocol complements website/application events; server-only collection can be partial. Attribution requires identifiers and session context; documented session-attribution use cases included session_id and delivery within 24 hours of session start. [Overview](https://developers.google.com/analytics/devguides/collection/protocol/ga4), [use cases](https://developers.google.com/analytics/devguides/collection/protocol/ga4/use-cases)

GA4 policies require appropriate notice and consent/opt-out according to the implementation and restrict personally identifiable information. The separate user-provided-data feature has specific normalization/hashing rules; it does not authorize raw email in URLs, event names, or User-ID. [Protocol policy](https://developers.google.com/analytics/devguides/collection/protocol/ga4/policy), [user-provided data](https://developers.google.com/analytics/devguides/collection/ga4/uid-data)

Manychat External Request is available on specified paid plans and sends selected contact/custom fields over HTTPS. Some Instagram contact fields must be collected in the workflow; they are not all available automatically. Test the actual plan, trigger, and origin/post fields. [External requests](https://help.manychat.com/hc/en-us/articles/14281285374364-Dev-Tools-External-request), [variables](https://help.manychat.com/hc/en-us/articles/14281183702556-Variables)

Twilio's WhatsApp interface documents ReferralCtwaClid and advertising referral fields for inbound Click-to-WhatsApp messages. Forwarded and FrequentlyForwarded are flags, not a complete forwarding chain. These findings apply to Twilio's interface and do not establish identical payloads for every provider or direct Meta integration. [Inbound webhook](https://www.twilio.com/docs/messaging/guides/webhook-request?display=embedded), [click-ID changelog](https://www.twilio.com/en-us/changelog/new--click-id--callback-parameter-for-inbound-whatsapp-messages-)

Calendly exposes invitee.created, invitee.canceled, and routing submissions. Rescheduling generates both creation and cancellation events; counting each as a new booking would inflate reports. UTM data can be passed through tracking fields, supported webhook plans are restricted, and old activity does not generate retroactive webhooks. [Webhooks](https://developer.calendly.com/docs/api-guides/receive-data-from-scheduled-events-in-real-time-with-webhook-subscriptions), [rescheduling](https://developer.calendly.com/docs/api-guides/trigger-automations-with-other-apps-when-invitees-schedule-or-cancel-events), [FAQ](https://developer.calendly.com/docs/getting-started/frequently-asked-questions), [plan availability](https://calendly.com/help/webhooks-overview)

Cal.com provides booking creation, cancellation, rescheduling, and no-show updates, with secrets for raw-body signature checks and versioned payloads. A trigger must be interpreted according to its source; it does not independently establish human attendance. [Cal.com webhooks](https://cal.com/docs/developing/guides/automation/webhooks)

Paymob distinguishes a processed transaction POST callback from a browser response redirect. Use HMAC-verified processed callbacks for state; the browser redirect may never complete. The reference includes refund, partial-refund, capture, void, and order identifiers. [Transaction callbacks](https://developers.paymob.com/paymob-docs/developers/transaction-callbacks)

Stripe signs webhooks and documents duplicate/out-of-order delivery. Verify signatures, process asynchronously, deduplicate, and subscribe only to needed event types. [Stripe webhooks](https://docs.stripe.com/webhooks)

### Proposed evidence chain
A possible organic journey is content -> placement-specific link/token -> first-party visit/form -> verified lead/contact -> booking/order/payment. Missing links remain unknown or explicitly self-reported/modeled; do not fill gaps with certainty.

Distinguish a WhatsApp-button click from a delivered message, a qualified lead, and a payment. A booking is not attendance; a conversation is not a sale. A generic wa.me link does not guarantee per-post attribution. Prefilled text may be removed, and missing codes reduce observable coverage.

Names, handles, and IP addresses alone are insufficient for identity merging. Use permitted identifiers scoped to a client with provenance, ambiguity review, and reversible merges. Hidden WhatsApp forwarding trees cannot be promised. YouTube aggregate retention cannot reveal the unobserved minute that caused a purchaser to buy.

Separate gross revenue, refunds, and net revenue from advertising platforms' conversion claims. Do not sum Meta, Google, and CRM conversions as independent sales. Spend ingestion and conversion delivery are separate from social insights; CAPI neither identifies every impression nor proves funnel completeness.

### Unresolved integration questions
Meta CAPI and Ads Insights pages returned rate-limit or login barriers in this research round. A secondary description of event_name plus event_id deduplication is not sufficient to approve exact windows or scopes. Recheck the official source during an authorized feasibility check. [CAPI deduplication](https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events/), [Ads Insights](https://developers.facebook.com/docs/marketing-api/insights/)

The final WhatsApp direct/provider route is undecided. Verify business-account ownership, onboarding, signatures, charges, templates/conversation rules, history, and coexistence for the chosen provider. No full-history access to ordinary WhatsApp Business conversations was established.

Payment eligibility, merchant geography/currencies, Stripe Connect versus merchant credentials, and Paymob onboarding remain open. LinkedIn Lead Sync, Meta Lead Ads, and Google Ads need independent scopes and specifications if approved. Privacy policy belongs inside the event pipeline; attribution does not justify collecting every message or personal field.

## Provider policies and production gates
### Findings
YouTube retention depends on data class. Some authorized analytics/statistics may be retained beyond 30 days with recurring authorization/deletion checks; other metadata requires refresh or deletion within 30 days. User deletion requests have a seven-day requirement in the researched policy. Avoid a single universal retention rule. [Developer policies](https://developers.google.com/youtube/terms/developer-policies)

The baseline policy restricts combining API data and inventing substitute metrics while permitting specified simple calculations. From June 2026, audited analytics developers could request additional derived-metric/storage terms; these are not automatically granted. Approved additional uses can permit some statistical/derived data for up to 36 months, while names, titles, and text retain refresh/deletion requirements. Clearly distinguish our metrics from YouTube metrics. [Policy guide](https://developers.google.com/youtube/terms/developer-policies-guide), [additional terms](https://developers.google.com/youtube/terms/derived-metrics-policy)

X requires stored content to reflect changes/deletions, promptly or within 24 hours following applicable requests under its published conditions, and restricts off-X matching. A token does not authorize unrestricted CRM matching or cross-tenant disclosure. [Developer policy](https://docs.x.com/developer-terms/policy)

### Proposed gates
These are proposed acceptance requirements, not completed tests.

| Gate | Evidence required |
|---|---|
| G1 Authorized connection | Actual account owner/type, scopes, application tier, API version, and correct agency/client binding |
| G2 Metric dictionary | Source definition, unit, dimensions, timezone, and nullable state; missing is not zero |
| G3 Actual read | Authorized account/content sample and API/native-dashboard comparison with explained differences |
| G4 History | Earliest/latest available dates, backfill cap, and late-data reconciliation window |
| G5 Cost and quotas | Per-tenant/global budgets, request/page/resource counts, throttling/backoff, and distinct financial versus API limits |
| G6 Security | Server-side encrypted tokens, least scopes, redacted logs, refresh, revocation, and reconnection |
| G7 Webhooks | Documented authentication/signature, durable receipt, acknowledgment, idempotency, replay, ordering, and quarantine |
| G8 Lifecycle | Client deletion, consent/grant withdrawal, content changes, permission changes, and data-class retention |
| G9 Attribution | Evidence for every join, model/window, unknown coverage, and no duplicate booking/refund |
| G10 Operations | Last successful synchronization, data-through date, error reason, runbook owner, alerts, kill switch, and sunset date |

Minimum cases include expired/revoked tokens, denied scopes, repeated callbacks, callback-before-source ordering, partial refunds, rescheduling, quotas, insufficient credit, pagination, deleted content, empty metrics, timezone boundaries, changed account access, and cross-tenant attempts.

A connector contract should record provider, api_version, account_type, required_scopes, access_status, resources, metric_definitions, native_timezone, history_window, latency_expectation, sync_strategy, quota_model, pricing_checked_at, webhook_auth, idempotency_key, deletion_policy, source_urls, verification_evidence, and owner_decision.

### Remaining gaps
There is no guarantee of complete coverage, application approval, or uninterrupted third-party service. Success means supported claims, sourced metrics and joins, visible limitations, and actual acceptance evidence.

Applicable markets, hosting location, controller/processor responsibilities, legal basis, and commercial retention remain undecided. These sources establish provider rules rather than legal advice. No defensible launch date exists before access approvals, authorized test accounts, and actual sale/booking providers are known.
