/** Shared paper surfaces, controls, and restrained motion. */

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Animated, Easing, Pressable, StyleSheet, View, type TextStyle, type ViewStyle } from 'react-native';

import { gap, radius } from '../theme/tokens';
import { motion } from '../theme/motion';
import { press as hapticPress, tap as hapticTap } from '../theme/feedback';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { tr } from '../i18n';
import { MotionPressable, useReducedMotion } from './Motion';

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
  const styles = useStyles();
  return (
    <View style={[styles.card, tone === 'inset' && styles.cardInset, style]}>{children}</View>
  );
}

/** The small rounded square that holds a leading icon. */
export function Tile({ children, size = 35 }: { children: ReactNode; size?: number }) {
  const styles = useStyles();
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
  const color = useColors();
  const styles = useStyles();
  const isDisabled = disabled === true && variant === 'primary';
  const press = () => {
    if (disabled) return;
    hapticPress();
    onPress?.();
  };
  return (
    <MotionPressable
      onPress={press}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      accessibilityLabel={tr(label)}
      style={[
        styles.button,
        variant === 'primary' && styles.buttonPrimary,
        isDisabled && styles.buttonPrimaryOff,
        variant === 'ghost' && styles.buttonGhost,
        variant === 'quiet' && styles.buttonQuiet,
        variant === 'danger' && styles.buttonDanger,
        style,
      ]}
    >
      {icon}
      <Txt
        variant="action"
        tone={
          variant === 'ghost' || variant === 'quiet'
            ? 'ink'
            : isDisabled
              ? 'ink4'
              : variant === 'danger'
                ? 'risk'
                : color.onAccent
        }
      >
        {label}
      </Txt>
    </MotionPressable>
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
  const styles = useStyles();
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
      accessibilityLabel={tr(title)}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed, style]}
    >
      {content}
    </Pressable>
  );
}

/** A row of mutually exclusive choices: one track, one raised selection. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  const reduced = useReducedMotion();
  const styles = useStyles();
  const [trackWidth, setTrackWidth] = useState(0);
  const [indicatorX] = useState(() => new Animated.Value(0));
  const positioned = useRef(false);
  const activeIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const segmentWidth = options.length
    ? Math.max(0, (trackWidth - 6 - Math.max(0, options.length - 1) * 3) / options.length)
    : 0;

  useEffect(() => {
    if (!segmentWidth) return;
    const target = activeIndex * (segmentWidth + 3);
    indicatorX.stopAnimation();
    if (reduced !== false || !positioned.current) {
      indicatorX.setValue(target);
      positioned.current = true;
      return;
    }
    Animated.spring(indicatorX, { toValue: target, ...motion.spring.morph }).start();
  }, [activeIndex, indicatorX, reduced, segmentWidth]);

  return (
    <View style={styles.segmented} onLayout={(event) => setTrackWidth(event.nativeEvent.layout.width)}>
      {segmentWidth > 0 ? (
        <Animated.View
          pointerEvents="none"
          style={[
            styles.segmentIndicator,
            { width: segmentWidth, transform: [{ translateX: indicatorX }] },
          ]}
        />
      ) : null}
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Pressable
            key={option.value}
            onPress={() => onChange(option.value)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            accessibilityLabel={tr(option.label)}
            style={({ pressed }) => [
              styles.segment,
              pressed && styles.rowPressed,
            ]}
          >
            <Txt variant="actionSmall" tone={active ? 'ink' : 'ink3'} numberOfLines={1}>
              {option.label}
            </Txt>
          </Pressable>
        );
      })}
    </View>
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
  const color = useColors();
  const styles = useStyles();
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
        tone={tone === 'accent' ? color.onAccent : tone === 'risk' ? 'risk' : tone === 'ok' ? 'ok' : 'ink'}
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

export function Toggle({
  value,
  onChange,
  label = 'Toggle',
}: {
  value: boolean;
  onChange: () => void;
  label?: string;
}) {
  const color = useColors();
  const styles = useStyles();
  // Lazy state, not a ref: an Animated value is read while rendering, and a ref
  // would hide that from the React compiler.
  const [anim] = useState(() => new Animated.Value(value ? 1 : 0));
  const [highlight] = useState(() => new Animated.Value(value ? 1 : 0));
  const reduced = useReducedMotion();

  useEffect(() => {
    anim.stopAnimation();
    highlight.stopAnimation();
    const target = value ? 1 : 0;
    if (reduced !== false) {
      anim.setValue(target);
      highlight.setValue(target);
      return;
    }
    Animated.parallel([
      Animated.spring(anim, { toValue: target, ...motion.spring.responsive }),
      Animated.timing(highlight, {
        toValue: target,
        duration: motion.duration.fast,
        easing: Easing.bezier(...motion.easing.standard),
        useNativeDriver: true,
      }),
    ]).start();
  }, [anim, highlight, value, reduced]);

  return (
    <Pressable
      onPress={() => {
        hapticTap();
        onChange();
      }}
      accessibilityRole="switch"
      accessibilityState={{ checked: value }}
      accessibilityLabel={tr(label)}
      hitSlop={8}
    >
      <View style={styles.track}>
        <Animated.View pointerEvents="none" style={[styles.trackOn, { opacity: highlight }]} />
        <Animated.View style={[styles.knob, {
          backgroundColor: color.surface,
          transform: [{ translateX: anim.interpolate({ inputRange: [0, 1], outputRange: [0, 22] }) }],
        }]} />
      </View>
    </Pressable>
  );
}

/* ------------------------------------------------------------- progress --- */

