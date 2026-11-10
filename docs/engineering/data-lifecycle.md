# Data lifecycle runner
Specification 003-A3/003-A4/003-A5 under D-024. Status: implemented and tested on the disposable database. Native tracking_sys rollout needs its own owner approval; it had not been performed when native status was last verified (2026-11-04, revision `0004_identity`).

## What is deleted, and when
`python -m app.lifecycle` runs one bounded pass and prints counts only. Each period counts from the row's end, never from creation alone, and is compared strictly with one cutoff sampled from the database clock.

| Data | Deleted after |
|---|---|
| Browser sessions | 30 days after revocation, absolute expiry, or idle expiry |
| Reset and legacy verification tokens | 7 days after consumption or expiry |
| Numeric verification challenges | 7 days after consumption, invalidation, or expiry |
| Google OAuth transactions | 1 day after consumption or expiry |
| Rate-limit buckets | At window expiry (an expired bucket restarts anyway) |
| Outbox rows | 30 days after delivery or expiry |
| Password credential, Google identity, sessions, tokens, challenges, and OAuth transactions of a closed account | On the next run after closure, without a period |
| Development `.eml` and `.pending` files in the mail directory | 7 days after they were written; only in development local mode, non-recursive, never symbolic links |

Security events, audit events, invitations, service credentials, and unverified registrations are not deleted; their rules remain pending (Q-012). A closed user's row stays pseudonymized for audit references ([account closure](authentication.md#account-closure)). The approved periods are also the settings' upper bounds: `TRACKING_SESSION_RETENTION_DAYS` and similar variables may shorten a period but cannot extend it. Every new verification, reset, and invitation message carries the expiry of its code or link, and the mail worker clears an undelivered message at that time instead of retrying it. Messages queued without an expiry are outside this cleanup; see [legacy queued mail](#legacy-queued-mail-proposal-awaiting-owner-approval).

## Safety properties
- A dedicated `tracking_lifecycle` role can select and delete rows only in the six credential-state tables, plus password credentials and external identities. The grants cannot restrict rows; the runner's predicates delete those two only for closed accounts, which it finds by reading users. It cannot update or insert anything, cannot change users, tenancy, audit, or security rows, and has no schema privileges.
- One run at a time: a second runner finds the advisory lock held and exits with `skipped_concurrent_run`.
- Batches commit separately. A batch waits at most 100 ms for a row lock held by an API request, then rolls back only its own batch; that table is reported as incomplete and finished by the next run. Because every run re-evaluates the predicates, an interrupted or bounded run never skips an eligible row permanently.

## Running it
Docker (disposable or local stack): `.env.docker` holds `TRACKING_LIFECYCLE_PASSWORD`; a fresh database volume creates the role during initialization. Run `docker compose --env-file .env.docker -f infra/docker/compose.yaml --profile lifecycle run --rm lifecycle`. An existing volume created before D-024 has no lifecycle role, so its migration to 0005 stops with a message before granting anything. Recreating the volume is not required: add the role in place as the container's PostgreSQL administrator, with the attributes, password variable, and schema usage that `infra/docker/postgres/init-roles.sh` gives it, then rerun the reviewed migrations. This preserves the volume and its data.

Native tracking_sys (owner-approved rollout step; not performed as of the last verified native status on 2026-11-04):
1. In pgAdmin, run [infra/postgres/lifecycle-role.sql](../../infra/postgres/lifecycle-role.sql) on tracking_sys, then set the role's password.
2. Add `TRACKING_LIFECYCLE_PASSWORD` to the ignored `.env`.
3. Apply the reviewed migrations with the migrator role, check readiness, and only then run `python -m app.lifecycle` from `backend`.

No scheduler is installed. Run the command manually or from an operating-system scheduler; durable scheduling waits for Q-009.

## Legacy queued mail (proposal awaiting owner approval)
Messages queued before expiries existed have `expires_at` NULL: reset and invitation messages queued before D-024, and verification-link messages queued before D-022. While such a message is undelivered, `delivered_at` is also NULL, so it matches neither the worker's expiry check nor the runner's outbox rule (delivery or expiry more than 30 days ago). Time-based cleanup never reaches it. The worker keeps retrying it, because D-024 sets no retry cap, and a message that never succeeds keeps its encrypted payload, with its recipient and link, indefinitely. A delivered legacy message is unaffected: delivery clears its payload, and the row ages out normally. This limitation is not fixed. The number of such rows in native tracking_sys is unknown, because it has not been inspected.

Proposed transition, as one reviewed, owner-run step after the native rollout. It adds no schema, migration, backfill, or retention period, and nothing has been run:
1. Count the candidates read-only, by purpose and creation month: `delivered_at IS NULL AND expires_at IS NULL AND encrypted_payload IS NOT NULL`.
2. Option T1, derive the expiry from a reliably linked token. A one-time reviewed job decrypts each candidate with the mail key, reads the token from its link, and looks up the token's SHA-256 digest in `auth_tokens.token_digest` (reset and legacy verification) or `agency_invitations.token_digest`. Only on an exact match does it set the message's `expires_at` to that row's `expires_at`. The worker then clears an expired payload unsent, and the runner deletes the row 30 days later under D-024. No expiry is inferred for a message without a match.
3. Option T2, retire explicitly. Clear the payload unsent, record a fixed failure code such as `retired_without_expiry`, and set `expires_at` to the retirement time, so the existing 30-day outbox rule removes the row. A link works only while its token row exists and is open, so retiring a message whose token is gone loses nothing; a recipient whose token is still open requests a new link or invitation.

Recommendation: T1 for messages with an exact token match, T2 for the rest. The policy, the job, and their rollout await an owner decision. Until then, legacy rows keep the behavior described above.
