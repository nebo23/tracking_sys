# Engineering workflow
Updated: 2026-10-29.

## Current stage
The foundation is verified, and D-016/D-017 authorized tenancy slice 002-A. Its schema, services, and isolation tests are implemented; 51 checks passed and the additive migration is applied locally. Owner review remains pending. Authentication and remaining discovery decisions stay open for dependent work. The owner-provided [repository](https://github.com/nebo23/tracking_sys) is connected through origin/main; implementation and documentation changes remain local pending review and upload approval.

## Future feature delivery
1. Select one approved specification with clear boundaries and acceptance criteria.
2. Resolve open questions and approve its plan and dependencies.
3. Divide work into independently reviewable local changes.
4. Complete the approved specification and run relevant checks for business logic, permissions, integration contracts, or interface behavior.
5. Present the completed changes, validation evidence, and limitations to the owner; address review findings.
6. After explicit owner approval to upload, prepare the feature branch and commits as needed, push, and open or update the PR.
7. Follow the owner's merge decision and obtain the required approval before deployment.

Do not open an early draft PR or push partial work before this review gate unless the owner explicitly changes the workflow. Local checks and review do not by themselves authorize upload.

A PR should describe the problem, resulting behavior, spec and decision references, validation, limitations, and any migration, backfill, or recovery implications. Do not claim unexecuted checks.

## Specification states
Draft -> Awaiting clarification -> Approved for planning -> Ready for implementation -> In progress -> Verified -> Owner accepted.

The foundation and 002-A are verified locally and await owner review. Only 002-A is implemented within specification 002; subsequent slices retain their decision gates. A specification's presence alone does not authorize its implementation.

## Specification tooling
The local `.specify/` directory is a manually maintained set of principles and templates. Specify CLI has not been installed, configured, or initialized. Before adopting it, review the [official reference](https://github.github.com/spec-kit/reference/core.html) and [quickstart](https://github.github.com/spec-kit/quickstart.html), select a release, and verify its actual commands.

## Repository conventions
Use formal English for maintained text and filenames. Retain reusable project tools only. Remove one-time processing utilities and temporary exports. Do not produce a separate report for every small task; update the relevant specification, PR, decision record, or maintained document.

Install and run Python project dependencies in an isolated project virtual environment or container, using approved versions declared in backend/requirements.txt. Keep frontend dependencies local with a manifest and lockfile. Never install project packages globally. The backend environment is now established under specification 001.
