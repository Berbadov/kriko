/**
 * The bottom bar's coming and going. Screens report how far they have scrolled;
 * `engine/dockrules.ts` decides whether the reader wants the room, and the bar
 * (`Chrome.tsx`) follows `progress`: 1 is shown, 0 is gone and its space given
 * back to the page. Reduced motion makes the change instant.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { Animated, Easing } from 'react-native';

import { initialDock, nextDock, type DockMetrics } from '../engine/dockrules';
import { motion } from '../theme/motion';
import { useReducedMotion } from './Motion';

interface Dock {
  /** 1 while the bar is shown, 0 once it has left. Drives layout, so not native. */
  progress: Animated.Value;
  /** One scroll event. `user` is false when the app itself moved the list. */
  report: (metrics: DockMetrics, user?: boolean) => void;
  /** Bring the bar back and forget where the last page was scrolled to. */
  show: () => void;
}

const idle = new Animated.Value(1);
const standalone: Dock = { progress: idle, report: () => undefined, show: () => undefined };
const DockContext = createContext<Dock>(standalone);

export function DockProvider({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(1));
  const state = useRef(initialDock);
  const shown = useRef(true);

  const apply = useCallback((hidden: boolean) => {
    if (shown.current === !hidden) return;
    shown.current = !hidden;
    progress.stopAnimation();
    if (reduced !== false) {
      progress.setValue(hidden ? 0 : 1);
      return;
    }
    Animated.timing(progress, {
      toValue: hidden ? 0 : 1,
      duration: motion.duration.standard,
      easing: Easing.bezier(...motion.easing.standard),
      // The page resizes with the bar, so this is layout, which only JS can drive.
      useNativeDriver: false,
    }).start();
  }, [progress, reduced]);

  const report = useCallback((metrics: DockMetrics, user = true) => {
    state.current = nextDock(state.current, metrics, Date.now(), user);
    apply(state.current.hidden);
  }, [apply]);

  const show = useCallback(() => {
    state.current = initialDock;
    apply(false);
  }, [apply]);

  const value = useMemo(() => ({ progress, report, show }), [progress, report, show]);
  return <DockContext.Provider value={value}>{children}</DockContext.Provider>;
}

export function useDock(): Dock {
  return useContext(DockContext);
}
