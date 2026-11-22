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

Each section below records the root cause, the correction, the regression and adjacent cases, and the commit. Sections are completed as each correction lands; the final verification and the second review pass follow at the end.
