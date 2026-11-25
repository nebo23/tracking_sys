# Connect design language

Status: the design of specification 018, prepared 2026-11-25 under D-074. D-075 approves the logo, the sign-in screen and the pill-shaped search field. D-076 (2026-11-26) approves the remaining decisions of the [018 entry review](../../specs/018-react-workspace/entry-review.md): the name, both languages, the colors, the typefaces, the themes, the data states, the navigation and the accessibility target. No React code, dependency or build tool is added by this folder; the application is planned in the [018-A plan](../../specs/018-react-workspace/plan-018a.md).

Connect is the product name in the interface (D-076). A trademark and domain search is still required before any public launch. The design covers the multi-agency product with both launch capabilities: content performance and financial tracking.

## What is in this folder
| Path | Content |
|---|---|
| [`brand/`](brand/README.md) | Logo, mark, Arabic lockup, application icon and favicon as SVG, with usage rules. |
| [`tokens/`](tokens/) | `tokens.source.mjs` is the source of truth. `build-tokens.mjs` compiles it into `tokens.css` (custom properties, light and dark) and `tokens.json` (Design Tokens Community Group format 2025.10) and audits the result. |
| [`ui/`](ui/) | `connect-ui.css`: framework-neutral reference styles for every component. `connect-icons.css`: interface icons and provider glyphs as CSS masks. [Third-party notices](ui/THIRD-PARTY-NOTICES.md). |
| [`preview/`](preview/index.html) | Static reference pages: the design system (`index.html`) and eleven screens (`screens.html`). Open them in a browser; they need no build step. |

Rebuild and audit the tokens with Node.js 20 or later:

```
node docs/design/tokens/build-tokens.mjs
node docs/design/tokens/build-tokens.mjs --check
```

## Principles
1. **Every figure names its source.** A value is shown with the account it came from, the day boundary it uses and how fresh it is. This is the product's signature and follows the report contract of specification 016-A.
2. **Nothing missing is drawn as zero.** Missing, unsupported, not-synced, stale, partial and provisional values each have one icon, one word and one sentence that says why.
3. **Calm surfaces, loud data.** Neutral surfaces, one teal for action and selection, and reserved state colors. Color is never the only carrier of meaning.
4. **Two directions, one design.** Layout mirrors for Arabic through logical properties. Numbers, handles, addresses and codes stay left to right.
5. **Summary before detail.** Key figures, then one chart, then the table. One date range above everything it scopes.

## Brand
The capital C of the name is a horseshoe magnet with two teal pole tips, and every other letter is regular: content pulls customers in, and Connect tracks the pull to the sale. The owner chose this logo from six options (D-075). See [brand/README.md](brand/README.md) and the [logo brief](brand/logo-brief.md). The teal of the tips is the one accent of the interface: it marks the active navigation item, the primary action and the first chart series.

## Color
Authored in OKLCH and compiled to sRGB. Three layers:

- **Primitive ramps**: `neutral` (a cool gray biased toward the brand hue), `brand` (teal, hue 190 to 205), and `success`, `warning`, `danger`, `info`.
- **Semantic roles**, one value per theme: surfaces (`surface-canvas`, `surface-raised`, `surface-sunken`, `surface-overlay`, `surface-selected`), text (`text-primary`, `text-secondary`, `text-tertiary`, `text-brand`), borders (`border-default`, `border-control`, `border-focus`), actions (`action-primary`, `action-danger`) and five status tones with `fg`, `bg`, `border` and `solid`.
- **Chart palette**: eight categorical slots in a fixed order (teal, orange, violet, yellow, magenta, green, blue, red), a sequential teal ramp and a diverging teal-to-orange pair. A ninth series folds into "Other".

Components use semantic roles only. Dark values are chosen for the dark surface, not inverted. The theme follows the system setting unless `data-theme="light"` or `data-theme="dark"` is set on any element.

### Audit results on 2026-11-25
`build-tokens.mjs` checks these on every run and fails on a miss:

- 130 foreground and background pairs across both themes. Text holds at least 4.5:1 on every surface it is used on; control borders, focus rings and action fills hold at least 3:1 (WCAG 2.2, criteria 1.4.3 and 1.4.11).
- Chart palette: every slot inside the lightness band with chroma of at least 0.10; worst adjacent pair 11.9 (light) and 9.9 (dark) under simulated protanopia and deuteranopia against a target of 8; worst adjacent pair 19.6 and 19.3 for normal vision against a floor of 15; the first three slots also separate pairwise. Distances are Euclidean in OKLab multiplied by 100, with the simulation of Machado, Oliveira and Fernandes (2009).
- `viz-4` (yellow) and `viz-5` (magenta) are below 3:1 on the light chart surface. A chart that uses them must show direct labels or offer its table view.

