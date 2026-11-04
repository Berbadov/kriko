/**
 * A scroll rail within reach of the right thumb, for a conversation too long to
 * cross by reaching to the top. A slim handle at the right edge follows the
 * list; dragging it scrolls the list in proportion, with the percentage beside
 * it. It rests as a faint nub and brightens while the list moves or is held.
 *
 * The list reports its position through `update` instead of through props, so
 * a scroll never re-renders the screen. Only the rail itself takes touches: the
 * strip it occupies is the only part of the list it hides from the finger.
 */

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Animated, Easing, PanResponder, StyleSheet, View } from 'react-native';

import {
  SCRUB_HANDLE_H,
  clampHandleTop,
  handleTopFor,
  offsetForHandleTop,
  percentThrough,
  railHeight,
  scrubEligible,
} from '../engine/scrubrules';
import { tr } from '../i18n';
import { tap } from '../theme/feedback';
import { motion } from '../theme/motion';
import { makeStyles } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { useReducedMotion } from './Motion';

export interface ScrubMetrics {
  offset: number;
  viewport: number;
  content: number;
}

export interface ScrubberHandle {
  /** The list's position. `moving` is true while the list is scrolling. */
  update: (metrics: ScrubMetrics, moving: boolean) => void;
}

interface Props {
  /** Scroll the list to this offset. */
  onScrub: (offset: number) => void;
  onScrubStart?: () => void;
  onScrubEnd?: () => void;
  /** A screen-reader step: down (1) or up (-1) by about a screen. */
  onNudge?: (direction: 1 | -1) => void;
}

/** Wide enough for a thumb, narrow enough to leave the text alone. */
const RAIL_W = 44;
/** The rail fades out this long after the list stops. */
const IDLE_MS = 1500;
/** A touch on the empty rail must travel this far before it scrolls anything. */
const SLOP = 6;

interface Grab {
  active: boolean;
  /** Where the finger first landed, within the rail. */
  origin: number;
  /** How far below the handle's top edge it is held. */
  grip: number;
  moving: boolean;
  bucket: number;
}

