# Specification 006 design — Lead identity and customer journey

Status: **proposal, revision 3** (2026-11-11). Revision 2 corrected findings R006-01 to R006-08 from the review of the published D-039 preparation at `b9801de`. Revision 3 corrects R006-09 to R006-14 from the second review and closes the remaining gaps in the first eight (D-041). The [review register](preparation-review.md#finding-coverage) maps each finding to its sections and acceptance cases. Nothing in this document is approved for implementation. Schema, dependencies, policies and values below become binding only through a recorded owner decision on the [decision packet](decision-packet.md). Baseline and inherited contracts: [entry review](entry-review.md). Test plan: [verification matrix](verification-matrix.md).

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
| 09:05:10 | Phone | Bloom's verified form session supplies a fresh random challenge. The page passes it to `tracker.identityHandoff(challenge)` and posts the returned code to the same backend session. | P is browser-issued (section 8.1). Handoff H1 stores digests of its code and challenge for P and the identity grant receipt in force. It expires after 10 minutes and permits one application. |
| 09:05:11 | Bloom backend | `POST .../identity-assertions` with Bloom's ingest key: assertion `A1`, handoff H1 and the challenge from its own verified session, identifier `email = mona@example.test`, method `email_code`, verified at 09:05:09. | New person **S1**. Identity key **K1** (keyed email) owned by S1. Link P->S1 via A1. P's events received after 09:00:05.200 now belong to S1. Bloom's backend receives only the generic `accepted` acknowledgement (section 12.2). |
| 09:05:12 | Bloom backend | Bloom's backend recorded Mona's form consent through the server consent API (server-issued collection subject **Q**, `attribution` and `identity_link`), sends a trusted `lead_signal` `e3` (`consultation_request`) and then assertion `A2` (subject token of Q and the current `identity_link` receipt, same email, `email_code`). | `e3`: server, trust rank 2. Link Q->S1 via A2. S1 becomes a **lead**. |
| 11-05 20:10:00 | Laptop | Mona types `bloom.example.test` directly. Banner grants the three purposes. | Browser-issued collection subject **L**. Page view `e4` without link or campaign. |
| 20:12:30 | Laptop | She signs in to Bloom's patient portal (account `cust-1042`). Her portal session issues a new challenge, the page obtains handoff H3 for L with it, and Bloom's backend asserts `A3` with H3 and that session's challenge: `customer_ref = cust-1042` (method `account_login`) and `email = mona@example.test` (method `account_verified_email`). | K1 is already owned by S1, and the new key **K2** (customer_ref) is co-asserted with it, so K2 joins S1. Link L->S1 via A3. |
| 20:14:02 | Laptop | Page view `e5` (`/pricing`). | `e5` rank 1, assigned to S1 through L. |
| 20:31:45 | Bloom backend | Bloom's server reports a payment as `purchase_signal` `e6` on Q. | `e6` rank 2. S1 is flagged `purchase_reported`. S1 is **not** a customer until specification 007 records verified sale evidence. |

The evidence chain for every interaction in S1's timeline:

| Event | Device subject | Link | Evidence behind the link | Consent that permitted it |
|---|---|---|---|---|
| e1, e2 | P | P->S1 | A1: Bloom's server asserted K1 after an email code entered **on the phone**, delivered through handoff H1 issued to P | analytics (collection); identity_link on P (handoff and link) |
| e3, e6 | Q | Q->S1 | A2: Bloom's server asserted K1 for its own server subject Q | attribution (collection); identity_link on Q |
| e4, e5 | L | L->S1 | A3: Bloom's server asserted K2 and K1 after a portal sign-in **on the laptop**, delivered through handoff H3 issued to L | analytics; identity_link on L |

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
| **IdentityLink** (new) | Evidence that one collection subject's interactions belong to one person for a time interval (an owned segment), or that they followed a verified session whose owner is ambiguous (an ambiguous segment, section 4.4). | New `identity_links`, created only from an identity assertion. References the collection subject, the person or the candidate persons, and the assertion. |
| **Identity assertion** (new evidence record) | A trusted sender's statement that, on one collection subject, the person proved control of the listed identifiers. | New `identity_assertions`; sender idempotency ID like 004 `event_id`. |
| **Touchpoint** (derived) | One collected event as it appears in a person's journey: the event, the link that assigns it, and the event's provenance. | Read model computed from `collected_events` (event ID, type, channel, trust rank, `occurred_at`, `first_received_at`, `link_id` -> managed link, campaign and content reference) and `identity_links`. No event payload is copied. |
| **Agency user** (existing) | A platform login (`users`, `external_identities`). | Entirely separate. Agency users never become persons, and a visitor's identifier is never compared with platform accounts. Google sign-in (D-022) identifies agency users only. |
| **Client workspace** (existing) | Tenant boundary. | Every new table has composite `(agency_id, client_id)` foreign keys, as in 004/005. |
| **Event ID / link ID** (existing) | Sender idempotency ID of an event; managed link reference. | Touchpoints are keyed by `collected_events.id` and display `event_id`. `link_id` provides campaign and content provenance and is never identity evidence. |

## 4. Evidence and matching rules

### 4.1 Evidence sources

| Source | Who may submit | What counts as verification | May link automatically? |
|---|---|---|---|
| **Trusted identity assertion** with a browser handoff | An ingest key granted for the client. | The client backend binds its verified form or login session to the handoff of a browser-issued collection subject (sections 8 and 8.1). For email, accept `email_code`, `email_link` or `account_verified_email`. For phone, accept `phone_code` or `account_verified_phone`. For `customer_ref`, accept `account_login`. `staff_verified` requires the client's explicit attestation for the named kind. Each `verified_at` must be within 30 days and at most 5 minutes ahead of server receipt (D2). | Yes, subject to section 4.2. |
| **Trusted identity assertion** for a server-held collection subject | Same ingest key scope, direct token of a subject created by the server consent API. | Same method and freshness checks. Validate the stored issuance channel (section 8.1) and require the current server-recorded `identity_link` grant receipt for this subject. The sender obtains the receipt from the server consent response. For a multi-purpose grant, map the returned receipts in sorted purpose order as 004 records them. A later server consent update on a browser token cannot change its issuance channel. | Yes, subject to section 4.2. |
| Signed webhook assertion | Generic HMAC webhook sources (004). | Same rules. | **Not in 006 v1** (proposed for 015 with named integrations). |
| Browser form value (email, phone, name) | Public browser. | None. | **Never.** 006 keeps the 004 form classes unchanged; contact values are not collected by the tracker (D9). |
| Managed link or UTM parameters (`ts_link`) | Public browser. | None; shared by every recipient. | **Never.** Provenance only. |
| Device, IP address, user agent, fingerprint, timing | — | — | **Never collected or used.** Excluded by the specification. |
| CSV, CRM or connector import | 015/009. | E6 rules. | Not in 006. |
| Manual merge | Agency Owner/Admin. | Human judgement with a closed reason code. | Manual, audited and reversible (section 10). |
| Platform-run verification (Tracking System emailing or texting a code to the visitor) | — | — | **Not proposed.** It would be outbound contact with client customers, which needs its own approval. |

"Verified" therefore always means *verified by the client's own system and asserted by the client's trusted backend*. Tracking System records the declared method and time. It never claims independent verification.

### 4.2 Deterministic matching within one client

Processing one assertion follows these steps in this order. Step 1 runs before the client privacy lock and steps 2–10 inside it (section 12.4). Section 12.2 defines the external response of each step.

1. **Authenticate and validate.** Authenticate the ingest credential and its live client grant (`events:write`). Validate the request syntax: a UUID assertion ID, exactly one proof form, 1–3 identifiers with at most one per kind, an allowed method for each kind and a well-formed `verified_at`. Validate and canonicalize every identifier with its versioned normalizer (section 5). One invalid identifier rejects the whole assertion (no partial evidence). These checks depend only on the request, so their result does not depend on whether the assertion ID was used before.
2. **Lock and derive keys.** Take the client lock, read the database clock, recheck live sender scope and load the client's matching secret. Compute every IdentityKey and the keyed request fingerprint over the assertion ID, credential ID, canonical evidence, proof digests and verification times.
3. **Recognize retries before proof.** If an `assertion_id` replay tombstone matches (section 7.3), compare the fingerprint with the `assertion_request` tombstones of that deletion. If a receipt `(client_id, assertion_id)` exists, compare the fingerprint with the receipt. An equal fingerprint returns the duplicate acknowledgement and a different one returns a conflict. Neither consumes proof or writes a receipt, key, link, revision or change record, so an exact retry also succeeds after the handoff expired or was purged and after erasure.
4. **Check freshness.** Check each `verified_at` against the locked database clock (30 days back, 5 minutes ahead; D2).
5. **Resolve new proof.** Resolve either a live, unused handoff whose code and challenge digests both match and whose collection subject is browser-issued, or the direct token of a server-issued collection subject (section 8.1).
6. **Require current consent.** Require `identity_link` currently granted on that collection subject (E3, section 6). For a direct-token assertion its receipt must equal the current grant. For a handoff the receipt captured at issuance must equal the current grant. A fresh grant cannot reactivate old proof. Steps 5 and 6 share one external rejection.
7. **Check identity tombstones.** Evaluate every key against the `identity_key` tombstones with `deletion.admission`, using the receipt time of the subject's current identity grant. A suppressed assertion consumes its proof and stores a minimal receipt with the internal reason (`no_consent_after_deletion` or `subject_objected`), but writes no key, link, person, revision or change record. Externally it is acknowledged like any accepted assertion (section 12.2).
8. **Match.** Classify the asserted keys by current owner. Apply the R5 filter first:
   - **R1 (new person).** No key is owned or contested -> create a person, assign every key to it, and link the collection subject.
   - **R2 (one owner).** At least one key is owned, every owned key belongs to the same person (after resolving merges), any remaining eligible keys are new, and neither R3 nor R2-P applies -> assign the new keys to that person and link the collection subject. Keys asserted **together in one assertion** belong together because the sender stated that one person proved control of all of them. This is the only way two keys join automatically.
   - **R2-P (phone is a weak anchor).** Phone numbers are recycled and shared more often than email addresses or account IDs. If the only owned keys in the assertion are phones and it brings a new email or `customer_ref`, the phones become **contested**, and the new keys form a new person (or follow R3), with outcome `contested_identifier`. A new phone may still join a person anchored by an email, a `customer_ref` or another phone.
   - **R3 (customer reference is authoritative).** A person holds at most one `customer_ref`, the client's own account ID. R3 applies when the assertion carries a `customer_ref` and either (a) it is owned by X while another asserted key is owned by a different person, or (b) it is new while the owner of another asserted key already holds a different `customer_ref`. The `customer_ref` then decides: link to X, or to a new person created for the new `customer_ref`. Every asserted key owned by a different person becomes **contested** (owner cleared), with outcome `contested_identifier`. A new `customer_ref` joins an existing person only when that person has none (Mona's A3 in section 2.1).
   - **R4 (conflict).** Owned keys point to two or more different persons and no `customer_ref` decides -> **no link and no merge**. The assertion is stored with outcome `ambiguous` and candidate person IDs for Owner/Admin review (section 9.4), and it opens an ambiguous segment on the collection subject (section 4.4).
   - **R5 (contested evidence).** Exclude contested keys from ownership decisions. Keep their contested status and record that they were presented. With no remaining key, return `ambiguous`, naming as candidates the persons whose recorded evidence presented those contested keys. With only new keys, run R1 on those keys. With owned keys, resolve R2/R2-P/R3/R4 using only the eligible keys. An undecidable combination of multiple owners and a new `customer_ref` is ambiguous unless R3 identifies a distinct account without assigning any other person's owned keys.
