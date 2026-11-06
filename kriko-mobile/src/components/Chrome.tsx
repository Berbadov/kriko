import type { ReactNode } from 'react';
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  View,
  type LayoutChangeEvent,
  type ViewStyle,
} from 'react-native';
import { router, usePathname, type Href } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useStore } from '../engine/store';
import { tr } from '../i18n';
import { motion } from '../theme/motion';
import { HEADER_H, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { FileIcon, HistoryIcon, ScanIcon, SlidersIcon } from './Icon';
import { Wordmark } from './Logo';
import { Aurora } from './Aurora';
import { Fade, Glass, GlassProvider, GlassTarget } from './GlassLayer';
import { MotionPressable, MotionView, useReducedMotion } from './Motion';

export function HeaderAction({ onPress, children, label }: {
  onPress?: () => void; children: ReactNode; label: string;
}) {
  const styles = useStyles();
  return <MotionPressable onPress={onPress} accessibilityRole="button" accessibilityLabel={tr(label)} hitSlop={4}
    style={styles.action}>{children}</MotionPressable>;
}

/** The floating bar: brand, then the thread title when a chat is open. */
export function AppHeader({ actions, title }: { actions?: ReactNode; title?: string }) {
  const color = useColors();
  const styles = useStyles();
  return <Glass radius={HEADER_H / 2} style={styles.bar}>
    <View style={styles.barInner}>
      <View style={styles.brand}>
        <Wordmark height={17} tint={color.ink} />
        <View style={styles.brandRule} />
        <Txt variant={title ? 'rowTitle' : 'monoSm'} tone={title ? 'ink' : 'ink3'} numberOfLines={1}
          style={styles.brandNote}>{title || 'a closer look'}</Txt>
      </View>
      {actions ? <View style={styles.actions}>{actions}</View> : null}
    </View>
  </Glass>;
}

/* ---------------------------------------------------------------- frame -- */

type Insets = { top: number; bottom: number };
const InsetsContext = createContext<Insets>({ top: 0, bottom: 0 });

/** How far scrolling content must be padded to clear the floating bars. */
export function useFrameInsets(): Insets {
  return useContext(InsetsContext);
}

export function useKeyboardUp(): boolean {
  const [up, setUp] = useState(false);
  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', () => setUp(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setUp(false));
    return () => { show.remove(); hide.remove(); };
  }, []);
  return up;
}

/** Space between a floating bar and the screen's edge. */
export const FLOAT_GAP = 10;

/**
 * Every screen: content scrolls full-bleed and the header, whatever the screen
 * floats (`floating`) and the tab bar sit over it as frosted glass, so text
 * goes soft underneath instead of meeting a hard edge.
 */