## Typography
IBM Plex Sans for Latin, IBM Plex Sans Arabic for Arabic and IBM Plex Mono for keys, identifiers, slugs and addresses. All three are open-licensed and drawn as one family, so a bilingual line keeps one texture.

| Style | Size / line | Weight | Use |
|---|---|---|---|
| `type-metric-xl` | 36 / 44 | 600 | The one hero figure of a view |
| `type-metric-lg` | 28 / 36 | 600 | Figure in a tile |
| `type-metric-md` | 20 / 28 | 600 | Compact figure |
| `type-title-lg` | 24 / 32 | 600 | Page title |
| `type-title-md` | 18 / 26 | 600 | Section and dialog title |
| `type-title-sm` | 15 / 22 | 600 | Card title |
| `type-body-lg` | 16 / 24 | 400 | Sign-in copy, phone body |
| `type-body` | 14 / 22 | 400 | Default text |
| `type-body-sm` | 13 / 20 | 400 | Table cells |
| `type-label` | 13 / 18 | 500 | Buttons, labels, tabs |
| `type-caption` | 12 / 16 | 400 | Meta lines and axis labels; the smallest size |
| `type-code` | 13 / 20 | 400 | Mono |

Rules: sentence case everywhere; no all-capital labels; no letter spacing (it breaks connected Arabic script); Arabic text is set one pixel larger with two pixels more leading through `:lang(ar)`; tabular figures only where numbers align in a column.

## Layout
- Spacing follows a 4-pixel base (`space-1` to `space-12`). Radius is assigned by role: 6 for controls, 8 for menus, 12 for cards, full for pills.
- Shell: a 248-pixel sidebar, a 56-pixel top bar and a content column of at most 1440 pixels with 24-pixel gutters. Below 768 pixels the sidebar is replaced by a bottom tab bar of five items.
- Two levels of navigation: the agency (clients, team and access, keys, audit log, privacy) and one client workspace (overview, analyze, collect, manage). The switcher at the top of the sidebar always shows which client is open.
- Controls are 36 pixels high on desktop and 44 in touch layouts. Every pointer target is at least 24 by 24 pixels (WCAG 2.2, criterion 2.5.8).

## Data states
The mapping below is fixed across the product. It mirrors the availability, total status, freshness and provisional fields of the 016-A reports.

| State | Shown as | Tone | Comparison |
|---|---|---|---|
| Available, complete, fresh | The value, with its source line | None | Shown |
| Provisional | Value and "Provisional" (hourglass) | Info | Hidden, with the reason |
| Partial | Labeled subtotal and "Partial" (half dot) | Warning | Hidden, with the reason |
| Stale | Value and "Stale" (clock), last sync time | Warning | Hidden, with the reason |
| Missing | Dash and "Missing" (dashed circle), provider reason | Neutral | None |
| Unsupported | Dash and "Unsupported" (slashed circle) | Neutral | None |
| Not synced | Dash and "Not synced" (cloud off) | Neutral | None |
| No total (non-additive) | "No total" and one sentence, link to daily values | Neutral | None |
| Failed or reconnect needed | Banner and badge (alert circle), one action | Danger | None |

Further rules:

