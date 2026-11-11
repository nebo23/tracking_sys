# Specification 006 verification matrix

Status: **proposed, not executed** (2026-11-11, D-039 preparation). Prepared against [design revision 1](design.md) and the [decision packet](decision-packet.md). Every case uses synthetic agencies, clients, identifiers (`example.test` emails, fictional phone digits) and tokens on a disposable PostgreSQL database. Assertions inspect stored rows, response bodies and outgoing browser bytes, not helper calls.

Acceptance criteria (spec.md): **AC1** anonymous visits link only within the same client under applicable consent; **AC2** shared or conflicting identifiers do not merge without a policy; **AC3** a shared-device switch does not transfer visits; **AC4** merge/unmerge preserves provenance and triggers recalculation without losing evidence.

## Identity and evidence

| Case | Scenario | Required observable evidence | AC | Decisions | Slice |
|---|---|---|---|---|---|
| I1 Verified cross-device journey | Design section 2.1: phone P (link L1), server subject Q, laptop L, assertions A1-A3. | One person S1; links P->S1, Q->S1, L->S1, each naming its assertion; timeline e1-e6 in the specified order with both times, trust levels and `spring-25`/`ig-post-0147` provenance on e1/e2; stage `lead` with flag `purchase_reported`; no customer stage. | AC1 | D2, D3, D6, D13 | B, C, E |
| I2 Unlinked anonymous visit | Design section 2.2: P never asserted. | P has **no** row in `identity_links`; S1's timeline contains no event of P; the profile's first touch is not `spring-25`; aggregate event counts still include P. | AC1 | D2 | B, C |
| I3 Shared campaign URL | 50 synthetic subjects arrive through the same `ts_link`, one of them asserted. | Exactly one link exists; the other 49 subjects have no links and no review entries. | AC1 | D2 | B |
| I4 Conflicting identifiers | Assertion with an email owned by X and a phone owned by Y, no customer_ref. | Outcome `ambiguous` with candidates {X, Y}; no new link; X and Y unchanged (versions, keys, timelines); review queue entry. | AC2 | D2, D5 | B |
| I5 Shared email | Accounts `cust-2001` and `cust-2002` both assert `family@example.test`. | Two persons; the email key `contested` with null owner; a later email-only assertion is `ambiguous`; neither timeline gains the other's events. | AC2 | D5 | B |
| I6 Recycled phone | X verified a fictional phone; a different person later asserts the same phone with their own email. | Phone key contested (R2-P); the new email forms a new person and never joins X; X's earlier links unchanged; no event of the new person in X's timeline. A variant where X adds an email next to the phone shows the documented split. | AC2 | D5 | B |
| I7 Same person, second key | Assertion with an owned email plus a new phone; later a phone-only assertion on another device. | The phone joins the owner only through the co-assertion; the phone-only assertion links to that owner. A separate first assertion of a new key creates a new person and no merge. | AC2 | D2 | B |
| I8 Stale or invalid verification | `verified_at` 31 days old, in the future beyond 5 minutes, unknown method, national phone, invalid email. | 422 with closed reasons (`verification_stale`, `phone_country_required`, ...); no assertion, key or link row; only diagnostic counters change. | AC2 | D2, D4 | B |
| I9 Normalization vectors | The vectors of design section 5.1, plus email case, whitespace and plus addressing. | `email:v1` and `phone:v1` outputs and rejections exactly as tabled; no national number is accepted under `phone:v1`; key rows store the normalizer label. | AC2 | D4 | A |
| I10 Shared-device switch | Tablet T: Sara asserted at 10:00, Omar at 10:20, events before, between and after, and one event received after 10:20 that claims 10:19:50. | Sara gets only events received 10:00-10:20; Omar only from 10:20; pre-10:00 and cross-boundary events are in neither timeline; no Sara event in Omar's responses or vice versa. | AC3 | D5 | B, C |
| I11 Sign-out restart | The tracker calls `restart()` after Sara; Omar grants and signs in. | A new collection subject for Omar; no request after `restart()` carries Sara's token; Sara's server consent is unchanged. | AC3 | D5 | E |

## Consent, isolation and deletion

