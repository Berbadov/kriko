/**
 * Every radius, gap and type size in the app comes from here.
 *
 * Colours live in `palettes.ts` and reach a component through `theme.tsx`, so a
 * theme switch is a render, not a new bundle. The type scale stays the measured
 * mobile one; the reader's text-size preference scales it at runtime.
 */

import type { TextStyle } from 'react-native';

export const radius = {
  s: 8,
  m: 14,
  l: 20,
  xl: 28,
  pill: 999,
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
export const PAGE_X = 22;

/** The app bar is 56 px tall above the safe-area inset. */
export const HEADER_H = 52;
/** The top bar of an open conversation: the thread's name and one action. */
export const TITLE_BAR_H = 44;

export const font = {
  display: 'Geist-SemiBold',
  displaySemi: 'Geist-SemiBold',
  editorial: 'Geist-SemiBold',
  regular: 'Geist-Regular',
  medium: 'Geist-Medium',
  semibold: 'Geist-SemiBold',
  bold: 'Geist-Bold',
  mono: 'GeistMono-Regular',
  monoMedium: 'GeistMono-Medium',
} as const;

/**
 * Type scale. The desktop's headline is Geist semibold at 32–36 px; the body
 * is 15.5 px over a 1.7 line. The mono crumb stays for data lines.
 */
export const type = {
  /** Settings and welcome titles. */
  display: { fontFamily: font.editorial, fontSize: 42, lineHeight: 47, letterSpacing: -1.2 },
  /** "What do you want to check?" — the desktop's hello. */
  headline: { fontFamily: font.editorial, fontSize: 36, lineHeight: 42, letterSpacing: -0.8 },
  heroSub: { fontFamily: font.regular, fontSize: 15, lineHeight: 22, letterSpacing: 0.05 },
  productTitle: { fontFamily: font.semibold, fontSize: 22, lineHeight: 27, letterSpacing: -0.35 },
  crumb: { fontFamily: font.mono, fontSize: 12, lineHeight: 16, letterSpacing: 0 },
  cardTitle: { fontFamily: font.semibold, fontSize: 16.5, lineHeight: 21, letterSpacing: -0.15 },
  body: { fontFamily: font.regular, fontSize: 15.5, lineHeight: 24, letterSpacing: 0 },
  bodyTight: { fontFamily: font.regular, fontSize: 14.5, lineHeight: 20, letterSpacing: 0.05 },
  rowTitle: { fontFamily: font.semibold, fontSize: 15.5, lineHeight: 20, letterSpacing: -0.1 },
  sectionLabel: { fontFamily: font.semibold, fontSize: 12.5, lineHeight: 17, letterSpacing: 0.15 },
  input: { fontFamily: font.regular, fontSize: 16, lineHeight: 22, letterSpacing: 0.05 },
  rowText: { fontFamily: font.regular, fontSize: 15.5, lineHeight: 21, letterSpacing: 0.05 },
  action: { fontFamily: font.semibold, fontSize: 14, lineHeight: 18, letterSpacing: 0.1 },
  actionSmall: { fontFamily: font.semibold, fontSize: 12.5, lineHeight: 16, letterSpacing: 0.1 },
  chip: { fontFamily: font.semibold, fontSize: 11, lineHeight: 14, letterSpacing: 0.2 },
  mono: { fontFamily: font.mono, fontSize: 11.5, lineHeight: 16, letterSpacing: 0.2 },
  monoSm: { fontFamily: font.mono, fontSize: 10.5, lineHeight: 14, letterSpacing: 0.2 },
  meta: { fontFamily: font.regular, fontSize: 14, lineHeight: 18, letterSpacing: 0.05 },
  metaMono: { fontFamily: font.mono, fontSize: 12, lineHeight: 17, letterSpacing: 0.2 },
  fieldValue: { fontFamily: font.semibold, fontSize: 16.5, lineHeight: 22, letterSpacing: -0.1 },
  stepTitle: { fontFamily: font.semibold, fontSize: 14.5, lineHeight: 20, letterSpacing: -0.05 },
  stepMeta: { fontFamily: font.mono, fontSize: 11.5, lineHeight: 16, letterSpacing: 0.1 },
  claimTitle: { fontFamily: font.semibold, fontSize: 16, lineHeight: 21, letterSpacing: -0.1 },
  beta: { fontFamily: font.bold, fontSize: 10.5, lineHeight: 14, letterSpacing: 1.6 },
} as const;

export type TypeToken = keyof typeof type;

/** The same shape, as resolved styles the theme can scale. */
export type TypeScale = { [K in TypeToken]: TextStyle };
