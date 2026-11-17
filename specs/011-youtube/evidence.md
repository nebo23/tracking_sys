# Spec 011 evidence

## 011-B preparation (2026-11-18)

Scope: D-058, which approves entry review decisions D1-D14, D16 and D17 and runs 011-B before 011-A, with D15 decided by D-057. This section covers preparation only.

- The [feasibility checklist](feasibility-checklist.md) lists the owner's steps and questions F1-F14.
- The read-only tool `backend/app/youtube_feasibility.py` uses only the standard library, python-dotenv and the already pinned `tzdata`.
- No dependency was added, no live Google call was made, and native `tracking_sys` was not touched.

| Command (from `backend/`, project `.venv`) | Result |
|---|---|
| `python -m pytest -q tests/test_youtube_feasibility.py` | **15 passed**, offline with a fake transport (see the list below). |
| `python -m pytest -m "not integration" -q` | **563 passed**, 328 deselected. |
| `python -m ruff check .` and `python -m ruff format --check .` | All checks passed; 142 files formatted. |

The 15 tests cover:

- the authorization request: read-only offline consent, and PKCE only on request;
- the Web client and loopback redirect checks, state checking, and closed consent-error codes;
- the loopback receiver on 127.0.0.1, which ignores other paths and logs nothing;
- redaction: no token, code, secret, channel or video ID, or metric value in the console or the evidence;
- the single-metric fallback when the combined day report is refused;
- the analytics-only consent;
- the stop on quota answers and the call budget;
- the token and refresh records;
- storing and forgetting tokens in the environment file;
- the refused consent and the wrong PKCE verifier;
- `revoke-test` with its confirmation;
- keyed day digests that show changed days on a later probe.

The test fixture also models Google's documented account-wide revocation (entry review G-1), so the expected `revoke-test` record is "slot b does not survive". The live answer is F12.

### Console setup recorded before the run

See [entry review section 10](entry-review.md#10-owner-decisions):

- `connectapp` is in Testing.
- `youtube.readonly` is classified sensitive and `yt-analytics.readonly` non-sensitive.
- A separate Web client with the loopback callback exists.
- The client credentials are in the ignored `.env`, used at the owner's instruction, and rotating the secret is a follow-up.

Next: the owner runs Part C of the checklist (`authorize`), and Claude records the redacted results here.
