// Source of truth for the Connect design tokens (specification 018 design proposal).
//
// Colors are authored in OKLCH and compiled to sRGB hex by build-tokens.mjs.
// Three layers: primitive ramps, semantic roles (one value per theme), and the
// fixed chart palette. Components consume semantic roles only.
//
// Status: proposal for owner review. Values change only through this file.

import { oklchToHex } from './color-math.mjs';

const ramp = (hue, steps) =>
  Object.fromEntries(
    Object.entries(steps).map(([step, [L, C, h]]) => [step, oklchToHex(L, C, h ?? hue)]),
  );

// --- Primitive ramps -------------------------------------------------------
// Neutral: a cool gray biased toward the brand hue so that surfaces and ink read
// as one family with the teal. One ramp serves both themes.
const neutral = ramp(215, {
  0: [1, 0],
  25: [0.99, 0.002],
  50: [0.978, 0.004],
  100: [0.96, 0.006],
  150: [0.938, 0.007],
  200: [0.91, 0.009],
  300: [0.86, 0.011],
  350: [0.8, 0.012],
  400: [0.74, 0.014],
  450: [0.68, 0.015],
  500: [0.63, 0.016],
  600: [0.52, 0.017],
  700: [0.43, 0.017],
  750: [0.37, 0.016],
  800: [0.31, 0.015],
  850: [0.265, 0.014],
  900: [0.235, 0.013],
  925: [0.205, 0.012],
  950: [0.18, 0.012],
  975: [0.165, 0.011],
  1000: [0.14, 0.01],
});

// Brand teal. Tints lean slightly green, shades slightly blue, which keeps the
// light steps fresh and the dark steps deep.
const brand = ramp(192, {
  50: [0.975, 0.012, 190],
  100: [0.95, 0.028, 190],
  200: [0.905, 0.052, 190],
  300: [0.84, 0.082, 189],
  400: [0.76, 0.108, 188],
  500: [0.655, 0.11, 190],
  600: [0.525, 0.091, 193],
  700: [0.455, 0.079, 196],
  800: [0.385, 0.066, 199],
  900: [0.32, 0.054, 202],
  950: [0.255, 0.042, 205],
});

const success = ramp(152, {
  50: [0.975, 0.02],
  100: [0.95, 0.045],
  200: [0.9, 0.085],
  300: [0.83, 0.13],
  400: [0.74, 0.16],
  500: [0.64, 0.165],
  600: [0.54, 0.145],
  700: [0.46, 0.12],
  800: [0.39, 0.095],
  900: [0.32, 0.075],
  950: [0.25, 0.038],
});

const warning = ramp(75, {
  50: [0.98, 0.025, 90],
  100: [0.955, 0.055, 90],
  200: [0.915, 0.1, 88],
  300: [0.865, 0.14, 85],
  400: [0.81, 0.16, 80],
  500: [0.74, 0.16, 72],
  600: [0.62, 0.14, 62],
  700: [0.5, 0.115, 58],
  800: [0.42, 0.095, 55],
  900: [0.35, 0.075, 52],
  950: [0.26, 0.04, 55],
});

const danger = ramp(25, {
  50: [0.972, 0.014],
  100: [0.94, 0.033],
  200: [0.89, 0.065],
  300: [0.81, 0.115],
  400: [0.71, 0.17],
  500: [0.63, 0.205],
  600: [0.555, 0.205],
  700: [0.485, 0.18],
  800: [0.41, 0.145],
  900: [0.34, 0.11],
  950: [0.25, 0.045],
});

const info = ramp(258, {
  50: [0.972, 0.014],
  100: [0.94, 0.032],
  200: [0.89, 0.06],
  300: [0.81, 0.105],
  400: [0.71, 0.15],
  500: [0.62, 0.18],
  600: [0.54, 0.185],
  700: [0.47, 0.165],
  800: [0.4, 0.135],
  900: [0.33, 0.105],
  950: [0.25, 0.05],
});

