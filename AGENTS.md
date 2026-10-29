# Working agreement

## Authority and scope
- Work with the owner in Arabic; keep technical identifiers in English.
- Maintain formal English in all project files, filenames, documentation, code comments, and future repository contributions. Product interface localization is a separate decision (D-009).
- Keep only useful project assets and reusable tooling. Remove one-time processing scripts, temporary files, and document exports from the project after use (D-010).
- Confirmed stack: FastAPI, PostgreSQL, React, Docker.
- Isolate project dependencies. Install Python packages only in a project virtual environment or container, maintain approved versions in backend/requirements.txt, and keep frontend dependencies local with their manifest and lockfile. Never install project packages globally or copy host environments into container images (D-011).
- Confirmed launch: multi-agency SaaS with BOTH social analytics and attribution. Do not silently reduce launch to one agency or attribution only.
- The owner asked for research, local folders, draft specifications and a step-by-step review workflow first. Do not interpret these drafts as authorization to implement business features.
- The owner explicitly confirmed planning files and folders only for now, followed by review of spec 000. Do not create or run an executable scaffold until a later owner decision (D-008).
- The owner will create the GitHub repository. Do not run git init, create a remote, push, or open a PR until the owner supplies the repository and authorizes that stage.
- Product, scope, spending, hosting, major dependency and schema decisions need an explicit recorded owner decision. Present concrete recommendations with evidence; do not silently invent requirements.
- Routine reversible research, document organization and verification are authorized.
- Preserve owner edits. Keep proposals, source requirements and approved decisions distinct.
- Do not install tools merely because permission exists. Inspect installed tools and justify what is needed.
- Do not introduce agents by default. Research may use delegation when an applicable skill explicitly requires it.

## Future implementation workflow
Read README.md, docs/planning/decisions.md, and the active spec before work. Work one approved spec or independently reviewable slice at a time.
Spec -> clarification -> plan -> tasks -> implementation -> relevant checks -> review -> authorized PR/push -> owner merge decision.
Use the current official Spec Kit workflow if the CLI is adopted; local documents are presently manual drafts.
Never claim tests, app-review access, security compliance, successful deployments or feature completion without evidence.

## Data boundaries
Treat agency and client authorization as mandatory across APIs, jobs, cache, reports and exports.
Never commit tokens, real customer events, uploaded identifiers, signed download URLs or production data.
Use synthetic fixtures. No unapproved customer outreach or account changes.
Maintain source references and explicit missing/unsupported/stale states in every connector and analytics contract.
