import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { Keyboard, ScrollView, StyleSheet, View, type ViewStyle } from 'react-native';
import { router, usePathname, type Href } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useStore } from '../engine/store';
import { color, HEADER_H, PAGE_X, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { FileIcon, HistoryIcon, ScanIcon, SlidersIcon } from './Icon';
import { Wordmark } from './Logo';
import { MotionPressable, MotionView } from './Motion';

export function HeaderAction({ onPress, children, label }: {
  onPress?: () => void; children: ReactNode; label: string;
}) {
  return <MotionPressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} hitSlop={4}
    style={styles.action}>{children}</MotionPressable>;
}

export function AppHeader({ actions }: { actions?: ReactNode; transparent?: boolean }) {
  const insets = useSafeAreaInsets();
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
  return <MotionView style={styles.hero}>
    <Txt variant="crumb" tone="ink3" style={styles.crumb}>{crumb.replace('kriko / ', '')}</Txt>
    <Txt variant="headline" style={styles.heroTitle}>{title}</Txt>
    {subtitle ? <Txt variant="heroSub" tone="ink2" style={styles.heroSub}>{subtitle}</Txt> : null}
  </MotionView>;
}

export function BottomNav() {
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const { queueJobs } = useStore();
  const [keyboard, setKeyboard] = useState(false);
  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', () => setKeyboard(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKeyboard(false));
    return () => { show.remove(); hide.remove(); };
  }, []);
  if (keyboard) return null;
  const pending = queueJobs.filter((job) => job.status === 'queued' || job.status === 'running').length;
  const items = [
    { path: '/', label: 'Home', Icon: ScanIcon },
    { path: '/history', label: 'History', Icon: HistoryIcon },
    { path: '/queue', label: 'Queue', Icon: FileIcon },
    { path: '/settings', label: 'Settings', Icon: SlidersIcon },
  ];
  return <View style={[styles.dock, { paddingBottom: Math.max(insets.bottom, 10) }]}>
    {items.map(({ path, label, Icon }) => {
      const active = pathname === path;
      return <MotionPressable key={path} accessibilityRole="tab" accessibilityLabel={label}
        accessibilityState={{ selected: active }} onPress={() => { if (!active) router.replace(path as Href); }}
        style={styles.destination}>
        <View style={[styles.navIcon, active && styles.navIconActive]}>
          <Icon size={20} color={active ? color.accent : color.ink3} strokeWidth={active ? 1.9 : 1.5} />
          {path === '/queue' && pending > 0 ? <View style={styles.count}>
            <Txt variant="monoSm" tone="#FFFFFF" translate={false}>{pending}</Txt>
          </View> : null}
        </View>
        <Txt variant="actionSmall" tone={active ? 'accent' : 'ink3'}>{label}</Txt>
      </MotionPressable>;
    })}
  </View>;
}

export function Page({ actions, footer, children, scroll = true, contentStyle, note }: {
  actions?: ReactNode; footer?: ReactNode; children: ReactNode; scroll?: boolean;
  artHeight?: number; contentStyle?: ViewStyle; note?: string;
}) {
  return <View style={styles.page}>
    <AppHeader actions={actions} />
    {note ? <View style={styles.note}><Txt variant="mono" tone="ink2">{note}</Txt></View> : null}
    {scroll ? <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, contentStyle]}
      keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>{children}</ScrollView>
      : <View style={[styles.content, styles.flex, contentStyle]}>{children}</View>}
    {footer ? <View style={styles.footer}>{footer}</View> : null}
    <BottomNav />
  </View>;
}

export function Divider({ inset = 0 }: { inset?: number }) {
  return <View style={[styles.divider, { marginLeft: inset }]} />;
}
export function FooterSurface({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[styles.footerSurface, style]}>{children}</View>;
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: color.ground }, flex: { flex: 1 },
  bar: { backgroundColor: color.ground, zIndex: 2 },
  barInner: { height: HEADER_H, paddingHorizontal: PAGE_X, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  brandRule: { width: 1, height: 15, backgroundColor: color.edgeStrong },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 1 },
  action: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radius.m },
  scroll: { flex: 1 }, content: { paddingBottom: 28 },
  hero: { paddingHorizontal: PAGE_X, paddingTop: 18, paddingBottom: 26 },
  crumb: { fontSize: 11, letterSpacing: 1.3, textTransform: 'uppercase' },
  heroTitle: { marginTop: 10 }, heroSub: { marginTop: 10, maxWidth: 320, lineHeight: 22 },
  footer: { paddingHorizontal: PAGE_X, paddingTop: 12, paddingBottom: 12, backgroundColor: color.ground },
  note: { paddingHorizontal: PAGE_X, paddingVertical: 8 },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: color.edge, marginVertical: 8 },
  footerSurface: { backgroundColor: color.surface, borderRadius: radius.l, borderWidth: 1, borderColor: color.edge, overflow: 'hidden' },
  dock: { flexDirection: 'row', paddingTop: 8, paddingHorizontal: 12, backgroundColor: color.ground, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: color.edge },
  destination: { flex: 1, alignItems: 'center', gap: 3, minHeight: 54 },
  navIcon: { width: 48, height: 30, alignItems: 'center', justifyContent: 'center', borderRadius: 12 },
  navIconActive: { backgroundColor: color.accentSoft },
  count: { position: 'absolute', top: -3, right: -2, minWidth: 17, height: 17, paddingHorizontal: 3,
    alignItems: 'center', justifyContent: 'center', borderRadius: 9, backgroundColor: color.accent },
});
