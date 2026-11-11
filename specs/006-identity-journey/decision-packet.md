# Specification 006 decision packet

Prepared: 2026-11-11 under D-039 (preparation only). **No item is decided.** Read the [design](design.md) first; the values it states are part of each recommendation. The [verification matrix](verification-matrix.md) names the tests each decision controls.

Approving a recommendation approves local implementation with synthetic data and disposable databases only. Push, pull request, merge, native `tracking_sys` migration, real customer intake and deployment remain separately gated.

## Group A: scope, schema and retention

| ID | Recommended option | Practical alternative | Consequence of each |
|---|---|---|---|
| D1 Scope and slices | Implement 006-A to 006-E (design section 14) in order, each committed locally and reviewed: schema and keys; assertions, linking and consent; read models; merge, unmerge and erasure; tracker handoff and end-to-end journey. | Implement 006-A to 006-C first and decide merge/erasure later. | Recommended: all four acceptance criteria can be closed. Alternative: earlier review of linking, but criterion 4 and person erasure stay open, so 006 cannot close and real data must wait. |
| D11 Schema | Migration `0009_identity_journey` with the eight tables of design section 12.1. Also extend tombstone match types, diagnostic channel, audit actions and the `can_view_identities` grant flag. Per-client HMAC key sealed under the D-025 local development keyring. Guarded downgrade. No native rollout. | Derive per-client keys from one root secret (no key table). | Recommended: destroying one client's key makes its pseudonyms unlinkable, as 003 section 7 requires. Alternative: one fewer table, but a root-key compromise exposes every client, and per-client crypto-shredding becomes impossible. |
| D12 Development retention (Q-012, provisional) | Design section 12.5: identity rows follow their evidence; persons deleted 395 days after last evidence or when empty; handoffs 1 day after expiry or use; merge ledger 2 years or until erasure; change feed 30 days; tombstones for the workspace lifetime. Development only, like D-027 decision 7. | Keep identity rows until manual deletion during development. | Recommended: lifecycle behavior is tested before real data. Alternative: less code now, but untested retention and an open Q-012 blocker for any pilot. |

## Group B: identity policy

| ID | Recommended option | Practical alternative | Consequence of each |
|---|---|---|---|
| D2 Evidence and automatic linking | Automatic links only from **trusted assertions** sent with an ingest key, per identifier method and `verified_at` within **30 days**. Keys join only when co-asserted in one assertion. The engine never merges existing persons. Browser forms, campaign links, devices and IP addresses never link. No webhook assertions in 006 v1. | Also accept unverified contact values (for example a lead-form email) as automatic links when they match an existing verified key. | Recommended: fewer false merges and a clear evidence chain, but lower recall (Outcome B in design section 2.2). Alternative: more connected journeys, but anyone typing another person's email attaches their visits to that person's timeline, which violates acceptance criterion 2. |
| D4 Phone normalization | `phone:v1` = international input only (`+` or `00`); national input rejected with `phone_country_required`. The candidate trunk-zero rule is not used. | (a) Add a per-client default country with the trunk-zero rule (new client column). (b) Add a phone-number parsing library (new dependency) with an explicit per-assertion country. | Recommended: no false merges from country guesses; senders must convert to international form. (a) Merges a Saudi or UAE mobile with an Egyptian landline, mishandles Italian numbers, and false merges cannot be undone without the raw values (design section 5.1, observed on merged code). (b) Correct parsing, but a dependency and metadata update cycle needs its own approval. |
| D5 Conflicts and shared devices | Rules R1-R5 and the segment model of design sections 4.2-4.4: contested keys, an ambiguous outcome with a review queue, `customer_ref` authoritative within its client (one per person), phones as weak anchors that never pull a new email or `customer_ref` into a person (R2-P), pre-identification events ambiguous on shared devices, cross-boundary late events ambiguous. Add tracker `restart()` for sign-out. | Treat any second person on a collection subject as making the whole subject ambiguous (no segments). | Recommended: shared devices keep usable journeys without transferring visits between people. Alternative: simpler code, but a shared family browser loses all attribution after one switch. |
| D13 Lead and customer stages | Design section 4.5: lead requires a **trusted** `lead_signal`; customer requires **verified sale evidence from 007**; browser lead signals and trusted purchase signals are flags only. | Treat any lead_signal as a lead and a trusted purchase_signal as a customer until 007 exists. | Recommended: stage counts are evidence-backed and do not change meaning when 007 arrives. Alternative: earlier "customer" numbers that 007 would later contradict. |

## Group C: consent, handoff and deletion

