# Tenancy and authentication review amendments

Status: Owner-requested implementation handoff for Claude; this package does not claim implementation or passing new checks. Prepared: 2026-11-04.

## Entry point and authority

The ready-to-use [Claude implementation prompt](implementation-prompt.md) coordinates this package and the private configuration handoff. It contains no credentials and preserves the review gates below.

The owner requested the accumulated review findings and deferred explanatory comments as English amendment files within the affected specifications. The owner selected both Gmail delivery and Google sign-in, subsequently confirmed numeric email-verification OTPs rather than the existing link, and explicitly requested coordination with Claude. D-021 records that direction. This document is the shared implementation handoff, not evidence that a change has already been made or uploaded.

Read `AGENTS.md`, `README.md`, the [decision register](../../docs/planning/decisions.md), [002 design](design.md), [authentication design](auth-design.md), and the current source before implementation. Read all three amendment files:

1. [Foundation amendments](../001-foundation/review-amendments.md): database comments and the Docker alternate-port/origin defect.
2. This file: authentication/access findings, model query references, and explanatory comments.
3. [Privacy and Google amendments](../003-privacy-data-policy/review-amendments.md): the owner-requested Google/Gmail continuation, its privacy boundary, proposed design, and review gates.

There were three findings in the earlier branch review, although the owner recalled two: T-01, T-02 below, and F-01 in foundation. Include all three; distinguish the static concurrency hypothesis from a reproduced failure. Do not manufacture a discovery amendment or add unrelated findings just to populate every specification.

## Execution contract for Claude

- Prepare small, independently reviewable slices: documentation/query references; confirmed behavioral fixes; then the reviewed Google/Gmail design and its approved implementation. New schema and major dependencies still require their recorded design decision. Missing Google credentials must not block independent documentation or local fixes.
- Work on `claude/development`, preserve the existing origin, and inspect the worktree first. At handoff preparation, pre-existing owner work includes a modified `backend/app/models/tenancy.py` and untracked privacy research/design files. Re-read status; do not overwrite, reset, stage, or claim those changes as your own.
- Use formal English for comments, files, and documentation. Explain every maintained backend source module, class, and function with concise purpose comments, including private helpers and constructors. Cover all `backend/app/api/` files, not just authentication routes. Do not edit third-party libraries, `.venv`, generated files, or dependencies merely to add comments. Do not add unrequested line-by-line narration.
- Separate comment-only changes from behavior. No unrelated refactoring, reformatting of owner changes, enum changes, new retention rules, React work, or deferred provider features.
- Use `.venv` or containers. Keep approved runtime dependencies and hashes in the maintained manifests; do not install globally.
- Use synthetic fixtures and a guarded disposable database. Do not seed, downgrade, truncate, delete from, or run destructive integration tests against native `tracking_sys`. A future native additive migration requires the reviewed migration/rollout step; do not run one while preparing these files.
- Never print or commit credentials, request passwords, raw tokens, authorization codes, provider responses containing secrets, or real customer data. Do not request secrets in chat. Read only necessary configuration, with secret values omitted from output.
- Validate the completed slice, record actual evidence and limitations, and present it for owner review. D-020 permits local slice commits on the working branch, with only the implementer's reviewed files staged. Push and PR creation/update require separate approval after review. Merge and deployment remain owner decisions.

## T-01: Investigate and resolve a possible user/agency lock cycle

Type: Concurrency finding. Priority: P2. Evidence: Static analysis; not reproduced by a deterministic concurrency test in this review.

Current source anchors are `AuthService._lock_user`, `_user_by_email`, `authenticate`, `AccessService.accept_invitation`, and `TenancyService.add_member`/`_audit`. Use symbol names rather than old walkthrough line numbers, which have shifted after owner edits.

Potential sequence:

