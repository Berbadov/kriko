import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { AccessibilityInfo, Animated, Easing, Pressable, View, type PressableProps, type StyleProp, type ViewStyle } from 'react-native';

import { color as palette } from '../theme/tokens';

const MotionPreference = createContext<boolean | null>(null);

export function MotionProvider({ children }: { children: ReactNode }) {
  const [reduced, setReduced] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((value) => {
      if (alive) setReduced(value);
    }).catch(() => { if (alive) setReduced(true); });
    const listener = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduced);
    return () => { alive = false; listener.remove(); };
  }, []);
  return <MotionPreference.Provider value={reduced}>{children}</MotionPreference.Provider>;
}

export function useReducedMotion() { return useContext(MotionPreference); }

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);
export function MotionPressable({ children, style, onPressIn, onPressOut, ...props }: Omit<PressableProps, 'children' | 'style'> & {
  children: ReactNode; style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  const [scale] = useState(() => new Animated.Value(1));
  const [pressed, setPressed] = useState(false);
  const settle = (value: number) => {
    if (reduced !== false) { scale.setValue(1); return; }
    Animated.spring(scale, { toValue: value, speed: 38, bounciness: 2, useNativeDriver: true }).start();
  };
  return <AnimatedPressable {...props} style={[style, { opacity: pressed ? 0.84 : 1, transform: [{ scale }] }]}
    onPressIn={(event) => { setPressed(true); settle(0.97); onPressIn?.(event); }}
    onPressOut={(event) => { setPressed(false); settle(1); onPressOut?.(event); }}
  >{children}</AnimatedPressable>;
}

export function MotionView({ children, delay = 0, style }: {
  children: ReactNode; delay?: number; style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(0));
  useEffect(() => {
    if (reduced === null) return;
    if (reduced) { progress.setValue(1); return; }
    const animation = Animated.timing(progress, {
      toValue: 1, duration: 380, delay: Math.min(delay, 320),
      easing: Easing.out(Easing.cubic), useNativeDriver: true,
    });
    animation.start();
    return () => animation.stop();
  }, [progress, delay, reduced]);
  return <Animated.View style={[style, { opacity: progress,
    transform: [{ translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [12, 0] }) }],
  }]}>{children}</Animated.View>;
}

export function ActivityDots({ color = palette.accent }: { color?: string }) {
  const reduced = useReducedMotion();
  const [values] = useState(() => [new Animated.Value(0.35), new Animated.Value(0.35), new Animated.Value(0.35)]);
  useEffect(() => {
    if (reduced !== false) { values.forEach((value) => value.setValue(0.65)); return; }
    const loops = values.map((value, index) => Animated.loop(Animated.sequence([
      Animated.delay(index * 100),
      Animated.timing(value, { toValue: 1, duration: 360, useNativeDriver: true }),
      Animated.timing(value, { toValue: 0.35, duration: 360, useNativeDriver: true }),
      Animated.delay((2 - index) * 100),
    ])));
    loops.forEach((loop) => loop.start());
    return () => loops.forEach((loop) => loop.stop());
  }, [values, reduced]);
  return <View accessibilityLabel="Working" style={{ flexDirection: 'row', alignItems: 'center', gap: 4, height: 16 }}>
    {values.map((value, index) => <Animated.View key={index} style={{ width: 5, height: 5, borderRadius: 3,
      backgroundColor: color, opacity: value,
      transform: [{ scale: value.interpolate({ inputRange: [0.35, 1], outputRange: [0.8, 1.15] }) }],
    }} />)}
  </View>;
}
