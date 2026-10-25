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
        toValue: pressed ? 0.975 : 1,
        ...motion.spring.snappy,
      }),
      Animated.timing(opacity, {
        toValue: pressed ? 0.86 : 1,
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

/** A short opacity/lift reveal; children remain visible while motion loads. */
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
    const animation = Animated.timing(progress, {
      toValue: 1,
      duration: motion.duration.considered,
      delay: Math.max(0, Math.min(delay, 320)),
      easing: Easing.bezier(...motion.easing.enter),
      useNativeDriver: true,
    });
    animation.start();
    return () => animation.stop();
  }, [progress, delay, reduced]);

  return (
    <Animated.View
      style={[
        style,
        {
          opacity: progress,
          transform: [
            { translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [10, 0] }) },
          ],
        },
      ]}
    >
      {children}
    </Animated.View>
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
            backgroundColor: color,
            opacity: value,
            transform: [{ scale: value.interpolate({ inputRange: [0.4, 1], outputRange: [0.8, 1.15] }) }],
          }}
        />
      ))}
    </View>
  );
}
