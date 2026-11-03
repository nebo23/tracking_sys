# 002-tenancy-access — Agencies, clients, identity, and access
Status: approved local 002 scope implemented and verified; owner acceptance pending. Level: L1. Updated: 2026-10-30.

## Sources
PDF-096,098,099(audit); USER multi-agency. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Define agency tenants, client workspaces, membership, sign-in, invitations, roles, service/API credentials, and auditing of sensitive changes.

D-016 records the owner's instruction to continue backend work through the existing specification sequence. The [first-slice design](design.md) makes the proposed schema, role matrix, and acceptance tests reviewable before business tables or access policy are implemented.

D-017 approved that design. Models, migration, authorization services, and 51 passing checks are documented in [002-A evidence](evidence.md). This historical first-slice evidence is superseded for current status by [002-B/C/D evidence](auth-evidence.md): 115 passing cases, authenticated HTTP, invitations, service credentials, and native revision 0003_auth. Consumer-specific job/export/cache implementations remain in their own specs.

## Out of scope
Advanced SSO/SAML or a default global-administrator bypass.

D-018 authorizes continuing with authentication and the remaining 002 work. Google/Facebook login is explicitly deferred. The concrete [authentication and access design](auth-design.md) was explicitly approved under D-019, including schema, dependencies, registration, and local email delivery.

## Acceptance criteria
1. With two agencies and two clients per agency, every read, mutation, export, and job enforces the relevant access boundary.
2. A client viewer cannot access another client in the same agency or financial fields excluded by their permissions.
3. Expired or reused invitations grant no new access; disabling a member revokes access.
4. Background jobs and cache keys carry tenant/client scope; a user-supplied tenant_id is insufficient authorization.

## Required design contracts
Agency, ClientWorkspace, User, Membership, RolePolicy, and AuditEvent; define an authorization matrix before routes.

## Dependencies and open decisions
Dependencies: [001-foundation](../001-foundation/spec.md)

Open decisions: Q-008. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
D-017 and D-019 authorize the implemented local scope. Owner acceptance remains pending. Google/Facebook sign-in is deferred, external email is a production prerequisite, and real job/export/cache consumers require their later end-to-end enforcement checks. Push and PR approval remain separate under D-012.
