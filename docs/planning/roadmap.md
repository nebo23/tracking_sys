# Delivery roadmap
Updated: 2026-10-29. Proposed sequence; no delivery dates or cost estimates have been approved.

The first commercial release must combine social analytics, attribution, and multi-agency access. Development milestones do not redefine launch scope.

Current progress: foundation and specification 002, including the D-022 numeric verification, Google sign-in, and Gmail sender additions and the R-01 to R-03 corrections, are merged into main (PR 1, `98747a2`). Native tracking_sys is at 0004_identity with 19 tables. Specification 003 is completed at contract level on codex/spec-003-privacy-data-policy under D-023 to D-025 and awaits review. Slice 003-A (data-class registry, log allowlist, lifecycle runner, mail expiry, and account closure) is implemented, and the 003-B to 003-D contracts are tested libraries; the local suite passes 327 checks. Native rollout of migrations 0005/0006 and the lifecycle role needs separate approval. End-to-end verification of the transferred acceptance cases is listed in each of specifications 004-020. Facebook sign-in and production mail remain explicit later obligations.

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
