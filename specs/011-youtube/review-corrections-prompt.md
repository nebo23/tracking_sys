# Spec 011 continuation: review corrections, the 011-B run and 011-A

Work in `C:\Code\Tracking-system\.worktrees\spec-011-youtube` on `codex/spec-011-youtube`. The reviewed head is `bb3263e` (Spec 011-B: Prepare the YouTube feasibility check, D-058). Verify the branch, the working tree and that `bb3263e` is still the head before editing, and preserve any later owner change. Read `AGENTS.md`, `README.md`, D-056 to D-058 in `docs/planning/decisions.md`, and `specs/011-youtube/` (`spec.md`, `entry-review.md`, `feasibility-checklist.md`, `evidence.md`, `plan.md`, `tasks.md`). Communicate with the owner in Arabic and write project files in formal English. Save this handoff as `specs/011-youtube/review-corrections-prompt.md`.

## Authority

On 2026-11-18 the owner reviewed the independent review of `bb3263e` below and chose to complete Spec 011 before starting Spec 012 ("continue the rest of Spec 011"). Record this as D-059 in `docs/planning/decisions.md` and `AGENTS.md`: complete Spec 011 before Spec 012; correct findings R011-01 to R011-09 of the 011-B tool and documents with regressions, within D-058; then the owner-operated 011-B run, then 011-A as D-058 orders it. Under D-051 and D-058, push `codex/spec-011-youtube` after successful verification. 011-C, 011-D, customer channels, native `tracking_sys` migration, pull request, merge and deployment remain separate owner decisions; ask the owner when the work reaches them.

## Review result at `bb3263e`

Verified in the review: 4 commits; only `backend/app/youtube_feasibility.py` and `backend/tests/test_youtube_feasibility.py` are new code; no existing code, migration or dependency changed. `pytest tests/test_youtube_feasibility.py` gives 15 passed; `pytest -m "not integration"` gives 563 passed and 328 deselected; ruff check and format pass (142 files). The branch history contains no credential or real identifier (only the synthetic test secret). The new `TRACKING_YOUTUBE_*` keys do not affect the application settings (`extra="ignore"`), and `.env` and `local-data/` are ignored.

Not done in the review: the integration suite (no Docker daemon or PostgreSQL 18 in the review environment), and a re-reading of the Google pages (`developers.google.com` was not reachable there). The findings rest on the code and on the facts the entry review records.

## Findings to correct

Each correction needs a regression test that fails at `bb3263e` and passes after the change. Keep the tool read-only and keep its redaction guarantees (no token, code, secret, channel or video ID, title or metric value in the console or the evidence).