9. **Apply the device rule.** Apply section 4.4 to the collection subject's existing segments and its identity floor.
10. **Commit evidence.** Consume the handoff, write the receipt, keys, links and segment bounds, increment the journey revision of each affected person and visible merge root, and append change records (section 11). The external response is the generic acknowledgement whatever the internal outcome.

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

A collection subject can carry evidence for several persons over time. Its evidence forms **segments** ordered by assertion receipt time. An **owned segment** is a link to one person. An **ambiguous segment** records an ambiguous assertion (R4, or R5 without an eligible key) and its candidate persons. It assigns events to nobody, but it records that they followed a different verified session.

- Store each segment's inclusive `eligible_from` and exclusive `eligible_until`. Close the open segment at the end of its uninterrupted identity consent, at the receipt of an assertion for a different original owner and at an ambiguous assertion. An ambiguous result therefore ends the previous person's segment even though it creates no owned link.
- Persist a per-collection-subject **identity floor**, `identity_floor_at`, that only moves forward. Raise it to the closing time whenever a segment closes (switch, ambiguous assertion, end of consent, W1) and to the deletion time whenever an erasure removes a segment of that subject. Also persist `identity_shared_at` when the subject first records a second original owner or an ambiguous segment. It is never cleared, even after the other person's evidence is erased.
- Close any open segment before computing a new link's start. A new link reaches back to the start of the current identity grant (D6) only when the floor is unset or precedes that grant start, that is, when no segment closure or erasure occurred on the subject during the current grant. Otherwise it starts at its own assertion receipt. When the subject becomes shared, shorten the first owner's retrospective portion to that owner's first assertion receipt, so pre-identification events on a shared device belong to nobody.
- Erasure, expiry of evidence, a merge or an unmerge never extends a segment or lowers the floor. Events received in a closed, ambiguous or erased interval stay unassigned permanently, whoever asserts on the subject later: the remaining person, the erased person after re-registration, or anyone else. Later links cannot bridge a consent gap or a period of ambiguity.
- An event whose `first_received_at` falls in one person's segment while its client-claimed `occurred_at` falls in another person's segment or a known unassigned gap is **ambiguous** (for example, a queued event of the previous user delivered after the switch). Client time can only withhold an association, never create one.
- A new assertion for the same original owner continues a segment only while consent and evidence are uninterrupted. Use server receipt order for boundaries. An event indistinguishable from a switch at the database clock's precision stays ambiguous.

