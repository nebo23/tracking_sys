# Data lifecycle runner
Specification 003-A3/003-A4 under D-024. Status: implemented and tested on the disposable database; native tracking_sys rollout has not been performed and needs its own owner approval.

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
| Development `.eml` and `.pending` files in the mail directory | 7 days after they were written; only in development local mode, non-recursive, never symbolic links |

Security events, audit events, invitations, service credentials, users, and unverified registrations are not deleted; their rules remain pending (Q-012) or belong to account closure (003-A5). The approved periods are also the settings' upper bounds: `TRACKING_SESSION_RETENTION_DAYS` and similar variables may shorten a period but cannot extend it. Every new verification, reset, and invitation message carries the expiry of its code or link, and the mail worker clears an undelivered message at that time instead of retrying it. Messages queued without an expiry before D-024 keep the earlier behavior until delivered.

## Safety properties
- A dedicated `tracking_lifecycle` role can only select and delete rows in the six governed tables. It cannot update or insert anything, cannot touch users, tenancy, audit, or security rows, and has no schema privileges.
- One run at a time: a second runner finds the advisory lock held and exits with `skipped_concurrent_run`.
- Batches commit separately. A batch waits at most 100 ms for a row lock held by an API request, then rolls back only its own batch; that table is reported as incomplete and finished by the next run. Because every run re-evaluates the predicates, an interrupted or bounded run never skips an eligible row permanently.

## Running it
Docker (disposable or local stack): `.env.docker` holds `TRACKING_LIFECYCLE_PASSWORD`; a fresh database volume creates the role during initialization. Run `docker compose --env-file .env.docker -f infra/docker/compose.yaml --profile lifecycle run --rm lifecycle`. An existing volume created before D-024 has no lifecycle role, so its migration to 0005 stops with a message; create the role there or recreate that local volume.

Native tracking_sys (owner-approved rollout step, not yet performed):
1. In pgAdmin, run [infra/postgres/lifecycle-role.sql](../../infra/postgres/lifecycle-role.sql) on tracking_sys, then set the role's password.
2. Add `TRACKING_LIFECYCLE_PASSWORD` to the ignored `.env`.
3. Apply the reviewed migrations with the migrator role, check readiness, and only then run `python -m app.lifecycle` from `backend`.

No scheduler is installed. Run the command manually or from an operating-system scheduler; durable scheduling waits for Q-009.
