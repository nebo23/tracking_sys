# Specification 003: privacy, consent, and data lifecycle design
Status: Completed at contract level under D-025, pending owner review. Prepared: 2026-11-03. Reconciled on 2026-11-04 under D-023 with merged main `98747a2` (PR 1, revision `0004_identity`). Slice 003-A is implemented (D-023, D-024), and the 003-B to 003-D contracts are tested libraries (D-025) whose tables and end-to-end enforcement belong to the consuming specifications (section 16).

Requirements: [spec](spec.md), [plan](plan.md), [tasks](tasks.md). Decisions blocking the next slices: [003-A decision packet](decision-packet-003a.md). Implementation evidence: [evidence](evidence.md). Research: [sources](../../research_notes/privacy-data-policy/sources.md); "[S-n]" cites an entry there.

Reconciliation note: sections 1, 2, 5 to 8, and 10 to 15 keep the 2026-11-03 proposal text, with additions marked "Reconciled 2026-11-04". Sections 3, 9, 16, 17, and 18 were rewritten against the merged code. The superseded Google/Gmail proposal is kept for traceability in [review-amendments](review-amendments.md); the approved [auth design](../002-tenancy-access/auth-design.md) and the code describe implemented behavior.

Status labels used below: **implemented** (code and tests on this branch), **existing** (merged behavior from specifications 001/002), **proposed** (no decision yet), **awaiting decision** (named in the decision packet), **later specification** (owned by the named specification).

| Required contract | Section | Status 2026-11-04 |
|---|---|---|
| DataClassPolicy | 4 | **Implemented** for stored columns (003-A1); client-data fields (lawful basis, export, outbound) proposed for 003-B/003-C |
| ConsentRecord | 5 | **Contract implemented** (D-025) in `app.privacy.consent` with J1 strict opt-in; the table and enforcement points belong to 004, 005, 006, and 014 |
| DeletionRequest | 10 | User-account scope **implemented** (003-A5). Request lifecycle, target outcomes, keyed identifiers, and tombstone admission are **contract implemented** (D-025) in `app.privacy.deletion`; tables and consumers belong to 004, 006, 014, 016, and 017 |
| TokenSecretReference | 8 | **Contract implemented** (D-025) in `app.privacy.token_secrets`: envelope encryption with a local development keyring refused in production; the table belongs to 009 and managed custody to 020 |
| Provider-specific policy table | 14 | **Contract implemented** (D-025) in `app.privacy.providers`: connector rows are stale and block their features until re-verified in 009-016; the Google platform rows are current |

## 1. Purpose and boundaries
This design proposes the five contracts required by specification 003 (ConsentRecord, DataClassPolicy, DeletionRequest, TokenSecretReference, and the provider-specific policy table) and applies them both to the data held today and to data that specifications 004-020 will introduce. It is design research, not legal advice. It makes no claim of legal compliance, certification, provider program approval, or app-review access. Counsel should confirm jurisdictional positions before Q-003 or Q-012 is recorded.

Not decided here: markets and storage region (Q-003), retention values (Q-012), hosting, KMS/HSM, queue or job tooling, consent-management or payment vendors, contractual controller/processor positions, and production mail. Every period, role, and option below is proposed unless it cites a D-ID. This document approves no schema, dependency, privilege, or behavior change. Specification 003 defines contracts; tracker, ingestion, connectors, reporting, and backups implement them in their own specifications. Pending EU legislative changes [S-32] are handled as reviewed policy-data changes, not assumed.

## 2. Confirmed inputs and open decisions
- D-004, D-005, D-006: both social analytics and attribution, multiple agencies, broad market. Controls must not silently drop either capability, and any client may submit health or financial leads.
- D-009, D-011, D-012, D-023: formal English, isolated dependencies, and owner review of each slice before upload. D-023 supersedes D-020's shared branch: this specification uses codex/spec-003-privacy-data-policy from merged main.
- D-014, D-015, D-017, D-019: PostgreSQL 18, SQLAlchemy 2, Alembic, Psycopg 3, cryptography (Fernet), pwdlib/Argon2, and email-validator. tracking_sys receives only reviewed additive migrations; destructive and restore tests use a disposable database. 002-A excluded hard deletion and deferred retention and deletion to 003.
- Reconciled 2026-11-04. D-021/D-022: numeric email-verification codes, optional Google sign-in (OpenID Connect, PyJWT[crypto]), and an opt-in Gmail API sender with its own Desktop OAuth client, merged with the R-01 to R-03 corrections in PR 1. Google unlinking and erasure were explicitly left to this specification (auth design, account policy 5). Native tracking_sys is at `0004_identity` and holds the owner's own test account data, which is platform-user personal data rather than client end-customer data.
- AGENTS.md data boundaries: agency/client authorization across APIs, jobs, caches, reports, and exports; no tokens, real events, identifiers, signed URLs, or production data in the repository; explicit missing, unsupported, and stale states.

| Open decision | What depends on it |
|---|---|
| Q-003 markets and storage region | Jurisdiction profiles, consent defaults, request deadlines, breach clocks, transfer register. Market scope is not inferred from conversation language. |
| Q-012 retention, consent, deletion per class | Every candidate period in sections 4, 9, 10, and 11. |
| Q-011 SLO/RPO/RTO; Q-008 production mail | Backup, journal, and restore windows; overdue-retention alerts; production mail retention. |
| Q-009 job tooling; Q-010 build versus integrate | Retention scheduling; first-party consent capture versus an external consent platform. |
| Q-002 lead evidence; Q-007 attribution rules | Lead data classes; recomputation scope after deletion. |

