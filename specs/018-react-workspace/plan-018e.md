# Plan of P2: Attribution (018-E)

Status: phase P2 of the [completion handoff](implementation-prompt-completion.md), approved with D1-D12 of the [completion entry review](entry-review-completion.md) by D-099 (2026-11-28). Done on 2026-11-28: see the [evidence](evidence-018e.md). This plan was written down after the code, from the notes of the phase; nothing in it deviates from the packet except the explicit range "up to today" of section 4.

## 1. The page
One page at `/agencies/{a}/clients/{c}/attribution` with the tabs Credit (C08), Funnel (C09) and Return on ad spend (C10), the tab in the address (`tab`, the default left out), as D6 describes. The head is the one of Analyze: range, comparison and the CSV of the open tab.

- **Model.** The client's active versions from `GET .../attribution/models`, the default first; the chosen version is kept in the address (`model`, the default left out) and sent as `model_version`.
- **Grouping.** Campaign, content, link or recipient for credit; campaign, content or link for the funnel (`group`, the default left out).
- **ROAS.** The ad account and the level of Ad spend (`connection`, `level`); names joined from the 014 read.

## 2. Reports
`attributionReportQuery` (groups and models views; the models view sends neither a comparison nor a model version), `funnelReportQuery` and `roasReportQuery` in `src/api/reports.ts`, every page read with the revision of the first, keyed under the agency and the client.

## 3. States
Freshness `behind`, `rebuilding` and `failed` as banners over the published values; `not_ready` and `attribution_not_ready` in words, never 0; `permission_unavailable` as "Needs financial access" with lead credit kept; the reconciliation's `difference` with its reason; ROAS reasons (`zero_spend`, `zero_leads`, `currency_mismatch`); visits that cannot be measured; credit that matched no ad, apart. A unit test reads the reasons of `backend/app/reporting/` and `backend/app/advertising/roas.py`.

## 4. Up to today
Journey `21-attribution` makes today's lead, and Analyze ranges end on the last complete day, so the lead could not be shown. D10 of the 018 entry review (D-083) approves "Up to today" as an explicit choice that marks provisional days; it is added as the preset "Last 30 days, up to today", with a notice that today is provisional and never compared. A range may now end today, never later; the defaults still end on the last complete day.

## 5. Tests
Unit tests for the rules and the three tabs; journey `21-attribution` with a lead that came through a campaign link and one attribution pass; the three tabs in the accessibility scans of the four looks and at 390 pixels; the removed protections of the handoff.