- A comparison is shown only when the report marks it comparable. Otherwise the tile states the first reason; it never shows an empty or zero change.
- Default date ranges end on the last final day, so comparisons are available by default. "Up to today" is a deliberate choice and marks its provisional days.
- Verified revenue, declared revenue and unresolved items are separate blocks and are never added together. Currencies are never added together.
- Each source keeps its own day boundary (Instagram UTC, YouTube Pacific, advertising spend in the account's zone, revenue UTC), and the source line says which.

## Charts
- Form before color: a line for a trend, thin bars for magnitude, a tile for a single figure. No dual axes, pies or gauges.
- Marks: lines 2 pixels, area wash at 10 percent, bars at most 24 pixels wide with a 4-pixel rounded data end, solid hairline gridlines.
- A legend is present for two or more series; text never takes the series color. The latest point carries a dot.
- Every chart has a table view and a text alternative. The hover layer adds a crosshair and one tooltip for all series; nothing is readable by hover only.
- Provisional days are shaded and labeled inside the plot.
- In Arabic, time still runs from left to right and the surrounding card mirrors. Published guidance on this point disagrees, so it is an owner decision (D4 in the entry review).

## Right-to-left and bilingual text
- Use logical properties (`margin-inline`, `padding-inline`, `inset-inline`, `text-align: start`) and no physical left or right in components.
- Wrap numbers in `u-num` and handles, addresses and codes in `u-ltr`; both isolate direction.
- Icons that show travel (back, next, chevrons in breadcrumbs) mirror with `c-icon--mirror`. Logos, check marks, clocks, trend arrows and provider glyphs never mirror.
- Western digits and the Gregorian calendar in both languages. Currency follows the language: `EGP 128,450.75` in English and `128,450.75 ج.م` in Arabic.
- One-time codes are always typed left to right.

## Accessibility
Target: WCAG 2.2 level AA.

- Visible focus on every interactive element: a 2-pixel `border-focus` ring with a 2-pixel offset.
- State is carried by an icon and a word, never by color alone.
- Motion is limited to 120 to 240 milliseconds and stops under `prefers-reduced-motion`. The one exception is the picture on the sign-in screen, which loops: it rests as a still picture under reduced motion and has a pause control beside it (WCAG 2.2, criterion 2.2.2).
- The reference pages use real buttons, links, inputs and labels, table headers with scope, and labels on icon-only buttons.

## Components
The reference styles cover: buttons, form fields, select, checkbox, radio, switch, one-time code, search field, tabs, segmented control, filter chips, badges, status dots, source chips, avatars, cards, figure tiles, change indicators, definition lists, meters, segmented bars, coverage bars, tables, chart frame and legend, tooltip, banners, empty state, skeleton, toast, dialog, drawer, menu, timeline, sidebar navigation, client switcher, top bar, bottom tab bar and the sign-in layout. Class names use `l-` for layout, `c-` for components, `u-` for utilities and `is-` for states.

Search is always a pill (`c-search`), in the top bar and above a list, so it is never mistaken for a button or for a field of a form. In the top bar it is a button that opens the command palette; above a list it holds an input.

## Screens
See [`preview/screens.html`](preview/screens.html). Sign in, Clients, Overview (light, dark, Arabic, phone), Content, Revenue, Connections, Links, Team and access, and an Attribution concept. Each screen lists the specification that backs it. The Attribution screen is a concept only: its reports wait for specifications 006, persisted 008 and 016-B.

The sign-in screen, as the owner approved it (D-075):

- The brand side shows a magnet that pulls people in; on the way they turn into sales. The picture is built from the `c-pull` classes and moves in a loop of 7.2 seconds.
- The language switch sits in the top corner at the end of the reading direction.
- "Forgot password?" sits under the password field, in the secondary text color, so it does not compete with the links and the action below it.
- A box that starts unticked asks the user to agree to the Terms of Service and the Privacy Policy. Both sign-in actions stay enabled; a sign-in without the tick is refused with a message at the box. The API records no acceptance of terms today and the two texts do not exist yet, so this needs backend work and the owner's legal texts before it is built.

## Verification performed on 2026-11-25
| Check | Result |
|---|---|
| Token audit (`build-tokens.mjs`) | Passed: 130 contrast pairs and the chart palette gates, both themes. |
| Rendering | All thirteen reference pages rendered in Chromium (Playwright 1.64.1) and reviewed as screenshots in light, dark, Arabic and at phone width. |
| Responsive check | Thirteen pages at 390, 768, 1024 and 1440 pixels (dark at 390 and 1440): no horizontal overflow, no console errors, no pointer target under 24 pixels. |
| Revision for D-075 | The token audit and the responsive check were run again and passed. Reviewed as screenshots: the sign-in screen in light, in dark and at phone width; its picture frozen at three moments of the loop and under reduced motion; the top bar with the pill search in light, dark, Arabic and at phone width; and the fourteen logo files. The other pages were not reviewed again by eye. |

Not verified: screen readers, keyboard-only walkthroughs, Firefox and Safari, real phones, usability with Arabic-speaking users, review of the Arabic copy by a native editor, provider brand-guideline compliance, and name or trademark clearance.

## Sources
Research evidence, measurements and links are in [research_notes/product-design/sources.md](../../research_notes/product-design/sources.md).
