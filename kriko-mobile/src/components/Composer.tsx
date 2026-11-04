/**
 * One slim row: scan and image on the left, the question in the middle, send
 * (or stop) on the right. The writing surface grows upward with the text; the
 * row itself is as tall as one line of it, so the answer keeps the screen.
 *
 * Every control is the same 40 point square, so the row reads as one line; the
 * surface itself is the app's glass material, and focus draws a ring rather
 * than animating layout.
 */

import { useEffect, useState } from 'react';
import { AccessibilityInfo, Animated, AppState, Easing, Keyboard, Linking, StyleSheet, TextInput, View } from 'react-native';

import { tr, useLanguage } from '../i18n';
import { impact, press } from '../theme/feedback';
import { motion } from '../theme/motion';
import { radius } from '../theme/tokens';
import { makeStyles, useColors, useType } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { GlassBar } from './Glass';
import { MotionPressable, useReducedMotion } from './Motion';
import { ImageIcon2, MicIcon, RecordingStopIcon, ScanIcon, SendIcon, StopIcon } from './Icon';
import { useVoiceTyping } from './useVoiceTyping';

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
  autoFocus = false,
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
  autoFocus?: boolean;
}) {
  const color = useColors();
  const styles = useStyles();
  const type = useType();
  const language = useLanguage();
  const voice = useVoiceTyping(value, onChangeText, language);
  const canSend = !streaming && !disabled && !voice.active && value.trim().length > 0;
  const reduced = useReducedMotion();
  const [focused, setFocused] = useState(false);
  const [focus] = useState(() => new Animated.Value(0));
  const [action] = useState(() => new Animated.Value(streaming ? 1 : 0));
  const [bars] = useState(() => [0, 1, 2, 3, 4].map(() => new Animated.Value(0.35)));
  const [systemReduced, setSystemReduced] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((value) => { if (alive) setSystemReduced(value); }).catch(() => { if (alive) setSystemReduced(true); });
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setSystemReduced);
    return () => { alive = false; subscription.remove(); };
  }, []);
  useEffect(() => {
    bars.forEach((bar) => bar.stopAnimation());
    const reducedMotion = reduced === true || (reduced === null && systemReduced !== false);
    if (!voice.active || AppState.currentState !== 'active' || reducedMotion) {
      bars.forEach((bar) => bar.setValue(0.55));
      return;
    }
    const loops = bars.map((bar, index) => Animated.loop(Animated.sequence([
      Animated.delay(index * 75),
      Animated.timing(bar, { toValue: 1, duration: 260, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      Animated.timing(bar, { toValue: 0.25, duration: 300, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
    ])));
    loops.forEach((loop) => loop.start());
    const subscription = AppState.addEventListener('change', (state) => {
      loops.forEach((loop) => loop.stop());
      if (state === 'active' && voice.active) loops.forEach((loop) => loop.start());
    });
    return () => { subscription.remove(); loops.forEach((loop) => loop.stop()); };
  }, [bars, reduced, systemReduced, voice.active]);
  useEffect(() => {
    focus.stopAnimation();
    if (reduced !== false) { focus.setValue(focused ? 1 : 0); return; }
    const animation = Animated.timing(focus, { toValue: focused ? 1 : 0, duration: motion.duration.fast, useNativeDriver: true });
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
      <GlassBar
        radius={radius.l}
        intensity={40}
        tint={color.surface}
        tintOpacity={0.85}
        border={1}
        borderColor={color.edge}
        contentStyle={styles.surface}
      >
        <MotionPressable
          onPress={() => {
            press();
            onScan();
          }}
          disabled={disabled || voice.active}
          hitSlop={2}
          accessibilityRole="button"
          accessibilityLabel={tr('Scan a product')}
          style={styles.tool}
        >
          <ScanIcon size={20} color={disabled || voice.active ? color.ink4 : color.ink2} />
        </MotionPressable>
        <MotionPressable
          onPress={() => {
            press();
            onPick();
          }}
          disabled={disabled || streaming || voice.active}
          hitSlop={2}
          accessibilityRole="button"
          accessibilityLabel={tr('Choose a screenshot')}
          style={styles.tool}
        >
          <ImageIcon2 size={20} color={disabled || streaming || voice.active ? color.ink4 : color.ink2} />
        </MotionPressable>
        <TextInput
          autoFocus={autoFocus}
          value={value}
          onChangeText={onChangeText}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={tr(placeholder)}
          placeholderTextColor={color.ink3}
          multiline
          editable={!voice.active}
          selectionColor={color.accent}
          style={[styles.input, type.input]}
          maxLength={2000}
          accessibilityLabel={tr('Your question')}
        />
        {voice.supported ? (
          <MotionPressable
            onPress={() => {
              press();
              if (voice.active) voice.stop();
              else { Keyboard.dismiss(); void voice.start(); }
            }}
            disabled={disabled || streaming || voice.phase === 'starting' || voice.phase === 'processing'}
            hitSlop={2}
            accessibilityRole="button"
            accessibilityLabel={tr(voice.active ? 'Finish voice typing' : 'Type with your voice')}
            accessibilityHint={tr('Your words appear in the message field. Review them before you send.')}
            accessibilityState={{ busy: voice.phase === 'starting' || voice.phase === 'processing', disabled: !!disabled || streaming || voice.phase === 'starting' || voice.phase === 'processing' }}
            style={[styles.microphone, voice.active && styles.microphoneOn]}
          >
            {voice.active ? <View style={styles.voiceBars} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">{bars.map((bar, index) => <Animated.View key={index} style={[styles.voiceBar, { opacity: bar, transform: [{ scaleY: bar }] }]} />)}<RecordingStopIcon size={15} color={color.onAccent} /></View> : <MicIcon size={22} color={disabled || streaming ? color.ink4 : color.accentHi} />}
          </MotionPressable>
        ) : null}
        <Animated.View style={{ width: action.interpolate({ inputRange: [0, 1], outputRange: [SEND, STOP_W] }), height: SEND }}>
          <MotionPressable
            onPress={() => {
              if (streaming) { impact(); onStop(); }
              else if (canSend) { press(); onSend(); }
            }}
            disabled={!streaming && !canSend}
            hitSlop={2}
            accessibilityRole="button"
            accessibilityLabel={tr(streaming ? 'Stop the answer' : 'Send')}
            accessibilityState={{ disabled: !streaming && !canSend }}
            style={[styles.sendButton, streaming ? styles.stopButton : canSend ? styles.sendOn : styles.sendOff]}
          >
            <Animated.View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
              style={[styles.actionLayer, { opacity: action.interpolate({ inputRange: [0, 1], outputRange: [1, 0] }), transform: [{ scale: action.interpolate({ inputRange: [0, 1], outputRange: [1, 0.7] }) }] }]}>
              <SendIcon size={18} color={canSend ? color.onAccent : color.ink4} />
            </Animated.View>
            <Animated.View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
              style={[styles.actionLayer, { opacity: action, transform: [{ scale: action.interpolate({ inputRange: [0, 1], outputRange: [0.7, 1] }) }] }]}>
              <StopIcon size={15} color={color.risk} /><Txt variant="action" tone="risk">{tr('Stop')}</Txt>
            </Animated.View>
          </MotionPressable>
        </Animated.View>
      </GlassBar>
      {/* Focus is a ring drawn over the glass; opacity is the only animated value. */}
      <Animated.View pointerEvents="none" style={[styles.focusRing, { opacity: focus }]} />
      {voice.active ? (
        <View style={styles.voiceStatus}>
          <Txt variant="bodyTight" tone="ink2" accessibilityLiveRegion="polite" style={styles.voiceText}>
            {voice.phase === 'starting' ? 'Opening the microphone…' : voice.phase === 'processing' ? 'Finishing your words…' : 'Listening… Speak now.'}
          </Txt>
          <MotionPressable onPress={() => voice.cancel(true)} accessibilityRole="button" accessibilityLabel={tr('Cancel voice typing')} style={styles.voiceCancel}>
            <Txt variant="action" tone="ink2">Cancel</Txt>
          </MotionPressable>
        </View>
      ) : voice.error ? (
        <View>
          <Txt variant="bodyTight" tone="risk" accessibilityLiveRegion="polite" style={styles.voiceError}>{voice.error}</Txt>
          {voice.permissionDenied ? <MotionPressable onPress={() => { void Linking.openSettings().catch(() => {}); }} accessibilityRole="button" accessibilityLabel={tr('Open microphone settings')} style={styles.voiceCancel}>
            <Txt variant="action" tone="fill">Open microphone settings</Txt>
          </MotionPressable> : null}
        </View>
      ) : null}
    </View>
  );
}

/** The send button's side; every control in the row is this square. */
const SEND = 40;
/** The stop button widens to hold its label while keeping the row height. */
const STOP_W = 76;
/** One line of the input token: 22 px tall, centred in the 40 px row. */
const INPUT_LINE = 22;

const useStyles = makeStyles((color) => StyleSheet.create({
  wrap: {},
  surface: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  focusRing: {
    position: 'absolute',
    top: -2,
    left: -2,
    right: -2,
    bottom: -2,
    borderRadius: radius.l + 2,
    borderWidth: 2,
    borderColor: color.accentHi,
  },
  tool: { width: SEND, height: SEND, borderRadius: radius.s, alignItems: 'center', justifyContent: 'center' },
  microphone: {
    width: SEND,
    height: SEND,
    borderRadius: radius.m,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.accentWash,
    borderWidth: 1,
    borderColor: color.accentSoft,
  },
  microphoneOn: { backgroundColor: color.accent, borderColor: color.accent },
  voiceBars: { height: 24, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 3 },
  voiceBar: { width: 3, height: 18, borderRadius: 2, backgroundColor: color.onAccent },
  voiceStatus: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingLeft: 8, paddingTop: 4 },
  voiceText: { flex: 1 },
  voiceCancel: { minHeight: 44, minWidth: 64, alignItems: 'center', justifyContent: 'center' },
  voiceError: { paddingHorizontal: 8, paddingTop: 8 },
  input: {
    flex: 1,
    minHeight: SEND,
    maxHeight: 132,
    paddingTop: (SEND - INPUT_LINE) / 2,
    paddingBottom: (SEND - INPUT_LINE) / 2,
    paddingHorizontal: 4,
    color: color.ink,
  },
  sendButton: { width: '100%', height: SEND, alignItems: 'center', justifyContent: 'center' },
  actionLayer: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 4 },
  sendOn: { backgroundColor: color.accent, borderRadius: radius.m },
  sendOff: {
    backgroundColor: color.inset,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.edge,
  },
  stopButton: {
    paddingHorizontal: 8,
    borderRadius: radius.m,
    backgroundColor: color.riskWash,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
}));
