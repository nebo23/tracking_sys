# Connect brand assets

Status: design proposal for specification 018, prepared 2026-11-25. The name, the mark and the colors are not approved until the owner records the decisions listed in the [018 entry review](../../../specs/018-react-workspace/entry-review.md).

## The idea
The mark is the letter C drawn as an open ring, and the dot that closes it. Marketing teams call measured attribution "closing the loop": the ring is the path from a piece of content to a sale, and the dot is the moment the two are connected. The same dot marks the current place in the navigation and the latest point of a trend line.

## Files
All files are SVG with outlined paths. They use no fonts, strokes, gradients or effects.

| File | Use |
|---|---|
| `connect-logo.svg` | Primary logo on white and light surfaces. |
| `connect-logo-reversed.svg` | On dark surfaces. |
| `connect-logo-ar.svg`, `connect-logo-ar-reversed.svg` | Arabic lockup: the mark with the name set in Arabic. |
| `connect-mark.svg`, `connect-mark-reversed.svg` | The mark alone, where space is tight or the name is already present. |
| `*-mono-black.svg`, `*-mono-white.svg` | One ink, for single-color printing, embossing and placement on the brand color. |
| `connect-app-icon.svg` | Application icon: the mark on a rounded teal tile. |
| `favicon.svg` | Browser tab icon. |

## Construction
- Mark: outer diameter 160 units; ring thickness 32 (one fifth of the diameter); aperture 68 degrees, centered on three o'clock; dot diameter 36, centered on the ring's centerline. The dot overhangs the ring by 2 units, so the artboard is 168 units square.
- Latin wordmark: the mark stands for the capital C at cap height. The letters "onnect" are drawn from circles and straight stems of one thickness (19 units on an x-height of 100), with flat terminals.
- Arabic lockup: the name is set in Alexandria SemiBold and converted to outlines. The mark sits on the right, because Arabic is read from the right.

## Colors
| Role | Value | Token |
|---|---|---|
| Ink (ring and letters) | `#02282c` | `brand-950` |
| Dot | `#15a6a0` | `brand-500` |
| Reversed ink | `#f5f8f9` | `neutral-50` |
| Reversed dot | `#4ec7be` | `brand-400` |
| Icon tile | `#007a79` with a white ring and a `#b9ebe7` dot | `brand-600`, `brand-200` |

## Rules
- Keep clear space of one ring thickness (one fifth of the mark's height) on every side.
- Smallest sizes: mark 16 pixels; Latin logo 20 pixels high; Arabic lockup 24 pixels high.
- Use the color versions on white, `neutral-50`, `brand-50` and the dark surfaces. On any other color or on a photograph, use a one-ink version.
- Never mirror the logo in a right-to-left layout. Never rotate it, recolor it, outline it, add a shadow, or set the name in another typeface beside the mark.
- The dot is never used alone as the logo.

## Open points
- "Connect" is a common word and many products use it. No trademark or domain search has been made. Run one before any public launch.
- The Arabic form "كونكت" is a transliteration. Whether the Arabic interface shows the Arabic lockup or keeps the Latin logo is an owner decision.

## Licenses
The Latin wordmark and the mark are original drawings made for this project. The Arabic wordmark uses outlines of Alexandria (Mohamed Gaber and Julieta Ulanovsky), licensed under the SIL Open Font License 1.1, which permits use of the outlines in artwork.
