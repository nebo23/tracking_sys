# Spec 016 entry review and decision packet

Prepared: 2026-11-22. Revision: 1. Status: preparation authorized by D-071; D1-D12 below were approved as recommended by D-072 on 2026-11-22. 016-A is implemented under them (see the [evidence](evidence.md)).

## 1. Baseline and intended result

Start from merged `main` at `2a0c8e512e9ae29aecea7728f57ecd366807f178` (Spec 015, [PR 13](https://github.com/nebo23/tracking_sys/pull/13)). Its tree is `e66c26e1c6ed7d8d7c535a30459aa94b4a52428a`, equal to reviewed PR head `f7d8289714afb3a0df3f724fea024b52b240206e`. Preparation uses `codex/spec-016-analytics-reporting` in an isolated worktree. Existing owner files and other worktrees remain intact.

The recommendation is a bounded first slice, **016-A: authenticated reporting over existing stored facts**, followed by explicit dependency work and later reporting slices. This does not complete Spec 016 or change the commercial requirement for multi-agency social analytics **and** attribution. No application code, schema, dependency, provider setting or native database changes are authorized by this preparation.

## 2. What the repository can supply

| Source | Evidence in the merged repository | Reporting consequence |
|---|---|---|
| Instagram | `backend/app/connectors/instagram.py`; connector records, stream checkpoints and sync runs | Account daily values use UTC; media/story observations are current lifetime values for content published in a cohort, not performance earned during that cohort's dates. |
| YouTube | `backend/app/connectors/synthetic_youtube.py`, shared by the live adapter; `connector_coverage.py` | Daily analytics use `America/Los_Angeles`; channel snapshots and video lifetime totals have different semantics. Preserve provisional and unavailable states and definition changes. |
| Meta advertising | `backend/app/services/advertising.py`; `AdSpendFact` and `AdAccount` | Account-local daily spend, clicks and impressions; retain original currencies, refusal counts, coverage and provisional dates. Grouping and pagination must retain currency (R010). |
| Revenue | `backend/app/services/revenue.py`; `backend/app/ledger/calculation.py` | Spec 015 stores evidence and derives the 007-A calculation. Verified postings, declarations, pending adjustments, held Paymob refunds and reconciliation are different states. A raw evidence sum is not revenue. |
| Bookings, CRM and WhatsApp | Spec 015 services and [integration guide](../../docs/engineering/integrations.md) | Existing current-state APIs remain usable. They do not establish historical funnels, identity joins or attributed sales. Do not infer a funnel from current CRM counts. |
| Identity and attribution | [006](../006-identity-journey/spec.md), [007](../007-revenue-ledger/plan.md), [008](../008-attribution-engine/spec.md) | 006 is a reviewed design; 007-B/C and persisted 008 integration are open. 008-A is a synthetic calculation slice. Real content revenue, model comparison and ROAS require these predecessors. |
| LinkedIn and X | D-063 | Deferred; no connector implementation or placeholder zero totals in this slice. |

Two implementation traps require an explicit contract. `MetricSpec.additive` defaults to true and is insufficient to decide whether reach can be summed over days. Also, `ConnectorRecord` is unique by connection, stream and provider object ID; updates replace the stored observation. A request timestamp cannot reconstruct an earlier version of an overwritten value.

The [015 correction tracker](../015-business-integrations/review-corrections-tracker.md) also retains A2 (CI activation) and A3 (financial calculation cost). Reporting must not turn repeated full-ledger calculation into an unbounded production query or invoke the prefix journal to produce a simple total.

## 3. Decisions for the owner

All recommended choices below form one proposed packet. An owner may approve the packet together or amend individual rows. The [design](design.md) defines the observable behavior, and the [verification matrix](verification-matrix.md) defines the required evidence.

| ID | Recommended decision | Alternative / consequence |
|---|---|---|
| D1 | Build 016-A now: separate social, advertising spend and recorded-revenue report APIs, previous-period comparisons where valid, and direct CSV downloads. Keep 016-B attribution reporting and 016-C retained/scheduled reports open. | Complete 006, 007-B/C and persisted 008 before starting any reporting. This enables a broader first release but delays independent reporting work. |
| D2 | One client per request; one connection for each social/spend report. Reuse existing `client:read` and `finance:read`, including scoped read credentials. No agency-wide rollup or combined endpoint that reveals financial metadata to non-financial readers. | Design cross-client rollups and additional permission rules separately. |
| D3 | Adopt the explicit metric classes in the design: additive activity, non-additive reach, snapshots, lifetime content cohorts and ratios/averages. A closed reporting catalog overrides unsafe generic defaults. Unknown semantics produce unsupported results. | Expose only raw observations until a broader metric dictionary is approved. |
| D4 | Require calendar dates `start` inclusive and `end` exclusive, at most 31 days per period. Use source-native days: Instagram UTC, YouTube Pacific, spend account-local, revenue UTC. Optional previous period has the same number of calendar days. | Arbitrary reporting timezones require finer-grained source facts; daily aggregates cannot be accurately rebucketed. |
| D5 | Revenue uses **activity by posting effective time, as known at the current read**: calculate the complete authorized evidence set first, then select final signed postings in the period. Keep currencies and unverified declarations separate; expose unresolved evidence counts. No FX, sale-cohort revenue, attribution model or ROAS claim. | A sale-cohort view needs a separately named contract and refund timing policy. Persisted historical revisions depend on 007-B. |
| D6 | Return provenance, native period, metric definition, coverage, freshness, provisional status and explicit reasons for unavailable values. A known partial subtotal is labeled partial; an unknown value is null. Never manufacture zero for an absent day, platform or attribution result. | Hiding incomplete rows would conceal source limitations. |
| D7 | Use bounded consistent database reads and deterministic pagination. A revision hash binds the normalized query, principal, scope, relevant facts and status inputs; later pages must present it. Changed inputs return `409 report_changed`, not mixed revisions. Recheck current authorization and source validity before releasing JSON or CSV. | Durable historical snapshots need new storage, retention, invalidation and schema decisions. |
| D8 | Development bounds: 10,000 relevant source rows across both comparison periods for social/spend; 200 total revenue evidence rows for a client before financial calculation; pages default 100, maximum 500; CSV maximum 5,000 output rows and 2 MiB. Reject excess explicitly, without truncated totals. Measure these bounds before accepting implementation. | Larger financial reports wait for an approved 007-B performance/persistence design; these limits are not production capacity targets. |
| D9 | CSV uses the same authorized full filtered result as JSON, with fixed typed columns, provenance/status fields, no names or other arbitrary free text, and no personal identifiers, evidence payloads or secrets. Prefix all identifier cells with `id:` and serialize numbers from validated numeric values. | Richly named/presentational exports need a separate spreadsheet-safety and field review. |
| D10 | No shared cache, retained export file, download token, background report job or new table in 016-A. Buffer each bounded download, authorize before release, and return `Cache-Control: no-store`. Keep the retained export/deletion obligation of 003 and full 016 AC5 open for 016-C. | Adding reusable download URLs now requires the 003 artifact lifecycle and explicit retention/schema approval. |
| D11 | Backend/API work only, using current dependencies, synthetic fixtures and disposable PostgreSQL. No new provider calls, scheduling, native migrations, frontend design or deployment. Respect the separate owner brief/brand gate for 018/UI work. | Any expansion requires a concrete additional decision, not an implicit consequence of starting 016. |
| D12 | After approval, implement and verify 016-A in reviewable commits on this branch; publish verified work under D-051. Present the completed slice for independent review. A new PR and merge require their own owner authorization. | The owner may explicitly authorize PR creation together with the implementation packet. No merge authorization is implied. |

## 4. Source requirement coverage and remaining slices

| Requirement | 016-A proposal | Remaining work; not silently closed |
|---|---|---|
| PDF-065 combined analytics | APIs with separate source, date and freshness semantics; UI can later compose them | 018 presentation, 020 scheduling/SLOs; no universal real-time promise |
| PDF-068 segmentation | Connection, metric, date and approved ad level only | Journey/person segmentation needs 006, privacy thresholds and an approved dimension catalog |
| PDF-071 CSV | Direct authenticated download of bounded stored facts | Retained/revocable exports in 016-C; warehouse and Sheets sync in 021 |
| PDF-073 comparisons | Previous period for comparable additive activity and revenue activity | External benchmarks require independent sources; 021 |
| PDF-038 model comparisons | Explicit dependency state only | 016-B after real journey and allocation integration; same cohort/model/window/evidence revision |
| PDF-067 funnels | No inferred funnel from bookings or current CRM state | 006 identity, explicit stage history and denominator/consent contract, then 016-B |
| PDF-069 content revenue | Social content cohort data only, never called attributed revenue | 007-B/C, persisted 008 and the 014-C join contract, then 016-B |
| PDF-070 scheduled reports | Deferred within Spec 016 | 016-C delivery, revocation, recipient permissions and scheduling; 017/020 as applicable |
| PDF-097 white-label client reports | No branding or visual work | 016-C delivery contract and 018 owner brief/brand approval |

016-A may close only its own evidence checklist. The full specification retains all five acceptance criteria, including retained export revocation. Global Q-001, Q-004, Q-006, Q-007, Q-011 and Q-012 remain open outside the explicitly approved slice; approving source-native days, currency separation and development limits does not choose production defaults or retention policy.

## 5. Preparation evidence and sources

This packet comes from source inspection of the merged tree and the existing specification evidence. It does not claim new runtime tests, live provider validation or a completed reporting feature. [Preparation evidence](preparation-evidence.md) records document checks and the exact base.

Technical references checked on 2026-11-22:

- [PostgreSQL 18 transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html): Read Committed can change snapshots between statements; Repeatable Read keeps a transaction snapshot. A stable data snapshot does not observe a concurrent permission revocation, so the design uses a separate current authorization check before response release.
- [OWASP CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection): quoting alone is not a universal spreadsheet formula defense, and spreadsheet save/reopen behavior matters. The first export therefore restricts field types and excludes arbitrary text; it makes no universal safety claim about subsequently edited files.

No external provider policy was re-approved by this entry review. Existing provider follow-ups and gates remain in their original specifications.
