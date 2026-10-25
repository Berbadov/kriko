/** A black writing surface with a native Arc-style send/stop action swap. */

import { useEffect, useState } from 'react';
import { Animated, StyleSheet, TextInput, View } from 'react-native';

import { tr } from '../i18n';
import { impact, press } from '../theme/feedback';
import { motion } from '../theme/motion';
import { font, radius } from '../theme/tokens';
import { makeStyles, useColors, useType } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { ActivityDots, MotionPressable, useReducedMotion } from './Motion';
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
  const color = useColors();
  const styles = useStyles();
  const type = useType();
  const canSend = !streaming && !disabled && value.trim().length > 0;
  const reduced = useReducedMotion();
  const [focused, setFocused] = useState(false);
  const [focus] = useState(() => new Animated.Value(0));
  const [action] = useState(() => new Animated.Value(streaming ? 1 : 0));
  useEffect(() => {
    focus.stopAnimation();
    if (reduced !== false) { focus.setValue(focused ? 1 : 0); return; }
    const animation = Animated.timing(focus, { toValue: focused ? 1 : 0, duration: motion.duration.fast, useNativeDriver: false });
    animation.start();
    return () => animation.stop();
  }, [focus, focused, reduced]);
  useEffect(() => {
    action.stopAnimation();
    if (reduced !== false) { action.setValue(streaming ? 1 : 0); return; }
    const animation = Animated.spring(action, { ...motion.spring.morph, toValue: streaming ? 1 : 0, useNativeDriver: false, overshootClamping: true });
    animation.start();
    return () => animation.stop();
  }, [action, streaming, reduced]);

  return (
    <View style={styles.wrap}>
      <Animated.View style={[styles.surface, { borderColor: focus.interpolate({ inputRange: [0, 1], outputRange: [color.edge, color.accentHi] }) }]}>
        <View style={styles.inputRow}>
          <TextInput
            value={value}
            onChangeText={onChangeText}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder={tr(placeholder)}
            placeholderTextColor={color.ink3}
            multiline
            selectionColor={color.accent}
            style={[styles.input, type.input]}
            maxLength={2000}
            accessibilityLabel={tr('Your question')}
          />
          <Animated.View style={{ width: action.interpolate({ inputRange: [0, 1], outputRange: [44, 76] }), height: 44 }}>
            <MotionPressable
              onPress={() => {
                if (streaming) { impact(); onStop(); }
                else if (canSend) { press(); onSend(); }
              }}
              disabled={!streaming && !canSend}
              accessibilityRole="button"
              accessibilityLabel={tr(streaming ? 'Stop the answer' : 'Send')}
              accessibilityState={{ disabled: !streaming && !canSend }}
              style={[styles.sendButton, streaming ? styles.stopButton : canSend ? styles.sendOn : styles.sendOff]}
            >
              <Animated.View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
                style={[styles.actionLayer, { opacity: action.interpolate({ inputRange: [0, 1], outputRange: [1, 0] }), transform: [{ scale: action.interpolate({ inputRange: [0, 1], outputRange: [1, 0.7] }) }] }]}>
                <SendIcon size={17} color={canSend ? color.onAccent : color.ink3} />
              </Animated.View>
              <Animated.View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
                style={[styles.actionLayer, { opacity: action, transform: [{ scale: action.interpolate({ inputRange: [0, 1], outputRange: [0.7, 1] }) }] }]}>
                <StopIcon size={15} color={color.risk} /><Txt variant="actionSmall" tone="risk">{tr('Stop')}</Txt>
              </Animated.View>
            </MotionPressable>
          </Animated.View>
        </View>

        <View style={styles.toolbar}>
          <MotionPressable
            onPress={() => {
              press();
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
              press();
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
      </Animated.View>
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  wrap: { paddingTop: 4 },
  surface: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edge,
    borderRadius: radius.l,
    paddingHorizontal: 13,
    paddingTop: 10,
    paddingBottom: 8,
    shadowColor: color.shadow,
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
  sendButton: { width: '100%', height: 44, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  actionLayer: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 5 },
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
}));
