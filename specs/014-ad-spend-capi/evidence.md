# Specification 014 evidence

Branch `codex/spec-014-ad-spend-capi`, created from `a52d2fb` (the D-063 and D-064 preparation on top of merged `main` at `6283935`). Authority: D-063 and D-064, decisions D1-D14 of the [entry review](entry-review.md) as recommended. Design: [design-014.md](design-014.md).

No live Meta call was made, nothing was sent to Meta, and no Meta app, business, ad account or dataset was created or changed. Phase 0 read public documentation pages only. Every migration ran on the disposable PostgreSQL 18 service of `backend/tests/README.md` (Compose project `tracking-014-test`, `127.0.0.1:55433`), never on the native `tracking_sys`. No dependency was added and no frontend file changed.

## Baseline

At `a52d2fb`, in the worktree `.worktrees/spec-014-ad-spend-capi` with the project `.venv` (Python 3.12.4):
- unit suite: 608 passed, 346 deselected;
- integration suite on the disposable service: 343 passed and 3 skipped (the browser journeys, which need `TRACKING_RUN_BROWSER_TESTS=1`).

## Phase 0: sources

[Entry review section 2.4](entry-review.md#24-official-sources-read-in-phase-0) lists every page read on 2026-11-20 and 2026-11-21, with the result for V-1 to V-18. In summary:
- **Confirmed:** V-1, V-2, V-4 to V-6 and V-9 to V-12, V-16 to V-18.
- **Corrected at parameter level:** V-7 (Login for Business tokens do not expire, and no callbacks or revocation endpoint are documented), V-8 (one invalid event no longer fails a whole batch) and V-14 (the delivery permission is `ads_read`).
- **Partly read:** V-13 and V-15; their dedicated pages answer 404.
- **Not stated:** V-3.

No fact changes D1-D14. The design note applies the parameters (section 1).

## 014-A: spend ingestion

**Scope (D2 to D5, D13, D14).**
- The synthetic `synthetic_meta_ads` provider.
- The named ad account of a connect, described after the exchange (`account_unavailable` otherwise).
- Per-connection day zones from the account.
- The `account`, `ad_objects` and `ad_daily` streams, stored in `ad_accounts`, `ad_objects` and `ad_spend_facts` under the checkpoint's fence.
- The 28-day provisional re-read, exact minor units with the `unparseable_amount` and `unsupported_currency` refusals, no zero rows, and facts kept when a later read omits them.
- The spend route (`finance:read`), the purge at disconnect, the 730-day lifecycle deletion, and migration `0017_ad_spend`.

**Tests.**
- `tests/integration/test_ad_spend.py`: T-01 to T-10, plus the connect case.
- `tests/integration/test_ad_migrations.py`: the `0017` privileges, its refused and empty downgrades, and the 730-day lifecycle deletion.
- `tests/test_advertising_spend.py`: the parsing table and the currency table (T-04), local-day windows across the 2026-11-01 New York change (25 hours) and the 2026-10-04 Sydney change (23 hours) (T-03), the 7-day windows, the cursor and the Login for Business request.

Existing expectations updated: the synthetic registry set (`test_connector_contracts.py`), the table counts (`test_data_policy.py`, `test_data_policy_schema.py`) and the approved rules.

**Verification of 014-A** (from `backend/` with the project `.venv`, 2026-11-21):

| Check | Result |
|---|---|
| `python -m ruff check .` and `python -m ruff format --check .` | Clean (163 files) |
| Unit suite (`pytest -m "not integration"`) | 638 passed, 361 deselected |
| Integration suite on the disposable service (`run_db.py`, `pytest -m integration`) | 358 passed, 3 skipped (the browser journeys), 638 deselected |
| OpenAPI snapshot (`tests/test_contract.py`) | Regenerated in `contracts/openapi.json`; passing |

The first full integration run of 014-A found five failures, all expectations of the previous head: the synthetic registry set (`test_connector_instagram_login.py`), the head revision after a refused downgrade (`test_connector_youtube_live.py`, which now compares with the head it read), and the known table list of the migration cycle (`test_postgres.py`). They were updated and the suite reran clean.

**Mutation checks of 014-A.** Each safeguard was disabled in turn, its tests rerun on the disposable service, and every source restored byte for byte (SHA-256 compared). The migration mutation downgraded the disposable database to `0016` before and after the run.

| Safeguard (case) | Mutation | Result |
|---|---|---|
| Unique fact key (T-01) | The key of `0017` also covers the row ID | Caught: `test_rereading_a_window_keeps_facts_and_totals` |
| Exact parsing (T-04) | A rounding parse instead of `Money.parse` | Caught: 6 parametrized refusal cases and `test_refused_amounts_are_not_stored` |
| Per-currency totals (T-05) | Totals summed into the first currency | Caught: `test_currency_change_keeps_earlier_facts` |
| `finance:read` on the spend route (T-09) | `client:read` in the route and the service | Caught: `test_spend_reads_need_finance_access` |

Caught 4 of 4.
