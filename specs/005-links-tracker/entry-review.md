# Specification 005 entry review

Date: 2026-11-10. Status: **preparation only; implementation, schema and tooling decisions remain unapproved**. Authority: D-032.

Preparation update: [design revision 1](design.md), the [decision packet](decision-packet.md), and the [verification matrix](verification-matrix.md) are now ready for owner review. They remain proposals; the next implementation gate is the recorded selection of D1-D10 or a scoped subset.

Branch: `codex/spec-005-links-tracker`, created from merged `main` at `e8ef587eb4df39f9f0bf1b31421d0a672388e9dd`. PR 3 was merged on 2026-11-10 with verified head `f888197`. Its merge tree is identical to that reviewed head. The root workspace's unrelated changes remain outside this branch. This entry packet is local and has not been uploaded.

## What the project can do now

These are implemented backend capabilities, exercised with synthetic fixtures; they are not a claim of a deployed production application.

| Area | Available in merged code | Boundary |
|---|---|---|
| Foundation | FastAPI, PostgreSQL models/migrations, health/readiness checks, isolated dependencies and optional Docker setup | Native rollout and production deployment are separate actions. |
| Accounts | Registration, numeric email verification, login/logout, sessions, password recovery, invitations, optional Google sign-in and configurable Gmail delivery | Google/Gmail require approved configuration. Development mail capture is available; this review sent no external mail. |
| Agency/client access | Multiple agencies and client workspaces, roles, scoped permissions and separate read/ingest service keys | Backend API workflows; no React dashboard yet. |
| Collection | Browser/server/generic signed-webhook event intake; page views, link clicks, constrained form submissions, lead signals and purchase signals; client-scoped deduplication and trusted upgrades | A synthetic sender can call the API. There is no installable website tracker or named payment/social provider adapter yet. Purchase signals are not verified revenue. |
| Privacy and lifecycle | J1 opt-in enforcement, minimized URLs/forms, consent changes, subject erasure and replay-blocking tombstones, expiry and safe consent handling between cleanup batches | Development retention; remaining provider/export/identity enforcement belongs to later consuming specifications. |
| Diagnostics | Event metadata and daily counters, with bot/internal labels | Not a marketing dashboard, verified human-click metric or attribution report. |

Latest independent verification before merge: **481 suite tests plus two independent reproduction checks passed**, with Ruff, formatting, dependency and diff checks. See [004 final review](../004-event-collection/final-review-2026-11-10.md). There were no reported commit statuses or PR-triggered workflow runs in the connector queries at merge time; local verification is the recorded evidence.

The owner's native database was last documented at `0004_identity`; merged code expects `0007_event_collection`. This session did not inspect or migrate native `tracking_sys`, start the application, deploy it, or claim that the new routes are live there.

Still ahead: website tracker and managed links (005), identity/journey (006), verified revenue and attribution (007/008), provider connectors and social analytics (009-015), reports/SaaS workflows (016/017), React interface (018), release testing and production operations (019/020). The commercial launch still includes both social analytics and attribution for multiple agencies.

## Proposed outcome of specification 005

Connect a client website to the existing collection backend through a project-authored JavaScript tracker, and provide managed links with UTM/provenance and safe redirects. The tracker is separate from React. Custom-domain ownership/TLS/slug-conflict acceptance remains in this specification's draft; it is not silently dropped or treated as permission to buy domains or deploy infrastructure.

Illustrative synthetic journey: an agency manages a link for one client's content; the visitor reaches the allowed destination even if analytics is unavailable; after explicit consent, the tracker obtains the subject token and submits permitted events to 004. This demonstrates collection and provenance, not revenue attribution or automatic identification of the visitor.

## Contracts inherited from merged 003/004

- Use `/collect/v1/{public_key}/consent` for explicit consent issuance/changes, then the scoped events endpoint with the issued subject token. Never embed an ingest service key in browser code.
- Preserve J1: no identifier or identifying telemetry before consent (003 case C4). Define precisely what may load before consent; do not invent cookies, fingerprints or cross-domain identifiers.
- Apply the never-collect and minimization rules before transmission, not only at server admission (003 case M4). Password, payment-card, one-time-code and unmapped form values must be absent from outgoing requests. Do not expand the approved option/code/quantity form classes into email/phone/free text owned by 006.
- Match the strict EventEnvelope and existing field/purpose matrix. Decide whether link provenance fits existing allowed URL/UTM data or requires an explicitly reviewed contract extension; arbitrary campaign/link fields are not implicitly accepted.
- Registered-origin CORS is uncredentialed. JSON preflights and text/plain requests are supported. Confirm retry/backoff and browser visibility of relevant response headers before choosing a tracker transport.
- Preserve consent withdrawal, erasure, replay protection, stable retry IDs and source/client isolation. Generic browser 202 responses do not prove an event was stored.
- Bot/prefetch labels are not proof of a qualified human click. Analytics failure must not break a valid redirect.

## Preparation sequence and decision gates

1. Refresh the detailed 005 design against the merged contracts and map every existing acceptance criterion plus C4/M4 to a testable outcome.
2. Present a decision packet for link/campaign/content-reference/domain models and grants; do not create tables before schema review. Content references must not invent a full social-content system before its specification.
3. Propose URL/redirect safety, slug uniqueness, destination changes, disabling/expiry, UTM conflict rules and retention. Keep open redirects and redirect loops out of the design; any validation network access needs explicit SSRF boundaries.
4. Propose tracker configuration, consent integration, identifier storage/lifetime, withdrawal and erasure behavior, retry limits, form mapping and distribution/versioning. Evaluate whether JavaScript alone or TypeScript/build tooling is warranted; no dependency or CDN is selected here.
5. Separate synthetic domain-verification/TLS tests from live DNS, certificate issuance, hosting and domain purchase. Preserve custom-domain acceptance while presenting its real infrastructure gate explicitly.
6. After approval, split implementation into reviewable slices for link administration/redirects, consent-first tracker integration, then form/domain hardening and end-to-end verification. Exact ordering and schema remain proposals until the design is approved.

Q-001/Q-002/Q-003 remain unresolved where relevant. Q-004/Q-009/Q-012 may affect sizing, tooling and retention. Existing J1 and 004 contracts support independent synthetic design work; unresolved market/provider choices must not silently become defaults or block unrelated preparation.

## Exit from preparation

The next review should present the design, a small decision packet, proposed schema/grants and a regression matrix. No 005 implementation or dependency installation is authorized by this entry review. Upload, native rollout and deployment require their own authorization. The existing local 003 follow-up and other predecessor items P1-P4 remain separate.
