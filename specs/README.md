# Specification index
Each specification contains spec.md, plan.md, and tasks.md. The foundation and approved specification 002 are implemented, verified, and uploaded to the claude/development branch (D-020); formal acceptance and merge remain pending. See [current 002 evidence](002-tenancy-access/auth-evidence.md) for 115 checks and explicit later obligations: social sign-in, external email, and actual job/export/cache consumers.

| Specification | Level | Purpose |
|---|---|---|
| [000-discovery](000-discovery/spec.md) | L0 | Scope and decision review |
| [001-foundation](001-foundation/spec.md) | L1 | Project foundation and environment |
| [002-tenancy-access](002-tenancy-access/spec.md) | L1 | Agencies, clients, identity, and access |
| [003-privacy-data-policy](003-privacy-data-policy/spec.md) | L1 | Consent, data protection, and lifecycle |
| [004-event-collection](004-event-collection/spec.md) | L2 | Event collection and contracts |
| [005-links-tracker](005-links-tracker/spec.md) | L2 | Links, UTM parameters, and website tracker |
| [006-identity-journey](006-identity-journey/spec.md) | L2 | Lead identity and customer journey |
| [007-revenue-ledger](007-revenue-ledger/spec.md) | L3 | Revenue, refunds, and currencies |
| [008-attribution-engine](008-attribution-engine/spec.md) | L3 | Lead and revenue attribution engine |
| [009-connector-runtime](009-connector-runtime/spec.md) | L4 | Connector runtime and OAuth |
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
