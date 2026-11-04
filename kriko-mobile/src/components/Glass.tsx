/**
 * The glass surfaces: a frosted material drawn over the page with `expo-blur`.
 *
 * Two components, one material:
 * - `GlassCard` — an inline card (a rounded panel sitting on the page).
 * - `GlassBar`  — a chrome surface (the top app bar, the composer deck).
 *
 * Rules the rest of the app can rely on:
 * - The palette's `glass` colour is the tint *and* the fallback. If the platform
 *   cannot blur (no Android target, Android < 12, reduce-transparency, reduce-
 *   motion, or a caller forcing `solid`), the surface is still exactly the right
 *   colour — it simply stops being frosted.
 * - The blur layer is static: its intensity is never animated. Only the wrapper
 *   the caller animates may move, never the BlurView itself.
 * - It is never placed on a scrolling list item: a BlurView per row would
 *   allocate a blur target per row and re-blur on every scroll frame. Cards that
 *   scroll are `color.surface` panels; the app bar and floating chrome blur.
 *
 * Android needs `BlurTargetView`: wrap the content to blur in a
 * `BlurTargetView` (`expo-blur`) and pass its ref as `blurTarget`. One target
 * can serve several BlurViews as long as they all fit inside it. Without a
 * target the SDK silently falls back to a semi-transparent view, so this module
 * makes that fallback explicit (the palette fill).
 * Docs: https://docs.expo.dev/versions/v58.0.0/sdk/blur-view/
 */

import { BlurView } from 'expo-blur';
import type { ComponentRef, ReactNode, RefObject } from 'react';
import { useEffect, useState } from 'react';
import {
  AccessibilityInfo,
  Platform,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { radius as radii } from '../theme/tokens';
import { useTheme } from '../theme/theme';
import { useReducedMotion } from './Motion';

/** The ref type Android's `BlurView.blurTarget` expects. */
export type GlassTarget = RefObject<ComponentRef<typeof View> | null>;

/** Android RenderNode blur is stable from SDK 31 (Android 12). */
const ANDROID_BLUR_MIN_SDK = 31;

/**
 * Whether a real native blur can render here. Android additionally needs a
 * `BlurTargetView`; without its ref the native side falls back to `none`.
 *
 * This checks that a *ref object* was supplied rather than its current value:
 * a surface renders before the commit that attaches the ref, and a ref never
 * re-renders its owner, so reading `.current` at render time would permanently
 * latch the solid fallback on Android.
 */
export function canBlur(blurTarget?: GlassTarget): boolean {
  if (Platform.OS === 'android') {
    return Boolean(blurTarget) && Number(Platform.Version) >= ANDROID_BLUR_MIN_SDK;
  }
  // iOS ships a native blur view; the app does not target web.
  return Platform.OS === 'ios';
}

/**
 * The phone's "reduce transparency" setting (iOS only; elsewhere it is false).
 * Glass turns into its palette fill when this is on.
 */
export function useReducedTransparency(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (Platform.OS !== 'ios') return;
    let alive = true;
    AccessibilityInfo.isReduceTransparencyEnabled()
      .then((value) => {
        if (alive) setReduced(value);
      })
      .catch(() => {
        if (alive) setReduced(false);
      });
    const listener = AccessibilityInfo.addEventListener('reduceTransparencyChanged', (value) => {
      if (alive) setReduced(value);
    });
    return () => {
      alive = false;
      listener.remove();
    };
  }, []);
  return reduced;
}

export type GlassProps = {
  children?: ReactNode;
  style?: StyleProp<ViewStyle>;
  /** Corner radius. Defaults: `radius.l` for a card, `radius.m` for a bar. */
  radius?: number;
  /** Blur strength, 1–100. Moderate by default (50). Never animated. */
  intensity?: number;
  /** Hairline edge. `true`/`false` or an explicit width. Card: 1, bar: 0. */
  border?: boolean | number;
  borderColor?: string;
  /** The colour laid over the blur; also the whole surface when it cannot blur. */
  tint?: string;
  /** How strongly the palette tint sits over the blur (0–1). Defaults to 0.5. */
  tintOpacity?: number;
  /** Android: the content this surface samples. Omit for the solid fallback. */
  blurTarget?: GlassTarget;
  /** Force the palette fill with no blur layer. */
  solid?: boolean;
  /** Forwarded to the surface view; a bar over content usually wants `box-none`. */
  pointerEvents?: 'auto' | 'box-none' | 'box-only' | 'none';
  /** Padding for the children, so a card reads correctly without extra styles. */
  contentStyle?: StyleProp<ViewStyle>;
  accessible?: boolean;
  accessibilityLabel?: string;
  testID?: string;
};

function GlassSurface({
  children,
  style,
  radius = radii.m,
  intensity = 50,
  border = 0,
  borderColor,
  tint,
  tintOpacity = 0.5,
  blurTarget,
  solid = false,
  pointerEvents,
  contentStyle,
  accessible,
  accessibilityLabel,
  testID,
}: GlassProps) {
  const { color, dark } = useTheme();
  const reduceMotion = useReducedMotion();
  const reduceTransparency = useReducedTransparency();
  const fill = tint ?? color.glass;
  const edgeWidth = border === true ? 1 : border === false ? 0 : border;
  // Reduced motion also flattens glass: a still page has no material to sample.
  const frosted = !solid && reduceMotion === false && !reduceTransparency && canBlur(blurTarget);

  return (
    <View
      accessible={accessible}
      accessibilityLabel={accessibilityLabel}
      testID={testID}
      pointerEvents={pointerEvents}
      style={[
        styles.surface,
        { borderRadius: radius, borderWidth: edgeWidth, borderColor: borderColor ?? color.edge },
        style,
      ]}
    >
      {frosted ? (
        <BlurView
          // Static material: intensity is a mount-time value, never animated.
          intensity={intensity}
          tint={dark ? 'dark' : 'light'}
          blurMethod="dimezisBlurViewSdk31Plus"
          blurTarget={blurTarget}
          pointerEvents="none"
          style={StyleSheet.absoluteFill}
        />
      ) : null}
      <View
        pointerEvents="none"
        style={[
          StyleSheet.absoluteFill,
          { backgroundColor: fill, opacity: frosted ? tintOpacity : 1 },
        ]}
      />
      <View style={contentStyle}>{children}</View>
    </View>
  );
}

/** An inline frosted card: rounded, hairline edge, palette tint. */
export function GlassCard({ radius = radii.l, border = 1, ...rest }: GlassProps) {
  return <GlassSurface {...rest} radius={radius} border={border} />;
}

/** A chrome bar: the app bar, the composer deck. Rounded unless given a radius. */
export function GlassBar({ radius = radii.m, border = 0, ...rest }: GlassProps) {
  return <GlassSurface {...rest} radius={radius} border={border} />;
}

const styles = StyleSheet.create({
  surface: { backgroundColor: 'transparent', overflow: 'hidden' },
});
