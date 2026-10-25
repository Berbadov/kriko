/**
 * The reader's display preferences, as data.
 *
 * Kept apart from React so the store, the theme and the motion provider can all
 * agree on the vocabulary without importing each other in a circle.
 */

/** How the app chooses a palette. `system` follows the phone's own setting. */
export type Appearance = 'system' | 'dark' | 'paper' | 'white';

/** A resolved palette name. */
export type PaletteName = 'dark' | 'paper' | 'white';

export type TextSize = 'small' | 'default' | 'large';

/** `system` follows Android's reduce-motion setting. */
export type MotionPreference = 'system' | 'reduced' | 'full';

export const APPEARANCES: readonly Appearance[] = ['system', 'dark', 'paper', 'white'];
export const TEXT_SIZES: readonly TextSize[] = ['small', 'default', 'large'];
export const MOTION_PREFERENCES: readonly MotionPreference[] = ['system', 'reduced', 'full'];

export const TEXT_SCALE: Record<TextSize, number> = {
  small: 0.92,
  default: 1,
  large: 1.14,
};

export function isAppearance(value: unknown): value is Appearance {
  return typeof value === 'string' && (APPEARANCES as readonly string[]).includes(value);
}

export function isTextSize(value: unknown): value is TextSize {
  return typeof value === 'string' && (TEXT_SIZES as readonly string[]).includes(value);
}

export function isMotionPreference(value: unknown): value is MotionPreference {
  return typeof value === 'string' && (MOTION_PREFERENCES as readonly string[]).includes(value);
}

/** Resolve `system` against the phone, leaving an explicit choice alone. */
export function resolvePalette(appearance: Appearance, systemScheme: 'light' | 'dark' | null | undefined): PaletteName {
  if (appearance === 'system') return systemScheme === 'light' ? 'paper' : 'dark';
  return appearance;
}
