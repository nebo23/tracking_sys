# Specification 003-A decision packet
Status: prepared for owner decision on 2026-11-04 under D-023. Nothing below is approved until the owner records a decision. Recommendations are marked; alternatives are listed with their effects.

Basis: merged main `98747a2` (PR 1) at revision `0004_identity`, the [reconciled design](design.md), [evidence](evidence.md), and [sources](../../research_notes/privacy-data-policy/sources.md). Q-003 (markets) is not needed for any decision here: the records concerned belong to the platform's own users and security state, not to client end customers.

## Already done without these decisions
003-A1 (data-class registry) and 003-A2 (log allowlist) are implemented locally as independent work under D-023. Neither changes the schema, dependencies, retention, deletion, privileges, or the API. The owner may accept or reject them in review.

## Decision 1: boundaries of the next slices

| Slice | Content | Requires | Schema, API, and privilege effect |
|---|---|---|---|
| 003-A3 credential-state lifecycle | `python -m app.lifecycle`: one bounded run, like the mail worker, that deletes ended sessions, tokens, verification challenges, OAuth transactions, expired rate-limit buckets, and ended outbox rows, plus development `.eml` cleanup | Decisions 2, 4, 5 | No table or API change. Grants only (decision 4). |
| 003-A4 mail expiry | `expires_at` on reset and invitation messages | Decision 5 | None |
| 003-A5 account closure and erasure | `POST /auth/close-account`, identity pseudonymization, credential and external-identity deletion, last-Owner refusal | Decisions 3, 4 | Additive migration 0005 and one API operation |
| Deferred | Unverified-registration purge, ended invitations and service credentials, security and audit event retention, legal holds | Later decision 2 values, counsel | `legal_holds` when the first held class becomes eligible |

**Recommendation:** approve A3 and A4 together as the next slice, then A5 as a separate slice. A3 and A4 remove only state that is already unusable, need no API, and provide the runner that A5 reuses. A5 changes identity data and the public API, so it deserves its own review.

Alternatives: (b) A5 first, because closure is currently impossible for a platform user; this is a larger first review. (c) Stop 003-A after A1/A2 until specification 004; ended credential rows then keep accumulating and no closure path exists.

Not proposed for A3: a `retention_runs` table and `legal_holds`. A3 predicates are time-based. Every run re-evaluates them, so an interrupted, failed, or skipped (`SKIP LOCKED`) batch is retried on the next run without a cursor, and no eligible row can be permanently skipped. Counts are printed as JSON. Both tables become necessary when security, audit, or account classes become eligible.

## Decision 2: retention for current records
The Q-012 candidate values in the design remain proposals. Each row below is eligible only when its anchor has passed and the period has elapsed, compared strictly against one cutoff sampled from the database clock per run.

| Table | Eligible after (anchor) | Candidate period | Effect on current behavior | Recommendation |
|---|---|---|---|---|
| auth_sessions | `revoked_at`, `expires_at`, or `last_seen_at` plus idle lifetime | 30 days | None: such sessions already fail authentication. A pending Google link needs its initiating session only for the 10-minute transaction. | Approve 30 days |
| auth_tokens | `consumed_at` or `expires_at` | 7 days | None: replay of a deleted token finds no digest and gets the same generic error. | Approve 7 days |
| verification_challenges | `consumed_at`, `invalidated_at`, or `expires_at` | 7 days | None: the daily failure cap lives in `auth_rate_limits`, not in challenge rows. | Approve 7 days |
| oauth_transactions | `consumed_at` or `expires_at` (10 minutes) | 1 day | None: an unknown state digest is rejected like an expired one. | Approve 1 day |
| auth_rate_limits | `expires_at` | At expiry (design candidate: 1 day) | None: an expired bucket already restarts at one attempt. | Approve at expiry |
| mail_outbox rows | `delivered_at`, or payload cleared at expiry | 30 days | Delivery state disappears; the row holds no recipient after clearing. | Approve 30 days |
| Unverified users | `created_at`, never verified, no membership or external identity | 30 days | Needs the decision 3 erasure path | Decide with A5 |
| agency_invitations with grants | Accepted, revoked, or `expires_at` | 90 days | Invitee emails of non-users disappear; audit `resource_id` becomes a documented dangling reference | Keep pending |
| service_credentials with grants | Revoked or `expires_at` | 90 days | As above | Keep pending |
| security_events | `occurred_at` | 1 year | Needs a lifecycle `DELETE` grant; affects security investigations | Keep pending (counsel) |
| audit_events | `occurred_at` | 2 years | Accountability record for tenant changes | Keep pending (counsel) |
| external_identities | Unlink or account erasure only | Not time-based | Decision 3 | Not applicable |

