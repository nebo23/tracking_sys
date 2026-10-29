# 002-tenancy-access — Agencies, clients, identity, and access
Status: Draft; implementation is not approved. Level: L1. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
PDF-096,098,099(audit); USER multi-agency. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Define agency tenants, client workspaces, membership, sign-in, invitations, roles, service/API credentials, and auditing of sensitive changes.

## Out of scope
Advanced SSO/SAML or a default global-administrator bypass.

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
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