Example: Sara signs in on a shared clinic tablet (collection subject T) at 10:00 and leaves; Omar signs in on the same browser session at 10:20. Events received 10:00-10:20 -> Sara; events received from 10:20 -> Omar; events received before 10:00 -> ambiguous (T is shared); an event received at 10:20:30 but claiming 10:19:50 -> ambiguous. Omar's assertion closes Sara's segment, raises T's floor to 10:20 and sets `identity_shared_at`. If Omar is erased at 11:00, the floor moves to 11:00. A later assertion by Sara at 11:30 starts a new segment at 11:30, so no event received between 10:20 and 11:30 can reach her.

**Event classes for one person.** On a shared collection subject each event has one of three classes for a person X:

| Class for X | Events | Use |
|---|---|---|
| Confirmed | Assigned to an owned segment of X: received in it, with a claimed time that falls in no other segment or known gap. | X's journey; erased with X. |
| Excluded | Received and claimed in another person's owned segment, or in an ambiguous segment whose candidates do not include X. | Never in X's journey; survives X's erasure. |
| Unresolved | Every other event on the subject: unattributed periods (before identification, consent gaps, after a closure or an erasure), ambiguous segments that name X, and late events crossing a boundary of X's segment. | In nobody's journey; requires clarification before X's erasure completes (section 7.2). |

A subject that has evidence for X and no `identity_shared_at` is **exclusive** to X, and all of its events belong to X's device history.

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
| phone | `phone:v1` (recommended, D4) | Trim ASCII spaces (U+0020) only. The whole remaining input must then match `^(\+\|00)[1-9][0-9 ()-]*$` in ASCII and contain 8–15 digits after the prefix and formatting are removed, so the first country-code digit is 1–9. Reject letters, extension text, Unicode digits (for example Arabic-Indic digits, which the sender must convert), Unicode spaces, tabs and every other character. Only then call the 003 helper, without a default country. Input of ASCII digits and formatting without a prefix returns `phone_country_required`; every other invalid input returns `identifier_invalid`. |
| customer_ref | `ref:v1` | Exact client account ID, 1-128 characters of `[A-Za-z0-9_.:-]`, case-sensitive, no normalization. |

The validation runs before the 003 helper because the helper keeps every character for which Python's `str.isdigit()` is true, removes all others and strips Unicode whitespace. These are the actual outputs of the merged helper (`canonical_identifier("phone", value)` at `c251e20`, project virtual environment, fictional digits) and the proposed `phone:v1` result:

| Input (ASCII escapes) | Helper output | `phone:v1` result |
|---|---|---|
| `+20 10 0000 0101` | `+201000000101` | Accepted as `+201000000101`. |
| `+20oops10 0000 0101` | `+201000000101` | `identifier_invalid` (letters); the helper would match the valid number. |
| `+20 10 0000 0101 ext 9` | `+2010000001019` | `identifier_invalid` (extension); the helper would produce a different, possibly real, number. |
| `+٢٠ 10 0000 0101` | `+٢٠1000000101` | `identifier_invalid` (non-ASCII digits). |
| `+0020 10 0000 0101` | `+00201000000101` | `identifier_invalid` (country code cannot start with 0). |
| `\xa0+20 10 0000 0101` | `+201000000101` | `identifier_invalid` (no-break space is not trimmed). |

Compute `subject_key(client_key, client_id, normalizer_label, canonical_value)`. The label separates versions even when two normalizers return identical strings. In v1 the per-client matching secret stays stable for the workspace lifetime. Rewrapping it preserves its bytes. Before introducing any new matching version, assertion and erasure must check tombstone candidates under every retained applicable version. Losing an old key or a required normalizer must fail closed. Because a rewrap preserves the secret, existing keys and the objections recorded on `identity_key` tombstones still match after it (I9).

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
| Withdrawal or explicit denial of `identity_link` on a collection subject | Apply W1 on every consent write path in the same transaction. Remove its owned and ambiguous segments, assertions and handoffs, raise its floor to the withdrawal time, then remove keys and persons left without evidence. Events retain their independent collection policy. |
| Expiry of `identity_link` | End the segment at grant expiry even if no worker runs. The next write under the client lock persists that closure and raises the floor to the expiry time before it computes any new link. Only earlier assignments remain visible. A later grant starts a separate eligibility period and requires a new assertion. A grant renewed before expiry can extend an uninterrupted period. |
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
- The write API never discloses identity history. For a well-formed, authenticated and proven assertion, neither the HTTP status nor the body reveals whether an identifier had an owner, was contested, was erased or was the subject of an objection (section 12.2). Exact internal reasons stay in authorized internal evidence: assertion receipts, aggregate diagnostics for managers and the Owner/Admin review queue.

### 7.2 What erasure removes

Erasure uses the existing 003 request states in two stages:

1. **Resolve the target before any destructive write.** Resolve the requested original person. For a contested identifier, a person in an active merge, or evidence shared across the proposed targets, move the request from `verifying` to `paused_for_clarification` and delete nothing. Resolve or reverse an erroneous merge first. A merge pointer alone cannot authorize erasing another original person's history.
2. **Classify every collection subject of the resolved person** with the event classes of section 4.4. A single confirmed link does not make a subject exclusive: exclusivity also requires that the subject never recorded another original owner or an ambiguous segment (`identity_shared_at` unset).

The authorized deletion runs in one transaction under the agency lock followed by the client privacy lock.

