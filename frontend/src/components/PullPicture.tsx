// The picture of the sign-in screen (docs/design/preview/screens/sign-in.html): a magnet pulls
// people toward it, and on the way they turn into sales. The motion, its pause control and the
// resting picture under reduced motion are all in the c-pull rules of the reference styles.

const tracks = ['top', 'mid', 'low'] as const;
const places = [1, 2, 3] as const;

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
        <circle r="16" fill="#104546" stroke="#379792" strokeWidth="1.5" />
        <g transform="translate(-9 -9) scale(0.75)" stroke="#b9ebe7" {...line}>
          <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </g>
      </g>
      <g className="c-pull__coin">
        <circle r="19" fill="#15a6a0" />
        <g transform="translate(-11 -11) scale(0.9167)" stroke="#02282c" {...line}>
          <Banknote />
        </g>
      </g>
    </g>
  );
}

export function PullPicture({ label }: { label: string }) {
  return (
    <svg className="l-auth__art c-pull" viewBox="0 20 440 200" role="img" aria-label={label}>
      <g
        className="c-pull__tracks"
        fill="none"
        stroke="#4ec7be"
        strokeOpacity="0.55"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray="0.1 9"
      >
        <path d="M430 44C330 44 250 96 160 112" />
        <path d="M430 120H156" />
        <path d="M430 196C330 196 250 144 160 128" />
      </g>
      {tracks.flatMap((track) =>
        places.map((place) => (
          <g key={`${track}-${place}`} className={`c-pull__mover c-pull__mover--${track} c-pull__mover--${place}`}>
            <Traveller />
          </g>
        )),
      )}
      <g transform="translate(10 48) scale(0.9)">
        <path d="M116 0H80A80 80 0 0 0 80 160H116V130H80A50 50 0 0 1 80 30H116Z" fill="#f5f8f9" />
        <path d="M116 0h30v30h-30ZM116 130h30v30h-30Z" fill="#4ec7be" />
        <g className="c-pull__held">
          <circle cx="116" cy="80" r="36" fill="#4ec7be" />
          <g transform="translate(98 62) scale(1.5)" stroke="#02282c" {...line}>
            <Banknote />
          </g>
        </g>
      </g>
    </svg>
  );
}
