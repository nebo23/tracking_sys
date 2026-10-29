# Engineering workflow
Updated: 2026-10-29.

## Current stage
Review the product brief, research, feature register, and provider limitations. Approve spec 000 and decisions needed for spec 001. The owner will create the repository. No commits, pushes, or PRs are authorized yet.

## Future feature delivery
1. Select one approved specification with clear boundaries and acceptance criteria.
2. Resolve open questions and approve its plan and dependencies.
3. Divide work into independently reviewable slices.
4. Create a branch and draft PR after an inspectable change exists and repository work is authorized.
5. Implement the approved slice and run relevant checks for business logic, permissions, integration contracts, or interface behavior.
6. Push and update the same PR with actual validation evidence.
7. Obtain review and follow the owner's merge and deployment authorization.

A PR should describe the problem, resulting behavior, spec and decision references, validation, limitations, and any migration, backfill, or recovery implications. Do not claim unexecuted checks.

## Specification states
Draft -> Awaiting clarification -> Approved for planning -> Ready for implementation -> In progress -> Verified -> Owner accepted.

All current specifications remain drafts. Their presence does not authorize application implementation.

## Specification tooling
The local `.specify/` directory is a manually maintained set of principles and templates. Specify CLI has not been installed, configured, or initialized. Before adopting it, review the [official reference](https://github.github.com/spec-kit/reference/core.html) and [quickstart](https://github.github.com/spec-kit/quickstart.html), select a release, and verify its actual commands.

## Repository conventions
Use formal English for maintained text and filenames. Retain reusable project tools only. Remove one-time processing utilities and temporary exports. Do not produce a separate report for every small task; update the relevant specification, PR, decision record, or maintained document.

Install and run Python project dependencies in an isolated project virtual environment or container, using approved versions declared in backend/requirements.txt. Keep frontend dependencies local with a manifest and lockfile. Never install project packages globally. Actual environment creation is deferred until spec 001 is approved.
