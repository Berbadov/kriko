/**
 * The history drawer: swipe right on Home and it glides in over the chat as a
 * pane of frosted glass, with chats and screen reads on separate shelves.
 *
 * `progress` (0 closed, 1 open) is owned by the screen so its swipe can drive
 * the drawer while the finger is still down.
 */

import { useState } from 'react';
import { Animated, PanResponder, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { tr } from '../i18n';
import { motion } from '../theme/motion';
import { gap, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { Glass } from './Glass';
import { HistoryLists } from './HistoryLists';
import { PlusIcon, XIcon } from './Icon';
import { MotionPressable, useReducedMotion } from './Motion';

export function drawerWidth(screen: number): number {
  return Math.min(screen * 0.9, 400);
}

export function settleDrawer(progress: Animated.Value, open: boolean, reduced: boolean | null) {
  progress.stopAnimation();
  if (reduced !== false) {
    progress.setValue(open ? 1 : 0);
    return;
  }
  Animated.spring(progress, { ...motion.spring.morph, toValue: open ? 1 : 0, useNativeDriver: true, overshootClamping: true }).start();
}

export function HistoryDrawer({ progress, open, onClose, onNewChat }: {
  progress: Animated.Value;
  open: boolean;
  onClose: () => void;
  onNewChat: () => void;
}) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const color = useColors();
  const styles = useStyles();
  const reduced = useReducedMotion();
  const w = drawerWidth(width);

  // A swipe left on the open drawer drags it shut.
  const [pan] = useState(() => PanResponder.create({
    onMoveShouldSetPanResponderCapture: (_, g) => g.dx < -10 && Math.abs(g.dx) > Math.abs(g.dy) * 1.5,
    onPanResponderMove: (_, g) => progress.setValue(Math.max(0, Math.min(1, 1 + g.dx / w))),
    onPanResponderRelease: (_, g) => {
      const shut = g.dx < -w * 0.25 || g.vx < -0.5;
      settleDrawer(progress, !shut, reduced);
      if (shut) onClose();
    },
    onPanResponderTerminate: () => settleDrawer(progress, true, reduced),
  }));

  const translateX = progress.interpolate({ inputRange: [0, 1], outputRange: [-w - 24, 0] });
  const scrim = progress.interpolate({ inputRange: [0, 1], outputRange: [0, 1] });

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents={open ? 'auto' : 'box-none'}>
      <Animated.View pointerEvents={open ? 'auto' : 'none'} style={[StyleSheet.absoluteFill, styles.scrim, { opacity: scrim }]}>
        <MotionPressable
          onPress={() => { settleDrawer(progress, false, reduced); onClose(); }}
          accessibilityRole="button"
          accessibilityLabel={tr('Close history')}
          style={StyleSheet.absoluteFill}
        >
          <View />
        </MotionPressable>
      </Animated.View>

      <Animated.View
        {...pan.panHandlers}
        pointerEvents={open ? 'auto' : 'none'}
        style={[styles.panelWrap, { width: w, top: insets.top + 10, bottom: Math.max(insets.bottom, 10), transform: [{ translateX }] }]}
      >
        <Glass radius={radius.xl} style={styles.panel} intensity={90}>
          <View style={styles.head}>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">History</Txt>
              <Txt variant="bodyTight" tone="ink3">Swipe left to close.</Txt>
            </View>
            <MotionPressable
              onPress={() => { settleDrawer(progress, false, reduced); onClose(); }}
              hitSlop={10}
              accessibilityRole="button"
              accessibilityLabel={tr('Close history')}
              style={styles.close}
            >
              <XIcon size={19} color={color.ink2} />
            </MotionPressable>
          </View>

          <MotionPressable onPress={onNewChat} accessibilityRole="button" accessibilityLabel={tr('New chat')} style={styles.newChat}>
            <PlusIcon size={17} color={color.onAccent} />
            <Txt variant="action" tone={color.onAccent}>{tr('New chat')}</Txt>
          </MotionPressable>

          <ScrollView style={styles.scroll} contentContainerStyle={styles.list} showsVerticalScrollIndicator={false}>
            {/* Mounted only while open, so the shelves are always current. */}
            {open ? <HistoryLists onOpen={onClose} /> : null}
          </ScrollView>
        </Glass>
      </Animated.View>
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  scrim: { backgroundColor: 'rgba(0,0,0,0.42)' },
  panelWrap: { position: 'absolute', left: 10 },
  panel: { flex: 1, padding: gap[3], gap: gap[3] },
  head: { flexDirection: 'row', alignItems: 'center', gap: gap[3], paddingLeft: 6 },
  headText: { flex: 1, gap: 2 },
  close: { width: 42, height: 42, borderRadius: 21, alignItems: 'center', justifyContent: 'center', backgroundColor: color.raise },
  newChat: {
    minHeight: 48,
    borderRadius: radius.pill,
    backgroundColor: color.accent,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  scroll: { flex: 1 },
  list: { paddingBottom: gap[3] },
}));