export const primitives = { neutral, brand, success, warning, danger, info };

// --- Semantic roles --------------------------------------------------------
// Each entry: name -> { light, dark, usage }. A value "ramp-step" refers to a
// primitive; any other value is a literal CSS color.
const role = (light, dark, usage) => ({ light, dark, usage });

export const semantic = {
  // Surfaces
  'surface-canvas': role('neutral-50', 'neutral-975', 'Application background behind every card and panel.'),
  'surface-raised': role('neutral-0', 'neutral-925', 'Cards, tables, the sidebar and the top bar. Charts are drawn on this surface.'),
  'surface-sunken': role('neutral-100', 'neutral-1000', 'Wells inside a raised surface: table headers, code blocks, input groups.'),
  'surface-overlay': role('neutral-0', 'neutral-900', 'Menus, popovers, dialogs and drawers.'),
  'surface-hover': role('neutral-100', 'neutral-850', 'Hover wash on rows, menu items and ghost buttons.'),
  'surface-pressed': role('neutral-150', 'neutral-800', 'Pressed state of the same elements.'),
  'surface-selected': role('brand-50', 'brand-950', 'Selected navigation item, selected row, active segment.'),
  'surface-selected-hover': role('brand-100', 'brand-900', 'Hover on a selected element.'),
  'surface-disabled': role('neutral-100', 'neutral-900', 'Disabled controls.'),
  'surface-inverse': role('neutral-950', 'neutral-100', 'Tooltips and the inverse banner.'),
  'surface-scrim': role('rgba(12, 22, 26, 0.48)', 'rgba(0, 0, 0, 0.62)', 'Backdrop behind dialogs and drawers.'),

  // Text
  'text-primary': role('neutral-950', 'neutral-100', 'Headings, values and body copy on every surface.'),
  'text-secondary': role('neutral-700', 'neutral-350', 'Supporting copy, table cells of lower rank, field hints.'),
  'text-tertiary': role('neutral-600', 'neutral-450', 'Meta lines, axis labels, placeholders. Still 4.5:1 on canvas, raised and sunken.'),
  'text-disabled': role('neutral-400', 'neutral-700', 'Disabled labels only. Exempt from contrast rules.'),
  'text-inverse': role('neutral-0', 'neutral-975', 'Text on surface-inverse.'),
  'text-brand': role('brand-700', 'brand-300', 'Links and the label of the active navigation item.'),
  'text-on-primary': role('neutral-0', 'neutral-1000', 'Label on action-primary and on the brand tile.'),
  'text-on-danger': role('neutral-0', 'neutral-1000', 'Label on action-danger.'),

  // Borders
  'border-subtle': role('neutral-150', 'neutral-850', 'Dividers inside a card, table row rules.'),
  'border-default': role('neutral-200', 'neutral-800', 'Card and panel outlines.'),
  'border-strong': role('neutral-300', 'neutral-750', 'Emphasized dividers, the selected segment outline.'),
  'border-control': role('neutral-500', 'neutral-600', 'Inputs, selects, checkboxes and radios. At least 3:1 on canvas and raised.'),
  'border-focus': role('brand-600', 'brand-400', 'Focus ring: 2px solid with a 2px offset in the surface color.'),
  'border-brand': role('brand-300', 'brand-700', 'Outline of a selected card or tile.'),

  // Actions
  'action-primary': role('brand-600', 'brand-400', 'Primary button, checked controls, progress fill.'),
  'action-primary-hover': role('brand-700', 'brand-300', 'Hover on action-primary.'),
  'action-primary-active': role('brand-800', 'brand-200', 'Pressed action-primary.'),
  'action-danger': role('danger-600', 'danger-400', 'Destructive button: disconnect, revoke, delete.'),
  'action-danger-hover': role('danger-700', 'danger-300', 'Hover on action-danger.'),

  // Status: success
  'status-success-fg': role('success-700', 'success-300', 'Text and icons for a confirmed or healthy state.'),
  'status-success-bg': role('success-50', 'success-950', 'Tint behind a success badge or banner.'),
  'status-success-border': role('success-200', 'success-800', 'Outline of a success badge or banner.'),
  'status-success-solid': role('success-600', 'success-400', 'Solid success dot or fill.'),
  // Status: warning
  'status-warning-fg': role('warning-700', 'warning-300', 'Text and icons for partial, stale or attention states.'),
  'status-warning-bg': role('warning-50', 'warning-950', 'Tint behind a warning badge or banner.'),
  'status-warning-border': role('warning-300', 'warning-800', 'Outline of a warning badge or banner.'),
  'status-warning-solid': role('warning-400', 'warning-400', 'Solid warning dot or fill. Always paired with dark text.'),
  // Status: danger
  'status-danger-fg': role('danger-700', 'danger-300', 'Text and icons for failures and blocking problems.'),
  'status-danger-bg': role('danger-50', 'danger-950', 'Tint behind a danger badge or banner.'),
  'status-danger-border': role('danger-200', 'danger-800', 'Outline of a danger badge or banner.'),
  'status-danger-solid': role('danger-600', 'danger-400', 'Solid danger dot or fill.'),
  // Status: info
  'status-info-fg': role('info-700', 'info-300', 'Text and icons for provisional or informational states.'),
  'status-info-bg': role('info-50', 'info-950', 'Tint behind an info badge or banner.'),
  'status-info-border': role('info-200', 'info-800', 'Outline of an info badge or banner.'),
  'status-info-solid': role('info-600', 'info-400', 'Solid info dot or fill.'),
  // Status: neutral
  'status-neutral-fg': role('neutral-700', 'neutral-300', 'Text and icons for missing, unsupported or not-synced values.'),
  'status-neutral-bg': role('neutral-100', 'neutral-850', 'Tint behind a neutral badge.'),
  'status-neutral-border': role('neutral-300', 'neutral-750', 'Outline of a neutral badge.'),
  'status-neutral-solid': role('neutral-500', 'neutral-500', 'Solid neutral dot.'),
  'status-on-solid': role('neutral-0', 'neutral-1000', 'Label on the success, danger and info solids.'),
  'status-warning-on-solid': role('neutral-1000', 'neutral-1000', 'Label on the warning solid in both themes.'),
};