## 3. Current data inventory (reconciled 2026-11-04)
Revision `0004_identity` holds 19 application tables plus alembic_version, verified against the SQLAlchemy metadata, the migration code, and a migrated disposable database ([evidence](evidence.md)). No end-customer, event, lead, revenue, consent, or connector data exists. No foreign key declares ON DELETE. Rows are never deleted except client grants on revocation. tracking_app has DELETE only on client_grants; audit_events and security_events are append-only for it, and its UPDATE rights on users, verification_challenges, oauth_transactions, and external_identities are column-limited (grant matrix in the [decision packet](decision-packet-003a.md#decision-4-privilege-model)). The session cookie (Max-Age 12 hours, cleared on logout), the CSRF value, issued service keys, verification codes, OAuth state values, and Google tokens are never persisted raw. Every column is mapped to a data class in [backend/app/data_policy.py](../../backend/app/data_policy.py) (003-A1, **implemented**).

| Store | Personal or secret content | Registry classes | Current end of life | Gap |
|---|---|---|---|---|
| users | email_normalized, display_name | account.identity, account.reference | Never deleted; runtime cannot change email, name, or status | No closure or erasure path; unverified registrations (possibly of third-party addresses) persist; audit and security foreign keys block deletion |
| password_credentials | Argon2id hash; absent for Google-only accounts | credential.secret_verifier | Overwritten on change or reset | Removable only by closure (decision 3) |
| auth_sessions, auth_tokens | Token digests; login, activity, and expiry times | credential.token_digest, credential.lifecycle | Revoked, consumed, superseded, or expired; rows kept | No purge; one session row per login |
| verification_challenges (D-022) | Keyed HMAC verifier of a six-digit code; failed-attempt counts | credential.secret_verifier, credential.lifecycle | Consumed, invalidated on reissue, or expired; rows kept | No purge |
| oauth_transactions (D-022) | State and browser/session binding digests; link transactions name the user | credential.token_digest, credential.lifecycle | Consumed or expired after 10 minutes; rows kept | No purge |
| external_identities (D-022) | Google issuer and subject, which is stable and never reused by Google | identity.external_subject | Kept while linked; no unlink | No unlink or erasure (deferred to 003 by D-022 policy 5); Google ID and access tokens are discarded after validation |
| service_credentials, agency_invitations, and their client grant rows | Key and invitation digests; invitee email (may never register); key labels | credential.token_digest, contact.invitee, tenancy.* | Revoked, accepted, or expired; rows kept; expired invitations stay pending | No purge |
| auth_rate_limits | HMAC bucket keys over IP, email, or user ID | security.telemetry | Counter restarts in place | Unbounded growth; the key holder can test candidate values; key rotation orphans rows |
| security_events | user_id (NULL for login_failed), action, time; D-022 added Google and verification-failure actions | security.telemetry | Append-only forever | No retention |
| mail_outbox | Fernet ciphertext with recipient and a code (verification) or live link (reset, invitation) | message.transactional, message.delivery_state | Ciphertext cleared on delivery; verification payload cleared unsent at expires_at (D-022); rows kept | Reset and invitation payloads have no expiry and retry with capped backoff indefinitely; one key, no key ID |
| Local .eml files (local-data/mail, mail-data volume) | Plaintext recipient, code, or raw link token | local.development_file | Never deleted | Live links readable for up to 7 days |
| Gmail sender mailbox (owner's Google account) | Sent copy of each delivered message, including live reset and invitation links | Outside application control | Gmail retention (not verified) | Deleting copies would need a broader Gmail scope (decision 5) |
| agencies, client_workspaces, agency_memberships, client_grants | Names that may be personal names; person-role and scope links | tenancy.label, tenancy.configuration | No closure; archiving is reversible; memberships only disabled; client grants hard-deleted on revoke | Offboarding belongs to 017 |
| audit_events | actor_user_id, resource_id, time | audit.administrative, account.reference | Append-only forever | No retention; resource_id has no foreign key |
| Application and server logs | Registered event codes only (003-A2); before 003-A2, %-arguments, uvicorn tracebacks, and unconfigured library records reached stderr with their values (verified) | log.application | stderr; no rotation configured | Rotation and retention belong to 019/020 |
| PostgreSQL server and container logs | A unique violation logs the conflicting key value in DETAIL with default settings (verified on the disposable server) | log.database | Outside application control | Recommend log_error_verbosity = terse for operated servers (operator setting, not changed) |
| postgres-data volume; native tracking_sys data directory | Full database copies, dead tuples, WAL | backup.copy | Kept across compose down | No backup or restore tooling (020) |
| .env, .env.docker, local-data/google | auth_secret, mail key, OTP key, database passwords; Google sign-in client secret; Gmail sender client secret and refresh token (send authority over the owner's mailbox); downloaded client JSON | secret.configuration | Manual | auth_secret serves several purposes; no rotation procedure; Testing-mode Gmail refresh tokens expire after 7 days |
| Caches, exports, frontend storage | None exist | cache, export.artifact | Not applicable | Contracts in sections 10-11 must precede 016 and 018 |

## 4. Data classes (DataClassPolicy)
DataClassPolicy fields: class_code, sensitivity (high, medium, low, prohibited), personal (direct, pseudonymous [S-1][S-19], none), provenance (provided, observed, derived [S-7]), lawful_basis_ref set by the controller rather than the platform [S-3], retention_rule (anchor timestamp plus interval, "purpose", or "provider row"), end_of_life action, legal_hold_allowed, export_allowed, outbound_allowed, governing spec, and policy_version. The registry is versioned code reviewed like a migration; a used class code never changes meaning. Storage limitation and accountability require a finite rule per class [S-2]. Retention values below are candidates requiring Q-012 approval; none is in force.

| Class | Examples | Sensitivity | Candidate default retention (Q-012) | End of life | Spec |
|---|---|---|---|---|---|
| account.identity | User email and name; invitee emails | High | Active account; unverified accounts 30 days; closure completed within 30 days | Delete, or pseudonymize where audit references remain | 003-A, 017 |
| credential.*, security.telemetry | Password hash; session, token, and key digests; security_events; rate-limit buckets | High, medium | Section 9 table | Delete | 003-A |
| tenancy.configuration | Agencies, clients, memberships, grants | Medium | Agency lifetime plus a 30-day post-closure export window | Delete | 017 |
| audit.administrative | audit_events | Medium | 2 years | Delete; actor pseudonymized on account erasure | 003-A |
| message.transactional | mail_outbox; future production mail | High | Payload until embedded token expiry; row 30 days | Clear payload, then delete | 003-A, 020 |
| consent.evidence | ConsentRecord, notice snapshots (personal data [S-23]) | Medium | While relied on plus a 3-year proof period; Egypt marketing evidence 3 years after the last message if selected [S-35] | Delete; minimal proof only under hold | 003-B |
| visitor.event | Tracker events, visitor and click ids, IP, user agent, URLs | Medium | Raw 13 months, then aggregates only | Drop partitions; aggregate | 004, 005 |
| lead.contact | Form submissions, CRM and import rows | High | 24 months after last activity; client may shorten | Delete or detach | 004, 005, 015 |
| identity.pseudonym, identity.provider_match_key | Keyed HMAC subject keys and identity links; provider SHA-256 match keys | High | Pseudonyms as the underlying subject; match keys only inside the encrypted outbox payload | Delete and destroy the per-client key on offboarding; clear match keys after delivery or suppression | 006, 014 |
| financial.record | Payments, refunds, ledger entries | High | Market accounting duties (unverified; counsel) | Detach subject identifiers; retain amounts | 007 |
| payment.sensitive_authentication | PAN, CVV/CVC, PIN, track data, passwords | Prohibited | Never collected [S-89] | Drop in tracker and at ingestion | 003-B, 005 |
| connector.token | OAuth access and refresh tokens | High | Until disconnect, revocation, or provider expiry | Revoke at provider, delete, crypto-shred where possible | 009 |
| provider.social_data | Metrics, content references, comments | Medium | Shortest applicable provider row (section 14) | Delete or refresh | 010-013 |
| derived.analytics | Aggregates, attribution allocations, scores | Medium | As inputs; subject-free aggregates for client lifetime | Recompute or aggregate | 008, 016 |
| export.artifact | Report snapshots, CSV, offboarding exports | High | 7 days | Delete file and per-export key | 016, 017 |
| cache | Read models, API caches, browser state | As source | No longer than source; epoch invalidation | Expire | 016, 018 |
| backup.copy | Backups, volumes, WAL | As source | Q-011 (candidate 35 days) | Expire; tombstones reapplied on restore | 020 |
| log.application, log.database | Application, worker, server, container logs | Low (no personal data permitted) | 30 days | Rotate and delete | 003-A, 019, 020 |
| local.development_file | .eml captures, local-data | High | Token lifetime, at most 7 days | Delete | 003-A |

Reconciled 2026-11-04 (003-A1, **implemented**). [backend/app/data_policy.py](../../backend/app/data_policy.py) implements DataClassPolicy for stored columns: class code, description, sensitivity, personal (direct, pseudonymous, none), provenance, proposed end-of-life action, governing specification, and registry version. Per-table end-of-life rules carry a status (approved, pending_decision, deferred, not_applicable) and a decision or specification reference. Retention is recorded per table rather than per class, because one row mixes classes and its lifetime follows the row's anchor timestamp. lawful_basis_ref, legal_hold_allowed, export_allowed, and outbound_allowed are not yet fields; they first matter for client data in 003-B and 003-C. The current-data classes refine the table above:
- account.identity: user email and name.
- account.reference: user IDs, account state, and every column referencing users.
- contact.invitee.
- credential.secret_verifier.
- credential.token_digest.
- credential.lifecycle.
- identity.external_subject: new under D-022.
- security.telemetry.
- message.transactional.
- message.delivery_state.
- tenancy.label.
- tenancy.configuration.
- audit.administrative.
- system.schema_version.

Only two rules are approved, both decided under specification 002: clearing the outbox payload (D-019, D-022) and deleting a client grant on revocation (D-017). Every retention period in this section remains a Q-012 candidate.

## 5. Consent model (ConsentRecord)
Purposes are internal codes mapped to provider signals, so provider renaming never changes the internal model:

| Purpose | Meaning | Google Consent Mode v2 [S-79] | Other providers |
|---|---|---|---|
| necessary | Security, fraud prevention, consent storage, requested function | security_storage, functionality_storage | Exemption scope per jurisdiction profile [S-14][S-28] |
| analytics.first_party | Measurement for the client's own site | analytics_storage | None |
| attribution | Linking touchpoints to the client's leads and revenue | None | None |
| identity_link | Linking anonymous visits to a known identity (006 AC1) | None | X off-platform matching needs express opt-in [S-87] |
| ads.measurement | Sending conversions to ad platforms | ad_storage, ad_user_data; consent field per upload [S-77] | Meta verifiable consent [S-67]; LinkedIn legal basis per event [S-83] |
| ads.personalization | Audiences and remarketing | ad_personalization | Objection to direct marketing suppresses [S-8] |
| sale_or_share | US-style sale or sharing opt-out | Not applicable | Meta Limited Data Use per event [S-69]; GPC [S-109][S-57] |

States: unknown (no valid signal), granted, denied, withdrawn, expired (refresh interval passed). Evaluation allows a purpose only when it is granted, or when the active jurisdiction profile documents an exemption or opt-out model for it; unknown is denied in every opt-in profile. Consent is never inferred from scrolling, form submission, or closing a banner, and pre-ticked choices are rejected [S-12][S-13][S-58]. ConsentRecord (append-only): id (uuidv7), agency_id and client_id (composite foreign key), subject_ref (HMAC device or subject key) and key_id, purpose, state, source (tracker_banner, external_cmp, gpc, api, admin_import), jurisdiction_profile, policy_version, notice_snapshot_hash, captured_at (client, untrusted), received_at (server), expires_at, supersedes_id. No raw IP, user agent, or email. consent_state(client_id, subject_ref, purpose) is updated in the same transaction. consent_notice_versions holds immutable snapshots of text, purposes, named recipients, and storage items with lifetimes and third-party access [S-12][S-13][S-78]. This keeps verifiable evidence [S-4][S-67] without excess processing [S-12]; consent strings are themselves personal data [S-23].

Withdrawal is offered in the same interface with no more steps than granting [S-4]. Propagation: (1) record withdrawal and update consent_state; (2) the delivery-time check suppresses queued items and clears payloads; (3) identity linking stops; (4) without another basis, open a DeletionRequest with reason consent_withdrawn [S-12] (a Saudi draft would also require destroying derived data [S-41]); (5) mirror the withdrawal to the restore journal (section 12).

| Default option | Behavior | Trade-off |
|---|---|---|
| J1 strict opt-in everywhere | Deny every non-necessary purpose until granted | One test matrix and safe default [S-9]; loses data where law permits opt-out or notice-based analytics |
| J2 per-workspace jurisdiction profile | Opt-in profiles: EU/EEA [S-14], Egypt [S-37], Saudi Arabia [S-40], UAE onshore provisional [S-47]. UK: first-party statistics with notice and a free objection, never advertising [S-28][S-29], now enforced under the DPA 2018 regime [S-31]. US opt-out: honor GPC on every path, including server-side feeds [S-57][S-59][S-60] | Matches market rules once Q-003 is decided; more rows and tests; one site may have visitors from several jurisdictions |
| J3 per-visitor geolocation | Resolve the profile from IP per event | Processes every visitor's IP, itself in scope [S-14]; location errors; not recommended as the only mechanism |

Recommendation: 003-B enables only J1 while storing the profile field and policy rows in the J2 shape; additional profiles are enabled only after Q-003 names markets and counsel reviews each. Google basic consent mode (tags blocked until consent) is recommended over advanced mode, which sends cookieless pings while consent is denied [S-79].

| Point | Spec | Rule |
|---|---|---|
| E1 Tracker, before storage access, identifiers, or form capture | 005 | Default deny; read GPC; no request carrying identifiers before evaluation [S-14] |
| E2 Ingestion, before persistence | 004 | Re-evaluate against server consent_state (client claims are untrusted); drop disallowed fields; count rejected events by reason code only and never quarantine their payload |
| E3 Identity linking | 006 | Require identity_link and any provider matching row |
| E4 Outbound enqueue | 014 | Per-destination purpose and tombstone check; store the consent snapshot version |
| E5 Delivery claim | 014 | Recheck consent and tombstones in the claiming transaction (FOR UPDATE SKIP LOCKED); suppress and clear payload |
| E6 Connector backfill, CSV and CRM import | 009, 015 | Consent and tombstones apply to imported subjects |

Reconciled 2026-11-04. Status: **proposed; later specification** (003-B with 004, 005, and 014). Merged specification 002 changes nothing in this contract: Google sign-in and Gmail delivery serve platform users and are not consent purposes for client end customers.

## 6. Collection minimization and masking
- Form capture is an allowlist: a client maps each field to an approved data class, and unmapped fields are never read. Capture happens at submission only; collecting typed input before submission is within Art. 5(3) scope [S-14]. Defaults collect only what each purpose needs [S-2].
- Never-collect rules apply in the tracker and again at ingestion: input type password or hidden; autocomplete tokens current-password, new-password, one-time-code, and every cc-* token [S-110]; payment iframes; field names, ids, or labels matching password, card, CVV/CVC, or PIN patterns (a second layer only); and, as a candidate, mapped free-text values matching a Luhn-valid card number. Encryption does not make retained sensitive authentication data acceptable [S-89][S-100]. Health, financial, and under-13 data never enter Meta deliveries [S-67].
- URLs keep only allowlisted campaign and click parameters; other query values and fragments are dropped, and tracked links never carry personal data (005 AC1).
- Ingestion rejects unknown fields and applies the same rules regardless of tracker version, recording only counts by reason.
- Logging is an allowlist: a closed registry maps event names to typed fields. A record with %-args, an unregistered event, or an unregistered field emits log_event_rejected instead [S-111][S-112]. uvicorn, uvicorn.error, sqlalchemy, and alembic loggers route through the same formatter. Keep --no-access-log and hide_parameters=True; record PostgreSQL log_statement=none and log_parameter_max_length_on_error=0, and evaluate log_error_verbosity=terse [S-113], because constraint DETAIL lines may contain key values (unverified). Never log non-consented data [S-111] or consent-withdrawn payloads [S-12].
- Reconciled 2026-11-04 (003-A2, **implemented** in [backend/app/logging_config.py](../../backend/app/logging_config.py)). The "tracking" logger accepts only registered events, with fields restricted to closed code sets. Positional arguments, unregistered events or fields, and other values become log_event_rejected. Every handler on uvicorn's loggers, the root logger, and other existing loggers uses the same allowlist formatter, and the root logger gets one if it has none, so Python's last-resort output is never reached. Uvicorn templates are emitted without arguments; other library records keep only their logger name. Exceptions keep only their type and innermost file, line, and function; messages and tracebacks are never written. The application lifespan reapplies the configuration after a server's own logging setup. Access lines, if enabled, carry no path or query, so the Google callback's code and state stay out of logs. Alembic's migration command keeps its own console configuration because it is a separate operator process that logs revision names. The DETAIL claim was verified on the disposable server, and log_error_verbosity = terse is recommended as an operator setting for operated servers; it is not changed here.

| Case (acceptance criterion 2, synthetic values) | Slice | Expected | Status 2026-11-04 |
|---|---|---|---|
| M1 Log call with %-args carrying a synthetic password | 003-A2 | log_event_rejected; value absent from output | Implemented; passes; fails on `98747a2` |
| M2 Unhandled exception whose message contains a synthetic token | 003-A2 | uvicorn.error output contains no token | Implemented with a real uvicorn server in both startup orders; fails on `98747a2` |
| M3 Unregistered event or field | 003-A2 | Rejected | Implemented, including field values and unconfigured library loggers |
| M4 Tracker fixture with password, cc-number, cc-csc, and one-time-code inputs | 005 | Values absent from the outgoing request | Later specification |
| M5 Ingestion payload with those fields and a Luhn-valid number in free text | 003-B, 004 | Dropped; absent from database, outbox, and logs | Later specification |
| M6 Existing stderr secret test (backend/tests/integration/test_auth.py) | 002 | Still passes | Passes; it now reads the current stderr rather than a stream bound earlier |

## 7. Hashing and pseudonymous identifiers
Hashing is not anonymization. Plain hashes of emails and phones can be reversed by guessing [S-18][S-102]. Pseudonymized data remains personal for any party able to link it [S-1][S-19][S-20], and a regulator reportedly fined hashed-email matching without consent [S-22]. Interfaces and documents never describe these values as anonymous.

| Form | Construction | Use | Storage |
|---|---|---|---|
| Random token digest | SHA-256 of a 256-bit random value (existing security.digest) | Sessions, tokens, keys | As today; never for emails or phones |
| Internal subject key | HMAC-SHA256(per-client key, "subject:v1", client_id, identifier_type, canonical value), length-prefixed | Joins within one client | bytea(32) plus key_id; unique (client_id, identifier_type, subject_key) |
| Tombstone match key | Same construction with an independent tombstone key | Replay blocking | Append-only ledger |
| Provider match key | SHA-256 hex after the provider's versioned normalizer | Outbound delivery only | Encrypted outbox payload; never joins or logs |

- Per-client keys are random and wrapped by the KEK (section 8), not derived from a root, so destroying a client's key makes its pseudonyms unlinkable. Per-client domains also prevent cross-tenant linkage [S-19][S-98]; cross-client identity graphs are excluded, and Bahrain would require authorization to combine files of different controllers [S-52].
- Internal normalization is stable and separate from provider rules: email trimmed and lowercased (the existing account convention, without dot or plus rewriting). Phone parsing to E.164 needs a country context; a phone-number library would be a new dependency and is not proposed, so the candidate rule is digits only with a client-configured default country code.
- Provider rules conflict: Meta hashes phone digits with country code and no "+", and hashes city, state, and postal code [S-68]; Google uses E.164 with "+", removes Gmail dots and plus suffixes, and leaves location fields plain [S-76]; LinkedIn accepts SHA256_EMAIL with normalization unverified [S-85]. Each normalizer is versioned in the provider table with synthetic test vectors, following Google's prose rule rather than its sample code [S-76].
- New purposes receive independent secrets; auth_secret keeps only its current rate-limit and CSRF uses.

## 8. Secret protection (TokenSecretReference)
Proposed row: id, agency_id, client_id, connector_id, secret_kind (access_token, refresh_token), version, alg (A256GCM-ENV-v1), kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext, aad_version, provider_expires_at, last_refreshed_at, status (active, refresh_due, revoked, destroyed), created_at, destroyed_at. Platform application secrets are deployment secrets, not rows.
- Envelope: a fresh 256-bit data key and a 96-bit random nonce per secret version using the approved cryptography package's AESGCM [S-93]. The data key is wrapped with AESGCM under a KEK, not RFC 3394/5649 wrapping, which takes no associated data [S-95].
- Associated data: a canonical length-prefixed encoding of format tag, agency_id, client_id, connector_id, secret id, kind, and version, rebuilt from the row at decryption; a ciphertext moved to another row or tenant fails with InvalidTag [S-93]. Wrap associated data binds kek_id and secret id.
- Keys: a local KEK keyring in ignored .env (TRACKING_TOKEN_KEYRING, TRACKING_TOKEN_ACTIVE_KEK), independent of auth_secret and the mail key, behind a wrap/unwrap KeyEncryptionProvider with only a local implementation. Production settings refuse the local keyring, as they refuse local mail today [S-97][S-99]. Production custody (KMS or HSM) is a hosting decision in 020.
- Rotation re-wraps data keys in SKIP LOCKED batches without touching token ciphertext. Wraps are counted per kek_id and rotated far below the 2^32 random-nonce limit [S-94]. A KEK is retired only when no row and no retained backup references it [S-97][S-98].
- Crypto-shredding works only where the destroyed key is absent from every retained backup. It does not reach plaintext derived data, pseudonyms, logs, caches, downloaded exports, or provider copies [S-98][S-100]. Revocation at the provider is the primary control for OAuth tokens [S-101].
- Tokens are never logged, exported, or sent to the browser [S-61], and storage accommodates tokens of at least 1,000 characters [S-84]. Encryption and restore ability are risk measures, not compliance proof [S-11]. MultiFernet suits short-lived mail payloads but has no associated data or key id [S-96]. pgcrypto is avoided because keys would travel in SQL text.
- Reconciled 2026-11-04. Status: **proposed; later specification** (first 009 slice). No TokenSecretReference row exists. Google sign-in keeps no Google token: the authorization-code response is used only to validate the ID token, and only the issuer and subject are stored. The Gmail sender's refresh token and both OAuth client secrets are platform deployment secrets in ignored .env, like the auth and mail keys, not connector tokens. The sender refresh token carries send authority over the owner's mailbox; in Testing publishing status it expires after 7 days. Revocation means removing the authorization in the owner's Google account and clearing the setting. Production custody for these deployment secrets is part of 020.

## 9. Retention execution
- Runner: a bounded CLI module (python -m app.lifecycle, following app.mail_worker), run manually or by an operating-system scheduler in development; durable scheduling waits for Q-009. One runner per job holds pg_try_advisory_lock(int4 namespace, int4 job) in the two-key space, separate from the existing 64-bit registration lock [S-108].
- Batches: a primary-key CTE with ORDER BY, LIMIT, and FOR UPDATE SKIP LOCKED feeds DELETE ... USING; each batch commits and stays under statement_timeout [S-107]. Dependent rows are deleted in the same transaction.
- Future high-volume tables store retain_until and policy_version at write time. Raw events use native monthly range partitions on server received_at, detached concurrently and dropped, with BRIN indexes [S-105][S-106]; pg_partman is not proposed.
- Idempotency and observability (reconciled 2026-11-04: **proposed for later classes**; the [decision packet](decision-packet-003a.md#decision-1-boundaries-of-the-next-slices) proposes no table for the time-based credential-state slice 003-A3, whose predicates are re-evaluated on every run): retention_runs(job, data_class, policy_version, started_at, finished_at, status, rows_affected, batches, last_key, error_code); reruns resume from last_key. Logs carry class codes and counts only. A gauge reports the age of the oldest overdue row per class; alert thresholds follow Q-011. Storage limitation [S-2] is why this runner should exist before real data arrives.
- Legal hold: legal_holds(scope, data classes, reason code, basis reference, created_by, review_at). The runner skips and reports held rows, and data retained for a legal duty keeps proof of that duty [S-61].
- Privileges: tracking_app keeps its append-only audit and security grants. Deletion runs under a dedicated lifecycle role with DELETE or UPDATE only on governed tables (decision 4).

Reconciled 2026-11-04: every period below is a Q-012 candidate **awaiting decision 2** in the [decision packet](decision-packet-003a.md#decision-2-retention-for-current-records), which also states each row's effect on current behavior.

| Existing table | Eligible when | Candidate period (Q-012) | Action |
|---|---|---|---|
| auth_sessions | Revoked, absolute expiry, or idle expiry passed | 30 days after end | Delete |
| auth_tokens | Consumed or expired | 7 days after | Delete |
| verification_challenges (D-022) | Consumed, invalidated, or expired | 7 days after | Delete; daily failure limits live in auth_rate_limits |
| oauth_transactions (D-022) | Consumed or expired (10 minutes) | 1 day after | Delete |
| auth_rate_limits | Window expired | At expiry (earlier candidate: 1 day) | Delete; an expired bucket already counts as restarted |
| mail_outbox | Payload: verification codes are already cleared unsent at expires_at (D-022, existing); reset and invitation payloads get a proposed expires_at at their token expiry (decision 5); the earlier 10-attempt cap is no longer proposed. Row: delivered or expired | Row 30 days later | Delete row |
| Local .eml and .pending files | Written (development only) | Token lifetime, at most 7 days | Delete files (decision 5) |
| agency_invitations, service_credentials, and their client grant rows | Invitation accepted, revoked, or expired; credential revoked or expired | 90 days after end | Delete parent and grants together; audit resource_id becomes a documented dangling reference |
| Unverified users | Never verified; no membership, accepted invitation, or external identity | 30 days after registration | Follows the decision 3 erasure path rather than hard deletion |
| Closed accounts (decision 3) | closed_at set | None after closure | Delete credentials, sessions, tokens, challenges, OAuth transactions, and the external identity; keep the pseudonymized user |
| security_events | occurred_at | 1 year | Delete |
| audit_events | occurred_at | 2 years | Delete |

## 10. Deletion (DeletionRequest)

| Scope | Triggers | Coverage beyond primary rows |
|---|---|---|
| Subject within one client | Request through the client or agency; Meta signed deletion callback [S-62]; YouTube user request [S-72]; consent withdrawal without another basis [S-6] | Raw events, leads, identity links, consent records beyond minimal proof, derived rows, caches, prior exports, queued deliveries, provider recipients [S-6] |
| Connector or provider-wide | Disconnect, provider deauthorize, revocation signal; provider API access terminated | Provider token revocation [S-101], ciphertext deletion, provider-sourced data per section 14, derived metrics, caches, exports; on termination, that provider's data for all tenants immediately with evidence [S-74][S-86] |
| Client workspace | Client offboarding | All client data; per-client pseudonymization key destroyed; LinkedIn marketing data within 10 days [S-83] |
| Agency | Closure (017) | All clients and configuration after an export window; return or deletion at end of service [S-10] |
| User account | Platform user closes the account | Sessions, tokens, and credential deleted; memberships disabled; identity erased per decision 3; refused while the user is the last active Owner |

Reconciled 2026-11-04. Status: the user-account scope is **awaiting decision 3** (slice 003-A5). The current proposal also covers verification challenges, OAuth transactions, and the Google external identity, and reauthentication for Google-only accounts, which have no password. The subject, connector, client, and agency scopes, the lifecycle states, and tombstones are **proposed** for 003-B and 003-C and owned by 004-017. A platform-user closure is handled directly by the account owner and needs no DeletionRequest row; the request contract starts with client data in 003-B.

Lifecycle: received, verifying (requester authority and identity; the UK clock starts after identity information [S-30]), accepted or rejected with reason, optional paused_for_clarification or on_hold, in_progress, completed or partially_completed, and verified. Each target records pending, done, not_applicable, unsupported, or failed; unsupported and failed targets are reported, never silently marked done [S-17]. Fields: id, agency_id, client_id (nullable only for user and agency scopes), scope_kind, requester_kind (client_admin, agency_admin, provider_callback, platform_operator, consent_withdrawal), jurisdiction_profile, received_at, due_at, extension reason and notice time [S-5], status, provider confirmation code [S-62], tombstone ids, legal_hold_id, completed_at, and per-target counts. Raw identifiers are used only to compute match keys and are not stored.

| Target | Mechanism |
|---|---|
| Raw events and leads | Indexed delete by (client_id, subject_key) in live partitions |
| Derived data and identity links | Remove subject rows and links; recompute affected attribution runs with their model version; unmerge preserves remaining provenance (006 AC4); subject-free aggregates remain under 016 small-count thresholds |
| Caches | Invalidate client namespaces by epoch |
| Exports | Revoke unexpired artifacts created before the request; report that downloaded copies are outside system control |
| Outbound queues | Suppress items and clear payloads at the delivery claim |
| Provider recipients | Call provider deletion where supported, otherwise record unsupported; notify recipients [S-6] |
| Local files and logs | Delete development files; logs hold no personal data by design and expire |
| Backups | Not edited; tombstones reapplied on restore [S-17]; data ages out with backup retention |

Tombstones: deletion_tombstones is append-only for the runtime (INSERT and SELECT) with id (uuidv7), agency_id, client_id, scope_kind, match_type, match_key (tombstone-key HMAC), match_key_id, deletion_request_id, effective_at, blocks_received_before, and journal_seq. Checks run at E2-E6. Blocking uses server received_at, event ids, idempotency keys, and provider object ids, never client-claimed occurred_at. Replay windows include Meta CAPI 7 days [S-70], LinkedIn CAPI 90 days [S-85], 004 late arrivals, and connector backfills. Whether new activity may be collected after deletion is decision 10.

Financial and audit records (decision 11): F1 detach subject identifiers from financial rows and keep amounts, preserving totals and attribution history; F2 delete the subject's financial rows, breaking 007 history; F3 retain under legal hold with restricted access. Recommendation: F1, with F3 only where counsel confirms a duty. Audit actor references follow decision 3.

Statutory timelines depend on Q-003: EU one month plus two [S-5]; UK one month from the latest of receipt, identity, or fee, with a clarification pause [S-30]; Egypt six working days [S-35]; Saudi Arabia 30 plus 30 days [S-41]; UAE federal unsettled [S-45][S-48]; DIFC one month plus two [S-49]; California 45 plus 45 days and opt-out within 15 business days [S-57]. Provider limits: YouTube 7 days, or 30 days after external revocation [S-72]; X 24 hours from a request [S-86][S-87]; LinkedIn immediately on user request and 10 days on client offboarding [S-80][S-83]; Meta promptly [S-61]. Candidate internal SLA: automated targets complete within 72 hours of acceptance and X content changes within 24 hours.

## 11. Access and export
- Subject access resolves a normalized identifier to a subject_key within one client and returns data per class with provenance, recipients, and retention [S-5]. Portability output contains provided and observed classes only [S-7]. Other people's data is excluded. The controller verifies the requester; a public visitor portal (IDEA-15) or account-free request channel [S-49] is a separate decision. Request intake and processing support the controller's response duties [S-10][S-30].
- Client and agency exports cover offboarding return [S-10] and reporting. LinkedIn member data is not exportable [S-82]; X exports carry identifiers only within its redistribution cap [S-87].
- export_artifacts: id, agency_id and client_id (composite foreign key), requested_by_membership_id or credential_id, data_classes, includes_financials, status, created_at, expires_at, revoked_at, file_ref, kek_id, wrapped_dek, download_token_digest. Artifacts are encrypted with AESGCM bound to export_id, agency_id, and client_id [S-93]. Downloads go through the authenticated API, which re-resolves the 002 scope at download time (backend/app/services/access.py); includes_financials requires can_view_financials; responses keep Cache-Control: no-store. Development uses no public signed URLs, and any later signed URL is never logged or committed. Candidate lifetimes: artifact 7 days, download token 15 minutes.

## 12. Backup and restore
No backup tooling exists; 020 implements it under this contract (acceptance criterion 4):
- Journal: each tombstone and consent withdrawal is also written, through a transactional outbox, to an independent append-only journal with monotonic journal_seq and an HMAC chain, because point-in-time recovery loses entries after the recovery target [S-103]. Development uses a separate local database or file; the production store is a hosting decision. Journal retention is at least the longest backup retention.
- Runbook: (1) stop workers and block tracking_app with NOLOGIN or pg_hba.conf, because ALLOW_CONNECTIONS false would also block maintenance [S-103]; (2) recover and verify the Alembic head; (3) insert a restore_epochs row with reconciled_at NULL; (4) import journal entries above the restored maximum sequence and idempotently re-run tombstone deletions and consent withdrawals across raw, derived, cache, outbox, and export data; (5) confirm destroyed KEKs and per-client keys remain destroyed; (6) invalidate cache epochs; (7) set reconciled_at with counts; (8) restore login and start workers. Erasure is tracked and reapplied on restored systems [S-17].
- Readiness: /health/ready reports not_ready with reason restore_reconciliation_pending while the latest epoch is unreconciled or the live (system_identifier, timeline_id) differs from the recorded fingerprint [S-104]. The explicit epoch is primary because pg_restore into the same cluster changes neither value; runtime access to the control functions must be tested on a disposable database.

## 13. Residency and transfers
The storage region stays a deployment setting, recorded on each client workspace and in a transfer register; no region, hosting vendor, or sub-processor is chosen. Remote support access also counts as a transfer [S-24].

| Option | Description | Trade-offs |
|---|---|---|
| R1 One region per deployment | All tenants share one region | Simplest; transfer mechanisms needed for clients elsewhere; exposed to localization rules |
| R2 Per-workspace region pinning | Separate regional deployments; each workspace belongs to one | Supports localization; higher cost; cross-region agency views need design |
| R3 Primary region plus in-country copies where required | Mixed | Ambiguous under the Saudi draft [S-42]; complex deletion fan-out |

Recommendation: choose after Q-003; design for R1 at launch with no cross-deployment data sharing, so R2 remains possible. Facts for Q-003: EU transfers need adequacy or safeguards, possibly with technical measures [S-24][S-25]; the EU-US Data Privacy Framework stands with an appeal pending, and UK adequacy was renewed in December 2025 [S-26]; the UK applies a "not materially lower" test and the UK Extension [S-27]. Egypt requires controller and processor licenses, a cross-border license naming countries and storage locations, and a local representative; the regularization period ended on 31 October or 1 November 2026, as sources differ [S-33][S-34][S-35][S-36][S-38]. Saudi Arabia permits SCC transfers today [S-39][S-43], but a draft would require in-Kingdom storage (consultation closes 2026-11-05) [S-42]. UAE federal rules are unsettled, and DIFC and ADGM apply only to entities established there [S-45][S-47][S-49][S-50]. Qatar is permissive, Bahrain, Jordan, and Morocco use approved lists or authorizations, and Kuwait has no comprehensive law [S-51][S-52][S-53][S-54][S-55]. The register records each sub-processor and recipient with location, mechanism, DPF and UK Extension status, and verified_at [S-16].

## 14. Provider-specific policy table
Contract fields: provider, rule_id, data_class, retention_limit, deletion_trigger, delete_sla, required_callback, refresh_obligation, hashing_rule_version, consent_purposes, export_allowed, combination_allowed, source_ref, verified_at, review_due_at, status (current, stale, unsupported). Rows are versioned code data. A stale row blocks the affected connector feature instead of defaulting to permissive. Every row is re-verified at connector specification time; none implies app approval. A Facebook Login deauthorize callback, if Facebook Login is used for connectors, is unverified because current documentation was not found [S-92]; confirm it in 009.

| Provider and data | Retention limit | Deletion trigger and SLA | Callback or refresh | Hashing, consent, and use limits | Source | Re-verify |
|---|---|---|---|---|---|---|
| Meta platform data | Until no longer necessary; includes derived and aggregated data | User, client, or Meta request, or product end: as soon as reasonably possible | Signed data deletion callback; annual Data Use Checkup | Per-client separation; no cross-client aggregation | S-61, S-62, S-66 | 009, 010 |
| Instagram API with Instagram Login | Meta rule; references and metrics, not media archives | Deauthorize: revoke, disconnected state, purpose-end deletion | Deauthorize and deletion URLs; refresh after 24 hours, before 60 days | App Review, Advanced Access, Business Verification are prerequisites | S-63, S-64, S-65 | 010 |
| Meta Conversions API and Pixel | Events older than 7 days rejected; Meta deletes contact data after matching | Tombstone and consent check before send and replay | None | SHA-256 em, ph, fn, ln, db, ge, ct, st, zp, country; never hash IP, user agent, fbc, fbp; verifiable consent; LDU for listed US states; no sensitive or under-13 data | S-67, S-68, S-69, S-70 | 014 |
| YouTube authorized analytics | While necessary; authorization rechecked every 30 days | In-app revocation: revoke now, delete within 7 days; settings revocation: 30 days; user request: 7 days | Optional RISC receiver | Limited Use; no cross-owner aggregation; no derived metrics by default | S-71, S-72, S-73, S-75 | 011 |
| YouTube other authorized and public data | 30 days, statistics included for public data | Expiry; termination: immediately, with certification possible | Refresh or purge job | Shown only to the authorizing user and approved agents | S-72, S-74 | 011 |
| LinkedIn member data | Social activity 48 hours; other member profiles 24-hour cache, not stored | User request or account closure: immediately | Token 60 days, refresh token 365 days; re-consent at expiry | Not for leads, CRM enrichment, audiences, combination, or export | S-80, S-81, S-82, S-84 | 012 |
| LinkedIn organization data | Social activity 6 weeks (6 months if authenticated); profile 8 weeks if authenticated; reporting 1 year | Client offboarding or request: 10 days; termination: immediately for member data | Incident notice within 24 hours | Shortest applicable duration wins | S-80, S-81, S-83 | 012 |
| LinkedIn Conversions API | Conversions within 90 days | Tombstone check before send | None | SHA256_EMAIL; plaintext IP subject to consent; legal basis per event; normalization unverified | S-83, S-85 | 014 |
| X stored content | Kept in sync with X | Deletion, protection, suspension, or request: 24 hours; termination: delete, evidence within 10 business days | Batch compliance jobs (delete, rehydrate, scrub_geo) | Off-X matching needs express opt-in; no model training or off-X ad targeting; export ids only | S-86, S-87, S-88 | 013 |
| Google Ads enhanced conversions | Not researched | Tombstone check before upload | None | SHA-256 email, E.164 phone, names, street; location fields plain; Gmail canonicalization; ad_user_data per upload; no IP for EEA, UK, CH users | S-76, S-77, S-78 | 014 |
| Payment processors (Stripe, Paymob as examples; none selected) | Provider ids, brand, last four, expiry only | Subject deletion detaches per F1 | Webhook signature or HMAC verification | Never PAN, CVC, or raw card posting | S-89, S-90, S-91 | 015 |
| Google sign-in, platform users (D-022, existing) | Issuer and subject only, while linked; no Google token or profile copy | Unlink or account erasure (decision 3) | None; Cross-Account Protection not adopted | Identity scopes only (`openid email profile`); `sub` is never reused and identifies the account, email does not | S-114; auth design | 003-A5 |
| Gmail API sender, platform mail (D-022, existing) | Sent copies remain in the sender mailbox (Gmail behavior, outside application control) | Owner revokes the authorization in their Google account | Refresh token in ignored .env; 7-day expiry in Testing publishing status | `gmail.send` only; no inbox read or modify | Auth design; review-amendments G-01, G-02 | Decision 5; 020 |

Reconciled 2026-11-04. Rows for client connectors remain **proposed** and are re-verified in their specifications. The two Google rows describe **existing** platform identity and mail behavior merged under D-022. They are not connector authorizations, and nothing in them implies Google app verification or production delivery.

## 15. Roles and responsibilities

| Party | Candidate position (legal review required) | Consequence |
|---|---|---|
| Client business | Controller for its visitors, leads, and customers | Chooses the lawful basis per purpose [S-3]; answers subject requests |
| Agency | Processor for the client, or controller where it sets its own purposes | Instructions flow from client contracts |
| Platform operator | Processor, or sub-processor when the agency processes for its client [S-10][S-15]; controller for platform users, security telemetry, and billing; CCPA service provider or contractor where applicable [S-56][S-57] | Data processing agreement template, active sub-processor change notice [S-15][S-16], processor records [S-10], rights-assistance tooling, end-of-service return or deletion |
| Ad platforms | Joint controller with the advertiser for pixels and list matching [S-21]; Meta processor for matching and joint controller for certain event data [S-67] | Named recipients, not platform sub-processors [S-16] |
| Hosting and mail vendors | Platform sub-processors (none selected) | Register entries with location and mechanism |

Own-purpose use of client data (cross-client benchmarks, model training, product analytics on end-user data) would make the platform a controller [S-15] and conflicts with Meta and YouTube terms [S-61][S-72], so it is excluded unless separately decided. Egypt licenses both controllers and processors [S-35]; Saudi registration may extend to controllers transferring abroad [S-44], and a monitoring-heavy product may require a DPO [S-39]. The UAE regulator is being reorganized [S-46]. Breach clocks (EU 72 hours [S-11], Egypt 72 hours plus 3 working days to subjects [S-35], Saudi Arabia 72 hours [S-42], LinkedIn 24 hours [S-80], Meta as soon as practicable [S-61]) require a per-tenant impact query and a runbook, not automated external mail (Q-008).

## 16. Implementation slices and status
**003-A: govern current data.** Existing stack, no new dependency, no dependence on Q-003. Platform users and invitees are the only personal data held today. Reconciled 2026-11-04: 003-A is split into independently reviewable slices.

| Slice | Content | Status | Schema, API, and privilege effect |
|---|---|---|---|
| 003-A1 | Data-class registry: every stored column mapped to a class, per-table end-of-life rules with decision status, checked against the metadata and the migrated database | **Implemented** (independent work under D-023) | None |
| 003-A2 | Allowlist logging and library logger routing (section 6) | **Implemented** (independent work under D-023) | None |
| 003-A3 | Credential-state lifecycle runner (`python -m app.lifecycle`) for sessions, tokens, challenges, OAuth transactions, rate-limit buckets, outbox rows, and development `.eml` files | **Implemented** under D-024 ([guide](../../docs/engineering/data-lifecycle.md)) | Migration 0005_lifecycle: grants to the new tracking_lifecycle role only |
| 003-A4 | `expires_at` for reset and invitation messages | **Implemented** under D-024 | None |
| 003-A5 | Platform-user account closure and erasure, applying data protection by design to the platform's own users [S-9] | **Implemented** under D-024 ([guide](../../docs/engineering/authentication.md#account-closure)) | Additive migration 0006_account_closure and `POST /auth/close-account` |
| Later 003-A | Unverified-registration purge; ended invitations and service credentials; security and audit event retention; `retention_runs` and `legal_holds` | **Proposed**; values pending Q-012 and counsel | Tables when the first held class becomes eligible |

The 2026-11-03 proposal's schema list (retention_runs, legal_holds, users.erased_at, account_closed and account_erased actions, failure_code expired, and a password-only close-account endpoint) is superseded by the [decision packet](decision-packet-003a.md):
- The mail expiry already exists as `expired_before_delivery` (D-022).
- A3 needs no run table.
- Closure must also cover Google-only accounts.

Closure concurrency analysis (decision 3). Tenancy mutations lock the agency row `FOR UPDATE` before checking Owners. The Owner count includes only memberships whose user is active. Closure locks the user row first, which is the existing authentication order, and then each agency of the user's active memberships in agency-ID order. A co-owner's demotion, disablement, or closure therefore serializes on the agency row. Whichever commits second sees the first change and is refused if no other active Owner would remain. The existing user lock is `FOR NO KEY UPDATE`, which is compatible with the foreign-key `KEY SHARE` locks taken by audit inserts that reference the user. Tests must cover both commit orders and concurrent closure of two co-owners.

Acceptance:
- L1: the registry passes on the current schema and fails on a synthetic unclassified column (**passes**).
- L2: cases M1-M3 and M6 (**pass**).
- L3: the runner deletes only rows past boundaries; reruns are idempotent; a concurrent second runner exits; an interrupted batch is retried on the next run without skipping eligible rows (**passes**).
- L4: undelivered reset and invitation mail past token expiry loses its payload and is not retried (**passes**).
- L5: the unverified-account rule spares verified users and members.
- L6: closure revokes sessions, removes credentials, tokens, challenges, OAuth transactions, and the external identity, frees the email and the Google subject, preserves audit rows, and refuses the last active Owner under concurrency.
- L7: tracking_app still cannot update or delete audit or security events, and the lifecycle role cannot touch users, tenancy, audit, or security rows.
- L8: tests run on the disposable database, and tracking_sys receives only the reviewed additive migration at its authorized rollout step.

The decisions were recorded as D-024 on 2026-11-04. L1-L4, L6, L7, and L8 pass on the disposable database. L5 remains pending, because the unverified-registration rule was not approved. The native rollout of 0005/0006 and the lifecycle role has not been performed.

- **003-B: consent and deletion contracts.** Status: **contract implemented** under D-025 in `app.privacy.consent`, `app.privacy.collection`, and `app.privacy.deletion`, with no tables. J1 strict opt-in is the only enabled profile; tombstones block replay and require consent recorded after deletion unless the subject objected, and last for the workspace lifetime. The consent, deletion-request, and tombstone tables, the journal outbox, and the enforcement points E1-E6 belong to 004, 005, 006, 014, and 015, which must verify C1-C5, M4-M5, and D1-D2 end to end.
- **003-C: provider rows and secrets.** Status: **contract implemented** under D-025 in `app.privacy.token_secrets` and `app.privacy.providers`. The TokenSecretReference table belongs to 009, provider-row re-verification to 010-016, export artifacts to 016, and managed key custody to 020; D3 to D5 are verified end to end there.
- **003-D: restore verification.** Status: **contract implemented** under D-025 in `app.privacy.restore` (HMAC-chained journal, re-application plan, idempotent reconciliation, readiness gate). The journal store, restore_epochs, readiness integration, and the restore drill (R1-R4) belong to 019 and 020.

Both social analytics and attribution, and multi-agency isolation, remain required launch scope (D-004, D-005). Under D-025 the specification closes at contract level. Each consuming specification lists its 003 obligations in its own spec.md, and no end-to-end enforcement is claimed before those consumers exist.

## 17. Acceptance case mapping

Reconciled 2026-11-04 status per criterion:
- Criterion 1: **contract verified** (C1-C3, C5 against `app.privacy.consent`); end-to-end verification transferred to 004, 005, and 014 (D-025).
- Criterion 2: logs **implemented and verified** (M1-M3, M6); form telemetry **contract verified** (M4, M5 against `app.privacy.collection`), with tracker and ingestion verification transferred to 005 and 004.
- Criterion 3: the platform-account scope is **implemented and verified** (003-A3, 003-A5). Subject and connector deletion, replay blocking, and outcome reporting are **contract verified** (D2, D4, D5, D3 at contract level); raw, derived, cache, and export coverage is transferred to 004, 006, 009, 014, and 016.
- Criterion 4: **contract verified** (R1, R2, R4 against `app.privacy.restore`); the restore drill is transferred to 019 and 020.

| Criterion | Slices | Test cases (synthetic fixtures only) |
|---|---|---|
| 1. Consent-violating events enter neither prohibited storage nor an outbound queue | 003-B, 004, 005, 014 | C1 opt-in profile with unknown consent: event not persisted, counter incremented, no payload stored; C2 analytics granted and ads.measurement denied: event stored, no ad outbox row; C3 withdrawal after enqueue: delivery claim suppresses and clears the payload; C4 tracker sets no identifier and sends no identifying request before consent; C5 GPC under a US profile maps to LDU or suppression |
| 2. Password and payment fields excluded from telemetry and logs | 003-A (logs); 003-B, 005 (forms) | M1-M6 |
| 3. Deletion covers raw, derived, caches, exports and blocks replay | 003-A (accounts), 003-B, 003-C, 016 | D1 subject deletion removes raw, lead, link, derived, cache, export, and queued items; D2 replay of a pre-deletion event id or idempotency key is rejected at ingestion and enqueue; D3 connector disconnect revokes the token at a mocked provider, deletes ciphertext, and purges provider data within its row SLA; D4 unsupported provider deletion is reported, never marked done; D5 client offboarding destroys the per-client key, and old pseudonyms no longer match |
| 4. Restore reapplies tombstones before service | 003-D, 019, 020 | R1 restoring a pre-deletion backup keeps readiness not_ready and tracking_app unable to log in until reconciliation; R2 after reconciliation, deleted subjects and withdrawn consents are absent; R3 a replayed pre-deletion event is still rejected; R4 rerunning reconciliation is idempotent |

## 18. Owner decisions required
Reconciled 2026-11-04: decisions 1-5 block 003-A and are presented in the decision packet. Decisions 6-17 belong to 003-B to 003-D and later specifications and are not needed for 003-A. None is recorded as approved.

| # | Decision | Recommendation | Alternatives | Affects |
|---|---|---|---|---|
| 1-5 | 003-A slice boundaries, retention for current records, account closure and erasure, privilege model, mail cleanup | Superseded on 2026-11-04 by the [003-A decision packet](decision-packet-003a.md), which reflects 0004_identity, Google-only accounts, and the D-022 mail expiry. A MultiFernet mail keyring remains a 020 candidate. | See the packet | 003-A, 017, 020 |
| 6 | Markets and jurisdiction profiles (Q-003) | Decide with counsel before any real end-customer data; no market inferred | Launch with J1 only while markets stay open | 003-B, 004, 005, 013-015, 020 |
| 7 | Consent default and Consent Mode | J1 until Q-003, then J2 profiles; basic consent mode | J2 immediately; J3; advanced mode | 003-B, 005, 014 |
| 8 | Consent capture (Q-010) | Minimal first-party consent API in the tracker that also accepts external platform signals; no vendor | Require a third-party consent platform; build a full banner product | 005, 018 |
| 9 | Future class retention (Q-012) | Treat section 4 values as planning candidates; set final values per market with counsel | Client-configurable within platform maxima; shorter defaults | 004-008, 016, 020 |
| 10 | Collection after deletion and tombstone retention | Block replay of anything received before effective_at; allow new collection only with consent recorded after deletion, unless the subject objected [S-8]; keep subject tombstones for the workspace lifetime | Permanent suppression; tombstones only for backup plus replay windows | 004, 006, 014, 020 |
| 11 | Financial records on subject deletion | F1, plus F3 where counsel confirms a duty | F2 | 007, 008 |
| 12 | Internal deletion SLA | 72 hours for automated targets; X content 24 hours; shorter provider rows prevail | Statutory clock per jurisdiction only | 003-B, 009-015 |
| 13 | Residency approach | Region as a deployment setting; R1 after Q-003 without cross-deployment sharing | R2; R3 | 017, 020 |
| 14 | Roles and contracts | Legal review of the processing agreement, sub-processor register, and positions; prohibit own-purpose use of client data now [S-15] | Postpone legal review until the first paying customer (not recommended) | 015-017, 021 |
| 15 | Provider restrictions as product constraints | Accept LinkedIn member-data exclusion from attribution and CRM enrichment, YouTube aggregation and derived-metric limits, and X opt-in matching; do not apply for the YouTube audited exception now. Both launch capabilities (D-004) remain | Apply for provider exceptions or partner programs (cost and review time) | 008, 011-013, 016 |
| 16 | Key custody and journal store | Local keyring now; production KMS or HSM, journal, and export storage chosen with hosting in 020 | Select a vendor now (premature without Q-003 and Q-004) | 009, 016, 020 |
| 17 | Public subject request intake (IDEA-15) | Defer; provide agency- and client-side request tooling first | Public account-free request form [S-49] | 018, 021 |
