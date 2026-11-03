# Decision register
Updated: 2026-10-29. An unanswered question or proposal is not approval.

## Confirmed decisions
| ID | Decision | Evidence |
|---|---|---|
| D-001 | FastAPI, PostgreSQL, React, and Docker. | Initial owner request. |
| D-002 | Backend first, then frontend and production, using specifications and reviews. | Initial owner request. |
| D-003 | The owner creates the GitHub repository. Repository creation and remote setup were reserved to the owner; this setup condition was fulfilled by D-012. | Initial owner request; historical setup restriction. |
| D-004 | Social analytics and attribution must both be included in the first release. | Explicit scope clarification. |
| D-005 | Multi-agency SaaS from the first release. | Explicit operating-model clarification. |
| D-006 | Broad customer market; no industry vertical selected. | Owner clarification that the product is SaaS for all customer types. |
| D-007 | Research, local planning, and necessary tools are authorized. This does not approve paid subscriptions or additional technology decisions. | Initial owner request. |
| D-008 | Initially, planning files and folders only, followed by spec 000 review. The implementation restriction is superseded for specification 001 by D-013. | Explicit owner choice on 2026-10-28; retained as history. |
| D-009 | All maintained project content and filenames must use formal English for collaboration with the team. Conversation may remain Arabic; product localization is separate. | Explicit owner instruction on 2026-10-29. |
| D-010 | Remove one-time PDF processing scripts, temporary files, and unrelated generated artifacts from the project. Retain only useful project assets and reusable tooling. | Explicit owner cleanup instruction on 2026-10-29. |
| D-011 | Use an isolated project virtual environment for Python; maintain approved versions in backend/requirements.txt. Keep frontend dependencies project-local with a manifest and lockfile. Containers install declared dependencies rather than copying host environments. | Explicit owner environment and requirements.txt instructions on 2026-10-29. |
| D-012 | The owner supplied [nebo23/tracking_sys](https://github.com/nebo23/tracking_sys). Complete each approved specification and relevant checks, then obtain owner review and approval before push or PR creation/update. The existing local origin and main branch are preserved. Merge remains an owner decision; sharing the repository does not approve implementation or publication of pending work. | Repository URL and explicit review-before-upload instruction on 2026-10-29; local Git status and remote verified. |
| D-013 | Begin backend/database foundation implementation through specification 001 using the existing sequence. Supersedes D-008 for this independent work; remaining discovery decisions are deferred to affected specifications, not silently approved. No business schema, frontend, deployment, push, or PR is authorized. | Explicit owner instruction on 2026-10-29 to follow the specifications and begin with backend/database. |
| D-014 | Use PostgreSQL 18, SQLAlchemy 2.x, Alembic, and Psycopg 3. The baseline establishes migration version control without business tables. Supporting server/settings/test tools are recorded in isolated dependency manifests. | Explicit owner approval of the proposed database tools on 2026-10-29. |
| D-015 | Use the owner's existing native PostgreSQL database tracking_sys for local backend development. Use owner-supplied administrator credentials for initial provisioning only; keep dedicated runtime/migration passwords in ignored local configuration. Preserve the optional Docker database and its credentials separately; keep Python dependencies in .venv. | Owner request, explicit database-name confirmation, and supplied connection details on 2026-10-29. Native PostgreSQL 18.4 on localhost:5432, both dedicated connections, baseline migration, and in-process application readiness verified. |
| D-016 | Continue backend work through specification 002 using independently reviewable slices. This is progression authorization, not upload approval or formal acceptance of every foundation review item. | Owner instruction on 2026-10-29 to start backend work and inspect the specification after native database verification. |
| D-017 | Approve and implement [002-A](../../specs/002-tenancy-access/design.md): six entity tables, Owner/Admin/Analyst/ClientViewer policy, explicit client/financial grants, migration, transactional audit, and isolation tests. No business HTTP routes before authentication in 002-B. | Explicit owner answer on 2026-10-29: approve the design and begin implementation. |
| D-018 | Continue specification 002 including authentication. Defer Google/Facebook login until the owner supplies provider configuration. Prepare and resolve the remaining material authentication/schema/dependency choices before their implementation. | Explicit owner instruction on 2026-10-29 to continue spec 002 and auth, leaving Google/Facebook login for later. |

| D-019 | Approve and implement [002-B/C/D](../../specs/002-tenancy-access/auth-design.md): auth schema, self-service registration, email verification, opaque sessions, invitations, service credentials, pwdlib/Argon2, email-validator, and cryptography. Use local development email capture; external delivery remains a production prerequisite. Google/Facebook sign-in stays deferred; upload approval is unchanged. | Explicit owner approval and local mailbox selection on 2026-10-30. |

## Open decisions
| ID | Decision required | Proposal for discussion | Affected work |
|---|---|---|---|
| Q-001 | Mandatory launch platforms, account types, and metrics. | Four platforms were named; each requires its own access gate. No silent omission. | 010-013 |
| Q-002 | Initial lead and sale evidence sources. | Form, audited manual entry, one payment integration, and one scheduler are candidates. | 004, 007, 015 |
| Q-003 | Initial markets and data storage region. | Do not infer Egypt-only scope from the conversation language or source PDF. | Privacy, hosting, payments |
| Q-004 | Expected load and monthly budget. | Specify agencies, clients, accounts, event volumes, and historical coverage. | Infrastructure, quotas, API costs |
| Q-005 | Subscription customer, trial, and usage limits. | An agency subscription with client limits is only a proposal. | 017 |
| Q-006 | Product interface languages, currencies, and FX source. | Arabic RTL and English remain candidates. English repository content does not resolve this question. | 007, 018 |
| Q-007 | Attribution rules. | Define lookback, direct traffic, timezone, refunds, and late events. | 008 |
| Q-008 | Production mail delivery and deferred social sign-in configuration. | D-019 resolves local email/password registration, verification, opaque sessions, invitations, service credentials, and local mail delivery. An external mail provider and Google/Facebook configuration remain deferred. | 002, 020 |
| Q-009 | React/TypeScript and job tooling. | Database tools are resolved by D-014 and local authentication dependencies by D-019; other tools require decisions when their specifications need them. | 002, 009, 018 |
| Q-010 | Build versus integrate per capability. | Compare cost, access, and vendor dependence. | 009-015 |
| Q-011 | Freshness, SLO, RPO, and RTO targets. | Set measurable targets from load and budget, not a 100% guarantee. | 019, 020 |
| Q-012 | Retention, consent, and deletion per data class. | Resolve before receiving real customer data, considering applicable markets. | 003 |
| Q-013 | Additional team review assignments, if any. | D-012 confirms owner review of completed specifications before upload; merge remains an owner decision. Team reviewer assignments are still open. | Workflow |
| Q-014 | Exact source features required for launch. | Approve a subset containing both product capabilities rather than adopting all source MVP labels. | 000 |

## Recording a decision
Record the date, question, alternatives, evidence, cost and data implications, owner approval, status, and affected specifications. Preserve superseded decisions and link their replacements.