export function Frame({ actions, title, banner, floating, overlay, nav = true, children }: {
  actions?: ReactNode; title?: string; banner?: ReactNode; floating?: ReactNode; overlay?: ReactNode;
  nav?: boolean; children: ReactNode;
}) {
  const insets = useSafeAreaInsets();
  const { access } = useStore();
  const keyboard = useKeyboardUp();
  const styles = useStyles();
  const [topH, setTopH] = useState(0);
  const [bottomH, setBottomH] = useState(0);
  const showNav = nav && access.kind !== 'none' && !keyboard;
  const seat = keyboard ? FLOAT_GAP : Math.max(insets.bottom, FLOAT_GAP);
  return <GlassProvider>
    <View style={styles.page}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <View style={styles.flex}>
          <GlassTarget style={StyleSheet.absoluteFill}>
            <Aurora />
            <InsetsContext.Provider value={{ top: topH, bottom: bottomH }}>{children}</InsetsContext.Provider>
          </GlassTarget>
          <Fade edge="top" height={insets.top + FLOAT_GAP + 22} />
          <Fade edge="bottom" height={seat + 26} />
          <View style={[styles.top, { paddingTop: insets.top + FLOAT_GAP }]}
            onLayout={(event) => setTopH(event.nativeEvent.layout.height)} pointerEvents="box-none">
            <AppHeader actions={actions} title={title} />
            {banner}
          </View>
          <View style={[styles.bottom, { paddingBottom: seat }]}
            onLayout={(event) => setBottomH(event.nativeEvent.layout.height)} pointerEvents="box-none">
            {floating}
            {showNav ? <BottomNav /> : null}
          </View>
          {overlay}
        </View>
      </KeyboardAvoidingView>
    </View>
  </GlassProvider>;
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

/** Where the tab indicator last rested, so a new screen slides it on from there. */
let lastIndicatorX: number | null = null;

export function BottomNav() {
  const pathname = usePathname();
  const { queueJobs } = useStore();
  const reduced = useReducedMotion();
  const color = useColors();
  const styles = useStyles();
  const [trackWidth, setTrackWidth] = useState(0);
  const [indicatorX] = useState(() => new Animated.Value(lastIndicatorX ?? 0));
  const positioned = useRef(false);
  const pending = queueJobs.filter((job) => job.status === 'queued' || job.status === 'running').length;
  const items = [
    { path: '/', label: 'Home', Icon: ScanIcon },
    { path: '/history', label: 'History', Icon: HistoryIcon },
    { path: '/queue', label: 'Queue', Icon: FileIcon },
    { path: '/settings', label: 'Settings', Icon: SlidersIcon },
  ];
  const activeIndex = Math.max(0, items.findIndex((item) => pathname === item.path));
  const slotWidth = trackWidth / items.length;
  useEffect(() => {
    if (!slotWidth) return;
    const target = activeIndex * slotWidth + (slotWidth - 52) / 2;
    const hadPrevious = lastIndicatorX !== null;
    lastIndicatorX = target;
    indicatorX.stopAnimation();
    const first = !positioned.current;
    positioned.current = true;
    // The very first mount of the app has nowhere to slide from.
    if (first && !hadPrevious) { indicatorX.setValue(target); return; }
    if (reduced !== false) { indicatorX.setValue(target); return; }
    Animated.spring(indicatorX, { toValue: target, ...motion.spring.morph }).start();
  }, [activeIndex, indicatorX, reduced, slotWidth]);
  const measureTrack = (event: LayoutChangeEvent) => setTrackWidth(event.nativeEvent.layout.width);
  return <Glass radius={32} style={styles.dock}>
    <View style={styles.navTrack} onLayout={measureTrack}>
      <Animated.View pointerEvents="none" style={[styles.navIndicator, { transform: [{ translateX: indicatorX }] }]} />
      {items.map(({ path, label, Icon }, index) => {
        const active = activeIndex === index;
        return <MotionPressable key={path} accessibilityRole="tab" accessibilityLabel={tr(label)}
          accessibilityState={{ selected: active }} onPress={() => { if (!active) router.replace(path as Href); }}
          style={styles.destination}>
          <View style={styles.navIcon}>
            <Icon size={20} color={active ? color.accent : color.ink3} strokeWidth={active ? 1.9 : 1.5} />
            {path === '/queue' && pending > 0 ? <View style={styles.count}>
              <Txt variant="monoSm" tone={color.onAccent} translate={false}>{pending}</Txt>
            </View> : null}
          </View>
          <Txt variant="actionSmall" tone={active ? 'accent' : 'ink3'}>{label}</Txt>
        </MotionPressable>;
      })}
    </View>
  </Glass>;
}

export function Page({ actions, footer, children, scroll = true, contentStyle, note, title }: {
  actions?: ReactNode; footer?: ReactNode; children: ReactNode; scroll?: boolean;
  artHeight?: number; contentStyle?: ViewStyle; note?: string; title?: string;
}) {
  const styles = useStyles();
  return <Frame actions={actions} title={title} floating={footer}
    banner={note ? <Glass radius={radius.l} style={styles.note}><Txt variant="mono" tone="ink2">{note}</Txt></Glass> : null}>
    <PageBody scroll={scroll} contentStyle={contentStyle}>{children}</PageBody>
  </Frame>;
}

function PageBody({ scroll, contentStyle, children }: { scroll: boolean; contentStyle?: ViewStyle; children: ReactNode }) {
  const styles = useStyles();
  const { top, bottom } = useFrameInsets();
  const pad = { paddingTop: top + 4, paddingBottom: bottom + 24 };
  return scroll
    ? <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, pad, contentStyle]}
      keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>{children}</ScrollView>
    : <View style={[styles.content, styles.flex, pad, contentStyle]}>{children}</View>;
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
  top: { position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: FLOAT_GAP, gap: 8 },
  bottom: { position: 'absolute', bottom: 0, left: 0, right: 0, paddingHorizontal: FLOAT_GAP, gap: 8 },
  bar: { height: HEADER_H },
  barInner: { flex: 1, paddingLeft: 18, paddingRight: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  brand: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 9 },
  brandRule: { width: 1, height: 15, backgroundColor: color.edgeStrong },
  brandNote: { flex: 1 },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 1 },
  action: { width: 42, height: 42, alignItems: 'center', justifyContent: 'center', borderRadius: radius.m },
  scroll: { flex: 1 }, content: {},
  hero: { paddingHorizontal: PAGE_X, paddingTop: 10, paddingBottom: 22 },
  crumb: { fontSize: 11, letterSpacing: 1.3 },
  heroTitle: { marginTop: 10 }, heroSub: { marginTop: 10, lineHeight: 22 },
  note: { paddingHorizontal: 16, paddingVertical: 10 },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: color.edge, marginVertical: 8 },
  footerSurface: { backgroundColor: color.surface, borderRadius: radius.l, borderWidth: 1, borderColor: color.edge, overflow: 'hidden' },
  dock: {},
  navTrack: { position: 'relative', flexDirection: 'row', minHeight: 62, paddingTop: 6, paddingHorizontal: 6 },
  navIndicator: { position: 'absolute', top: 6, left: 6, width: 52, height: 32, borderRadius: radius.m, backgroundColor: color.accentSoft },
  destination: { flex: 1, alignItems: 'center', gap: 3, minHeight: 52, zIndex: 1 },
  navIcon: { width: 52, height: 32, alignItems: 'center', justifyContent: 'center', borderRadius: radius.m },
  count: { position: 'absolute', top: -3, right: -2, minWidth: 17, height: 17, paddingHorizontal: 3,
    alignItems: 'center', justifyContent: 'center', borderRadius: radius.m, backgroundColor: color.accent },
}));
