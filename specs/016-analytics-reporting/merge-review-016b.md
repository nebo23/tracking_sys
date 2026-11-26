# Spec 016-B merge review (PR 18)

Reviewed 2026-11-26 at head `2958b9e` of `codex/spec-016b-attribution-reports`, against `main` at `f15b6e4`. The owner asked Claude to review the completed branch and merge it if the review confirmed it. The review found two defects. The owner chose to correct both before the merge, and recorded that choice as D-090.

## Scope of the review

The review checked the implementation against decisions D1-D14 of the [entry review](entry-review-016b.md), the [design note](design-016b.md) and the [evidence](evidence-016b.md):
- **The four parts:**
  - the attribution report, in its groups and models views;
  - the ROAS report and `roas_from_credit` beside `roas_report`;
  - the funnel report;
  - the conversions list.
- **The stored-credit reads (`attribution_reports.py`):** the published-generation filter, the exact fraction sums, the group, event and spend bounds, the registered flags, the social content pointer and the ledger reconciliation.
- **The release corrections O1 and O2 of the [008-B merge review](../008-attribution-engine/merge-review-008b.md):** the change token that the runs route and the list read before and after building an answer, and the status route in one snapshot.
- **The adapter change (D7a):** the `utm_content` rule, its precedence and the input adapter revision in the model-set digest.
- **The finance split (D9), the revision and the release check (D10):** the CSV identifier cells and migration `0030`.

## Verification run by the reviewer

All cases ran on a fresh disposable PostgreSQL 18.6 service (127.0.0.1:55433, `tracking_foundation_test`), with the repository's three roles and synthetic settings only.

| Check at `2958b9e` | Result |
|---|---|
| `ruff check app tests migrations`, `ruff format --check app tests migrations` | Clean (295 files) |
| `pytest -m "not integration"` | 933 passed |
| `pytest -m integration` with `TRACKING_RUN_BROWSER_TESTS=1`, Chromium | 683 passed; 7 skipped (the opt-in BV19, AV16 and D-076 measurements); the Firefox journey case not run |
| Tracker unit and browser (Chromium) | 73 and 25 passed |
| `pip check`, `git diff --check`, relative links of the changed Markdown (350) | Clean |
| OpenAPI, semantic comparison with `main` | 4 paths and 42 schemas added; `Dependency` gains the `available` state and `family`; nothing else changed |

Firefox is not installable in the review environment. The implementing model's evidence records the Firefox cases passing.

## Findings

### R016B-01 (P2): the funnel separates a UTM-only managed link's visits from its credit

The funnel grouped a visit through a managed link by the link's registered campaign or content reference only. The attribution input adapter credits the touch of that visit under the link's `utm_campaign` and `utm_content` values when the link has no registered reference. A managed link created with `"utm": {"utm_campaign": "spring"}` and no campaign therefore produced two funnel rows:
- `spring`, with the credited sales and revenue and `visits: unsupported`;
- "no campaign", with the visits and no credit.

**Reproduction at `2958b9e`:** `test_review_r016b_01_utm_only_link_visits_join_their_credit` failed, because the `spring` row had `{"state": "unsupported", "count": null}` visits instead of one.

**Correction:** a visit takes the reference that the input adapter gives its touches: the registered code, else the value of the link's UTM snapshot, which the redirect composes into the landing URL. A reference counts as supported when a managed link carries it either way.

### R016B-02 (P2): sale-only groups were visible without `finance:read`

D9 withholds sale values from a reader without `finance:read`. The attribution and funnel reports built their groups from all credit, however, so a group that held only sale credit was listed for such a reader, with `permission_unavailable` sales and no lead credit. Its name, the number of rows and the CSV showed that the group had produced sales.

**Reproduction at `2958b9e`:** `test_review_r016b_02_sale_only_groups_stay_hidden_without_finance` failed, because the analyst's groups response named `autumn`, a campaign with sale credit only.

**Correction:** without `finance:read`, only lead credit shapes the groups, the row count, the group bound and the export. Lead credit groups stay.

### Observations without a change

- The conversions list orders by the stored conversion time, and long paginations can meet `report_changed` under continuous intake. The evidence records both as limits.
- The traffic source is not stored, so the ROAS join cannot test `utm_source`. D7 of the entry review accepts this.

## Corrections and their verification

Both corrections are in `backend/app/services/attribution_reports.py`, and the regressions are in `test_funnel_reports.py` and `test_attribution_reports.py`. Both regressions fail at `2958b9e` and pass with the corrections (`4b2acb1`).

| Check at `4b2acb1` | Result |
|---|---|
| `ruff check`, `ruff format --check` | Clean (295 files) |
| `pytest -m "not integration"` | 933 passed |
| `pytest -m integration` with `TRACKING_RUN_BROWSER_TESTS=1`, Chromium | 685 passed; 7 skipped (the opt-in measurements); the Firefox journey case not run |

The [evidence](evidence-016b.md#review-corrections-d-090) records the same results.
