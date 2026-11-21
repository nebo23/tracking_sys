# Spec 014 implementation: advertising spend and conversion delivery (Meta), and the pull request

Work in the owner's local repository, for example in a worktree `C:\Code\Tracking-system\.worktrees\spec-014-ad-spend-capi`. Use a new branch `codex/spec-014-ad-spend-capi` (D-023). Fetch `claude/gallant-cray-b16xwk` and create the branch from `origin/claude/gallant-cray-b16xwk`, which holds this preparation on top of merged `main` at `6283935`. If `main` has meanwhile received this preparation, branch from `main` instead. If your session requires another branch name, create that branch from the same commit.

Before editing:
- Verify that `git log --oneline 6283935..HEAD` lists only the D-063 and D-064 preparation commits and any later owner commits.
- Verify that the working tree is clean, and preserve every owner change.

Read:
- `AGENTS.md` and `README.md`;
- D-051, D-062, D-063 and D-064 in `docs/planning/decisions.md`;
- every file in `specs/014-ad-spend-capi/`, in particular the [entry review](entry-review.md) sections 2 to 8.

Use the 009 runtime and the 010 and 011 work as the pattern:
- `backend/app/connectors/`: `contracts.py`, `synthetic_instagram.py`, `synthetic_youtube.py`, `instagram.py` and `youtube.py`;
- `backend/app/services/connectors.py`: `build_providers`, `rules_allow` and `LIVE_RULES`;
- migrations `0013` to `0016`;
- `backend/app/config.py` and `backend/app/data_policy.py`;
- `backend/app/privacy/`: `consent.py`, `deletion.py` and `providers.py`;
- `backend/app/ledger/` and `backend/app/attribution/`;
- the test support in `backend/tests/instagram_graph.py`, `backend/tests/youtube_api.py` and `backend/tests/integration/connector_support.py`;
- `docs/engineering/connectors.md`.

Communicate with the owner in Arabic, and write project files, code comments and commit messages in formal English.

## Authority

- **D-063 (owner, 2026-11-20).** Specs 012 and 013 are deferred and stay unchanged. Meta is the initial advertising provider. Spec 014 is completed against synthetic Meta-shaped providers and fixture tests only. After successful verification you push and open a pull request against `main` for review, without a further upload request. The merge remains the owner's decision.
- **D-064 (owner, 2026-11-20).** Approves decisions D1-D14 of the entry review as recommended and authorizes this implementation. Phase 0 confirms that it is recorded before any implementation.
- **Amendments.** Phase 0 reads the official pages behind V-1 to V-18.
  - A fact that changes a decision goes to the owner first, as D-054 did, and the work that depends on it waits.
  - A fact that changes only a parameter (a window, a code, a field name) is applied and recorded.
  - A later change to D1-D14 also goes to the owner first.

## Hard limits

- No live Meta call of any kind: no OAuth, no Graph or Marketing API read, and no Conversions API send. Do not create or change a Meta app, business, ad account or dataset. Do not ask for Meta credentials. The live adapters stay off by default.
- Test migrations on the disposable PostgreSQL 18 service of `backend/tests/README.md` only, never on the owner's native `tracking_sys`.
- No new dependency. HTTP goes through the standard library, as the Instagram and YouTube adapters do.
- No frontend change. Destination and account screens wait for the owner's brief, design and brand identity (D-039).
- No collection of email, phone, name, address, IP address or user agent. D8 governs match keys.
- Do not touch Specs 012 and 013 beyond the D-063 status lines.
- Do not touch the YouTube test account, its tokens or `local-data\youtube-feasibility`. Spec 011 Phase 4 follows its own branch after 2026-11-24 23:57 UTC (D-062).
- Never commit a token, real customer data, an identifier from a live account, or a signed URL. Tests use synthetic values only.
- Do not merge, do not enable auto-merge and do not deploy.

## Phase 0: decisions, sources and branch

1. **Branch.** Set up the branch as described above.
2. **D-064 gate.** Look for D-064 in `docs/planning/decisions.md`.
   - If it is recorded, apply it as written.
   - If it is not recorded, present D1-D14 to the owner in Arabic: a short table with the decision, the recommendation and the alternative. Ask whether to approve every recommendation or change some.
   - Record the answer as D-064 in the decision register and as one line in `AGENTS.md`, in the style of the earlier entries, and update section 9 of the entry review.
   - Do not start Phase 1 before D-064 is recorded.
3. **Source verification.** Read the official pages behind V-1 to V-18 of the entry review section 2.3.
   - **Record.** Fill section 2.4 with one row per page: the URL, the date read and any last-updated date. For each V row, state whether it was confirmed, corrected or not read.
   - **Apply.** Apply parameter-level corrections in the design note (Phase 1). Present any decision-level change to the owner before the work that depends on it.
   - **Unreadable pages.** If a page cannot be read, say so in section 2.4 and keep the assumption marked as unverified. The rules of Phase 5 then stay stale, and the live adapters stay unregistered. That is acceptable for this completion.
4. **Commit and push** (D-051).