export function ProgressBar({ value, height = 6 }: { value: number; height?: number }) {
  const styles = useStyles();
  const [anim] = useState(() => new Animated.Value(value));
  const reduced = useReducedMotion();

  useEffect(() => {
    anim.stopAnimation();
    const target = Math.max(0, Math.min(1, value));
    if (reduced !== false) {
      anim.setValue(target);
      return;
    }
    Animated.spring(anim, {
      toValue: target,
      stiffness: 320,
      damping: 36,
      mass: 1,
      overshootClamping: true,
      useNativeDriver: false,
    }).start();
  }, [anim, value, reduced]);

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

const useStyles = makeStyles((color) => StyleSheet.create({
  card: {
    backgroundColor: color.surface,
    borderRadius: radius.l,
    borderWidth: 0,
    padding: 18,
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
    minHeight: 52,
    borderRadius: radius.m,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: gap[2],
    paddingHorizontal: 16,
  },
  buttonPrimary: { backgroundColor: color.accent },
  buttonPrimaryOff: { backgroundColor: color.accentDim },
  buttonGhost: { borderWidth: 1, borderColor: color.edge, backgroundColor: color.surface },
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
  segmented: {
    flexDirection: 'row',
    backgroundColor: color.inset,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.edge,
    padding: 3,
    gap: 3,
    position: 'relative',
  },
  segmentIndicator: {
    position: 'absolute',
    left: 3,
    top: 3,
    height: 44,
    borderRadius: radius.s,
    backgroundColor: color.raise,
    borderWidth: 1,
    borderColor: color.edgeStrong,
  },
  segment: {
    flex: 1,
    minHeight: 44,
    borderRadius: radius.s,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  chipSm: { paddingHorizontal: 7, paddingVertical: 3 },
  chipAccent: { backgroundColor: color.accent, borderColor: color.accent },
  chipRisk: { backgroundColor: color.riskWash, borderColor: color.risk },
  chipOk: { backgroundColor: color.accentWash, borderColor: color.ok },
  track: {
    width: 52,
    height: 30,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: color.edgeStrong,
    backgroundColor: color.inset,
    justifyContent: 'center',
    alignItems: 'flex-start',
    paddingHorizontal: 2,
  },
  trackOn: { ...StyleSheet.absoluteFill, borderRadius: 15, backgroundColor: color.accent },
  knob: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: color.edgeSoft,
    shadowColor: color.shadow,
    shadowOpacity: 0.10,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  trackBar: { backgroundColor: color.inset, overflow: 'hidden', width: '100%' },
  fill: { backgroundColor: color.fill },
}));