export const ScrollScrubber = forwardRef<ScrubberHandle, Props>(function ScrollScrubber(props, ref) {
  const styles = useStyles();
  const reduced = useReducedMotion();
  const [rail, setRail] = useState({ eligible: false, height: 0 });
  const [percent, setPercent] = useState(0);
  const [handleY] = useState(() => new Animated.Value(0));
  const [activity] = useState(() => new Animated.Value(0));
  const [grabbed] = useState(() => new Animated.Value(0));

  const current = useRef(props);
  const railNow = useRef(rail);
  const metrics = useRef<ScrubMetrics>({ offset: 0, viewport: 0, content: 0 });
  const topNow = useRef(0);
  const grab = useRef<Grab>({ active: false, origin: 0, grip: 0, moving: false, bucket: -1 });
  const awake = useRef(false);
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    current.current = props;
  });

  const fade = useCallback((value: Animated.Value, to: number, duration: number) => {
    value.stopAnimation();
    if (reduced !== false) {
      value.setValue(to);
      return;
    }
    Animated.timing(value, {
      toValue: to,
      duration,
      easing: Easing.bezier(...motion.easing.standard),
      useNativeDriver: true,
    }).start();
  }, [reduced]);

  /** Bring the rail up and keep it up for a moment after the last movement. */
  const wake = useCallback(() => {
    if (idle.current) clearTimeout(idle.current);
    if (!awake.current) {
      awake.current = true;
      fade(activity, 1, motion.duration.instant);
    }
    idle.current = setTimeout(() => {
      idle.current = null;
      if (grab.current.active) return;
      awake.current = false;
      fade(activity, 0, motion.duration.considered);
    }, IDLE_MS);
  }, [activity, fade]);

  useEffect(() => () => {
    if (idle.current) clearTimeout(idle.current);
  }, []);

  useImperativeHandle(ref, () => ({
    update: (next, moving) => {
      metrics.current = next;
      const eligible = scrubEligible(next.content, next.viewport);
      const height = railHeight(next.viewport);
      railNow.current = { eligible, height };
      setRail((previous) => (previous.eligible === eligible && previous.height === height
        ? previous : { eligible, height }));
      if (!eligible) return;
      // While a finger holds the handle, the finger decides where it is: the
      // list's own position only catches up, and would make the handle jitter.
      if (!grab.current.active) {
        const place = handleTopFor(next.offset, next.content, next.viewport, height);
        topNow.current = place;
        handleY.setValue(place);
      }
      if (moving) wake();
    },
  }), [handleY, wake]);

  const begin = useCallback(() => {
    grab.current.moving = true;
    fade(grabbed, 1, motion.duration.instant);
    tap();
    current.current.onScrubStart?.();
  }, [fade, grabbed]);

  const finish = useCallback(() => {
    const state = grab.current;
    if (!state.active) return;
    state.active = false;
    fade(grabbed, 0, motion.duration.fast);
    if (state.moving) current.current.onScrubEnd?.();
    state.moving = false;
    wake();
  }, [fade, grabbed, wake]);

  const pan = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => railNow.current.eligible,
    onMoveShouldSetPanResponder: () => false,
    onPanResponderTerminationRequest: () => false,
    onPanResponderGrant: (event) => {
      const touch = event.nativeEvent.locationY;
      const place = topNow.current;
      const onHandle = touch >= place - 10 && touch <= place + SCRUB_HANDLE_H + 10;
      grab.current = {
        active: true,
        origin: touch,
        grip: onHandle ? touch - place : SCRUB_HANDLE_H / 2,
        moving: false,
        bucket: -1,
      };
      wake();
      if (onHandle) begin();
    },
    onPanResponderMove: (_event, gesture) => {
      const state = grab.current;
      if (!state.active) return;
      if (!state.moving) {
        if (Math.abs(gesture.dy) < SLOP) return;
        begin();
      }
      const place = clampHandleTop(state.origin + gesture.dy - state.grip, railNow.current.height);
      topNow.current = place;
      handleY.setValue(place);
      const { content, viewport } = metrics.current;
      const offset = offsetForHandleTop(place, content, viewport, railNow.current.height);
      current.current.onScrub(offset);
      const through = percentThrough(offset, content, viewport);
      setPercent((previous) => (previous === through ? previous : through));
      const bucket = Math.floor(through / 10);
      if (bucket !== state.bucket) {
        if (state.bucket >= 0) tap();
        state.bucket = bucket;
      }
    },
    onPanResponderRelease: finish,
    onPanResponderTerminate: finish,
  }), [begin, finish, handleY, wake]);

  if (!rail.eligible) return null;

  return (
    <View
      {...pan.panHandlers}
      style={[styles.rail, { height: rail.height }]}
      accessible
      accessibilityRole="adjustable"
      accessibilityLabel={tr('Scroll the conversation')}
      accessibilityActions={[
        { name: 'increment', label: tr('Scroll down') },
        { name: 'decrement', label: tr('Scroll up') },
      ]}
      onAccessibilityAction={(event) => {
        current.current.onNudge?.(event.nativeEvent.actionName === 'increment' ? 1 : -1);
      }}
    >
      <Animated.View
        pointerEvents="none"
        style={[styles.track, { opacity: activity.interpolate({ inputRange: [0, 1], outputRange: [0, 0.5] }) }]}
      />
      <Animated.View pointerEvents="none" style={[styles.handleBox, { transform: [{ translateY: handleY }] }]}>
        <Animated.View style={[styles.hint, { opacity: grabbed }]}>
          <Txt variant="monoSm" tone="ink" translate={false}>{`${percent}%`}</Txt>
        </Animated.View>
        <Animated.View style={[styles.handle, styles.handleRest, {
          opacity: activity.interpolate({ inputRange: [0, 1], outputRange: [0.34, 1] }),
        }]} />
        <Animated.View style={[styles.handle, styles.handleHeld, { opacity: grabbed }]} />
      </Animated.View>
    </View>
  );
});

const useStyles = makeStyles((color) => StyleSheet.create({
  rail: { position: 'absolute', right: 0, bottom: 10, width: RAIL_W },
  track: {
    position: 'absolute', right: 19, top: 4, bottom: 4, width: 3, borderRadius: 2,
    backgroundColor: color.edgeStrong,
  },
  handleBox: { position: 'absolute', top: 0, right: 0, width: RAIL_W, height: SCRUB_HANDLE_H },
  handle: { position: 'absolute', right: 17, top: 4, width: 6, height: SCRUB_HANDLE_H - 8, borderRadius: 3 },
  handleRest: { backgroundColor: color.ink3 },
  handleHeld: { backgroundColor: color.accent },
  hint: {
    position: 'absolute', right: RAIL_W + 6, top: (SCRUB_HANDLE_H - 26) / 2, minWidth: 48, height: 26,
    paddingHorizontal: 10, borderRadius: 13, alignItems: 'center', justifyContent: 'center',
    backgroundColor: color.surface, borderWidth: 1, borderColor: color.edgeStrong,
  },
}));
