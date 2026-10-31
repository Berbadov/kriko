import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import {
  Animated, Keyboard, ScrollView, StyleSheet, View,
   type NativeScrollEvent, type NativeSyntheticEvent, type ViewStyle,
} from 'react-native';
import { router, usePathname, type Href } from 'expo-router';
import { House } from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useStore } from '../engine/store';
import { updateNeedsAttention } from '../engine/updatecore';
import { useAppUpdate } from '../engine/updater';
import { tr } from '../i18n';
import { HEADER_H, PAGE_X, radius, TITLE_BAR_H } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { useDock } from './dock';
import { HistoryIcon, SlidersIcon } from './Icon';
import { Wordmark } from './Logo';
import { MotionPressable, MotionView } from './Motion';

export function HeaderAction({ onPress, children, label }: {
  onPress?: () => void; children: ReactNode; label: string;
}) {
  const styles = useStyles();
  return <MotionPressable onPress={onPress} accessibilityRole="button" accessibilityLabel={tr(label)} hitSlop={4}
    style={styles.action}>{children}</MotionPressable>;
}

/**
 * The top bar. With a `title` (an open conversation) it is one slim row that
 * names the thread; without, the brand. It leaves with the bottom bar while the
 * reader moves down through text and returns with it; the status bar's own
 * height stays, so nothing slides under the clock.
 */
export function AppHeader({ actions, title }: { actions?: ReactNode; title?: string; transparent?: boolean }) {
  const insets = useSafeAreaInsets();
  const dock = useDock();
  const color = useColors();
  const styles = useStyles();
  const full = title !== undefined ? TITLE_BAR_H : HEADER_H;
  return <Animated.View style={[styles.bar, {
    height: dock.progress.interpolate({ inputRange: [0, 1], outputRange: [insets.top, insets.top + full] }),
    opacity: dock.progress,
  }]}>
    <View style={{ paddingTop: insets.top }}>
      <View style={[styles.barInner, { height: full }]}>
        {title !== undefined
          ? <Txt variant="rowTitle" tone="ink" numberOfLines={1} style={styles.barTitle}>{title}</Txt>
          : <View style={styles.brand}><Wordmark height={18} tint={color.ink} /></View>}
        {actions ? <View style={styles.actions}>{actions}</View> : null}
      </View>
    </View>
  </Animated.View>;
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

/** Normal-flow navigation: no absolute positioning or animated clipping bounds. */
export function BottomNav() {
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const { newChat } = useStore();
  const dock = useDock();
  const color = useColors();
  const styles = useStyles();
  const update = updateNeedsAttention(useAppUpdate());
  const [keyboard, setKeyboard] = useState(false);
  useEffect(() => {
    const shown = Keyboard.addListener('keyboardDidShow', () => setKeyboard(true));
    const hidden = Keyboard.addListener('keyboardDidHide', () => setKeyboard(false));
    return () => { shown.remove(); hidden.remove(); };
  }, []);
  useEffect(() => { dock.show(); }, [pathname, dock]);
  const items = [
    { path: '/', label: 'Home', Icon: House },
    { path: '/history', label: 'History', Icon: HistoryIcon },
    { path: '/settings', label: 'Settings', Icon: SlidersIcon },
  ];
  if (keyboard || pathname === '/assist') return null;
  return <View style={[styles.navigation, { paddingBottom: Math.max(insets.bottom, 8) }]}>
    <View style={styles.navTrack} accessibilityRole="tablist">
      {items.map(({ path, label, Icon }) => {
        const selected = path === '/' ? pathname === '/' : pathname.startsWith(path);
        return <MotionPressable key={path} accessibilityRole="tab" accessibilityLabel={tr(label)}
          accessibilityState={{ selected }} style={styles.destination}
          onPress={() => { dock.endCompose(); if (path === '/') newChat(); router.replace(path as Href); }}>
          <View style={styles.navIcon}>
            <Icon size={21} color={selected ? color.ink : color.ink3} strokeWidth={selected ? 1.9 : 1.5} />
            {path === '/settings' && update ? <View style={styles.updateDot} /> : null}
          </View>
          <Txt variant="monoSm" tone={selected ? 'ink' : 'ink3'} numberOfLines={1}>{label}</Txt>
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
  bar: { backgroundColor: color.ground, zIndex: 2, overflow: 'hidden' },
  barInner: { paddingHorizontal: PAGE_X, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  barTitle: { flex: 1 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 9 },
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
  navigation: { flexShrink: 0, paddingTop: 4, paddingHorizontal: PAGE_X, backgroundColor: color.ground },
  navTrack: { flexDirection: 'row', minHeight: 52, alignItems: 'center' },
  destination: { flex: 1, minHeight: 52, minWidth: 44, alignItems: 'center', justifyContent: 'center', gap: 3 },
  navIcon: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  updateDot: { position: 'absolute', top: -2, right: -3, width: 9, height: 9, borderRadius: 5,
    backgroundColor: color.accent, borderWidth: 1.5, borderColor: color.ground },
  count: { position: 'absolute', top: -5, right: -7, minWidth: 16, height: 16, paddingHorizontal: 3,
    alignItems: 'center', justifyContent: 'center', borderRadius: 8, backgroundColor: color.accent },
}));