// --- Chart palette ---------------------------------------------------------
// Fixed categorical order. The order is the color-vision safety mechanism and
// never changes; a ninth series folds into "Other". Dark steps are selected
// for the dark surface, not inverted.
export const viz = {
  categorical: [
    { name: 'viz-1', hue: 'teal', light: oklchToHex(0.6, 0.105, 192), dark: oklchToHex(0.64, 0.112, 190) },
    { name: 'viz-2', hue: 'orange', light: '#eb6834', dark: '#d95926' },
    { name: 'viz-3', hue: 'violet', light: '#6250d6', dark: '#9085e9' },
    { name: 'viz-4', hue: 'yellow', light: '#eda100', dark: '#c98500' },
    { name: 'viz-5', hue: 'magenta', light: '#e87ba4', dark: '#d55181' },
    { name: 'viz-6', hue: 'green', light: '#008300', dark: '#0ca30c' },
    { name: 'viz-7', hue: 'blue', light: '#2a78d6', dark: '#3987e5' },
    { name: 'viz-8', hue: 'red', light: '#e34948', dark: '#e66767' },
  ],
  roles: {
    'viz-other': role('neutral-400', 'neutral-600', 'De-emphasized series and the "Other" bucket.'),
    'viz-grid': role('neutral-150', 'neutral-850', 'Chart gridlines: solid hairlines.'),
    'viz-axis': role('neutral-300', 'neutral-750', 'Chart baseline and axis rule.'),
    'viz-seq-1': role('brand-100', 'brand-900', 'Sequential ramp, lowest magnitude.'),
    'viz-seq-2': role('brand-200', 'brand-800', 'Sequential ramp.'),
    'viz-seq-3': role('brand-300', 'brand-700', 'Sequential ramp. First step allowed for ordinal marks.'),
    'viz-seq-4': role('brand-400', 'brand-600', 'Sequential ramp.'),
    'viz-seq-5': role('brand-500', 'brand-500', 'Sequential ramp.'),
    'viz-seq-6': role('brand-600', 'brand-400', 'Sequential ramp.'),
    'viz-seq-7': role('brand-800', 'brand-300', 'Sequential ramp, highest magnitude.'),
    'viz-div-neg': role('#d95926', '#eb6834', 'Diverging scale, below the baseline.'),
    'viz-div-mid': role('neutral-200', 'neutral-800', 'Diverging scale midpoint: reads as nothing.'),
    'viz-div-pos': role('brand-600', 'brand-400', 'Diverging scale, above the baseline.'),
  },
};