## Phase 1: design note

Write `specs/014-ad-spend-capi/design-014.md`, then continue; it is not a stopping point. It covers:
- the tables, columns, constraints and indexes of D3, D9, D10 and D13, with the column-limited privileges of `tracking_app` and `tracking_lifecycle`;
- the `app.data_policy` entries for every new table;
- the upgrade and downgrade of `0017` to `0019`;
- the runtime extensions (the account named at connect, per-connection day zones, the new streams and the storage of their pages);
- the delivery state machine with its closed reason codes;
- the error mapping of the synthetic and live adapters;
- the routes with their permissions and answer shapes;
- the worker's delivery step;
- the mapping of each case T-01 to T-53 (entry review section 7) to its test.

## Phase 2: 014-A, spend ingestion

1. **Synthetic provider.** `synthetic_meta_ads`, registered in `build_providers` next to the other synthetic providers, with a state file carrying a `-meta-ads` suffix. It reproduces the shapes of V-1 to V-6 as verified in Phase 0:
   - ad accounts with currency, time zone and status;
   - campaigns, ad sets and ads with parent IDs, status and names;
   - daily ad-level rows with decimal-string spend;
   - restated values inside the re-read window;
   - deleted and archived ads;
   - throttling, permission and token errors on demand;
   - an approval helper for tests, like `SyntheticProvider.approve`.
2. **Runtime extensions (D2 to D5).**
   - The connect request names the ad account. It is stored on the OAuth transaction and checked after the exchange (`account_unavailable`).
   - A spend connection's day zone comes from its `account` snapshot.
   - The streams `account`, `ad_objects` and `ad_daily`.
   - Pages are stored into `ad_accounts`, `ad_objects` and `ad_spend_facts` in the same fenced transaction as the checkpoint.
   - The 28-day re-read is marked provisional.
   - The counted refusals `unparseable_amount` and `unsupported_currency`.
   - The purge at disconnect.
3. **Route.** `GET /agencies/{agency_id}/clients/{client_id}/ad-spend` needs `finance:read`.
   - **Filters:** connection, account-local date range and level (ad, ad set, campaign).
   - **Answer:** totals per currency, provisional days and coverage.
   - **Never** sum across currencies.
4. **Migration.** `0017`, with the data-policy entries and privileges, tested on the disposable service.
5. **Tests.** T-01 to T-10, with the mutation checks marked (M).
6. **Verify, record and push.** Verify (Phase 6, step 1, for the affected suites), record the commands and counts in `specs/014-ad-spend-capi/evidence.md`, then commit and push.

## Phase 3: 014-B, conversion delivery

1. **Synthetic receiver.** `synthetic_meta_capi` receives events with the semantics of V-8 to V-13 as verified:
   - deduplication by dataset, event name and event ID within the window;
   - the age limit;
   - required fields per action source;
   - `events_received`;
   - failures on demand: 5xx, throttling, invalid token, missing permission, invalid parameter, expired event and a wrong `events_received`;
   - test events kept apart.
2. **Delivery connections (D2).** They go through the 009 runtime with the dataset named at connect, and request only the delivery permission.
3. **Destinations (D10) and the outbox (D9).**
   - E4 at enqueue and E5 in the claiming transaction (D7), with the consent basis and policy version stored at enqueue.
   - Subject and replay tombstones through `admission`.
   - The deterministic `event_id` and the sealed payload, destroyed when the delivery ends.
   - The retry, deadline, rejection-class, requeue and dismiss rules.
   - Acknowledgements per attempt.
4. **Conversion source.** A service function that enqueues eligible sales (D6, D8) from:
   - a 007-A `LedgerCalculation`, or its `ledger_feed` journal;
   - synthetic journeys: person, collection subjects, and click identifiers with their receipt times.

   There is no HTTP route for enqueueing. The 007-B journal replaces the synthetic source later.
5. **Worker.** A bounded delivery step in `python -m app.connector_worker`, or a separate module if the design note justifies it. It claims with a lease, fences writes by attempt and prints counts only.
6. **Routes (D10).**
   - Create, list and update destinations.
   - List deliveries (`finance:read`).
   - Requeue and dismiss deliveries (Owner or Admin, with an audit event).

   No answer or log contains `fbc`, `fbclid`, a payload or a provider trace ID.
7. **Lifecycle (D13).** `python -m app.lifecycle` deletes ended delivery rows and their acknowledgements 30 days after they end, as `tracking_lifecycle`.
8. **Migration.** `0018`, with the data-policy entries and column-limited grants, tested on the disposable service.
9. **Tests.** T-20 to T-35 with the mutation checks, including C2, C3, C5 and outbound replay blocking end to end on the disposable database.
10. **Verify, record and push.** Verify, record in `evidence.md`, then commit and push.

## Phase 4: 014-C, ROAS contract

1. **Module.** A pure module, for example `backend/app/advertising/roas.py`, implementing D11 with the `app.ledger.money` and `app.attribution` types. It has no route.
2. **Tests.** T-40 to T-47, using:
   - spend facts stored on the disposable database;
   - 008-A runs over synthetic journeys whose touches follow the URL convention of D11.
