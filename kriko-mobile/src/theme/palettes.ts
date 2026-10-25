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
  ground: '#000000',
  /** Cards, sheets and the composer. */
  surface: '#111111',
  /** Inset tiles and recessed rows. */
  inset: '#090909',
  /** A slightly lifted surface for rows inside a card. */
  raise: '#1A1A1A',

  edge: 'rgba(255, 255, 255, 0.07)',
  edgeSoft: 'rgba(255, 255, 255, 0.05)',
  edgeStrong: 'rgba(255, 255, 255, 0.15)',

  /** Brand blue: the app mark and the one primary action. */
  accent: '#3562E9',
  accentDeep: '#2852D6',
  accentDim: '#192548',
  accentSoft: 'rgba(88, 124, 255, 0.16)',
  accentWash: 'rgba(88, 124, 255, 0.10)',
  accentHi: '#99B1FF',
  /** Text and icons drawn on top of `accent`. */
  onAccent: '#FFFFFF',

  ink: '#F5F5F5',
  ink2: '#B8B8B8',
  ink3: '#989898',
  ink4: '#888888',

  /** Light blue used by the progress fill and inline citations. */
  fill: '#99B1FF',

  ok: '#3DDC97',
  warn: '#F5B84B',
  risk: '#FF6B7A',
  riskWash: 'rgba(255, 107, 122, 0.14)',

  glass: 'rgba(17, 17, 17, 0.94)',
  scrim: 'rgba(0, 0, 0, 0.78)',
  shadow: '#000000',
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

  edge: '#DED8CC',
  edgeSoft: '#EAE4D8',
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
} as const satisfies Record<keyof typeof darkColors, string>;

/** Pure white, for a brighter light theme with no warm cast. */
export const whiteColors = {
  ground: '#F7F8FA',
  surface: '#FFFFFF',
  inset: '#EEF1F5',
  raise: '#FFFFFF',

  edge: '#E1E5EA',
  edgeSoft: '#EDF0F3',
  edgeStrong: '#C8CDD4',

  accent: '#2E5BEF',
  accentDeep: '#2449CA',
  accentDim: '#D5DFFB',
  accentSoft: '#EAF0FE',
  accentWash: 'rgba(46, 91, 239, 0.05)',
  accentHi: '#2E5BEF',
  onAccent: '#FFFFFF',

  ink: '#111318',
  ink2: '#4A4F57',
  ink3: '#6B7280',
  ink4: '#8A9099',

  fill: '#2E5BEF',

  ok: '#1F7A54',
  warn: '#98600F',
  risk: '#B42318',
  riskWash: '#FDECEA',

  glass: 'rgba(255, 255, 255, 0.96)',
  scrim: 'rgba(17, 19, 24, 0.32)',
  shadow: '#20242B',
} as const satisfies Record<keyof typeof darkColors, string>;

export type Colors = { [K in keyof typeof darkColors]: string };

export const PALETTE_NAMES = ['dark', 'paper', 'white'] as const;
export type PaletteName = (typeof PALETTE_NAMES)[number];

export const palettes: Record<PaletteName, Colors> = {
  dark: darkColors,
  paper: paperColors,
  white: whiteColors,
};
