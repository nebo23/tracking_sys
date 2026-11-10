# Privacy, Gmail delivery, and Google sign-in amendments

Historical handoff notice (2026-11-04): the Google/Gmail/OTP continuation below was subsequently approved under D-022, implemented under specification 002, and merged in PR 1 (`98747a2`), including the R-01 to R-03 authentication corrections. Its proposal wording and unchecked preparation checklist are historical, not evidence that those features remain unimplemented. The current specification 003 entry point is [implementation-prompt.md](implementation-prompt.md). Retain this record for traceability; use the merged code, auth design, and test evidence for actual behavior. Provider configuration and live-delivery claims still require their own evidence.

Status: Owner-selected feature direction; concrete design below is proposed for review before new schema/dependency implementation. No provider credentials, live email delivery, or OAuth implementation are included in this handoff. Prepared: 2026-11-04.

## Scope and authority

The owner explicitly selected both sending transactional email from their Gmail account and adding Google sign-in, then requested this continuation within the privacy specification's amendment file. A subsequent explicit choice selects numeric email-verification OTPs instead of the current verification link. See D-021 and the [complete implementation entry point](../002-tenancy-access/review-amendments.md).

This direction revisits the Google-only deferral in D-018/D-019. Facebook remains deferred. The original local email mode remains the safe default. This request does not approve all of [the existing privacy design](design.md), its candidate retention/deletion periods, a new hosting region, paid services, deployment, or a production-readiness claim. Preserve that owner-authored design and research without rewriting their proposed decisions as approved.

The feature work touches authentication/configuration/mail code governed by specification 002; record the reviewed auth-design, schema, contract, dependency and evidence changes there as well. Its privacy/security requirements and continuation checklist are maintained here as the owner requested. Do not treat Google sign-in as an analytics-connector authorization or silently change the multi-agency launch scope.

## G-01: Separate sender authorization from user sign-in

| Flow | Authorized person and purpose | Minimum access |
|---|---|---|
| Gmail delivery | The owner authorizes one designated sender mailbox to send verification, recovery and invitation messages. | Propose Gmail API `gmail.send` only; no inbox read/delete, contacts, Drive, analytics, or broad Gmail scope. |
| Google sign-in | Each application user authenticates their own identity. | `openid email profile`; no request for the user's Gmail sending permission or offline access solely to log in. |

Use separate OAuth client configuration/secret references for these flows. They may belong to the same owner-controlled Cloud project if deliberately configured, but sender consent must never be granted by every signing-in customer. A sender refresh token is not a sign-in token or application session credential.

Google lists `gmail.send` as sensitive. Confirm the actual consent-screen audience, test users, publishing/verification requirements and sender limits for the owner's project; do not claim app approval or guaranteed inbox placement. External OAuth apps in Testing generally receive refresh tokens with a seven-day lifetime when requesting Gmail scope; document reauthorization/production-consent requirements instead of treating a short-lived setup as permanent delivery.

## G-02: Proposed Gmail adapter

- Preserve the encrypted durable outbox and atomic registration/verification/reset/invitation transactions. Make delivery an explicit adapter selected by validated settings (`local` as default; proposed `gmail` as an opt-in mode).
- Use Gmail API `users.messages.send` with a properly encoded MIME message and the authenticated sender or an authorized alias. Do not spoof arbitrary From addresses. Use the reviewed numeric verification OTP contract in G-07; password reset and invitation messages retain links unless separately approved otherwise.
- Use an owner-authorized refresh token for offline sender access. Bound connection/read timeouts and retry attempts; classify revoked/invalid credentials, quota/rate limiting, temporary failure and malformed payload with sanitized codes. Do not log provider response bodies or recipient/token payloads.
- Reuse a stable application message identity across retries. Gmail acceptance and database commit are not atomic, and a stable Message-ID does not guarantee provider deduplication. Explicitly handle/document ambiguous send outcomes and possible duplicate delivery; do not promise exactly-once email.
- Preserve encrypted payload clearing after confirmed delivery. Keep local-mode regression coverage. Evaluate delivery relative to token expiry and privacy retention proposals, but do not silently enact the unapproved ten-attempt/retention periods from the existing privacy design.
- Document the one-batch worker and how the owner runs it. Do not add a scheduler, broker or hosting service by implication. Running the API alone must not be described as running the mail worker.
- Update configuration validation deliberately. Replacing the current unconditional production rejection requires a reviewed production rule set: required external adapter secrets, secure cookies, HTTPS origins/links, fail-closed disabled settings and relevant tests. Successful Gmail setup alone does not establish production readiness or authorize deployment.
- Provider smoke tests are separate from automated fixtures. Use only the owner's explicitly designated test recipient after configuration and authorization; no outreach or customer mail is implied by this preparation task.

