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

/**
 * How opaque the floating K is while it waits, in percent. It is drawn by the
 * native scanner, so the choice travels there as a number. A touch, a running
 * scan or a waiting answer always wakes it to full strength.
 */
export const PUCK_OPACITY_STEPS: readonly number[] = [35, 55, 75, 100];
export const PUCK_OPACITY_DEFAULT = 55;
const PUCK_OPACITY_MIN = 20;

/** Clamp a stored value to a usable opacity; anything unreadable is the default. */
export function normalizePuckOpacity(value: unknown): number {
  const number = Number(value);
  if (typeof value === 'boolean' || value === null || value === '' || !Number.isFinite(number)) {
    return PUCK_OPACITY_DEFAULT;
  }
  return Math.round(Math.max(PUCK_OPACITY_MIN, Math.min(100, number)));
}

/** The offered step closest to a stored opacity, so a control always shows a choice. */
export function nearestPuckOpacityStep(value: number): number {
  return PUCK_OPACITY_STEPS.reduce((best, step) =>
    Math.abs(step - value) < Math.abs(best - value) ? step : best, PUCK_OPACITY_STEPS[0]);
}

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
