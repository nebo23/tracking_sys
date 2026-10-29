# Tasks: 002-tenancy-access
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for agencies, clients, identity, and access.
- [ ] Resolve Q-008 and record the owner decision.
- [ ] Verify dependencies: 001-foundation.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable PR slices once the repository is available.
- [ ] Implement the first approved slice.
- [ ] Verify: With two agencies and two clients per agency, every read, mutation, export, and job enforces the relevant access boundary.
- [ ] Verify: A client viewer cannot access another client in the same agency or financial fields excluded by their permissions.
- [ ] Verify: Expired or reused invitations grant no new access; disabling a member revokes access.
- [ ] Verify: Background jobs and cache keys carry tenant/client scope; a user-supplied tenant_id is insufficient authorization.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Create or update a PR and push only after repository authorization.
- [ ] Record owner acceptance before progressing to dependent work.
