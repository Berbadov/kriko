/** A quiet paper writing surface with fast scan and image actions. */

import * as Haptics from 'expo-haptics';
import { StyleSheet, TextInput, View } from 'react-native';

import { tr } from '../i18n';
import { color, font, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { ActivityDots, MotionPressable } from './Motion';
import { ImageIcon2, ScanIcon, SendIcon, StopIcon } from './Icon';

export function Composer({
  value,
  onChangeText,
  onSend,
  onStop,
  onPick,
  onScan,
  streaming,
  disabled,
  placeholder = 'Ask about a product',
}: {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  onStop: () => void;
  onPick: () => void;
  onScan: () => void;
  streaming: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  const canSend = !streaming && !disabled && value.trim().length > 0;

  return (
    <View style={styles.wrap}>
      <View style={styles.surface}>
        <View style={styles.inputRow}>
          <TextInput
            value={value}
            onChangeText={onChangeText}
            placeholder={tr(placeholder)}
            placeholderTextColor={color.ink3}
            multiline
            selectionColor={color.accent}
            style={styles.input}
            maxLength={2000}
            accessibilityLabel={tr('Your question')}
          />
          {streaming ? (
            <MotionPressable
              onPress={() => {
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
                onStop();
              }}
              accessibilityRole="button"
              accessibilityLabel={tr('Stop the answer')}
              style={styles.stopButton}
            >
              <StopIcon size={17} color={color.risk} />
              <Txt variant="actionSmall" tone="risk">{tr('Stop')}</Txt>
            </MotionPressable>
          ) : (
            <MotionPressable
              onPress={() => {
                if (!canSend) return;
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
                onSend();
              }}
              disabled={!canSend}
              accessibilityRole="button"
              accessibilityLabel={tr('Send')}
              accessibilityState={{ disabled: !canSend }}
              style={[styles.sendButton, canSend ? styles.sendOn : styles.sendOff]}
            >
              <SendIcon size={17} color={canSend ? '#FFFFFF' : color.ink3} />
            </MotionPressable>
          )}
        </View>

        <View style={styles.toolbar}>
          <MotionPressable
            onPress={() => {
              Haptics.selectionAsync().catch(() => {});
              onScan();
            }}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel={tr('Scan a product')}
            style={styles.tool}
          >
            <ScanIcon size={15} color={disabled ? color.ink4 : color.ink2} />
            <Txt variant="monoSm" tone={disabled ? 'ink4' : 'ink2'}>{tr('Scan page')}</Txt>
          </MotionPressable>
          <View style={styles.toolbarRule} />
          <MotionPressable
            onPress={() => {
              Haptics.selectionAsync().catch(() => {});
              onPick();
            }}
            disabled={disabled || streaming}
            accessibilityRole="button"
            accessibilityLabel={tr('Choose a screenshot')}
            style={styles.tool}
          >
            <ImageIcon2 size={15} color={disabled || streaming ? color.ink4 : color.ink2} />
            <Txt variant="monoSm" tone={disabled || streaming ? 'ink4' : 'ink2'}>{tr('Image')}</Txt>
          </MotionPressable>
          {streaming ? (
            <View style={styles.working}>
              <ActivityDots color={color.accent} />
              <Txt variant="monoSm" tone="ink3">{tr('Working')}</Txt>
            </View>
          ) : null}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingTop: 4 },
  surface: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edge,
    borderRadius: radius.l,
    paddingHorizontal: 13,
    paddingTop: 10,
    paddingBottom: 8,
    shadowColor: color.ink,
    shadowOpacity: 0.06,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 5 },
    elevation: 2,
  },
  inputRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 8 },
  input: {
    flex: 1,
    minHeight: 42,
    maxHeight: 132,
    paddingTop: 8,
    paddingBottom: 7,
    paddingHorizontal: 2,
    color: color.ink,
    fontFamily: font.regular,
    fontSize: 16,
    lineHeight: 23,
  },
  sendButton: { width: 38, height: 38, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  sendOn: { backgroundColor: color.accent },
  sendOff: { backgroundColor: color.inset },
  stopButton: {
    minHeight: 38,
    paddingHorizontal: 9,
    borderRadius: 12,
    backgroundColor: color.riskWash,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  toolbar: {
    minHeight: 34,
    marginTop: 5,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edge,
    paddingTop: 7,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
  },
  tool: { minHeight: 28, paddingHorizontal: 2, flexDirection: 'row', alignItems: 'center', gap: 6 },
  toolbarRule: { width: StyleSheet.hairlineWidth, height: 16, backgroundColor: color.edge },
  working: { marginLeft: 'auto', flexDirection: 'row', alignItems: 'center', gap: 6 },
});