1. Invitation acceptance by the invitee locks the agency and invitation.
2. A concurrent authenticated mutation by the inviter holds `FOR UPDATE` on the inviter's `users` row and waits for that agency lock.
3. Acceptance creates membership/grant audit entries through a `TenancyService` whose actor is the inviter. The audit foreign key to `users` needs a compatible key-share lock on that inviter row.
4. Each transaction can then wait for a lock held by the other. PostgreSQL aborts one transaction or a configured lock timeout interrupts it; the intended mutation fails.

The final `invitation.accepted` event uses the accepting actor; do not confuse it with intermediate membership/grant events attributed to the issuer. Confirm the complete current lock graph, constraints, and flush order before choosing the fix.

Required outcome:

- Build a bounded, deterministic two-connection test on disposable PostgreSQL, using explicit synchronization rather than relying only on sleeps. Capture whether the original cycle reproduces; do not state it was reproduced unless it was.
- Evaluate `FOR NO KEY UPDATE` for locks that only protect non-key user state, including both lookup helpers. It can remain compatible with foreign-key key-share locks while retaining write serialization. Confirm the ORM's generated PostgreSQL lock mode rather than assuming an option's meaning.
- Alternatively use a consistently ordered locking design if the full graph requires it. Do not simply remove user locks, weaken disablement/revocation checks, forge audit attribution, or swallow a deadlock as success.
- Verify concurrent invitation acceptance versus an inviter mutation completes safely, with correct membership/grants/audit and no duplicate acceptance. Re-run relevant password/session/revocation and last-Owner concurrency cases to preserve the original guarantees.

Reference: [PostgreSQL row-level locks](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS). This is support for the lock analysis, not proof the application race has already occurred.

## T-02: Persistently throttle invitation acceptance

Type: Missing control in the reviewed implementation. Priority: P2. Source: `backend/app/api/tenancy.py`, `accept_invitation`, and the existing `enforce_rate_limit` helper.

`/invitations/accept` reaches invitation lookup/locking without an explicit persistent attempt limit, despite the auth design requiring throttling of token consumption.

- Apply the existing independent counter mechanism before expensive invitation processing. Review dependency ordering: browser authentication may itself acquire locks before the handler; avoid claiming the handler limit precedes every lock if it does not.
- Use a stable authenticated subject and an appropriate peer limit with separate purpose namespaces. Do not derive the only bucket from an attacker-controlled token, put raw tokens into counters/logs, or blindly trust forwarded IP headers.
- Preserve existing policy where reusable. State any newly proposed endpoint-specific limit/window in the reviewed design/configuration instead of inventing an unexplained product rule.
- Return the existing sanitized 429 contract with `Retry-After`. Failed attempts must remain counted after business-transaction rollback; counters must be shared across API processes.
- Test success below the limit, invalid/replayed tokens, threshold crossing, independent-counter persistence after rollback, window recovery, and separation between subjects. Ensure denied attempts do not create membership or audit side effects.

## T-03: Explanatory comments retained from the walkthrough

Type: Documentation-only amendment. Use short English `#` comments above definitions/decorators. Keep useful existing docstrings. Comments must explain why a definition exists and when it is called, without claiming additional behavior.

### Configuration and schemas

| Location | Required explanation |
|---|---|
| `backend/app/config.py` imports `Literal`, `urlsplit`, `Fernet` | Restrict typed choices; parse URL components for origin validation; authenticated encryption/key validation. Imports do not execute the corresponding application feature by themselves. |
| `Settings` | Extend database settings with application auth/mail/browser policy; configuration is not the registration implementation or storage for individual users. |
| `validate_auth_secret` | Validate the required hexadecimal key material; distinguish a field validator from an ordinary unregistered helper. |
| `validate_mail_key` | Validate a Fernet key; `SecretStr` masks display but is not encryption. |
| `validate_development_boundary` | An after-model validator checks relationships across parsed settings, including exact origins, loopback exceptions, and the current production gate. Update the comment if a reviewed external adapter changes that gate. |
| `cookie_name` | Compute the cookie name on property access from `cookie_secure`; this does not issue a session cookie or run automatically after every validator. |
| `backend/app/api/schemas.py` | Explain common annotated types, `Input`, `Output`, each request/response class, inherited rules, and validators. `extra="forbid"` rejects unexpected fields; `from_attributes` reads object attributes; `hide_input_in_errors` affects textual errors and is not a substitute for the application's sanitized API handler. |

