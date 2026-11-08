/**
 * The dot-matrix vocabulary, drawn as dust.
 *
 * `MatrixLed`, `LiquidDots` and `LedStatus` keep their props and the footprint
 * their callers laid out for them, and fill it with the same grains as the home
 * screen: a band of light passes down for `scan`, the grains drift slowly for
 * `drift`, and shimmer in place otherwise. Each is one `DustCanvas`, which
 * holds still under reduced motion, while the app is in the background and
 * when its caller pauses it.
 */

import { memo } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { useColors } from '../theme/theme';
import { DustCanvas } from '../dust/DustCanvas';
import { reading as dustReading } from '../dust/engine';
import { Txt } from '../theme/Txt';

/** A field's grid is at most this many cells; it sets the footprint, not the grain count. */
export const MAX_DOTS = 64;

export type MatrixLedMode = 'wave' | 'scan' | 'bars' | 'drift' | 'glyph';

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
  intensity = 0.9,
  fill = false,
  paused = false,
  reducedMotion,
  accessibilityLabel,
  style,
}: MatrixLedProps) {
  const palette = useColors();
  // The grid's own footprint, so a caller's layout is unchanged; the dust fills it.
  const down = Math.max(1, Math.min(8, Math.round(rows)));
  const across = Math.max(1, Math.min(12, Math.floor(MAX_DOTS / down), Math.round(cols)));
  const box = fill ? null : { width: across * (dot + gap) - gap, height: down * (dot + gap) - gap };
  const tint = colors && colors.length ? colors[0] : color ?? palette.accentHi;
  return (
    <View
      pointerEvents="none"
      accessible={Boolean(accessibilityLabel)}
      accessibilityRole={accessibilityLabel ? 'image' : undefined}
      accessibilityLabel={accessibilityLabel}
      importantForAccessibility={accessibilityLabel ? 'auto' : 'no-hide-descendants'}
      accessibilityElementsHidden={!accessibilityLabel}
      style={[fill ? styles.fillField : box, style]}
    >
      <DustCanvas
        scene={dustReading}
        reading={mode === 'scan'}
        calm={mode === 'drift'}
        color={tint}
        strength={Math.min(1, intensity * 1.1)}
        per={fill ? 10 : 1.4}
        cap={fill ? 3000 : 260}
        paused={paused || reducedMotion === true}
      />
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
  width = 44,
  height = 18,
  color,
  colors,
  paused = false,
  reducedMotion,
  style,
}: LiquidDotsProps) {
  const palette = useColors();
  const tint = colors && colors.length ? colors[0] : color ?? palette.accentHi;
  return (
    <View pointerEvents="none" style={[{ width, height }, style]}>
      <DustCanvas
        scene={dustReading}
        color={tint}
        per={1.6}
        cap={400}
        paused={paused || reducedMotion === true}
      />
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
