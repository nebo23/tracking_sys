# Spec 015 review correction evidence

Corrections of findings R001-R011 of the [001-015 review](../../reports/specs-001-015-review-2026-11-22.md) under D-069 and D-070, on `codex/spec-015-business-integrations` (PR 13). The per-finding status is in the [tracker](review-corrections-tracker.md); the execution instructions are in the [handoff](review-corrections-prompt.md). Every check ran against synthetic data on the disposable PostgreSQL service; nothing called Paymob, Cal.com, a CRM or Meta, and no migration ran on the native `tracking_sys`.

## Environment

- Worktree `.worktrees/spec-015-business-integrations`, project `.venv` with Python 3.12.4 (SQLAlchemy 2.1.6, Alembic 1.20.1, Psycopg 3.3.6, FastAPI 0.162.0, pytest 9.2.0).
- Disposable PostgreSQL 18.6 (`postgres:18.6-bookworm@sha256:5c4783a8...`) in the Compose project `tracking-system-foundation-test` on `127.0.0.1:55433`, started with a synthetic environment file kept outside the repository. The port was free and outside the Windows excluded port ranges on 2026-11-22, so the integration guard of `backend/tests/integration/conftest.py` ran unchanged (the review had used a private copy on 55434).
- Tests run through a runner that drops inherited `TRACKING_`, `PG` and `PYTHON` variables and sets `TRACKING_RUN_DB_TESTS=1`; the owner's `.env` is never read because the worktree has none.

## Baseline reproduction at `db750d1`

`git archive db750d1` was extracted into a scratch directory, and `reports/specs-001-015-review-regressions.patch` passed `git apply --check` and was applied there. Application code was unchanged.

| Run | Result |
|---|---|
| `pytest tests/integration/test_review_001_015.py -q --tb=line` | **12 failed** in 25.95 s (repeated: 23.87 s). Every case failed at its intended assertion: line 39 (R001, test-to-live promotion stored a verified EGP 1,000.00 sale), line 50 (R001, refund retargeted, answered `received`), line 58 (R005, `500 Internal Server Error`), `CheckViolation` on `ck_bookings_valid_link` (R002), line 97 (R003, `linked` stayed 1 after withdrawal), line 110 (R006, one booking instead of two), line 138 (R007, `won_unverified` for the reversed order), line 165 (R008, `open: 500` for 501 deals), line 204 (R010, USD group unreachable), line 222 (R004, the claimant's number was `active` and received the message), line 235 twice (R009, `500` for the list `source_type` and for the 12-digit timestamp). No fixture, connectivity or dependency failure. |
| `pytest tests/test_review_instagram_cursor.py -q` | **1 failed** in 0.15 s (R011): the resumed page returned `2024-11-24` after `2024-11-22`. |

The same thirteen cases were then applied to the correction branch unchanged (`git apply`), so the permanent suite carries them.

## Corrections

Each section below records the root cause, the correction, the regression and adjacent cases, and the commit. Sections are completed as each correction lands; the final verification and the second review pass follow at the end. A "mutation" disables the new safeguard in the working tree, reruns the named tests on the disposable database and restores the file byte for byte (SHA-256 checked); "caught" means the tests failed.

### R001 P1: Paymob financial meaning from signed fields only

**Root cause.** Paymob's processed-callback HMAC covers 20 documented fields (V-2); `is_live`, `parent_transaction`, `is_refund` and `is_void` are outside it. The mapper still took the environment from `is_live` and the refunded sale from `parent_transaction`. Note N1's signed-flag rule only constrained the operation's shape, so an unchanged signature allowed both reproduced changes.

**Decision.** D-070 (owner, 2026-11-22). The Paymob pages read that day state that integration IDs differ between test and live mode ("the table will refresh with a different set of Integration IDs depending on the mode"; "The mode is controlled by the keys and integration IDs you use") and list `integration_id` and `order.id` among the signed fields. They do not show a refund response, so the shared order of a refund and its sale is recorded as an assumption for the live check.

**Correction.**
- `payment_sources.live_integration_ids` (migration `0021` amended in place): 1 to 20 positive bigints without nulls, required at creation, changeable by an Owner or Admin with the existing `payment_source.updated` audit event, and returned by the source routes.
- `map_transaction` posts only when `is_live` is true and the signed `integration_id` is declared; otherwise `test_mode` with the new diagnostic reason `undeclared_integration`.
- `receive_callback` refuses a refund or void whose stored parent sale carries another signed order ID (`unmapped`, `invalid_parent`, nothing stored).
- `client_ledger` holds back, before the 007-A calculation, a Paymob refund whose parent arrived later with another order (`unbound_refunds`). It never reaches the calculation, the journal, attribution, conversion delivery or CRM verification; the revenue read lists it as pending with `parent_order_mismatch`.
- The synthetic sender now gives each payment its own order (every transaction previously shared order `810000001`, which would have hidden a cross-order retargeting), gives children their parent's order, and gives test-mode transactions a test integration ID, as Paymob documents.

**Tests.** The two regressions pass. New cases:
- `test_paymob.py`: `test_only_declared_live_integrations_post` (tampered `is_live`, undeclared live integration, audited declaration), `test_live_integration_ids_are_validated`, `test_refund_cannot_move_to_a_sale_of_another_order` (refused moved copy, then the genuine refund still posts), `test_refund_before_a_sale_of_another_order_stays_held` (held refund absent from totals, journal and 014-B candidates; an own-order refund still posts).
- `test_revenue_migrations.py::test_0021_live_integration_check`.
- `test_paymob_contract.py`: `test_only_a_declared_live_integration_posts`, `test_refund_and_sale_share_the_signed_order`.

The existing T-10 to T-21 and A1 cases, including duplicates, every delivery order, voids, captures and the unchanged HMAC example, pass unchanged in substance. Three fixtures were adapted to the D-070 contract, each still asserting the same property: `test_revenue_evidence._record` gives its Paymob-intake records a Paymob-shaped source reference with the sale's order, `test_no_card_or_customer_field_is_stored_logged_or_returned` expects the sale's own order in the reference, and the mapping-table unit case expects the generated order.

**Results.**
- Integration: the two regressions with `test_paymob.py`, `test_revenue_evidence.py`, `test_revenue_migrations.py` and `test_revenue_imports.py`, 53 passed in 93.76 s.
- Unit: `test_paymob_contract.py`, `test_revenue_ledger.py`, `test_revenue_csv.py` and `test_contract.py` (with the regenerated OpenAPI snapshot), 112 passed.
- Mutations: R001-a (integration check removed), R001-b (intake parent check removed) and R001-c (read-time hold removed) are each caught by a regression or a new case.

**Remaining limits.** A merchant who lists a test integration as live makes its test payments count; that is the source owner's audited assertion. The live check confirms that test and live integration IDs differ and that a refund or void carries its sale's order ID; a refund whose order differs meanwhile stays visibly pending rather than adjusting a sale.
