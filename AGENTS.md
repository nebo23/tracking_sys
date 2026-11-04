# Working agreement

## Authority and scope
- Work with the owner in Arabic; keep technical identifiers in English.
- Maintain formal English in all project files, filenames, documentation, code comments, and future repository contributions. Product interface localization is a separate decision (D-009).
- Keep only useful project assets and reusable tooling. Remove one-time processing scripts, temporary files, and document exports from the project after use (D-010).
- Confirmed stack: FastAPI, PostgreSQL, React, Docker.
- Isolate project dependencies. Install Python packages only in a project virtual environment or container, maintain approved versions in backend/requirements.txt, and keep frontend dependencies local with their manifest and lockfile. Never install project packages globally or copy host environments into container images (D-011).
- Confirmed launch: multi-agency SaaS with BOTH social analytics and attribution. Do not silently reduce launch to one agency or attribution only.
- The owner asked for research, local folders, draft specifications and a step-by-step review workflow first. Do not interpret these drafts as authorization to implement business features.
- D-013 supersedes the planning-only restriction in D-008 for specification 001: the owner authorized starting the backend and database foundation using the existing specification sequence. Later product decisions remain open and must not block independent foundation work.
- D-014 approves PostgreSQL 18, SQLAlchemy 2.x, Alembic, and Psycopg 3 for the foundation. Do not introduce agency, client, lead, or revenue tables before their relevant specification and schema review.
- D-015 selects the owner's native PostgreSQL database tracking_sys on localhost:5432 for local development. Keep owner-entered passwords in ignored .env. Preserve optional Docker credentials in ignored .env.docker; do not run migration integration tests against the owner's database.
- D-016/D-017 authorize specification 002-A as defined in specs/002-tenancy-access/design.md: the six models, access policy, migration, and isolation tests. Authentication, business HTTP endpoints, invitations, and service credentials remain subsequent slices. Apply only reviewed additive upgrades to tracking_sys; destructive checks require a disposable database.
- D-018/D-019 authorize the remaining specification 002 implementation in specs/002-tenancy-access/auth-design.md, including its schema and authentication dependencies. Use local development mail capture; do not send external messages. Google/Facebook sign-in is deferred. Existing review-before-upload and native-data preservation requirements remain in force.
- The owner supplied https://github.com/nebo23/tracking_sys; the local workspace is already connected to origin on main (D-012). Preserve the existing repository and remote.
- Complete one approved specification, run relevant checks, and present the result for owner review before uploading. Push or open/update a PR only after the owner approves the completed work for upload. Merge remains an owner decision. The repository link alone does not approve implementation, upload, or deployment.
- D-020 historically designated claude/development for specifications 001/002. D-023 supersedes that branch rule: use a fresh branch from current merged main for each specification, defaulting to codex/spec-NNN-short-name; keep that specification's amendments on its branch. Specification 003 uses codex/spec-003-privacy-data-policy. Do not commit to main or reuse claude/development for new specifications. Commit each completed specification or slice locally, present it for owner review, and push only after upload approval. Merge remains an owner decision.
- D-022 approves implementing the Google sign-in, numeric verification OTP, and Gmail delivery design in specs/002-tenancy-access/auth-design.md with its listed dependency, schema, account policy, OTP values, legacy transition, and separate sender client. Native migration rollout, production delivery, live provider use beyond owner-operated smoke tests, and upload remain separately gated.
- Product, scope, spending, hosting, major dependency and schema decisions need an explicit recorded owner decision. Present concrete recommendations with evidence; do not silently invent requirements.
- D-023 authorizes continuing specification 003 toward review and preparing its Claude handoff. Refresh the proposal against merged specification 002, resolve only decisions needed for the next slice, and continue independent authorized work. Candidate retention periods, erasure policy, lifecycle privileges, schema, and new dependencies are not approved merely by progression authorization. See specs/003-privacy-data-policy/implementation-prompt.md.
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
