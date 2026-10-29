# Project constitution
Version: 0.1 draft. Updated: 2026-10-29. Proposed engineering principles remain subject to owner review.

1. Record owner decisions. A proposal does not become a requirement without approval.
2. Use the confirmed stack: FastAPI, PostgreSQL, React, and Docker.
3. Design agency and client isolation from the first implementation, including jobs, caches, reports, and exports.
4. Keep social metrics, attribution results, and financial facts distinct, with provenance and completeness metadata.
5. Do not invent metrics, identities, or evidence. Unknown is not zero; attribution is not proof of causation.
6. Define interface contracts, versioning, idempotency, and monetary precision before presentation layers.
7. Include consent, retention, deletion, token protection, and data minimization in each relevant specification.
8. Build and validate the backend before React. The first commercial release must include both approved product capabilities.
9. Prefer the smallest independently reviewable PR, supported by relevant validation and recovery instructions.
10. Do not initialize a repository or push changes until the owner authorizes that stage.
11. Do not introduce unapproved major dependencies, paid services, microservices, or infrastructure.
12. Report measured coverage, failure modes, and limitations instead of claiming 100% readiness.
13. Maintain formal English throughout project documentation, filenames, code comments, and future repository contributions.
14. Retain only reusable project tooling. Remove one-time processing scripts and temporary artifacts after their task.
15. Isolate Python dependencies in a project virtual environment or container and record approved versions in backend/requirements.txt. Keep frontend dependencies project-local. Do not install project packages globally or copy host environments into images.
