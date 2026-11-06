/**
 * The compact grouped list Settings is built from.
 *
 * A section is a quiet label above one or more cards. A card is one glass panel
 * with hairline rules between rows. A row is [accent icon tile] [label] [muted
 * current value] [chevron], with a toggle at the right edge instead of a value
 * when the choice is on/off. Explanations do not belong to a row: they live in
 * the sheet that row opens, so the list stays short enough to scan.
 */

import { Children, Fragment, type ReactNode } from 'react';
import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { tr } from '../../i18n';
import { gap, radius } from '../../theme/tokens';
import { makeStyles, useColors } from '../../theme/theme';
import { Txt } from '../../theme/Txt';
import { GlassCard } from '../Glass';
import { ChevronRightIcon } from '../Icon';
import { MotionPressable, MotionView } from '../Motion';
import { Toggle } from '../Primitives';

/** Horizontal inset of a row, the square that holds its icon, and the gap between. */
const ROW_X = 14;
const TILE = 30;
const ROW_GAP = 12;
/** Rules start after the icon column, the way a grouped list does. */
const DIVIDER_INSET = ROW_X + TILE + ROW_GAP;

/** One labelled group: a muted heading, then its cards. */
export function SettingsSection({
  label,
  children,
  delay = 0,
}: {
  label?: string;
  children: ReactNode;
  delay?: number;
}) {
  const styles = useStyles();
  return (
    <MotionView delay={delay} style={styles.section}>
      {label ? (
        <Txt variant="sectionLabel" tone="ink3" style={styles.sectionLabel}>
          {label}
        </Txt>
      ) : null}
      <View style={styles.stack}>{children}</View>
    </MotionView>
  );
}

/** One rounded panel. Hairline rules between the rows are added here. */
export function SettingsCard({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const color = useColors();
  const items = Children.toArray(children).filter(Boolean);
  return (
    <GlassCard radius={18} border={1} tint={color.surface} style={style}>
      {items.map((child, index) => (
        <Fragment key={index}>
          {index > 0 ? <RowDivider /> : null}
          {child}
        </Fragment>
      ))}
    </GlassCard>
  );
}

/** A hairline between two rows, inset past the icon column. */
export function RowDivider() {
  const styles = useStyles();
  return <View style={styles.divider} />;
}

/**
 * A row that opens something: a sheet, a system screen, or a page. When it does
 * not open anything (`onPress` omitted) it is a plain display row.
 */
export function SettingRow({
  icon,
  label,
  value,
  subtitle,
  valueTranslate = true,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  danger,
  chevron = true,
}: {
  icon: ReactNode;
  label: string;
  /** The current choice, right-aligned and muted. Kept short. */
  value?: string;
  /** A sentence under the label for the few rows that carry state, never copy. */
  subtitle?: string;
  /** False for a language's own name or a reader's own text. */
  valueTranslate?: boolean;
  onPress?: () => void;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  danger?: boolean;
  chevron?: boolean;
}) {
  const color = useColors();
  const styles = useStyles();
  const content = (
    <>
      <View style={styles.line}>
        <View style={[styles.tile, danger && styles.tileDanger]}>{icon}</View>
        <Txt variant="rowTitle" tone={danger ? 'risk' : 'ink'} numberOfLines={1} style={styles.label}>
          {label}
        </Txt>
        {value ? (
          <Txt variant="meta" tone="ink3" numberOfLines={1} translate={valueTranslate} style={styles.value}>
            {value}
          </Txt>
        ) : null}
        {onPress && chevron ? <ChevronRightIcon size={16} color={color.ink4} /> : null}
      </View>
      {subtitle ? (
        <Txt variant="bodyTight" tone="ink3" numberOfLines={3} style={styles.subtitle}>
          {subtitle}
        </Txt>
      ) : null}
    </>
  );
  if (!onPress) return <View style={styles.row}>{content}</View>;
  return (
    <MotionPressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? tr(label)}
      accessibilityHint={accessibilityHint}
      style={styles.row}
    >
      {content}
    </MotionPressable>
  );
}

/** A row whose right edge is the switch; the whole row is the touch target. */
export function ToggleRow({
  icon,
  label,
  value,
  onChange,
  accessibilityLabel,
}: {
  icon: ReactNode;
  label: string;
  value: boolean;
  onChange: () => void;
  accessibilityLabel?: string;
}) {
  const styles = useStyles();
  return (
    <Pressable
      onPress={onChange}
      accessibilityRole="switch"
      accessibilityState={{ checked: value }}
      accessibilityLabel={accessibilityLabel ?? tr(label)}
      style={styles.lineRow}
    >
      <View style={styles.tile}>{icon}</View>
      <Txt variant="rowTitle" tone="ink" style={styles.label}>{label}</Txt>
      {/* The switch is the visual, not a second focusable control. */}
      <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        <Toggle value={value} onChange={onChange} label={label} />
      </View>
    </Pressable>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  section: { gap: gap[2] },
  sectionLabel: { paddingLeft: 4 },
  stack: { gap: gap[3] },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: color.edge,
    marginLeft: DIVIDER_INSET,
  },
  row: {
    minHeight: 54,
    justifyContent: 'center',
    gap: 4,
    paddingHorizontal: ROW_X,
    paddingVertical: 10,
  },
  lineRow: {
    minHeight: 54,
    flexDirection: 'row',
    alignItems: 'center',
    gap: ROW_GAP,
    paddingHorizontal: ROW_X,
    paddingVertical: 10,
  },
  line: {
    minHeight: 30,
    flexDirection: 'row',
    alignItems: 'center',
    gap: ROW_GAP,
  },
  label: { flex: 1 },
  tile: {
    width: TILE,
    height: TILE,
    borderRadius: radius.m,
    backgroundColor: color.accentSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tileDanger: { backgroundColor: color.riskWash },
  subtitle: { marginLeft: TILE + ROW_GAP, paddingBottom: 2 },
  value: { maxWidth: '46%', textAlign: 'right' },
}));
