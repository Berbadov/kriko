/**
 * The primitives every screen draws with.
 *
 * Sizes come from the captures: cards are a 358 px wide surface with a 20 px
 * corner and a 16 px inset, actions are 48 px tall, and the toggle is the 45 px
 * square with the knob that overhangs its right edge.
 */

import * as Haptics from 'expo-haptics';
import { useEffect, useState, type ReactNode } from 'react';
import { Animated, Easing, Pressable, StyleSheet, View, type TextStyle, type ViewStyle } from 'react-native';

import { color, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';

/* ------------------------------------------------------------------ card -- */

export function Card({
  children,
  style,
  tone = 'surface',
}: {
  children: ReactNode;
  style?: ViewStyle | ViewStyle[];
  tone?: 'surface' | 'inset';
}) {
  return (
    <View style={[styles.card, tone === 'inset' && styles.cardInset, style]}>{children}</View>
  );
}

/** The small rounded square that holds a leading icon. */
export function Tile({ children, size = 35 }: { children: ReactNode; size?: number }) {
  return (
    <View style={[styles.tile, { width: size, height: size, borderRadius: size * 0.29 }]}>{children}</View>
  );
}

/* --------------------------------------------------------------- actions -- */

type ButtonProps = {
  label: string;
  onPress?: () => void;
  icon?: ReactNode;
  variant?: 'primary' | 'ghost' | 'quiet' | 'danger';
  disabled?: boolean;
  style?: ViewStyle;
};

export function Button({ label, onPress, icon, variant = 'primary', disabled, style }: ButtonProps) {
  const isDisabled = disabled === true && variant === 'primary';
  const press = () => {
    if (disabled) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    onPress?.();
  };
  return (
    <Pressable
      onPress={press}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      accessibilityLabel={label}
      style={({ pressed }) => [
        styles.button,
        variant === 'primary' && styles.buttonPrimary,
        isDisabled && styles.buttonPrimaryOff,
        variant === 'ghost' && styles.buttonGhost,
        variant === 'quiet' && styles.buttonQuiet,
        variant === 'danger' && styles.buttonDanger,
        pressed && !disabled && styles.buttonPressed,
        style,
      ]}
    >
      {icon}
      <Txt
        variant="action"
        caps
        tone={
          variant === 'ghost' || variant === 'quiet'
            ? 'ink'
            : isDisabled
              ? 'rgba(244,247,255,0.34)'
              : variant === 'danger'
                ? 'risk'
                : '#FFFFFF'
        }
      >
        {label}
      </Txt>
    </Pressable>
  );
}

/** A pressable list row: icon, text, and an optional trailing node. */
export function Row({
  leading,
  title,
  subtitle,
  trailing,
  onPress,
  style,
}: {
  leading?: ReactNode;
  title: string;
  subtitle?: ReactNode;
  trailing?: ReactNode;
  onPress?: () => void;
  style?: ViewStyle;
}) {
  const content = (
    <>
      {leading}
      <View style={styles.rowText}>
        <Txt variant="rowText" tone="ink" numberOfLines={2}>
          {title}
        </Txt>
        {subtitle}
      </View>
      {trailing}
    </>
  );
  if (!onPress) return <View style={[styles.row, style]}>{content}</View>;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={title}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed, style]}
    >
      {content}
    </Pressable>
  );
}

/* ----------------------------------------------------------------- chips -- */

export function Chip({
  label,
  icon,
  tone = 'neutral',
  size = 'md',
}: {
  label: string;
  icon?: ReactNode;
  tone?: 'neutral' | 'accent' | 'risk' | 'ok';
  size?: 'sm' | 'md';
}) {
  return (
    <View
      style={[
        styles.chip,
        size === 'sm' && styles.chipSm,
        tone === 'accent' && styles.chipAccent,
        tone === 'risk' && styles.chipRisk,
        tone === 'ok' && styles.chipOk,
      ]}
    >
      {icon}
      <Txt
        variant="chip"
        caps
        tone={tone === 'accent' ? '#FFFFFF' : tone === 'risk' ? 'risk' : tone === 'ok' ? 'ok' : 'ink'}
      >
        {label}
      </Txt>
    </View>
  );
}

/** The mono "reader · on this phone" line that sits beside a state chip. */
export function ReaderLine({ text }: { text: string }) {
  return (
    <Txt variant="crumb" tone="ink2">
      {text}
    </Txt>
  );
}

