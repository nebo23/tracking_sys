# Conditional implementation handoff: 006 and 007-B/C

Status: prepared 2026-11-23 under D-074; execution authorized by D-075, which approves J1-J12 as recommended.

## Read first

Read `AGENTS.md`, `README.md`, `docs/planning/decisions.md`, `docs/planning/review-next.md`, and:

- [Joint entry review and J1-J12](joint-entry-review.md).
- [Joint design addendum](joint-design.md) and [verification matrix](joint-verification.md).
- [Original 006 design](design.md), [decision packet](decision-packet.md), [review register](preparation-review.md) and [original verification matrix](verification-matrix.md).
- [007 spec](../007-revenue-ledger/spec.md), [plan](../007-revenue-ledger/plan.md), [entry review](../007-revenue-ledger/entry-review.md), [evidence](../007-revenue-ledger/evidence.md) and [review corrections](../007-revenue-ledger/review-corrections-prompt.md).
- The 003 consent/deletion contracts; current 004/005 collection and tracker code; 008-A engine; 014 delivery; 015 revenue/integrations; 016 reporting and their tests.

Work on `codex/spec-006-007-identity-ledger`, based on merged `main` `81977a3`, in its own worktree. Preserve other checkouts and owner files. Do not resume the historical 006/007 branches or apply the obsolete proposed migration 0009.

## Authority

Before application or migration changes, locate an explicit owner decision approving J1-J12, including any amendments. D-074 approves joint preparation, not these policy/schema choices. If they remain undecided, finish useful preparation and present the concrete packet. Explain that the decision gate is from `AGENTS.md` (product/schema decisions and review before implementation); do not ask for approvals already given in the current conversation.

After approval, record its exact scope in the decision register and working agreement, then implement phases P0-P5 in order. The latest owner instructions take precedence over this handoff. Publish verified commits under D-051 and the applicable owner decision; open a PR or merge only when authorized for this combined workstream. The earlier 016 merge authorization does not authorize this branch's merge.

## Required result

Implement the approved 006 identity/journey behavior and 007-B financial persistence, then 007-C sale association and actual-input handoff tests. Use the existing receipt store and financial engine. Correct the six deferred 006 findings, each with its own evidence. Preserve original receipt history and currencies. A change of identity must never change monetary evidence; financial erasure detaches the approved identifying links without deleting amounts.

The scope is backend APIs plus the specified additions to the existing tracker package. It does not include customer-facing React work, provider onboarding/calls, native migrations, deployment, production FX, persisted 008 allocations or 016-B/C reports. Do not touch 012/013.

## Execution requirements

1. Verify current main/branch, clean owner state and the approved decisions. Inventory existing migrations, lock paths, permissions and affected consumers. Update the concrete contract/schema definitions if implementation reveals a routine detail; return only material new product/schema/dependency choices to the owner, with independent work continuing.
2. Implement identity schema/proof/consent and its read/correction/erasure/tracker behavior. Add the R006-23 to R006-28 regressions before marking the findings resolved. A held or retained anonymous event remains excluded after trust upgrades and hold cleanup.
3. Implement durable financial receipts, movements, current projections and reconciliation review over `revenue_evidence`. Keep stable raw receipt positions for held evidence. Use the approved compensating release policy, atomic commits, resumable backfill and explicit readiness/generation checks. Never copy the latest held filter across all historical prefixes.
4. Implement the approved sale-association trust protocol, double permission boundary, current consent checks and complete F1 unlinking. Test pending associations, shared devices, conflicting owners, source-account ambiguity, erasure of historical binding revisions and replay. A bare browser purchase reference cannot establish ownership.
5. Integrate the existing 008-A calculation in tests using persisted synthetic source data. Preserve immutable conversion identity by rebuilding affected derived state after ownership changes. Exercise gap-safe feeds, both compare-and-swap fields and the erasure release barrier. State that production attribution persistence remains open.
6. Re-run the complete relevant verification from the matrix and existing suites. Review 014/015/016 behavior after the changes, including effective-date revenue reports and scoped final authorization. Measure financial writes/backfills as well as reads; do not mark A3 fixed merely because reads use a table.
7. Produce per-phase evidence, a developer usage guide, current OpenAPI and an accurate scope/remaining-work statement. Commit each verified slice and publish as authorized. Leave PR/merge at the applicable owner gate; do not end with local-only changes when D-051 applies.

## Final report

Report in Arabic: the implemented user-visible behavior, exact commits, tests actually executed, deferred findings closed one by one, unresolved limitations and the next dependency. Keep all repository contributions in formal English. Do not claim all of 006/007/008/016 or production readiness merely because the combined branch passed its local checks.
