# Tasks: 001-foundation
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for project foundation and environment.
- [ ] Resolve Q-004, Q-009, Q-013 and record the owner decision.
- [ ] Verify dependencies: 000-discovery.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable PR slices once the repository is available.
- [ ] Implement the first approved slice.
- [ ] Verify: After tool approval, a single setup guide starts the project on a clean machine with a disposable database.
- [ ] Verify: A forward migration and documented rollback or recovery procedure work on synthetic data.
- [ ] Verify: Health responses expose no secrets; readiness fails when a required dependency is unavailable.
- [ ] Verify: Local Python project dependencies install only inside a project virtual environment; backend/requirements.txt declares approved versions. React dependencies remain local to the frontend project. Container builds install from dependency manifests without copying the host virtual environment (D-011).
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Create or update a PR and push only after repository authorization.
- [ ] Record owner acceptance before progressing to dependent work.