| Store | Action |
|---|---|
| `identity_subjects` | Delete the resolved original person after checking its evidence scope. Record its final revision and an `erased` change record first (section 11). |
| `identity_keys` | Delete its owned keys with `identity_key` tombstones. A contested key the person also presented loses this person's evidence. If nothing else references it, it is deleted. |
| `identity_links`, `identity_assertions`, `identity_handoffs` | Delete the person's owned segments, assertions and handoffs, with `assertion_id` and `assertion_request` tombstones. Remove the person from the candidate lists of ambiguous segments and assertions. A segment left with one candidate stays ambiguous, because erasure is never evidence for the remaining candidate. |
| Collection subject exclusive to this person | Extend the internal 004 erasure helper to accept an already scoped subject row, including a subject with zero events. Create the `subject_token` tombstone from its stored digest and tombstone every retained event ID. Keep the public 004 lookup inputs unchanged. |
| Shared collection subject | Delete the person's confirmed events with `event_id` tombstones. Keep excluded events, other persons' segments and their bounds, and the token, which receives no `subject_token` tombstone and stays usable. Raise the floor to the deletion time. Hold unresolved events: they stay outside every journey and below the floor, and the request's `unresolved_events` target stays `pending`. |
| `identity_merges` | Delete closed ledger rows naming the person. An active edge pauses the request in stage 1. |
| `audit_events` | Kept: IDs and action codes only (existing policy). |
| Derived data in 007/008/014/016 | Notified through the change feed (section 11); each consumer applies its own erasure rule. |

**Request status.** Without unresolved events the request completes in the same transaction. Otherwise it moves from `in_progress` to `on_hold` with `unresolved_events` pending, so it cannot report completion. An Owner/Admin then chooses for that request either to erase the held events with `event_id` tombstones or to retain them as anonymous device events. Either choice is audited and completes the request. D7 presents automatic erasure of unresolved events as the alternative.

Example (synthetic): tablet T has one confirmed segment for Sara, 10:00–10:20, followed by an ambiguous segment whose candidates are Omar and Ali. Erasing Sara deletes the events received 10:00–10:20 with `event_id` tombstones. It keeps every event of the Omar/Ali interval, because that evidence excludes her. It holds the events received before 10:00 and the event received at 10:20:30 that claims 10:19:50. T keeps collecting under its token, and Sara's keys and assertion IDs are tombstoned. The request stays `on_hold` until the held events are decided.

A shared identifier can appear in evidence for several original people. Apply an identity-key tombstone to an exclusive key. For a contested key retain the ambiguity and hold any unresolved objection scope for clarification. No deletion request can report completion while an affected target is unresolved. The existing 004 token-holder route erases that collection subject, its events and its identity evidence, and removes persons left without evidence. On a shared subject that includes other persons' events on that session, as in 004, because possession of the token is the verification; their journeys receive change records and their other devices are unaffected. It creates no identity-key tombstone and never acquires authority over other devices through a person link.

### 7.3 Minimal replay protection

D-025 tombstones are reused with three additional match types (schema change in D11):

| Match type | Tombstone value | Blocks |
|---|---|---|
| `identity_key` | The hex IdentityKey (per-client pseudonym) under the tombstone key | A later assertion of the same identifier, unless the asserting collection subject's `identity_link` consent was received after the deletion and the person did not object (existing `deletion.admission`). |
| `assertion_id` | The sender's assertion ID | Retries or delayed imports of the exact assertions that existed before erasure. |
| `assertion_request` | The keyed request fingerprint of that assertion (section 4.2, step 2) | Nothing by itself. It lets the retry check distinguish an exact retry from a changed request after the receipt is gone, so the external idempotency response is the same as for a live receipt. |
| `subject_token`, `event_id` (existing) | As in 004 | Events and tokens of erased collection subjects. |

The pseudonym is used as the tombstone value so that erasure by profile ID works without the raw identifier. Tombstones never store raw values, and per-client keys live as long as the workspace, like the tombstones. A delayed import or retry therefore cannot rebuild an erased link. A genuinely new consent after the deletion can create a new, unconnected person, which is what D-025 decision 10 requires. Carry `objected` onto the exclusive identity-key tombstones. Exact assertion IDs are unconditional replay keys. When a lookup is ambiguous, return `paused_for_clarification` before deleting any rows. A tombstone outcome is internal evidence only: the write API acknowledges a suppressed or replayed assertion exactly as it would a live one (section 12.2).

## 8. Tracker additions (specification 005 package)

| API | Behavior |
|---|---|
| `identityHandoff(challenge)` | The client's backend supplies a fresh random challenge bound to the current form or login transaction. Include it with the subject token in the request body. Check effective `identity_link` immediately before sending and before returning the code to the same host session. Return `{status: "issued", code, expires_at}` or `blocked`/`unavailable`. Keep both values out of URLs, logs and persistent browser storage. |
| `restart()` | Immediately invalidate the old local session, clear its persisted token, permissions and queue, and cancel timers and pending transmissions where possible. Ignore late responses, including subject creation and issued codes. No queued request or retry may start for the old session. The next explicit grant creates a new subject. Server consent remains in its recorded state. |

The client backend generates the challenge from at least 128 random bits for one verified transaction and encodes it as 22–128 base64url characters. The collector stores only its SHA-256 digest. `(client_id, challenge_digest)` is unique, so a reused challenge cannot obtain a second handoff and the route answers `unavailable`. The client backend invalidates its pending challenge on logout or account switch. On redemption the backend supplies the challenge from its own verified transaction state. The collector requires matching code and challenge digests, the issued client and subject, live consent and unexpired proof. The handoff correlates a browser with the transaction. The backend supplies the verification evidence. In 004 the 12-month limit applies to a grant. The subject token itself has no fixed 12-month expiry.

### 8.1 Proof route by issuance channel

Migration 0009 records an immutable `issuance_channel` on every collection subject. The public consent route creates `browser` subjects and the server consent API creates `server` subjects. Rows created before 0009 receive `unknown`, because nothing in a legacy row, including its later consent updates, establishes its original channel. A later consent update through either API never changes the channel.

| Issuance channel | Browser handoff (`identityHandoff(challenge)`, then `{handoff, challenge}`) | Direct-token assertion (`{subject_token, identity_consent_receipt_id}`) |
|---|---|---|
| `browser` | **Permitted.** Proof: effective `identity_link` at issuance and redemption, the receipt captured at issuance equal to the current grant, matching code and challenge digests, unexpired and unused. Outcome: matching proceeds (section 4.2). | **Rejected** as `proof_invalid`, even with a correct receipt. A browser token is not shared with the client backend, so a backend presenting one is outside the protocol. No proof is consumed. |
| `server` | **Rejected.** The public route returns the same `unavailable` response as for an unknown token and issues nothing, so it cannot become an alternative route for a server-held token. | **Permitted.** Proof: the token of a live server-issued subject and the current `identity_link` grant receipt. Outcome: matching proceeds. |
| `unknown` (legacy, recommended D3/D11) | **Rejected** with `unavailable`. | **Rejected** as `proof_invalid`. |

