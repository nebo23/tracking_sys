# Product design research for specification 018

Collected on 2026-11-25 for the [018 entry review](../../specs/018-react-workspace/entry-review.md) and the [design language](../../docs/design/README.md). Each note states how it was obtained. Agency blogs and vendor pages are marked as opinion.

## 1. What the interface must show
Read from the merged repository at `81977a3`:

- `contracts/openapi.json`: 124 operations. The interface-relevant groups are authentication (12) and Google sign-in (3), agency access (20), connectors (13), reports (3), revenue (4), advertising (7), payments (4), integrations (9), WhatsApp (4), managed links (20) and event collection (12).
- [`docs/engineering/reporting.md`](../../docs/engineering/reporting.md): the 016-A reports carry availability, total status, coverage, freshness and provisional fields, and give a comparison only when both periods are complete, final, fresh and of one definition. This is the origin of the data-state language and of the rule that default date ranges end on the last final day.
- Reports are per client and, for social and spend, per connection. There is no agency-wide rollup and no combined social and financial report, so the Overview screen composes separately sourced figures and never mixes them into one ratio.
- Attribution, funnels, content revenue and return on ad spend are not available (016-B, after 006 and persisted 008). The Attribution screen is therefore a concept.

## 2. Visual survey of comparable products
Measured by opening each public home page in a browser and reading the computed styles (font family of body and first heading, and the most used saturated colors). These are marketing sites, not the products' signed-in interfaces.

| Product | Typefaces | Dominant colors | Note |
|---|---|---|---|
| Metricool | Plus Jakarta Sans | `#2d1a29` aubergine, `#e7ff56` lime, `#f87fdd` pink | Social analytics for agencies |
| Sprout Social | Proxima Nova | `#98e58e` green on black | Social management |
| AgencyAnalytics | DM Sans | `#df2020` red | Agency reporting |
| Triple Whale | Inter, TWK Lausanne | `#033855` navy, `#99ffff` cyan, `#ff835e` coral | Attribution |
| Northbeam | Poppins, TT Commons | `#01082b` navy, `#7081ff` periwinkle | Attribution |
| Dub | Inter, Satoshi | `#3b82f6` blue on near-white | Link attribution |
| Whatagraph | Inter | `#101828` slate, `#1863dc` blue | Agency reporting |
| Hootsuite | Montserrat | `#012b3a` dark teal, `#e03035` red, `#1f60c9` blue | Social management |
| Linear | Inter Variable | `#08090a` near-black, `#5e6ad2` indigo | Interface benchmark |
| PostHog | Custom | `#eeefe9` beige, `#2f80fa` blue, `#eb9d2a` orange | Analytics benchmark |

Reading: blue, indigo and navy dominate the category; green, red and lime are each taken by a direct competitor; Inter is the default typeface. A mid teal with a deep teal ink is unclaimed among these products, stays clear of the state colors (red, amber, green) and reads as calm on long sessions.

