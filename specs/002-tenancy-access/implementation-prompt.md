# Claude implementation prompt: review amendments and Google authentication

Prepared: 2026-11-04. This is an execution handoff for the owner's implementation session. It is not evidence of completed application changes or provider configuration. The owner reports having an OAuth Client ID and Client Secret; their values have not been provided to or verified by the reviewer.

## Task

Complete the independently authorized review amendments, and carry the selected Gmail delivery, Google sign-in and numeric email-verification OTP work through the project's design, implementation, verification and owner-review sequence. Do not stop at a generic plan when an approved independent change can be implemented. Resolve only the remaining material schema, dependency and identity-policy decisions before their dependent implementation; missing provider configuration must not block unrelated work or controlled local tests.

Communicate with the owner in Arabic. Maintain formal English in every project file and code comment.

## Required reading

Read the current source and these files before editing:

1. `AGENTS.md`, `README.md`, and `docs/planning/decisions.md`, especially D-012 through D-021.
2. [Foundation amendments](../001-foundation/review-amendments.md).
3. [Tenancy/authentication amendments](review-amendments.md).
4. [Privacy, Gmail, Google sign-in and numeric OTP amendments](../003-privacy-data-policy/review-amendments.md), including G-06 and G-07.
5. [Tenancy design](design.md), [authentication design](auth-design.md), and their evidence/task files. Inspect the privacy proposal as context without treating its unrelated retention/deletion proposals as approved.

The three amendment files define the detailed requirements. This prompt coordinates their execution; it does not remove their decision or data boundaries.

## Worktree and data boundaries

- Verify the current branch is `claude/development`. Preserve the existing repository, remote and owner edits. Inspect `git status` and relevant diffs before changing files.
- At preparation time, `backend/app/models/tenancy.py` already contains an owner edit; `specs/003-privacy-data-policy/design.md` and `research_notes/privacy-data-policy/` are existing owner work. Amendment files, their task links, D-021 and the configuration template are reviewer preparation. Do not reset, overwrite, broadly stage or claim pre-existing work as your own.
- Use the existing project `.venv` or containers. New approved dependencies must have reviewed versions and updated manifests/locks; no global installation.
- Run migration, concurrency and data-changing integration tests only against a guarded disposable PostgreSQL database. Preserve native `tracking_sys`. Do not seed, downgrade, truncate, delete or reset native tables. Apply a future reviewed additive native migration only at its authorized rollout step.
- Keep Google values, local secrets, generated codes, passwords and real account data out of terminal output, logs, Git, screenshots and model responses. No secret belongs in this prompt.
- Do not push, create/update a PR, merge or deploy before the owner's separate approval of completed work. Use the existing local slice-commit agreement and stage only intended reviewed files.

## Private configuration handoff

The reviewer staged missing configuration names in the ignored root `.env`, with safe defaults and blank provider values. Existing values were preserved. The tracked `.env.example` documents the names without credentials. The directory `local-data/google/` is ignored by Git and can hold the owner's downloaded OAuth JSON. Staged names alone do not make the current application support Google.

| Flow | Local settings/source | Important distinction |
|---|---|---|
| Google sign-in | `TRACKING_GOOGLE_CLIENT_ID`, `TRACKING_GOOGLE_CLIENT_SECRET`, `TRACKING_GOOGLE_REDIRECT_URI`; optional owner-provided Web application client JSON. | The Web application client validates sign-in audiences. |
| Gmail sending | `TRACKING_GMAIL_CLIENT_ID`, `TRACKING_GMAIL_CLIENT_SECRET`, `TRACKING_GMAIL_REFRESH_TOKEN`, `TRACKING_GMAIL_SENDER`; optional separate Desktop app client JSON for the local sender-authorization helper. | The owner grants send-only consent for the designated sender; sign-in users do not grant Gmail access. |
| Numeric OTP verification | `TRACKING_OTP_SECRET` after the reviewed verifier design. | An application-generated independent secret, not a Google client secret. |

The proposed local sign-in callback is:

```text
http://127.0.0.1:8000/auth/google/callback
```

Use that exact route/configuration or coordinate an explicit change with the owner's Console setting. Do not report the callback as implemented before it exists.

Configuration procedure:

