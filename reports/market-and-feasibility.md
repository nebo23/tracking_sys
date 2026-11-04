# Market and feasibility report
Research date: 2026-10-28. English revision: 2026-10-29; no pricing or API re-verification is implied.

**The core product is technically plausible, but its final capabilities depend on platform permissions, permitted data use, and demonstrated linkage between events and business outcomes.** The confirmed first release is a multi-agency SaaS combining social analytics and revenue attribution, using FastAPI, PostgreSQL, React, and Docker.

The source contains 109 features and 16 additional ideas across 15 categories. It is an extensive option map rather than an approved launch backlog. Existing products already offer many individual capabilities and substantial combinations. The proposed opportunity is a coherent agency workflow, auditable data, and integrations suited to customer needs. Commercial demand and differentiation remain hypotheses.

This research used official product, pricing, and technical documentation plus the owner's requirements. It did not include purchases, customer-account connections, competitor accuracy tests, or interviews. Prices, quotas, and access conditions must be rechecked before commitment. Some Meta references could not be retrieved directly. The [original requirements](https://drive.google.com/file/d/1Um4719Vwi3d71QHVO6pnipzka8cay0Tc/view) are documented in [source provenance](../docs/source/README.md); reference copies are preserved outside the project.

## Two complementary competitive categories
Attribution products connect visits and leads to financial outcomes. Social analytics products aggregate account/content performance and support agency reporting. Both belong in the confirmed launch. Follower/view statistics alone do not demonstrate sales attribution, and a revenue report alone does not meet the social-account requirement.