| ID | Recommended option | Practical alternative | Consequence of each |
|---|---|---|---|
| D3 Identity handoff | One-time handoff code from the tracker (`identityHandoff()`), 10-minute lifetime, single use, issued only with effective `identity_link`, redeemable only with the client's ingest key. The subject token stays private to the tracker. | Expose the subject token to the host page so the client's backend can send it directly. | Recommended: one small public route and table, with no long-lived bearer token in client systems. Alternative: no new route, but a 12-month credential that can change consent and erase data spreads into client backends and logs. |
| D6 Retrospective linking | R-B: a link covers events of that collection subject received at or after its `identity_link` grant, including events before the assertion. | R-A: all retained events of the collection subject. R-C: only events received after the assertion. | R-B: in the usual one-banner flow the whole session links, and nothing collected before identity consent is linked. R-A links data collected without identity consent. R-C loses the campaign landing that preceded sign-in, which is the main value of cross-device attribution. |
| D7 Withdrawal, expiry and erasure | **W1**: withdrawing `identity_link` deletes that collection subject's links, assertions and handoffs immediately, and removes persons and keys left without evidence. On **expiry**, nothing new is linked and earlier assignments stay until their events expire. **Erasure** follows design section 7 with new tombstone types `identity_key` (over the pseudonym) and `assertion_id`. | **W2**: withdrawal stops new links but keeps past links for history. | W1 matches the 003 propagation rule (linking stops; without another basis, delete) and leaves no linked history the visitor objected to. W2 keeps fuller history for attribution, but continued use of withdrawn linking needs a legal basis the owner must document. |

## Group D: access and corrections

| ID | Recommended option | Practical alternative | Consequence of each |
|---|---|---|---|
| D8 Who may read person-level data | Owner/Admin for all clients; Analyst and ClientViewer only with a new per-client `can_view_identities` grant flag (default off), like the financial flag. No service read-key access in v1. | Any principal with `client:read` sees profiles and timelines. | Recommended: person-level journeys are opt-in per member and client; one schema flag on two grant tables. Alternative: no schema change, but every existing analyst and client viewer immediately sees person-level journeys. |
| D9 Contact values | Store keyed identifiers only. Profiles and the lead inbox show identifier kinds and verification methods, **never values or masks**. Follow-up uses the client's own CRM. The 004 form classes stay unchanged. | Store sealed raw contact values and add a contact-view permission so the lead inbox can show them. | Recommended: no reversible contact store, smallest breach impact, no new key custody. Alternative: a more useful inbox, but new high-sensitivity storage, a display permission, export rules and Q-012 retention, all of which need review. |
| D10 Merge and unmerge | Owner/Admin only, with closed reason codes and expected versions. Pointer merges that move nothing, evidence-anchored associations, exact unmerge with ambiguous items sent to review, idempotent operation IDs, and the `identity_changes` feed for 007/008. | Physical merge that rewrites keys and links to the survivor and keeps a history table. | Recommended: unmerge is exact and cheap, and original evidence is never edited. Alternative: simpler reads, but reversal must replay history and loses links created during the merge window. |

## Reconciliation of the open questions listed by the specification

| Question | Current register state | Effect on 006 | Blocks 006? |
|---|---|---|---|
| Q-002 Initial lead and sale evidence sources | Open. | 006 needs only the generic trusted assertion API and the existing `lead_signal`/`purchase_signal` types. The named sources (forms, CRM, payment provider, scheduler) decide which senders exist in 015 and what 007 calls verified sale evidence. | **No** for local synthetic implementation. **Yes** for real customer intake and for any customer-stage count (007). |
| Q-008 (originally "authentication, registration and roles") | Narrowed: roles, registration and local authentication are resolved by D-017/D-019/D-022. Only production mail and Facebook sign-in remain. | 006 uses the existing roles plus D8. Agency-user identity is separate from visitor identity (design section 3). | **No.** Recommend removing Q-008 from 006's open decisions. |
| Q-012 Retention, consent and deletion per data class | Open for real data. J1 and tombstone lifetime are decided (D-025); event and subject development retention by D-027. | D12 proposes provisional development values for the new classes; D6/D7 decide consent effects. | **Yes for implementation**, through D6, D7 and D12 (development values). **Yes** for real data until Q-012 is answered for production. |
| Q-003 Markets (not listed by the specification) | Open. | Affects phone handling (D4) and future consent profiles; J1 applies everywhere. | **No** if D4 is approved as recommended. |
| Q-004 Load and budget (not listed) | Open. | The per-client lock serializes identity writes; sizing is needed before real intake. | No for local work. |

## Decisions that actually block the next step

- **To start 006-A:** D1, D3, D4, D11 and D12 (schema, key custody, normalizers and retention all land in the migration).
- **To start 006-B:** D2, D5, D6 and D7.
- **To start 006-C and 006-D:** D8, D9, D10 and D13.

Approving Groups A to D as recommended authorizes all five slices locally. A partial approval should name the groups or items approved, and the slices then stop at the first unapproved dependency.