## G-03: Proposed Google sign-in design to review

Prefer a server-side authorization-code/OpenID Connect flow that integrates with the existing opaque application sessions. Before implementation, update the authentication design with precise endpoints, redirect URIs, callback method, transaction storage, account-linking policy, schema/privileges and dependencies; present that concrete design for owner approval under the working agreement.

Required design properties:

1. Browser-bound, unpredictable, expiring, single-use state and nonce; use PKCE where supported by the selected Google client flow. Bind return destinations to an explicit allowlist and forbid arbitrary redirect URLs. Cover login CSRF, replay, cancellation and provider failures.
2. Server-side validation of the ID token signature using trusted Google keys, allowed issuer, expected audience, expiry and nonce. Never accept a client-supplied user ID/email as proof, decode a JWT without validation, or use an access token as if it were an ID token.
3. Identify the external account by validated provider/issuer and `sub`, not by email alone. Propose an additive external-identity table with a unique provider/subject pair and a foreign key to `users`. Review constraints, runtime privileges, races, migration recovery and deletion implications before implementation.
4. Never silently link an existing password account by matching email. Propose explicit linking from a recently authenticated existing account, protected by session CSRF/state, or return an actionable safe conflict and defer linking. Decide the supported behavior in the reviewed contract; do not overwrite a password or transfer an identity already linked elsewhere.
5. Require appropriate verified-mailbox proof. Google's guidance distinguishes Gmail/verified Workspace addresses from third-party email addresses where Google may not remain authoritative even with an `email_verified` claim. Specify when the existing email-verification flow is still required. A verified email is not proof of a human, absence of spam, or permission to join an agency.
6. Google-only accounts must not receive a fabricated password or bypass the existing disabled-user checks. Define safe password creation/reset and account recovery for them; preserve account-enumeration protections and prevent weak fallback takeover.
7. Issue the existing application session cookie after successful local authorization/transaction commit. Preserve expiry, idle timeout, revocation, Origin/CSRF, cookie/Bearer ambiguity rules, and rate limits. A Google token does not carry trusted agency roles or client grants, and new accounts receive no agency membership by inference.
8. OAuth callback protocol may carry an authorization code/state in its query or form. Document this deliberate protocol-specific exception to the original body-only token convention; never put application session tokens or provider access/refresh tokens into return URLs. Redact callback access logs and prevent credential-bearing redirects/referrer leakage. Do not broadly disable protection on unrelated routes.
9. A provider redirect will not necessarily carry the application's exact Origin header. Protect its callback using the reviewed state/nonce/browser binding and allow it only at that explicit callback route; do not remove the existing mutation Origin policy across the API.
10. Keep React implementation in its approved specification. Provide a backend/browser smoke walkthrough for Google redirects; a Swagger JSON request is not a substitute for a real browser OAuth exchange. No additional Swagger feature was requested.

## G-04: Configuration and privacy inventory

Proposed names below are a design contract, not values already configured. Final names must be reviewed and used consistently in settings, examples, Docker, tests and documentation.

The [Claude implementation prompt](../002-tenancy-access/implementation-prompt.md) coordinates private configuration. Missing names have been staged with blank values/safe defaults in the ignored local `.env`; `.env.example` documents them without credentials. Staging these names does not implement the Google/Gmail/OTP features or verify the owner's provider values.

| Variable | Purpose | Treatment |
|---|---|---|
| `TRACKING_MAIL_MODE` | `local` or reviewed `gmail` adapter selection. | Default to local; validate required settings when enabled. |
| `TRACKING_GMAIL_CLIENT_ID` | Sender OAuth client identity. | Backend configuration; distinct from sign-in audience. |
| `TRACKING_GMAIL_CLIENT_SECRET` | Sender client secret. | Secret; ignored local configuration only. |
| `TRACKING_GMAIL_REFRESH_TOKEN` | Owner's offline sender authorization. | Secret; ignored local configuration only. |
| `TRACKING_GMAIL_SENDER` | Authorized sender address. | Configuration/personal data; never use the address as a committed real example. |
| `TRACKING_GOOGLE_SIGN_IN_ENABLED` | Explicit provider feature flag. | Disabled until configured and reviewed. |
| `TRACKING_GOOGLE_CLIENT_ID` | Sign-in audience. | Configuration; exact match in token validation. |
| `TRACKING_GOOGLE_CLIENT_SECRET` | Server-side sign-in client secret, if required by the selected flow. | Secret; backend only. |
| `TRACKING_GOOGLE_REDIRECT_URI` | Exact registered callback. | Explicit local HTTPS/loopback development policy and production URI; not a wildcard. |
| `TRACKING_OTP_SECRET` | Proposed independent keyed-verifier secret for numeric challenges. | Generate locally with at least 32 random bytes after the design is approved; backend secret, unrelated to Google credentials. |

