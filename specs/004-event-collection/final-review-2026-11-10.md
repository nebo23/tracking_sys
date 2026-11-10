# Specification 004: final correction review

Date: 2026-11-10. Result: **no remaining blocking finding identified in the reviewed corrections; ready for publication to PR 3**. Merge remains the owner's decision.

PR: https://github.com/nebo23/tracking_sys/pull/3

Reviewed implementation: `7720868e8d766ab7efe7ca1d84e43df8d50a7826`, backend tree `d7dfff34c823022757f0a7f08476758957918a78`. Reviewed correction range: `b90fa53..7720868`, including `c229ac7` and `7720868`. The PR head was still `b90fa53` when this independent review began. The subsequent review-record commit changes documentation only.

## Findings disposition

| Finding | Final assessment |
|---|---|
| R004-01: unreadable public consent response | Closed for the reviewed HTTP contract. Source-specific uncredentialed CORS enables the registered origin to read the token and perform JSON preflights; platform cookie/CSRF boundaries remain covered. |
| R004-02: lifecycle races admission | Closed with R004-04. Collected-data cleanup holds the shared client privacy lock and rechecks eligibility; concurrent admission tests pass in both transaction orders. |
| R004-03: prematurely rejected webhook secret | Closed. All unexpired versions remain eligible through their recorded overlap. Rotation, expiry and cross-source/client regressions pass. |
| Query-value privacy observation | The reported prohibited card/email patterns are removed from retained query values, including the tested encoding forms. This is bounded pattern recognition, not general PII detection. |
| R004-04: historical grant revived between batches | Closed. A latest consent record remains while older records of the same subject/purpose exist. Removal follows the evaluator's `(received_at, id)` ordering. Each committed boundary therefore retains the effective record or leaves the purpose unknown; it cannot expose a historical grant. The existing client lock, bounded work and resumability remain intact. |

## Independent verification

An exact `git archive` of the reviewed implementation was tested without `.env`, using the existing project `.venv`. Inherited `TRACKING_`, `PG` and `PYTHON` variables were cleared. Settings and credentials were synthetic; collection keyrings came from the test fixtures. The dedicated Compose project was `tracking-review004final`, with disposable PostgreSQL database `tracking_foundation_test` on `127.0.0.1:55433` and separate runtime, migration and lifecycle roles. Native `tracking_sys` was not accessed.

| Check | Actual result |
|---|---|
| `python -m pytest -q -p no:cacheprovider -rs` on the unchanged implementation archive | **481 passed in 136.79 seconds**, no skips or warnings reported |
| Independent replay of the previous review reproduction | **2 passed in 2.61 seconds**, batch sizes 1 and 500 |
| `python -m ruff check app migrations tests` | Passed |
| `python -m ruff format --check app migrations tests` | 83 files already formatted |
| `python -m pip check` | No broken requirements |
| `git diff b90fa53..7720868 --check` | Passed |

The independent reproduction used 30-day supported retention, a still-valid historical grant, and a newer withdrawal whose UUID sorted before the grants. After one committed cleanup batch, the withdrawal remained, a new event still returned `422 consent_withdrawn`, and no event was stored. Resuming cleanup removed the remaining consent and subject; the old token then returned `unknown_subject`. These are the same two cases that previously accepted and stored an event.

The full suite also covers denial, multiple purposes, receipt-time ties, unbounded completion, active-subject preservation, consent evidence, database privileges, migration cycles and model consistency, data-policy registration, and the OpenAPI snapshot. The reviewer inspected the final implementation diff and the correction tests. No application code was changed during this review.

## Publication and remaining boundaries

D-031 records the owner's request to review for upload and authorizes publishing the successfully verified corrections to the existing branch and PR. The historical local-only gates in D-029/D-030 are satisfied for this reviewed correction set. No merge, deployment, native rollout, dependency, schema or new product policy is authorized by this review.

No new real-browser run, load test, API-container smoke test or live-provider test was performed here. The earlier headless Chrome run remains implementation evidence; this review independently checked the HTTP/database contract. Production key custody, workload sizing and customer-data policy questions Q-002/Q-004/Q-012 remain open. The separate predecessor items P1-P4 remain outside this branch.

Temporary diagnostic code and synthetic settings are not included in the commit. Only the review's own disposable resources are removed after verification. Unrelated root-worktree changes and the historical review reports are preserved.
