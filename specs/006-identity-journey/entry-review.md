# Specification 006 entry review

Date: 2026-11-11. Status: preparation record under D-039. This review does not authorize implementation, schema, dependencies or publication.

## Baseline reviewed

| Item | Value |
|---|---|
| `origin/main` after fetch | `c251e20bc93d65fa1e5fa4fea46505f7ee03c5cb`, "Merge pull request #4 from nebo23/codex/spec-005-links-tracker" (2026-11-11). |
| Merge parents | `e8ef587` (Spec 004 merge, previous main) and `3bdcc89` (Spec 005 reviewed and published head). |
| Merge tree | `8119766f4abf3caa2be15c7e8f383db52ca06c40`, identical to the tree of `3bdcc89`; `git diff 3bdcc89 c251e20` is empty. |
| Spec 005 evidence at that head | Tested tree `cbccaf6`: 616 backend, 67 Node and 44 browser tests passed (see [005 evidence](../005-links-tracker/evidence.md)). Not re-run here, because this preparation changes no code. |
| Branch and worktree | `codex/spec-006-identity-journey` created from `origin/main` in `.worktrees/spec-006-identity-journey`; no earlier 006 branch existed locally or on the remote. Upstream tracking of `main` was removed so the branch cannot be pushed to `main` by default. |
| Other workspaces | The main workspace (branch `codex/spec-003-privacy-data-policy` with staged, unstaged and untracked owner work), the 004 worktree and the 005 worktree were not modified. Local `main` remains at `3a3bba1` and was not updated. |
| Owner configuration and database | `.env`, credentials and native `tracking_sys` were not read or accessed. |
| API contract | `contracts/openapi.json` lists 75 operations. |

The original source PDF is kept outside the workspace ([source provenance](../../docs/source/README.md)). PDF-027 to PDF-030 and PDF-050 were reviewed through the maintained [feature register](../../docs/product/feature-register.md) and [source review](../../docs/product/pdf-review.md):

| Item | Register note | Carried into 006 as |
|---|---|---|
| PDF-027 Cross-device identity resolution | Deterministic matching is the initial proposal. | Trusted, verified assertions per device (design section 4). |
| PDF-028 Identity stitching | Use verified identifiers; do not automatically merge shared phone numbers. | Rules R1-R5, contested keys, no automatic person merge. |
| PDF-029 Unified customer profile | Isolate profiles within each client. | Client-scoped persons and per-client keys. |
| PDF-030 Customer journey timeline | Preserve source, evidence, occurred_at and received_at. | Timeline entries carry all four (design section 9.2). |
| PDF-050 Lead inbox / mini-CRM (partial) | Propose a read model first; a full CRM requires a separate decision. | Read-only lead inbox without contact values or workflows. |
| Source review | "Do not merge people solely because of an IP address or shared device." | Fingerprinting, IP and device matching excluded. |

## Inherited contracts inspected

| Area | Merged code | What 006 must respect |
|---|---|---|
| Tenancy and authorization | `app.services.access.resolve_scope`, `app.services.tenancy` (roles Owner/Admin/Analyst/ClientViewer, `MANAGERS`, client grants with `can_view_financials`) | Every read and write re-resolves scope; users never hold `events:write`; read and ingest keys are distinct kinds. |
| Per-client identity keys | `app.privacy.deletion.canonical_identifier`, `keyed_identifier`, `subject_key` | HMAC with the client ID in the message under a random per-client key; email by account convention; phone trunk-zero rule flagged as a 006 review item. |
| Consent | `app.privacy.consent` (J1, `Purpose.IDENTITY_LINK`, `require_all`, GPC set) and `app.services.collection.record_consent`/`consent_view` | Unknown, denied, withdrawn and expired all deny; consent belongs to a collection subject; GPC does not cover `identity_link`. |
| Erasure and replay | `erase_subject`, `deletion.admission`, `deletion_tombstones` (types `subject_token`, `event_id`), `TombstoneKeyring` | Tombstones for the workspace lifetime; new collection after deletion only with later consent and no objection; blocking by server time and IDs, never client time. |
| Event trust and deduplication | `app.collection.contract` (`TRUST_RANK`, `fingerprint`, `REQUIRED_PURPOSES`), `admit` | Browser rank 1, server/webhook rank 2; one row per client and event ID; trusted upgrades; server events also need a subject token. |
| Link provenance | `managed_links`, `collected_events.link_id`, tracker `ts_link` handling | A link reference is limited-trust provenance and never a visitor identifier; disabled links still identify history. |
| Tracker | `packages/tracker-js` 0.5.4: `grant`, `resume`, `withdraw`, `erase`, `refresh`, capture APIs, `state()`; subject token in `sessionStorage` for at most 24 hours; token not exposed to the host page | A browser subject is a short-lived session identifier; cross-device association needs evidence on each device. |
| Concurrency | Client privacy lock (namespace 4004) for admission, consent, erasure and lifecycle | Identity writes must use the same lock and ordering. |
| Data policy and lifecycle | `app.data_policy` registry, `app.services.lifecycle` (395-day events and subjects) | New tables need registry classes and lifecycle cascade under the client lock. |

This review read the source modules above. The existing test modules that cover them were identified but not read in detail or executed: `backend/tests/test_privacy_deletion.py`, `test_privacy_consent.py`, `test_collection_contract.py`, `test_event_link_contract.py`, `integration/test_collection.py`, `integration/test_event_links.py`, `integration/test_lock_order.py`, `integration/test_tracker_journey.py`, and the tracker's Node and browser suites. The implementation slices must keep them passing.

One read-only check was run: the merged `canonical_identifier` was evaluated in the project virtual environment on fictional phone and email inputs. Its outputs are recorded in [design section 5.1](design.md#51-review-of-the-candidate-trunk-zero-rule). The scratch script was removed afterwards.

## Gaps 006 must close

1. No person-level entity, identity key table, link, or timeline exists. Collection subjects are per browser session or server record.
2. A browser subject token is invisible to the host page by design, so there is no safe path for a client's backend to say "this browser session verified this identifier". The design proposes a one-time handoff.
3. `deletion_tombstones` accepts only `subject_token` and `event_id`, so erased identifiers and assertion retries cannot yet be blocked.
4. The phone canonicalization candidate produces false merges under a country assumption (design section 5.1).
5. Grants have no person-level visibility control; today any client reader would see whatever a new endpoint returns.
6. D-025 transferred end-to-end verification of 003 acceptance criteria 1, 3 and 4 to consuming specifications. 006 must prove identity-link consent (E3), deletion of identity links, and unmerge provenance.

## Decision state

Q-002 and Q-012 remain open; Q-008 is narrowed to production mail and Facebook sign-in and no longer affects 006. The [decision packet](decision-packet.md) reconciles them and identifies which items block each slice.

## Frontend boundary

No wireframe, mockup, dashboard, React component or visual prototype was produced. The design illustrates the profile and timeline with synthetic API responses only. Customer-facing frontend work waits for the owner's brief, design and brand identity.
