# Delivery roadmap
Updated: 2026-11-10. Proposed sequence; no delivery dates or cost estimates have been approved.

The first commercial release must combine social analytics, attribution, and multi-agency access. Development milestones do not redefine launch scope.

Current progress: 001/002 are merged in PR 1 (`98747a2`), 003 in PR 2 (`bab3a33`), and 004 with its corrections in PR 3 (`e8ef587`). The latest independent verification passed 481 suite tests and two reproduction checks. Specification 005 is in preparation on a fresh branch from that merged main; see its [entry review](../../specs/005-links-tracker/entry-review.md). Native tracking_sys was last documented at 0004_identity; rollout of 0005 to 0007 and the lifecycle role still needs separate approval. Real customer intake waits for Q-002/Q-004/Q-012. The commercial release still includes both social analytics and attribution for multiple agencies.

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

SQLAlchemy, Psycopg, and Alembic are approved and implemented. Local authentication tooling is approved by D-019 and implemented; queue and React tooling belong to their later specifications. No Kubernetes, warehouse, or hosting vendor is selected implicitly.

## Review process
Present the problem, scope, alternatives, costs, acceptance examples, and unresolved questions for one specification at a time. After approval and repository authorization, divide implementation into small PRs.

Native mobile applications and SDKs, replay/heatmaps, MMM, incrementality, autonomous outreach or ad actions, a full CRM, partner payouts, and enterprise SSO are proposed expansion candidates. They remain recorded, not deleted or unilaterally deferred.