Use placeholders/blank values in tracked examples. The owner enters secrets in ignored `.env` or the separately ignored `.env.docker`; do not ask them to send tokens in chat, paste secrets into a prompt, or commit downloaded credentials/token JSON. A reusable owner-operated sender authorization tool may be proposed if necessary; isolate its dependencies and keep generated tokens outside tracked files. Never bundle a personal mailbox refresh token into an image or frontend.

Add to the reviewed privacy inventory: provider subject, profile/email claims, one-time OAuth transactions, sender authorization, consent scope, revocation, and failure logs. Minimize stored claims. Discard sign-in access/ID tokens after validation unless a separately reviewed purpose requires retention; sign-in alone does not require storing a user's refresh token. Integrate secret custody/revocation with the existing `TokenSecretReference` proposal without prematurely implementing a KMS/vendor. Retention periods, unverified-account deletion, and identity unlink/erasure policy retain Q-012/design approval.

## G-05: Tests and owner review

- [ ] Record the concrete Google/Gmail schema, dependencies, account-linking and verification decisions before dependent implementation. Choose maintained validation/OAuth libraries with evidence, pin/hash approved packages in the project environment, and do not hand-roll token verification.
- [ ] Test Gmail send selection, MIME construction, refresh, invalid/revoked credentials, timeouts, quota failures, sanitized errors, retry ambiguity, encryption/clearing and preservation of local capture using controlled provider substitutes. Automated tests send no real mail.
- [ ] Test Google success and rejection of wrong signature, issuer, audience, expiry, nonce/state mismatch, replay, cancellation, unverified/third-party email cases, existing-email conflicts, disabled users and concurrent linking/registration.
- [ ] Test session commit/cookie behavior, logout/revocation, CSRF/Origin boundaries, rate limits and cross-agency denial after federated login. Preserve all existing password flows.
- [ ] Test fresh/repeat additive migration and model agreement on disposable PostgreSQL, plus safe recovery and populated-state guards. Native schema changes remain a separately reviewed rollout.
- [ ] Update sanitized OpenAPI, example configuration, Docker forwarding, auth/mail walkthrough and evidence. Distinguish automated substitutes, live Google sign-in, Gmail acceptance and actual owner receipt; each needs its own observed evidence.
- [ ] Present the completed slice and limitations for owner review before any push/PR. Missing credentials or provider review must be reported precisely, without claiming that planned external delivery already works.

## G-06: Owner-operated Google Console setup for local testing

This is a proposed concrete local setup to align credentials with implementation; it is not a claim the callback/helper already exists.

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select an owner-controlled development project, for example `Tracking System Development`. Enable the Gmail API under APIs & Services / Library. Google sign-in does not require broad Gmail authorization.
2. Open Google Auth platform / Branding, supply the application name and the owner's support/contact emails. For a personal Gmail account and a SaaS test, select External, keep the publishing state Testing, and add the owner/sender and intended test sign-in accounts under Audience / Test users. Do not publish or buy services as a side effect.
3. Under Data Access, declare the identity scopes `openid`, `userinfo.email`, `userinfo.profile` and the send-only Gmail scope. The declared project inventory does not mean every flow requests every scope: sign-in requests only identity scopes; sender authorization requests only `gmail.send`.
4. Create a Web application OAuth client named `Tracking System Sign-in Development`. Proposed local Authorized redirect URI: `http://127.0.0.1:8000/auth/google/callback`. The implementer must use that exact URI, or update both configuration and Console together after reviewing a different route. A server authorization-code flow does not require a JavaScript origin merely to exchange a code; add explicit frontend origins only if the chosen browser integration needs them. No wildcard URI.
5. For a reusable owner-run local sender-authorization helper, create a separate Desktop app client named `Tracking System Gmail Sender Development`, following Google's installed-app/loopback pattern. This is a local development bootstrap, not a new public SaaS sender-consent endpoint. Review the helper and approved dependencies first; use its loopback browser consent flow to obtain the sender refresh token. A future hosted onboarding model requires its own reviewed client/redirect design.
6. Store downloaded client JSON only in an ignored private location, such as `local-data/google/`, and then map required values into the reviewed ignored settings. Do not paste the JSON, client secrets or refresh token into chat or into a model prompt. Tracked examples contain no values. There is no general API key that replaces these OAuth clients, and no manually typed OTP setting in Google Console.
7. Client ID/secret creation is not completion of sender authorization. The owner must authorize the designated Gmail account through the reviewed helper before delivery can work. Verify the granted send-only scope, token refresh, test audience restrictions and a controlled owner-recipient delivery; keep actual secrets omitted from output.

