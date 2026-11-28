// Color mathematics for the Connect design tokens. No dependencies.
//
// - OKLCH/OKLab conversions follow Bjorn Ottosson's published matrices.
// - Contrast is the WCAG 2.x relative-luminance ratio.
// - Color-vision-deficiency simulation uses the transforms of Machado, Oliveira
//   and Fernandes (2009) at severity 1.0, applied in linear RGB.

const toLinear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLinear = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
const clamp01 = (v) => Math.min(1, Math.max(0, v));

export function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}

export function rgbToHex(rgb) {
  return '#' + rgb.map((v) => Math.round(clamp01(v) * 255).toString(16).padStart(2, '0')).join('');
}

function oklabToLinear(L, a, b) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
}

function linearToOklab([r, g, b]) {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

const inGamut = (rgb) => rgb.every((v) => v >= -0.0005 && v <= 1.0005);

/** Convert OKLCH to an sRGB hex value. Chroma is reduced until the color fits sRGB. */
export function oklchToHex(L, C, h) {
  const at = (c) => oklabToLinear(L, c * Math.cos((h * Math.PI) / 180), c * Math.sin((h * Math.PI) / 180));
  if (inGamut(at(C))) return rgbToHex(at(C).map(fromLinear));
  let lo = 0;
  let hi = C;
  for (let i = 0; i < 28; i += 1) {
    const mid = (lo + hi) / 2;
    if (inGamut(at(mid))) lo = mid;
    else hi = mid;
  }
  return rgbToHex(at(lo).map(fromLinear));
}

/** Return [L, C, h] for an sRGB hex value. */
export function hexToOklch(hex) {
  const [L, a, b] = linearToOklab(hexToRgb(hex).map(toLinear));
  const h = ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
  return [L, Math.hypot(a, b), h];
}

export function relativeLuminance(hex) {
  const [r, g, b] = hexToRgb(hex).map(toLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2.x contrast ratio between two opaque colors. */
export function contrast(a, b) {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Composite a color with alpha over an opaque background; returns a hex value. */
export function over(fg, alpha, bg) {
  const f = hexToRgb(fg);
  const b = hexToRgb(bg);
  return rgbToHex(f.map((v, i) => v * alpha + b[i] * (1 - alpha)));
}

const MACHADO = {
  protan: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deutan: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
};

function simulate(hex, kind) {
  const [r, g, b] = hexToRgb(hex).map(toLinear);
  const M = MACHADO[kind];
  return M.map((row) => clamp01(row[0] * r + row[1] * g + row[2] * b));
}

/** Euclidean distance in OKLab, multiplied by 100. `kind` selects a simulated deficiency. */
export function deltaE(a, b, kind = null) {
  const p = linearToOklab(kind ? simulate(a, kind) : hexToRgb(a).map(toLinear));
  const q = linearToOklab(kind ? simulate(b, kind) : hexToRgb(b).map(toLinear));
  return 100 * Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
}
