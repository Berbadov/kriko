/**
 * The conversation's own weather: a slow LED drift field and four liquid
 * patches, full-bleed behind the messages and the composer.
 *
 * The reader asked for "a background animation for chat". This one is an
 * ambience, not a show: the brightest dot never passes 0.10 opacity and the
 * patches stay under 0.06, so answer text keeps the contrast it had. It draws
 * nothing a finger can hit (`pointerEvents="none"`) and it costs one 63-dot LED
 * field plus four views, all on native-driver opacity/transform — no blur, no
 * gradient, no per-frame JavaScript.
 *
 * It stops when the route loses focus or the app is backgrounded, and under
 * reduced motion it renders the same geometry as a still, faint field.
 */

import { memo, useCallback, useMemo, useState } from 'react';
import { Animated, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';

import { useColors } from '../theme/theme';
import { useReducedMotion } from './Motion';
import { MatrixLed, curveAt, driftCurve, useLedClock } from './MatrixLed';

/** The brightest dot in the field; answer text must stay fully readable. */
const FIELD_INTENSITY = 0.1;
/** One drift cycle. Slow enough that the field never draws the eye. */
const FIELD_SPEED = 14000;
/** One bob cycle for the liquid patches. */
const BLOB_SPEED = 30000;

type Blob = {
  size: number;
  left: `${number}%`;
  top: `${number}%`;
  /** Where this patch sits in the shared cycle. */
  phase: number;
  /** How far it wanders, in points. */
  driftX: number;
  driftY: number;
  /** Palette key; resolved at render so a theme switch recolours it. */
  tint: 'accent' | 'ok' | 'warn';
  low: number;
  high: number;
};

/** Four patches, spread so the page never has one bright corner. */
const BLOBS: readonly Blob[] = [
  { size: 280, left: '-22%', top: '-14%', phase: 0.08, driftX: 28, driftY: 34, tint: 'accent', low: 0.024, high: 0.07 },
  { size: 190, left: '58%', top: '18%', phase: 0.44, driftX: -24, driftY: 30, tint: 'ok', low: 0.016, high: 0.05 },
  { size: 240, left: '4%', top: '56%', phase: 0.71, driftX: 20, driftY: -32, tint: 'accent', low: 0.02, high: 0.055 },
  { size: 160, left: '64%', top: '70%', phase: 0.26, driftX: -18, driftY: -24, tint: 'warn', low: 0.014, high: 0.042 },
];

export type ChatBackgroundProps = {
  /** Stop the ambience without unmounting it (a modal, a paused screen). */
  paused?: boolean;
};

/**
 * A pointer-events-none, full-bleed animated background for the conversation.
 *
 * Cost: 63 LED dots + 4 patch views, two native-driven loops (14 s field,
 * 30 s patches), zero JavaScript per frame. `memo` keeps a streaming answer's
 * re-renders from touching any of them. Reduced motion: a still field.
 */
export const ChatBackground = memo(function ChatBackground({ paused = false }: ChatBackgroundProps) {
  const palette = useColors();
  const reduced = useReducedMotion();
  const still = reduced !== false;

  // A chat behind a sheet or another route should not keep drawing frames.
  const [focused, setFocused] = useState(true);
  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      return () => setFocused(false);
    }, []),
  );

  const active = focused && !paused;
  const clock = useLedClock(BLOB_SPEED, active && !still);
  const tints = useMemo(() => [palette.accent, palette.ok, palette.warn], [palette]);

  const blobs = useMemo(
    () =>
      BLOBS.map((blob, index) => {
        const x = driftCurve(blob.phase, -blob.driftX, blob.driftX);
        const y = driftCurve(blob.phase + 0.17, -blob.driftY, blob.driftY);
        const fade = driftCurve(blob.phase + 0.5, blob.low, blob.high);
        const swell = driftCurve(blob.phase + 0.33, 0.92, 1.08);
        return {
          key: `${blob.tint}-${index}`,
          size: blob.size,
          left: blob.left,
          top: blob.top,
          tint: palette[blob.tint],
          stillX: curveAt(x, 0.5),
          stillY: curveAt(y, 0.5),
          stillOpacity: curveAt(fade, 0.5),
          stillScale: curveAt(swell, 0.5),
          x: clock.interpolate({ inputRange: x.input, outputRange: x.output, extrapolate: 'clamp' }),
          y: clock.interpolate({ inputRange: y.input, outputRange: y.output, extrapolate: 'clamp' }),
          opacity: clock.interpolate({ inputRange: fade.input, outputRange: fade.output, extrapolate: 'clamp' }),
          scale: clock.interpolate({ inputRange: swell.input, outputRange: swell.output, extrapolate: 'clamp' }),
        };
      }),
    [clock, palette],
  );

  return (
    <View pointerEvents="none" style={styles.stage}>
      <View style={styles.field}>
        <MatrixLed
          rows={7}
          cols={9}
          mode="drift"
          dot={4}
          round
          fill
          colors={tints}
          intensity={FIELD_INTENSITY}
          speed={FIELD_SPEED}
          paused={!active}
        />
      </View>
      {blobs.map((blob) => (
        <Animated.View
          key={blob.key}
          style={{
            position: 'absolute',
            left: blob.left,
            top: blob.top,
            width: blob.size,
            height: blob.size,
            borderRadius: blob.size / 2,
            backgroundColor: blob.tint,
            opacity: still ? blob.stillOpacity : blob.opacity,
            transform: still
              ? [{ translateX: blob.stillX }, { translateY: blob.stillY }, { scale: blob.stillScale }]
              : [{ translateX: blob.x }, { translateY: blob.y }, { scale: blob.scale }],
          }}
        />
      ))}
    </View>
  );
});

const styles = StyleSheet.create({
  stage: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, overflow: 'hidden' },
  field: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, paddingHorizontal: 12, paddingVertical: 18 },
});
