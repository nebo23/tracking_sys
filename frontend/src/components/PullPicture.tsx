// The picture of the sign-in screen (docs/design/preview/screens/sign-in.html): a magnet, its field
// drawn as lines of iron filings, and people pulled in who turn into sales on the way. The motion,
// its pause control and the resting picture under reduced motion are all in the c-pull rules of the
// reference styles; the geometry here and there is the same.

const tracks = ['top', 'mid', 'low'] as const;
const places = [1, 2, 3] as const;

/** The field: lines that leave the magnet's outer edges, then loops from one pole to the other, fainter as they grow. */
const field: ReadonlyArray<readonly [string, number]> = [
  ['M200.2 101C228.2 41 398.2 9 650 31', 0.3],
  ['M188.2 101C198.2 21 338.2 -29 520 -20', 0.16],
  ['M200.2 336.2C228.2 396.2 398.2 428.2 650 406.2', 0.3],
  ['M188.2 336.2C198.2 416.2 338.2 466.2 520 460', 0.16],
  ['M218.2 124.8C258.2 120.8 258.2 319.2 218.2 315.2', 0.9],
  ['M218.2 124.8C304.2 106.8 304.2 333.2 218.2 315.2', 0.72],
  ['M218.2 124.8C360.2 88.8 360.2 351.2 218.2 315.2', 0.56],
  ['M218.2 124.8C426.2 66.8 426.2 373.2 218.2 315.2', 0.43],
  ['M218.2 124.8C502.2 42.8 502.2 397.2 218.2 315.2', 0.33],
  ['M218.2 124.8C588.2 18.8 588.2 421.2 218.2 315.2', 0.25],
  ['M218.2 124.8C684.2 -3.2 684.2 443.2 218.2 315.2', 0.18],
  ['M218.2 124.8C790.2 -25.2 790.2 465.2 218.2 315.2', 0.12],
];

const line = {
  fill: 'none',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const;

function Banknote() {
  return (
    <>
      <rect width="20" height="12" x="2" y="6" rx="2" />
      <circle cx="12" cy="12" r="2" />
      <path d="M6 12h.01M18 12h.01" />
    </>
  );
}

function Traveller() {
  return (
    <g className="c-pull__body">
      <g className="c-pull__person">
        <circle r="15" fill="#013b3f" stroke="#15a6a0" strokeWidth="1.5" />
        <g transform="translate(-8.4 -8.4) scale(0.7)" stroke="#b9ebe7" {...line}>
          <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </g>
      </g>
      <g className="c-pull__coin">
        <circle r="16" fill="#fdcb5b" stroke="#e79700" strokeWidth="2" />
        <g transform="translate(-9 -9) scale(0.75)" stroke="#743d0e" {...line}>
          <Banknote />
        </g>
      </g>
    </g>
  );
}

export function PullPicture({ label }: { label: string }) {
  return (
    <svg className="l-auth__art c-pull" viewBox="0 0 640 440" role="img" aria-label={label}>
      <defs>
        <linearGradient id="c-pull-steel" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.55" stopColor="#e6eced" />
          <stop offset="1" stopColor="#b6c0c2" />
        </linearGradient>
        <radialGradient id="c-pull-warm">
          <stop offset="0" stopColor="#fdcb5b" stopOpacity="0.42" />
          <stop offset="1" stopColor="#fdcb5b" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="c-pull-cool">
          <stop offset="0" stopColor="#15a6a0" stopOpacity="0.5" />
          <stop offset="1" stopColor="#15a6a0" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="c-pull-fade">
          <stop offset="0.6" stopColor="#ffffff" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
        <mask id="c-pull-edge">
          <rect width="640" height="440" fill="url(#c-pull-fade)" />
        </mask>
      </defs>
      <circle cx="170.6" cy="220" r="230" fill="url(#c-pull-cool)" opacity="0.55" />
      <g
        className="c-pull__field"
        mask="url(#c-pull-edge)"
        fill="none"
        stroke="#4ec7be"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeDasharray="0.01 8"
      >
        {field.map(([d, opacity]) => (
          <path key={d} d={d} strokeOpacity={opacity} />
        ))}
      </g>
      <circle cx="208.2" cy="124.8" r="36" fill="url(#c-pull-cool)" />
      <circle cx="208.2" cy="315.2" r="36" fill="url(#c-pull-cool)" />
      {tracks.flatMap((track) =>
        places.map((place) => (
          <g key={`${track}-${place}`} className={`c-pull__mover c-pull__mover--${track} c-pull__mover--${place}`}>
            <Traveller />
          </g>
        )),
      )}
      <circle cx="170.6" cy="220" r="96" fill="url(#c-pull-warm)" />
      <g transform="translate(4 101) scale(1.7)">
        <path d="M96 0H70A70 70 0 0 0 70 140H96V112H70A42 42 0 0 1 70 28H96Z" fill="url(#c-pull-steel)" />
        <path d="M96 0h30v28h-30ZM96 112h30v28h-30Z" fill="#4ec7be" />
      </g>
      <g className="c-pull__held" transform="translate(170.6 220)">
        <circle r="31" fill="#fdcb5b" stroke="#e79700" strokeWidth="3" />
        <circle r="24" fill="none" stroke="#f6b324" strokeWidth="1.5" />
        <g transform="translate(-18 -18) scale(1.5)" stroke="#743d0e" {...line}>
          <Banknote />
        </g>
      </g>
    </svg>
  );
}
