# Specification 006 design — Lead identity and customer journey

Status: **proposal, revision 2** (local review of the published D-039 preparation at `b9801de`, 2026-11-11). Nothing in this document is approved for implementation. Schema, dependencies, policies and values below become binding only through a recorded owner decision on the [decision packet](decision-packet.md). Baseline and inherited contracts: [entry review](entry-review.md). Test plan: [verification matrix](verification-matrix.md).

All names, addresses, numbers, identifiers and times in this document are synthetic. Email addresses use the reserved `example.test` domain; phone numbers use fictional digit patterns.

## 1. Product outcome

An authorized agency user can answer, for one client:

> Which interactions can we reliably associate with this lead or customer, in what order, and what evidence supports each association?

Three properties follow from that question and drive the whole design:

1. **Evidence before association.** Every association between an interaction and a person names the evidence that created it. An association without evidence does not exist.
2. **Abstain when unsure.** When the evidence is missing, conflicting or shared, the interaction stays anonymous or is marked ambiguous. A wrong association is treated as worse than a missing one, because it misattributes revenue and can expose one person's activity to another.
3. **Client isolation.** A person exists only inside one client workspace. The same verified contact in two clients produces two unrelated records that cannot be compared.

## 2. Worked journey (synthetic)

Client `bloom` (a synthetic clinic in agency `north`) runs campaign `spring-25` with content reference `ig-post-0147` and managed link `go.example.test/r/spring` (link ID `L1`). The visitor, Mona, uses a phone and later a laptop. The tracker is installed as in specification 005, with the 006 handoff addition proposed in section 8.

### 2.1 Outcome A: both devices reliably associated

| Time (UTC) | Device | What happens | Stored result |
|---|---|---|---|
| 11-02 09:00:00 | Phone | Mona taps the Instagram link. The redirect returns 302 to `https://bloom.example.test/offer?utm_source=instagram&utm_medium=social&utm_campaign=spring&utm_id=spring-25&ts_link=L1`. | Nothing. The redirect stores no visit, cookie or identifier (005 D5). |
| 09:00:05 | Phone | Her banner choice grants `analytics.first_party`, `attribution` and `identity_link`. | Collection subject **P** (token `sbj_...P`) with three consent records, received 09:00:05.200. |
| 09:00:06 | Phone | Page view `e1`. The tracker moves `ts_link` into `link_id`. | `e1`: browser, trust rank 1, `link_id = L1` (campaign `spring-25`, content `ig-post-0147`). |
| 09:03:40 | Phone | Lead form submitted with `plan = pro`. | `e2` form_submit, rank 1, `link_id = L1`. No email is stored by the tracker (004 field matrix). |
| 09:05:09 | Phone | Bloom's own site emails Mona a six-digit code; she types it on the phone. | Nothing in Tracking System. Verification is Bloom's process. |
| 09:05:10 | Phone | Bloom's verified form session supplies a fresh random challenge. The page passes it to `tracker.identityHandoff(challenge)` and posts the returned code to the same backend session. | Handoff H1 stores digests of its code and challenge for P. It expires after 10 minutes and permits one application. |
| 09:05:11 | Bloom backend | `POST .../identity-assertions` with Bloom's ingest key: assertion `A1`, handoff H1 and the challenge from its own verified session, identifier `email = mona@example.test`, method `email_code`, verified at 09:05:09. | New person **S1**. Identity key **K1** (keyed email) owned by S1. Link P->S1 via A1. P's events received after 09:00:05.200 now belong to S1. |
| 09:05:12 | Bloom backend | Bloom's backend recorded Mona's form consent through the server consent API (collection subject **Q**, `attribution` and `identity_link`), sends a trusted `lead_signal` `e3` (`consultation_request`) and assertion `A2` (subject token of Q and the `identity_link` receipt, same email, `email_code`). | `e3`: server, trust rank 2. Link Q->S1 via A2. S1 becomes a **lead**. |
| 11-05 20:10:00 | Laptop | Mona types `bloom.example.test` directly. Banner grants the three purposes. | Collection subject **L**. Page view `e4` without link or campaign. |
| 20:12:30 | Laptop | She signs in to Bloom's patient portal (account `cust-1042`). Bloom's backend asserts `A3` with a handoff for L: `customer_ref = cust-1042` (method `account_login`) and `email = mona@example.test` (method `account_verified_email`). | K1 is already owned by S1, and the new key **K2** (customer_ref) is co-asserted with it, so K2 joins S1. Link L->S1 via A3. |
| 20:14:02 | Laptop | Page view `e5` (`/pricing`). | `e5` rank 1, assigned to S1 through L. |
| 20:31:45 | Bloom backend | Bloom's server reports a payment as `purchase_signal` `e6` on Q. | `e6` rank 2. S1 is flagged `purchase_reported`. S1 is **not** a customer until specification 007 records verified sale evidence. |

The evidence chain for every interaction in S1's timeline:

| Event | Device subject | Link | Evidence behind the link | Consent that permitted it |
|---|---|---|---|---|
| e1, e2 | P | P->S1 | A1: Bloom's server asserted K1 after an email code entered **on the phone**, delivered through handoff H1 issued to P | analytics (collection); identity_link on P (handoff and link) |
| e3, e6 | Q | Q->S1 | A2: Bloom's server asserted K1 for its own server subject Q | attribution (collection); identity_link on Q |
| e4, e5 | L | L->S1 | A3: Bloom's server asserted K2 and K1 after a portal sign-in **on the laptop**, delivered through a handoff issued to L | analytics; identity_link on L |

The phone and the laptop are connected only because each device presented, through its own handoff, an identifier that Bloom's system verified on that device. The campaign link, the shared clinic URL, the device type and the time proximity play no part.

### 2.2 Outcome B: the phone visit has no qualifying link

Everything is the same except that Mona closes the phone tab before entering the email code, so no handoff from P is ever asserted.