// --- Typography ------------------------------------------------------------
export const typography = {
  families: {
    sans: '"IBM Plex Sans", "IBM Plex Sans Arabic", system-ui, -apple-system, "Segoe UI", Tahoma, sans-serif',
    mono: '"IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace',
  },
  // Sizes in px. Arabic text adds --script-size-bump and --script-leading-bump.
  styles: [
    { name: 'type-metric-xl', group: 'Figures', size: 36, line: 44, weight: 600, usage: 'The one hero figure of a view.' },
    { name: 'type-metric-lg', group: 'Figures', size: 28, line: 36, weight: 600, usage: 'KPI tile value.' },
    { name: 'type-metric-md', group: 'Figures', size: 20, line: 28, weight: 600, usage: 'Compact tile value, drawer figures.' },
    { name: 'type-title-lg', group: 'Titles', size: 24, line: 32, weight: 600, usage: 'Page title.' },
    { name: 'type-title-md', group: 'Titles', size: 18, line: 26, weight: 600, usage: 'Section title, dialog title.' },
    { name: 'type-title-sm', group: 'Titles', size: 15, line: 22, weight: 600, usage: 'Card title.' },
    { name: 'type-body-lg', group: 'Text', size: 16, line: 24, weight: 400, usage: 'Lead paragraphs, sign-in copy, mobile body.' },
    { name: 'type-body', group: 'Text', size: 14, line: 22, weight: 400, usage: 'Default interface text.' },
    { name: 'type-body-sm', group: 'Text', size: 13, line: 20, weight: 400, usage: 'Table cells, secondary lines.' },
    { name: 'type-label', group: 'Text', size: 13, line: 18, weight: 500, usage: 'Buttons, form labels, tabs, navigation.' },
    { name: 'type-caption', group: 'Text', size: 12, line: 16, weight: 400, usage: 'Meta lines, axis labels, badges. The smallest size in the product.' },
    { name: 'type-code', group: 'Code', size: 13, line: 20, weight: 400, family: 'mono', usage: 'Keys, identifiers, slugs, URLs and webhook addresses.' },
  ],
  script: {
    arabicSizeBump: 1, // px added to every size under :lang(ar)
    arabicLeadingBump: 2, // px added to every line height under :lang(ar)
  },
};

// --- Scales ----------------------------------------------------------------
export const spacing = [
  ['space-0', 0, 'No gap.'],
  ['space-1', 2, 'Hairline offsets, icon nudges.'],
  ['space-2', 4, 'Icon to label, badge padding.'],
  ['space-3', 6, 'Tight stacks inside a control.'],
  ['space-4', 8, 'Control padding, related items.'],
  ['space-5', 12, 'Rows in a list, form field stacks.'],
  ['space-6', 16, 'Card padding (compact), grid gap.'],
  ['space-7', 20, 'Card padding (default).'],
  ['space-8', 24, 'Page gutter, section gap.'],
  ['space-9', 32, 'Between page sections.'],
  ['space-10', 40, 'Large section breaks.'],
  ['space-11', 48, 'Empty-state padding.'],
  ['space-12', 64, 'Page top spacing on marketing-like screens (sign-in).'],
];