| ID | Severity | Location at `bb3263e` | Finding and observed result | Required correction |
|---|---|---|---|---|
| R011-01 | Medium (F9) | `_probe_video_reports`, lines 737-809 | `video_filter_catalog`, `video_filter_two_metrics` and `video_and_content_type` send `dimensions=video` (or `video,creatorContentType`) with a `video==` filter but without `sort` and `maxResults`. Entry review YT-13 records that video reports need `maxResults` of 200 or less and a `sort`. A refusal would read as "the video filter is not supported" and would push the D7 `video_totals` stream to the top-200 report without cause. The fallback has the same gap. | Send `sort=-views` and `maxResults=200` on these queries. Add one unsorted variant (for example `video_filter_unsorted` with `views` only) so that the evidence shows whether `sort` and `maxResults` are required. Regression: a fake that refuses video-dimension queries without `sort` and `maxResults`. |
| R011-02 | Medium (F5) | `_probe_videos`, line 558 | The 51-ID check repeats `batch[0]` 51 times; reproduced: 51 IDs sent, 1 distinct. A server that removes duplicates would accept it, which reads as "more than 50 IDs are allowed". The `batchGetStats` ID limit is not checked, although the F5 row of the checklist says it is. | Use up to 51 distinct IDs from the uploads. Record `ids_sent`, `distinct_ids` and `conclusive` (a refusal is conclusive; an acceptance is conclusive only with 51 distinct IDs). Apply the same check to `videos:batchGetStats` after re-verifying its HTTP method, path and parameter names on the official page. Regression: a fake that removes duplicate IDs and refuses more than 50 distinct IDs. |
| R011-03 | Low-medium (F12) | `_revoke_test`, lines 1138-1168 | The answer rests on one refresh 10 seconds after the revocation, while G-1 says a revocation may take some time to take full effect. A surviving slot b is recorded as the final answer and could wrongly argue against D5. | Record `wait_seconds`, and mark a surviving slot b as provisional in the evidence and in the printed message. Checklist Part D step 6 tells the owner to run `check-access --slot b` again at least 30 minutes later before any conclusion. Regression: a fake whose revocation reaches slot b only after a delay. |
| R011-04 | Low | `Probe.get` and `probe_channel` | A transport failure during a probe propagates and nothing is written. Reproduced: a failure at the 12th call gives exit code 1 and no evidence file. | Catch `FeasibilityFailed` in `Probe.get`, set `stopped` to `no_answer`, and write the probe evidence with what was read. Regression for both `probe` and `authorize`. |
| R011-05 | Low | `_probe_videos`, line 552 | `public_items_equal_video_count` compares the public items among the first 50 videos with the channel's `videoCount`. Reproduced: a channel with 60 public videos reports `false`. | Report it only when every upload was read and fits the batch; otherwise record `null` with a reason. |
| R011-06 | Low | `main`, argument parser | `--max-calls` is accepted only before the command name. Reproduced: `probe --max-calls 50` exits with code 2. The checklist does not say where it goes. | Accept it after `authorize` and `probe` as well (default `argparse.SUPPRESS`, so the top-level value is kept), and document it in the module docstring and the checklist. |
| R011-07 | Documentation | `specs/011-youtube/plan.md`, slice 2 | It says 011-B uses "a dedicated Google Cloud project", which contradicts D-057 (the existing project `connectapp`). | Correct it. |
| R011-08 | Documentation (D-010) | Checklist Part D step 8 | `forget` removes only the tokens; `local-data\youtube-feasibility` (evidence files and `digest-key`) stays. | Add a clean-up step: delete that folder once Claude's summary is recorded in `evidence.md`. |
| R011-09 | Low (Windows) | `CallbackReceiver` | `http.server.HTTPServer` sets `SO_REUSEADDR`. On Windows that lets a second socket bind a port that is already in use. CPython's own `socket.create_server` does not set it on Windows for that reason (it cites Microsoft's SO_EXCLUSIVEADDRUSE page). The "port in use" message may therefore not appear while the API server still runs, and Google's redirect may reach the API instead of the tool. | Use a server class that, on Windows, does not set `SO_REUSEADDR` and sets `SO_EXCLUSIVEADDRUSE`. Tests: a second receiver on the same port raises `FeasibilityFailed`; with `sys.platform` patched to `win32`, `SO_REUSEADDR` is not set. |

Update `evidence.md` with a dated "011-B review corrections" section: the finding IDs, the regression test names, and the commands with their counts. Update `tasks.md` and the checklist where the commands or steps change.

## Verification before the push

From `backend/` with the project `.venv`:

- `python -m pytest -q tests/test_youtube_feasibility.py`
- `python -m pytest -m "not integration" -q`
- `python -m ruff check .` and `python -m ruff format --check .`
- Show that each new regression fails at `bb3263e` (for example by running it against a temporary checkout of `bb3263e`), and record the result.
- The integration suite on the disposable PostgreSQL service of `backend/tests/README.md` is not required for these corrections, because they change no shared code. Record that it was not run, or its result if it was.

Commit with a message that names R011-01 to R011-09 and D-059, push `codex/spec-011-youtube` (D-051, D-058), and report the head commit to the owner. Do not open a pull request.

## Then: the owner's 011-B run

Guide the owner in Arabic through Parts B to E of the corrected checklist, one step at a time. Recommend that the test channel belongs to a Google account other than the Gmail sender's (D-057), and keep Part D steps 6 and 7 for last. The owner sends only the redacted evidence files or the printed summaries, never a value from `.env`. Record a dated summary answering F1-F14 in `evidence.md`. Where an answer differs from the entry review, write it as a proposed amendment, as D-054 did for Spec 010. A change to D1-D13 needs the owner's decision before 011-A uses it. Commit and push the evidence.

## Then: 011-A

When the 011-B evidence is recorded and any amendment is decided, prepare 011-A as entry review section 6 defines it. First write a short design note for migration `0015` (tables, columns, constraints, privileges and downgrade). Then implement the `synthetic_youtube` adapter and the runtime extensions of D2 to D13, with `backend/tests/integration/test_connector_youtube.py` covering the cases listed there, including a mutation check of each safeguard. Test migration `0015` upgrade and downgrade on the disposable PostgreSQL 18 service only; never on the owner's `tracking_sys`. Record the commands and counts in `evidence.md`, commit, push the branch, and present 011-A for owner review. 011-C (the live adapter and the re-verification of the `youtube.authorized_analytics` and `youtube.other_data` rows), 011-D, the pull request and the merge wait for the owner's decision.

## Follow-ups that stay open

- Rotate the `connectapp` connector client secret that was shared in the conversation before any use beyond owner test channels (D-058).
- After 011-B, delete `local-data\youtube-feasibility` (R011-08).
