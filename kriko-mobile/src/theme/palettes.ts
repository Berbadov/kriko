/**
 * The two palettes a build can carry.
 *
 * `tokens.ts` picks one at build time from `EXPO_PUBLIC_KRIKO_THEME`, so a
 * second APK can be built for the light theme without a runtime toggle and
 * without touching a component. Both objects hold exactly the same keys, which
 * is what keeps `keyof typeof color` a single, exact vocabulary.
 *
 * Dark is the phone's own theme. Light is the desktop app's light theme
 * (`kriko-ui/src/styles/tokens.css`), so the two products still agree.
 */

export const darkColors = {
  /** Page background. */
  ground: '#090B11',
  /** Cards, sheets and the composer. */
  surface: '#141825',
  /** Inset tiles and recessed rows. */
  inset: '#0F121A',
  /** A slightly lifted surface for rows inside a card. */
  raise: '#1A1F2F',

  edge: 'rgba(255, 255, 255, 0.07)',
  edgeSoft: 'rgba(255, 255, 255, 0.05)',
  edgeStrong: 'rgba(255, 255, 255, 0.15)',

  /** Brand blue: the app mark and the one primary action. */
  accent: '#3D6BFF',
  accentDeep: '#2F5BFF',
  accentDim: '#1C2B5E',
  accentSoft: 'rgba(61, 107, 255, 0.16)',
  accentWash: 'rgba(61, 107, 255, 0.10)',
  accentHi: '#7B98FF',

  ink: '#EEF1F9',
  ink2: '#A8B0C4',
  ink3: '#6C7489',
  ink4: '#50586C',

  /** Light blue used by the progress fill and inline citations. */
  fill: '#7B98FF',

  ok: '#3DDC97',
  warn: '#F5B84B',
  risk: '#FF6B7A',
  riskWash: 'rgba(255, 107, 122, 0.14)',

  glass: 'rgba(22, 27, 42, 0.58)',
  scrim: 'rgba(4, 6, 12, 0.66)',
} as const;

export const lightColors = {
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

  /** Brand blue on white; `accentDim` is the pale fill behind it. */
  accent: '#2E5BEF',
  accentDeep: '#2449CA',
  accentDim: '#CAD5F7',
  accentSoft: '#E4EAFB',
  accentWash: 'rgba(46, 91, 239, 0.06)',
  accentHi: '#2E5BEF',

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
  // A compile error here means the two palettes drifted apart: same keys or
  // `keyof typeof color` stops being the whole vocabulary.
} as const satisfies Record<keyof typeof darkColors, string>;