## 3. Dashboard practice
- Nielsen Norman Group, ["Dashboards: Making Charts and Graphs Easier to Understand"](https://www.nngroup.com/articles/dashboards-preattentive/) (2017, citing Cleveland and McGill): length and position for quantities; color as a secondary cue; avoid pies, gauges, treemaps and 3D on action dashboards.
- Lazarev agency, ["SaaS dashboard design"](https://www.lazarev.agency/articles/saas-dashboard-design) (2026, opinion): three layers of figures (immediate, supporting, on demand); summary, then trend, then detail.
- Trend articles for 2026 ([dev.to](https://dev.to/thekitbase/saas-dashboard-design-trends-in-2026-with-examples-121m), [adminlte.io](https://adminlte.io/blog/25-best-dashboard-design-examples-for-2026-real-products-principles/), opinion): less chrome, one accent color, color reserved for state, role-based views.
- User reviews of attribution tools ([G2, Triple Whale](https://www.g2.com/products/triple-whale/reviews), search-result excerpts): at least one reviewer doubted whether the dashboard overstated sales because returns were not included. This supports showing refunds, verified versus declared amounts and data state openly.

## 4. Accessibility
- W3C, [What's new in WCAG 2.2](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/): focus not obscured (2.4.11), dragging alternatives (2.5.7), target size of at least 24 by 24 CSS pixels (2.5.8), consistent help (3.2.6), redundant entry (3.3.7), accessible authentication (3.3.8).
- Smashing Magazine, ["How Accessibility Standards Can Empower Better Chart Visual Design"](https://smashingmagazine.com/2024/02/accessibility-standards-empower-better-chart-visual-design) (2024): chart marks at 3:1 against neighbors, text at 4.5:1, a second encoding beside color, direct labels, a table alternative.
- The chart palette was tested with the method of the data visualization skill used in this session: OKLab distances under the Machado, Oliveira and Fernandes (2009) simulation. `build-tokens.mjs` re-implements the gates, and its figures matched the skill's validator (11.9 and 19.6 light, 9.9 and 19.3 dark).

## 5. Arabic and right-to-left
- Apple, [Human Interface Guidelines: Right to left](https://developer.apple.com/design/human-interface-guidelines/right-to-left) (read in a browser): align text with the interface direction; never reverse the digits of a number; flip progress and navigation controls; keep logos, check marks and real-world objects unflipped; Arabic beside Latin capitals can look small, so raise its size; Western or Eastern Arabic numerals vary by region.
- Alebri and others, ["Design Patterns in Right-to-Left Visualizations: The Case of Arabic Content"](https://research.uaeu.ac.ae/en/publications/design-patterns-in-rightto-left-visualizations-the-case-of-arabic/) (IEEE VIS 2024, abstract): 128 visualizations from Arabic news outlets show mixed left-to-right and right-to-left chart directions, and no clear guideline exists.
- Search-result excerpts, not read in full: Apple's developer session ["Get it right (to left)"](https://developer.apple.com/videos/play/wwdc2022/10034/) places the earliest time on the right in a right-to-left chart; Wikimedia's [Codex style guide](https://doc.wikimedia.org/codex/v2.3.2/style-guide/bidirectionality.html) mirrors a chart only when the meaning survives. The sources disagree, so chart direction is put to the owner (D4).
- shadcn/ui, [RTL documentation](https://ui.shadcn.com/docs/rtl) and [changelog of January 2026](https://ui.shadcn.com/docs/changelog/2026-01-rtl): the command line tool converts physical classes to logical ones when `rtl` is enabled; Calendar, Pagination and Sidebar need manual steps; it suggests Noto for Arabic.
- The Material Design bidirectionality page could not be read in this environment and is not cited as evidence.

## 6. Typefaces
Google Fonts metadata, read on 2026-11-25 (`https://fonts.google.com/metadata/fonts`): families with Arabic and Latin subsets, by popularity rank.

| Family | Rank | Weights | Note |
|---|---|---|---|
| Rubik | 26 | variable 300 to 900 | Rounded |
| Cairo | 52 | variable 200 to 1000 | Kufi, very common |
| Tajawal | 74 | static 200 to 900 | Geometric |
| Almarai | 94 | static 300, 400, 700, 800 | No 500 or 600 |
| IBM Plex Sans Arabic | 98 | static 100 to 700 | Pairs with IBM Plex Sans and Mono; updated March 2026 |
| Noto Sans Arabic | 113 | variable 100 to 900, width axis | Neutral |
| Readex Pro | 123 | variable 160 to 700 | Arabic by Nadine Chahine on Lexend |
| Vazirmatn | 170 | variable 100 to 900 | Persian and Arabic |
| Alexandria | 247 | variable 100 to 900 | Geometric, wide |
| Alan Sans | 490 | variable 300 to 900 | Added 2025 |
| Firjar | 687 | variable weight and width | Added November 2026 |

Fourteen candidates were rendered side by side in the same interface sample (figure, navigation, table rows, a sentence) in English and Arabic at 12 to 30 pixels. Findings: IBM Plex Sans with IBM Plex Sans Arabic kept the two scripts closest in size, density and line count, with clear numerals; Readex Pro and Alexandria read comfortably but are wide and cost a line or a column in tables; Noto Sans Arabic with Inter is neutral with taller lines; Firjar and Fustat are stylized for running text. The specimen images were working material and are not stored.

For the Arabic wordmark, thirteen families were set as outlines beside the mark. Alexandria SemiBold matched the single-thickness geometric Latin letters best.

## 7. Tokens and tooling
- Design Tokens Community Group, [Format Module 2025.10](https://www.w3.org/community/reports/design-tokens/CG-FINAL-format-20251028/), the first stable version (October 2025; a community report, not a W3C standard). `tokens.json` follows its value shapes: color as `colorSpace`, `components`, optional `alpha` and `hex`; dimensions and durations as `value` and `unit`; curly-brace references.
- Package versions on the npm registry on 2026-11-25, for the toolchain proposal only: react 19.3.1, vite 8.3.8, typescript 7.0.2, tailwindcss 4.3.5, @tanstack/react-query 5.108.4, @tanstack/react-router 1.170.46, react-router 8.5.3, @tanstack/react-table 9.3.1, recharts 3.11.1, @visx/xychart 4.0.0, echarts 6.1.0, shadcn 4.23.0, radix-ui 1.8.1, react-aria-components 1.22.1, lucide-react 1.80.0, react-i18next 18.0.3, zod 4.6.7, react-hook-form 7.92.0, vitest 5.1.2, @playwright/test 1.65.1, openapi-typescript 7.13.0, openapi-fetch 0.17.0.
- Chart library comparisons ([LogRocket](https://blog.logrocket.com/top-5-react-chart-libraries/), [TanStack](https://tanstack.com/charts/latest/docs/comparison), opinion): Recharts as the practical default for dashboards under about ten thousand points; ECharts for very large series; visx for full control at higher build cost. None of the sources assesses accessibility.

## 8. Name and logo
- A web search for an existing social analytics or attribution product named "Connect" returned none in this category, but the word is used by many products in other categories, among them [Stripe Connect](https://docs.stripe.com/connect) in payments. No trademark or domain search was made.
- Logo trend articles for 2026 ([Creative Bloq](https://www.creativebloq.com/design/logos-icons/these-logo-design-trends-will-define-2026), [Shopify](https://www.shopify.com/blog/logo-trends), opinion): simple geometric wordmarks remain usual for software, with one distinctive detail to avoid a generic result.
- A second round of logo research on 2026-11-25, after the owner's review, is recorded with its sources in the [logo brief](../../docs/design/brand/logo-brief.md): Paul Rand's essay on logos (read in full), the criteria of Chermayeff & Geismar & Haviv, wordmarks that hide one idea in their letters, practice for very small sizes, and the use of the magnet in logos and in marketing language. Six options were drawn; the owner chose "Pure magnet" (D-075).

## 9. Limits of this research
- No interviews, surveys or usability tests were run. The audience description comes from the product brief.
- Competitor observations come from public marketing pages on one day.
- The chart-direction and numeral choices for Arabic rest on published guidance and should be confirmed with Arabic-speaking users.