3. **Verify, record and push.** Verify, record, then commit and push.

## Phase 5: 014-D, live adapters with fixture tests

1. **Policy rules (D-025).**
   - Re-read the pages of V-7, V-14 and V-16, and re-verify `meta.conversions_api`.
   - Add `meta.marketing_api` for spend data, with its data class registered in `app.data_policy`.
   - Mark a rule current only when its pages were read, with the verification date and a review date one year later.
   - Test that neither adapter is registered while a rule is stale or past its review date.
2. **Adapters.** `backend/app/connectors/meta_ads.py` provides `meta_ads` and `meta_capi`, with the Graph version established by V-17:
   - the Facebook Login for Business authorization URL with the login configuration ID, and the code exchange;
   - the scopes of D12, with the granted scopes recorded;
   - Insights reads (D4, D5);
   - the Conversions API sender (D8, D9). `fbc` is never hashed, and no field outside D8 is sent;
   - the error mapping of V-6 and V-13;
   - the 010 deauthorize and data deletion callbacks, only if V-7 confirms that they apply.
3. **Settings.**
   - `TRACKING_CONNECTOR_META_ADS_ENABLED` (default false), `TRACKING_META_ADS_APP_ID`, `TRACKING_META_ADS_APP_SECRET` and `TRACKING_META_ADS_CONFIG_ID`.
   - When enabled, require a numeric app ID, a non-blank secret and a configuration ID.
   - Keep them separate from the Instagram settings, and list them in `.env.example` with blank values.
4. **Registration.** `build_providers` registers the two adapters only when they are enabled, configured and allowed by `rules_allow`. Add their `LIVE_RULES` entries.
5. **Migration.** `0019` admits `meta_ads` and `meta_capi` in the pattern of `0016`, and is tested on the disposable service.
6. **Fixture tests.** T-50 to T-53, against an in-memory Graph (`backend/tests/meta_graph.py`) built from the shapes recorded in Phase 0. The suite makes no network call.
7. **Verify, record and push.** Verify, record, then commit and push.

## Phase 6: verification, records and the pull request

1. **Verification.** From `backend/` with the project `.venv`:
   - `python -m ruff check .` and `python -m ruff format --check .`;
   - the full unit suite;
   - the full integration suite on the disposable service, following `backend/tests/README.md`;
   - the OpenAPI snapshot updated in `contracts/openapi.json`, with its test passing;
   - every new regression;
   - every mutation check, with its result.

   Report skipped tests as skipped, never as passed. If a check cannot run in your environment, tell the owner in Arabic and wait for instructions instead of opening the pull request.
2. **Records.**
   - `specs/014-ad-spend-capi/evidence.md`: the scope and the decisions applied, the source verification summary, the commands with their counts, the mutation checks, the limitations and the follow-ups.
   - `spec.md`: the status line, and AC1 to AC4 each mapped to its evidence.
   - `plan.md` and `tasks.md`: completed items closed, separately gated items listed as follow-ups.
   - An operator guide `docs/engineering/advertising.md`: destinations, delivery states, requeue and dismiss, the worker step, lifecycle and settings. Link it from `docs/engineering/connectors.md`.
   - The status lines of `README.md`, `specs/README.md`, `docs/planning/roadmap.md` and `docs/planning/review-next.md`.
3. **Pull request.** Push, then open a pull request from your branch against `main`. If `.github/pull_request_template.md` exists, follow it; none existed at preparation. Suggested title: "Spec 014: advertising spend and conversion delivery (Meta, synthetic and fixtures)". The description covers:
   - the problem and the resulting behavior per slice;
   - D-063, D-064 and any amendment;
   - the source verification summary;
   - the commands and counts;
   - migrations `0017` to `0019` with their downgrade behavior;
   - the limitations and follow-ups;
   - a plain statement that no live Meta call was made, nothing was sent to Meta and no native migration was run.

   Do not merge.
4. **Report.** Tell the owner in Arabic that the pull request is ready for review: the head commit, the link, the counts, any amendment, and the open follow-ups.

## Follow-ups that stay open after Spec 014

- 014-E, a read-only live spend check with the owner's Meta app (Facebook Login for Business and the Marketing API) and an ad account the owner controls; a browser connect needs a registered HTTPS redirect (020) or an approved feasibility tool.
- 014-F, test events to an owner dataset with a test event code; this writes to Meta and needs its own approval.
- 014-G: App Review for `ads_read` and the delivery permission, Business Verification, Tech Provider status if required, the Data Use Checkup, and HTTPS hosting with the callbacks (020).
- The browser-field decision for website events if V-9 requires `client_user_agent` (D8), and email or phone match keys after 006.
- The 007-B journal as the persisted conversion source, ROAS read routes and reports (016), destination and account screens (018), and production scheduling of the worker (020).
- Google Ads, and LinkedIn Ads with Spec 012 when the owner resumes it.
- Native `tracking_sys` migration and deployment, which remain separate owner decisions.
