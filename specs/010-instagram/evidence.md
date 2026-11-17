# Spec 010 evidence

## 010-A: Instagram-shaped synthetic adapter and runtime extensions (2026-11-17)

Scope: D-053, implementing decisions D1-D9 of the [entry review](entry-review.md) as settled in its section 8, against the synthetic provider `synthetic_instagram` only. No Meta app exists, no live Meta call was made, native `tracking_sys` was not touched, and no dependency was added.

### What changed

| Area | Files |
|---|---|
| Contracts: `StreamSpec`, stream and product-type metric support, optional PKCE, self-refreshing tokens, no fixed quota, data delay, `SignedRequest` and `verify_signed_request`, absent-value reasons | `backend/app/connectors/contracts.py` |
| Instagram-shaped synthetic provider (Instagram Login shapes, D2 catalog, three streams, thresholds, empty data, signed requests) | `backend/app/connectors/synthetic_instagram.py`; the 009 provider accepts the `stream` argument |
| Runtime: streams in runs, checkpoints, records, scheduling, sync requests and webhooks; PKCE only when offered; renewal of self-refreshing tokens; absent-value reasons; optional provider quota; shared `start_disconnect`; deletion completion in the teardown | `backend/app/services/connectors.py`, `backend/app/services/connector_webhooks.py` |
| Provider callbacks and deletion status | `backend/app/services/connector_callbacks.py`, `backend/app/api/connectors.py`, `backend/app/main.py` |
| Coverage and records by stream, product type, reason and provisional flag | `backend/app/services/connector_coverage.py`, `backend/app/api/connectors.py` |
| Migration `0013_connector_streams`, models, registry `010-A`, lifecycle target and setting | `backend/migrations/versions/0013_connector_streams.py`, `backend/app/models/connectors.py`, `backend/app/data_policy.py`, `backend/app/services/lifecycle.py`, `backend/app/config.py` |
| OpenAPI snapshot (88 operations) | `contracts/openapi.json` |
| Tests | `backend/tests/integration/test_connector_instagram.py` (8 cases); updated expectations for the additive response fields, the new table and the registry |
| Documentation | [Connector guide](../../docs/engineering/connectors.md#instagram-shaped-providers-010-a), lifecycle guide, migration notes, README and local setup counts |

### Commands and results

From `backend/` with the project `.venv`, against a fresh disposable PostgreSQL 18.6 at `127.0.0.1:55433/tracking_foundation_test` with a synthetic environment file:

| Command | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 133 files formatted |
| `python -m pytest -m "not integration" -q` | **508 passed**, 325 deselected |
| `python -m pytest -m integration -q -rw` | **322 passed, 3 skipped**, no warnings (the 3 skips are the opt-in Spec 005 browser journeys) |
| The browser journeys with `TRACKING_RUN_BROWSER_TESTS=1` and the tracker's Playwright browsers | **3 passed** (Chromium and Firefox) |
| `python -m pytest -m integration -q tests/integration/test_connector_instagram.py` | 8 passed |
| Mutation check: each 010-A safeguard disabled in turn, the 010-A tests rerun, source restored byte for byte | All eight caught: renewal never due, renewal ignoring the 24-hour minimum age, absent-value reasons dropped, product types ignored, signature not compared, a callback stopping only the first connection, a deletion request never completing, stream intervals ignored |
| `git diff --check` | No whitespace errors |

### Criteria covered for the synthetic provider

| Criterion | Test (`test_connector_instagram.py`) |
|---|---|
| D1, D3: Instagram Login shape without PKCE; state and session binding unchanged | every connect in the module asserts that the authorization URL carries no code challenge |
| D6: three streams with their own runs, checkpoints and records; sync requests by stream; tenants isolated (K1, K2, K3 share `ig-acct-1`) | `test_010a_streams_product_types_and_isolation` |
| D2, D7: product types; metrics unsupported for a product type; `missing` with `below_threshold` or `not_returned`, never 0 | `test_010a_streams_product_types_and_isolation`, `test_010a_absent_values_carry_reasons_and_recent_values_are_provisional` |
| D8: values within the 48-hour delay are provisional | `test_010a_absent_values_carry_reasons_and_recent_values_are_provisional` |
| D4: renewal after 24 hours and within 7 days of expiry; no renewal of a fresh token; a refused renewal requires reconnection with data kept | `test_010a_self_refresh_before_expiry_and_failed_refresh` |
| D5: unsupported revocation reported honestly, every stream purged | `test_010a_disconnect_reports_unsupported_revocation_and_purges_every_stream` |
| D5: invalid, foreign, expired or unreadable signed requests have no effect | `test_010a_signed_requests_are_verified_before_any_effect` |
| D5: deauthorization stops every connection of the account in every tenant, archived client included, and nothing else | `test_010a_deauthorize_stops_every_connection_of_the_account` |
| D5: data deletion answers with a code and status URL; the status completes after the purge; no account stored | `test_010a_data_deletion_returns_a_status_that_completes_after_the_purge` |
| D6, D9: stream intervals (stories every 2 hours, others daily), privileges, deletion 730 days after observation | `test_010a_stream_intervals_privileges_and_two_year_retention` |

The 009 connector cases pass unchanged apart from the expected shape of the additive response fields (`streams[].sync`, metric `stream` and `product_types`, record `stream`, `product_type`, `provisional` and value `reason`) and the provider set built from the development state.

### Limits that remain

- Everything above describes the synthetic adapter. Acceptance criterion 1 needs the owner-operated feasibility check (010-B); the metric names, PKCE support, revocation, history window, rate-limit signals and webhook fields of the live service are unconfirmed, and the `meta.platform_data` and `instagram.login_api` rows stay stale and blocking.
- The 1-hour age limit on signed requests is an adapter choice, not a documented Meta rule; 010-B checks what Meta sends.
- Facebook Login, Unified Login and the `story_insights` webhook are not modeled (D1).
- Deletion requests and run history have no approved retention period (Q-012). Native `tracking_sys` has none of the migrations 0009 to 0013.
- The worker remains a bounded command; production scheduling is 020.

## 010-B preparation (2026-11-17)

Scope: D-053 decision D10, preparation only. The [feasibility checklist](feasibility-checklist.md) lists the owner's steps and questions F1-F11. The read-only tool `backend/app/instagram_feasibility.py` (standard library and python-dotenv only) is not yet run: no Meta app exists and no live call was made.

| Command (from `backend/`, project `.venv`) | Result |
|---|---|
| `python -m pytest -q tests/test_instagram_feasibility.py` | **9 passed**, offline with a fake transport: read-only scopes, PKCE only on request, redirect parsing with state and the `#_` suffix, configuration bounds, redaction of every token, code, secret, ID, username and metric value from the console and evidence files, the refused `media_product_type` fallback, throttling and the call budget, and storing and forgetting the token in the environment file |
| `python -m pytest -m "not integration" -q` | **517 passed**, 325 deselected |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 135 files formatted |

Documentation finding recorded in [entry review section 8.1](entry-review.md#81-documentation-finding-for-010-b-2026-11-17): `media_product_type` is documented for Facebook Login only, which question F7 settles.