The database-specific definitions and `MigrationSettings` are covered by F-02. Do not omit them because this file also references configuration.

### Security helpers

In `backend/app/security.py`, explain every function and exception constructor: `AuthError.__init__`, `RateLimited.__init__`, `now_utc`, `normalize_email`, `new_token`, `digest`, `keyed_digest`, `csrf_token`, and `verify_password`.

- `normalize_email` validates syntax and normalizes under the existing case-insensitive account policy; it neither proves mailbox ownership nor detects every disposable/spam address. Do not add provider-specific dot/plus rewrites.
- `digest` is SHA-256 for high-entropy tokens, not password hashing. Passwords use the existing pwdlib/Argon2 mechanism.
- `keyed_digest` is a purpose-separated HMAC, not reversible encryption. `csrf_token` derives a session-bound value whose verification occurs elsewhere along with Origin checks.
- `verify_password` checks the supplied password against a stored hash; its dummy-hash work reduces timing differences for a missing credential but still returns rejection.

### Services and API

In `backend/app/services/auth.py`, cover `enforce_rate_limit` and every `AuthService` method, including `__init__`, `event`, `_lock_user`, `_user_by_email`, `_issue_token`, `register`, `request_verification`, `_consume_token`, `verify_email`, `login`, `authenticate`, `logout`, `revoke_sessions`, `logout_all`, `request_reset`, `_set_password`, `reset_password`, and `change_password`.

Explain transaction ownership, independent counter persistence, row locks, expiry/replay checks, session revocation, and outbox enqueueing where relevant. Currently `_issue_token` returns `None`, consumes prior tokens only for the same user/purpose, persists a digest, and queues a link using the raw token; it does not commit or send external mail itself. After G-07, update that explanation to distinguish numeric verification challenges from the retained reset/invitation link flows; do not copy the historical link description onto new OTP behavior.

Apply the same purpose-comment convention to the remaining maintained backend source files: tenancy/access/mail services, mail worker, API dependencies, middleware, routers, schemas, and package initializers with meaningful behavior. Explain that `SessionDep` obtains the database session through `get_session`; its function-scoped transaction commits before response delivery and rolls back on failure. A decorator dependency can enforce a check without supplying a handler argument. Distinguish the database Session from a browser login session.

For routes, identify input purpose, main service call, authentication/authorization dependency, meaningful response, and side effects concisely. Preserve sanitized errors and do not expose secrets to make Swagger debugging easier.

## T-04: PostgreSQL reference queries beside every mapped model

The owner requested complete copyable read/search queries as comments in `backend/app/models/tenancy.py`, `auth.py`, and `access.py`. Add a concise purpose comment for each class, then bounded read-only PostgreSQL query comments. `Entity` is a reusable column mixin with no table: explain it and do not invent an `entities` table.

| File | Class/table inventory | Useful lookup/filter |
|---|---|---|
| `tenancy.py` | `User` / `users` | User ID or synthetic normalized email; include administrative status and email verification timestamp. |
| | `Agency` / `agencies` | Agency ID and status. |
| | `AgencyMembership` / `agency_memberships` | Agency plus user/membership ID, role and membership status. |
| | `ClientWorkspace` / `client_workspaces` | Agency plus client ID. |
| | `ClientGrant` / `client_grants` | Agency plus membership/client composite key. |
| | `AuditEvent` / `audit_events` | Agency, optional client/actor, and bounded recent events. |
| `auth.py` | `PasswordCredential` / `password_credentials` | User ID and change timestamp; do not select password hashes. |
| | `AuthSession` / `auth_sessions` | User/session ID, expiry, last-seen and revocation metadata; omit token digests. |
| | `AuthToken` / `auth_tokens` | User ID, purpose, expiry and consumption metadata; omit token digests. |
| | `AuthRateLimit` / `auth_rate_limits` | Bucket metadata/expiry with a synthetic replacement key; avoid raw subject examples. |
| | `SecurityEvent` / `security_events` | User ID, action and recent occurrence time. |
| | `MailOutbox` / `mail_outbox` | Pending/delivered status, purpose, attempt count and sanitized failure code; omit encrypted payload. |
| `access.py` | `AgencyInvitation` / `agency_invitations` | Agency plus invitation ID/status; omit token digests. |
| | `InvitationClientGrant` / `invitation_client_grants` | Agency plus invitation/client composite key. |
| | `ServiceCredential` / `service_credentials` | Agency plus credential ID/status/expiry; omit key digests. |
| | `ServiceClientGrant` / `service_client_grants` | Agency plus credential/client composite key. |

