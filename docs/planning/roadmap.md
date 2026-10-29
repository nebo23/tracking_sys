# Delivery roadmap
Updated: 2026-10-29. Proposed sequence; no delivery dates or cost estimates have been approved.

The first commercial release must combine social analytics, attribution, and multi-agency access. Development milestones do not redefine launch scope.

| Level | Specifications | Reviewable outcome | Exit gate |
|---|---|---|---|
| L0: Discovery | 000 | Scope, 109-feature and 16-idea register, research, decisions. | Approved launch capability matrix and boundaries. |
| L1: Backend foundation | 001-003 | Configuration, migrations, agency/client access, data policy. | Local operation, isolation evidence, approved data rules. |
| L2: Collection and journey | 004-006 | Events, links, tracker, identity. | A consent-aware click-to-lead path with deduplication. |
| L3: Revenue and attribution | 007-008 | Ledger, refunds, currency, models. | Financial and attribution fixtures reconcile. |
| L4: Integrations | 009-015 | Connector runtime, social platforms, selected ads and business sources. | Access evidence and provider contracts for every required connector. |
| L5: Reporting and SaaS | 016-017 | Read APIs, reports, onboarding, usage and entitlements. | Traceable reports, isolation, and usage controls. |
| L6: React | 018 | Agency and client workflows and missing-data states. | Integrated interface using approved backend contracts. |
| L7: Quality and security | 019 | End-to-end, load, recovery, and user acceptance evidence. | Release blockers resolved and acceptance documented. |
| L8: Production | 020 | Staging, deployment, monitoring, restore, and rollback. | Provider approvals, recovery drills, and owner acceptance. |
| After L8: Expansion | 021 | Selected advanced capabilities. | Independent value assessment, specification, and approval. |

## External dependencies
Platform review, business verification, access tiers, developer accounts, payment/CRM/scheduler selection, permitted test data, jurisdiction and retention, expected load, and budget may constrain delivery. Access investigations may begin early once authorized; writing a connector does not guarantee provider approval.

Authentication, ORM, queue, and React tooling remain decisions for spec 001. No Kubernetes, warehouse, or hosting vendor is selected implicitly.

## Review process
Present the problem, scope, alternatives, costs, acceptance examples, and unresolved questions for one specification at a time. After approval and repository authorization, divide implementation into small PRs.

Native mobile applications and SDKs, replay/heatmaps, MMM, incrementality, autonomous outreach or ad actions, a full CRM, partner payouts, and enterprise SSO are proposed expansion candidates. They remain recorded, not deleted or unilaterally deferred.
