# Spec 018 entry review and design decision packet

Prepared: 2026-11-25. Revision: 4 (2026-11-26). Revision 2 followed the owner's design review of 2026-11-25; revision 3 changed the recommendation of D13 and added D15; revision 4 records the owner's approval. Status: decided. D-082 decides D6 (the logo) and approves the sign-in screen and the search field (section 5.1). D-083 approves D1-D5 and D7-D15 as recommended (section 5.2). No package is installed and no application code is written until the owner approves the package list of the [018-A plan](plan-018a.md); a migration needs its own decision.

## 1. Baseline and intended result
Start from merged `main` at `81977a38110458a75838baa47c73029a0495c2ae` (Spec 016-A, [PR 14](https://github.com/nebo23/tracking_sys/pull/14)). Preparation uses `codex/spec-018-react-workspace` in an isolated worktree. Existing owner files and other worktrees remain intact.

The owner asked for research first, then the complete visual design of the product, which the owner calls Connect: colors, logo, look, and an interface that is fitting, comfortable and clear. This packet delivers:

- research evidence: [research_notes/product-design/sources.md](../../research_notes/product-design/sources.md);
- the design language, tokens, reference styles and brand assets: [docs/design/](../../docs/design/README.md);
- eleven screen designs as static reference pages: [docs/design/preview/screens.html](../../docs/design/preview/screens.html);
- the decisions that the owner needs to take before implementation.

The same design is published for the owner as two private pages, a design system and a canvas of screens. Their addresses are given in the session report, not stored here.

## 2. What the repository can supply
| Area | Evidence in the merged repository | Consequence for the interface |
|---|---|---|
| Sign-in and accounts | Authentication and Google sign-in routes; six-digit email code (D-022) | Sign in, register, verify, recover and close account can be built against the existing API. |
| Agencies, clients, people | Agency access routes; roles Owner, Admin, Analyst and Client viewer; client and financial grants | Two navigation levels: the agency and one client. Financial data is gated separately from client access. |
| Connections | Connector routes with status, coverage, sync state and quota | A connection card can show status, freshness, per-stream coverage and the reconnect path. |
| Reports | 016-A social, spend and revenue reports with availability, total status, freshness and provisional fields | The data-state language of section 4. One client and, for social and spend, one connection per report: no agency rollup and no combined ratio. |
| Revenue | Ledger read, CSV import, manual declarations, Paymob sources | Verified, declared and unresolved amounts are separate blocks. |
| Links and tracking | Managed links, campaigns, content references, UTM templates, domains; event collection and diagnostics | Links list and create form; domain verification and tracker setup follow in a later slice. |
| Attribution and journeys | 006 is a design; 008-A is an in-memory calculation; 016-B is open | No real screen yet. The packet includes a concept only, labeled as such. |
| Subscriptions | Spec 017 is not started | No billing or plan screen is designed. |

The specification lists 016 and 017 as dependencies. 016-A is enough for the first slices; 016-B, 016-C and 017 gate their own screens only.

## 3. Research findings that shaped the design
1. The report contract already distinguishes missing, unsupported, stale, partial and provisional values. Competitor reviews show distrust when dashboards hide such gaps. Showing source and state on every figure is therefore the product's signature, not decoration.
2. Blue, indigo and navy dominate the category, and Inter is the default typeface. A teal with a deep teal ink, and the IBM Plex family, separate Connect from that field without leaving the calm, trustworthy register the product needs.
3. Arabic and English must be designed together. The IBM Plex family kept both scripts closest in size, density and line count in a side-by-side rendering of fourteen candidates.
4. Published guidance disagrees on chart direction in Arabic, so the question is put to the owner rather than assumed.
5. A comparison exists only for final periods. Default date ranges should therefore end on the last final day, or most views would show no comparison.

## 4. The proposed design in brief
- **Brand**: the capital C as a horseshoe magnet with two teal pole tips, and every other letter regular (content pulls customers in, and Connect tracks the pull to the sale). Latin logo, Arabic lockup, mark, application icon and favicon. Approved by D-082.
- **Color**: one teal for actions, selection and the first chart series; cool neutrals; green, amber, red and blue reserved for states; a fixed eight-color chart order validated for color-vision deficiency.
- **Type**: IBM Plex Sans, IBM Plex Sans Arabic and IBM Plex Mono.
- **Layout**: sidebar, top bar and a content column; a bottom tab bar on phones; agency level and client level.
- **Data states**: one icon, one word and one sentence per state; a missing value is never zero; comparisons are hidden with a stated reason.
- **Themes and direction**: light and dark, left to right and right to left, from the first slice.

Details, token values and audit results are in the [design language](../../docs/design/README.md).

## 5. Owner decisions
| ID | Decision | Recommendation | Alternative |
|---|---|---|---|
| D1 | Product name in the interface | "Connect", with the Arabic lockup "كونكت" available. Run a trademark and domain search before any public launch; the word is common. | Another name, or Connect with a descriptor. |
| D2 | Interface languages at launch (part of Q-006) | English and Arabic, both designed and tested from the first slice. | English first, Arabic in a later slice. This risks layouts that do not mirror. |
| D3 | Numerals, calendar and currency display | Western digits and the Gregorian calendar in both languages; `EGP 128,450.75` in English and `128,450.75 ج.م` in Arabic. | Arabic-Indic digits in Arabic, as a user setting. |
| D4 | Chart direction in Arabic | Time runs from left to right; the card around the chart mirrors. Confirm with Arabic-speaking users. | Mirror the time axis, as Apple's guidance describes. |
| D5 | Brand color | Teal (`brand-600` `#007a79` for actions, `brand-950` `#02282c` as ink). | A cobalt or violet brand. The tokens make the switch a change of one ramp, but the category is crowded there. |
| D6 | Logo | Decided by D-082: "Pure magnet", option 2 of the [logo brief](../../docs/design/brand/logo-brief.md), with the custom Latin wordmark and the Arabic lockup. The first proposal, a ring closed by a dot, was not accepted. | None; decided. |
| D7 | Typeface | IBM Plex Sans, IBM Plex Sans Arabic and IBM Plex Mono, self-hosted. | Readex Pro (friendlier, wider) or Noto Sans Arabic with Inter (most neutral). |
| D8 | Themes | Light and dark, following the system setting with an explicit choice in the account menu. | Light only at launch. |
| D9 | Data-state language | Adopt the state table of the design language as a product rule for every screen and export. | None recommended. |
| D10 | Default date ranges | Ranges end on the last final day; "Up to today" is an explicit choice that marks provisional days. | Ranges end today; most comparisons would then be hidden. |
| D11 | Navigation | Agency level (Clients, Team and access, API keys, Audit log, Privacy and data) and client level (Overview; Analyze: Content, Revenue, Ad spend, Attribution; Collect: Links, Website tracking, Integrations; Manage: Connections, Reports). | Fewer groups, with the collection tools under Settings. |
| D12 | Accessibility target | WCAG 2.2 level AA, checked in each slice. | None recommended. |
| D13 | Frontend toolchain (Q-009) | React 19 with TypeScript and Vite; the reference styles of this design as the application's stylesheet (`tokens.css`, `connect-ui.css`, `connect-icons.css`), so the screens the owner reviewed are built as drawn; React Aria Components for the behavior of menus, dialogs, selects, tabs, date pickers and the command palette; TanStack Query; a typed client generated from `contracts/openapi.json`; Recharts for charts; an i18n library with ICU messages; Vitest and Playwright; fonts and icons as local packages. Exact versions are pinned when approved. | Tailwind CSS 4 reading these tokens, with shadcn/ui components and right-to-left enabled. It is the most common kit and quick to start, but every component is then drawn a second time in another vocabulary, with a risk of drifting from the approved look, and it adds more packages. |
| D14 | Slices | 018-A: toolchain, tokens, application shell, sign-in and account flows. 018-B: clients, team and access, connections. 018-C: overview, content, revenue and ad spend on the 016-A reports. 018-D: links, tracking and integrations. Attribution and journeys follow 016-B. | One slice per screen. |
| D15 | Record of agreement to the terms | Store one record per account and terms version (who, which version, when), written at registration and at sign-in, through an amendment to specification 002 with its own schema review. The sign-in box stays as approved in D-082. The owner supplies the Terms of Service and the Privacy Policy. | Keep the box without a record. Not recommended: nothing would show who agreed to what. A lighter form asks at registration and again only when the terms change. |

D13 names dependency families only. Under D-011 each package needs an exact reviewed version, a manifest and a lockfile inside `frontend/`, and under the working agreement a major dependency needs a recorded decision.

Revision 3 reverses the first recommendation for D13, which was Tailwind CSS with shadcn/ui. The reason is the owner's review: the look is now approved screen by screen in the reference styles, so carrying those styles into the application is the shortest path and keeps what was approved. React Aria Components also ships its own right-to-left interactions and Arabic strings, and the dependency list is shorter (D-011). What this path costs: the few controls the reference styles do not cover yet, such as the calendar of the date range and the command palette, are styled by hand. Both paths are workable; see the tooling notes in the [research notes](../../research_notes/product-design/sources.md).

### 5.1 Decided in the owner's review of 2026-11-25 (D-082)
| Item | Decision |
|---|---|
| Logo (D6) | "Pure magnet": the capital C is a horseshoe magnet with two teal pole tips. Chosen from six options after research; see the [logo brief](../../docs/design/brand/logo-brief.md). |
| Sign-in screen | Approved as designed in [`sign-in.html`](../../docs/design/preview/screens/sign-in.html): a brand side with a magnet that pulls people in and turns them into sales, as a looping picture; the language switch in the top corner; "Forgot password?" under the password field in a quieter color; a box the user ticks to agree to the Terms of Service and the Privacy Policy. |
| Search | Search fields are pills, in the top bar and above lists. |

Two consequences of the sign-in decision need work before the screen is built:

- **Agreement to the terms (D15).** The API has no field or record for it, and the Terms of Service and the Privacy Policy do not exist. Recording who agreed, when and to which version is backend and schema work that needs its own decision. The design keeps both sign-in actions enabled and refuses a sign-in without the tick with a message at the box, because a disabled action does not say what is missing. A lighter alternative the owner may prefer later: ask once at registration and again only when the terms change.
- **A picture that loops.** A loop beside a form must be stoppable (WCAG 2.2, criterion 2.2.2). The design stops it under the system's reduced-motion setting and adds a pause control on the brand side.

### 5.2 Decided on 2026-11-26 (D-083)
The owner approved every remaining decision of the table as recommended: D1 to D5 and D7 to D15. Two of them leave work that keeps its own gate:

- **D13** approves the package families. The [018-A plan](plan-018a.md) names thirty packages with exact versions, and that list needs the owner's approval before anything is installed.
- **D15** approves the record of agreement in principle. Its schema belongs to an amendment of specification 002 with its own review, and the Terms of Service and the Privacy Policy come from the owner.

## 6. What this preparation does not decide
- Currencies and the exchange-rate source of Q-006 (they belong to 007).
- Subscription, trial and usage screens (017).
- Marketing website, onboarding emails and help content.
- Whether client viewers get a reduced navigation; the design assumes they see their one client without the Manage and Collect groups.

## 7. Risks and checks before implementation
| Risk | Check |
|---|---|
| The name is generic | Trademark and domain search (owner). Stripe Connect is an established product name in payments. |
| The sign-in screen asks for agreement that nothing records | Decide the acceptance record and supply the legal texts before 018-A builds the screen. |
| Provider brand rules | Re-read Google sign-in, YouTube API and Meta brand guidelines when the screens are built. |
| Arabic copy written by a model | Review by a native editor; a short usability check with Arabic-speaking users, including D3 and D4. |
| Only Chromium was used for rendering | Add Firefox and WebKit to the browser checks in 018-A. |
| No assistive-technology test | Keyboard and screen-reader walkthrough in 018-A. |
| Sample data in designs | Every reference page uses synthetic names and figures; none comes from a real account. |

## 8. Evidence
See "Verification performed" in the [design language](../../docs/design/README.md#verification-performed-on-2026-11-25): the token audit, the rendering review and the responsive check, with what was not verified.