Query requirements:

- Use existing table/column names, explicit columns, the actual `public` schema, stable ordering and `LIMIT 100` or less for list/search queries. Include a practical key lookup for each class; composite-key examples include all required components.
- Use valid PostgreSQL literals and clearly marked synthetic replacements, such as `'00000000-0000-0000-0000-000000000001'::uuid`; do not leave unbound `:parameter` placeholders and describe them as directly executable in pgAdmin.
- Scope tenant tables by agency and client/member as applicable. These queries are manual diagnostics; they do not implement application authorization and must only be run by an authorized database operator.
- Keep examples as comments. No automatic execution, real account values, token extraction, destructive SQL, fixtures, table creation, or native data mutation. Reference queries are read/search examples, not an exhaustive list of every possible SQL operation.

## Verified behavior that must not be silently changed

- `User.status == "active"` means administratively enabled. `email_verified_at` separately records verified ownership. An unverified active row must still be denied password login. Explain this distinction in comments/docs; do not add a `pending` enum or alter registration storage without a reviewed design.
- Registration currently atomically stores an unverified account, credential, token digest and encrypted outbox entry. Current verification uses a one-time link. The owner now selected numeric verification OTPs; implement that only through the reviewed G-07 design, and do not describe it as already working. Password reset and invitation links retain their existing semantics unless separately changed.
- A local worker writes `.eml` files; creating an outbox row is not proof of delivery to Gmail. The queued token is not returned by registration.
- Token expiry does not delete an account. Unverified-account cleanup/retention values in the privacy design are proposals, not approved deletion policy.
- The Swagger addition mentioned at the end of the conversation was withdrawn by the owner as a transcription error; no additional Swagger feature is requested.

## Completion checklist

- [ ] Confirm the current source and owner worktree state before edits.
- [ ] Implement comments/reference queries as an independently reviewable slice; verify executable ASTs are unchanged for that slice.
- [ ] Reproduce or explicitly qualify T-01, implement the supported fix, and verify concurrency/authorization guarantees.
- [ ] Implement and verify T-02 persistent invitation throttling.
- [ ] Complete F-01/F-02 under foundation and cross-reference their evidence.
- [ ] Review the proposed Google/Gmail design and dependency/schema decisions before its implementation; preserve unrelated privacy decision gates.
- [ ] Run appropriate unit/contract/PostgreSQL checks and Ruff, regenerate OpenAPI only if the public contract changes, and record actual evidence. A historical 115-case result is not a new run.
- [ ] Show changed files, outcomes, risks, unrun/provider-blocked checks and migration implications to the owner. Do not upload before approval.

## Handoff coordination evidence

On 2026-11-04, a separate Claude Code read-only session confirmed reading `AGENTS.md`, the three amendment files and D-021/Q-008. No implementation was requested in that session. It identified numeric-code lookup/verifier, collision, attempt-limit, scope and contract gaps while the owner clarified OTP requirements. The package was updated with G-06/G-07, the numeric-OTP decision and corresponding comment/contract requirements. This confirms a separate shared-project handoff, not synchronization with an existing IDE conversation, and is not test evidence for application changes.
