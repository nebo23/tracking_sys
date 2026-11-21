# Spec 014 review corrections: R014-01 and R014-02 (PR 12)

Work in the owner's local repository on `codex/spec-014-ad-spend-capi`, for example in the worktree `C:\Code\Tracking-system\.worktrees\spec-014-ad-spend-capi`. The reviewed head is `f00d997` ("Spec 014: Record the final verification and update the status records"), the head of PR 12 (https://github.com/nebo23/tracking_sys/pull/12).

Before editing:
- Fetch the branch.
- Verify that `f00d997` is still its head and that the working tree is clean.
- Preserve any later owner change.

Read:
- `AGENTS.md` and `README.md`;
- D-063 and D-064 in `docs/planning/decisions.md`;
- in `specs/014-ad-spend-capi/`: the entry review (D9, D10 and section 9), `design-014.md` sections 5.2 and 5.3, and `evidence.md`;
- `docs/engineering/advertising.md` and `docs/engineering/connectors.md`.

Communicate with the owner in Arabic, and write project files, comments and commit messages in formal English. Save this handoff as `specs/014-ad-spend-capi/review-corrections-prompt.md`.

## Authority

Record the owner's decision of 2026-11-21 as D-065: one row after D-064 in the decision register, and one line in `AGENTS.md`.

> D-065: Correct findings R014-01 and R014-02 of Claude's review of PR 12 (reviewed head `f00d997`, 2026-11-21) on `codex/spec-014-ad-spend-capi`, each with a regression that fails at `f00d997`, and amend the D9 delivery key: a sale reaches a dataset at most once. Its event ID is derived only from the client, the dataset and the sale, with no destination and no rotatable secret. At most one delivery per client and event ID may exist. The one exception is a delivery cancelled before any attempt because its destination was disabled or its connection ended, which never reached Meta. The unmerged migration `0018` is amended in place, on disposable databases only. The worker's delivery step reports `not_configured` instead of failing when a keyring it needs is missing. Commit, push and update PR 12 without a further upload request; open no second pull request. The merge waits for Claude's review of the corrections and the owner's decision. The review notes N1 to N3 stay follow-ups. Live Meta calls, native migration and deployment remain separate decisions.

The evidence column: "Owner instruction on 2026-11-21 to prepare the prompt that fixes the two problems of Claude's review of PR 12 and to update the pull request for Claude's review."

In the entry review, mark the D9 row "Amended by D-065 (delivery key)" and add a line to section 9.

## Findings

### R014-01: one sale can be counted twice in one dataset

**Location at `f00d997`:**
- `backend/app/services/delivery.py:310-314` (`event_id_of`) and `:405-415` (the lookup of an existing delivery);
- `backend/app/models/delivery.py:173` and migration `0018` (`uq_conversion_deliveries_event`).

**Finding.** The event ID is an HMAC under `TRACKING_AUTH_SECRET` of the client, the **destination** and the sale. The only uniqueness is (`destination_id`, `event_id`), and the row stores no sale reference. Two cases create a second delivery for the same sale:
- **(a) Reconnection.** The delivery connection is disconnected and the same dataset is connected again, which makes a new connection and a new destination. A repeated enqueue of a sale that was already delivered then inserts a second delivery with a new event ID. A later partial refund within the 7 days is one such enqueue.
- **(b) Secret rotation.** After a rotation of `TRACKING_AUTH_SECRET`, the same sale enqueued for the same destination gets a new event ID and a second row.

**Observed.** Claude reproduced both cases on the disposable service. The second enqueue answered `{"queued": 1}`, the delivery step answered `{"delivered": 1}`, and the synthetic receiver counted the sale **twice** in dataset 880001. Meta deduplicates only identical event IDs, so a live dataset would count the purchase twice, against AC3. The limitation in `evidence.md` ("within 48 hours", "deliveries not yet enqueued") understates this.