The six recommended values would become reviewed settings with bounded ranges, not unreviewed "development defaults". Holds are not needed for these short-lived records. Alternatives: shorter periods (sessions 7 days, outbox rows 7 days); or approve the security and audit periods now as well. The latter is not recommended before counsel and Q-003.

## Decision 3: account closure and erasure
Current behavior: no closure or erasure path exists. The runtime cannot change a user's email, name, or status; a disabled user is denied everywhere.

**Recommendation: P1, pseudonymize in place, then delete credential state.**

1. **Request.** Authenticated `POST /auth/close-account` with the exact Origin, CSRF header, and throttling. Reauthentication: an account with a password credential submits its current password. A Google-only account has no password. It must present a session created within the last 10 minutes, which means a fresh Google sign-in, or it may first set a password through the existing reset email. The old password-only proposal did not cover Google-only accounts.
2. **Locks and last-Owner protection.** Lock the user row first (the existing `FOR NO KEY UPDATE` order). Then lock each agency in which the user has an active membership, `FOR UPDATE` in agency-ID order, which is the lock every tenancy mutation already takes. Where the user is an Owner, count the other active Owners whose users are active. If any agency would be left without one, return 409 `state_conflict` and change nothing. A concurrent demotion, disablement, or co-owner closure serializes on the same agency row, so two Owners cannot both leave (analysis in [design §16](design.md#16-implementation-slices-and-status)).
3. **One transaction.** Set `email_normalized` to `closed-<user id>@tracking.invalid`; registration validation rejects the special-use `.invalid` domain, so this value can never collide with a real address. Set `display_name` to `Closed account`, `status` to `disabled`, and `closed_at` to the current time. Revoke every session, consume open tokens, and invalidate open challenges. Disable the user's memberships with `membership.updated` audit rows, and record the security event `account_closed`.
4. **Deletion.** The lifecycle runner deletes the closed user's password credential, external identity, OAuth transactions, tokens, challenges, and sessions on its next run, without a waiting period.
5. **Kept.** The pseudonymized user row, disabled memberships, `audit_events` and `security_events` that reference the user ID, and invitations and service credentials the user created. Their service keys already stop working, because a creator must keep an active manager membership.
6. **Email reuse.** The original address is free immediately. A new registration creates a new user ID with no link to the old audit history; pending invitations addressed to that email work for the new account.
7. **External-identity reuse.** After the runner deletes the identity row, the same Google account may sign up again under the D-022 policy. Until then, that Google sign-in resolves to the closed, disabled user and is refused.
8. Closure is final. An administrator-disabled account has `closed_at` NULL, which distinguishes it.

Schema and API for P1: additive migration 0005 adds `users.closed_at` (nullable, with a check that a closed user is disabled). It adds `account_closed` to the `security_events` action constraint and grants `tracking_app` `UPDATE (email_normalized, display_name, status, closed_at)` on `users`. OpenAPI gains one operation.

Alternatives:
- **P1 with immediate deletion.** The API transaction also deletes credentials and the external identity. The Google account is free at once, but `tracking_app` needs `DELETE` on identity and credential tables.
- **Emailed closure code instead of the 10-minute session rule.** This proves current mailbox control for every account, but needs a new challenge purpose and mail purpose (schema change).
- **P2: hard deletion.** Make `audit_events.actor_user_id` and `security_events.user_id` nullable with `ON DELETE SET NULL`. This loses audit attribution and needs a larger migration; not recommended.
- **P3: disable only.** This retains identity data and does not satisfy erasure.

## Decision 4: privilege model
Current `tracking_app` grants on the disposable database at `0004_identity`, verified on 2026-11-04:

| Table | tracking_app now | P1 change (A5) | Proposed tracking_lifecycle (L1) |
|---|---|---|---|
| users | SELECT, INSERT, UPDATE (email_verified_at, updated_at) | Add UPDATE (email_normalized, display_name, status, closed_at) | SELECT |
| password_credentials | SELECT, INSERT, UPDATE | None | SELECT, DELETE (closed users) |
| auth_sessions, auth_tokens | SELECT, INSERT, UPDATE | None | SELECT, DELETE |
| verification_challenges | SELECT, INSERT, UPDATE (failed_attempts, consumed_at, invalidated_at) | None | SELECT, DELETE |
| oauth_transactions | SELECT, INSERT, UPDATE (consumed_at) | None | SELECT, DELETE |
| external_identities | SELECT, INSERT, UPDATE (last_login_at) | None | SELECT, DELETE (closed users) |
| auth_rate_limits, mail_outbox | SELECT, INSERT, UPDATE | None | SELECT, DELETE |
| security_events, audit_events | SELECT, INSERT (append-only) | None | None |
| agencies, client_workspaces, agency_memberships, agency_invitations, service_credentials | SELECT, INSERT, UPDATE | None | None |
| client_grants | SELECT, INSERT, UPDATE, DELETE | None | None |
| invitation_client_grants, service_client_grants | SELECT, INSERT | None | None |
| alembic_version | SELECT | None | None |

**Recommendation: L1, a dedicated `tracking_lifecycle` login role.** It has no inheritance, no schema privileges, and only the grants above. It is used only by the lifecycle runner with its own password in ignored `.env` and `.env.docker`. `tracking_app` keeps its append-only audit and security permissions and gains no `DELETE`. Cost: role creation in `infra/postgres/local-roles.sql` and `init-roles.sh`, one new private setting, and an owner step to create the role on native `tracking_sys` before that rollout. Tests assert the role cannot touch audit, security, tenancy, or users rows.

Alternatives:
- **L2: give `tracking_app` the `DELETE` grants.** No new role or password. A compromised or faulty API process could delete sessions, tokens, or identities, but still not audit or security rows.
- **L3: `SECURITY DEFINER` functions owned by the migrator.** Fixed deletion predicates, with `EXECUTE` granted to the runtime. This gives the narrowest deletion capability, but the policy moves into migration SQL, needs `search_path` hardening, and is harder to test and change.
- **Run as `tracking_migrator`.** No grant change. Not recommended: a recurring job would hold a DDL-capable role.

## Decision 5: mail cleanup and retry
Already implemented under D-019/D-022 (verified in code):
- The payload is cleared after confirmed delivery.
- Verification messages carry `expires_at` equal to the code's expiry and are cleared unsent after it (`expired_before_delivery`).
- Failures retry with exponential backoff capped at one hour.
- Gmail mode refreshes per batch.

Not yet covered:
- Reset and invitation messages have no `expires_at`. A failing one keeps its encrypted live link and retries indefinitely.
- Local `.eml` files are never deleted and contain plaintext codes and links.
- In Gmail mode, the sender mailbox's Sent folder keeps a copy of every message, which is Gmail behavior outside application control and not verified here. Reset links stay live there for up to 30 minutes and invitation links for up to 7 days.

**Recommendations:**
- **5a.** Set `expires_at` on reset and invitation messages to their token expiry. This needs no schema change; the existing worker clears them unsent.
- **5c.** The A3 runner deletes `.eml` files older than the longest link lifetime (7 days), in development local mode only.
- **5d.** Treat the sender mailbox as holding live links: restrict access, keep 2-step verification on, and do not request the broader `gmail.modify` scope to delete Sent copies.

Alternatives:
- **5b: a 10-attempt retry cap** from the old design. With 5a, every message already has an expiry that bounds its retries, so a cap is not recommended now.
- **Stop retrying on permanent Gmail rejections** (`gmail_rejected_message`). This can be added later from observed failures.
- **Leave `.eml` cleanup manual.**

## How to respond
For example: "Approve recommendations 1-5", or per item such as "1 approved, 2 approved except sessions 7 days, 3 alternative emailed code, 4 L1, 5 approved". Only the owner's actual answer will be recorded in the decision register.