- P keeps `e1` and `e2` as an **anonymous** collection subject. They still count in aggregate campaign reporting for `spring-25` under the analytics purpose.
- S1 is created later from the laptop (A3) and the server subject (A2). Its timeline contains `e3`, `e4`, `e5` and `e6` only.
- Nothing links P to S1. The `ts_link = L1` in P's events is shared by every visitor of that post. The `plan = pro` choice could match any number of people. A typed but unverified email on the phone, even if one were collected, would be a claim, not evidence (section 4.3).
- Person-level attribution (008) for S1 therefore sees no `spring-25` touch. The design accepts that loss rather than guessing.

### 2.3 What the timeline contains

The profile and timeline responses for Outcome A are shown in section 13. The timeline lists each interaction once, in the order defined in section 9.2, with its device subject, the evidence (assertion, key kind and verification method), its trust level, `occurred_at`, `received_at` and campaign/content provenance.

## 3. Definitions and relation to existing contracts

| Term | 006 meaning | Relation to merged code |
|---|---|---|
| **Collection subject** (existing) | One pseudonymous browser session or server-held record that holds consent and events. | `collection_subjects` (004): created only by an explicit grant; bearer token `sbj_...` (SHA-256 digest stored); consent records and events reference it. A browser token lives at most 24 hours locally (005 D6). It is a device/session identifier, **not** a person. |
| **Subject** (new, "person") | One client-scoped person to whom evidence attributes interactions. | New `identity_subjects`. Never shares an ID or table with collection subjects. Random UUID; carries no identifier value. |
| **IdentityKey** (new) | A keyed pseudonym of one verified identifier value inside one client: kind `email`, `phone` or `customer_ref`. | Computed with `app.privacy.deletion.subject_key` (HMAC-SHA256 under a random per-client key, domain `subject:v1`, client ID in the message) with the normalizer label as the kind argument and the canonical value as the final argument (section 5). Raw values are used transiently and never stored. |
| **IdentityLink** (new) | Evidence that one collection subject's interactions belong to one person for a time interval. | New `identity_links`, created only from an identity assertion. References the collection subject, the person and the assertion. |
| **Identity assertion** (new evidence record) | A trusted sender's statement that, on one collection subject, the person proved control of the listed identifiers. | New `identity_assertions`; sender idempotency ID like 004 `event_id`. |
| **Touchpoint** (derived) | One collected event as it appears in a person's journey: the event, the link that assigns it, and the event's provenance. | Read model computed from `collected_events` (event ID, type, channel, trust rank, `occurred_at`, `first_received_at`, `link_id` -> managed link, campaign and content reference) and `identity_links`. No event payload is copied. |
| **Agency user** (existing) | A platform login (`users`, `external_identities`). | Entirely separate. Agency users never become persons, and a visitor's identifier is never compared with platform accounts. Google sign-in (D-022) identifies agency users only. |
| **Client workspace** (existing) | Tenant boundary. | Every new table has composite `(agency_id, client_id)` foreign keys, as in 004/005. |
| **Event ID / link ID** (existing) | Sender idempotency ID of an event; managed link reference. | Touchpoints are keyed by `collected_events.id` and display `event_id`. `link_id` provides campaign and content provenance and is never identity evidence. |

## 4. Evidence and matching rules

### 4.1 Evidence sources

| Source | Who may submit | What counts as verification | May link automatically? |
|---|---|---|---|
| **Trusted identity assertion** with a browser handoff | An ingest key granted for the client. | The client backend binds its verified form or login session to the browser handoff (section 8). For email, accept `email_code`, `email_link` or `account_verified_email`. For phone, accept `phone_code` or `account_verified_phone`. For `customer_ref`, accept `account_login`. `staff_verified` requires the client's explicit attestation for the named kind. Each `verified_at` must be within 30 days and at most 5 minutes ahead of server receipt (D2). | Yes, subject to section 4.2. |
| **Trusted identity assertion** for a server-held collection subject | Same ingest key scope, direct token of a subject created by the server consent API. | Same method and freshness checks. Validate the stored issuance channel and require the current server-recorded `identity_link` grant receipt for this subject. The sender obtains the receipt from the server consent response. For a multi-purpose grant, map the returned receipts in sorted purpose order as 004 records them. A later server consent update on a browser token cannot change its issuance channel. | Yes, subject to section 4.2. |
| Signed webhook assertion | Generic HMAC webhook sources (004). | Same rules. | **Not in 006 v1** (proposed for 015 with named integrations). |
| Browser form value (email, phone, name) | Public browser. | None. | **Never.** 006 keeps the 004 form classes unchanged; contact values are not collected by the tracker (D9). |
| Managed link or UTM parameters (`ts_link`) | Public browser. | None; shared by every recipient. | **Never.** Provenance only. |
| Device, IP address, user agent, fingerprint, timing | — | — | **Never collected or used.** Excluded by the specification. |
| CSV, CRM or connector import | 015/009. | E6 rules. | Not in 006. |
| Manual merge | Agency Owner/Admin. | Human judgement with a closed reason code. | Manual, audited and reversible (section 10). |
| Platform-run verification (Tracking System emailing or texting a code to the visitor) | — | — | **Not proposed.** It would be outbound contact with client customers, which needs its own approval. |

"Verified" therefore always means *verified by the client's own system and asserted by the client's trusted backend*. Tracking System records the declared method and time. It never claims independent verification.

### 4.2 Deterministic matching within one client

Processing one assertion (all inside the client privacy lock, section 12.4):

