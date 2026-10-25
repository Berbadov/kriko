import type { ReactNode } from 'react';
import { useEffect, useRef, useState } from 'react';
import { Animated, Keyboard, ScrollView, StyleSheet, View, type LayoutChangeEvent, type ViewStyle } from 'react-native';
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

export function BottomNav() {
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const { queueJobs } = useStore();
  const reduced = useReducedMotion();
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
    const target = activeIndex * slotWidth + (slotWidth - 48) / 2;
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
  return <View style={[styles.dock, { paddingBottom: Math.max(insets.bottom, 10) }]}>
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
  </View>;
}

export function Page({ actions, footer, children, scroll = true, contentStyle, note }: {
  actions?: ReactNode; footer?: ReactNode; children: ReactNode; scroll?: boolean;
  artHeight?: number; contentStyle?: ViewStyle; note?: string;
}) {
  const styles = useStyles();
  return <View style={styles.page}>
    <AppHeader actions={actions} />
    {note ? <View style={styles.note}><Txt variant="mono" tone="ink2">{note}</Txt></View> : null}
    {scroll ? <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, contentStyle]}
      keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>{children}</ScrollView>
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
  dock: { paddingHorizontal: 12, backgroundColor: color.ground, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: color.edge },
  navTrack: { position: 'relative', flexDirection: 'row', minHeight: 62, paddingTop: 8 },
  navIndicator: { position: 'absolute', top: 8, left: 0, width: 48, height: 30, borderRadius: 12, backgroundColor: color.accentSoft },
  destination: { flex: 1, alignItems: 'center', gap: 3, minHeight: 54, zIndex: 1 },
  navIcon: { width: 48, height: 30, alignItems: 'center', justifyContent: 'center', borderRadius: 12 },
  count: { position: 'absolute', top: -3, right: -2, minWidth: 17, height: 17, paddingHorizontal: 3,
    alignItems: 'center', justifyContent: 'center', borderRadius: 9, backgroundColor: color.accent },
}));
