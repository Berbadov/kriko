/**
 * Native adaptation of Arc UI's free motion tokens and principles.
 * Source: https://uiarc.dev/r/arc-motion-tokens.json (MIT, 2026-10-25).
 * Spring presets map Arc's stiffness/damping to React Native Animated; the web
 * visualDuration presets are represented by native critically damped springs.
 */
export const motion = {
  duration: { instant: 120, fast: 160, exit: 180, standard: 240, considered: 480 },
  spring: {
    responsive: { stiffness: 520, damping: 44, mass: 1, useNativeDriver: true as const },
    gentle: { stiffness: 340, damping: 34, mass: 1, useNativeDriver: true as const },
    snappy: { stiffness: 600, damping: 50, mass: 1, useNativeDriver: true as const },
    smooth: { stiffness: 340, damping: 34, mass: 1, useNativeDriver: true as const },
    morph: { stiffness: 400, damping: 38, mass: 1, useNativeDriver: true as const },
  },
  easing: {
    enter: [0.16, 1, 0.3, 1] as const,
    exit: [0.7, 0, 0.84, 0] as const,
    standard: [0.22, 1, 0.36, 1] as const,
    inOut: [0.65, 0, 0.35, 1] as const,
  },
  stagger: { item: 35, line: 80 },
} as const;
