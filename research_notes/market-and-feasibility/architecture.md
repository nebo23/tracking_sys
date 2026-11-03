# Architecture and specification workflow research
Research checked: 2026-10-28. English revision: 2026-10-29; technical source claims have not been rechecked by this editorial revision.

Status: research and design proposals, not approved architecture or implementation. The fixed stack is FastAPI, PostgreSQL, React, and Docker. The confirmed first commercial release combines social analytics and revenue attribution for multiple agencies and their clients. No industry vertical has been selected.

## Specification workflow
### Findings
The researched Spec Kit workflow was constitution, specify, clarify, plan, checklist, tasks, analyze, implement, and converge. These workflow actions are invoked through the agent integration, not simply entered as terminal commands. Current-feature selection used feature.json or a feature directory rather than the Git branch alone. [Official quickstart](https://github.github.com/spec-kit/quickstart.html)

The initialization interface used --integration, with optional Git support supplied by an extension rather than installed by default. PowerShell was supported through --script ps. Codex integration placed skills under .agents/skills/speckit-<command>/SKILL.md and used invocations such as $speckit-specify. [Core reference](https://github.github.com/spec-kit/reference/core.html), [Codex integration](https://github.github.com/spec-kit/integrations/codex.html)

The installation guide recommended a specific release and also documented PyPI. Running specify version identifies the local version but does not establish executable provenance. Review current help and protect existing files before any future initialization; do not assume historical --ai or --no-git options remain valid. [Installation](https://github.github.com/spec-kit/installation.html)

### Proposed application
The current .specify directory contains manually authored project principles and templates. It does not mean the CLI was installed, that official generation occurred, or that the directory stores private assistant configuration.

Use a specification for value and observable behavior, clarification decisions, a design plan, contracts/data models when needed, tasks, and verification evidence. Additional files should exist only when useful. Record question, alternatives, recommendation, evidence, impact, status, and owner approval in the decision register.

Use small reviewable changes linked to approved specifications. After this research, the owner supplied the repository and confirmed the review-before-upload workflow (D-012): complete the approved specification and relevant checks, obtain owner review and upload approval, then push and create or update its PR. This replaces the earlier proposal to open a draft PR before implementation. Preserve the existing repository and remote.

Completion requires acceptance evidence, authorization/data review, applicable migration/recovery documentation, and owner acceptance. An external API-access blocker is not completion.

### Delivery levels
The initial research grouping was consolidated into the current [roadmap](../../docs/planning/roadmap.md). That roadmap and specification dependencies govern delivery.

| Level | Current specifications | Exit evidence |
|---|---|---|
| L0 | 000 discovery | Traceability, launch capability matrix, and owner decisions |
| L1 | 001-003 foundation, access, privacy | Reproducible setup after approval, isolation, migrations, and data policies |
| L2 | 004-006 collection, links, identity | Repeat-safe click-to-lead journey, consent, and identity boundaries |
| L3 | 007-008 ledger and attribution | Known financial fixtures and deterministic model results |
| L4 | 009-015 connectors | Authorized provider capabilities, recovery, quotas, cost, and freshness |
| L5 | 016-017 reporting and SaaS lifecycle | Traceable reports plus agency/subscription/entitlement behavior |
| L6 | 018 React | Complete accessible workflows and isolated client state |
| L7 | 019 system readiness | End-to-end, failure, security, load, and owner acceptance evidence |
| L8 | 020 production | Approved hosting, measured restore, monitoring, and rollback |
| After L8 | 021 growth | Separate value, feasibility, and approval for each selected addition |

A small backend click-to-lead-to-payment demonstration is an internal implementation milestone, not a release that removes social analytics. Platform access work should begin early when authorized because external approvals may take longer than code. Account types, metrics, lead definitions, payment sources, workload, retention, pricing, and trials remain decisions.

### Environment decision added after research
D-011 confirms isolated Python dependencies and backend/requirements.txt. Frontend dependencies remain project-local with their manifest and lockfile. Container builds install declared dependencies without copying host .venv or node_modules. This does not select package versions, ORM, authentication, job libraries, or a locking tool. Actual environment setup remains deferred to approved specification 001 work.

## Architecture and trust boundaries
### Findings
FastAPI recommends building from a Python base image rather than the deprecated tiangolo/uvicorn-gunicorn-fastapi image. Its deployment guidance separates HTTPS, startup, restart, scaling, and preparation tasks. BackgroundTasks is suited to small in-process work; durable distributed work requires additional job infrastructure. This is not a decision to adopt Celery. [Containers](https://fastapi.tiangolo.com/deployment/docker/), [background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)

Docker Compose supports development, tests, and single-host production. That alone does not establish high availability. [Compose](https://docs.docker.com/compose/intro/features-uses/)

PostgreSQL row-level security defaults to deny when enabled without a policy, but superusers, BYPASSRLS roles, and normally table owners bypass it; FORCE RLS changes the owner case. Application authorization is still required. OWASP requires object authorization wherever a supplied identifier is used to access an object; UUIDs are not an authorization mechanism. [PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html), [OWASP object authorization](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/)

OAuth security guidance covers CSRF protection, exact redirect matching, PKCE for public clients and its recommendation for confidential clients, and provider mix-up attacks. [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)

React recommends frameworks for new applications while documenting from-scratch builds where appropriate. Vite is an example, not a selection of routing or data-fetching tools. Approval of React does not implicitly approve Next.js or TypeScript. [Creating an app](https://react.dev/learn/creating-a-react-app), [from-scratch approach](https://react.dev/learn/build-a-react-app-from-scratch)

GA4 Measurement Protocol complements tagging; server-only usage can produce partial reporting. Its api_secret must remain server-side. [Protocol overview](https://developers.google.com/analytics/devguides/collection/protocol/ga4), [sending events](https://developers.google.com/analytics/devguides/collection/protocol/ga4/sending-events?client_type=gtag&hl=en)

### Proposed design
Begin with a modular monolith and a durable worker process, separating public ingestion logically from authenticated administration. PostgreSQL can hold operational records, accepted events, and the revenue ledger. The unknown workload does not justify microservices, a warehouse, partitioning, or Kubernetes by default.

| Boundary | Proposed controls |
|---|---|
| Authenticated control API | Identity establishes agency and client grants; a browser-supplied tenant_id is insufficient. Cover membership, sites, connections, configuration, and reports. |
| Public browser ingestion | Public site identifiers, versioned schemas, bounded bodies, abuse limits, consent, deduplication, and quarantine. Origin/domain checks are signals, not authentication. Browser purchase events are not payment proof. |
| Trusted server ingestion | Scoped, rotatable credentials/signatures, replay controls, client/site binding, and event-type privileges distinct from public pixel IDs. |
| Payment/webhook inbox | Verify raw-body signatures, record accepted messages durably before successful acknowledgment, normalize asynchronously, and deduplicate both events and business transactions. |
| Worker and connectors | Backoff/jitter, quotas, checkpoints, leases/timeouts, reviewed failure queues, disconnection cancellation, and outbound delivery records. Queue selection requires a decision. |
| Reporting | Rebuildable projections with definitions, model versions, last successful synchronization, and coverage. |

Social aggregates, first-party touchpoints, and verified business outcomes remain distinct data classes in the same product. Content/campaign/link references can connect them only where technically supported and permitted. A missing social metric should not prevent recording a verified conversion; a view or follower must not be assigned to a person or revenue without evidence.

Candidate event fields include schema_version, event_id, event_name, server-resolved agency/client/site, anonymous_id, session_id, optional identified-subject reference, occurred_at, received_at, source type, consent state/version, permitted page/referrer/UTM/click identifiers, allowlisted properties, and integrity status. Preserve source timezone and distinguish missing from zero.

Tracked redirects should resolve an authorized slug to a stored approved destination rather than accept arbitrary destinations. Define domain ownership, TLS, failure durability/latency behavior, and SSRF protections before fetching previews. Analytics failure must have explicit redirect behavior.

Identity linking should retain the anonymous journey and use verified, permitted identifiers within one client. Define ambiguity, shared-device switching, merge/unmerge, and auditing. Do not assume fingerprinting or hashed email provides anonymous, universal identity.

Design agency/client isolation from the first migration. Scope foreign keys, uniqueness, services, queries, workers, caches, reports, and exports. If RLS is adopted, verify transaction-local tenant context and pooled-connection reuse, and avoid an owner/superuser runtime role. Test both cross-agency and cross-client denials. Suspension, quotas, account grants, and data ownership after cancellation need explicit policies.

A React SPA is a candidate for an authenticated workspace; router, query tools, TypeScript, and build tooling remain open. Public marketing-site SEO is a separate concern. Never display illustrative data as live customer metrics.

### Gaps
No cloud, object store, authentication provider, session mechanism, ORM, or queue is selected. Volume, freshness, SLO, RPO, and RTO targets are unknown. Provider grants and data-combination rules require connector-specific evidence, especially for YouTube. Regional legal responsibility and consent require separate review; this is technical research.

## Financial correctness and release evidence
### Findings
Stripe documents duplicate and out-of-order webhook delivery, signature verification using raw request bodies, and asynchronous processing. Event deduplication may also need object ID and event type because distinct events can represent the same business fact. Outbound request idempotency keys do not replace inbound webhook deduplication. [Webhooks](https://docs.stripe.com/webhooks), [idempotent requests](https://docs.stripe.com/api/idempotent_requests)

Stripe uses currency-specific minor units with zero-decimal and special cases, and presentment can differ from settlement currency. Partial/multiple refunds are supported, and a pending refund must not immediately be treated as confirmed. These are reference behaviors, not a decision to use Stripe. [Currencies](https://docs.stripe.com/currencies), [refunds](https://docs.stripe.com/refunds)

Alembic autogeneration produces candidate migrations requiring review. PostgreSQL supports major versions for five years and recommends current minor releases for the selected major. At research time, version 18 support extended to November 2030 while version 14 approached its November 2026 end; no project version was pinned. [Alembic](https://alembic.sqlalchemy.org/en/latest/autogenerate.html), [PostgreSQL version policy](https://www.postgresql.org/support/versioning/)

PostgreSQL distinguishes SQL dumps, filesystem backups, and continuous archiving. Point-in-time recovery needs an appropriate base backup and WAL sequence; pg_dump alone is not a WAL-replay base. [Backup](https://www.postgresql.org/docs/current/backup.html), [PITR](https://www.postgresql.org/docs/current/continuous-archiving.html)

### Proposed ledger and attribution rules
The proposed reporting ledger is not a complete statutory accounting system. Preserve payment/capture/refund/chargeback/adjustment facts, provider-account and transaction identifiers, timestamps, exact amounts, and currency. Add referenced adjustments instead of silently overwriting history. Privacy-related deletion and lawful retention still need explicit resolution.

Separate client revenue from SaaS subscription billing. Agree on taxes, shipping, fees, discounts, failed payments, refunds, and recurring charges. Deduplicate the business transaction as well as each transport event so browser/server/provider messages cannot count one order three times. Reconciliation should expose discrepancies rather than erase them.

Retain original currency plus an approved FX rate, source, timestamp, and reporting currency. Missing FX produces an unavailable conversion, not an invalid combined total. Test refund-before-payment, repeated payment, repeated refund, and partial-to-full refunds.

A payment is a business fact; attribution is a versioned allocation claim. Define eligible touches, direct/unknown handling, conversion time, lookback, timezone, timestamp ties, and late arrivals. First/Last with one eligible touch allocate 100%; Linear divides among eligible touches with deterministic rounding. Preserve unknown sources and require allocated credit to reconcile with eligible net revenue. Refund treatment and recomputation must preserve audit history.

ROAS divides attributed revenue by advertising spend under matching currency, period, and definitions. With zero spend, the value is undefined. Keep platform-reported and internally attributed conversions separate. Attribution does not prove incremental lift.

### Minimum proposed verification
| Area | Evidence |
|---|---|
| Authorization | Denied read/write/list/export/job access across agencies and clients, including changed IDs and reused database connections |
| Ingestion | Schema/body limits, replay, conflicting events, duplicate business transactions, crashes, late/out-of-order arrival |
| Tracker/links | Approved destinations, consent, no browser secrets, campaign persistence, known single-page navigation |
| Ledger/models | Exact arithmetic, currency separation, reconciliation, manually calculated model/window/refund fixtures, deterministic reruns |
| OAuth/connectors | State/PKCE as applicable, wrong-tenant callbacks, scope loss, refresh races, expiry, revocation, quotas/backoff |
| API/React | Contract consistency, pagination/filter/sort/errors, approved generated client, empty/stale/partial states |
| Migrations | Fresh database, upgrades from fixtures, locking/index review, forward-fix/recovery plan without automatic destructive rollback |
| CI | Approved formatting/types, meaningful unit tests, PostgreSQL integration, connector contracts, and end-to-end cases |
| Operations | Redacted logs, correlation IDs, lag/failure/duplicate/queue/reconciliation metrics, named alert ownership |
| Release | Staging acceptance, agreed load, measured restore objectives, secret rotation, rollback, retention/deletion propagation |

Numeric service targets remain TBD until agreed and measured. No runtime, production API, or restore was tested by this research. No delivery date, cost, compatibility guarantee, certification, or universal accuracy claim is established. Repository CI remains future work.
