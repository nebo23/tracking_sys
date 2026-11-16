# Complete Spec 009 and assess readiness for Spec 010

Work in `C:\Code\Tracking-system\.worktrees\spec-009-connector-runtime` on `codex/spec-009-connector-runtime`. Communicate with the owner in Arabic and write project files in English. Read `AGENTS.md`, `README.md`, `docs/planning/decisions.md`, the [specification](spec.md), [plan](plan.md) and [tasks](tasks.md). Confirm the branch, HEAD and working tree before editing. The correction review was recorded at `817a582` against application code at `2d0ac21`. Preserve later work and verify any fixes already present.

## 1. Correct the three open findings in 009-A

Read the [correction review](corrections-review-2026-11-15.md) and [earlier regression evidence](evidence.md). Start in `backend/app/services/connectors.py` and the existing connector tests. Work within the approved D-048 synthetic lifecycle and its existing schema. Preserve the guarantees established by R009-01 through R009-07.

| Finding | Required behavior and regression evidence |
| --- | --- |
| R009-08 · Concurrent reconnects | Bind the connection generation and the eligible old secret-version IDs to one consistent view. A superseded callback may dispose of its own grant. The winning grant must remain usable. Use independent database sessions and deterministic synchronization. Assert both public `active` status and a successful fresh read at the synthetic provider with the installed grant. |
| R009-09 · Rejected reconnect | Check the selected external account, agency, client eligibility, current session, manager authority and expected generation before touching a retained grant. Recheck authority and generation at installation. Cover account mismatch, loss of authority and an ineligible client. Assert that the original grant still works at the synthetic provider, its recorded revocation outcome is unchanged, and the newly rejected grant receives the appropriate disposal outcome. |
| R009-10 · Purge deadline | Record completion time after the scoped database purge succeeds, in the transaction that records its outcome. Preserve the original `purge_due_at`. Use a controlled clock to cover on-time completion, late provider revocation and late database cleanup. Check the deletion, stored completion time and public `deadline_met` value. |

Add maintained regression tests for each finding. Keep them independent of wall-clock sleeps and exercise the normal API or worker entry point. Verify continued isolation for two clients sharing an external account and for a client in another agency. Commit the verified correction locally as a reviewable change.

## 2. Complete the remaining runtime slices under their recorded decisions

D-048 covers 009-A. Check for later owner decisions before planning the next slice. For unapproved work, prepare a compact decision packet on this branch. Give a recommended option, the main alternative, the schema and privilege impact, dependency or cost implications, and the acceptance tests enabled. Present the decisions needed for the next slice together. Continue independent preparation while awaiting them. Once the owner records approval, implement and verify that slice and continue through the remaining scope.

| Slice | Observable completion criteria |
| --- | --- |
| 009-B · Synchronization | Cover pagination, checkpoints, backfill, overlapping runs, `401`, `403`, `429` with `Retry-After`, retryable `5xx`, usage accounting and synthetic budget stops. Prove that a restart at the page-write/checkpoint boundary skips no page and creates no duplicate record. Bring worker and scheduling choices under Q-009 and the relevant budget assumptions under Q-004 to the owner. |
| 009-C · Coverage and provenance | Expose source, version, last successful sync, complete-through time, historical coverage and cost or quota state per authorized connection. Test observed zero, missing, unsupported and stale metrics, including the outcome after a delayed page or budget stop. |
| 009-D · Provider webhooks | Reuse the applicable Spec 004 contracts and test a synthetic adapter through ingestion. A valid delivery has one scoped effect, a repeated delivery has no additional effect, and an invalid signature causes no ingestion. Verify tenant isolation and behavior after disconnect. |

Map `Connection`, `SyncRun`, `Checkpoint`, `Capability`, `ProviderError` and `UsageRecord` to their owning slices. Keep provider-specific access and sourcing decisions under Q-001 and Q-010 with the first slice that needs them. Use synthetic fixtures throughout Spec 009. The 72-hour teardown target belongs to the synthetic lifecycle.

## 3. Verify and hand off

- Use the project `.venv`. From `backend/`, run the connector contract and integration tests, the backend unit and integration suites, `python -m ruff check .` and `python -m ruff format --check .`. Run `git diff --check` for the changes. Follow the [database test guide](../../backend/tests/README.md) and target only disposable `tracking_foundation_test` at `127.0.0.1:55433`. Verify the existing OpenAPI snapshot against the application and update it when an approved change affects the public contract.
- After each slice, update [evidence](evidence.md) and [tasks](tasks.md) with the tested commit, exact commands, pass/fail/skip counts, and remaining findings. Map AC1 through AC4 and Spec 003 deletion case D3 to named tests. Review the final committed tree against those criteria. Follow the owner's recorded publication and merge instructions for the exact scope reviewed.
- Return an Arabic handoff with the local commit SHAs, review and merge status, and an explicit readiness decision. For full closure, account for 009-A through 009-D. If a slice awaits a decision, name it and identify exactly which Instagram capability depends on it. For [Spec 010](../010-instagram/spec.md), identify the next owner decision on account types and metrics, the authorized test-account evidence needed for scopes, fields and history, and the Meta and Instagram policy rows requiring reverification. Live provider use, native rollout and deployment retain their separate owner decisions.
