/**
 * Every radius, gap and type size in the app comes from here.
 *
 * Colours live in `palettes.ts` and reach a component through `theme.tsx`, so a
 * theme switch is a render, not a new bundle. The type scale stays the measured
 * mobile one; the reader's text-size preference scales it at runtime.
 */

import type { TextStyle } from 'react-native';

export const radius = {
  s: 10,
  m: 16,
  l: 24,
  xl: 32,
  pill: 999,
} as const;

/**
 * Depth comes from a soft shadow and a bright rim, not from outlines. `card`
 * rests on the page; `float` is for what hovers above it (the composer, the
 * dock, a sheet); `glow` is the halo behind the one primary action.
 */
export const elevation = {
  card: (shadow: string) => ({
    shadowColor: shadow,
    shadowOpacity: 0.07,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 4 },
    elevation: 1,
  }),
  float: (shadow: string) => ({
    shadowColor: shadow,
    shadowOpacity: 0.16,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 10 },
    elevation: 6,
  }),
} as const;

export const gap = {
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 28,
  7: 36,
} as const;

/** Horizontal page margin. */
export const PAGE_X = 16;

/** The app bar is 56 px tall above the safe-area inset. */
export const HEADER_H = 56;
/** The top bar of an open conversation: the thread's name and one action. */
export const TITLE_BAR_H = 44;

/**
 * Atkinson Hyperlegible, drawn by the Braille Institute so that look-alike
 * letters (I, l, 1, O, 0) stay distinct for low-vision readers. It ships two
 * weights, so emphasis is Regular against Bold and the finer steps of the
 * hierarchy come from size and tone, never from a medium weight.
 */
export const font = {
  display: 'Atkinson-Bold',
  displaySemi: 'Atkinson-Bold',
  editorial: 'Atkinson-Bold',
  regular: 'Atkinson-Regular',
  medium: 'Atkinson-Regular',
  semibold: 'Atkinson-Bold',
  bold: 'Atkinson-Bold',
  mono: 'AtkinsonMono-Regular',
  monoMedium: 'AtkinsonMono-Medium',
} as const;

/**
 * Type scale, set for readers of every age: nothing is below 13 pt, running
 * text is 16 to 17.5 pt over a 1.5 line, and labels are sentence case at 14 pt
 * or more rather than tiny tracked capitals. Atkinson is a wide face, so
 * tracking is zero everywhere (negative tracking closes the very gaps the face
 * was drawn to keep open).
 */
export const type = {
  /** Settings and welcome titles. */
  display: { fontFamily: font.editorial, fontSize: 38, lineHeight: 43, letterSpacing: 0 },
  /** "Check before you buy." */
  headline: { fontFamily: font.editorial, fontSize: 36, lineHeight: 41, letterSpacing: 0 },
  heroSub: { fontFamily: font.regular, fontSize: 17, lineHeight: 25, letterSpacing: 0 },
  productTitle: { fontFamily: font.semibold, fontSize: 24, lineHeight: 31, letterSpacing: 0 },
  /** A section heading inside a long answer: quieter than the product title. */
  heading: { fontFamily: font.editorial, fontSize: 21, lineHeight: 27, letterSpacing: 0 },
  crumb: { fontFamily: font.mono, fontSize: 14, lineHeight: 20, letterSpacing: 0 },
  cardTitle: { fontFamily: font.semibold, fontSize: 18, lineHeight: 23, letterSpacing: 0 },
  body: { fontFamily: font.regular, fontSize: 17.5, lineHeight: 27, letterSpacing: 0 },
  bodyTight: { fontFamily: font.regular, fontSize: 16, lineHeight: 23, letterSpacing: 0 },
  rowTitle: { fontFamily: font.semibold, fontSize: 17, lineHeight: 22, letterSpacing: 0 },
  sectionLabel: { fontFamily: font.semibold, fontSize: 14, lineHeight: 19, letterSpacing: 0 },
  input: { fontFamily: font.regular, fontSize: 17.5, lineHeight: 24, letterSpacing: 0 },
  rowText: { fontFamily: font.regular, fontSize: 17, lineHeight: 23, letterSpacing: 0 },
  action: { fontFamily: font.semibold, fontSize: 16, lineHeight: 20, letterSpacing: 0 },
  actionSmall: { fontFamily: font.semibold, fontSize: 14, lineHeight: 18, letterSpacing: 0 },
  chip: { fontFamily: font.semibold, fontSize: 13.5, lineHeight: 17, letterSpacing: 0 },
  mono: { fontFamily: font.mono, fontSize: 14, lineHeight: 20, letterSpacing: 0 },
  monoSm: { fontFamily: font.mono, fontSize: 13, lineHeight: 18, letterSpacing: 0 },
  meta: { fontFamily: font.regular, fontSize: 15.5, lineHeight: 20, letterSpacing: 0 },
  metaMono: { fontFamily: font.mono, fontSize: 14, lineHeight: 19, letterSpacing: 0 },
  fieldValue: { fontFamily: font.semibold, fontSize: 17.5, lineHeight: 23, letterSpacing: 0 },
  stepTitle: { fontFamily: font.semibold, fontSize: 16.5, lineHeight: 22, letterSpacing: 0 },
  stepMeta: { fontFamily: font.mono, fontSize: 13.5, lineHeight: 18, letterSpacing: 0 },
  claimTitle: { fontFamily: font.semibold, fontSize: 17.5, lineHeight: 23, letterSpacing: 0 },
  beta: { fontFamily: font.bold, fontSize: 13, lineHeight: 17, letterSpacing: 1.2 },
} as const;

export type TypeToken = keyof typeof type;

/** The same shape, as resolved styles the theme can scale. */
export type TypeScale = { [K in TypeToken]: TextStyle };