/* --------------------------------------------------------------- toggle --- */

export function Toggle({ value, onChange }: { value: boolean; onChange: () => void }) {
  // Lazy state, not a ref: an Animated value is read while rendering, and a ref
  // would hide that from the React compiler.
  const [anim] = useState(() => new Animated.Value(value ? 1 : 0));

  useEffect(() => {
    Animated.timing(anim, {
      toValue: value ? 1 : 0,
      duration: 180,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false,
    }).start();
  }, [anim, value]);

  const knobStyle = {
    transform: [
      {
        translateX: anim.interpolate({ inputRange: [0, 1], outputRange: [-17, 0] }),
      },
    ],
    backgroundColor: anim.interpolate({
      inputRange: [0, 1],
      outputRange: ['#151C33', '#1E2A4C'],
    }),
  };

  return (
    <Pressable
      onPress={() => {
        Haptics.selectionAsync().catch(() => {});
        onChange();
      }}
      accessibilityRole="switch"
      accessibilityState={{ checked: value }}
      accessibilityLabel="Wi-Fi only"
      hitSlop={8}
    >
      <View style={[styles.track, value && styles.trackOn]}>
        <Animated.View style={[styles.knob, knobStyle]} />
      </View>
    </Pressable>
  );
}

/* ------------------------------------------------------------- progress --- */

export function ProgressBar({ value, height = 6 }: { value: number; height?: number }) {
  const [anim] = useState(() => new Animated.Value(value));

  useEffect(() => {
    Animated.timing(anim, {
      toValue: Math.max(0, Math.min(1, value)),
      duration: 180,
      easing: Easing.out(Easing.quad),
      useNativeDriver: false,
    }).start();
  }, [anim, value]);

  return (
    <View style={[styles.trackBar, { height, borderRadius: height / 2 }]}>
      <Animated.View
        style={[
          styles.fill,
          { height, borderRadius: height / 2 },
          {
            width: anim.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }),
          },
        ]}
      />
    </View>
  );
}

/* ---------------------------------------------------------------- misc ---- */

export function SectionLabel({ children, style }: { children: string; style?: TextStyle }) {
  return (
    <Txt variant="sectionLabel" tone="ink" style={style}>
      {children}
    </Txt>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: color.surface,
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: color.edge,
    padding: 16,
  },
  cardInset: { backgroundColor: color.inset },
  tile: {
    backgroundColor: color.inset,
    borderWidth: 1,
    borderColor: color.edgeSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  button: {
    height: 48,
    borderRadius: radius.l,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: gap[2],
    paddingHorizontal: 16,
  },
  buttonPrimary: { backgroundColor: color.accent },
  buttonPrimaryOff: { backgroundColor: color.accentDim },
  buttonGhost: { borderWidth: 1, borderColor: color.edge, backgroundColor: 'transparent' },
  buttonQuiet: { backgroundColor: color.raise },
  buttonDanger: { backgroundColor: color.riskWash },
  buttonPressed: { opacity: 0.82 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[3],
    minHeight: 48,
  },
  rowPressed: { opacity: 0.7 },
  rowText: { flex: 1 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: radius.s,
    borderWidth: 1,
    borderColor: color.edge,
  },
  chipSm: { paddingHorizontal: 7, paddingVertical: 3 },
  chipAccent: { backgroundColor: color.accent, borderColor: color.accent },
  chipRisk: { backgroundColor: color.riskWash, borderColor: 'rgba(255,111,99,0.35)' },
  chipOk: { backgroundColor: 'rgba(61,220,151,0.12)', borderColor: 'rgba(61,220,151,0.3)' },
  track: {
    width: 45,
    height: 45,
    borderRadius: 14,
    borderWidth: 1.5,
    borderColor: color.edgeStrong,
    backgroundColor: color.inset,
    justifyContent: 'center',
    alignItems: 'flex-end',
  },
  trackOn: { borderColor: '#A9C0FF', backgroundColor: '#14224A' },
  knob: {
    width: 31,
    height: 31,
    borderRadius: 31,
    marginRight: -6,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.45)',
    shadowColor: '#000',
    shadowOpacity: 0.45,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  trackBar: { backgroundColor: '#050C1C', overflow: 'hidden', width: '100%' },
  fill: { backgroundColor: color.fill },
});
