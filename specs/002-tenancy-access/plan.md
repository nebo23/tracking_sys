# Plan: 002-tenancy-access
Status: approved local scope implemented and verified under D-017/D-019; owner acceptance pending. Updated: 2026-10-30.

## Delivered sequence
1. 002-A: six-table tenancy model, role matrix, scoped services, atomic audit, and last-Owner protection. Historical [evidence](evidence.md).
2. 002-B: email/password identity, verification/recovery, opaque sessions, CSRF/Origin controls, throttling, and authenticated tenant HTTP operations.
3. 002-C: encrypted local email outbox, invitations, recipient matching, expiry/replay/revocation, and atomic membership/grant creation.
4. 002-D: scoped service credentials, live scope resolver, and cache partition contract for later consumers.
5. Verify the 115-case suite, reviewed migrations, native empty-schema upgrade, contracts, and container execution. Current [evidence](auth-evidence.md).

## Authority and acceptance mapping
The [002-A design](design.md) and [auth design](auth-design.md) are approved. D-019 resolves registration/session/schema/dependency/local mail choices. Google/Facebook login remains deferred under D-018. External email delivery is a production prerequisite; no vendor or paid service is selected.

HTTP and internal services enforce agency/client boundaries using authenticated identity. ClientViewer/Analyst require explicit client grants; financial access has its own grant. Invitations verify expiry/reuse, roles, recipient matching, and live revocation.

Trusted consumer scope and cache partition contracts are implemented/tested. Actual jobs, caches, reports, and exports remain in their own specifications and need their own end-to-end enforcement checks.

## Rollout and recovery
Revisions 0002_tenancy and 0003_auth are additive. Downgrades take exclusive locks and refuse populated state. Use reviewed forward fixes once data exists. The native database receives upgrades only; recovery exercises use guarded disposable PostgreSQL.

## Review and progression
Review implementation, [OpenAPI](../../contracts/openapi.json), [local walkthrough](../../docs/engineering/authentication.md), and evidence with the owner. Record acceptance and separate upload approval before push/PR. Do not begin specification 003 or production work without its review and required decisions.
