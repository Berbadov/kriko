import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import {
  AccessibilityInfo,
  Animated,
  Easing,
  Pressable,
  View,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { motion } from '../theme/motion';
import type { MotionPreference } from '../theme/preferences';
import { useColors } from '../theme/theme';
import { tr } from '../i18n';

const MotionPreferenceContext = createContext<boolean | null>(null);

export function MotionProvider({
  preference = 'system',
  children,
}: {
  preference?: MotionPreference;
  children: ReactNode;
}) {
  const [systemReduced, setSystemReduced] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    void AccessibilityInfo.isReduceMotionEnabled()
      .then((value) => {
        if (alive) setSystemReduced(value);
      })
      .catch(() => {
        if (alive) setSystemReduced(true);
      });
    const listener = AccessibilityInfo.addEventListener('reduceMotionChanged', (value) => {
      if (alive) setSystemReduced(value);
    });
    return () => {
      alive = false;
      listener.remove();
    };
  }, []);
  const reduced =
    preference === 'reduced' ? true : preference === 'full' ? false : systemReduced;
  return (
    <MotionPreferenceContext.Provider value={reduced}>
      {children}
    </MotionPreferenceContext.Provider>
  );
}

export function useReducedMotion() {
  return useContext(MotionPreferenceContext);
}

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

/** Interruptible press feedback: the press settles before another can start. */
export function MotionPressable({
  children,
  style,
  onPressIn,
  onPressOut,
  ...props
}: Omit<PressableProps, 'children' | 'style'> & {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  const [scale] = useState(() => new Animated.Value(1));
  const [opacity] = useState(() => new Animated.Value(1));

  const settle = (pressed: boolean) => {
    scale.stopAnimation();
    opacity.stopAnimation();
    if (reduced !== false) {
      scale.setValue(1);
      opacity.setValue(1);
      return;
    }
    Animated.parallel([
      Animated.spring(scale, {
        toValue: pressed ? 0.965 : 1,
        ...(pressed ? motion.spring.snappy : motion.spring.press),
      }),
      Animated.timing(opacity, {
        toValue: pressed ? 0.9 : 1,
        duration: pressed ? motion.duration.instant : motion.duration.fast,
        easing: Easing.bezier(...motion.easing.standard),
        useNativeDriver: true,
      }),
    ]).start();
  };

  return (
    <AnimatedPressable
      {...props}
      style={[style, { opacity, transform: [{ scale }] }]}
      onPressIn={(event) => {
        settle(true);
        onPressIn?.(event);
      }}
      onPressOut={(event) => {
        settle(false);
        onPressOut?.(event);
      }}
    >
      {children}
    </AnimatedPressable>
  );
}

/**
 * Content arriving: it rises, scales up a hair and fades in on a soft spring.
 * The spring is over-damped, so nothing bounces; `delay` staggers siblings.
 */
export function MotionView({
  children,
  delay = 0,
  style,
}: {
  children: ReactNode;
  delay?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(0));
  useEffect(() => {
    progress.stopAnimation();
    if (reduced === null) return;
    if (reduced) {
      progress.setValue(1);
      return;
    }
    const animation = Animated.spring(progress, {
      toValue: 1,
      delay: Math.max(0, Math.min(delay, 420)),
      ...motion.spring.arrive,
    });
    animation.start();
    return () => animation.stop();
  }, [progress, delay, reduced]);

  return (
    <Animated.View
      style={[
        style,
        {
          opacity: progress.interpolate({ inputRange: [0, 0.6, 1], outputRange: [0, 0.9, 1], extrapolate: 'clamp' }),
          transform: [
            { translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [16, 0] }) },
            { scale: progress.interpolate({ inputRange: [0, 1], outputRange: [0.985, 1] }) },
          ],
        },
      ]}
    >
      {children}
    </Animated.View>
  );
}

/**
 * A ring that breathes outward from whatever it sits behind: the scan button's
 * invitation. Still when motion is reduced; it never runs behind a press.
 */
