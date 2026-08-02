/**
 * Icons as SVG, not text glyphs.
 *
 * The plus in the action button was a `+` character nudged with a negative margin, because a
 * glyph sits on a text baseline rather than in the middle of its box — it can only ever be
 * approximately centred, and the approximation changes with the font. An SVG on a square
 * viewBox is centred by construction, at every size.
 *
 * `currentColor` throughout, so an icon inherits the colour of whatever it sits in.
 */

type IconProps = {
  name: keyof typeof PATHS;
  className?: string;
  /** Mirrors in RTL. Only for icons that encode reading direction — never a plus or a gear. */
  directional?: boolean;
};

const PATHS = {
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  check: <path d="m4 12 5 5L20 6" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  chevronUp: <path d="m6 15 6-6 6 6" />,
  chevronStart: <path d="m14 6-6 6 6 6" />,
  chevronEnd: <path d="m10 6 6 6-6 6" />,
  wallet: (
    <>
      <path d="M3 8a2 2 0 0 1 2-2h13a1 1 0 0 1 1 1v2" />
      <path d="M3 8v9a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2H5" />
      <circle cx="16.5" cy="13.5" r="1" />
    </>
  ),
  list: <path d="M4 7h16M4 12h16M4 17h10" />,
  swap: <path d="M7 8h13l-3-3M17 16H4l3 3" />,
  repeat: (
    <>
      <path d="M4 12a8 8 0 0 1 13.7-5.6L20 8" />
      <path d="M20 4v4h-4" />
      <path d="M20 12a8 8 0 0 1-13.7 5.6L4 16" />
      <path d="M4 20v-4h4" />
    </>
  ),
  sliders: (
    <>
      <path d="M4 8h10M18 8h2M4 16h4M12 16h8" />
      <circle cx="16" cy="8" r="2" />
      <circle cx="10" cy="16" r="2" />
    </>
  ),
  gear: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v2M12 19v2M4.2 7.5l1.7 1M18.1 15.5l1.7 1M4.2 16.5l1.7-1M18.1 8.5l1.7-1" />
    </>
  ),
  undo: (
    <>
      <path d="M4 9h11a5 5 0 0 1 0 10h-5" />
      <path d="M8 5 4 9l4 4" />
    </>
  ),
  redo: (
    <>
      <path d="M20 9H9a5 5 0 0 0 0 10h5" />
      <path d="m16 5 4 4-4 4" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 2" />
    </>
  ),
  external: (
    <>
      <path d="M14 4h6v6" />
      <path d="M20 4 11 13" />
      <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
    </>
  ),
  drag: (
    <>
      <circle cx="9" cy="6" r="1.2" />
      <circle cx="15" cy="6" r="1.2" />
      <circle cx="9" cy="12" r="1.2" />
      <circle cx="15" cy="12" r="1.2" />
      <circle cx="9" cy="18" r="1.2" />
      <circle cx="15" cy="18" r="1.2" />
    </>
  ),
  sparkle: (
    <>
      <path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z" />
      <path d="M18 16l.7 1.9L20.6 18l-1.9.7L18 20.6l-.7-1.9L15.4 18l1.9-.7z" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
} as const;

export function Icon({ name, className = "size-5", directional }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={`${className} ${directional ? "icon-directional" : ""} shrink-0`}
    >
      {PATHS[name]}
    </svg>
  );
}

export type IconName = keyof typeof PATHS;