This setup follows the [Gmail Python setup pattern](https://developers.google.com/workspace/gmail/api/quickstart/python), [consent configuration](https://developers.google.com/workspace/guides/configure-oauth-consent), and [desktop OAuth flow](https://developers.google.com/identity/protocols/oauth2/native-app). Do not copy the quickstart's read-only mailbox scope or global installation commands: this project needs send-only scope and isolated approved dependencies.

## G-07: Numeric verification OTP requested by the owner

Direction confirmed; the following concrete policy is proposed for review before changing the schema/API. Gmail transports the message; this application generates, stores a verifier for, expires and consumes the OTP. Google sign-in is an independent authentication method and does not automatically require another email OTP after an authoritative verified identity has been established.

- Propose a six-digit cryptographically random code, ten-minute lifetime, single use, at most five failed checks per challenge, and a minimum 60-second resend cooldown in addition to the existing independently persisted request limits. These exact policy values require an explicit decision in the reviewed authentication design; they are not existing behavior. Keep codes as strings so leading zeroes survive.
- Bind the challenge to the intended account, verification purpose and a high-entropy challenge identifier. Accept a bounded challenge identifier plus code in the verification request; review how an opaque challenge reference is supplied without revealing account existence. Never locate a user by numeric code alone or expose whether a third-party email already owns an account. Identical codes for different challenges must be safe: the current globally unique token-digest lookup is not the numeric-code identity contract. Keep registration/recovery acknowledgements appropriately generic.
- A numeric code has low entropy: plain SHA-256 by itself permits easy offline enumeration. Use a purpose-separated keyed verifier with a dedicated secret kept outside PostgreSQL, and a standard constant-time comparison. Include the challenge context; never persist a plaintext OTP in the auth challenge table or logs. The existing encrypted outbox may temporarily contain the code for delivery and must clear it after confirmed delivery.
- Reissue must invalidate the previous verification challenge atomically under appropriate locking. Enforce attempt limits and throttle before expensive work; failed attempts must survive business rollback. Cover parallel checks, replay, resend races, expired/out-of-order messages, and delivery delays beyond expiry.
- On successful verification set `email_verified_at` and consume the challenge atomically. An enabled-but-unverified account remains unable to use password login. Do not infer that an OTP proves a human or prevents all spam, and do not silently change account deletion/retention policy.
- Propose an additive schema/privilege change if needed for challenge ID, verifier and attempt state; review it and its migration first. Do not overload the current `token_digest` field with an incompatible format or inadvertently change reset/invitation links. Define a reviewed rollout cutoff for previously issued verification links and pending verification mail: stop issuing links, do not silently convert queued content, and specify safe OTP reissue. Do not bulk modify native records while preparing the handoff. Update bounded schemas, route responses, mail templates, explanatory comments, diagnostic query references and the OpenAPI contract together.
- Verify correct/incorrect codes, leading zeroes, expiry boundaries, maximum attempts, independent request limits, single-use consumption, resend invalidation, concurrent checks, sanitized responses and encrypted mail delivery using synthetic fixtures. Include a local/owner-operated end-to-end walkthrough. Do not send real verification messages as an automated test side effect.

## Primary references

- [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect): server flow, validated claims and stable subject identity.
- [Google server-side token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token): validation and mailbox-authority distinctions.
- [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes): scope minimization and sensitivity classification.
- [Gmail sending guide](https://developers.google.com/workspace/gmail/api/guides/sending): encoded MIME messages and API submission.
- [Google OAuth web-server authorization](https://developers.google.com/identity/protocols/oauth2/web-server): offline sender authorization and refresh.
- [Google OAuth token lifetime](https://developers.google.com/identity/protocols/oauth2): revocation and Testing-mode refresh-token limitations.

References checked on 2026-11-04. They inform the proposal; they do not constitute provider approval or owner approval of unresolved implementation decisions.
