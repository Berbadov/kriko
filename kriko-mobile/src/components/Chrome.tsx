import type { ReactNode } from 'react';
import { useEffect, useRef, useState } from 'react';
import {
  Animated, Easing, Keyboard, ScrollView, StyleSheet, View,
  type LayoutChangeEvent, type NativeScrollEvent, type NativeSyntheticEvent, type ViewStyle,
} from 'react-native';
import { router, usePathname, type Href } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useStore } from '../engine/store';
import { tr } from '../i18n';
import { motion } from '../theme/motion';
import { HEADER_H, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { useDock } from './dock';
import { FileIcon, HistoryIcon, ScanIcon, SlidersIcon } from './Icon';
import { Wordmark } from './Logo';
import { MotionPressable, MotionView, useReducedMotion } from './Motion';

export function HeaderAction({ onPress, children, label }: {
  onPress?: () => void; children: ReactNode; label: string;
}) {
  const styles = useStyles();
  return <MotionPressable onPress={onPress} accessibilityRole="button" accessibilityLabel={tr(label)} hitSlop={4}
    style={styles.action}>{children}</MotionPressable>;
}

export function AppHeader({ actions }: { actions?: ReactNode; transparent?: boolean }) {
  const insets = useSafeAreaInsets();
  const color = useColors();
  const styles = useStyles();
  return <View style={[styles.bar, { paddingTop: insets.top }]}>
    <View style={styles.barInner}>
      <View style={styles.brand}>
        <Wordmark height={18} tint={color.ink} />
        <View style={styles.brandRule} />
        <Txt variant="monoSm" tone="ink3">a closer look</Txt>
      </View>
      {actions ? <View style={styles.actions}>{actions}</View> : null}
    </View>
  </View>;
}

/** Kept for older callers; the paper redesign has no decorative hero image. */
export function HeroArt(_props: { height?: number }) { return null; }

export function Hero({ crumb, title, subtitle }: { crumb: string; title: string; subtitle?: string }) {
  const styles = useStyles();
  return <MotionView style={styles.hero}>
    <Txt variant="crumb" tone="ink3" caps style={styles.crumb}>{crumb.replace('kriko / ', '')}</Txt>
    <Txt variant="headline" style={styles.heroTitle}>{title}</Txt>
    {subtitle ? <Txt variant="heroSub" tone="ink2" style={styles.heroSub}>{subtitle}</Txt> : null}
  </MotionView>;
}

/** The bar's own height; the safe-area inset sits under it. */
const DOCK_H = 46;
const PILL_H = 34;
/** Space left either side of the active pill inside its slot. */
const PILL_INSET = 6;

/** The active destination's name, easing in beside its icon. */
function DockLabel({ text }: { text: string }) {
  const reduced = useReducedMotion();
  const [progress] = useState(() => new Animated.Value(0));
  useEffect(() => {
    progress.stopAnimation();
    if (reduced !== false) {
      progress.setValue(1);
      return undefined;
    }
    const animation = Animated.timing(progress, {
      toValue: 1,
      duration: motion.duration.standard,
      delay: 50,
      easing: Easing.bezier(...motion.easing.enter),
      useNativeDriver: true,
    });
    animation.start();
    return () => animation.stop();
  }, [progress, reduced]);
  return <Animated.View style={{
    opacity: progress,
    transform: [{ translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [-5, 0] }) }],
  }}>
    <Txt variant="actionSmall" tone="accent" numberOfLines={1}>{text}</Txt>
  </Animated.View>;
}

/**
 * A slim bar: icons only, with the open one named inside its pill. It gives its
 * space back while the reader moves down through text (`dock.tsx`) and returns
 * on the first move up.
 */
