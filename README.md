# Tracking System
Status: foundation, specification 002, D-022 additions, and the R-01 to R-03 corrections are merged into main (PR 1, `98747a2`). Specification 003 is completed at contract level on codex/spec-003-privacy-data-policy under D-023 to D-025 and awaits owner review: slice 003-A is implemented, and the consent, deletion, token-encryption, provider, and restore contracts are tested libraries whose end-to-end enforcement belongs to specifications 004-020. Updated: 2026-11-04.

A multi-agency SaaS platform combining social account analytics with lead and revenue attribution in its first commercial release. The confirmed technology stack is FastAPI, PostgreSQL, React, and Docker.

## Project status
The owner created [nebo23/tracking_sys](https://github.com/nebo23/tracking_sys); the workspace preserves its existing origin and main branch. Specification 001 provides the backend/database foundation. Approved specification 002 adds tenancy/access, email/password authentication, sessions/recovery, invitations, scoped service credentials, and local email capture. D-022 adds numeric email verification codes, optional Google sign-in, and an opt-in Gmail sender. The corrected local suite passes 196 checks; see the [authentication correction evidence](specs/002-tenancy-access/auth-corrections-2026-11-04.md). Facebook sign-in is deferred; React and later business capabilities retain their own specifications.

Start with [local setup](docs/engineering/local-environment.md), the [auth walkthrough](docs/engineering/authentication.md), and [current evidence](specs/002-tenancy-access/auth-evidence.md). Native tracking_sys on 127.0.0.1:5432 received the owner-approved additive 0004_identity upgrade on 2026-11-04 and has 19 application tables; existing rows, runtime privileges, and readiness were verified. Optional Docker configuration remains separate in .env.docker. Start Uvicorn to view the 36-operation API at http://127.0.0.1:8000/docs. Production startup remains blocked until a reviewed production rule set and approved delivery are recorded.

Complete an approved specification, run relevant checks, and present the result for owner review. Push and PR creation follow the owner's approval of the completed work for upload (D-012); merge and deployment require their respective owner decisions. Each specification uses a fresh branch from merged main, by default codex/spec-NNN-short-name (D-023, superseding D-020's shared branch). D-022 adds numeric email verification, optional Google sign-in, and an opt-in Gmail sender, verified locally; the native 0004 rollout is applied, and live provider checks remain owner steps.

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
| `backend/app/` | FastAPI, authenticated APIs, tenancy/auth models, scoped services, and local email worker. |
| `backend/migrations/` | Baseline, tenancy, and auth revisions with restricted runtime privileges and guarded recovery. |
| `backend/tests/` | Foundation unit checks and real PostgreSQL isolation, permission, migration, and concurrency tests. |
| `frontend/src/` | Future React application source. |
| `frontend/tests/` | Future component, interaction, and end-to-end interface tests. |
| `contracts/` | Generated health/auth/access OpenAPI snapshot; later event/provider contracts follow their specs. |
| `packages/tracker-js/` | Future first-party tracking library authored for client websites. Not a directory for downloaded dependencies. |
| `infra/docker/` | Local API, PostgreSQL, role initialization, migration, and optional mail-worker containers. |
| `infra/operations/` | Future deployment, monitoring, backup, restore, and incident runbooks. |
| `docs/` | Maintained product, architecture, planning, decision, and engineering documentation. |
| `specs/` | 22 specifications, numbered 000 through 021. Approved local 002 scope awaits owner review; later specs retain their decision gates. |
| `research_notes/` | Detailed evidence, source links, limitations, and research observations. |
| `reports/` | Synthesized research and decision reports; not an automatic report after every task. |

Python dependencies are isolated in .venv and pinned with hashes in [backend/requirements.txt](backend/requirements.txt). Development tools are locked separately. Containers install runtime requirements without copying host environments. No project packages are installed globally on the workstation. Future frontend dependencies will use a project-local manifest and lockfile.

One-time PDF repair tools, temporary files, and document exports have been removed from the project. The original reference PDF and final corrected reading copy are preserved outside the workspace. [Source provenance](docs/source/README.md) remains available to the team.

## Working method
Follow the specification sequence. D-017/D-019 authorized the completed local 002 scope. Review the implementation, explicit deferrals, and evidence before progression. Specification 003 is in progress: see its [reconciled design](specs/003-privacy-data-policy/design.md), [decision packet](specs/003-privacy-data-policy/decision-packet-003a.md), and [evidence](specs/003-privacy-data-policy/evidence.md). Completed 001/002 work was merged through PR 1; each later specification is reviewed with the owner before its upload.
