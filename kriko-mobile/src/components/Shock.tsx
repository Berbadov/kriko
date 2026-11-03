/**
 * Two small pieces of light for the moments the app wants to be noticed.
 *
 * `PulseRing` is a quiet invitation: a ring that breathes outward from whatever
 * it sits behind. `ShockWave` is the one loud thing in the app: when the phone's
 * assistant is summoned, a wavefront crosses the whole screen from the bottom
 * edge, split into red, green and blue rings that arrive a few frames apart (the
 * chromatic edge of a lens), followed by two faint echoes.
 *
 * Rules both keep:
 * - Everything is native-driver opacity and transform; nothing animates layout.
 * - The shock plays exactly once per summoning and never loops, so it cannot
 *   flash more than three times in a second (WCAG 2.3.1), and the flash at its
 *   origin is capped well under full white.
 * - Reduced motion draws no rings at all: the dimmed veil stays, so the reader
 *   still sees that the assistant answered, without anything moving.
 */

import { useEffect, useState } from 'react';
import { Animated, Easing, StyleSheet, useWindowDimensions, View, type StyleProp, type ViewStyle } from 'react-native';

import { motion } from '../theme/motion';
import { useReducedMotion } from './Motion';

/** The three channels of the front. Red leads, blue trails: the order of a lens. */
const CHANNELS = [
  { color: '#FF3060', delay: 0 },
  { color: '#46FFB0', delay: 55 },
  { color: '#4080FF', delay: 110 },
] as const;

/** Fainter white rings that follow the front. */
const ECHOES = [380, 720] as const;

const SHOCK_MS = 1250;
const FRONT_EASING = Easing.bezier(0.2, 0.75, 0.2, 1);

/** A ring that breathes outward once every `period` ms. Nothing moves if reduced. */
export function PulseRing({
  color,
  radius,
  delay = 0,
  period = motion.duration.considered * 5,
  style,
}: {
  color: string;
  radius: number;
  delay?: number;
  period?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  const [phase] = useState(() => new Animated.Value(0));
  useEffect(() => {
    phase.stopAnimation();
    phase.setValue(0);
    if (reduced !== false) return undefined;
    const loop = Animated.loop(Animated.sequence([
      Animated.delay(delay),
      Animated.timing(phase, { toValue: 1, duration: period, easing: FRONT_EASING, useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [phase, reduced, delay, period]);
  if (reduced !== false) return null;
  return (
    <Animated.View
      pointerEvents="none"
      style={[
        StyleSheet.absoluteFill,
        {
          borderRadius: radius,
          borderWidth: 2,
          borderColor: color,
          opacity: phase.interpolate({ inputRange: [0, 0.15, 1], outputRange: [0, 0.5, 0] }),
          transform: [{ scale: phase.interpolate({ inputRange: [0, 1], outputRange: [1, 1.7] }) }],
        },
        style,
      ]}
    />
  );
}

/**
 * The wavefront. Mount it over the screen the assistant opens on; it plays once
 * per `playKey` and then leaves only its veil behind. `pointerEvents` is none,
 * so nothing under it stops working.
 */
export function ShockWave({ playKey, veil = 'rgba(6, 8, 18, 0.5)' }: { playKey: string; veil?: string }) {
  const reduced = useReducedMotion();
  const { width, height } = useWindowDimensions();
  const [front] = useState(() => CHANNELS.map(() => new Animated.Value(0)));
  const [echo] = useState(() => ECHOES.map(() => new Animated.Value(0)));
  const [flash] = useState(() => new Animated.Value(0));
  const [dim] = useState(() => new Animated.Value(0));

  // From the bottom centre to the farthest corner, with room for the ring's width.
  const reach = Math.hypot(width / 2, height) + 80;

  useEffect(() => {
    [...front, ...echo, flash, dim].forEach((value) => { value.stopAnimation(); value.setValue(0); });
    if (reduced !== false) {
      // Still, not silent: the veil says the assistant answered.
      dim.setValue(1);
      return undefined;
    }
    const run = (value: Animated.Value, delay: number) => Animated.sequence([
      Animated.delay(delay),
      Animated.timing(value, { toValue: 1, duration: SHOCK_MS, easing: FRONT_EASING, useNativeDriver: true }),
    ]);
    const animation = Animated.parallel([
      Animated.timing(dim, { toValue: 1, duration: 220, useNativeDriver: true }),
      Animated.sequence([
        Animated.timing(flash, { toValue: 1, duration: 140, useNativeDriver: true }),
        Animated.timing(flash, { toValue: 0, duration: 520, useNativeDriver: true }),
      ]),
      ...front.map((value, index) => run(value, CHANNELS[index].delay)),
      ...echo.map((value, index) => run(value, ECHOES[index])),
    ]);
    animation.start();
    return () => animation.stop();
  }, [playKey, reduced, front, echo, flash, dim]);

  const ringBase = {
    position: 'absolute' as const,
    left: width / 2 - reach,
    top: height - reach,
    width: reach * 2,
    height: reach * 2,
    borderRadius: reach,
    backgroundColor: 'transparent',
  };

  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: veil, opacity: dim }]} />
      {reduced === false ? (
        <>
          {front.map((value, index) => (
            <Animated.View
              key={CHANNELS[index].color}
              style={[ringBase, {
                borderWidth: 26,
                borderColor: CHANNELS[index].color,
                // `screen` adds the three channels where they overlap, so the
                // front is white in the middle and coloured only at its edges.
                mixBlendMode: 'screen',
                opacity: value.interpolate({ inputRange: [0, 0.04, 0.8, 1], outputRange: [0, 0.95, 0.85, 0] }),
                transform: [{ scale: value.interpolate({ inputRange: [0, 1], outputRange: [0.02, 1] }) }],
              }]}
            />
          ))}
          {echo.map((value, index) => (
            <Animated.View
              key={ECHOES[index]}
              style={[ringBase, {
                borderWidth: 5,
                borderColor: 'rgba(255, 255, 255, 0.5)',
                mixBlendMode: 'screen',
                opacity: value.interpolate({ inputRange: [0, 0.04, 0.8, 1], outputRange: [0, 0.6 - index * 0.2, 0.4 - index * 0.15, 0] }),
                transform: [{ scale: value.interpolate({ inputRange: [0, 1], outputRange: [0.02, 1] }) }],
              }]}
            />
          ))}
          <Animated.View
            style={{
              position: 'absolute',
              left: width / 2 - 150,
              top: height - 150,
              width: 300,
              height: 300,
              borderRadius: 150,
              backgroundColor: 'rgba(255, 255, 255, 0.55)',
              opacity: flash,
              transform: [{ scale: flash.interpolate({ inputRange: [0, 1], outputRange: [0.2, 1.6] }) }],
            }}
          />
        </>
      ) : null}
    </View>
  );
}
