# Conditional implementation handoff: Spec 016-A

Prepared: 2026-11-22. **Executed under D-072** (2026-11-22, D1-D12 approved as recommended, no pull request authorization); see the [evidence](evidence.md). The text below is kept as the handoff that was followed. D-071 approved preparation only. First obtain the owner's recorded decision on D1-D12 of [entry-review.md](entry-review.md), with any amendments. Do not treat this file, the branch, or the instruction to start Spec 016 as approval of its proposed business behavior.

## Context to read

Read `AGENTS.md`, `README.md`, `docs/planning/decisions.md`, this specification's `spec.md`, `entry-review.md`, `design.md`, `verification-matrix.md`, `plan.md` and `tasks.md`. Read the 015 correction tracker, current ledger/revenue services, connector coverage and advertising reads before implementation. The preparation base is merged `main` at `2a0c8e512e9ae29aecea7728f57ecd366807f178`.

Use `codex/spec-016-analytics-reporting`. Inspect current changes and upstream main before editing; preserve other sessions and owner files. If later merges change relevant contracts, reconcile the design and disclose material changes before relying on the old review. Do not reset or clean other worktrees.

## Work after the decision is recorded

1. Record the actual approval and amendments in the decision register/AGENTS; do not invent approval text or a new decision in advance. Reconcile the design and verification matrix to that decision. Inventory every supported reporting metric explicitly; unfamiliar aggregation semantics stay unsupported.
2. Implement shared typed report contracts, native calendar periods, source statuses, deterministic revisions and bounded result/pagination behavior. Reuse current authentication and permission evaluation. No new dependency or migration is approved by the proposed packet.
3. Implement social and spend reads over the complete bounded input sets, with catalog-controlled aggregation, source freshness/coverage and valid previous-period comparison. Never call a provider or trigger synchronization while reading a report.
4. Implement the bounded recorded-revenue activity view through the existing ledger calculation and held-refund policy. Count whole-client evidence before calculating; preserve verified/declared/unresolved distinctions and original currencies. Avoid the prefix journal and raw-evidence sums.
5. Implement typed CSV through the same report result, with bounded buffering and a fresh authorization/source check before release. No artifact storage, public link, download token, cache or scheduled mail.
6. Exercise V01-V19 using synthetic fixtures and disposable PostgreSQL. Add focused regression cases for discovered defects; do not modify predecessor semantics without evidence. Preserve native `tracking_sys` and owner credentials. No live provider calls, account changes, frontend work or deployment.
7. Update the generated OpenAPI snapshot, a reusable engineering guide, task status and implementation evidence. Describe limits precisely. Mark only 016-A complete after its actual evidence; 016-B/C, 006/007/008 follow-ups, 012/013 and the production gates remain open.
8. Commit independently reviewable verified slices and push this branch under D-051. Present the completed result and evidence. Open a PR only if the owner has explicitly authorized it; never infer merge approval from implementation approval.

## Required final report

State what was implemented, the exact commit and branch, tests actually run and their results, all remaining limits/dependencies, and whether publication/PR/merge occurred. Report performance measurements as observations, not production promises. If a decision remains open, finish independent approved work and present the concrete smallest question with its source; do not claim completion or silently broaden the design.