**Required correction (D-065):**
- **Event ID.** The SHA-256 hex digest of a length-prefixed encoding of the domain `conversion-event:v2`, the client ID, the dataset ID (the delivery connection's account at enqueue), the source account and the sale operation. It uses no destination and no keyed secret. It is never returned by a route or logged.
- **Uniqueness.** Replace `uq_conversion_deliveries_event` with a partial unique index on (`client_id`, `event_id`). The index excludes only rows with `status = 'cancelled' AND attempts = 0 AND reason IN ('destination_disabled', 'connection_ended')`. Change it in the model and in `0018`. Amend `0018` in place: it exists only on this unmerged branch and on disposable databases.
- **Lookup.** Look up an existing delivery by client and event ID. Follow it (`_follow`) only when it belongs to the current destination and is still waiting; otherwise the outcome is `unchanged`.
- **Cancelled before any attempt.** Such a sale may be enqueued again through a re-enabled or new destination of the same dataset, with the same event ID.
- **Records.** Correct the limitation text in `evidence.md`, the design note (5.2, 5.3) and `docs/engineering/advertising.md`.

### R014-02: the connector worker command fails without the tombstone keyring

**Location at `f00d997`:**
- `backend/app/connector_worker.py:28`;
- `backend/app/services/delivery.py:786` (`run_deliveries`);
- `backend/tests/integration/test_connectors.py:258-283`.

**Finding.** The worker command now always runs the delivery step. That step requires the tombstone keyring whenever a delivery provider is registered, which is always the case with the synthetic state. The documented connector configuration needs the token keyring only (`docs/engineering/connectors.md`, "Configuration"). With that configuration, `python -m app.connector_worker` exits 1 with `CollectionError: collection_not_configured`. This happens after the teardown, scheduling and sync work have committed, and the command prints no counts.

**Observed.** `test_disconnect_through_worker_command_isolates_other_clients` failed this way in Claude's clean environment and passed at `main` (`6283935`) in the same environment. It passes only where the developer's environment or `.env` supplies `TRACKING_TOMBSTONE_KEYRING`.

**Required correction:**
- **Step behavior.** When a delivery provider is registered but the token or tombstone keyring is not configured, `run_deliveries` still expires overdue deliveries, which needs no key and destroys their payloads. It claims nothing and returns the expired count with `"not_configured": 1`. The command exits 0 with every step's counts.
- **Documentation.** State in `docs/engineering/connectors.md` (Configuration) and `docs/engineering/advertising.md` that the delivery step needs both keyrings.
- **Test isolation.** Make the worker-command test independent of the developer's `.env` by setting both tombstone keyring variables explicitly in the subprocess environment.

## Regressions

Each regression fails at `f00d997` and passes after the correction. Add them to the existing test modules.

1. **R014-01 (a), reconnection** (`tests/integration/test_conversion_delivery.py`).
   - Steps: deliver a sale; disconnect the delivery connection and run the worker teardown; connect the same dataset again and enable a new destination; enqueue the same candidates again.
   - Expected: `{"unchanged": 1}`, the delivery step sends nothing, and the receiver counts the sale once.
   - At `f00d997`: `{"queued": 1}`, `{"delivered": 1}` and two counted events.
2. **R014-01 (b), rotation.**
   - Steps: deliver a sale; enqueue the same candidates with a settings copy whose `auth_secret` differs.
   - Expected: `{"unchanged": 1}`, one delivery row and one counted event.
   - At `f00d997`: a second row and two counted events.
3. **R014-01 (c), cancelled before any attempt.**
   - Steps: enqueue a sale; disconnect before any attempt, which cancels the delivery with `connection_ended`; connect the same dataset again with a new destination; enqueue again.
   - Expected: `{"queued": 1}` with the **same** event ID as the cancelled row, then one delivered and one counted event.
   - At `f00d997`: the event IDs differ.
4. **R014-01 (d), database constraint** (`tests/integration/test_ad_migrations.py`).
   - Expected: the database refuses a second delivery with the same client and event ID. The exception is a first delivery cancelled before any attempt with one of the two reasons, which does not block.
   - At `f00d997`: a second row under another destination is accepted.
5. **R014-02, worker command** (`tests/integration/test_connectors.py`).
   - Expected with the synthetic state, the token keyring and an explicitly blank `TRACKING_TOMBSTONE_KEYRING`: the command exits 0 and prints `"delivery": {"not_configured": 1}` next to the other steps.
   - Expected with both keyrings set explicitly: `"delivery": {}`.
   - At `f00d997`: the first case exits 1.
   - Also add a unit case: `run_deliveries` returns `{"not_configured": 1}`.

Keep every existing case passing. Update an expectation only where D-065 changes it, for example the `event_id_of` signature, and list each such change in the evidence.

## Verification

1. **Regressions at `f00d997`.** Run the new regressions against a temporary checkout of `f00d997` made with `git archive` outside the repository. Copy the new test code in, and remove it afterwards. Record that each fails with the reason above, then run them again at the corrected head.
2. **Mutation checks.** Restore each source byte for byte afterwards.
   - The old per-destination unique key: regressions 1 and 4 fail.
   - The auth secret in the event ID: regression 2 fails.
   - The `not_configured` guard removed: regression 5 fails.
3. **Suites.**
   - `python -m ruff check .` and `python -m ruff format --check .`;
   - the full unit suite;
   - the full integration suite on the disposable PostgreSQL 18 service of `backend/tests/README.md`;
   - the OpenAPI snapshot; no route change is expected.

   Report skipped tests as skipped.
4. **Environment notes.** Claude's review environment (Python 3.13, PostgreSQL 16.15) showed two environment-only failures. Both also fail at `main` in that environment. Record them as environment notes and do not change them.
   - The OpenAPI snapshot, because Python 3.13 renames the 413 and 422 phrases.
   - The PostgreSQL 18 version assertion of `test_postgres.py`.

## Records

- **`evidence.md`.** A section "Claude's review of PR 12 and the corrections (D-065)", with:
  - Claude's independent results at `f00d997`: ruff clean; unit 700 passed plus the snapshot failure above; integration 381 passed, 3 skipped and the two failures above;
  - the two findings, the regressions table (the result at `f00d997` and the corrected result), the commands and counts, and the mutation results;
  - the corrected limitation text;
  - the review notes as follow-ups, unchanged.
- **Documents.** The design note (5.2, 5.3), `docs/engineering/advertising.md` and `docs/engineering/connectors.md`.
- **Status lines.** `spec.md`, `specs/README.md` and `docs/planning/review-next.md`.

## Publication

1. Commit the corrections, for example "Spec 014: Correct review findings R014-01 and R014-02 (D-065)", and push `codex/spec-014-ad-spend-capi`.
2. Update the description of PR 12 with a "Review corrections (D-065)" section. Open no second pull request and do not merge.
3. Tell the owner in Arabic that the corrections are ready for Claude's review, with the new head commit, the PR link and the counts.

## Limits

The hard limits of `specs/014-ad-spend-capi/implementation-prompt.md` still apply:
- no live Meta call, nothing sent to Meta, and no Meta app or account change;
- migrations on the disposable service only, never on native `tracking_sys`;
- no new dependency and no frontend change;
- Specs 012 and 013 and the YouTube test account untouched.

Change nothing beyond R014-01 and R014-02, their regressions and their records. These review notes stay follow-ups:
- **N1:** the `system_generated` default of `SyntheticJourney.action_source`;
- **N2:** absent `impressions` and `clicks` stored as 0;
- **N3:** the fixed limit of 10 deliveries per worker pass.

A provider fact or test result that would change another decision goes to the owner first.
