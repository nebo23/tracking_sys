# Decision register
Updated: 2026-10-29. An unanswered question or proposal is not approval.

## Confirmed decisions
| ID | Decision | Evidence |
|---|---|---|
| D-001 | FastAPI, PostgreSQL, React, and Docker. | Initial owner request. |
| D-002 | Backend first, then frontend and production, using specifications and reviews. | Initial owner request. |
| D-003 | The owner creates the GitHub repository. No initialization, remote creation, push, or PR at this stage. | Initial owner request. |
| D-004 | Social analytics and attribution must both be included in the first release. | Explicit scope clarification. |
| D-005 | Multi-agency SaaS from the first release. | Explicit operating-model clarification. |
| D-006 | Broad customer market; no industry vertical selected. | Owner clarification that the product is SaaS for all customer types. |
| D-007 | Research, local planning, and necessary tools are authorized. This does not approve paid subscriptions or additional technology decisions. | Initial owner request. |
| D-008 | Planning files and folders only, followed by spec 000 review. No executable application scaffold yet. | Explicit owner choice on 2026-10-28. |
| D-009 | All maintained project content and filenames must use formal English for collaboration with the team. Conversation may remain Arabic; product localization is separate. | Explicit owner instruction on 2026-10-29. |
| D-010 | Remove one-time PDF processing scripts, temporary files, and unrelated generated artifacts from the project. Retain only useful project assets and reusable tooling. | Explicit owner cleanup instruction on 2026-10-29. |
| D-011 | Use an isolated project virtual environment for Python; maintain approved versions in backend/requirements.txt. Keep frontend dependencies project-local with a manifest and lockfile. Containers install declared dependencies rather than copying host environments. | Explicit owner environment and requirements.txt instructions on 2026-10-29. |

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
| Q-008 | Authentication, registration, and roles. | Owner, administrator, analyst, and client viewer are proposed roles. | 002 |
| Q-009 | React tooling, TypeScript, ORM, migrations, and jobs. | No implicit dependency selection. | 001 |
| Q-010 | Build versus integrate per capability. | Compare cost, access, and vendor dependence. | 009-015 |
| Q-011 | Freshness, SLO, RPO, and RTO targets. | Set measurable targets from load and budget, not a 100% guarantee. | 019, 020 |
| Q-012 | Retention, consent, and deletion per data class. | Resolve before receiving real customer data, considering applicable markets. | 003 |
| Q-013 | Review and merge responsibilities. | Small PRs linked to approved specs; owner acceptance remains required. | Workflow |
| Q-014 | Exact source features required for launch. | Approve a subset containing both product capabilities rather than adopting all source MVP labels. | 000 |

## Recording a decision
Record the date, question, alternatives, evidence, cost and data implications, owner approval, status, and affected specifications. Preserve superseded decisions and link their replacements.
