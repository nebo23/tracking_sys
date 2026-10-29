# Complete requirements register
Status: complete inventory; proposed delivery ordering is not approved. Research reviewed: 2026-10-28. English revision: 2026-10-29.

See [source provenance](../source/README.md). Source priorities are translated as MVP, Important, and Advanced; they are not launch commitments. Every item remains **Draft / decision required**. Specification 021 preserves proposed future work rather than deleting it. Notes clarify compound items; references to two specifications do not duplicate a feature.

## Source categories
| Category | Feature numbers |
|---|---|
| Data Collection | 001–014 |
| Smart Links | 015–026 |
| Identity & Journey | 027–033 |
| Attribution | 034–044 |
| Calls & Sales | 045–051 |
| Revenue & Profit | 052–057 |
| Ad Platforms | 058–064 |
| Analytics & Reporting | 065–073 |
| Visitor Behavior | 074–077 |
| Advanced Measurement | 078–081 |
| Data Quality & Fraud | 082–085 |
| AI & Automation | 086–091 |
| Affiliates & Partners | 092–095 |
| Teams, Agencies & Platform | 096–103 |
| Privacy & Compliance | 104–109 |

## Original 109 features
| ID | Source feature | Page | Source priority | Primary specification | Extension | Review notes and limitations |
|---|---|---|---|---|---|---|
| PDF-001 | First-party pixel | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | [005-links-tracker](../../specs/005-links-tracker/spec.md) | Apply consent limits; server-side collection does not bypass blocking. |
| PDF-002 | Server-side tracking | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | — | Verify the source and distinguish trusted from public ingestion. |
| PDF-003 | Custom tracking domain (CNAME) | 3 | MVP | [005-links-tracker](../../specs/005-links-tracker/spec.md) | — | Verify domain ownership and TLS before activation. |
| PDF-004 | Auto-capture events | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | — | Allowlist events and fields; do not capture everything by default. |
| PDF-005 | Custom events API & SDKs | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Propose the event API first; native SDKs remain an expansion candidate. |
| PDF-006 | UTM capture & persistence | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | — | Define retention instead of indefinite persistence. |
| PDF-007 | Click ID capture | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | — | Record provider-specific source, consent, and retention rules. |
| PDF-008 | Form tracking | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | [015-business-integrations](../../specs/015-business-integrations/spec.md) | Redact fields and select supported form tools. |
| PDF-009 | Inbound webhooks | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | [015-business-integrations](../../specs/015-business-integrations/spec.md) | Verify signatures, idempotency, and event ordering. |
| PDF-010 | Mobile SDK & deep-link attribution | 3 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Requires a separate future specification. |
| PDF-011 | Offline conversion import | 3 | Important | [015-business-integrations](../../specs/015-business-integrations/spec.md) | — | CSV/manual imports are candidates; identify the source explicitly. |
| PDF-012 | GTM / server-side GTM | 3 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Evaluate after the primary installation workflow. |
| PDF-013 | Live event debugger | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | [018-react-workspace](../../specs/018-react-workspace/spec.md) | Redact sensitive data; display accepted, rejected, and deduplicated states. |
| PDF-014 | Event deduplication | 3 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | — | Scope deduplication by client and event ID; define conflict handling. |
| PDF-015 | Branded short links | 4 | MVP | [005-links-tracker](../../specs/005-links-tracker/spec.md) | — | Redirects must remain available when analytics fails. |
| PDF-016 | UTM builder & templates | 4 | MVP | [005-links-tracker](../../specs/005-links-tracker/spec.md) | — | Normalize parameters and define shared naming conventions. |
| PDF-017 | Auto QR codes | 4 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Proposed for later consideration. |
| PDF-018 | Geo / device targeting | 4 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Document location accuracy and data limitations. |
| PDF-019 | Split testing & link rotators | 4 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Causal conclusions require a properly designed experiment. |
| PDF-020 | Deferred deep linking | 4 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Verify mobile provider restrictions. |
| PDF-021 | Expiry & password links | 4 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Define crawler, cache, and expiry behavior. |
| PDF-022 | Custom link previews (OG) | 4 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Review crawler access and content safety. |
| PDF-023 | Bulk & programmatic links | 4 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Define batch limits and preview behavior. |
| PDF-024 | Per-content auto links | 4 | MVP | [005-links-tracker](../../specs/005-links-tracker/spec.md) | — | Registering a link does not authorize automatic post editing. |
| PDF-025 | Link uptime monitoring | 4 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Require SSRF controls and a scheduling policy. |
| PDF-026 | Retargeting pixels on links | 4 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Review consent, provider policies, and browser restrictions. |
| PDF-027 | Cross-device identity resolution | 4 | MVP | [006-identity-journey](../../specs/006-identity-journey/spec.md) | — | Deterministic matching is the initial proposal. |
| PDF-028 | Identity stitching | 4 | MVP | [006-identity-journey](../../specs/006-identity-journey/spec.md) | — | Use verified identifiers; do not automatically merge shared phone numbers. |
| PDF-029 | Unified customer profile | 5 | MVP | [006-identity-journey](../../specs/006-identity-journey/spec.md) | [018-react-workspace](../../specs/018-react-workspace/spec.md) | Isolate profiles within each client. |
| PDF-030 | Customer journey timeline | 5 | MVP | [006-identity-journey](../../specs/006-identity-journey/spec.md) | [018-react-workspace](../../specs/018-react-workspace/spec.md) | Preserve source, evidence, occurred_at, and received_at. |
| PDF-031 | Account-based B2B grouping | 5 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Distinguish the agency's client company from a lead's company. |
| PDF-032 | Configurable lookback window | 5 | MVP | [008-attribution-engine](../../specs/008-attribution-engine/spec.md) | — | Define time boundaries and policy versions. |
| PDF-033 | Visitor identification / enrichment | 5 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | No automatic deanonymization; establish source and consent. |
| PDF-034 | First / Last click | 5 | MVP | [008-attribution-engine](../../specs/008-attribution-engine/spec.md) | — | Define timestamp ties, direct traffic, and unknown sources. |
| PDF-035 | Linear, Time-decay, U/W-shaped | 5 | MVP | [008-attribution-engine](../../specs/008-attribution-engine/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Propose Linear first; other models require separate rules. |
| PDF-036 | Data-driven / algorithmic attribution | 5 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Require sufficient data, calibration, and evaluation. |
| PDF-037 | Custom attribution models | 5 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Validate allocation invariants and weights. |
| PDF-038 | Model comparison | 5 | Important | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | — | Compare the same cohort and attribution window. |
| PDF-039 | View-through attribution | 5 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Use permitted data only; do not infer viewer identity. |
| PDF-040 | Post-purchase self-reported survey | 5 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Label self-reported evidence separately from observed clicks. |
| PDF-041 | Organic content attribution | 5 | MVP | [008-attribution-engine](../../specs/008-attribution-engine/spec.md) | [005-links-tracker](../../specs/005-links-tracker/spec.md) | Use tagged links, coupons, or deterministic evidence. |
| PDF-042 | Revenue-level attribution | 5 | MVP | [007-revenue-ledger](../../specs/007-revenue-ledger/spec.md) | [008-attribution-engine](../../specs/008-attribution-engine/spec.md) | Establish a financial ledger before allocating credit. |
| PDF-043 | LTV & subscription attribution | 6 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Client subscription renewals are separate from SaaS billing. |
| PDF-044 | Assisted conversions / paths | 6 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Prevent double counting in totals. |
| PDF-045 | Call tracking / dynamic numbers | 6 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Select country, provider, consent requirements, and budget. |
| PDF-046 | Call recording, transcription & AI summary | 6 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Define consent, storage, and dialect evaluation. |
| PDF-047 | Booked-call attribution | 6 | MVP | [015-business-integrations](../../specs/015-business-integrations/spec.md) | — | Select Calendly, Cal.com, or another approved scheduler. |
| PDF-048 | Lead / intent scoring | 6 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Explain rules and calibrate scoring. |
| PDF-049 | CRM pipeline sync | 6 | Important | [015-business-integrations](../../specs/015-business-integrations/spec.md) | — | Select an approved initial CRM provider. |
| PDF-050 | Lead inbox / mini-CRM | 6 | Important | [006-identity-journey](../../specs/006-identity-journey/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Propose a read model first; a full CRM requires a separate decision. |
| PDF-051 | DM / chat attribution | 6 | Important | [015-business-integrations](../../specs/015-business-integrations/spec.md) | — | Verify scopes and referral metadata; handle missing evidence. |
| PDF-052 | Payment integrations | 6 | MVP | [007-revenue-ledger](../../specs/007-revenue-ledger/spec.md) | [015-business-integrations](../../specs/015-business-integrations/spec.md) | Select a provider based on approved markets. |
| PDF-053 | Refunds & chargebacks | 6 | MVP | [007-revenue-ledger](../../specs/007-revenue-ledger/spec.md) | — | Cover partial refunds, refunds before sales, and reversals. |
| PDF-054 | Multi-currency | 6 | MVP | [007-revenue-ledger](../../specs/007-revenue-ledger/spec.md) | — | Do not combine currencies without documented FX conversion. |
| PDF-055 | Profit metrics / ROAS / CAC / MER | 7 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | [014-ad-spend-capi](../../specs/014-ad-spend-capi/spec.md) | Limited ROAS belongs in 014; profit requires explicit cost definitions. |
| PDF-056 | Manual revenue logging | 7 | MVP | [007-revenue-ledger](../../specs/007-revenue-ledger/spec.md) | — | Identify manual evidence and preserve an audit trail. |
| PDF-057 | Cohort & LTV analysis | 7 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Define cohorts and reporting periods. |
| PDF-058 | Ad spend ingestion | 7 | MVP | [014-ad-spend-capi](../../specs/014-ad-spend-capi/spec.md) | — | Advertising spend is distinct from social analytics. |
| PDF-059 | Conversion API sync | 7 | MVP | [014-ad-spend-capi](../../specs/014-ad-spend-capi/spec.md) | — | Use an outbox, idempotency, and consent controls. |
| PDF-060 | Audience sync | 7 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Require separate delivery permissions and consent. |
| PDF-061 | Creative analytics | 7 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Link assets, ads, and revenue without claiming causality. |
| PDF-062 | Ad-level ROAS | 7 | MVP | [014-ad-spend-capi](../../specs/014-ad-spend-capi/spec.md) | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | Define attributable revenue, currency, and reporting window. |
| PDF-063 | AI budget recommendations | 7 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | No automatic financial spending. |
| PDF-064 | In-dashboard ad actions | 7 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Require write scopes, confirmation, and review. |
| PDF-065 | Real-time dashboard | 7 | MVP | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | [018-react-workspace](../../specs/018-react-workspace/spec.md) | Display source-specific freshness; do not promise universal real-time data. |
| PDF-066 | Custom dashboards | 7 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Define widget limits and metric permissions. |
| PDF-067 | Funnel analysis | 8 | MVP | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | — | Define funnel stages and denominators. |
| PDF-068 | Segmentation & breakdowns | 8 | MVP | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | — | Apply privacy thresholds; do not invent unavailable dimensions. |
| PDF-069 | Content revenue leaderboard | 8 | MVP | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | — | Show evidence, model, window, and currency. |
| PDF-070 | Scheduled reports & digests | 8 | Important | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | — | Future product capability; actual delivery requires owner configuration. |
| PDF-071 | Export & data warehouse sync | 8 | Important | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Propose CSV first; warehouse and Sheets synchronization are expansion candidates. |
| PDF-072 | Chart annotations | 8 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Scope annotations and label manual sources. |
| PDF-073 | Period comparison & benchmarks | 8 | Important | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Propose period comparison first; benchmarks require independent sources. |
| PDF-074 | Session replay | 8 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Mask sensitive data on the client before capture. |
| PDF-075 | Heatmaps & scroll maps | 8 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Review privacy and performance. |
| PDF-076 | Frustration & error signals | 8 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Signals do not establish user intent with certainty. |
| PDF-077 | Landing page analytics | 8 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Normalize pages and preserve source attribution. |
| PDF-078 | Marketing Mix Modeling | 8 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Require sufficient data, explicit assumptions, and evaluation. |
| PDF-079 | Incrementality / holdout / geo tests | 8 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Design experiments separately from attribution. |
| PDF-080 | Forecasting & budget scenarios | 9 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Show uncertainty and compare with a baseline. |
| PDF-081 | Anomaly detection & alerts | 9 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Evaluate false positives and seasonality. |
| PDF-082 | Bot filtering | 9 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | — | Record exclusion reasons; do not claim complete bot detection. |
| PDF-083 | Click-fraud protection | 9 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Evaluate false positives and review blocking actions. |
| PDF-084 | Internal traffic exclusion | 9 | MVP | [004-event-collection](../../specs/004-event-collection/spec.md) | — | Use auditable exclusion rules. |
| PDF-085 | Tracking health monitor | 9 | Important | [019-quality-security](../../specs/019-quality-security/spec.md) | [020-production](../../specs/020-production/spec.md) | Operational monitoring is foundational; product diagnostics are an expansion candidate. |
| PDF-086 | Natural-language AI analyst | 9 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Use scoped, read-only tools and prevent data leakage. |
| PDF-087 | MCP server | 9 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Require tenant authorization and a limited tool surface. |
| PDF-088 | Automated AI insights | 9 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Ground outputs in evidence and evaluate them. |
| PDF-089 | Content-maintenance agent | 9 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Require write permissions and confirmation of edits. |
| PDF-090 | Automation integrations / Zapier / n8n | 9 | MVP | [015-business-integrations](../../specs/015-business-integrations/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Propose webhook contracts first; native integrations remain future work. |
| PDF-091 | AI remarketing outreach | 9 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Require consent, sending authorization, and channel-specific rules. |
| PDF-092 | Affiliate / partner programs | 10 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Define fraud controls and commission states. |
| PDF-093 | Promo-code attribution | 10 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Resolve conflicts between promo codes and click attribution. |
| PDF-094 | Automated payouts | 10 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Money movement requires a separate requirements review. |
| PDF-095 | Partner portal | 10 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Enforce tenant, client, and partner permissions. |
| PDF-096 | Multi-workspace / multi-client | 10 | Important | [002-tenancy-access](../../specs/002-tenancy-access/spec.md) | [017-saas-lifecycle](../../specs/017-saas-lifecycle/spec.md) | Required for launch by owner decision despite the source priority. |
| PDF-097 | White-label client reports | 10 | Important | [016-analytics-reporting](../../specs/016-analytics-reporting/spec.md) | — | Review branding, permissions, and delivery scope. |
| PDF-098 | Roles & permissions | 10 | MVP | [002-tenancy-access](../../specs/002-tenancy-access/spec.md) | — | Define agency, client, and field permissions. |
| PDF-099 | SSO/SAML & audit logs | 10 | Advanced | [002-tenancy-access](../../specs/002-tenancy-access/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Basic auditing is foundational; SSO remains an advanced capability. |
| PDF-100 | Public API & outbound webhooks | 10 | Important | [009-connector-runtime](../../specs/009-connector-runtime/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Define contracts first; a public integration surface requires approval. |
| PDF-101 | Guided onboarding & integrations | 10 | MVP | [017-saas-lifecycle](../../specs/017-saas-lifecycle/spec.md) | [018-react-workspace](../../specs/018-react-workspace/spec.md) | Do not promise one-click setup where application review is required. |
| PDF-102 | Mobile app & push alerts | 10 | Important | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | A responsive React interface is distinct from a native mobile application. |
| PDF-103 | Localization & RTL | 10 | MVP | [018-react-workspace](../../specs/018-react-workspace/spec.md) | — | Arabic and English interface support remain proposals; repository language is English under D-009. |
| PDF-104 | Consent management & consent mode | 11 | MVP | [003-privacy-data-policy](../../specs/003-privacy-data-policy/spec.md) | — | Define provider-specific and market-specific rules. |
| PDF-105 | PII hashing | 11 | MVP | [003-privacy-data-policy](../../specs/003-privacy-data-policy/spec.md) | — | Hashing is not encryption or automatic anonymization. |
| PDF-106 | Retention & deletion requests | 11 | MVP | [003-privacy-data-policy](../../specs/003-privacy-data-policy/spec.md) | — | Cover raw data, derived data, caches, and restoration. |
| PDF-107 | Client-side masking | 11 | MVP | [003-privacy-data-policy](../../specs/003-privacy-data-policy/spec.md) | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Safe collection is foundational; replay masking applies if replay is approved. |
| PDF-108 | Data residency | 11 | Advanced | [003-privacy-data-policy](../../specs/003-privacy-data-policy/spec.md) | [020-production](../../specs/020-production/spec.md) | Select the storage region before production. |
| PDF-109 | SOC 2 / security certifications | 11 | Advanced | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | — | Implementing controls alone does not establish certification. |

## Additional 16 source ideas
Market differentiation claims require evidence. These are neither approved features nor established inventions.

| ID | Idea | Page | Review specification | Limitation |
|---|---|---|---|---|
| IDEA-01 | COD-aware attribution | 12 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Link delivery, collection, and settlement; a shipped order alone is not verified revenue. |
| IDEA-02 | Screenshot-to-revenue matching | 12 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | OCR may assist matching; financial verification must be independent. |
| IDEA-03 | End-to-end WhatsApp attribution | 12 | [015-business-integrations](../../specs/015-business-integrations/spec.md) | Candidate workflow using official referral metadata plus CRM/payment evidence. |
| IDEA-04 | Arabic-dialect conversation intelligence | 12 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Evaluate dialects and consent; do not equate purchase intent with payment. |
| IDEA-05 | The moment that sold | 12 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Reframe as correlation; causality and viewer matching are not established. |
| IDEA-06 | Dark-social share-tree tracking | 12 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Track explicitly issued referral links; hidden forwarding trees are unavailable. |
| IDEA-07 | Hijri & regional seasonality | 12 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Define the country, calendar, and comparison method. |
| IDEA-08 | Attribution confidence score | 12 | [008-attribution-engine](../../specs/008-attribution-engine/spec.md) | Propose evidence classes first; confidence percentages require calibration. |
| IDEA-09 | Cost-of-inaction alerts | 13 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Present estimated losses with assumptions and ranges. |
| IDEA-10 | Synthetic funnel monitoring | 13 | [019-quality-security](../../specs/019-quality-security/spec.md) | Use test mode without real purchases or external leads. |
| IDEA-11 | WhatsApp AI analyst | 13 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Use scoped, read-only data with recipient authorization and cost controls. |
| IDEA-12 | Comment-to-revenue attribution | 13 | [015-business-integrations](../../specs/015-business-integrations/spec.md) | Require valid permissions and explicit identifiers; do not imply access to all audience comments. |
| IDEA-13 | PPP-normalized revenue | 13 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Keep economic comparison separate from the revenue ledger. |
| IDEA-14 | Collab revenue split | 13 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Define contractual allocation; do not imply automatic payouts. |
| IDEA-15 | Visitor data receipt | 13 | [003-privacy-data-policy](../../specs/003-privacy-data-policy/spec.md) | Propose a transparency portal with identity verification. |
| IDEA-16 | Best-time-to-contact | 13 | [021-growth-backlog](../../specs/021-growth-backlog/spec.md) | Prediction requires data and evaluation; do not promise accuracy or automatic messaging. |

## Owner requirements supplementing the source
| ID | Confirmed requirement | Specification |
|---|---|---|
| USER-01 | Instagram analytics | [010](../../specs/010-instagram/spec.md) |
| USER-02 | YouTube analytics | [011](../../specs/011-youtube/spec.md) |
| USER-03 | LinkedIn analytics | [012](../../specs/012-linkedin/spec.md) |
| USER-04 | X/Twitter analytics | [013](../../specs/013-x/spec.md) |
| USER-05 | Multiple agencies and their clients from launch | [002](../../specs/002-tenancy-access/spec.md), [017](../../specs/017-saas-lifecycle/spec.md) |
| USER-06 | Both social analytics and attribution in the first release | [000](../../specs/000-discovery/spec.md), [016](../../specs/016-analytics-reporting/spec.md) |
| USER-07 | FastAPI/PostgreSQL/React/Docker | [001](../../specs/001-foundation/spec.md), [018](../../specs/018-react-workspace/spec.md), [020](../../specs/020-production/spec.md) |

Repository language, cleanup, and environment requirements are recorded separately as D-009, D-010, and D-011 in the [decision register](../planning/decisions.md).

## Proposed engineering improvements
| ID | Proposal | Relevant specifications |
|---|---|---|
| PROP-01 | Capability catalog, freshness, and evidence for every reported metric | 009, 010-013, 016 |
| PROP-02 | Tenant/client isolation across APIs, jobs, caches, and exports | 002, 019 |
| PROP-03 | Ledger, reconciliation, and repeat-safe ingestion | 004, 007, 008 |
| PROP-04 | API usage/cost limits and SaaS entitlements | 009, 017 |
| PROP-05 | Deletion propagation and restoration tombstones | 003, 020 |
| PROP-06 | Provider contract fixtures and permission-expiry tests | 009-015, 019 |
| PROP-07 | Deployment/recovery exercises and operational runbooks | 019, 020 |

## Coverage
The register preserves 109 PDF features and 16 ideas: 125 source items, plus seven owner product requirements and seven engineering proposals. No item is considered implemented or approved merely by inclusion. Page 2 of the source contains 12 summary bundles combining detailed rows; these are not 12 additional features.