1. Authenticate the sender, lock the client and resolve an authorized retry as specified in section 12.4. For a new assertion, resolve a live, unused, challenge-bound handoff or a server-issued subject token. Use a generic rejection for invalid proof.
2. Require `identity_link` currently granted on that collection subject (E3, section 6). For a new direct-token assertion compare its receipt to the current grant. For a handoff compare the receipt captured at issuance to the current grant. A fresh grant cannot reactivate old proof.
3. Canonicalize every identifier with its versioned normalizer (section 5) and compute its IdentityKey. An identifier that cannot be canonicalized rejects the whole assertion (no partial evidence).
4. Check tombstones for every key and for the assertion ID (section 7).
5. Classify the asserted keys by current owner. Apply the R5 filter first:
   - **R1 (new person).** No key is owned or contested -> create a person, assign every key to it, and link the collection subject.
   - **R2 (one owner).** At least one key is owned, every owned key belongs to the same person (after resolving merges), any remaining eligible keys are new, and neither R3 nor R2-P applies -> assign the new keys to that person and link the collection subject. Keys asserted **together in one assertion** belong together because the sender stated that one person proved control of all of them. This is the only way two keys join automatically.
   - **R2-P (phone is a weak anchor).** Phone numbers are recycled and shared more often than email addresses or account IDs. If the only owned keys in the assertion are phones and it brings a new email or `customer_ref`, the phones become **contested**, and the new keys form a new person (or follow R3), with outcome `contested_identifier`. A new phone may still join a person anchored by an email, a `customer_ref` or another phone.
   - **R3 (customer reference is authoritative).** A person holds at most one `customer_ref`, the client's own account ID. R3 applies when the assertion carries a `customer_ref` and either (a) it is owned by X while another asserted key is owned by a different person, or (b) it is new while the owner of another asserted key already holds a different `customer_ref`. The `customer_ref` then decides: link to X, or to a new person created for the new `customer_ref`. Every asserted key owned by a different person becomes **contested** (owner cleared), with outcome `contested_identifier`. A new `customer_ref` joins an existing person only when that person has none (Mona's A3 in section 2.1).
   - **R4 (conflict).** Owned keys point to two or more different persons and no `customer_ref` decides -> **no link and no merge**. The assertion is stored with outcome `ambiguous` and candidate person IDs for Owner/Admin review (section 9.4).
   - **R5 (contested evidence).** Exclude contested keys from ownership decisions. Keep their contested status and record that they were presented. With no remaining key, return `ambiguous`. With only new keys, run R1 on those keys. With owned keys, resolve R2/R2-P/R3/R4 using only the eligible keys. An undecidable combination of multiple owners and a new `customer_ref` is ambiguous unless R3 identifies a distinct account without assigning any other person's owned keys.
6. Apply the device rule (section 4.4) to the collection subject's existing links.
7. Consume the handoff, write the assertion, links and key changes, bump the journey revision of the affected persons, and append change records.

Two automatic rules are deliberately absent. **The engine never merges two existing persons**; only an Owner/Admin merge does. **Keys never join across assertions** through a shared device, because a device does not establish identity.

### 4.3 Shared, recycled and conflicting identifiers

| Situation | Outcome |
|---|---|
| Shared email (two Bloom accounts `cust-2001` and `cust-2002` both use `family@example.test`) | The second account's assertion triggers R3: the email key becomes contested, and each account remains its own person. From then on, an assertion carrying only that email is ambiguous. |
| Recycled phone (a fictional `+20 10 0000 0101` verified by person X in 2025 and by a different person in 2026 with their own email) | R2-P: the 2026 assertion (phone owned by X plus a new email) makes the phone contested and creates a new person for the new email; the email never joins X. If the new email was already owned by someone else, R4 applies instead. X's earlier links stay valid for their period. Recycling cannot be detected deterministically, so contested is the safe result. The cost: X legitimately adding an email next to a phone is split into two persons until an Owner/Admin merges them. |
| Conflicting identifiers in one assertion (email owned by X, phone owned by Y, no customer_ref) | R4: ambiguous, nothing linked, both persons unchanged, review entry created. |
| Verified identifier that matches an unverified one typed elsewhere | Not applicable: unverified values are never stored, so they cannot match. |
| Same person, second verified identifier later | Linked only when co-asserted with an identifier already owned by that person (R2). A separate assertion with only the new identifier creates a new person; a later co-assertion of keys with distinct owners goes through R3/R4. Joining the two existing persons requires a manual merge. |
| Assertion with stale verification (older than the freshness window) | Rejected with `verification_stale`; nothing stored except a counter. |

### 4.4 Shared device and account switching

A collection subject can carry links to several persons over time. Its links form **segments** ordered by assertion receipt time:

- Store each segment's inclusive `eligible_from` and exclusive `eligible_until`. Cap eligibility at the end of its uninterrupted identity consent and at the next account switch or ambiguous assertion. A new ambiguous result ends the previous person's segment even though it creates no new owned link.
- The first unambiguous link can extend back to the start of its current grant (D6). Once a second original owner or conflicting evidence appears, close the retrospective portion permanently. Persist the shortened bounds so erasure, expiry of evidence, a merge or an unmerge cannot extend another person's segment. Later links cannot bridge a consent gap or a period of ambiguity.
- An event whose `first_received_at` falls in one person's segment while its client-claimed `occurred_at` falls in another person's segment or a known unassigned gap is **ambiguous** (for example, a queued event of the previous user delivered after the switch). Client time can only withhold an association, never create one.
- A new assertion for the same original owner continues a segment only while consent and evidence are uninterrupted. Use server receipt order for boundaries. An event indistinguishable from a switch at the database clock's precision stays ambiguous.

Example: Sara signs in on a shared clinic tablet (collection subject T) at 10:00 and leaves; Omar signs in on the same browser session at 10:20. Events received 10:00-10:20 -> Sara; events received from 10:20 -> Omar; events received before 10:00 -> ambiguous (T is shared); an event received at 10:20:30 but claiming 10:19:50 -> ambiguous.

The host must call `restart()` when it observes sign-out or an account switch, before recording activity for the next user. A gap between an unreported change of user and the next assertion has no reliable owner. The segment rule identifies recorded boundaries only. Sites without a reliable account-transition signal on a shared device should limit person-level association to interactions bound to a verified account session (D5).

### 4.5 Lead and customer qualification

| Stage (derived on read) | Required evidence | Not sufficient on its own |
|---|---|---|
| Anonymous visitor | A collection subject without an assigned link. Not a person. | — |
| Known | A person with at least one active link from a verified assertion. | Campaign link, form submission, device |
| Lead | Known, plus at least one **trusted** (rank 2, server channel) `lead_signal` assigned to the person. | A browser `lead_signal` (rank 1) is shown as `lead_reported_unverified` and does not change the stage. |
| Customer | Known, plus at least one **verified sale** in the 007 revenue ledger linked to the person. | A trusted `purchase_signal` is shown as `purchase_reported` and does not make a customer. Until 007 exists, no person is a customer. |

