# Independent review of the partial Spec 015 corrections

Review date: 2026-11-22. Implementation reviewed: `a291bb6c9e5a3aeba267528b13fa62a5af4046d3` on `codex/spec-015-business-integrations`, [PR 13](https://github.com/nebo23/tracking_sys/pull/13). Base: `73efae9249e7111281a9c5e8c1f7a12771cd013a`. Original defective baseline: `db750d1b728f2ca352a999afe71c92a1b10730e1`.

## Decision

**Do not merge this partial correction head.** The implementer completed commits for R001-R008 and explicitly stopped before R009-R011. The latter three findings remain merge blockers under D-069. This review evaluates the existing corrections; it does not implement the remaining application changes or authorize native rollout, live provider use or deployment.

Independent verification: **1,286 passed, 4 failed, 0 skipped** in the full backend suite. The four failures are exactly the two R009 cases and the R010/R011 cases. The original review regressions now give **9 passed / 4 failed**: the nine cases covering R001-R008 pass, as do the added adjacent cases. No additional blocking defect was identified in the eight corrections within this review's scope.

## Review of R001-R008

The review inspected the application changes, regression tests, adjacent cases, migrations, grants, generated contract and D-070 decisions. The original thirteen regression cases are retained in the permanent suite. The following conclusions concern the approved synthetic/disposable scope, not live-provider acceptance.

| ID | Fix commit | Reviewed behavior and adjacent coverage |
|---|---|---|
| R001 | `b586287` | Paymob posting now requires a signed integration ID in the source's declared live list. Refunds and voids must bind to a sale of the same signed order; mismatched children arriving before their parent are held out of verified calculations and delivery candidates when that parent arrives. Valid sales/refunds, test mode, source configuration and both arrival orders are covered. |
| R002 | `24097aa` | Explicit erasure and lifecycle cleanup detach both booking link columns before deleting a subject, within the transaction. Tests cover rollback, multiple links, another client, the tombstone and restricted lifecycle privileges. |
| R003 | `9e2e015` | Withdrawal/denial detach links; reads check current consent and expiry. A grant after a lapse does not silently restore an old link. Tests cover renewals, replay, chain merges and both orders of concurrent withdrawal and delivery. |
| R004 | `0813f4f` | Number registration is a pending claim and cannot route or self-activate. The D-070 platform-operator workflow verifies one binding, revokes it or transfers it. Tests include a hostile first claim, legitimate enrollment, tenant separation, database uniqueness and CLI restrictions. |
| R005 | `b4ed895` | Callback `type` is checked as a string before set membership. Malformed shapes return the uniform 401 without storage; valid transaction and token callbacks remain accepted. |
| R006 | `fe8ce8a` | Booking and event identities include the delivering source. Duplicate local identifiers, reschedules and cancellations stay within that source, including two Cal.com sources and another client's source. |
| R007 | `74bee1a` | Stage, amount/currency and payment reference each keep their own occurrence ordering and deterministic tie-break. Tests exercise all 24 orders of a partial event history, equal-time ties and a later nonmatching reference. |
| R008 | `a291bb6` | CRM totals aggregate the complete authorized scope. Details use a full `(first_received_at, id)` keyset cursor. Tests cover 1,203 deals, five pages, multiple currencies, another client, permissions and invalid cursors. |

D-070 explicitly approves the two trust decisions in R001 and R004. Declared live integration IDs remain an owner/admin assertion; the shared order of a Paymob refund and parent still requires the separately gated live check. WhatsApp ownership remains an out-of-band platform-operator check. These are recorded limitations of the approved design, not newly invented closure requirements or evidence of a live-provider test.

## Remaining findings

### R009 / P2: One malformed WhatsApp item still rejects a valid sibling

`backend/app/integrations/whatsapp.py:68` converts a twelve-digit timestamp without catching unsupported date ranges. At line 87, a list/object `source_type` is still used in set membership. Both original malformed-item cases reproduced HTTP 500 instead of 200 at `test_review_001_015.py:235`. The intended fix must validate each item and preserve valid siblings while keeping signature verification and genuine storage failures truthful.

### R010 / P2: Advertising pagination still loses a currency group

`backend/app/services/advertising.py:136` filters a group using only `object_id`, although groups are keyed by `(object_id, currency)`. With two currencies for one object and `limit=1`, the second currency cannot be reached. The regression at `test_review_001_015.py:204` still returns only `{'EGP'}` instead of `{'EGP', 'USD'}`. The complete grouping key must be carried in ordering, cursor and continuation filtering.

### R011 / P2: The Instagram day cursor still shifts across midnight

`backend/app/connectors/instagram.py:448` recalculates the rolling history boundary on each request, while lines 473-487 apply a numeric cursor to the newly built day list. Resuming across midnight can skip a day. The regression at `test_review_instagram_cursor.py:24` still returns November 24 after November 22, 2024. Use a stable day position and verify truthful coverage without restoring days outside the provider's supported history.

These are the three previously reported findings, not new defects attributed to the eight correction commits. R010 and R011 affect predecessor specifications 014 and 010 and remain explicitly in the D-069 scope.

## Independent verification

The reviewed commit was exported into a private archive without copying ignored environment files. A byte comparison of all 456 tracked files found no unexpected difference. Application code was unchanged. Tests used a new disposable PostgreSQL 18.6 container on `127.0.0.1:55434`, database `tracking_foundation_test`, synthetic credentials and the repository's role-initialization script. Only the archive's integration-fixture port guard was changed from 55433 to 55434, preserving its database-name and explicit-opt-in checks. The native database on 5432 and the existing disposable container on 55433 were not used.

The project `.venv` supplied Python and approved dependencies. Browser journeys were explicitly enabled and used the existing local tracker dependencies through a temporary junction. No package was installed and no provider was called.

| Check | Observed result |
|---|---|
| `python -m pytest -q --tb=short --show-capture=no` from the archive's `backend/`, with database and browser flags enabled | **1,286 passed, 4 failed, 0 skipped in 747.06 s**; 497 integration cases and 793 unit/contract cases collected |
| Original review regressions within that run | **9 passed, 4 failed**; only R009 (two cases), R010 and R011 failed, at the intended assertions |
| Backend browser journeys within that run | **3 passed**, including Chromium and Firefox; included in the count above |
| Ruff lint and format check | Passed; 221 Python files already formatted |
| `python -m pip check` | Passed |
| `git diff --check db750d1 a291bb6` | Passed |
| Tracker source/dependency diff from the original review | None; the prior 67 JavaScript unit and 44 Chromium/Firefox results were not rerun in this partial review |
| GitHub commit statuses and PR-triggered workflow runs at `a291bb6` | Both returned empty lists; this is not a successful CI run or branch-protection verification |
| GitHub PR state | Open, unmerged, head `a291bb6`, base `73efae9` |

The implementer's mutation-test results are recorded in [correction evidence](../specs/015-business-integrations/review-corrections-evidence.md). This review inspected those tests and reran the ordinary suite; it does not claim to have independently rerun the mutations.

After verification, the private archive, one-time runner, dependency junction and review container were removed. The original tracker dependencies and the existing disposable container on 55433 were preserved. This follow-up changes only this report and the correction tracker.

## Documentation and continuation

At the reviewed head, the tracker still labelled all eleven findings `REPRODUCED`, despite the eight implementation commits. This documentation-only independent-review update records R001-R008 as `FIXED_PENDING_REVIEW`, with this evidence, and leaves R009-R011 `REPRODUCED`. `CLOSED_VERIFIED` and the final merge record must wait for the completed correction head and final second pass required by the handoff.

A1 remains unfinished: the README still advertises revision `0016_youtube_provider` and 88 API operations, while the branch's migration head is `0025_whatsapp` and its generated contract has 121 operations across 99 paths; the setup/status documentation and PR description need reconciliation at completion. A2 has no observed CI execution. A3, the ledger calculation scaling risk, remains a disclosed follow-up; this review does not claim it was fixed or rerun its earlier benchmark. Specifications 012/013 and the other approved future slices remain outside this correction task.

Continue from the existing branch and [correction handoff](../specs/015-business-integrations/review-corrections-prompt.md). Do not redo or overwrite the reviewed fixes. Complete R009, R010 and R011 one at a time with the original regressions and adjacent positive cases; reconcile A1 and record A2/A3 accurately; run the final complete checks; independently review R001-R011 at the final implementation SHA; then apply D-069's conditional merge gate. This partial review is not that final merge clearance.