1. Inspect only whether the required names are present/nonempty. Do not display `.env` or downloaded OAuth JSON. If importing a JSON file, process it locally, validate its expected `web`/`installed` structure and client purpose, and report only success or missing field names.
2. Preserve all existing database/application values. Import only the explicitly supplied client for the matching flow. Do not silently reuse the sign-in client's credentials for the sender flow.
3. Keep `TRACKING_GOOGLE_SIGN_IN_ENABLED=false` and `TRACKING_MAIL_MODE=local` until the corresponding implementation and required settings are ready. Enable features deliberately for the owner-operated smoke test; do not activate Gmail against an existing native outbox just because credentials are present.
4. If the sender refresh token is missing, implement the reviewed reusable local authorization helper and give the owner its command. It should open the real Google consent page in the owner's browser, request only `https://www.googleapis.com/auth/gmail.send`, and store the result privately without printing it. The owner completes sign-in and consent. Do not ask them to paste a token into chat.
5. Generate a new dedicated OTP verifier secret with secure randomness once its reviewed format is settled; preserve an existing valid value. Keep its value local. Confirm required settings without exposing them.

## Implementation sequence

### 1. Explanatory comments and SQL references

Implement F-02, T-03 and T-04. Cover every requested backend file/class/function, the specified config imports/validators/properties, and every mapped class in the three model files. Include bounded, copyable PostgreSQL read/search query comments with synthetic replacements and explicit tenant scope where relevant. Exclude password hashes, tokens and encrypted mail payloads from diagnostic projections. Explain `Entity` as a mixin with no table.

Keep this slice behavior-preserving and distinguish it from fixes. Do not reformat or revert the owner's edits unnecessarily. Compare executable ASTs for the documentation-only slice; do not invent tests merely to assert comments exist.

### 2. The three review findings

- F-01: Forward/document the explicit allowed origins and frontend origin through Docker configuration. Verify a non-default published API port works with the intended Origin while foreign origins remain denied.
- T-01: Investigate the possible user/agency/audit foreign-key lock cycle with a deterministic disposable PostgreSQL test. Select a supported lock fix that retains serialization and correct audit attribution. Preserve an honest distinction between a static hypothesis and reproduced evidence.
- T-02: Add persistent invitation-acceptance throttling using the independent counter mechanism. Preserve counting across rollback and verify the existing 429/Retry-After contract, replay/denial, recovery and subject separation.

### 3. Resolve the concrete Google/OTP design and implement its approved slice

Prepare the actual schema, dependency list, route contracts, account-linking/verification policy and rollout in the auth design, using G-01 through G-07. Check the owner's latest decisions before asking again; do not infer approval of unrelated privacy work. Present only genuinely unresolved material choices together while independent work proceeds.

The proposed OTP policy is six digits, ten-minute expiry, five failed attempts per challenge, and a 60-second resend cooldown in addition to existing persistent request limits. These exact values remain proposed until recorded as approved. Use challenge/account/purpose binding and a keyed verifier; plain globally indexed SHA-256 of a short code is unsuitable. The requested OTP replaces email-verification links only; reset and invitation links keep their existing purpose and behavior.

After the required decisions are recorded, complete the approved feature work:

- Google authorization-code/OIDC sign-in with browser-bound single-use state/nonce, appropriate PKCE, validated tokens, stable provider subject identity, explicit conflict/link policy, and existing opaque application sessions. Retain disabled-user, email verification, tenant authorization, CSRF and revocation guarantees.
- Numeric verification challenges, encrypted delivery payloads, atomic successful consumption, persistent failed-attempt counting, resend invalidation and a reviewed transition for legacy verification links/queued messages. Preserve generic account responses and leading-zero codes.
- Gmail send-only adapter and owner-run authorization helper, with local capture preserved, bounded network/retry behavior, sanitized failures and honest duplicate-delivery limitations.
- Necessary additive migration/runtime privileges, controlled provider tests, exact settings validation, Docker forwarding, OpenAPI and local walkthrough updates. Keep production deployment and unrelated React/analytics/Facebook/retention work out of scope.

## Verification and delivery

Use the existing test instructions and guarded fixture database. Run focused tests for each behavioral change, then the required relevant suite, Ruff, contract/model agreement and whitespace checks. Do not rerun destructive checks against native data. Record actual commands, outcomes and unrun checks; historical test counts are not new evidence.

Automated mail/provider tests use controlled substitutes and synthetic data. A live Google sign-in requires the owner's browser action; a live Gmail smoke test requires the configured sender and an explicitly designated owner test recipient. Do not process all existing outbox messages or send to arbitrary recipients to demonstrate readiness.

Provide an Arabic completion report with:

1. Files changed and the purpose of each slice.
2. Findings fixed versus findings still hypothetical or blocked.
3. Checks actually run and their outcomes.
4. Private setting names still missing, without values.
5. Exact local commands to run the API, sender authorization helper and bounded mail worker after implementation.
6. A concise test walkthrough for registration, numeric email verification, password login, Google sign-in and logout, with no raw tokens/passwords in the report.
7. Any remaining reviewed migration/provider decision, followed by the completed diff for owner review before upload.

Do not claim the system is ready merely because OAuth clients have been created. Complete the authorized local work; explicitly distinguish local automated verification from live provider verification.
