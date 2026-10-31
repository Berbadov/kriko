/**
 * One slim row: scan and image on the left, the question in the middle, send
 * (or stop) on the right. The writing surface grows upward with the text; the
 * row itself is as tall as one line of it, so the answer keeps the screen.
 */

import { useEffect, useState } from 'react';
import { Animated, StyleSheet, TextInput, View } from 'react-native';

import { tr } from '../i18n';
import { impact, press } from '../theme/feedback';
import { motion } from '../theme/motion';
import { font, radius } from '../theme/tokens';
import { makeStyles, useColors, useType } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { MotionPressable, useReducedMotion } from './Motion';
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
        <MotionPressable
          onPress={() => {
            press();
            onScan();
          }}
          disabled={disabled}
          hitSlop={{ top: 4, bottom: 4 }}
          accessibilityRole="button"
          accessibilityLabel={tr('Scan a product')}
          style={styles.tool}
        >
          <ScanIcon size={20} color={disabled ? color.ink4 : color.ink2} />
        </MotionPressable>
        <MotionPressable
          onPress={() => {
            press();
            onPick();
          }}
          disabled={disabled || streaming}
          hitSlop={{ top: 4, bottom: 4 }}
          accessibilityRole="button"
          accessibilityLabel={tr('Choose a screenshot')}
          style={styles.tool}
        >
          <ImageIcon2 size={20} color={disabled || streaming ? color.ink4 : color.ink2} />
        </MotionPressable>
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
        <Animated.View style={{ width: action.interpolate({ inputRange: [0, 1], outputRange: [SEND, 76] }), height: SEND }}>
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
      </Animated.View>
    </View>
  );
}

/** The send button's side; the row is this tall plus the surface's own padding. */
const SEND = 40;

const useStyles = makeStyles((color) => StyleSheet.create({
  wrap: {},
  surface: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 2,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edge,
    borderRadius: radius.l,
    paddingHorizontal: 5,
    paddingVertical: 4,
    shadowColor: color.shadow,
    shadowOpacity: 0.06,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 5 },
    elevation: 2,
  },
  tool: { width: 36, height: SEND, alignItems: 'center', justifyContent: 'center' },
  input: {
    flex: 1,
    minHeight: SEND,
    maxHeight: 132,
    paddingTop: 8,
    paddingBottom: 8,
    paddingHorizontal: 4,
    color: color.ink,
    fontFamily: font.regular,
    fontSize: 16,
    lineHeight: 23,
  },
  sendButton: { width: '100%', height: SEND, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  actionLayer: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 5 },
  sendOn: { backgroundColor: color.accent },
  sendOff: { backgroundColor: color.inset },
  stopButton: {
    paddingHorizontal: 9,
    borderRadius: 12,
    backgroundColor: color.riskWash,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
}));
