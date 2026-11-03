/**
 * Swipe right to open the history drawer, following the finger.
 *
 * A PanResponder is built once and must read the latest values when a gesture
 * happens, not when it was built, so it reads them from a ref at event time.
 * The React Compiler lint cannot see that those reads are inside handlers, so
 * the ref rules are switched off for this file only.
 */
/* eslint-disable react-hooks/refs */

import { useEffect, useRef, useState } from 'react';
import { Animated, PanResponder, useWindowDimensions, type PanResponderInstance } from 'react-native';

import { drawerWidth } from './HistoryDrawer';

export function useDrawerSwipe(progress: Animated.Value, settle: (open: boolean) => void): {
  swipe: PanResponderInstance;
  /** Call from a child whose own horizontal scrolling must win. */
  claimTouch: () => void;
  /** Call as every touch begins, before any child sees it. */
  resetTouch: () => void;
} {
  const { width } = useWindowDimensions();
  const live = useRef({ width, settle, claimed: false });
  useEffect(() => { live.current = { ...live.current, width, settle }; });

  const [swipe] = useState(() => PanResponder.create({
    onMoveShouldSetPanResponderCapture: (_, g) =>
      !live.current.claimed && g.dx > 12 && Math.abs(g.dx) > Math.abs(g.dy) * 1.6,
    onPanResponderGrant: () => { progress.stopAnimation(); },
    onPanResponderMove: (_, g) =>
      progress.setValue(Math.max(0, Math.min(1, g.dx / drawerWidth(live.current.width)))),
    onPanResponderRelease: (_, g) => {
      live.current.settle(g.dx > drawerWidth(live.current.width) * 0.28 || g.vx > 0.5);
    },
    onPanResponderTerminate: () => live.current.settle(false),
  }));

  return {
    swipe,
    claimTouch: () => { live.current.claimed = true; },
    resetTouch: () => { live.current.claimed = false; },
  };
}
