# Spec 008-A · Lead and revenue attribution

Work on the existing `codex/spec-008-attribution-engine` branch in `C:\Code\Tracking-system\.worktrees\spec-008-attribution-engine`. Read `AGENTS.md`, `README.md`, `docs/planning/decisions.md`, the [specification](spec.md), [entry review](entry-review.md), [plan](plan.md), [tasks](tasks.md) and the [007-A receipt replay contract](../007-revenue-ledger/evidence.md#equal-receipt-instants-r007-02-follow-up).

**Owner decision.** D-044 opened design review. The rules below are recommended for a local synthetic slice. Record the scope, date and actual choices in the decision register when the owner explicitly authorizes execution with those choices. If choices are still pending, prepare the contract and expected examples for review and identify the open choice before coding its behavior. Production defaults remain a later decision.

## Deliverable

Implement a provider-independent, in-memory backend calculation using existing project dependencies. One run answers how much credit each eligible content interaction receives for one conversion, under one version of one model. Return the source and content or campaign references available from each eligible touch, its evidence, credited amount or lead share, and the rule that assigned it. Preserve explicit direct and unknown outcomes. This slice consumes synthetic, authorized journey associations and the real 007-A financial contract. Durable storage, HTTP routes, identity matching, live providers, social metric collection and dashboards belong to their respective specifications.

## Recommended Q-007 rules for owner selection

1. Calculate First Click, Last Click and Linear independently. A lead has one unit of lead credit distributed as exact shares. A verified sale uses the net for the specific scoped transaction in its original currency and integer minor units. Never sum across model results or treat a purchase signal as money.
2. Use a configurable window, initially 30 days for synthetic examples, inclusive from the start through the conversion's effective instant. Compare UTC instants. Order eligible touches by effective instant and then stable touchpoint ID. Retrying the same scoped touch contributes once. Preserve distinct eligible interactions with the same content.
3. Prefer eligible campaign touches. If there are none, assign to an evidenced eligible direct visit or, failing that, to unknown. Aggregate platform views, ambiguous ownership, missing consent and another client's touch cannot identify a buyer. Keep runs scoped by agency, client, conversion and model version. Preserve the ledger's source-account scope where business references may repeat.
4. Split Linear revenue by largest remainder with stable touch order for ties. For a refund or a released posting, recompute from the revised transaction net anchored to the original sale time and record the signed allocation differences. For this synthetic slice, a newly received eligible touch with an in-window occurrence time produces a revised run. Keep prior revisions traceable under their original model version. Apply the current consent and ownership decision when constructing a revision.

## Acceptance tests

| Case | Expected result |
|---|---|
| Lead versus sale | A then B precede a lead. First credits A with one lead, Last credits B with one, and Linear credits each with half. For a verified sale of 100.00, the three independent results are A 100.00, B 100.00, and 50.00 each. An unverified purchase signal supplies zero verified revenue. |
| Direct, unknown and scope | A campaign touch followed by direct still credits the campaign. A direct-only eligible journey credits direct. With no eligible evidence, unknown receives all eligible credit. Exercise repeated identifiers across agencies, clients and ledger source accounts, denied consent, and corrected ownership. |
| Time and precision | Include a touch exactly 30 days before the conversion. Exclude one a microsecond earlier and one after conversion. Exercise equal instants and equivalent timestamps with different offsets. Splitting one minor unit across two equally weighted touches allocates it once, to the first touch in the stable order. |
| Real ledger replay | Build the sale and refunds through `app.ledger.calculate()`. A 1,000.00 sale followed by a 200.00 refund gives 400.00 per touch under Linear. A release of that refund followed by a 900.00 refund leaves 50.00 each. Drive the equal-receipt-time case from 007-A: resume from movement 2, apply the suffix, and compare with full replay. Retrying the same movements leaves allocations unchanged. |
| Revisions and evidence | Start with A as the only known touch, then supply a later-received eligible B that occurred between A and the sale. Under Last Click, the new revision moves credit to B and explains the difference. Repeating identical inputs and version reproduces the result. Test a changed model version, a full refund to zero, and a withdrawal that makes a previously matched touch ineligible. |

Use the specification contracts `AttributionRun`, `ModelVersion`, `CreditAllocation` and `EvidenceClass`. Reuse ledger amounts, transaction scope and movements. Compare allocations per conversion, currency and model, including unknown. Advance a receipt checkpoint only after the corresponding allocation update succeeds in the in-memory scenario. Record the remaining 006, 007-B and 007-C dependencies for live use.

Run the focused attribution and ledger tests, the existing backend non-integration suite, Ruff lint and format checks on changed Python files, and `git diff --check`. Use the project virtual environment. Update the specification tasks and evidence with the actual commands, outcomes, exclusions and a worked example. Commit the verified slice locally and return the SHA, results and remaining decisions to the owner in Arabic for review before publication.
