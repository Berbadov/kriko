/**
 * Frosted glass for the bars that float over the scrolling text.
 *
 * Android blurs only what sits inside a `BlurTargetView`, so one target wraps
 * the screen's content and every `Glass` (header, composer, tab bar) reads it
 * through context. A glass element must be a sibling of the target, never a
 * child of it: a surface cannot blur itself.
 */

import { BlurTargetView, BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import {
  createContext,
  useContext,
  useRef,
  type ReactNode,
  type RefObject,
} from 'react';
import { StyleSheet, View, type HostInstance, type StyleProp, type ViewStyle } from 'react-native';

import { useTheme } from '../theme/theme';

const TargetContext = createContext<RefObject<HostInstance | null> | null>(null);

/** Owns the blur target's ref so glass and content can share it. */
export function GlassProvider({ children }: { children: ReactNode }) {
  const target = useRef<HostInstance | null>(null);
  return <TargetContext.Provider value={target}>{children}</TargetContext.Provider>;
}

/** The layer that gets blurred. Wrap the scrolling content in this. */
export function GlassTarget({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const target = useContext(TargetContext);
  return <BlurTargetView ref={target ?? undefined} style={style}>{children}</BlurTargetView>;
}

/** `#rrggbb` + alpha → `rgba(...)`, for fades that must end in the same hue. */
export function withAlpha(hex: string, alpha: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) return hex;
  const value = parseInt(match[1], 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

/** The blur and its veil, filling whatever rounded, clipped parent holds it. */
export function GlassFill({ intensity = 80 }: { intensity?: number }) {
  const { dark, color } = useTheme();
  const target = useContext(TargetContext);
  return (
    <>
      <BlurView
        blurTarget={target ?? undefined}
        blurMethod="dimezisBlurView"
        intensity={intensity}
        tint={dark ? 'dark' : 'light'}
        style={StyleSheet.absoluteFill}
      />
      <View
        pointerEvents="none"
        style={[StyleSheet.absoluteFill, { backgroundColor: withAlpha(color.ground, dark ? 0.55 : 0.62) }]}
      />
    </>
  );
}

/** A rounded floating pane of frosted glass. */
export function Glass({
  children,
  radius = 26,
  style,
  intensity,
}: {
  children?: ReactNode;
  radius?: number;
  style?: StyleProp<ViewStyle>;
  intensity?: number;
}) {
  const { color } = useTheme();
  return (
    <View
      style={[
        {
          borderRadius: radius,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: color.edgeStrong,
          overflow: 'hidden',
        },
        style,
      ]}
    >
      <GlassFill intensity={intensity} />
      {children}
    </View>
  );
}

/** A band that fades the page colour out, so text dissolves before the glass. */
export function Fade({ edge, height }: { edge: 'top' | 'bottom'; height: number }) {
  const { color } = useTheme();
  const solid = withAlpha(color.ground, 0.92);
  const clear = withAlpha(color.ground, 0);
  return (
    <LinearGradient
      pointerEvents="none"
      colors={edge === 'top' ? [solid, clear] : [clear, solid]}
      style={[styles.fade, edge === 'top' ? { top: 0 } : { bottom: 0 }, { height }]}
    />
  );
}

const styles = StyleSheet.create({
  fade: { position: 'absolute', left: 0, right: 0 },
});
