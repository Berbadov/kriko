/**
 * The dot-matrix vocabulary: a small LED field, a liquid particle row, and the
 * one clock they share.
 *
 * A reader asked for "more usage of matrix led animations" and a "particle
 * liquid animation for screen reading". This module is the whole cost budget
 * for both: every dot is a plain `Animated.View` whose opacity (and, for the
 * liquid row, its transform) is a *native-driver* interpolation of one shared
 * `Animated.Value`. No frame crosses the JS bridge, nothing calls `setState`
 * per frame, and a field is capped at 64 dots (`MAX_DOTS`) so a background can
 * afford one without a measurement pass.
 *
 * The shared clock is a linear 0→1 loop. Each dot turns that clock into its own
 * piecewise-linear curve — a travelling pulse (`wave`, `scan`, `bars`, `glyph`)
 * or a seamless shifted triangle (`drift`) — so one value carries every phase.
 *
 * Reduced motion renders the same geometry as a still pattern (the curve
 * sampled mid-cycle), and the loop stops when the app is backgrounded, when
 * the caller says the surface is off screen, or when the component unmounts.
 */

import { memo, useEffect, useMemo, useState } from 'react';
import {
  Animated,
  AppState,
  Easing,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { useReducedMotion } from './Motion';

/** No instance animates more dots than this; a full-screen field is 7×9. */
export const MAX_DOTS = 64;

/** A dot is never fully dark: a faint field reads as an LED panel at rest. */
const BASE_ALPHA = 0.1;

export type MatrixLedMode = 'wave' | 'scan' | 'bars' | 'drift' | 'glyph';

/** One full cycle, in milliseconds, when the caller does not name a speed. */
const MODE_SPEED: Record<MatrixLedMode, number> = {
  wave: 2600,
  scan: 1500,
  bars: 1900,
  drift: 9000,
  glyph: 2400,
};

/** A piecewise-linear opacity curve, in the shape `Animated.interpolate` wants. */
export type LedCurve = { input: number[]; output: number[] };

/** The curve's value at `t`, for a still frame under reduced motion. */
export function curveAt(curve: LedCurve, t: number): number {
  const { input, output } = curve;
  if (t <= input[0]) return output[0];
  for (let index = 1; index < input.length; index += 1) {
    if (t <= input[index]) {
      const span = input[index] - input[index - 1];
      const progress = span > 0 ? (t - input[index - 1]) / span : 1;
      return output[index - 1] + (output[index] - output[index - 1]) * progress;
    }
  }
  return output[output.length - 1];
}

/**
 * A seamless triangle wave, shifted by `phase`, as a curve the native driver can
 * interpolate. The triangle is symmetric, so the value at t=0 and t=1 is the
 * same and the loop has no visible seam. `low`/`high` are the output bounds.
 */
export function driftCurve(phase: number, low: number, high: number): LedCurve {
  const wrapped = phase - Math.floor(phase);
  // 0 and 1 would produce duplicate breakpoints; 0.5 is the triangle's peak.
  const p = Math.min(0.495, Math.max(0.005, wrapped));
  const span = high - low;
  if (p < 0.5) {
    const start = low + span * (2 * p);
    return { input: [0, 0.5 - p, 1 - p, 1], output: [start, high, low, start] };
  }
  const start = low + span * (2 * (1 - p));
  return { input: [0, 1 - p, 1.5 - p, 1], output: [start, low, high, start] };
}

/** A deterministic 0–1 value per dot, so a field's phases never repeat in step. */
function hash(row: number, col: number): number {
  const value = Math.sin(row * 127.1 + col * 311.7) * 43758.5453;
  return value - Math.floor(value);
}

/** The Kriko K, drawn on any grid: a stem, and two arms meeting at its middle. */
function inGlyph(row: number, col: number, rows: number, cols: number): boolean {
  const center = Math.floor((rows - 1) / 2);
  // The mark is as wide as its arms can reach; centre that inside a wider grid.
  const width = center + 1;
  const stem = col - Math.max(0, Math.floor((cols - width) / 2));
  if (stem < 0 || stem >= width) return false;
  return stem === 0 || row + stem === center || row - stem === center;
}

function curveFor(
  mode: MatrixLedMode,
  row: number,
  col: number,
  rows: number,
  cols: number,
  intensity: number,
  phase: number,
): LedCurve {
  // The dim end follows the brightness: a 0.10 background must not sit at 0.10.
  const dim = Math.min(BASE_ALPHA, intensity * 0.3);
  switch (mode) {
    case 'scan': {
      // A full-height bar crossing the field once per cycle.
      const start = cols > 1 ? (col / (cols - 1)) * 0.76 : 0.36;
      return { input: [start, start + 0.09, start + 0.2], output: [dim, intensity, dim] };
    }
    case 'bars': {
      // Columns fill bottom-up, each on its own beat, with uneven peaks.
      const start = (col / cols) * 0.55 + (rows - 1 - row) * 0.028;
      const peak = intensity * (0.55 + phase * 0.45);
      return { input: [start, start + 0.1, start + 0.2], output: [dim, peak, dim] };
    }
    case 'wave': {
      // A diagonal ridge travelling across the field.
      const span = Math.max(1, rows + cols - 2);
      const start = ((row + col) / span) * 0.7;
      return { input: [start, start + 0.12, start + 0.26], output: [dim, intensity, dim] };
    }
    case 'glyph': {
      // The mark itself, with a pulse running through it; off-mark dots sit dim.
      const on = inGlyph(row, col, rows, cols);
      const span = Math.max(1, rows + cols - 2);
      const start = ((row + col) / span) * 0.68;
      return {
        input: [start, start + 0.12, start + 0.26],
        output: [on ? dim * 1.5 : dim * 0.4, on ? intensity : dim * 0.6, on ? dim * 1.5 : dim * 0.4],
      };
    }
    case 'drift':
    default:
      // Every dot breathes on its own phase; uneven peaks keep it from pulsing.
      return driftCurve(phase, dim, intensity * (0.62 + phase * 0.38));
  }
}

/**
 * One looping 0→1 clock for an LED surface. Native-driven, linear, and never
 * treated as an interaction (it must not hold a VirtualizedList back).
 * `active` false stops the loop where it is; a backgrounded app stops it too.
 */
export function useLedClock(speed: number, active: boolean): Animated.Value {
  const [clock] = useState(() => new Animated.Value(0));
  const [awake, setAwake] = useState(() => AppState.currentState === 'active');

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      setAwake(state === 'active');
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    clock.stopAnimation();
    if (!active || !awake) return;
    clock.setValue(0);
    const loop = Animated.loop(
      Animated.timing(clock, {
        toValue: 1,
        duration: Math.max(400, speed),
        easing: Easing.linear,
        useNativeDriver: true,
        isInteraction: false,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [active, awake, clock, speed]);

  return clock;
}

export type MatrixLedProps = {
  /** Dots down. Default 3. */
  rows?: number;
  /** Dots across. Default 9; clamped so `rows × cols` never exceeds 64. */
  cols?: number;
  /** A dot's edge, in points. Default 3. */
  dot?: number;
  /** Space between dots. Default 3. */
  gap?: number;
  /** The motion pattern. Default `scan`. */
  mode?: MatrixLedMode;
  /** One tint. Ignored when `colors` is given. Defaults to the palette accent. */
  color?: string;
  /** Two or three tints, woven diagonally across the field. */
  colors?: readonly string[];
  /** Milliseconds for one cycle. Defaults per mode (scan 1.5 s, drift 9 s). */
  speed?: number;
  /** Brightest dot opacity, 0–1. Default 0.9; a background wants 0.10. */
  intensity?: number;
  /** Round dots (an LED) rather than square pixels. Default true. */
  round?: boolean;
  /** Spread the grid across the available box instead of packing it. */
  fill?: boolean;
  /** Stop the loop without unmounting (a folded sheet, an unfocused screen). */
  paused?: boolean;
  /** Override the reader's motion preference. */
  reducedMotion?: boolean;
  /** Decorative by default; a label makes the field an image for a screen reader. */
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
};

/**
 * A reusable dot-matrix LED field.
 *
 * Cost: one `Animated.Value`, one loop, `rows × cols` (≤ 64) plain views, all
 * driven by native-driver opacity interpolation. It never re-renders per frame,
 * and `memo` keeps a streaming answer from reconciling the dots on every tick.
 */
export const MatrixLed = memo(function MatrixLed({
  rows = 3,
  cols = 9,
  dot = 3,
  gap = 3,
  mode = 'scan',
  color,
  colors,
  speed,
  intensity = 0.9,
  round = true,
  fill = false,
  paused = false,
  reducedMotion,
  accessibilityLabel,
  style,
}: MatrixLedProps) {
  const palette = useColors();
  const reduced = useReducedMotion();
  // Unknown motion preference counts as reduced: a still field never flashes.
  const still = reducedMotion ?? reduced !== false;
  const clock = useLedClock(speed ?? MODE_SPEED[mode], !still && !paused);

  const tints = useMemo(
    () => (colors && colors.length ? colors : [color ?? palette.accentHi]),
    [color, colors, palette.accentHi],
  );
  // A caller may build the tint array inline; key on its contents, not identity.
  const tintKey = tints.join(',');

  const grid = useMemo(() => {
    const down = Math.max(1, Math.min(8, Math.round(rows)));
    const across = Math.max(1, Math.min(12, Math.floor(MAX_DOTS / down)));
    const lines: {
      key: string;
      tint: string;
      stillAlpha: number;
      alpha: Animated.AnimatedInterpolation<number>;
    }[][] = [];
    for (let row = 0; row < down; row += 1) {
      const line: {
        key: string;
        tint: string;
        stillAlpha: number;
        alpha: Animated.AnimatedInterpolation<number>;
      }[] = [];
      for (let col = 0; col < across; col += 1) {
        const curve = curveFor(mode, row, col, down, across, intensity, hash(row, col));
        line.push({
          key: `${row}-${col}`,
          // Two or three tints weave diagonally, so a sweep changes colour as it
          // travels and the field never reads as colour-blocked columns.
          tint: tints[(row + col) % tints.length],
          stillAlpha: curveAt(curve, 0.5),
          alpha: clock.interpolate({
            inputRange: curve.input,
            outputRange: curve.output,
            extrapolate: 'clamp',
          }),
        });
      }
      lines.push(line);
    }
    return lines;
    // `tints` is read through `tintKey`; the array identity is not meaningful.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clock, intensity, mode, rows, cols, tintKey]);

  return (
    <View
      pointerEvents="none"
      accessible={Boolean(accessibilityLabel)}
      accessibilityRole={accessibilityLabel ? 'image' : undefined}
      accessibilityLabel={accessibilityLabel}
      importantForAccessibility={accessibilityLabel ? 'auto' : 'no-hide-descendants'}
      accessibilityElementsHidden={!accessibilityLabel}
      style={[fill ? styles.fillField : styles.field, fill ? null : { gap }, style]}
    >
      {grid.map((line, row) => (
        <View key={row} style={fill ? styles.fillRow : styles.row}>
          {line.map((item) => {
            const shape = {
              width: dot,
              height: dot,
              borderRadius: round ? dot / 2 : 1,
              backgroundColor: item.tint,
              opacity: still ? item.stillAlpha : item.alpha,
            };
            return fill ? (
              <View key={item.key} style={styles.fillCell}>
                <Animated.View style={shape} />
              </View>
            ) : (
              <Animated.View key={item.key} style={shape} />
            );
          })}
        </View>
      ))}
    </View>
  );
});

export type LiquidDotsProps = {
  /** How many droplets. Default 7; keep it under a dozen. */
  count?: number;
  /** A droplet's diameter. Default 4. */
  size?: number;
  /** The row's width; droplets are spaced evenly across it. Default 44. */
  width?: number;
  /** The row's height, which is also the bob distance. Default 18. */
  height?: number;
  /** Milliseconds for one bob cycle. Default 2600. */
  speed?: number;
  /** One tint. Ignored when `colors` is given. Defaults to the palette accent. */
  color?: string;
  /** Two or three tints, cycled across the droplets. */
  colors?: readonly string[];
  paused?: boolean;
  reducedMotion?: boolean;
  style?: StyleProp<ViewStyle>;
};

/**
 * A compact liquid-particle row: droplets bob, swell and fade on the same
 * shifted triangle, so the loop is seamless and one clock drives every one.
 *
 * Cost: one `Animated.Value`, one loop, `count` views, native-driver opacity
 * and transform only. Reduced motion freezes them mid-bob.
 */
export const LiquidDots = memo(function LiquidDots({
  count = 7,
  size = 4,
  width = 44,
  height = 18,
  speed = 2600,
  color,
  colors,
  paused = false,
  reducedMotion,
  style,
}: LiquidDotsProps) {
  const palette = useColors();
  const reduced = useReducedMotion();
  const still = reducedMotion ?? reduced !== false;
  const clock = useLedClock(speed, !still && !paused);

  const tints = useMemo(
    () => (colors && colors.length ? colors : [color ?? palette.accentHi]),
    [color, colors, palette.accentHi],
  );
  const tintKey = tints.join(',');

  const particles = useMemo(() => {
    const step = width / Math.max(1, count);
    const list: {
      key: number;
      tint: string;
      left: number;
      bottom: number;
      stillOpacity: number;
      stillRise: number;
      stillScale: number;
      opacity: Animated.AnimatedInterpolation<number>;
      rise: Animated.AnimatedInterpolation<number>;
      scale: Animated.AnimatedInterpolation<number>;
    }[] = [];
    for (let index = 0; index < count; index += 1) {
      const phase = index / Math.max(1, count) + 0.06;
      // The bob stays inside the row's box: `bottom` is inset by the amplitude.
      const rise = driftCurve(phase, height * 0.25, -height * 0.25);
      const fade = driftCurve(phase + 0.42, 0.2, 0.9);
      const swell = driftCurve(phase + 0.21, 0.72, 1.12);
      list.push({
        key: index,
        tint: tints[index % tints.length],
        left: step * index + (step - size) / 2,
        bottom: height * 0.28,
        stillOpacity: curveAt(fade, 0.5),
        stillRise: curveAt(rise, 0.5),
        stillScale: curveAt(swell, 0.5),
        opacity: clock.interpolate({ inputRange: fade.input, outputRange: fade.output, extrapolate: 'clamp' }),
        rise: clock.interpolate({ inputRange: rise.input, outputRange: rise.output, extrapolate: 'clamp' }),
        scale: clock.interpolate({ inputRange: swell.input, outputRange: swell.output, extrapolate: 'clamp' }),
      });
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clock, count, height, size, tintKey, width]);

  return (
    <View
      pointerEvents="none"
      importantForAccessibility="no-hide-descendants"
      accessibilityElementsHidden
      style={[{ width, height }, style]}
    >
      {particles.map((particle) => (
        <Animated.View
          key={particle.key}
          style={{
            position: 'absolute',
            bottom: particle.bottom,
            left: particle.left,
            width: size,
            height: size,
            borderRadius: size / 2,
            backgroundColor: particle.tint,
            opacity: still ? particle.stillOpacity : particle.opacity,
            transform: still
              ? [{ translateY: particle.stillRise }, { scale: particle.stillScale }]
              : [{ translateY: particle.rise }, { scale: particle.scale }],
          }}
        />
      ))}
    </View>
  );
});

/**
 * A small LED beside one line of status copy — the compact form of the field for
 * a sheet that is reading something. The label is the caller's (already
 * translated) string, so this component owns no copy.
 */
export function LedStatus({
  label,
  mode = 'scan',
  color,
  rows = 3,
  cols = 6,
  speed,
  style,
}: {
  label: string;
  mode?: MatrixLedMode;
  color?: string;
  rows?: number;
  cols?: number;
  speed?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const palette = useColors();
  return (
    <View style={[styles.status, style]}>
      <MatrixLed
        rows={rows}
        cols={cols}
        mode={mode}
        dot={3}
        gap={3}
        color={color ?? palette.accentHi}
        intensity={0.92}
        speed={speed}
      />
      <Txt variant="bodyTight" tone="ink" style={styles.statusLabel}>
        {label}
      </Txt>
    </View>
  );
}

const styles = StyleSheet.create({
  field: { flexDirection: 'column', alignItems: 'flex-start' },
  row: { flexDirection: 'row', alignItems: 'center' },
  fillField: { flexDirection: 'column', alignSelf: 'stretch', flex: 1 },
  fillRow: { flex: 1, flexDirection: 'row', alignItems: 'center' },
  fillCell: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  status: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  statusLabel: { flexShrink: 1 },
});