| Product or category | Relevant overlap | Pricing model and lesson |
|---|---|---|
| VidWorth | Video/Reel to lead, booking, payment; journey/replay; Kashier, ManyChat, Stripe | Monthly/annual subscription. Direct content-to-sale competitor; local payments alone do not establish uniqueness. [Product](https://www.vidworth.co/) |
| HYROS | Tracking, conversion delivery, analytics, integrations | Custom tracked-revenue pricing. Compete on verification, usability, and actual cost. [Pricing](https://hyros.com/pricing-ai-tracking) |
| Triple Whale | Pixel, multi-touch attribution, surveys, BI, AI; optional MMM/incrementality | GMV/package-based. Its broad scope does not justify reproducing everything at launch. [Pricing](https://www.triplewhale.com/pricing) |
| Cometly | B2B/revenue attribution, journeys, CAPI, dashboards, CRM/payments | Custom pageview-based pricing. Supports integration with existing CRMs. [Pricing](https://www.cometly.com/pricing) |
| Northbeam | Multi-touch attribution, conversion enrichment, cross-channel measurement | Packages and usage-dependent quotes. Advanced measurement is a comparison point, not an immediate requirement. [Pricing](https://www.northbeam.io/pricing) |
| Dub and ClickMagick | Links, conversions, UTMs; tracking/CAPI and some offline features | Plan/usage limits; ClickMagick displayed USD 79/199/349 monthly. [Dub](https://dub.co/pricing/links), [ClickMagick](https://www.clickmagick.com/pricing/) |
| CallRail and WhatConverts | Calls, forms, chat, lead attribution | Subscription plus usage; agency plans available. Evaluate specialized integration rather than assuming in-house telephony. [CallRail](https://www.callrail.com/pricing), [WhatConverts](https://www.whatconverts.com/pricing) |
| AgencyAnalytics, Whatagraph, DashThis | Client dashboards, white-label reports, multiple sources | Client, source-credit, or dashboard pricing. Agency organization/reporting is established functionality. [AgencyAnalytics](https://agencyanalytics.com/pricing), [Whatagraph](https://whatagraph.com/pricing), [DashThis](https://dashthis.com/pricing) |
| Metricool, Sprout Social, Hootsuite | Social analytics alongside publishing and inbox management | Brand/seat/package pricing with add-ons. Analytics does not require copying all publishing/listening functions. [Metricool](https://metricool.com/pricing/), [Sprout](https://sproutsocial.com/pricing/), [Hootsuite](https://www.hootsuite.com/plans) |

Compare a common scenario covering agencies, clients, accounts, seats, sites, events/pageviews, historical coverage, and add-ons. Starting prices use incompatible units, and some old official pages conflict with current canonical pages. No unavailable Hootsuite price or outdated HYROS price was filled in by guesswork. The [market notes](../research_notes/market-and-feasibility/market.md) retain detailed observations and limitations.

WhatsApp attribution is also established: respond.io and Wati document click-to-chat sources and conversion workflows. Combining these with verified collection and understandable agency reports is a hypothesis worth testing, not a claim to invent WhatsApp attribution. [respond.io](https://respond.io/faqs/where-does-respondio-fit-in-click-to-chat-ad-setup), [Wati](https://support.wati.io/en/articles/11463598-how-to-track-ctwa-ad-conversions-in-wati)

No market-size estimate, willingness-to-pay finding, or universal competitor Arabic-language deficiency is established. Interviews and comparable datasets are needed.

## Platform permissions define the product promise
An OAuth token does not grant every account detail or viewer identity. Each connector needs account types, scopes, API version, metric definitions, historical availability, completeness, and cost. Public competitor data differs from private connected-account insights; social, advertising, and messaging permissions are distinct.

| Platform | Candidate capability | Access and design implications |
|---|---|---|
| Instagram | Permitted Business/Creator account and content insights | Facebook Login and Instagram Login are different paths; the former requires a professional account linked to a Facebook Page. Exact Insights/history/quotas remain verification tasks. [Official Meta collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-894be833-d0b6-4877-859e-c61ae6474d64) |
| YouTube | Public metadata plus authorized channel analytics | OAuth, source timezone, and completeness matter. Research documented 48-72-hour analytics latency and Pacific reporting days. [Authorization](https://developers.google.com/youtube/reporting/guides/authorization), [updates](https://developers.google.com/youtube/reporting/revision_history), [dimensions](https://developers.google.com/youtube/analytics/dimensions) |
| LinkedIn | Organization and permitted member analytics | Community Management is vetted; Standard access requires use-case review. Member analytics is neither universally impossible nor automatically granted. Track version sunsets. [Program](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview?view=li-lms-2026-10), [member metrics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics?tabs=http&view=li-lms-2026-03) |
| X | Public counts and permitted private account metrics | Private/organic/promoted metrics use user context and a 30-day post window in the researched reference. Paid usage and owned-read restrictions need per-client budgets. [Metrics](https://docs.x.com/x-api/fundamentals/metrics), [pricing](https://docs.x.com/x-api/getting-started/pricing) |

Meta rate-limit/login failures left exact Insights and Ads/CAPI details unresolved. This is an evidence gap, not proof integration is impossible; verify official documentation and actual grants before finalizing contracts. [Insights reference](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/insights)

Provider rules also govern subsequent storage and use. YouTube distinguishes retention classes and restricts some derived metrics and cross-source combinations; additional audited-use terms are not automatic. X imposes deletion and off-platform matching restrictions. Technical retrieval alone does not justify linking handles to CRM profiles or inventing revenue-per-view measures. [YouTube policies](https://developers.google.com/youtube/terms/developer-policies), [additional terms](https://developers.google.com/youtube/terms/derived-metrics-policy), [X policy](https://docs.x.com/developer-terms/policy)

Readiness requires more than one successful API request: authorized accounts, proven scopes, pagination/backfill, quota/credit handling, token refresh/revocation, reconnection, job cancellation, and deletion. Unknown, unavailable, partial, and stale states must remain visible. Detailed evidence is in the [platform notes](../research_notes/market-and-feasibility/platforms.md).

## Attribution requires stronger evidence than clicks
A verifiable journey is content/link -> visit -> lead -> booking/order -> payment/refund when identifiers survive across tools and events are authenticated. Dub and VidWorth already document click identifiers and conversion linkage. Lost identifiers must reduce reported coverage rather than be replaced with invented certainty. [Dub](https://github.com/dubinc/docs/blob/main/docs/concepts/attribution.mdx), [VidWorth](https://www.vidworth.co/docs)

A WhatsApp-button click is not a delivered message; a booking is not attendance; purchase intent is not collection. Twilio's documented referral fields and forwarding flags do not expose a complete private forwarding tree. Manychat depends on the actual plan, flow, and captured fields. [Twilio](https://www.twilio.com/docs/messaging/guides/webhook-request?display=embedded), [Manychat](https://help.manychat.com/hc/en-us/articles/14281285374364-Dev-Tools-External-request)

Financial evidence must be stronger than a browser success page. Paymob distinguishes signed processed callbacks from redirects; Stripe may duplicate and reorder webhooks; Calendly rescheduling emits both created and canceled events. These findings support a durable inbox, idempotency, an auditable payment/refund ledger, and reconciliation. A payment screenshot is a claim to review, not independent proof; no suitable official InstaPay API was verified. [Paymob](https://developers.paymob.com/paymob-docs/developers/transaction-callbacks), [Stripe](https://docs.stripe.com/webhooks), [Calendly](https://developer.calendly.com/docs/api-guides/trigger-automations-with-other-apps-when-invitees-schedule-or-cancel-events)

Multi-agency launch makes isolation, permissions, and basic auditing foundational even where the source ranks them later. Retention must be defined instead of indefinite UTM storage; hashing is not encryption or automatic anonymization. YouTube aggregate retention cannot identify a purchaser or the minute that caused a sale. Attribution allocates credit under a model; it does not prove causality. [YouTube data model](https://developers.google.com/youtube/analytics/data_model)

| Proposed improvement | Value | Evidence before marketing the capability |
|---|---|---|
| Metric provenance and completeness | Explain trust and gaps | Sourced metrics/conversions, timestamps, and rules without invented confidence percentages |
| Revenue/refund reconciliation | Avoid inflated ROAS | Known fixtures and provider or audited-manual reconciliation |
| Connector and tracking health | Detect broken grants/webhooks and missing identifiers | Failure cases, actionable alerts, and runbooks |
| Lead outcome lifecycle | Track qualified/booked/attended/won/lost | Defined states, update responsibility, and evidence |
| Regional language/payment experience | Potential local agency value | Interviews, approved RTL workflows, and actual provider tests |
| Cost per client | Sustainable SaaS economics | API/event/storage metering and usage scenarios |

COD, WhatsApp, dialects, and seasonality remain testable ideas. MMM, autonomous ad actions, replay, and a full CRM are candidates for later review, not approved exclusions. Every original requirement retains an identifier and status in the [feature register](../docs/product/feature-register.md).

## Delivery from backend to production
The proposed starting architecture is a FastAPI modular monolith with a durable worker and PostgreSQL, separating authenticated control, public browser events, and verified server/webhook ingestion. No microservice, warehouse, Kubernetes, Celery, or cloud choice is implied. FastAPI BackgroundTasks alone does not establish durable processing; Compose alone does not establish high availability. [Background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/), [containers](https://fastapi.tiangolo.com/deployment/docker/), [Compose](https://docs.docker.com/compose/intro/features-uses/)

Agency/client/site boundaries must apply to APIs, jobs, caches, and exports. PostgreSQL RLS is a possible additional control with role and pooling tests; owner/superuser/BYPASSRLS behavior matters. Object authorization remains mandatory even with UUIDs. [RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html), [OWASP](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/)

| Level | Specifications | Review and exit focus |
|---|---|---|
| L0 | 000 | Traceability, launch scope, metrics, provider limits, owner decisions |
| L1 | 001-003 | Reproducible backend setup, migrations, identity/access, privacy |
| L2 | 004-006 | Event contracts, limited tracker, links, deduplication, deterministic identity |
| L3 | 007-008 | Exact ledger, refunds/currency, approved attribution models and fixtures |
| L4 | 009-015 | Connector runtime, social accounts, advertising, selected business providers |
| L5 | 016-017 | Traceable reporting, onboarding, subscription/usage entitlements |
| L6 | 018 | React workflows, client context, connections, analytics, explicit missing-data states |
| L7 | 019 | Combined end-to-end, isolation, load, security, and owner acceptance |
| L8 | 020 | Approved staging/production, measured restore, monitoring, rollout/rollback |
| After L8 | 021 | Separate evidence, cost, specification, and approval for additions |

The small backend journey is a development milestone; the commercial release still includes both capabilities and multiple agencies. Verify developer-account access early when authorized. No delivery estimate, budget, or numeric service target has been invented.

Spec Kit offers a documented specification/review workflow, but current local files are manual drafts and do not establish CLI installation. Recheck and pin a release before adoption. Since this research, the owner has supplied the repository (D-012). Complete each approved specification and obtain owner review and upload approval before push or PR creation; deployment remains separately authorized. [Quickstart](https://github.github.com/spec-kit/quickstart.html), [core reference](https://github.github.com/spec-kit/reference/core.html)

## Decisions needed next
Review specification 000 to agree on mandatory accounts/metrics, lead entry and sale evidence, currencies, interface languages, markets, workload, budget, retention, and attribution rules. Then compare authentication, ORM, jobs, hosting, and pricing against actual requirements. React tooling remains separate from approval of React itself. [React guidance](https://react.dev/learn/creating-a-react-app)

Subsequent owner decisions require formal English project files (D-009), removal of one-time artifacts (D-010), and isolated Python dependencies declared in backend/requirements.txt plus project-local frontend dependencies (D-011). These do not authorize application setup or select package versions.

A representative authorized dataset containing social accounts and a lead/sale/refund journey is the strongest next feasibility check after scope approval. A bounded test does not narrow the intended market. It reveals missing data and decisions customers value, turning a broad tracking promise into documented capabilities.

See the [decision register](../docs/planning/decisions.md), [roadmap](../docs/planning/roadmap.md), [specification 000](../specs/000-discovery/spec.md), and [architecture notes](../research_notes/market-and-feasibility/architecture.md).
