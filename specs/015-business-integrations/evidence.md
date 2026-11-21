# Specification 015 evidence, first round

Branch `codex/spec-015-business-integrations`, created from `c81d506` (the D-066 preparation on top of merged `main` at `73efae9`). Authority: D-066 and D-067, decisions D1-D15 of the [entry review](entry-review.md) as recommended, with amendment A1. Design: [design-015a.md](design-015a.md).

No call was made to Paymob, no real payment was involved, and no Paymob account, integration or secret was created, changed or requested. Phase 0 read public documentation pages only. No card data, billing or shipping data, customer data or raw payload is stored. Every migration ran on the disposable PostgreSQL 18 service of `backend/tests/README.md` (Compose project `tracking-system-foundation-test`, `127.0.0.1:55433`), never on the native `tracking_sys`. No dependency was added and no frontend file changed.

## Baseline

At `c81d506` (with the Phase 0 and D-067 record commits, which change no code), in the worktree `.worktrees/spec-015-business-integrations` with the project `.venv` (Python 3.12.4):
- unit suite: 703 passed, 391 deselected;
- integration suite on the disposable service: 388 passed and 3 skipped (the browser journeys, which need `TRACKING_RUN_BROWSER_TESTS=1`).

## Phase 0: sources and D-067

[Entry review section 2.4](entry-review.md#24-official-sources-read-in-phase-0) lists every page read on 2026-11-21, with the result for V-1 to V-13. In summary:
- **Confirmed:** V-1, V-2 (the assumed field list and order), V-8, V-10, V-12 and V-13.
- **Corrected at parameter level:** V-3 (the child and test-mode flags), V-4 (refunds, voids and captures are their own transactions, and the parent is re-sent with flags), V-7 (`created_at` has no offset in the processed callback) and V-9 (four regions; Pakistan is not listed).
- **Partly confirmed:** V-5 (retries implied, no schedule) and V-11 (no documented secret regeneration).
- **Not stated:** V-6 (no size; 64 KiB kept).

One fact raised a decision: test-mode transactions (`is_live`). It was presented to the owner with D1-D15 as amendment A1 (section 2.5), and D-067 approves D1-D15 and A1 as recommended. Notes N1 (unsigned fields) and N2 (authorization and capture references) are recorded in section 2.5. The design note applies the parameters (section 1).

## 015-A: evidence store and ledger read

**Scope (D2, D11, D14, D15).**
- `revenue_evidence`, the append-only receipt log of 007-A `Evidence` records per client, with intake provenance and a content digest; an exact redelivery is stored once and a reused delivery ID with other content is a second row (migration `0020_revenue_evidence`).
- The client revenue lock (namespace 7007) and the database clock as receipt time, so a client's receipts increase in commit order.
- `append_evidence`, `load_evidence` and `client_ledger` (the 007-A calculation, and the `ledger_feed` journal on first use).
- `GET /agencies/{a}/clients/{c}/revenue` with `finance:read`: verified totals and transactions, declared items and totals apart, pending adjustments and reconciliation items, currencies never summed.

**Tests.**
- `tests/integration/test_revenue_evidence.py`: T-01 to T-05.
- `tests/integration/test_revenue_migrations.py`: the `0020` privileges (insert and read only for `tracking_app`, nothing for `tracking_lifecycle`), the refused and empty downgrades, and the check constraints.

Existing expectations updated: the table counts (`test_data_policy.py`, `test_data_policy_schema.py`), the known tables of `test_postgres.py` and the cleanup order of `tests/integration/conftest.py`.

**Verification of 015-A** (from `backend/` with the project `.venv`, 2026-11-21):
- `python -m ruff check .` and `python -m ruff format --check .`: clean.
- `python -m pytest -m "not integration" -q`: 703 passed, 407 deselected (015-A adds no unit case).
- The integration suite on the disposable service (`run_db.py`, the `backend/tests/README.md` procedure with the variables of the guarded environment): 404 passed and 3 skipped (the browser journeys).
- `contracts/openapi.json` regenerated with the unit-test settings; its contract test passes.

**Mutation checks (015-A).** Each safeguard was disabled, its test rerun on the disposable service, and the source restored byte for byte (SHA-256 checked):

| Mutation | Test | Result |
|---|---|---|
| M1: the exact-redelivery key also covers the row ID | T-02 `test_exact_redelivery_is_stored_once` | Caught: three stored rows instead of one stored and two duplicates |
| M2: the revenue route checks `client:read` instead of `finance:read` | T-03 `test_revenue_read_needs_finance_access` | Caught: the analyst read answered 200 instead of 403 |
