# Spec 008 entry review

**Owner decision pending.** The proposed first slice calculates lead and revenue credit from synthetic touchpoints. The inputs to the examples below are available after [PR 6](https://github.com/nebo23/tracking_sys/pull/6) merged 007-A into `main` at `bc0ff40`. These are expected outcomes for review. Implementation and test execution follow approval of the relevant Q-007 rules.

## Inputs and boundaries

- Scope each calculation to one agency, client, conversion and model version. An eligible touchpoint carries its source, occurrence instant, stable reference and permitted association. Production access to the journey depends on the [006 identity design](../006-identity-journey/design.md) and 007-C. Use synthetic associations while those consumers are pending.
- For a sale, use the verified net in original-currency minor units for that individual transaction. An aggregate client balance loses the distinction between buyers and journeys. Use distinct lead and money allocations. A purchase signal alone contributes zero verified revenue.
- The [007-A journal](../007-revenue-ledger/evidence.md#equal-receipt-instants-r007-02-follow-up) reports postings and releases. For an incremental consumer, apply each movement once and checkpoint only after its allocation is applied. Replay requires the original receipt order within equal instants. Durable positions, atomic writes and permissions belong to 007-B. For the proposed synthetic slice, compare each incremental result to a fresh calculation.

## Q-007 choices proposed for the first slice

| Choice | Recommendation for owner review | Example or alternative |
|---|---|---|
| Models and window | Exercise First Click, Last Click and Linear independently. For the synthetic baseline, use a configurable 30-day window ending at the conversion's effective instant, inclusive at both boundaries. Compare absolute instants in UTC. | A touch exactly 30 days before the sale qualifies. One microsecond earlier falls outside. A 7-day window would omit older visits. The owner chooses the product default. |
| Direct, unknown and ties | Prefer eligible campaign touches. When none exist, assign to an evidenced direct visit if present, otherwise to unknown. For equal occurrence instants, use a stable touchpoint ID as the proposed tie-break. | With campaign A followed by a direct visit, Last Click credits A under this proposal. Counting direct alongside campaigns would credit direct. Missing consent or an ambiguous identity link cannot create an eligible campaign touch. |
| Rounding and later changes | Keep each currency separate. For Linear, split integer minor units by largest remainder using stable touch order for ties. Recalculate the approved model on the revised transaction net when a refund or release arrives. Preserve the prior version and report the signed difference. | A one-cent linear allocation across A and B gives the cent to A under the proposed tie rule. Decide whether later eligible touchpoint evidence creates a revised result or whether reports freeze after a chosen cutoff. |

## Acceptance examples for review

1. A and then B precede a verified sale of 100.00. Expected independently for each model: First Click gives A 100.00, Last Click gives B 100.00, and Linear gives each 50.00. With no eligible touch or direct evidence, unknown receives 100.00.
2. For the same touches, capture 1,000.00 and refund 200.00. Linear yields 400.00 per touch. If 007-A releases that refund and posts a competing 900.00 refund, the new total is 100.00. Applying the two new movements from the saved position must produce 50.00 per touch. Replay of the same receipt log must agree.
3. A matching identifier in another client supplies no touchpoints. Verify separately that consent withdrawal or a corrected ownership decision removes ineligible associations when constructing a revised result. Repeated calculation with the same inputs and model version reproduces the same allocations.

The next review decision is whether to implement this provider-independent calculation slice with these Q-007 choices. The [008-A implementation handoff](implementation-prompt.md) includes the proposed late-evidence revision rule and the expected outputs for review. Live attribution still requires persisted financial evidence and an implemented journey association.
