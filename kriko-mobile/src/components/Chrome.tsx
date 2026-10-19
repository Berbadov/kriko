/**
 * The page chrome: the blue app bar, the ground, the hero art and the footer.
 *
 * Every screen is built from these, so the bar height, the page margin and the
 * place the dithered art sits are decided once.
 */

import { BlurView } from 'expo-blur';
import { Image } from 'expo-image';
import type { ReactNode } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, View, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { color, HEADER_H, PAGE_X, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { Logo } from './Logo';

export function HeaderAction({
  onPress,
  children,
  label,
}: {
  onPress?: () => void;
  children: ReactNode;
  label: string;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={10}
      style={({ pressed }) => [styles.action, pressed && styles.actionPressed]}
    >
      {children}
    </Pressable>
  );
}

export function AppHeader({ actions }: { actions?: ReactNode }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.bar, { paddingTop: insets.top }]}>
      <View style={styles.barInner}>
        <Logo />
        {actions ? <View style={styles.actions}>{actions}</View> : null}
      </View>
    </View>
  );
}

/** The dot-matrix blue field, pinned to the top right of a page. */
export function HeroArt({ height = 250 }: { height?: number }) {
  if (height <= 0) return null;
  return (
    <Image
      source={require('../assets/hero-texture.png')}
      style={[styles.art, { height }]}
      contentFit="cover"
      contentPosition="right top"
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    />
  );
}

/**
 * Breadcrumb, display title and one line of explanation. The title uses the
 * condensed display face; the capture solves "SET UP" at 42 px.
 */
export function Hero({
  crumb,
  title,
  subtitle,
}: {
  crumb: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <View style={styles.hero}>
      <Txt variant="crumb" tone="ink3">
        {crumb}
      </Txt>
      <Txt variant="display" tone="ink" caps style={styles.heroTitle}>
        {title}
      </Txt>
      {subtitle ? (
        <Txt variant="heroSub" tone="ink2" style={styles.heroSub}>
          {subtitle}
        </Txt>
      ) : null}
    </View>
  );
}

export function Page({
  actions,
  footer,
  children,
  scroll = true,
  artHeight = 250,
  contentStyle,
}: {
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  scroll?: boolean;
  artHeight?: number;
  contentStyle?: ViewStyle;
}) {
  const insets = useSafeAreaInsets();
  const body = (
    <>
      <HeroArt height={artHeight} />
      {children}
    </>
  );

  return (
    <View style={styles.page}>
      <AppHeader actions={actions} />
      <View accessibilityRole="summary" style={{ paddingHorizontal: PAGE_X, paddingVertical: 8, backgroundColor: color.ground }}>
        <Txt variant="mono" tone="ink2">PROTOTYPE · Example research and simulated image reading. No live sources.</Txt>
      </View>
      {scroll ? (
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[styles.content, contentStyle]}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {body}
        </ScrollView>
      ) : (
        <View style={[styles.content, styles.flex, contentStyle]}>{body}</View>
      )}
      {footer ? (
        <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, 12) }]}>
          {Platform.OS === 'android' ? <View style={styles.footerScrim} /> : null}
          {footer}
        </View>
      ) : (
        <View style={{ height: insets.bottom }} />
      )}
    </View>
  );
}

/** A hairline used between rows inside a card. */
export function Divider({ inset = 0 }: { inset?: number }) {
  return <View style={[styles.divider, { marginLeft: inset }]} />;
}

/** A sheet surface used above the composer. */
export function FooterSurface({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return (
    <View style={[styles.footerSurface, style]}>
      {Platform.OS === 'ios' ? (
        <BlurView intensity={30} tint="dark" style={StyleSheet.absoluteFill} />
      ) : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: color.ground },
  flex: { flex: 1 },
  bar: { backgroundColor: color.accent, zIndex: 2 },
  barInner: {
    height: HEADER_H,
    paddingHorizontal: PAGE_X,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  action: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.pill,
  },
  actionPressed: { backgroundColor: 'rgba(255,255,255,0.16)' },
  scroll: { flex: 1 },
  content: { paddingBottom: 28 },
  art: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    opacity: 0.95,
  },
  hero: { paddingHorizontal: PAGE_X, paddingTop: 22, paddingBottom: 22 },
  heroTitle: { marginTop: 9 },
  heroSub: { marginTop: 12, maxWidth: 330 },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: color.edge },
  footer: {
    paddingHorizontal: PAGE_X,
    paddingTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edgeSoft,
    backgroundColor: color.ground,
  },
  footerScrim: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: color.ground,
  },
  footerSurface: {
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.surface,
    overflow: 'hidden',
  },
});