export function PulseRing({
  color,
  radius,
  style,
}: {
  color: string;
  radius: number;
  style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  const [phase] = useState(() => new Animated.Value(0));
  useEffect(() => {
    phase.stopAnimation();
    phase.setValue(0);
    if (reduced !== false) return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(phase, {
          toValue: 1,
          duration: motion.breathe,
          easing: Easing.bezier(...motion.easing.standard),
          useNativeDriver: true,
        }),
        Animated.delay(500),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [phase, reduced]);
  if (reduced !== false) return null;
  return (
    <Animated.View
      pointerEvents="none"
      style={[
        {
          position: 'absolute',
          left: 0,
          right: 0,
          top: 0,
          bottom: 0,
          borderRadius: radius,
          borderWidth: 2,
          borderColor: color,
          opacity: phase.interpolate({ inputRange: [0, 0.15, 1], outputRange: [0, 0.55, 0] }),
          transform: [{ scale: phase.interpolate({ inputRange: [0, 1], outputRange: [1, 1.09] }) }],
        },
        style,
      ]}
    />
  );
}

/** A soft sweep over a placeholder while real content is on its way. */
export function Shimmer({ style }: { style?: StyleProp<ViewStyle> }) {
  const palette = useColors();
  const reduced = useReducedMotion();
  const [phase] = useState(() => new Animated.Value(0));
  const [width, setWidth] = useState(0);
  useEffect(() => {
    phase.stopAnimation();
    phase.setValue(0);
    if (reduced !== false || !width) return;
    const loop = Animated.loop(
      Animated.timing(phase, {
        toValue: 1,
        duration: 1400,
        easing: Easing.inOut(Easing.quad),
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [phase, reduced, width]);
  return (
    <View
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
      style={[{ overflow: 'hidden', backgroundColor: palette.raise, borderRadius: 8 }, style]}
    >
      {reduced === false && width ? (
        <Animated.View
          pointerEvents="none"
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            width: width * 0.45,
            backgroundColor: palette.accentWash,
            transform: [{ translateX: phase.interpolate({ inputRange: [0, 1], outputRange: [-width * 0.45, width] }) }],
          }}
        />
      ) : null}
    </View>
  );
}

/** Native looping activity indicator; reduced motion keeps a still indicator. */
export function ActivityDots({ color }: { color?: string }) {
  const palette = useColors();
  const tint = color ?? palette.accent;
  const reduced = useReducedMotion();
  const [values] = useState(() => [
    new Animated.Value(0.4),
    new Animated.Value(0.4),
    new Animated.Value(0.4),
  ]);
  useEffect(() => {
    values.forEach((value) => value.stopAnimation());
    if (reduced !== false) {
      values.forEach((value) => value.setValue(0.65));
      return;
    }
    const loops = values.map((value, index) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(index * 90),
          Animated.timing(value, {
            toValue: 1,
            duration: motion.duration.standard,
            easing: Easing.inOut(Easing.quad),
            useNativeDriver: true,
          }),
          Animated.timing(value, {
            toValue: 0.4,
            duration: motion.duration.standard,
            easing: Easing.inOut(Easing.quad),
            useNativeDriver: true,
          }),
          Animated.delay((2 - index) * 90),
        ]),
      ),
    );
    loops.forEach((loop) => loop.start());
    return () => loops.forEach((loop) => loop.stop());
  }, [values, reduced]);

  return (
    <View
      accessibilityLabel={tr('Working')}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 4, height: 16 }}
    >
      {values.map((value, index) => (
        <Animated.View
          key={index}
          style={{
            width: 5,
            height: 5,
            borderRadius: 3,
            backgroundColor: tint,
            opacity: value,
            transform: [{ scale: value.interpolate({ inputRange: [0.4, 1], outputRange: [0.8, 1.15] }) }],
          }}
        />
      ))}
    </View>
  );
}