This keeps three levels distinct in every response: `browser` (rank 1, untrusted sender), `trusted_sender` (rank 2, the client's backend) and `verified_sale` (007). A lead_signal that arrives on a collection subject without a link still appears in the lead inbox as an unidentified lead (section 9.3).

## 5. Canonicalization and normalization versions

006 calls `app.privacy.deletion.canonical_identifier` for validated email and phone inputs and validates `customer_ref` separately. The matching and erasure paths share this adapter:

| Kind | Version | Rule |
|---|---|---|
| email | `email:v1` | `normalize_email` (email-validator syntax check, then lowercase). No dot or plus rewriting: `mona.example+promo@example.test` and `mona.example@example.test` are different keys (a missed match, never a false merge). |
| phone | `phone:v1` (recommended, D4) | Require a literal leading `+` or `00` after trimming. Allow ASCII digits, spaces, hyphens and parentheses in the remainder, with 8–15 ASCII digits after removing formatting. Reject other characters and extensions before calling the 003 helper without a default country. National input returns `phone_country_required`. |
| customer_ref | `ref:v1` | Exact client account ID, 1-128 characters of `[A-Za-z0-9_.:-]`, case-sensitive, no normalization. |

Compute `subject_key(client_key, client_id, normalizer_label, canonical_value)`. The label separates versions even when two normalizers return identical strings. In v1 the per-client matching secret stays stable for the workspace lifetime. Rewrapping it preserves its bytes. Before introducing any new matching version, assertion and erasure must check tombstone candidates under every retained applicable version. Losing an old key or a required normalizer must fail closed.

### 5.1 Review of the candidate trunk-zero rule

The merged 003 function also accepts a national number with a default country code and removes one leading zero. These are the actual outputs of the merged function at `c251e20`, run in the project virtual environment with fictional digits:

| Input | Default country | Output | Assessment |
|---|---|---|---|
| `010 0000 0101` (Egyptian mobile, national) | 20 | `+201000000101` | Correct. |
| `+20 10 0000 0101` / `0020 10 0000 0101` | — | `+201000000101` | Correct; all three forms match. |
| `050 000 0101` (Egyptian Mansoura landline, national) | 20 | `+20500000101` | Correct. |
| `050 000 0101` (**Saudi** mobile, national, on a client whose default is Egypt) | 20 | `+20500000101` | **False merge**: identical to the Mansoura landline above. |
| `050 000 0101` (**UAE** mobile, national, on a client whose default is Saudi Arabia) | 966 | `+966500000101` | **False merge** with the Saudi mobile `+966 50 000 0101`. |
| `06 0000 0101` (Italian Rome landline, national) | 39 | `+39600000101` | **Wrong**: Italy keeps the leading zero internationally, so the same line written `+39 06 0000 0101` gives `+390600000101` (missed match), and the wrong form could equal another real number. |
| `011 20 10 0000 0101` (US caller dialling the 011 exit code) | 1 | `+111201000000101` | **Wrong** canonical form. |
| `010 0000 0101` | none | Rejected | Correct: no country context. |

A country assumption is therefore unsafe for any client that serves visitors from more than one country, which is the normal case for a multi-agency SaaS (D-006), and for countries that keep the trunk prefix. Recommendation (D4): `phone:v1` accepts only international input, and the client's form collects or converts the country code before asserting. Alternatives are listed in the decision packet.

## 6. Consent

J1 strict opt-in applies unchanged. Three separate permissions are involved:

| Permission | Rule | Enforcement point |
|---|---|---|
| Collect an event | The 004 required purpose of the event type on its collection subject (`analytics.first_party` for page, link and form events; `attribution` for lead and purchase signals). | 004 admission (E2), unchanged. |
| Link a collection subject to a person | `identity_link` granted (not denied, withdrawn, expired or unknown) on that collection subject when the handoff is issued **and** again when the assertion is processed, plus admission under the tombstones (D-025). | New E3 checks in the handoff route and assertion service. |
| Read a person's profile and timeline | An agency principal with the identity-read permission for that client (D8). The visitor's consent does not grant agency users anything; it limits what exists to be read. | API authorization through `resolve_scope`. |

Time-dependent behavior (D6, D7):

| Situation | Recommended behavior |
|---|---|
| Events collected before `identity_link` was granted on the same collection subject | Not linked. A link covers events received at or after the `identity_link` grant that is in force (retrospective option R-B). |
| `identity_link` granted later than the other purposes | Events from that grant onward become linkable at the next assertion; earlier events stay anonymous. |
| Withdrawal or explicit denial of `identity_link` on a collection subject | Apply W1 on every consent write path in the same transaction. Remove its links, assertions and handoffs, then remove keys and persons left without evidence. Events retain their independent collection policy. |
| Expiry of `identity_link` | End the segment at grant expiry even if no worker runs. Only earlier assignments remain visible. A later grant starts a separate eligibility period and requires a new assertion. A grant renewed before expiry can extend an uninterrupted period. |
| Re-grant after withdrawal or denial | Start a new period. A fresh assertion may link back only to that grant. Before a new assertion the prior person cannot receive new events. |
| Erasure | Section 7. |
| Global Privacy Control | No effect: GPC restricts only `sale_or_share` and the advertising purposes; `identity_link` keeps J1 semantics. |

Retrospective linking and the withdrawal and expiry choices are owner decisions (D6, D7), because they trade journey completeness against how far consent is read into the past.

## 7. Isolation and deletion

### 7.1 Tenant scope

- Write scope comes from the authenticated ingest key and its explicit client grant (`resolve_scope(..., "events:write")`), never from a body field. The handoff route derives the client from the public source key, as the 004 routes do.
- Read scope comes from `resolve_scope` for the authenticated agency user, plus the identity-read permission (D8). Path IDs of another client return the same generic 404 as missing IDs.
- IdentityKeys are HMACs under a **random per-client key**, with the client ID inside the message. The same `mona@example.test` in clients `bloom` and `north-dental` produces unrelated 32-byte values, and no query, index or join compares keys across clients.
- Composite foreign keys make a cross-client link, key or merge structurally impossible.
- Profile, review and write acknowledgements omit raw values and key bytes. Only the successful handoff issuance response carries the one-time code (section 8).

### 7.2 What erasure removes

Resolve the requested original person before deleting anything. For a contested identifier, a person participating in an active merge, or evidence shared across the proposed targets, pause the ambiguous part for clarification. Resolve or reverse an erroneous merge first. A merge pointer alone cannot authorize erasing another original person's history. The authorized deletion runs in one transaction under the agency lock followed by the client privacy lock.

| Store | Action |
|---|---|
| `identity_subjects` | Delete the resolved original person after checking its evidence scope. |
| `identity_keys` | Delete its owned keys. A contested key the person also used loses this person's evidence; if nothing else references it, it is deleted. |
| `identity_links`, `identity_assertions`, `identity_handoffs` | Delete every row of the person. |
| Collection subjects linked **only** to this person | Extend the internal 004 erasure helper to accept an already scoped subject row, including subjects with zero events. Create `subject_token` tombstones from its stored digest and tombstone every retained event ID. Keep the public 004 lookup inputs unchanged. |
| Collection subjects shared with another person | Snapshot original segment bounds first. Delete events assigned to the erased person and ambiguous events that may belong to them, with `event_id` tombstones. Preserve the other person's events, the token and the surviving segment's existing bounds. Future events cannot fall back to the remaining person across a deleted segment. |
| `identity_merges` ledger rows naming the person | Delete. |
| `audit_events` | Kept: IDs and action codes only (existing policy). |
| Derived data in 007/008/014/016 | Notified through the change feed (section 11); each consumer applies its own erasure rule. |

A shared identifier can appear in evidence for several original people. Apply an identity-key tombstone to an exclusive key. For a contested key retain the ambiguity and hold any unresolved objection scope for clarification. No deletion request can report completion while an affected target is unresolved. The existing 004 token-holder route erases that collection subject and its identity evidence only. It never acquires authority over other devices through a person link.

### 7.3 Minimal replay protection

D-025 tombstones are reused with two additional match types (schema change in D11):

| Match type | Tombstone value | Blocks |
|---|---|---|
| `identity_key` | The hex IdentityKey (per-client pseudonym) under the tombstone key | A later assertion of the same identifier, unless the asserting collection subject's `identity_link` consent was received after the deletion and the person did not object (existing `deletion.admission`). |
| `assertion_id` | The sender's assertion ID | Retries or delayed imports of the exact assertions that existed before erasure. |
| `subject_token`, `event_id` (existing) | As in 004 | Events and tokens of erased collection subjects. |

The pseudonym is used as the tombstone value so that erasure by profile ID works without the raw identifier. Tombstones never store raw values, and per-client keys live as long as the workspace, like the tombstones. A delayed import or retry therefore cannot rebuild an erased link. A genuinely new consent after the deletion can create a new, unconnected person, which is what D-025 decision 10 requires. Carry `objected` onto the exclusive identity-key tombstones. Exact assertion IDs are unconditional replay keys. When a lookup is ambiguous, return `paused_for_clarification` before deleting any rows.

## 8. Tracker additions (specification 005 package)

| API | Behavior |
|---|---|
| `identityHandoff(challenge)` | The client's backend supplies a fresh random challenge bound to the current form or login transaction. Include it with the subject token in the request body. Check effective `identity_link` immediately before sending and before returning the code to the same host session. Return `{status: "issued", code, expires_at}` or `blocked`/`unavailable`. Keep both values out of URLs, logs and persistent browser storage. |
| `restart()` | Immediately invalidate the old local session, clear its persisted token, permissions and queue, and cancel timers and pending transmissions where possible. Ignore late responses, including subject creation and issued codes. No queued request or retry may start for the old session. The next explicit grant creates a new subject. Server consent remains in its recorded state. |

The client backend invalidates its pending challenge on logout or account switch. On redemption the backend supplies the challenge from its own verified transaction state. The collector requires matching code and challenge digests, the issued client and subject, live consent and unexpired proof. The handoff correlates a browser with the transaction. The backend supplies the verification evidence. In 004 the 12-month limit applies to a grant. The subject token itself has no fixed 12-month expiry.

## 9. Profile, timeline and lead inbox read models

### 9.1 Profile

Fields include person ID, optimistic-concurrency `version`, status (`active`, or `merged` with `merged_into`), stage and flags (section 4.5), `first_seen_at` and `last_seen_at` (server receipt of the first and last assigned event), key summary (kind, normalizer version, verification method and time, `contested` flag; **never the value or a mask**, D9), device subject count, touchpoint count, first-touch and last-touch provenance (campaign, content reference, link), `journey_revision`, and pending review count. Manager lookup of an original merged ID also returns that member's ID and version for reversal.

### 9.2 Timeline ordering, duplicates and late arrivals

- Each event appears once per person, after resolving merges.
- Order: `occurred_at`, then `first_received_at`, then `event_id`, so equal timestamps sort deterministically. Both times are returned, because `occurred_at` is claimed by the sender (004 bounds: 7 days late, 5 minutes ahead).
- `late: true` when `first_received_at - occurred_at` exceeds 5 minutes.
- Duplicates with the same `event_id` are already merged by 004; a trusted upgrade shows the upgraded content with `trust: "trusted_sender"` and its `revision`. The same action reported by two senders with different event IDs appears twice; 004 upgrades a same-ID event only when the event type and collection subject also match. Evidence on a distinct server subject cannot upgrade a browser subject's event.
- Keyset pagination on `(occurred_at, first_received_at, event_id)`. Each response returns `journey_revision`. A late arrival or correction bumps the revision so a client can detect that earlier pages changed.
- Provenance for each entry: channel and trust, source or credential kind (never the key), `link_id` with campaign public code and content external code when present, minimized URL path from the stored payload, and the evidence (link ID, assertion ID, key kinds, verification methods).

### 9.3 Lead inbox (proposed read model for PDF-050)

`GET .../identity/leads` lists `lead_signal` events newest first: event ID, action, trust, times, person (ID and stage) or `unidentified`, and the individual event's `link_id` provenance. Filters: `identified`, `trust`, time range. It contains no contact values, notes, owners, statuses or pipeline stages. Assignment, follow-up, notes and CRM workflows stay outside 006 (021 or a later decision), as do dashboard screens (018).

### 9.4 Review queue

`GET .../identity/review` (Owner/Admin) lists ambiguous assertions, contested keys and links left ambiguous by an unmerge, with candidate person IDs and reason codes. Resolution happens through new evidence or a manual merge.

## 10. Merge and unmerge

### 10.1 Rules

- Only Owner/Admin may merge or unmerge, with a closed reason code (`same_person_confirmed_by_client`, `duplicate_account`, `data_correction`) and the expected `version` of each person (optimistic concurrency; a stale version returns 409).
- **Pointer merge (D10 recommendation).** Permit disjoint pairs in v1. Both people must be active, distinct, in the same client and outside any active merge. Persist the edge and original owners. Reject a self-merge, chain or overlapping pair before writing. This gives a single reversal target for evidence spanning both sides.
- Every association stays anchored to its **original evidence**: links name the person that owned the asserted key at assertion time, never the merge root. The one exception is a link whose evidence spans both sides of an active merge (section 10.3); it records the merge ID.
- Reverse only the currently active edge named in the request, under the original participants' expected versions. Clear its pointer, restore original-owner reads and move evidence spanning both sides to review. A new operation cannot reverse an already reversed or superseded edge.
- Both operations are idempotent by `operation_id`, ledgered in `identity_merges` and audited (`identity.merged`, `identity.unmerged`), bump both persons' `journey_revision`, and append change records.

### 10.2 Worked mistaken merge (synthetic)

Before (client `bloom`):

| Person | Keys | Devices | Touchpoints |
|---|---|---|---|
| S7 (Ali) | email `ali@example.test` (email_code) | D1 phone | t1 page view via campaign `autumn-25` (rank 1); t2 trusted lead_signal (rank 2) |
| S8 (Aliya) | phone `+20 10 0000 0202` (phone_code) | D2 laptop | t3 page view (rank 1); t4 browser lead_signal (rank 1) |

At 10:00 an Admin merges S8 into S7 with reason `same_person_confirmed_by_client`; this is a mistake. The merged timeline under S7 shows t1-t4, each still labelled with its device and key, so a reviewer can see two independent evidence chains.

During the merged period (10:00-12:00):
- t5: D2 sends a page view -> assigned through D2's link, whose evidence is S8's phone key; displayed under root S7.
- t6/t7: a new tablet D4 is asserted with **both** `ali@example.test` and `+20 10 0000 0202`. Normally that is a conflict (R4). Because both keys currently resolve to root S7, the engine accepts it, but it records the link with `merge_id = M1` and the original owners {S7, S8}. t7 is a page view on D4.

At 12:00 the Admin reverses M1. After:

| Person | Touchpoints |
|---|---|
| S7 | t1, t2: exactly as before the merge |
| S8 | t3, t4, t5: t5 follows its evidence (D2 -> S8's phone key) |
| Review queue | D4's link (evidence spans S7 and S8): **ambiguous**; t7 is assigned to neither person until new single-owner evidence arrives or an Owner/Admin merges deliberately |

No event, assertion or key was rewritten at any point. The unmerge response lists the reverted merge, the restored persons, and the links moved to review.

### 10.3 Ownership during a merged period

| Created during the merge | After unmerge |
|---|---|
| Link whose keys all have one original owner | Stays with that owner. |
| New key co-asserted with keys of one original owner | Owned by that owner. |
| Link or key whose evidence names owners on both sides | Moves to the review queue as ambiguous; excluded from both timelines. |
| Derived results (008 allocations, 016 caches) computed under the merged root | Invalidated through the change feed and recomputed. |

## 11. Recalculation and handoff to 007/008

Start each person's revision at zero before its first link. A committed change to a visible journey increments the revision once per affected journey per transaction for each affected person and visible root and appends `(client, seq, person_id, journey_revision, kind, time)` in the same transaction. Kinds include `linked`, `unlinked`, `contested`, `merged`, `unmerged`, `erased`, `withdrawn` and `events_changed`. The 004 admission, upgrade, erasure and lifecycle paths also notify 006 when an assigned event is added, changes content or leaves retention. Identical retries and rejected events do not advance revisions. Record the final revision before deleting an erased person.

| Derived association | Owner | Action after a change |
|---|---|---|
| Stage, first/last touch, counts, lead inbox | 006 | Computed on read; always current. |
| Touchpoint sequence for attribution | 008 | Each 008 run records the `journey_revision` of every person it used; a change record marks those runs stale. 008 recomputes with the same model version and keeps the superseded run for audit. |
| Sale-to-person association | 007 | 007 associates verified sales with an IdentityKey or a collection subject, never with a merge root. Ownership therefore follows keys and is resolved on read. Detaching identifiers while preserving amounts is the F1 proposal in 003. Its adoption and verification belong to 007. |
| Conversion and audience deliveries | 014 | Delivery claims recheck consent, tombstones and current ownership (E4/E5). |
| Reports and caches | 016 | Epoch invalidation per client. |

006 provides revisions and ordered per-client change records for internal consumers. Checkpoint against a per-client sequence that is contiguous across committed changes (allocate under the client lock). Retain a per-client high watermark after pruning the feed, including when it becomes empty. A consumer whose checkpoint predates retained coverage invalidates its client partition and rebuilds it from current state before advancing to a fresh watermark. This also removes derived rows for people erased during the gap. Actual 007/008 recalculation and its end-to-end verification belong to those specifications.

## 12. Technical proposal

### 12.1 Schema (migration `0009_identity_journey`, proposed)

All tables carry `agency_id` and `client_id` with composite foreign keys to `client_workspaces` and scoped uniqueness `(agency_id, client_id, id)`.

| Table | Columns (summary) | Constraints |
|---|---|---|
| `identity_key_secrets` | version, kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext, created_at | Unique `(client_id, version)`. Per-client HMAC key sealed with the existing token envelope under the D-025 **local development** keyring; production custody follows 020. Use a dedicated envelope kind `identity_matching_key`, the client ID as context owner and this secret row's ID as `secret_id`. Preserve the matching secret across wrapping-key changes. Created on first use under the client lock. |
| `identity_subjects` | status (`active`, `merged`), merged_into_id, version, journey_revision, created_at, updated_at, last_evidence_at | Scoped self-FK; `(status = 'merged') = (merged_into_id IS NOT NULL)`; `merged_into_id <> id`. |
| `identity_keys` | kind, key_bytes (32), key_version, normalizer, subject_id (owner, nullable), status (`owned`, `contested`), first_verified_at, last_verified_at | Unique `(client_id, kind, key_bytes)`; `(status = 'owned') = (subject_id IS NOT NULL)`; normalizer in the closed set. |
| `identity_assertions` | assertion_id (sender), credential_id, collection_subject_id, keyed request fingerprint, proof digest, per-identifier evidence (scoped key ID, method, verified_at, original owner), received_at, outcome, reason, candidate person IDs | Unique `(client_id, assertion_id)`. UUIDs inside compound evidence require explicit same-client validation under the lock. An array of UUIDs alone provides no foreign-key guarantee. |
| `identity_links` | collection_subject_id, subject_id, assertion_id, asserted_at, eligible_from, eligible_until, status (`active`, `ambiguous`), merge_id (nullable), original owners | Scoped FKs and interval checks. Store the exclusive end of every closed segment and its grant bounds independently of expiring consent history. |
| `identity_handoffs` | collection_subject_id, token_digest, challenge_digest, identity_consent_receipt_id, expires_at, consumed_at, created_at | Unique code digest and scoped FK. Issuance binds the code to one backend challenge and one subject. |
| `identity_merges` | operation_id, kind (`merge`, `unmerge`), survivor_id, merged_id, reverses_id, actor membership, reason_code, created_at | Unique `(client_id, operation_id)`; append-only for the runtime except deletion on erasure. |
| `identity_changes` | seq, person_id, kind, journey_revision, occurred_at | Ordered per client. One row per affected person and revision. Erasure notifications survive deletion of the person. |

Add immutable issuance channel (`browser`, `server`, or `unknown` for pre-0009 rows) to `collection_subjects`. Populate it from the trusted creation path. Existing active browser subjects can use a bound handoff. Direct-token assertions require positive server issuance. Legacy server senders must obtain a new subject through fresh explicit consent. Ordinary 004/005 consent and event behavior continues for legacy rows. Keep the committed feed high watermark per client (with the client workspace), including after person erasure. Other changes: `deletion_tombstones.match_type` adds `identity_key` and `assertion_id`; `event_diagnostics.channel` adds `identity`; `audit_events` adds actions `identity.merged`, `identity.unmerged`, `identity.erased` and resource type `identity_subject`; `client_grants` and `invitation_client_grants` add `can_view_identities` (default false, D8). Downgrade refuses populated tables and non-default values, as 0007/0008 do.

### 12.2 API (proposed, 10 operations)

| Operation | Principal | Notes |
|---|---|---|
| `POST /collect/v1/{public_key}/identity-handoff` | Token holder from a registered Origin | Body `{subject_token, challenge}`. Require effective `identity_link`, a live source and the scoped subject. 201 `{code, expires_at}` with the public consent-state CORS policy, per-subject rate limit and `no-store`. |
| `POST /agencies/{a}/clients/{c}/identity-assertions` | Ingest key | `assertion_id` (UUID), exactly one of `{handoff, challenge}` or `{subject_token, identity_consent_receipt_id}`, and 1–3 verified identifiers (one per kind). 201 acknowledged, 200 exact retry, 409 conflicting retry, 422 invalid or suppressed request with a closed reason. Keep matching outcomes internal. Write acknowledgements omit person IDs, candidates and whether an identifier already had an owner (D8). |
| `GET .../identity/subjects` | Identity reader | Filters: stage, flags, updated since; keyset pagination. |
| `GET .../identity/subjects/{id}` | Identity reader | Identify the requested member and its resolved root. Authorized managers can retrieve both participants' versions for a reversal. |
| `GET .../identity/subjects/{id}/timeline` | Identity reader | Section 9.2. |
| `GET .../identity/leads` | Identity reader | Section 9.3. |
| `GET .../identity/review` | Owner/Admin | Section 9.4. |
| `POST .../identity/merges` | Owner/Admin | `operation_id`, survivor/merged IDs and versions, reason. |
| `POST .../identity/merges/{id}/reversal` | Owner/Admin | `operation_id`, both participants' expected versions, reason. |
| `POST .../identity/erasures` | Owner/Admin | Exactly one of `subject_id` or `identifier: {kind, value}`, plus optional `objected` (default false); returns the 004-style deletion request with per-target outcomes. The raw value is used only to compute keys. |

### 12.3 Permissions

| Action | Owner | Admin | Analyst | ClientViewer | Read key | Ingest key |
|---|---|---|---|---|---|---|
| Submit assertions | — | — | — | — | — | Granted client |
| Read profiles, timelines, leads | All clients | All clients | With `can_view_identities` | With `can_view_identities` | No (v1) | No |
| Review queue, merge, unmerge, erase | Yes | Yes | No | No | No | No |

Carry `can_view_identities` through manager grant writes, invitation creation and acceptance, and live user scope resolution (`identity:read`). Keep service grants separate. Updates to an existing grant must preserve any flag omitted by an older caller. Recheck grant removal and membership status on every read.

### 12.4 Transactions, ordering and idempotency

- Audited administration (merge, reversal, person erasure) acquires the agency row lock before the 004 client privacy lock. Other identity writes take the client lock directly. Under the client lock, read the database clock, recheck live scope, consent and tombstones, then lock key rows in key order and persons in ID order. Never acquire an agency, user or session lock while holding the client lock.
- The 004 consent and erasure transactions call the identity cleanup in the same transaction, so a withdrawal or erasure either precedes an assertion (which then observes it) or removes the assertion's results.
- Check the assertion ID replay tombstone before resolving transient proof, including on retries. With live sender scope, look up `(client_id, assertion_id)`. For the same credential, proof and canonical request, return a generic duplicate acknowledgement without consuming again, even after the code expired or its row was purged. A changed request or credential cannot reuse the receipt. Use a keyed fingerprint over canonical evidence, proof digests and verification times. For a first application check proof, current consent, key tombstones and verification freshness, then atomically consume and write the receipt. W1 and erasure remove the old receipt. Bind merge operation IDs to action, target, actor and request content. An exact authorized retry precedes stale-version checks.
- Unique `(client_id, kind, key_bytes)` backs the lock, so concurrent assertions of a new key create one person.
- The per-client lock serializes identity work per client. Throughput limits need Q-004 sizing before real intake.

### 12.5 Data classes and retention (development, provisional)

| Data | Class (data-policy registry) | Proposed development retention (D12) |
|---|---|---|
| Sealed per-client key | `credential.sealed_secret` | Client lifetime; destroyed at offboarding (017). |
| Key bytes | `identity.pseudonym` (new, high, pseudonymous, derived) | With the owning person; contested keys 395 days after last verification. |
| Links, assertions | `identity.link` (new, high, pseudonymous, observed) | With their collection subject (lifecycle or erasure) or at withdrawal; at most 395 days after receipt. |
| Persons | `identity.profile` (new, medium, pseudonymous, derived) | Deleted when no link or key remains, or 395 days after `last_evidence_at`. |
| Handoff digests | `credential.token_digest` | 1 day after expiry or consumption. |
| Merge ledger | `identity.correction` (new, medium, pseudonymous) | D12 recommendation: retain an active edge while reversible. Retain its closed ledger entries for 2 years after reversal, or until earlier person erasure. |
| Change feed | `identity.change` (new, low, pseudonymous) | 30 days. |
| Tombstones | `deletion.tombstone` | Workspace lifetime (D-025). |

Expiry runs under the client lock in bounded batches. Expiring a single event updates the affected journey and preserves links for other live events on the subject. Expiring the subject drops its evidence and orphaned identity rows. Keep active merge evidence while its persons exist. Grant the lifecycle role the specific deletes, revision updates and feed inserts needed. A lifecycle run may never delete a live workspace's matching secret.

## 13. Example API responses (synthetic, Outcome A)

Profile:

```json
{
  "id": "00000000-0000-4000-8000-000000000101",
  "status": "active",
  "version": 1,
  "stage": "lead",
  "flags": ["purchase_reported"],
  "first_seen_at": "2026-11-02T09:00:06.412Z",
  "last_seen_at": "2026-11-05T20:31:45.020Z",
  "keys": [
    {"kind": "email", "normalizer": "email:v1", "method": "email_code", "verified_at": "2026-11-02T09:05:09Z", "contested": false},
    {"kind": "customer_ref", "normalizer": "ref:v1", "method": "account_login", "verified_at": "2026-11-05T20:12:28Z", "contested": false}
  ],
  "device_subjects": 3,
  "touchpoints": 6,
  "first_touch": {"campaign": "spring-25", "content": "ig-post-0147", "link_id": "00000000-0000-4000-8000-000000000201"},
  "last_touch": {"campaign": null, "content": null, "link_id": null},
  "journey_revision": 5,
  "review_items": 0
}
```

Timeline (first and last entries):

```json
{
  "subject_id": "00000000-0000-4000-8000-000000000101",
  "journey_revision": 5,
  "entries": [
    {
      "event_id": "00000000-0000-4000-8000-000000000301",
      "type": "page_view",
      "occurred_at": "2026-11-02T09:00:06.100Z",
      "received_at": "2026-11-02T09:00:06.412Z",
      "late": false,
      "trust": "browser",
      "revision": 1,
      "provenance": {"link_id": "00000000-0000-4000-8000-000000000201", "campaign": "spring-25", "content": "ig-post-0147", "path": "/offer"},
      "evidence": {"device_subject": "phone-session-1", "assertion_id": "00000000-0000-4000-8000-000000000401", "keys": ["email"], "methods": ["email_code"]}
    },
    {
      "event_id": "00000000-0000-4000-8000-000000000306",
      "type": "purchase_signal",
      "occurred_at": "2026-11-05T20:31:44.900Z",
      "received_at": "2026-11-05T20:31:45.020Z",
      "late": false,
      "trust": "trusted_sender",
      "revision": 1,
      "provenance": {"link_id": null, "campaign": null, "content": null, "path": null},
      "evidence": {"device_subject": "server-subject-1", "assertion_id": "00000000-0000-4000-8000-000000000402", "keys": ["email"], "methods": ["email_code"]},
      "note": "Reported purchase; not verified sale evidence."
    }
  ],
  "next_cursor": null
}
```

`device_subject` is a per-person display alias, not the collection subject ID or token. Field names are proposals for 018 review. No screen, component or visual prototype is part of this specification.

## 14. Implementation slices (after approval)

| Slice | Content | Depends on |
|---|---|---|
| 006-A | Migration 0009, models, data-policy registry, per-client key custody, keys/normalizers (`email:v1`, `phone:v1`, `ref:v1`), tombstone and audit extensions, grants. | D1–D12 (schema dependencies in the packet) |
| 006-B | Handoff route, assertion service and API, matching rules R1-R5, segments, consent (E3), withdrawal/expiry/lifecycle integration, diagnostics. | 006-A, D2/D5/D6/D7 |
| 006-C | Profile, timeline, lead inbox and review read APIs with permissions. | 006-B, D8/D9/D13 |
| 006-D | Merge, unmerge, erasure by person/identifier, change feed. | 006-C, D10 |
| 006-E | Tracker `identityHandoff(challenge)` and `restart()`, Node and Chromium/Firefox tests, end-to-end journey of section 2 on loopback with a disposable database. | 006-B for tracker tests, 006-C for the profile/timeline journey |

Each slice is committed locally, verified with the relevant rows of the verification matrix, and presented for review. Push, PR, native migration and real intake keep their separate gates.

## 15. Out of scope and limitations

- Fingerprinting, IP or user-agent matching, probabilistic matching and cross-client identity graphs.
- Platform-run verification messages to visitors; webhook and import assertions (015); provider match keys (014).
- Full CRM (assignment, notes, pipelines), React screens and visual design (018), and reporting (016).
- Verified sale evidence and revenue (007), and attribution models (008).
- Market-specific consent profiles (Q-003) and production key custody (020).
- The design cannot detect recycled phone numbers or shared mailboxes before a conflict appears; the first assertion of a shared identifier is attributed to its first verifier until a conflict is observed.
