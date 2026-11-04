import type { ComponentRef, ReactNode } from 'react';
import { useEffect, useRef, useState } from 'react';
import {
  Animated, Keyboard, ScrollView, StyleSheet, View,
   type NativeScrollEvent, type NativeSyntheticEvent, type ViewStyle,
} from 'react-native';
import { router, usePathname, type Href } from 'expo-router';
import { BlurTargetView } from 'expo-blur';
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
import { GlassBar, type GlassTarget } from './Glass';
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
 * The top bar: a glass strip over the page. With a `title` (an open
 * conversation) it is one slim row that names the thread; without, the brand.
 * It leaves with the bottom bar while the reader moves down through text and
 * returns with it; the status bar's own height stays, so nothing slides under
 * the clock.
 *
 * `overlay` puts the bar absolutely on top of the page (used by `Page`), so the
 * page content scrolls underneath it and the glass has something to blur. Pass
 * `blurTarget` (a `BlurTargetView` ref wrapping that content) for Android to
 * render a real blur; without it Android shows the palette glass fill.
 */
export function AppHeader({
  actions,
  title,
  overlay = false,
  blurTarget,
}: {
  actions?: ReactNode;
  title?: string;
  /** Kept for older callers; the glass bar is translucent by default now. */
  transparent?: boolean;
  overlay?: boolean;
  blurTarget?: GlassTarget;
}) {
  const insets = useSafeAreaInsets();
  const dock = useDock();
  const color = useColors();
  const styles = useStyles();
  const full = title !== undefined ? TITLE_BAR_H : HEADER_H;
  // The glass is expensive while it is not being looked at: a faded-out bar
  // still blurs every scrolling frame. Track the dock's own animation and drop
  // the blur layer once the bar has fully left.
  const [revealed, setRevealed] = useState(true);
  useEffect(() => {
    const id = dock.progress.addListener(({ value }) => {
      const next = value > 0.01;
      setRevealed((current) => (current === next ? current : next));
    });
    return () => dock.progress.removeListener(id);
  }, [dock.progress]);
  // Overlay bars leave by sliding up (transform only); an in-flow bar has to
  // give its height back to the page, so it collapses instead.
  const presence = overlay
    ? {
        height: insets.top + full,
        opacity: dock.progress,
        transform: [
          { translateY: dock.progress.interpolate({ inputRange: [0, 1], outputRange: [-full, 0] }) },
        ],
      }
    : {
        height: dock.progress.interpolate({ inputRange: [0, 1], outputRange: [insets.top, insets.top + full] }),
        opacity: dock.progress,
      };
  return <Animated.View pointerEvents="box-none" style={[styles.bar, overlay && styles.barOverlay, presence]}>
    <GlassBar
      blurTarget={revealed ? blurTarget : undefined}
      solid={!revealed}
      pointerEvents="box-none"
      radius={0}
      intensity={55}
      // Readable over long answers in every palette: the blur tint plus this
      // fill land around 0.86–0.91 opacity, at least the composer deck's 0.85.
      tintOpacity={0.8}
      style={StyleSheet.absoluteFill}
    />
    <View pointerEvents="none" style={styles.hairline} />
    <View pointerEvents="box-none" style={{ paddingTop: insets.top }}>
      <View pointerEvents="box-none" style={[styles.barInner, { height: full }]}>
        {title !== undefined
          ? <Txt variant="cardTitle" tone="ink" numberOfLines={1} style={styles.barTitle}>{title}</Txt>
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

/**
 * A scrolling page under the glass bar. The bar is drawn over the content (so
 * the content scrolls underneath it, which is what the glass blurs); the scroll
 * body is padded by the bar's own height so nothing starts hidden under it.
 * On Android the body is wrapped in a `BlurTargetView` and its ref handed to
 * the bar; on iOS the bar blurs the page directly.
 */
export function Page({ actions, footer, children, scroll = true, contentStyle, note }: {
  actions?: ReactNode; footer?: ReactNode; children: ReactNode; scroll?: boolean;
  artHeight?: number; contentStyle?: ViewStyle; note?: string;
}) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const dock = useDock();
  const blurTarget = useRef<ComponentRef<typeof View>>(null);
  const onScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, layoutMeasurement, contentSize } = event.nativeEvent;
    dock.report({ offset: contentOffset.y, viewport: layoutMeasurement.height, content: contentSize.height });
  };
  const topPad = { paddingTop: insets.top + HEADER_H };
  return <View style={styles.page}>
    <BlurTargetView ref={blurTarget} style={styles.flex}>
      {scroll ? <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, topPad, contentStyle]}
        keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}
        scrollEventThrottle={16} onScroll={onScroll}>
        {note ? <View style={styles.note}><Txt variant="mono" tone="ink2">{note}</Txt></View> : null}
        {children}
      </ScrollView>
        : <View style={[styles.content, styles.flex, topPad, contentStyle]}>
          {note ? <View style={styles.note}><Txt variant="mono" tone="ink2">{note}</Txt></View> : null}
          {children}
        </View>}
    </BlurTargetView>
    <AppHeader actions={actions} overlay blurTarget={blurTarget} />
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
  // The glass bar paints itself; the host only owns the animated height, the
  // clipping and the stacking. Transparent so the blur can sample the page.
  bar: { backgroundColor: 'transparent', zIndex: 2, overflow: 'hidden' },
  barOverlay: { position: 'absolute', top: 0, left: 0, right: 0 },
  hairline: { position: 'absolute', left: 0, right: 0, bottom: 0,
    height: StyleSheet.hairlineWidth, backgroundColor: color.edge },
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
