/**
 * The products-and-priorities editor, as a sheet.
 *
 * It is text input, not a choice, so it gets its own sheet instead of a
 * checkbox list. Saving keeps the old behaviour exactly: split on commas, new
 * lines or semicolons, trim, keep at most ten, and fall back to "all" when the
 * field is emptied.
 */

import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { tr } from '../../i18n';
import { gap } from '../../theme/tokens';
import { makeStyles, useColors, useType } from '../../theme/theme';
import { Txt } from '../../theme/Txt';
import { AnimatedSheet } from '../AnimatedSheet';
import { XIcon } from '../Icon';
import { MotionPressable } from '../Motion';
import { Button } from '../Primitives';

export function PrioritiesSheet({
  visible,
  products,
  onSave,
  onClose,
}: {
  visible: boolean;
  /** The saved list; `all` means no restriction. */
  products: string[];
  onSave: (products: string[]) => void;
  onClose: () => void;
}) {
  const color = useColors();
  const styles = useStyles();
  const type = useType();
  const [draft, setDraft] = useState('');
  const [dirty, setDirty] = useState(false);
  const saved = products.filter((item) => item !== 'all').join(', ');
  return (
    <AnimatedSheet visible={visible} onClose={onClose} style={styles.panel}>
      {(dismiss) => (
        <View style={styles.content}>
          <View style={styles.head}>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">Products and priorities</Txt>
              <Txt variant="bodyTight" tone="ink3">
                Tell Kriko what you’re considering and what matters. Separate items with commas or new lines.
              </Txt>
            </View>
            <MotionPressable onPress={dismiss} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close')} style={styles.close}>
              <XIcon size={20} color={color.ink2} />
            </MotionPressable>
          </View>
          <TextInput
            value={dirty ? draft : saved}
            onChangeText={(value) => {
              setDraft(value);
              setDirty(true);
            }}
            placeholder={tr('Quiet laptop, USB-C monitor, small kitchen')}
            placeholderTextColor={color.ink3}
            multiline
            maxLength={500}
            accessibilityLabel={tr('Products and priorities')}
            selectionColor={color.accent}
            style={[styles.input, type.input]}
          />
          <Button
            label={tr('Save priorities')}
            variant="quiet"
            disabled={!dirty}
            onPress={() => {
              const next = draft.split(/[,\n;]/).map((item) => item.trim()).filter(Boolean).slice(0, 10);
              onSave(next.length ? next : ['all']);
              setDirty(false);
              dismiss();
            }}
          />
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
  input: {
    minHeight: 96,
    textAlignVertical: 'top',
    borderWidth: 1,
    borderColor: color.edgeStrong,
    borderRadius: 12,
    color: color.ink,
    backgroundColor: color.inset,
    paddingHorizontal: gap[3],
    paddingVertical: gap[2],
  },
}));
