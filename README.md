# Tracking System
Status: planning and specification review. Updated: 2026-10-29.

A multi-agency SaaS platform combining social account analytics with lead and revenue attribution in its first commercial release. The confirmed technology stack is FastAPI, PostgreSQL, React, and Docker.

## Project status
The workspace contains research, draft specifications, and directory documentation. No application scaffold, running service, database, or Git repository has been created. The owner will create the GitHub repository and authorize repository operations separately.

All maintained project content and filenames must use formal English. Product localization is a separate, unresolved decision. Discussions with the owner may remain in Arabic.

## Reading order
1. [Product brief](docs/product/brief.md)
2. [Market and feasibility report](reports/market-and-feasibility.md)
3. [Source requirements review](docs/product/pdf-review.md) and [feature register](docs/product/feature-register.md)
4. [Delivery roadmap](docs/planning/roadmap.md)
5. [Decision register](docs/planning/decisions.md)
6. [Specification index](specs/README.md)
7. [Engineering workflow](docs/engineering/workflow.md)

## Directory guide
| Directory | Purpose |
|---|---|
| `.specify/` | Shared project principles and specification templates. Manually maintained; Specify CLI is not installed or configured. |
| `backend/app/` | Future FastAPI application: API handlers, domain logic, integrations, and background processing. |
| `backend/migrations/` | Future versioned database schema changes and controlled data migrations. |
| `backend/tests/` | Future unit, integration, authorization, and backend workflow tests. |
| `frontend/src/` | Future React application source. |
| `frontend/tests/` | Future component, interaction, and end-to-end interface tests. |
| `contracts/` | Future machine-readable API and event interface definitions shared by producers and consumers. |
| `packages/tracker-js/` | Future first-party tracking library authored for client websites. Not a directory for downloaded dependencies. |
| `infra/docker/` | Future container images and local service configuration. |
| `infra/operations/` | Future deployment, monitoring, backup, restore, and incident runbooks. |
| `docs/` | Maintained product, architecture, planning, decision, and engineering documentation. |
| `specs/` | 22 draft specifications, numbered 000 through 021, each with requirements, a plan, and tasks. |
| `research_notes/` | Detailed evidence, source links, limitations, and research observations. |
| `reports/` | Synthesized research and decision reports; not an automatic report after every task. |

Python dependencies must be installed in a project virtual environment and declared with approved versions in [backend/requirements.txt](backend/requirements.txt). That file is currently a planning placeholder; no packages have been selected or installed for this application. Third-party JavaScript dependencies will use a project-local package manifest, lockfile, and `node_modules/`. Do not install project packages globally. Container builds install dependencies from these files rather than copying host environments. Actual setup belongs to approved spec 001 work.

One-time PDF repair tools, temporary files, and document exports have been removed from the project. The original reference PDF and final corrected reading copy are preserved outside the workspace. [Source provenance](docs/source/README.md) remains available to the team.

## Working method
Review spec 000 first. Approve scope and material decisions before implementation. Use small, reviewable changes and relevant validation. Draft specifications are not implementation authorization, delivery estimates, or a guarantee of complete platform access.
