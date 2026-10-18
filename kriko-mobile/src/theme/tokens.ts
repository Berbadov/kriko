/**
 * Every colour, radius, gap and type size in the app comes from here.
 *
 * The values are not guesses: `tools/measure_ui.py` reads the design captures
 * and solves each text run against the real font files, and
 * `tools/trace_logo.py` / `tools/generate_assets.py` produce the art. The
 * comments name the measurement a token came from.
 */

export const color = {
  /** Page background, measured #03060F in the captures. */
  ground: '#03060F',
  /** Cards and the composer. */
  surface: '#0A1226',
  /** Inset tiles: icon chips, claim bodies. */
  inset: '#050A18',
  /** A slightly lifted surface for rows inside a card. */
  raise: '#0D1730',

  edge: '#192445',
  edgeSoft: '#101A33',
  edgeStrong: '#26355C',

  /** Brand blue: the app bar and every primary action. */
  accent: '#2862FF',
  accentDeep: '#1A48D8',
  accentDim: '#142F7B',
  accentSoft: '#0F214D',
  accentWash: 'rgba(40, 98, 255, 0.14)',

  ink: '#F4F7FF',
  ink2: '#C6D0E8',
  ink3: '#8C9AB8',
  ink4: '#6C7A9C',

  /** Light blue used by the progress fill. */
  fill: '#C9D8FF',

  ok: '#3DDC97',
  warn: '#F5B84B',
  risk: '#FF6F63',
  riskWash: 'rgba(255, 111, 99, 0.14)',

  glass: 'rgba(10, 18, 38, 0.72)',
  scrim: 'rgba(3, 6, 15, 0.72)',
} as const;

export const radius = {
  s: 8,
  m: 12,
  l: 16,
  xl: 20,
  pill: 999,
} as const;

export const gap = {
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  7: 32,
} as const;

/** Horizontal page margin: text starts at 16.5 px in the captures. */
export const PAGE_X = 16;

/** The app bar is 60 px tall above the safe-area inset. */
export const HEADER_H = 60;

export const font = {
  display: 'KrikoDisplay-Bold',
  displaySemi: 'KrikoDisplay-SemiBold',
  regular: 'Geist-Regular',
  medium: 'Geist-Medium',
  semibold: 'Geist-SemiBold',
  bold: 'Geist-Bold',
  mono: 'GeistMono-Regular',
  monoMedium: 'GeistMono-Medium',
} as const;

/**
 * Type scale. `size` is the font size that reproduces the ink width in the
 * capture; `lh` is the measured baseline-to-baseline distance.
 */
export const type = {
  /** "SET UP": 41.6 px at a 29 px cap height, condensed 62 wdth. */
  display: { fontFamily: font.display, fontSize: 42, lineHeight: 44, letterSpacing: -0.4 },
  /** "Download the reader once…": solved at 14.75 px over a 283 px run. */
  heroSub: { fontFamily: font.regular, fontSize: 15, lineHeight: 22, letterSpacing: 0.05 },
  /** The product name at the top of a run: Geist Bold at 22 px. */
  productTitle: { fontFamily: font.bold, fontSize: 22, lineHeight: 27, letterSpacing: -0.3 },
  /** "kriko / set up": solved at 12.5 px Geist Mono, no extra tracking. */
  crumb: { fontFamily: font.mono, fontSize: 12.5, lineHeight: 16, letterSpacing: 0 },
  /** "Reader model" and other card titles: 16.5 px semibold. */
  cardTitle: { fontFamily: font.semibold, fontSize: 16.5, lineHeight: 21, letterSpacing: -0.1 },
  /** Body copy: 14 px over a 21 px line. */
  body: { fontFamily: font.regular, fontSize: 14, lineHeight: 21, letterSpacing: 0.05 },
  bodyTight: { fontFamily: font.regular, fontSize: 14, lineHeight: 18, letterSpacing: 0.05 },
  /** "Wi-Fi only": 16 px semibold. */
  rowTitle: { fontFamily: font.semibold, fontSize: 16, lineHeight: 20, letterSpacing: -0.1 },
  /** "Try asking": 13.25 px semibold. */
  sectionLabel: { fontFamily: font.semibold, fontSize: 13.5, lineHeight: 18, letterSpacing: 0.1 },
  /** "Describe a product…": 15.85 px. */
  input: { fontFamily: font.regular, fontSize: 16, lineHeight: 21, letterSpacing: 0.05 },
  /** "Wireless earbuds with noise canceling": 15.35 px. */
  rowText: { fontFamily: font.regular, fontSize: 15.5, lineHeight: 21, letterSpacing: 0.05 },
  /** Action labels: 15 px bold, uppercase, tracked out. */
  action: { fontFamily: font.bold, fontSize: 15, lineHeight: 19, letterSpacing: 1.4 },
  actionSmall: { fontFamily: font.bold, fontSize: 13, lineHeight: 17, letterSpacing: 1.2 },
  /** State chips: 11.5 px bold uppercase. */
  chip: { fontFamily: font.bold, fontSize: 11.5, lineHeight: 14, letterSpacing: 1.2 },
  /** "[MODEL ID] · [SIZE]" and other data lines. */
  mono: { fontFamily: font.mono, fontSize: 11.5, lineHeight: 16, letterSpacing: 0.2 },
  monoSm: { fontFamily: font.mono, fontSize: 10.5, lineHeight: 14, letterSpacing: 0.2 },
  /** "Downloading" / "39%". */
  meta: { fontFamily: font.regular, fontSize: 14, lineHeight: 18, letterSpacing: 0.05 },
  metaMono: { fontFamily: font.mono, fontSize: 12.5, lineHeight: 17, letterSpacing: 0.2 },
  /** Field values in the check screen: 16.5 px bold. */
  fieldValue: { fontFamily: font.bold, fontSize: 16.5, lineHeight: 22, letterSpacing: -0.1 },
  /** Small step rows in the run card. */
  stepTitle: { fontFamily: font.semibold, fontSize: 15, lineHeight: 20, letterSpacing: -0.05 },
  stepMeta: { fontFamily: font.mono, fontSize: 12, lineHeight: 16, letterSpacing: 0.1 },
  /** Claim cards. */
  claimTitle: { fontFamily: font.semibold, fontSize: 17, lineHeight: 22, letterSpacing: -0.1 },
  /** "BETA" pill. */
  beta: { fontFamily: font.bold, fontSize: 11, lineHeight: 14, letterSpacing: 1.6 },
} as const;

export type TypeToken = keyof typeof type;