Every cell leaves ordinary 004/005 consent, event collection and token-holder erasure unchanged. For legacy rows, the recommendation accepts that a subject created before 0009 can never be linked. Browser visitors obtain a new browser-issued subject at their next explicit grant after the local token lifetime of at most 24 hours (005 D6). Server senders create a new server-issued subject with fresh explicit consent. Because no real customer intake precedes 0009, the cost is limited to development data unless a pilot starts before the migration. The alternative (D3) permits the browser handoff for `unknown` rows. It keeps current browser sessions linkable, but the holder of a legacy server-held token could then link it through the public route without server-issuance proof. Because a legacy row's channel can never be established, that exposure could not later be closed for individual rows.

## 9. Profile, timeline and lead inbox read models

### 9.1 Profile

Fields include person ID, the correction `version`, status (`active`, or `merged` with `merged_into`), stage and flags (section 4.5), `first_seen_at` and `last_seen_at` (server receipt of the first and last assigned event), key summary (kind, normalizer version, verification method and time, `contested` flag; **never the value or a mask**, D9), device subject count, touchpoint count, first-touch and last-touch provenance (campaign, content reference, link), `journey_revision`, and pending review count. Manager lookup of an original merged ID also returns that member's ID and version for reversal.

The two counters answer different questions:

| Counter | Starts at | Changes when | Unchanged by |
|---|---|---|---|
| `version` (optimistic concurrency for corrections) | 1 when the person is created | Each successful merge or reversal increments **both** participants' versions atomically. Lifecycle closure of an active edge increments the remaining participant (section 10.1). | Linking, events, failed operations and exact operation retries. |
| `journey_revision` (downstream change signal) | 0 before the first link | Each committed transaction that changes the person's visible journey increments it once (section 11). | Exact retries, rejected events and requests that change nothing. |

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

`GET .../identity/review` (Owner/Admin) lists ambiguous assertions and segments, contested keys (`shared` or `unmerged`), links left ambiguous by an unmerge or an edge closure, and erasure requests that are `paused_for_clarification` or `on_hold`, with candidate person IDs and reason codes. Identity items are resolved through new evidence or a manual merge, and erasure requests through the resolution operation (section 12.2).

## 10. Merge and unmerge

### 10.1 Rules

- Only Owner/Admin may merge or unmerge, with a closed reason code (`same_person_confirmed_by_client`, `duplicate_account`, `data_correction`) and the expected `version` of each person (optimistic concurrency; a stale version returns 409).
- **Pointer merge (D10 recommendation).** Permit disjoint pairs in v1. Both people must be active, distinct, in the same client and outside any active merge. Persist the edge and original owners. Reject a self-merge, chain or overlapping pair before writing. This gives a single reversal target for evidence spanning both sides.
- Every association stays anchored to its **original evidence**: links name the person that owned the asserted key at assertion time, never the merge root. The one exception is evidence that depends on both sides of an active merge (section 10.3). Such links and keys record the merge ID.
- Reverse only the currently active edge named in the request, under both original participants' expected versions. Clear its pointer, restore original-owner reads and move every link and key that records this merge ID to review (section 10.3). A new operation cannot reverse an already reversed or closed edge.
- A successful merge or reversal increments both participants' `version` and `journey_revision` in one transaction (section 9.1). A failed operation changes neither. An exact authorized retry, with the same `operation_id`, actor and request content, returns the recorded result before any version check and changes nothing. A new operation with pre-operation versions returns 409.
- An active edge stays reversible regardless of its age while both participants exist (D12). Erasure of a participant pauses at the edge (section 7.2). If lifecycle expiry removes a participant's last link and key, the same transaction closes the edge with reason `participant_removed`, moves its merge-dependent links and keys to review as a reversal would, increments the remaining participant's `version` and `journey_revision`, and appends change records.
- Both operations are idempotent by `operation_id`, ledgered in `identity_merges`, audited (`identity.merged`, `identity.unmerged`) and recorded in the change feed.

### 10.2 Worked mistaken merge (synthetic)

Before (client `bloom`):

| Person | Keys | Devices | Touchpoints |
|---|---|---|---|
| S7 (Ali) | email `ali@example.test` (email_code) | D1 phone | t1 page view via campaign `autumn-25` (rank 1); t2 trusted lead_signal (rank 2) |
| S8 (Aliya) | phone `+20 10 0000 0202` (phone_code) | D2 laptop | t3 page view (rank 1); t4 browser lead_signal (rank 1) |

Both persons have `version` 1. At 10:00 an Admin merges S8 into S7 (merge M1) with reason `same_person_confirmed_by_client`; this is a mistake. Both versions become 2 and both journey revisions increase by one. The merged timeline under S7 shows t1-t4, each still labelled with its device and key, so a reviewer can see two independent evidence chains.

During the merged period (10:00-12:00):
- t5: D2 sends a page view -> assigned through D2's link, whose evidence is S8's phone key; displayed under root S7.
- t6/t7: a new tablet D4 is asserted with **both** `ali@example.test` and `+20 10 0000 0202`, plus a new email K, `household@example.test` (`email_code`). Normally that is a conflict (R4). Because both owned keys currently resolve to root S7, the engine accepts it. It records the link with `merge_id = M1` and the original owners {S7, S8}. K is created for root S7 with the same `merge_id` and original owners, because its only evidence spans both sides. t7 is a page view on D4.
- t8: a third device D5 asserts **only** K. K is merge-dependent, so the link D5 -> S7 inherits `merge_id = M1` and the original owners {S7, S8}. t8 is a page view on D5.
- t9: device D6 asserts only `ali@example.test`. Its evidence names S7 alone, so its link records no merge ID. t9 is a page view on D6.

Each of t5-t8 increments the journey revisions of S7 (visible root) and S8 (original owner). t9 increments S7's only.

At 12:00 the Admin reverses M1 with expected versions 2 and 2. Both versions become 3, and both journey revisions increase by one. After:

