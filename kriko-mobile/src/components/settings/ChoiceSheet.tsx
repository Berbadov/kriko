/**
 * A single-select picker as a bottom sheet: one checkbox row per choice, the
 * current one checked, a tap selects it and closes the sheet.
 *
 * The explanation that used to sit under a settings row lives here, as the
 * sheet's first line, so the list itself stays compact.
 */

import { Fragment, type ReactNode } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { tr } from '../../i18n';
import { tap } from '../../theme/feedback';
import { gap } from '../../theme/tokens';
import { makeStyles, useColors } from '../../theme/theme';
import { Txt } from '../../theme/Txt';
import { AnimatedSheet } from '../AnimatedSheet';
import { CheckIcon, XIcon } from '../Icon';
import { MotionPressable } from '../Motion';

export type Choice<T extends string = string> = {
  value: T;
  label: string;
  /** False for a language's own name: it is a name, never translated. */
  translate?: boolean;
  /** An optional leading visual, such as the theme's palette swatch. */
  preview?: ReactNode;
};

export function ChoiceSheet<T extends string>({
  visible,
  title,
  subtitle,
  intro,
  options,
  selected,
  onSelect,
  onClose,
}: {
  visible: boolean;
  title: string;
  /** One sentence, the old row description, shown first. */
  subtitle?: string;
  /** An optional visual under the copy, such as the floating-K preview. */
  intro?: ReactNode;
  options: readonly Choice<T>[];
  selected: string;
  onSelect: (value: T) => void;
  onClose: () => void;
}) {
  const color = useColors();
  const styles = useStyles();
  return (
    <AnimatedSheet visible={visible} onClose={onClose} style={styles.panel}>
      {(dismiss) => (
        <View style={styles.content}>
          <View style={styles.head}>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">{title}</Txt>
              {subtitle ? <Txt variant="bodyTight" tone="ink3">{subtitle}</Txt> : null}
            </View>
            <MotionPressable onPress={dismiss} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close')} style={styles.close}>
              <XIcon size={20} color={color.ink2} />
            </MotionPressable>
          </View>
          {intro ? <View style={styles.intro}>{intro}</View> : null}
          <ScrollView keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false} style={styles.list} contentContainerStyle={styles.choices}>
            {options.map((option, index) => {
              const active = option.value === selected;
              return (
                <Fragment key={option.value}>
                  {index > 0 ? <View style={styles.divider} /> : null}
                  <MotionPressable
                    onPress={() => {
                      tap();
                      onSelect(option.value);
                      dismiss();
                    }}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: active }}
                    accessibilityLabel={option.translate === false ? option.label : tr(option.label)}
                    style={styles.option}
                  >
                    {option.preview}
                    <Txt variant="rowText" tone="ink" translate={option.translate !== false} style={styles.optionLabel}>
                      {option.label}
                    </Txt>
                    {active ? <CheckIcon size={18} color={color.accent} /> : <View style={styles.checkSpace} />}
                  </MotionPressable>
                </Fragment>
              );
            })}
          </ScrollView>
        </View>
      )}
    </AnimatedSheet>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  panel: { paddingHorizontal: gap[4] },
  content: { gap: gap[3] },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: gap[3] },
  headText: { flex: 1, gap: 3 },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  intro: { alignItems: 'center' },
  list: { flexGrow: 0, flexShrink: 1 },
  choices: { paddingBottom: gap[1] },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: color.edge },
  option: { minHeight: 52, flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  optionLabel: { flex: 1 },
  checkSpace: { width: 18, height: 18 },
}));