export function BottomNav() {
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const { queueJobs } = useStore();
  const reduced = useReducedMotion();
  const dock = useDock();
  const color = useColors();
  const styles = useStyles();
  const [keyboard, setKeyboard] = useState(false);
  const [trackWidth, setTrackWidth] = useState(0);
  const [indicatorX] = useState(() => new Animated.Value(0));
  const positioned = useRef(false);
  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', () => setKeyboard(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKeyboard(false));
    return () => { show.remove(); hide.remove(); };
  }, []);
  // A new screen starts with the bar in view, whatever the last one did.
  useEffect(() => { dock.show(); }, [pathname, dock]);
  const pending = queueJobs.filter((job) => job.status === 'queued' || job.status === 'running').length;
  const items = [
    { path: '/', label: 'Home', Icon: ScanIcon },
    { path: '/history', label: 'History', Icon: HistoryIcon },
    { path: '/queue', label: 'Queue', Icon: FileIcon },
    { path: '/settings', label: 'Settings', Icon: SlidersIcon },
  ];
  const activeIndex = Math.max(0, items.findIndex((item) => pathname === item.path));
  const slotWidth = trackWidth / items.length;
  const pillWidth = Math.max(0, slotWidth - PILL_INSET * 2);
  useEffect(() => {
    if (!slotWidth) return;
    const target = activeIndex * slotWidth + PILL_INSET;
    indicatorX.stopAnimation();
    if (!positioned.current) {
      indicatorX.setValue(target);
      positioned.current = true;
      return;
    }
    if (reduced !== false) {
      indicatorX.setValue(target);
      return;
    }
    Animated.spring(indicatorX, { toValue: target, ...motion.spring.morph }).start();
  }, [activeIndex, indicatorX, reduced, slotWidth]);
  const measureTrack = (event: LayoutChangeEvent) => setTrackWidth(event.nativeEvent.layout.width);
  if (keyboard) return null;
  const bottomPad = Math.max(insets.bottom, 6);
  const full = DOCK_H + bottomPad;
  // Gone, the bar still leaves the gesture bar's own height below the page, so
  // the composer never sits under the system's home indicator.
  return <Animated.View style={{
    height: dock.progress.interpolate({ inputRange: [0, 1], outputRange: [insets.bottom, full] }),
    opacity: dock.progress,
    overflow: 'hidden',
  }}>
    <View style={[styles.dock, { height: full, paddingBottom: bottomPad }]}>
      <View style={styles.navTrack} onLayout={measureTrack}>
        <Animated.View pointerEvents="none"
          style={[styles.navIndicator, { width: pillWidth, transform: [{ translateX: indicatorX }] }]} />
        {items.map(({ path, label, Icon }, index) => {
          const active = activeIndex === index;
          return <MotionPressable key={path} accessibilityRole="tab" accessibilityLabel={tr(label)}
            accessibilityState={{ selected: active }} onPress={() => { if (!active) router.replace(path as Href); }}
            style={styles.destination}>
            <View style={styles.navIcon}>
              <Icon size={21} color={active ? color.accent : color.ink3} strokeWidth={active ? 1.9 : 1.5} />
              {path === '/queue' && pending > 0 ? <View style={styles.count}>
                <Txt variant="monoSm" tone={color.onAccent} translate={false}>{pending}</Txt>
              </View> : null}
            </View>
            {active ? <DockLabel text={label} /> : null}
          </MotionPressable>;
        })}
      </View>
    </View>
  </Animated.View>;
}

export function Page({ actions, footer, children, scroll = true, contentStyle, note }: {
  actions?: ReactNode; footer?: ReactNode; children: ReactNode; scroll?: boolean;
  artHeight?: number; contentStyle?: ViewStyle; note?: string;
}) {
  const styles = useStyles();
  const dock = useDock();
  const onScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, layoutMeasurement, contentSize } = event.nativeEvent;
    dock.report({ offset: contentOffset.y, viewport: layoutMeasurement.height, content: contentSize.height });
  };
  return <View style={styles.page}>
    <AppHeader actions={actions} />
    {note ? <View style={styles.note}><Txt variant="mono" tone="ink2">{note}</Txt></View> : null}
    {scroll ? <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, contentStyle]}
      keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}
      scrollEventThrottle={16} onScroll={onScroll}>{children}</ScrollView>
      : <View style={[styles.content, styles.flex, contentStyle]}>{children}</View>}
    {footer ? <View style={styles.footer}>{footer}</View> : null}
  </View>;
}

export function Divider({ inset = 0 }: { inset?: number }) {
  const styles = useStyles();
  return <View style={[styles.divider, { marginLeft: inset }]} />;
}
export function FooterSurface({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  const styles = useStyles();
  return <View style={[styles.footerSurface, style]}>{children}</View>;
}

const useStyles = makeStyles((color) => StyleSheet.create({
  page: { flex: 1, backgroundColor: color.ground }, flex: { flex: 1 },
  bar: { backgroundColor: color.ground, zIndex: 2 },
  barInner: { height: HEADER_H, paddingHorizontal: PAGE_X, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  brandRule: { width: 1, height: 15, backgroundColor: color.edgeStrong },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 1 },
  action: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radius.m },
  scroll: { flex: 1 }, content: { paddingBottom: 28 },
  hero: { paddingHorizontal: PAGE_X, paddingTop: 18, paddingBottom: 26 },
  crumb: { fontSize: 11, letterSpacing: 1.3 },
  heroTitle: { marginTop: 10 }, heroSub: { marginTop: 10, maxWidth: 320, lineHeight: 22 },
  footer: { paddingHorizontal: PAGE_X, paddingTop: 12, paddingBottom: 12, backgroundColor: color.ground },
  note: { paddingHorizontal: PAGE_X, paddingVertical: 8 },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: color.edge, marginVertical: 8 },
  footerSurface: { backgroundColor: color.surface, borderRadius: radius.l, borderWidth: 1, borderColor: color.edge, overflow: 'hidden' },
  dock: { position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: 12, backgroundColor: color.ground,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: color.edge },
  navTrack: { position: 'relative', flexDirection: 'row', height: DOCK_H },
  navIndicator: { position: 'absolute', top: (DOCK_H - PILL_H) / 2, left: 0, height: PILL_H,
    borderRadius: PILL_H / 2, backgroundColor: color.accentSoft },
  destination: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    height: DOCK_H, zIndex: 1 },
  navIcon: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  count: { position: 'absolute', top: -5, right: -7, minWidth: 16, height: 16, paddingHorizontal: 3,
    alignItems: 'center', justifyContent: 'center', borderRadius: 8, backgroundColor: color.accent },
}));