| Case | Scenario | Required observable evidence | AC | Decisions | Slice |
|---|---|---|---|---|---|
| P1 No identity consent | Subject granted analytics only; host calls `identityHandoff()`; server tries the subject-token path. | Tracker sends **no** handoff request; the route returns the closed denial; the assertion is `suppressed` with the existing reason `consent_unknown` (from `app.privacy.consent.evaluate`); no handoff, assertion, key or link row. | AC1 | D3, D6 | B, E |
| P2 Later consent (R-B) | Events e1-e3 under analytics; identity_link granted at t; e4; assertion. | Only events received at or after t are assigned; e1-e3 remain anonymous. | AC1 | D6 | B |
| P3 Withdrawal (W1) | Linked subject withdraws identity_link. | In the same transaction: the subject's `identity_links`, `identity_assertions` and `identity_handoffs` rows are absent; an evidence-less key and person are deleted; timelines no longer list its events; events remain in `collected_events` while analytics stays granted; a change record exists. | AC1 | D7 | B |
| P4 Expiry | identity_link grant expires; later events arrive. | No new link; events received after expiry are not assigned; earlier assignments remain. | AC1 | D7 | B |
| P5 Cross-client isolation | The same synthetic email and customer ref are asserted in clients X and Y of one agency, and in a client of another agency. | Different `key_bytes`; no X response contains a Y ID; Y person, assertion and link IDs used in X paths return the generic 404; an X ingest key cannot assert for Y; composite FKs reject a crafted cross-client row. | AC1 | D11 | A, B, C |
| P6 Read permissions | Owner, Admin, Analyst and ClientViewer with and without `can_view_identities`; read key; ingest key; disabled member; other agency. | Exactly the matrix of design section 12.3; denied principals get no person, key kind or count fields. | AC1 | D8 | C |
| P7 No raw identifiers at rest or in logs | Run I1, I5, P3 and E1 with captured logs. | The synthetic email and phone strings (and their unsalted SHA-256) are absent from every table, audit row, diagnostic, log line and error body; responses show no values or masks. | AC1 | D9 | A-E |
| E1 Erasure by person | Erase S1 from I1. | Persons, keys, links, assertions, handoffs and merge rows of S1 are absent; P, Q and L are erased through the 004 path with tombstones; deletion request per-target outcomes `done`; audit has IDs only. | AC1 | D7 | D |
| E2 Erasure on a shared device | Erase Sara from I10. | Only Sara's segment events (and pre-switch ambiguous events) are deleted, with `event_id` tombstones; Omar's events and links remain; T's token is not tombstoned. | AC3 | D5, D7 | D |
| E3 Replay and delayed import | After E1, resend A1-A3 (same IDs) and a new assertion with the same email from a subject whose identity_link predates the erasure. | Same IDs -> rejected `replay_before_deletion`; new assertion -> `no_consent_after_deletion`; no person recreated. | AC1 | D7 | D |
| E4 New consent after erasure | A new subject grants identity_link after the erasure and asserts the email; also the objected variant. | Without objection, a **new, unconnected** person; with objection, rejected `subject_objected`. | AC1 | D7 | D |
| E5 Lifecycle cascade | Expire a linked collection subject and its events through the lifecycle runner. | Identity rows of that subject are removed in the same batch under the client lock; no orphan link; a person left without evidence is deleted. | AC1 | D12 | B |

## Profile, timeline and corrections

| Case | Scenario | Required observable evidence | AC | Decisions | Slice |
|---|---|---|---|---|---|
| T1 Ordering and ties | Events with equal `occurred_at`, equal receipt times, a late arrival (6 minutes) and a 004 trusted upgrade. | Order by (occurred_at, received_at, event_id); `late: true` only for the late event; upgraded entry shows rank 2 and its revision; `journey_revision` increases after the late arrival. | AC4 | D10 | C |
| T2 Lead inbox | Trusted and browser lead_signals, linked and unlinked. | Correct `identified`/`unidentified`, trust and provenance; no contact value, note or owner field; stage `lead` only for the trusted, linked signal. | — | D9, D13 | C |
| M1 Mistaken merge and reversal | Design section 10.2 exactly (S7/S8, t1-t7, D4 co-assertion during the merge). | Before, merged and after timelines as tabled; after reversal S7 = {t1, t2}, S8 = {t3, t4, t5}; D4's link in review and t7 in neither timeline; `collected_events`, assertions and keys byte-identical before and after; both revisions increased; ledger and audit rows present. | AC4 | D10 | D |
| M2 Merge permissions and versions | Analyst, ClientViewer and keys attempt to merge; two Admins merge with the same expected version; repeat with the same operation ID. | Only Owner/Admin succeed; exactly one concurrent merge wins and the other gets 409; the repeated operation returns the original result without a new ledger row. | AC4 | D10 | D |
| M3 Recalculation signal | Merge, unmerge, withdrawal, erasure and a late event. | Each appends `identity_changes` with affected person IDs and the new revision; no identifier in the feed. | AC4 | D10 | D |

## Concurrency and schema

| Case | Scenario | Required observable evidence | AC | Decisions | Slice |
|---|---|---|---|---|---|
| C1 Concurrent new key | Two connections assert the same new email from two subjects at once. | One person, one key, two links; no unique-violation error reaches the client. | AC2 | D11 | B |
| C2 Assertion vs withdrawal | Assertion and identity_link withdrawal on the same subject race. | Either the assertion is suppressed, or its rows are removed by the withdrawal; never a surviving link after a committed withdrawal. | AC1 | D7 | B |
| C3 Assertion vs erasure / merge | Assertion races person erasure, and separately a merge of its target. | After erasure, no rebuilt person; after merge, the link names the original owner and resolves to the root. | AC1, AC4 | D7, D10 | D |
| C4 Handoff reuse | Two redemptions of one handoff, one after 10 minutes, one from another client's key. | Exactly one success; the others are generic rejections; the handoff is consumed once. | AC1 | D3 | B |
| DB1 Migration 0009 | Fresh upgrade, re-upgrade, metadata comparison, guarded downgrade with populated tables, runtime and lifecycle grants, data-policy registry coverage. | All checks pass on the disposable database; no native run. | — | D11, D12 | A |
| E2E Browser journey | Chromium and Firefox: link -> consent -> events -> `identityHandoff()` -> loopback backend asserts -> second browser context asserts -> timeline API. | Outgoing bytes contain no identifier value; the handoff code is never in a URL; the timeline matches I1; repeated with identity_link denied (P1). | AC1 | D3 | E |

## Execution record required after implementation

Record the tested commit and tree, Python/Node versions, the disposable database identity, browser versions, commands, counts, skips and warnings. Run the full backend suite (with the database and browser journeys), Ruff lint and format, `pip check`, migration/grant/metadata/data-policy/OpenAPI checks, Node and Playwright tests, and `git diff --check`. Inherited coverage from 002-005 must stay green.
