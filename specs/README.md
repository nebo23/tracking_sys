# Specification index
Each specification contains spec.md, plan.md, and tasks.md. The foundation and approved specification 002, including the D-022 additions and R-01 to R-03 corrections, are merged into main (PR 1, `98747a2`); see the [002 evidence](002-tenancy-access/auth-evidence.md) and [corrections](002-tenancy-access/auth-corrections-2026-11-04.md). Specification 003 is completed at contract level under D-023 to D-025, with the review findings R003-01 to R003-03 corrected under D-026, and merged in [PR 2](https://github.com/nebo23/tracking_sys/pull/2) ([evidence](003-privacy-data-policy/evidence.md), [corrections](003-privacy-data-policy/review-corrections-evidence.md)); the consuming specifications list their 003 obligations. Specifications 004 to 008 are merged in PRs 3 to 7 as noted below, and Spec 009 merged in [PR 8](https://github.com/nebo23/tracking_sys/pull/8) at `4abcbc6` under D-050. Later obligations remain explicit: Facebook sign-in, production email, and actual job/export/cache consumers.

| Specification | Level | Purpose |
|---|---|---|
| [000-discovery](000-discovery/spec.md) | L0 | Scope and decision review |
| [001-foundation](001-foundation/spec.md) | L1 | Project foundation and environment |
| [002-tenancy-access](002-tenancy-access/spec.md) | L1 | Agencies, clients, identity, and access |
| [003-privacy-data-policy](003-privacy-data-policy/spec.md) | L1 | Consent, data protection, and lifecycle |
| [004-event-collection](004-event-collection/spec.md) | L2 | Event collection and contracts (merged in PR 3, `e8ef587`) |
| [005-links-tracker](005-links-tracker/spec.md) | L2 | Links, UTM parameters, and website tracker (merged in PR 4, `c251e20`) |
| [006-identity-journey](006-identity-journey/spec.md) | L2 | Lead identity and customer journey (design merged in PR 5, `ec9a09b`) |
| [007-revenue-ledger](007-revenue-ledger/spec.md) | L3 | Revenue, refunds, and currencies (007-A calculation contract merged in PR 6, `bc0ff40`; 007-B and 007-C open) |
| [008-attribution-engine](008-attribution-engine/spec.md) | L3 | Lead and revenue attribution engine (008-A synthetic slice merged in PR 7, `3f6dc06`) |
| [009-connector-runtime](009-connector-runtime/spec.md) | L4 | Connector runtime and OAuth (implemented against the synthetic provider: 009-A under D-048, 009-B to 009-D under D-049, verified with correction R009-11 under D-050 and merged in PR 8, `4abcbc6`; [evidence](009-connector-runtime/evidence.md)) |
| [010-instagram](010-instagram/spec.md) | L4 | Instagram analytics |
| [011-youtube](011-youtube/spec.md) | L4 | YouTube analytics |
| [012-linkedin](012-linkedin/spec.md) | L4 | LinkedIn analytics |
| [013-x](013-x/spec.md) | L4 | X analytics |
| [014-ad-spend-capi](014-ad-spend-capi/spec.md) | L4 | Advertising spend and conversion delivery |
| [015-business-integrations](015-business-integrations/spec.md) | L4 | Forms, bookings, payments, CRM, and WhatsApp |
| [016-analytics-reporting](016-analytics-reporting/spec.md) | L5 | Analytics queries and client reporting |
| [017-saas-lifecycle](017-saas-lifecycle/spec.md) | L5 | SaaS subscriptions and usage lifecycle |
| [018-react-workspace](018-react-workspace/spec.md) | L6 | React workspace and user experience |
| [019-quality-security](019-quality-security/spec.md) | L7 | System quality, security, and release readiness |
| [020-production](020-production/spec.md) | L8 | Deployment, operations, and recovery |
| [021-growth-backlog](021-growth-backlog/spec.md) | After L8 | Growth and advanced feature backlog |

Numbering gives the proposed review order; dependencies within each specification govern implementation. Privacy and isolation are addressed early. Testing begins with each implemented slice; specification 019 assembles release evidence across the system.

The first commercial release must combine social analytics, attribution, and multi-agency access. Excluding a platform from the initial launch requires an explicit recorded owner decision.