| Person | Touchpoints |
|---|---|
| S7 | t1, t2: exactly as before the merge; t9: D6's evidence is independent of S8 |
| S8 | t3, t4, t5: t5 follows its evidence (D2 -> S8's phone key) |
| Review queue | Links of D4 and D5 (`merge_id = M1`): **ambiguous**, candidates S7 and S8. Key K: **contested** (`contested_reason = unmerged`). t7 and t8 are assigned to neither person. |

D4 and D5 stay out of both timelines until independent evidence arrives. Because K is contested, an assertion of K alone stays ambiguous (R5). An assertion with an eligible key of exactly one person starts a new segment at its own receipt, so t7 and t8 remain unassigned (section 4.4). An Owner/Admin may also merge deliberately. A new merge or reversal that presents versions 1 or 2 returns 409. An exact retry of the original M1 merge request returns its recorded result and changes nothing.

No event or assertion was rewritten at any point, and no pre-existing key or link changed. The reversal changed only the status of the merge-dependent key K and of the links of D4 and D5. The unmerge response lists the reverted merge, both new versions, the restored persons, and the links and keys moved to review.

### 10.3 Ownership during a merged period

| Created during the merge | Recorded merge ID | After unmerge |
|---|---|---|
| Link whose keys all have one original owner | None | Stays with that owner. |
| New key co-asserted with keys of one original owner | None | Owned by that owner. |
| Link or key whose evidence names owners on both sides | The merge ID | Link ambiguous, key contested; excluded from both timelines and listed in the review queue. |
| Link or key anchored only by merge-dependent keys (D5 in section 10.2) | Inherited | Link ambiguous, key contested, as above. |
| Link or key whose evidence combines merge-dependent keys with owned keys of exactly one original owner | Inherited | Stays with that owner, as R5 would decide without the merge-dependent keys. |
| Derived results (008 allocations, 016 caches) computed under the merged root | — | Invalidated through the change feed and recomputed. |

**Dependency recording.** A key or link created during an active merge records the merge ID when its anchoring evidence spans both original participants or includes a key that already records that merge ID. V1 merges are disjoint pairs, and owned keys that resolve to different roots make an assertion ambiguous, so an item depends on at most one merge. On reversal, select the keys and links with that merge ID under the client lock. Re-evaluate each with R5 over the evidence that created it, treating every key with that merge ID as unavailable. An item whose remaining owned keys name exactly one original owner stays with that owner. Otherwise a key becomes contested with `contested_reason = unmerged`, and a link becomes ambiguous with both participants as candidates. The selection is an indexed lookup, because each dependency is recorded when its item is created.

## 11. Recalculation and handoff to 007/008

Start each person's revision at zero before its first link. A committed change to a visible journey increments the revision once per affected journey per transaction for each affected person and visible root and appends `(client, seq, person_id, journey_revision, kind, time)` in the same transaction. Kinds include `linked`, `unlinked`, `contested`, `merged`, `unmerged`, `merge_closed`, `erased`, `withdrawn` and `events_changed`. The 004 admission, upgrade, erasure and lifecycle paths, which already hold the client lock, perform the same revision and change-record writes in their own transaction when an assigned event is added, changes content or leaves retention. Identical retries and rejected events do not advance revisions. Record the final revision before deleting an erased person.

| Derived association | Owner | Action after a change |
|---|---|---|
| Stage, first/last touch, counts, lead inbox | 006 | Computed on read; always current. |
| Touchpoint sequence for attribution | 008 | Each 008 run records the `journey_revision` of every person it used; a change record marks those runs stale. 008 recomputes with the same model version and keeps the superseded run for audit. |
| Sale-to-person association | 007 | 007 associates verified sales with an IdentityKey or a collection subject, never with a merge root. Ownership therefore follows keys and is resolved on read. Detaching identifiers while preserving amounts is the F1 proposal in 003. Its adoption and verification belong to 007. |
| Conversion and audience deliveries | 014 | Delivery claims recheck consent, tombstones and current ownership (E4/E5). |
| Reports and caches | 016 | Epoch invalidation per client. |

006 provides revisions and ordered per-client change records for internal consumers. Actual 007/008 recalculation and its end-to-end verification belong to those specifications.

### 11.1 Feed state and consistent rebuild

`identity_feed_state` holds one row per client: `last_seq` (the committed high watermark) and `pruned_through_seq` (the highest sequence removed by retention). Every transaction that appends change records allocates contiguous sequence numbers under the client lock and advances `last_seq` in the same transaction. The client lock is transaction-scoped (`pg_advisory_xact_lock`), so change transactions of one client commit in sequence order. Feed pruning advances `pruned_through_seq` in the transaction that deletes the rows, and both values survive an empty feed and the erasure of any person.

A consumer stores, per client, its derived rows and a checkpoint sequence `c`:

| Consumer state | Required action |
|---|---|
| `c >= pruned_through_seq` | Replay change records `c + 1` to `last_seq` in order, then store the new checkpoint with the applied changes in one consumer transaction. |
| `c < pruned_through_seq` (records missed, including when the feed is now empty) | Rebuild the client partition as below. |

**Rebuild protocol.**

1. Open one read-only `REPEATABLE READ` transaction. Read `last_seq` from `identity_feed_state` as the snapshot watermark `w`, then read every source row the consumer needs (persons, keys, links, merges and assigned events) in the same transaction. Because every change and its watermark commit together, the snapshot contains exactly the changes with sequence `<= w`.
2. Write the derived rows into a new staging generation identified by `(client, generation)`. The published generation and its checkpoint stay current while the rebuild runs.
3. Publish in one consumer transaction: switch the client's current generation to the staging generation and store checkpoint `w`, conditional on the generation that was current when the rebuild started. A concurrent rebuild that published first makes this switch fail, and that rebuild's result stands.
4. Replay records `w + 1` onward as in normal operation. An erasure committed during the rebuild has a sequence above `w`, so its `erased` record removes the person even if the snapshot still contained them. If those records were pruned before replay, rebuild again.

An interrupted rebuild never published a generation. The retry discards the abandoned staging rows and starts again from a new snapshot, so data and checkpoint always change together. 006 verifies this contract with a synthetic reference consumer in its tests (M3). The production consumers belong to 007/008 and 016.

## 12. Technical proposal

### 12.1 Schema (migration `0009_identity_journey`, proposed)

All tables carry `agency_id` and `client_id` with composite foreign keys to `client_workspaces` and scoped uniqueness `(agency_id, client_id, id)`.

| Table | Columns (summary) | Constraints |
|---|---|---|
| `identity_key_secrets` | version, kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext, created_at | Unique `(client_id, version)`. Per-client HMAC key sealed with the existing token envelope under the D-025 **local development** keyring; production custody follows 020. Use a dedicated envelope kind `identity_matching_key`, the client ID as context owner and this secret row's ID as `secret_id`. Preserve the matching secret across wrapping-key changes. Created on first use under the client lock. |
| `identity_subjects` | status (`active`, `merged`), merged_into_id, version (correction concurrency, starts at 1), journey_revision (starts at 0), created_at, updated_at, last_evidence_at | Scoped self-FK; `(status = 'merged') = (merged_into_id IS NOT NULL)`; `merged_into_id <> id`; `version >= 1`; `journey_revision >= 0`. |
| `identity_keys` | kind, key_bytes (32), key_version, normalizer, subject_id (owner, nullable), status (`owned`, `contested`), contested_reason (`shared`, `unmerged`), merge_id (nullable), original owners, first_verified_at, last_verified_at | Unique `(client_id, kind, key_bytes)`; `(status = 'owned') = (subject_id IS NOT NULL)`; `(status = 'contested') = (contested_reason IS NOT NULL)`; normalizer in the closed set; scoped FK and index on merge_id. |
| `identity_assertions` | assertion_id (sender), credential_id, collection_subject_id, keyed request fingerprint, proof digest, per-identifier evidence (scoped key ID, method, verified_at, original owner), received_at, outcome (`linked`, `ambiguous`, `contested_identifier`, `suppressed`), reason, candidate person IDs | Unique `(client_id, assertion_id)`. UUIDs inside compound evidence require explicit same-client validation under the lock. An array of UUIDs alone provides no foreign-key guarantee. A suppressed receipt holds no key reference. |
| `identity_links` | collection_subject_id, subject_id (null for an ambiguous segment), candidate person IDs, assertion_id, asserted_at, eligible_from, eligible_until, closed_reason, status (`active`, `ambiguous`), merge_id (nullable), original owners | Scoped FKs and interval checks; `(status = 'active') = (subject_id IS NOT NULL)`; scoped FK and index on merge_id. Store the exclusive end of every closed segment and its grant bounds independently of expiring consent history. |
| `identity_handoffs` | collection_subject_id, code_digest, challenge_digest, identity_consent_receipt_id, expires_at, consumed_at, created_at | Unique `(client_id, code_digest)` and `(client_id, challenge_digest)`; scoped FK. Issuance binds the code to one backend challenge, one browser-issued subject and one grant receipt. |
| `identity_merges` | operation_id, kind (`merge`, `unmerge`), survivor_id, merged_id, reverses_id, status (`active`, `reversed`, `closed`), closed_reason, expected and resulting versions of both participants, keyed request fingerprint, recorded result, actor membership, reason_code, created_at | Unique `(client_id, operation_id)`; at most one active edge per person; append-only for the runtime except status changes on reversal or closure and deletion on erasure. |
| `identity_changes` | seq, person_id, kind, journey_revision, occurred_at | Unique `(client_id, seq)`. One row per affected person and revision. Erasure notifications survive deletion of the person. |
| `identity_feed_state` | last_seq, pruned_through_seq, updated_at | One row per client; `0 <= pruned_through_seq <= last_seq` (section 11.1). Survives an empty feed and person erasure. |

Add three columns to `collection_subjects`: the immutable `issuance_channel` (`browser`, `server`, or `unknown` for pre-0009 rows, section 8.1), the monotonic `identity_floor_at` and the write-once `identity_shared_at` (section 4.4). Populate the channel from the trusted creation path. Ordinary 004/005 consent and event behavior continues for legacy rows. Other changes: `deletion_tombstones.match_type` adds `identity_key`, `assertion_id` and `assertion_request`; `event_diagnostics.channel` adds `identity`; `audit_events` adds actions `identity.merged`, `identity.unmerged`, `identity.erased`, `identity.erasure_resolved` and resource type `identity_subject`; deletion requests gain the targets `identity_records` and `unresolved_events` in their existing per-target outcomes; `client_grants` and `invitation_client_grants` add `can_view_identities` (default false, D8). Downgrade refuses populated tables and non-default values, as 0007/0008 do.

### 12.2 API (proposed, 11 operations)

| Operation | Principal | Notes |
|---|---|---|
| `POST /collect/v1/{public_key}/identity-handoff` | Token holder from a registered Origin | Body `{subject_token, challenge}`. Require effective `identity_link`, a live source, the scoped subject, `browser` issuance (section 8.1) and an unused challenge. 201 `{code, expires_at}` with the public consent-state CORS policy, per-subject rate limit and `no-store`. Every refusal returns the same `unavailable` response. |
| `POST /agencies/{a}/clients/{c}/identity-assertions` | Ingest key | `assertion_id` (UUID), exactly one of `{handoff, challenge}` or `{subject_token, identity_consent_receipt_id}`, and 1–3 verified identifiers (one per kind). Responses follow the table below. Matching and tombstone outcomes stay internal. Write acknowledgements omit person IDs, candidates and whether an identifier already had an owner (D8). |
| `GET .../identity/subjects` | Identity reader | Filters: stage, flags, updated since; keyset pagination. |
| `GET .../identity/subjects/{id}` | Identity reader | Identify the requested member and its resolved root. Authorized managers can retrieve both participants' versions for a reversal. |
| `GET .../identity/subjects/{id}/timeline` | Identity reader | Section 9.2. |
| `GET .../identity/leads` | Identity reader | Section 9.3. |
| `GET .../identity/review` | Owner/Admin | Section 9.4. |
| `POST .../identity/merges` | Owner/Admin | `operation_id`, survivor/merged IDs and expected versions, reason. 201 with the merge ID and both resulting versions. An exact authorized retry returns the recorded result with 200 before any version check. A new operation with a stale version returns 409 without writes. |
| `POST .../identity/merges/{id}/reversal` | Owner/Admin | `operation_id`, both participants' expected versions, reason. Same retry and 409 rules. The response lists both resulting versions and the keys and links moved to review. |
| `POST .../identity/erasures` | Owner/Admin | Exactly one of `subject_id` or `identifier: {kind, value}`, plus optional `objected` (default false); returns the 004-style deletion request with per-target outcomes. The raw value is used only to compute keys, with the same validation as matching (section 5). |
| `POST .../identity/erasures/{request_id}/resolution` | Owner/Admin | For a request in `paused_for_clarification`, `{subject_id}` names the resolved original person after any merge reversal. For a request in `on_hold`, `{unresolved_events: "erase" \| "retain"}` decides the held events (section 7.2). Audited as `identity.erasure_resolved`. |

**Assertion responses.** The ingest principal can learn only about its own request: authentication, syntax, freshness, proof and idempotency. Steps refer to section 4.2.

| Condition | Step | HTTP | Body |
|---|---|---|---|
| Missing, invalid or revoked credential; no live grant for the client | 1 | 401 / 404 | Existing generic 004 responses. |
| Malformed body or identifier, method not allowed for the kind, more than one identifier per kind | 1 | 422 | `{"status": "rejected", "reason": ...}` with `request_invalid`, `identifier_invalid`, `phone_country_required` or `method_invalid`. |
| Exact retry of a live receipt or of a tombstoned assertion | 3 | 200 | `{"status": "duplicate", "assertion_id": ...}` |
| Same assertion ID with a different fingerprint, live or tombstoned | 3 | 409 | `{"status": "conflict", "assertion_id": ...}` |
| `verified_at` outside the freshness window | 4 | 422 | `{"status": "rejected", "reason": "verification_stale"}` |
| Unknown, expired, consumed or mismatched handoff; challenge mismatch; issuance channel not permitted; unknown or erased token; receipt not current or `identity_link` not granted | 5–6 | 422 | `{"status": "rejected", "reason": "proof_invalid"}` |
| Well-formed, authenticated, fresh and proven, whatever the internal outcome: `linked`, `ambiguous`, `contested_identifier`, or `suppressed` as `no_consent_after_deletion` or `subject_objected` | 7–10 | 201 | `{"status": "accepted", "assertion_id": ...}` |
| Rate limit | any | 429 | Existing generic response. |

Two assertions that differ only in an identifier's deletion or objection history therefore receive the same status and the same body apart from the echoed assertion ID. Internal outcomes and exact reasons are visible only to Owner/Admin through receipts, aggregate diagnostics and the review queue.

```json
{"status": "accepted", "assertion_id": "00000000-0000-4000-8000-000000000401"}
```

```json
{"status": "rejected", "reason": "proof_invalid"}
```

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
- Process assertions in the order of section 4.2. Retry recognition (step 3) follows live sender scope and precedes freshness, proof and consent, so an exact retry with the same credential, proof and canonical request receives the generic duplicate acknowledgement without consuming again, even after the code expired or its row was purged. The keyed fingerprint covers the assertion ID, credential ID, canonical evidence, proof digests and verification times, so a changed request or credential cannot reuse the receipt. A first application checks freshness, proof, current consent and key tombstones, then atomically consumes the proof and writes the receipt.
- Erasure replaces the receipt with `assertion_id` and `assertion_request` tombstones, so retries after erasure are answered exactly as for a live receipt. W1 and lifecycle expiry remove the receipt without a tombstone. A later request under that ID is then a new application whose old proof is no longer valid. That response reveals only that the sender's own proof is unusable, never deletion or objection history.
- Bind merge operation IDs to action, target, actor and request content. An exact authorized retry precedes stale-version checks and returns the recorded result.
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
| Merge ledger and merge-dependency markers | `identity.correction` (new, medium, pseudonymous) | D12 recommendation: retain an active edge, its original-owner fields and the merge IDs on dependent keys and links for as long as both participants exist, without an age limit. Retain closed ledger entries for 2 years after reversal or closure, or until earlier person erasure. |
| Change feed | `identity.change` (new, low, pseudonymous) | 30 days. `identity_feed_state` lives with the client workspace. |
| Tombstones | `deletion.tombstone` | Workspace lifetime (D-025). |

Expiry runs under the client lock in bounded batches. Expiring a single event updates the affected journey and preserves links for other live events on the subject. Expiring the subject drops its evidence and orphaned identity rows. Keep active merge evidence while its persons exist, and close an edge whose participant is removed (section 10.1). Grant the lifecycle role the specific deletes, revision updates, edge closures and feed inserts needed. A lifecycle run may never delete a live workspace's matching secret or lower an identity floor.

**Cost of reversible merges (D10/D12).** An active edge has no age limit. For a continuously active customer, the pseudonymous ledger row and its original-owner fields can therefore outlive the 2-year closed-ledger period indefinitely, and the merge IDs persist on dependent keys and links for as long as those rows live. The volume is one ledger row per active merge plus one marker per dependent item. The alternative is to make active edges irreversible after a fixed age by converting them into a physical merge. That bounds retention, but it needs a physical-merge path that v1 does not have and makes later correction of a mistaken merge impossible.

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

The values follow sections 9.1 and 11. `version` is 1 because S1 was never merged. `journey_revision` is 5 because five transactions changed S1's visible journey: A1 (link P with e1 and e2), A2 (link Q with the earlier e3), A3 (link L with e4), and the arrivals of e5 and e6 on linked subjects. Events received before their subject's link did not change any journey. `device_subject` is a per-person display alias, not the collection subject ID or token. Field names are proposals for 018 review. No screen, component or visual prototype is part of this specification.

## 14. Implementation slices (after approval)

| Slice | Content | Depends on |
|---|---|---|
| 006-A | Migration 0009, models, data-policy registry, per-client key custody, keys/normalizers (`email:v1`, `phone:v1`, `ref:v1`), tombstone and audit extensions, grants. | D1–D12 (schema dependencies in the packet) |
| 006-B | Handoff route, assertion service and API, matching rules R1-R5, segments, consent (E3), withdrawal/expiry/lifecycle integration, diagnostics. | 006-A, D2/D5/D6/D7 |
| 006-C | Profile, timeline, lead inbox and review read APIs with permissions. | 006-B, D8/D9/D13 |
| 006-D | Merge, unmerge with dependency re-evaluation, erasure by person/identifier with clarification, change feed and the rebuild contract. | 006-C, D10 |
| 006-E | Tracker `identityHandoff(challenge)` and `restart()`, Node and Chromium/Firefox tests, end-to-end journey of section 2 on loopback with a disposable database. | 006-B for tracker tests, 006-C for the profile/timeline journey |

Each slice is committed locally, verified with the relevant rows of the verification matrix, and presented for review. Push, PR, native migration and real intake keep their separate gates.

## 15. Out of scope and limitations

- Fingerprinting, IP or user-agent matching, probabilistic matching and cross-client identity graphs.
- Platform-run verification messages to visitors; webhook and import assertions (015); provider match keys (014).
- Full CRM (assignment, notes, pipelines), React screens and visual design (018), and reporting (016).
- Verified sale evidence and revenue (007), and attribution models (008).
- Market-specific consent profiles (Q-003) and production key custody (020).
- The design cannot detect recycled phone numbers or shared mailboxes before a conflict appears; the first assertion of a shared identifier is attributed to its first verifier until a conflict is observed.
