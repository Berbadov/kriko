/**
 * The app's motion vocabulary. One place for every spring and duration, so the
 * press of a button and the rise of a sheet read as the same hand.
 *
 * Two axes:
 * - `spring` — what a gesture or arrival *feels* like. `press` (a control
 *   answering a finger), `morph` (a control changing what it means), `sheet`
 *   (bottom chrome arriving), `reveal` (content unfolding into place).
 * - `duration` — the JS-clock counterpart for anything Animated.timing must
 *   drive (opacity, and the few layout props a platform cannot spring).
 *
 * The bare `duration` values (`instant` … `considered`) and the original
 * springs (`responsive`, `gentle`, `snappy`, `smooth`) stay exported because
 * screens already use them; the four named jobs are the vocabulary new work
 * should read.
 *
 * Native adaptation of Arc UI's free motion tokens and principles.
 * Source: https://uiarc.dev/r/arc-motion-tokens.json (MIT, 2026-10-25).
 */

/** A spring preset in the shape `Animated.spring` expects. */
export type SpringToken = {
  stiffness: number;
  damping: number;
  mass: number;
  useNativeDriver: true;
};

export const motion = {
  /** Milliseconds, for `Animated.timing`. */
  duration: {
    /** A state that must land before the eye moves on. */
    instant: 120,
    /** A control's own feedback; short enough to feel like touch. */
    press: 150,
    fast: 160,
    exit: 180,
    /** The state swap inside a morphing control. */
    morph: 240,
    standard: 240,
    /** A native screen transition (fade/slide); the stack also reads this. */
    screen: 240,
    /** A bottom sheet settling (260–320ms ease-out). */
    sheet: 300,
    /** A measured disclosure opening. */
    reveal: 320,
    considered: 480,
  },
  spring: {
    /** A control answering a finger: quick, no visible bounce. */
    press: { stiffness: 700, damping: 45, mass: 1, useNativeDriver: true as const },
    /** A control changing what it means (send → stop). */
    morph: { stiffness: 400, damping: 38, mass: 1, useNativeDriver: true as const },
    /** A bottom sheet arriving: carries weight, settles inside 260–320ms. */
    sheet: { stiffness: 240, damping: 30, mass: 1, useNativeDriver: true as const },
    /** A measured disclosure unfolding; clamped by callers, no overshoot. */
    reveal: { stiffness: 380, damping: 34, mass: 1, useNativeDriver: true as const },
    /** Older presets, kept for callers that already name them. */
    responsive: { stiffness: 520, damping: 44, mass: 1, useNativeDriver: true as const },
    gentle: { stiffness: 340, damping: 34, mass: 1, useNativeDriver: true as const },
    snappy: { stiffness: 600, damping: 50, mass: 1, useNativeDriver: true as const },
    smooth: { stiffness: 340, damping: 34, mass: 1, useNativeDriver: true as const },
  },
  easing: {
    enter: [0.16, 1, 0.3, 1] as const,
    exit: [0.7, 0, 0.84, 0] as const,
    standard: [0.22, 1, 0.36, 1] as const,
    inOut: [0.65, 0, 0.35, 1] as const,
  },
  /** `MotionView index={n}` multiplies this for a stream of arrivals. */
  stagger: { item: 35, line: 80 },
} as const;
