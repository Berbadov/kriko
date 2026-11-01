/**
 * The three palettes a phone can carry, chosen at runtime.
 *
 * Dark is the app's identity. Paper is the desktop's warm light theme. White is
 * a pure, cool light for readers who want maximum contrast and no cream cast.
 *
 * Both light palettes hold exactly the same keys as dark; that is what keeps
 * `keyof typeof darkColors` a single, exact vocabulary. Everything visual reads
 * one of these through `theme.tsx`, never through a module constant.
 */

export const darkColors = {
  /** Page background. */
  ground: '#07090E',
  /** Cards, sheets and the composer. */
  surface: '#0E1118',
  /** Inset tiles and recessed rows. */
  inset: '#0A0D13',
  /** A slightly lifted surface for rows inside a card. */
  raise: '#161A24',

  edge: 'rgba(255, 255, 255, 0.08)',
  edgeSoft: 'rgba(255, 255, 255, 0.05)',
  edgeStrong: 'rgba(255, 255, 255, 0.16)',

  /** Brand blue: the app mark and the one primary action. */
  accent: '#4672FF',
  accentDeep: '#3459E6',
  accentDim: '#17224A',
  accentSoft: 'rgba(96, 134, 255, 0.17)',
  accentWash: 'rgba(96, 134, 255, 0.09)',
  accentHi: '#A3B8FF',
  /** Text and icons drawn on top of `accent`. */
  onAccent: '#FFFFFF',

  ink: '#F3F5FA',
  ink2: '#B6BCCD',
  ink3: '#8F96AA',
  ink4: '#7C8398',

  /** Light blue used by the progress fill and inline citations. */
  fill: '#A3B8FF',

  ok: '#43E0A0',
  warn: '#F6BC52',
  risk: '#FF7080',
  riskWash: 'rgba(255, 112, 128, 0.14)',

  glass: 'rgba(14, 17, 24, 0.92)',
  scrim: 'rgba(2, 4, 8, 0.74)',
  shadow: '#000000',
  /** Halo behind the primary action and the scan ring. */
  glow: 'rgba(70, 114, 255, 0.45)',
  /** Quiet tints for a verdict that is fine, or needs care. */
  okWash: 'rgba(67, 224, 160, 0.12)',
  warnWash: 'rgba(246, 188, 82, 0.13)',
} as const;

export const paperColors = {
  /** Page background: the desktop's light canvas. */
  ground: '#F4F0E6',
  /** Cards, sheets and the composer. */
  surface: '#FFFDF7',
  /** Inset tiles and recessed rows. */
  inset: '#ECE7DB',
  /** A slightly lifted surface for rows inside a card. */
  raise: '#FAF7EF',

  edge: '#E0DACE',
  edgeSoft: '#ECE6DA',
  edgeStrong: '#C5BDAD',

  /** Brand blue on paper; `accentDim` is the pale fill behind it. */
  accent: '#2E5BEF',
  accentDeep: '#2449CA',
  accentDim: '#CAD5F7',
  accentSoft: '#E4EAFB',
  accentWash: 'rgba(46, 91, 239, 0.06)',
  accentHi: '#2E5BEF',
  onAccent: '#FFFFFF',

  ink: '#24231F',
  ink2: '#5D5A52',
  ink3: '#78756D',
  ink4: '#918B7F',

  /** Blue used by the progress fill and inline citations. */
  fill: '#2E5BEF',

  ok: '#39735B',
  warn: '#A36A20',
  risk: '#B74739',
  riskWash: '#F6E7DF',

  glass: 'rgba(244, 240, 230, 0.94)',
  scrim: 'rgba(36, 35, 31, 0.38)',
  shadow: '#3A3428',
  /** Halo behind the primary action and the scan ring. */
  glow: 'rgba(46, 91, 239, 0.28)',
  /** Quiet tints for a verdict that is fine, or needs care. */
  okWash: '#E3EEE6',
  warnWash: '#F4E8D2',
} as const satisfies Record<keyof typeof darkColors, string>;

/** Pure white, for a brighter light theme with no warm cast. */
export const whiteColors = {
  ground: '#F3F5F9',
  surface: '#FFFFFF',
  inset: '#E9EDF4',
  raise: '#FFFFFF',

  edge: '#E2E6EE',
  edgeSoft: '#ECEFF5',
  edgeStrong: '#C9CFDA',

  accent: '#2F5DF2',
  accentDeep: '#2349CF',
  accentDim: '#D4DEFC',
  accentSoft: '#E8EEFE',
  accentWash: 'rgba(46, 91, 239, 0.05)',
  accentHi: '#2E5BEF',
  onAccent: '#FFFFFF',

  ink: '#10131A',
  ink2: '#474D5A',
  ink3: '#697082',
  ink4: '#868D9D',

  fill: '#2F5DF2',

  ok: '#1F7A54',
  warn: '#98600F',
  risk: '#B42318',
  riskWash: '#FDECEA',

  glass: 'rgba(255, 255, 255, 0.96)',
  scrim: 'rgba(17, 19, 24, 0.32)',
  shadow: '#1B2438',
  /** Halo behind the primary action and the scan ring. */
  glow: 'rgba(47, 93, 242, 0.30)',
  /** Quiet tints for a verdict that is fine, or needs care. */
  okWash: '#E4F4EC',
  warnWash: '#FBF0DA',
} as const satisfies Record<keyof typeof darkColors, string>;

export type Colors = { [K in keyof typeof darkColors]: string };

export const PALETTE_NAMES = ['dark', 'paper', 'white'] as const;
export type PaletteName = (typeof PALETTE_NAMES)[number];

export const palettes: Record<PaletteName, Colors> = {
  dark: darkColors,
  paper: paperColors,
  white: whiteColors,
};
