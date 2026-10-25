/** Native counterpart to Arc UI's free accordion: measured layout and a spring.
 * Reference: https://uiarc.dev/components/accordion. See licenses/UIArc-MIT.txt.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { Animated, View, type StyleProp, type ViewStyle } from 'react-native';

import { motion } from '../theme/motion';
import { useReducedMotion } from './Motion';

function useDisclosureProgress(open: boolean) {
  const reduced = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(open ? 1 : 0));
  useEffect(() => {
    progress.stopAnimation();
    if (reduced !== false) { progress.setValue(open ? 1 : 0); return; }
    const animation = Animated.spring(progress, {
      ...motion.spring.morph, toValue: open ? 1 : 0,
      overshootClamping: true, useNativeDriver: false,
    });
    animation.start();
    return () => animation.stop();
  }, [open, progress, reduced]);
  return progress;
}

export function AnimatedDisclosure({ open, children, style }: {
  open: boolean; children: ReactNode; style?: StyleProp<ViewStyle>;
}) {
  const progress = useDisclosureProgress(open);
  const [height, setHeight] = useState(0);
  return <Animated.View pointerEvents={open ? 'auto' : 'none'}
    accessibilityElementsHidden={!open} importantForAccessibility={open ? 'auto' : 'no-hide-descendants'}
    style={{ overflow: 'hidden', height: progress.interpolate({ inputRange: [0, 1], outputRange: [0, height] }), opacity: progress }}>
    <View onLayout={(event) => setHeight(event.nativeEvent.layout.height)}
      style={[{ position: 'absolute', width: '100%' }, style]}>{children}</View>
  </Animated.View>;
}

export function DisclosureChevron({ open, children }: { open: boolean; children: ReactNode }) {
  const progress = useDisclosureProgress(open);
  return <Animated.View style={{ transform: [{ rotate: progress.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '90deg'] }) }] }}>
    {children}
  </Animated.View>;
}