export const radius = [
  ['radius-xs', 4, 'Checkboxes, inline tags, chart bar ends.'],
  ['radius-sm', 6, 'Buttons, inputs, selects, badges with text.'],
  ['radius-md', 8, 'Menus, tooltips, small cards, segmented controls.'],
  ['radius-lg', 12, 'Cards, panels, dialogs.'],
  ['radius-xl', 16, 'Sheets, the sign-in panel, the app icon inner grid.'],
  ['radius-full', 999, 'Pills, avatars, status dots, the switch.'],
];

export const shadow = [
  ['shadow-xs', { light: '0 1px 2px rgba(12, 22, 26, 0.06)', dark: '0 1px 2px rgba(0, 0, 0, 0.4)' }, 'Sticky headers and raised buttons.'],
  ['shadow-sm', { light: '0 2px 6px rgba(12, 22, 26, 0.08)', dark: '0 2px 6px rgba(0, 0, 0, 0.45)' }, 'Hovered interactive cards.'],
  ['shadow-md', { light: '0 8px 24px rgba(12, 22, 26, 0.12)', dark: '0 8px 24px rgba(0, 0, 0, 0.55)' }, 'Menus, popovers, tooltips.'],
  ['shadow-lg', { light: '0 20px 48px rgba(12, 22, 26, 0.18)', dark: '0 20px 48px rgba(0, 0, 0, 0.65)' }, 'Dialogs and drawers.'],
];

export const sizing = [
  ['control-sm', 32, 'Dense toolbars and table actions.'],
  ['control-md', 36, 'Default control height on desktop.'],
  ['control-lg', 44, 'Touch layouts and the sign-in form.'],
  ['icon-sm', 16, 'Inline icons.'],
  ['icon-md', 20, 'Navigation and button icons.'],
  ['icon-lg', 24, 'Empty states and page headers.'],
  ['sidebar-width', 248, 'Expanded navigation.'],
  ['sidebar-collapsed', 64, 'Collapsed navigation.'],
  ['topbar-height', 56, 'Application top bar.'],
  ['content-max', 1440, 'Maximum content width.'],
];

export const motion = [
  ['duration-fast', '120ms', 'Hover and press feedback.'],
  ['duration-base', '180ms', 'Menus, tooltips, tab changes.'],
  ['duration-slow', '240ms', 'Dialogs, drawers, page-level transitions.'],
  ['ease-standard', 'cubic-bezier(0.2, 0, 0, 1)', 'Entering and moving elements.'],
  ['ease-exit', 'cubic-bezier(0.4, 0, 1, 1)', 'Leaving elements.'],
];

export const zIndex = [
  ['z-sticky', 10, 'Sticky table headers.'],
  ['z-header', 20, 'Top bar and sidebar.'],
  ['z-drawer', 30, 'Side drawers.'],
  ['z-scrim', 40, 'Dialog backdrop.'],
  ['z-dialog', 50, 'Dialogs.'],
  ['z-popover', 60, 'Menus and popovers.'],
  ['z-toast', 70, 'Toasts.'],
  ['z-tooltip', 80, 'Tooltips.'],
];

export const breakpoints = [
  ['sm', 640, 'Large phones: two-column forms become possible.'],
  ['md', 768, 'Tablets: the bottom tab bar gives way to the collapsed sidebar.'],
  ['lg', 1024, 'Laptops: expanded sidebar, two-column dashboards.'],
  ['xl', 1280, 'Desktops: three and four-column KPI rows.'],
  ['2xl', 1536, 'Wide screens: content stops growing at content-max.'],
];
