# Development environment readiness
Status: planning only. The following is a historical inventory of the owner's workstation, not a team-wide or production version requirement.

| Tool | Observation on 2026-10-28 |
|---|---|
| Python | 3.12.4 installed |
| Node.js | v24.17.0 installed |
| npm | 11.13.0 installed |
| Docker CLI | 29.5.3 installed |
| Docker Engine | The Linux engine was not reachable at inspection time |
| uv | 0.12.9 installed |
| Git | Executable available; no repository initialized |
| Project services | FastAPI, React, and PostgreSQL have not been initialized or started for this project |

No additional language runtime is needed for the current documentation review. Under D-011, Python dependencies must be isolated in a project virtual environment and recorded with approved versions in backend/requirements.txt. Frontend dependencies must remain local to the project with a package manifest and lockfile. No project packages may be installed globally.

The requirements.txt file is currently a documented placeholder with no selected dependencies. The virtual environment and frontend manifests will be created during approved specification 001 work. A virtual environment lives on the workstation but isolates Python packages from other projects; it does not replace Docker. Container builds install declared dependencies into the container environment and must not copy the host .venv or node_modules.

Runtime versions, package management tooling, dependency locking strategy, images, authentication, ORM, migrations, and job processing remain unapproved.

After spec 001 is approved, define a reproducible team setup, use example configuration without secrets, verify Docker Engine availability, and document actual startup and validation commands. Do not treat the current folder structure as a runnable application.
