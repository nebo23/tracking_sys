# 002-tenancy-access — Agencies, clients, identity, and access
Status: Approved scope, D-022 additions, and R-01 to R-03 merged in PR 1 (`98747a2`). Level: L1. Status reconciled: 2026-11-10.

## Sources
PDF-096,098,099(audit); USER multi-agency. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Define agency tenants, client workspaces, membership, sign-in, invitations, roles, service/API credentials, and auditing of sensitive changes.

D-016 records the owner's instruction to continue backend work through the existing specification sequence. The [first-slice design](design.md) makes the proposed schema, role matrix, and acceptance tests reviewable before business tables or access policy are implemented.

D-017 approved that design. Models, migration, authorization services, and 51 passing checks are documented in [002-A evidence](evidence.md). The [002-B/C/D evidence](auth-evidence.md) records subsequent slices, D-022 additions, and the [196-test correction baseline](auth-corrections-2026-11-04.md). Native revision 0004_identity was last verified on 2026-11-04; it has not been rechecked for this status reconciliation. Consumer-specific job/export/cache implementations remain in their own specs.

## Out of scope
Advanced SSO/SAML or a default global-administrator bypass.

D-018 authorizes continuing with authentication and the remaining 002 work. The original Google/Facebook deferral was superseded for Google by D-022; Facebook remains deferred. The concrete [authentication and access design](auth-design.md) was explicitly approved under D-019, including schema, dependencies, registration, and local email delivery.

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
D-017, D-019, and D-022 authorize the implemented scope, merged in [PR 1](https://github.com/nebo23/tracking_sys/pull/1). Google sign-in, numeric verification OTP, and opt-in Gmail delivery are implemented. Facebook, production delivery approval, and real job/export/cache consumer enforcement remain deferred to their relevant decisions and specifications.
