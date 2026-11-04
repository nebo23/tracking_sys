# Specification 002: first backend slice for review
Status: 002-A implemented and verified locally under D-017; owner review pending. Updated: 2026-10-29. Later slices remain proposals. See [evidence](evidence.md).

## Immediate delivery: 002-A, agency and client access model
Build the data model, authorization services, an additive migration, and real PostgreSQL isolation tests using the existing approved stack. Use synthetic identities in tests. Do not expose business HTTP routes until real authentication is implemented in 002-B. A supplied user or agency identifier must never stand in for authentication.

This is the first reviewable slice of 002, not completion of sign-in, invitations, API credentials, or the full specification. No additional dependency is needed for 002-A. The native tracking_sys database receives only the additive schema after approval and verification; fixtures and destructive migration checks use a separate disposable database.

## Approved schema
Identifiers are UUIDs. Creation/update timestamps are timezone-aware UTC. Statuses and roles use explicit constraints. Agency and client names are labels, not globally unique identifiers.

| Table | Main fields and constraints | Purpose |
|---|---|---|
| users | id, email_normalized (unique), display_name, status, created_at, updated_at | One identity may hold memberships in several agencies. Authentication secrets are introduced only with the approved sign-in design. |
| agencies | id, name, status, created_at, updated_at | Primary tenant boundary; active or suspended. |
| agency_memberships | id, agency_id, user_id, role, status, created_at, updated_at; unique (agency_id, user_id), unique (agency_id, id) | A user's role belongs to one agency. Disabling this membership does not disable their other agencies. |
| client_workspaces | id, agency_id, name, status, created_at, updated_at; unique (agency_id, id) | A workspace belongs to exactly one agency; active or archived. |
| client_grants | agency_id, client_id, membership_id, can_view_financials; composite primary key | Explicit client access for restricted members. Financial visibility defaults to false. |
| audit_events | id, agency_id, optional client_id, actor_user_id, action, resource_type, resource_id, occurred_at | Record sensitive successful mutations with identifiers and action codes only. No password, token, email, or customer payload. |

Composite foreign keys join client_grants to both (agency_id, client_id) and (agency_id, membership_id), preventing cross-agency relationships at the database layer. Audit client references also preserve agency scope. Hard deletion is excluded from this slice; future retention/deletion behavior is governed by specification 003. Personal identity fields use synthetic data until privacy decisions are resolved.

No public identity creation or registration endpoint is part of 002-A. Public registration and identity verification require the subsequent authentication decision. Test fixtures create identities only in the disposable test database.

## Approved authorization matrix
All access requires an active user, agency, and membership. An inactive workspace cannot be used for ordinary client operations. Unknown roles/actions are denied. Roles are a fixed versioned policy in code; editable custom roles are not proposed here.

| Capability | Owner | Admin | Analyst | ClientViewer |
|---|---|---|---|---|
| Read agency profile | Yes | Yes | Yes | No |
| Manage agency settings | Yes | Yes | No | No |
| Create/update/archive client workspaces | Yes | Yes | No | No |
| Read client workspaces | All in agency | All in agency | Explicit grants only | Explicit grants only |
| Read future financial fields | All in agency | All in agency | Only with a client financial grant | Only with a client financial grant |
| Manage non-owner members and client grants | Yes | Yes | No | No |
| Create/change/remove an Owner membership | Owner only; retain an active Owner | No | No | No |
| Read agency audit events | Yes | Yes | No | No |
| Use a resource in another agency without membership | No | No | No | No |

The same user may have different roles in different agencies. Agency-level roles never imply access to another agency. A suspended agency or disabled membership is checked at the time of each operation, not only when a future session is issued. Last-owner changes lock the agency row and check remaining active owners in the same transaction.

The financial permission is a contract for later finance/reporting specs; no revenue field or endpoint exists in 002-A. Analyst-specific analytics actions will be defined by those later specs. No service or support role receives an implicit global bypass.

## Backend implementation boundaries
- Put SQLAlchemy entities in app/models, authorization/query services in app/services, and future route schemas/handlers in app/api when authentication is ready. Avoid placeholder directories that have no implemented purpose.
- Keep an SQLAlchemy Session scoped to a unit of work. Mutations and their audit events commit together; failures roll back both. API dependencies will use that service boundary in 002-B.
- Require a trusted authenticated actor at the application boundary. Service-level tests supply synthetic actor IDs explicitly; they do not establish HTTP authentication.
- Apply agency/client filters inside every scoped query. Resolve the membership and client grant from the database, not a caller-supplied role string. Deny before returning records or mutating objects.
- Scope lookups and related-object assignments; a UUID is not an access grant. Reject a grant that joins different agencies even when both objects exist.
- Preserve tracking_app as a non-owner, non-superuser role. Grant only required table privileges; audit events are append-only for the runtime. The migrator owns schema changes.
- This slice proposes application authorization plus composite database constraints. PostgreSQL RLS is not silently enabled or claimed; a subsequent reviewed database policy may add defense in depth once trusted transaction context is defined.
- Add one migration after 0001_foundation, validate on fresh storage, and review SQL before applying upgrade to tracking_sys. Do not run downgrade/recovery tests against tracking_sys.

## Acceptance cases for 002-A
1. Create two synthetic agencies with two clients each and a user with different memberships across them.
2. Reject reads, updates, and grants across agency boundaries; verify foreign keys reject cross-agency links directly in PostgreSQL.
3. Analyst and ClientViewer see only explicitly granted clients. A grant to client A gives no access to client B in the same agency.
4. Financial visibility is false without an explicit grant for restricted roles. Test this as an authorization decision, not a nonexistent finance endpoint.
5. Disabled users/memberships, suspended agencies, and inactive workspaces cannot perform ordinary operations.
6. Admin cannot assign Owner or disable an Owner; concurrent owner changes cannot remove the last active Owner.
7. A failed mutation leaves neither the change nor a successful-change audit event. Successful changes write a scoped event in the same transaction.
8. Runtime cannot mutate audit history or migration version metadata. Model metadata matches the migration after upgrade.
9. Foundation health behavior still passes; schema-aware readiness checks the new migration head.

Exports, jobs, caches, invitations, and service credentials remain acceptance obligations for the slices that actually introduce those surfaces. 002-A tests do not establish those future guarantees.

## Remaining slices in specification 002
- **002-B:** approve and implement sign-in, session/token handling, registration, identity verification, password recovery, and authenticated agency/client HTTP routes. Choose authentication dependencies explicitly.
- **002-C:** invitations, acceptance expiry/replay protection, member management, and immediate access revocation. Resolve email delivery before enabling real messages.
- **002-D:** scoped service/API credentials and reusable job/cache/export authorization contracts. Verify each implemented consumer before claiming coverage.

The first commercial release still requires the full approved 002 scope, social analytics, attribution, and multiple agencies. This sequencing does not remove any launch capability.

## Evidence informing the proposal
The role names, schema, and delivery sequence above are project recommendations, not requirements imposed by a source.

- [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html): deny by default and check permissions for every operation; consider relationships as well as roles.
- [PostgreSQL 18 row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html): table owners and BYPASSRLS roles require special attention when adopting RLS. Ordinary table grants alone do not enforce per-tenant isolation.
- [FastAPI password and JWT example](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) and [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) inform the later authentication decision; neither is selected as the project's complete authentication design yet.
