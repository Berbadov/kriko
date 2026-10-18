/**
 * The composer and the state line above it.
 *
 * The composer is one surface with a text row and an action row: the screenshot
 * button, the web switch, and send. While a run is working, send becomes STOP.
 */

import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { color, font, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { CheckCircleIcon, GlobeIcon, ImageIcon2, SendIcon, StopIcon } from './Icon';
import { Chip, ReaderLine } from './Primitives';

export type ReaderPhase = 'ready' | 'working' | 'blocked';

export function ReaderState({
  phase,
  note = 'reader · on this phone',
}: {
  phase: ReaderPhase;
  note?: string;
}) {
  if (phase === 'working') {
    return (
      <View style={styles.stateRow}>
        <Chip
          label="Working"
          icon={<ActivityIndicator size="small" color={color.ink} />}
          tone="neutral"
        />
        <ReaderLine text={note} />
      </View>
    );
  }
  return (
    <View style={styles.stateRow}>
      <Chip
        label={phase === 'ready' ? 'Ready' : 'No reader'}
        icon={<CheckCircleIcon size={14} color={phase === 'ready' ? color.ink : color.ink4} />}
      />
      <ReaderLine text={note} />
    </View>
  );
}

export function Composer({
  value,
  onChangeText,
  placeholder,
  onSend,
  onScreenshot,
  web,
  onToggleWeb,
  busy,
  onStop,
  disabled,
  lockedNote,
}: {
  value: string;
  onChangeText: (next: string) => void;
  placeholder: string;
  onSend: () => void;
  onScreenshot: () => void;
  web: boolean;
  onToggleWeb: () => void;
  busy?: boolean;
  onStop?: () => void;
  disabled?: boolean;
  lockedNote?: string;
}) {
  const [focused, setFocused] = useState(false);
  const canSend = value.trim().length > 0 && !disabled && !busy;

  return (
    <View style={[styles.surface, focused && styles.surfaceFocused]}>
      {disabled && lockedNote ? (
        <View style={styles.locked}>
          <Txt variant="body" tone="ink3">
            {lockedNote}
          </Txt>
        </View>
      ) : (
        <TextInput
          value={busy ? placeholder : value}
          editable={!busy && !disabled}
          onChangeText={onChangeText}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={placeholder}
          placeholderTextColor={busy ? color.ink2 : color.ink3}
          selectionColor={color.accent}
          style={[styles.input, busy && styles.inputBusy]}
          multiline={false}
          returnKeyType="send"
          onSubmitEditing={() => canSend && onSend()}
          accessibilityLabel={placeholder}
        />
      )}

      <View style={styles.actionRow}>
        <Pressable
          onPress={onScreenshot}
          disabled={disabled || busy}
          accessibilityRole="button"
          accessibilityLabel="Share a screenshot"
          style={({ pressed }) => [styles.round, (disabled || busy) && styles.dim, pressed && styles.pressed]}
        >
          <ImageIcon2 size={20} color={color.ink2} />
        </Pressable>

        <Pressable
          onPress={onToggleWeb}
          disabled={disabled}
          accessibilityRole="switch"
          accessibilityState={{ checked: web }}
          accessibilityLabel="Use the web"
          style={({ pressed }) => [
            styles.pill,
            web && styles.pillOn,
            disabled && styles.dim,
            pressed && styles.pressed,
          ]}
        >
          <GlobeIcon size={19} color={web ? color.ink : color.ink3} />
          <Txt variant="rowText" tone={web ? 'ink' : 'ink3'}>
            {web ? 'Web on' : 'Web off'}
          </Txt>
        </Pressable>

        <View style={styles.spacer} />

        {busy ? (
          <Pressable
            onPress={onStop}
            accessibilityRole="button"
            accessibilityLabel="Stop"
            style={({ pressed }) => [styles.stop, pressed && styles.pressed]}
          >
            <StopIcon size={18} color={color.risk} />
            <Txt variant="actionSmall" tone="risk" caps>
              Stop
            </Txt>
          </Pressable>
        ) : (
          <Pressable
            onPress={onSend}
            disabled={!canSend}
            accessibilityRole="button"
            accessibilityLabel="Send"
            style={({ pressed }) => [
              styles.round,
              styles.send,
              canSend && styles.sendOn,
              pressed && canSend && styles.pressed,
            ]}
          >
            <SendIcon size={20} color={canSend ? '#FFFFFF' : '#8FA8E8'} strokeWidth={1.7} />
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  stateRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[3],
    paddingBottom: 10,
  },
  surface: {
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.surface,
    paddingTop: 6,
    paddingHorizontal: 12,
    paddingBottom: 12,
  },
  surfaceFocused: { borderColor: color.edgeStrong },
  input: {
    color: color.ink,
    fontFamily: font.regular,
    fontSize: 16,
    lineHeight: 21,
    letterSpacing: 0.05,
    paddingVertical: 10,
    minHeight: 41,
  },
  inputBusy: { color: color.ink2 },
  locked: { paddingVertical: 12 },
  actionRow: { flexDirection: 'row', alignItems: 'center', gap: gap[2], marginTop: 4 },
  round: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#142241',
  },
  send: { backgroundColor: color.accentDeep },
  sendOn: { backgroundColor: color.accent },
  pill: {
    height: 44,
    borderRadius: 22,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[2],
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.raise,
  },
  pillOn: { backgroundColor: color.accentSoft, borderColor: '#1E3E8C' },
  stop: {
    height: 44,
    borderRadius: 14,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[2],
    backgroundColor: color.riskWash,
  },
  spacer: { flex: 1 },
  dim: { opacity: 0.45 },
  pressed: { opacity: 0.75 },
});
