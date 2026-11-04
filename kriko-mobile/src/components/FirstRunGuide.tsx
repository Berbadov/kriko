import { useEffect, useState } from 'react';
import { Animated, AppState, Easing, Modal, StyleSheet, View } from 'react-native';

import { tr } from '../i18n';
import { motion } from '../theme/motion';
import { gap, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { CheckCircleIcon, GlobeIcon, MicIcon, ScanIcon } from './Icon';
import { MotionPressable, useReducedMotion } from './Motion';

const steps = [
  { title: 'Scan the listing', copy: 'Kriko reads product details from your screen or screenshot.', Icon: ScanIcon },
  { title: 'Ask by voice or text', copy: 'Type below or tap the microphone to ask.', Icon: MicIcon },
  { title: 'Check the sources', copy: 'Review the evidence behind each answer.', Icon: GlobeIcon },
];

export function FirstRunGuide({ onComplete, onSkip }: { onComplete: () => void; onSkip: () => void }) {
  const colors = useColors();
  const styles = useStyles();
  const reduced = useReducedMotion();
  const [index, setIndex] = useState(0);
  const [fade] = useState(() => new Animated.Value(1));
  const [tapScale] = useState(() => new Animated.Value(0.55));
  const [tapOpacity] = useState(() => new Animated.Value(0.2));
  const [bars] = useState(() => [0, 1, 2, 3, 4].map(() => new Animated.Value(0.35)));
  const [appActive, setAppActive] = useState(AppState.currentState === 'active');
  const step = steps[index];

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => setAppActive(state === 'active'));
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    fade.stopAnimation();
    if (reduced !== false) { fade.setValue(1); return undefined; }
    fade.setValue(0);
    const animation = Animated.timing(fade, { toValue: 1, duration: motion.duration.fast,
      easing: Easing.out(Easing.quad), useNativeDriver: true });
    animation.start();
    return () => animation.stop();
  }, [fade, index, reduced]);

  useEffect(() => {
    tapScale.stopAnimation();
    tapOpacity.stopAnimation();
    bars.forEach((bar) => bar.stopAnimation());
    if (reduced !== false || !appActive) {
      tapScale.setValue(0.75);
      tapOpacity.setValue(0.48);
      bars.forEach((bar, barIndex) => bar.setValue([0.5, 0.85, 0.62, 1, 0.55][barIndex]));
      return undefined;
    }
    const pulse = Animated.loop(Animated.sequence([
      Animated.parallel([
        Animated.timing(tapScale, { toValue: 1.35, duration: 650, easing: Easing.out(Easing.quad), useNativeDriver: true }),
        Animated.timing(tapOpacity, { toValue: 0, duration: 650, useNativeDriver: true }),
      ]),
      Animated.timing(tapScale, { toValue: 0.55, duration: 1, useNativeDriver: true }),
      Animated.timing(tapOpacity, { toValue: 0.55, duration: 1, useNativeDriver: true }),
      Animated.delay(260),
    ]));
    const voiceLoops = bars.map((bar, barIndex) => Animated.loop(Animated.sequence([
      Animated.delay(barIndex * 90),
      Animated.timing(bar, { toValue: 1, duration: 330 + (barIndex % 2) * 90, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      Animated.timing(bar, { toValue: 0.28, duration: 330 + (barIndex % 2) * 90, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      Animated.delay((bars.length - barIndex) * 70),
    ])));
    if (index === 0 || index === 2) pulse.start();
    if (index === 1) voiceLoops.forEach((loop) => loop.start());
    return () => { pulse.stop(); voiceLoops.forEach((loop) => loop.stop()); };
  }, [appActive, bars, index, reduced, tapOpacity, tapScale]);

  const next = () => index === steps.length - 1 ? onComplete() : setIndex((value) => value + 1);
  return (
    <Modal visible transparent animationType={reduced === false ? 'fade' : 'none'} statusBarTranslucent onRequestClose={onSkip}>
      <View style={styles.scrim} accessibilityViewIsModal>
      <View style={styles.card} accessibilityRole="summary">
        <View style={styles.topline}>
          <Txt variant="monoSm" tone="ink3">{tr(`STEP ${index + 1} OF ${steps.length}`)}</Txt>
          <MotionPressable onPress={onSkip} accessibilityRole="button" accessibilityLabel={tr('Skip guide')} style={styles.textButton}>
            <Txt variant="actionSmall" tone="ink2">Skip</Txt>
          </MotionPressable>
        </View>
        <Animated.View style={[styles.step, { opacity: fade }]}>
          <View style={styles.preview} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            {index === 0 ? <View style={styles.scanPreview}>
              <View style={styles.listingLine} /><View style={[styles.listingLine, styles.shortLine]} />
              <View style={styles.scanFrame}><View style={[styles.corner, styles.cornerTL]} /><View style={[styles.corner, styles.cornerTR]} /><View style={[styles.corner, styles.cornerBL]} /><View style={[styles.corner, styles.cornerBR]} /></View>
              <Animated.View style={[styles.tapRing, { opacity: tapOpacity, transform: [{ scale: tapScale }] }]} />
            </View> : null}
            {index === 1 ? <View style={styles.voicePreview}>
              <View style={styles.voiceMic}><MicIcon size={20} color={colors.accent} /></View>
              <View style={styles.waveform}>{bars.map((bar, barIndex) => <Animated.View key={barIndex}
                style={[styles.waveBar, { opacity: bar, transform: [{ scaleY: bar.interpolate({ inputRange: [0, 1], outputRange: [0.35, 1] }) }] }]} />)}</View>
            </View> : null}
            {index === 2 ? <View style={styles.sourcePreview}>
              <View style={styles.sourceTop}><GlobeIcon size={16} color={colors.ink2} /><View style={styles.sourceText}><View style={styles.sourceLine} /><View style={[styles.sourceLine, styles.sourceShort]} /></View></View>
              <View style={styles.sourceRule} />
              <View style={styles.sourceBottom}><View style={styles.sourceLabel} /><View style={styles.sourceCheck}><CheckCircleIcon size={18} color={colors.accent} /></View></View>
              <Animated.View style={[styles.sourceTap, { opacity: tapOpacity, transform: [{ scale: tapScale }] }]} />
            </View> : null}
          </View>
          <Txt variant="rowTitle" tone="ink" accessibilityRole="header">{tr(step.title)}</Txt>
          <Txt variant="bodyTight" tone="ink2" style={styles.copy}>{tr(step.copy)}</Txt>
        </Animated.View>
        <View style={styles.bottom}>
          <View style={styles.dots} accessibilityLabel={tr(`Step ${index + 1} of ${steps.length}`)}>
            {steps.map((item, dot) => <View key={item.title} style={[styles.dot, dot === index && styles.activeDot]} />)}
          </View>
          <MotionPressable onPress={next} accessibilityRole="button"
            accessibilityLabel={tr(index === steps.length - 1 ? 'Done' : 'Next')} style={styles.nextButton}>
            <Txt variant="actionSmall" tone={colors.onAccent}>{tr(index === steps.length - 1 ? 'Done' : 'Next')}</Txt>
          </MotionPressable>
        </View>
      </View>
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  scrim: { flex: 1, backgroundColor: 'rgba(0,0,0,0.32)', justifyContent: 'center', padding: PAGE_X },
  card: { backgroundColor: color.surface, borderColor: color.edge, borderWidth: 1, borderRadius: radius.xl,
    padding: 20, gap: gap[4], shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 6 },
  topline: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  textButton: { minWidth: 44, minHeight: 44, alignItems: 'flex-end', justifyContent: 'center' },
  step: { alignItems: 'flex-start', gap: 10, minHeight: 250, justifyContent: 'center' },
  preview: { width: '100%', height: 136, marginBottom: 3, alignItems: 'center', justifyContent: 'center' },
  scanPreview: { width: 204, height: 120, borderRadius: radius.m, borderWidth: 1, borderColor: color.edge, backgroundColor: color.ground, justifyContent: 'center', paddingHorizontal: 25, gap: 9 },
  listingLine: { height: 7, width: '76%', borderRadius: 4, backgroundColor: color.edgeStrong },
  shortLine: { width: '48%' },
  scanFrame: { position: 'absolute', left: 14, right: 14, top: 13, bottom: 13 },
  corner: { position: 'absolute', width: 13, height: 13, borderColor: color.accent },
  cornerTL: { left: 0, top: 0, borderLeftWidth: 2, borderTopWidth: 2 },
  cornerTR: { right: 0, top: 0, borderRightWidth: 2, borderTopWidth: 2 },
  cornerBL: { left: 0, bottom: 0, borderLeftWidth: 2, borderBottomWidth: 2 },
  cornerBR: { right: 0, bottom: 0, borderRightWidth: 2, borderBottomWidth: 2 },
  tapRing: { position: 'absolute', width: 28, height: 28, borderRadius: 14, borderWidth: 1.5, borderColor: color.accent, backgroundColor: color.accentSoft },
  voicePreview: { width: 204, height: 120, borderRadius: radius.m, borderWidth: 1, borderColor: color.edge, backgroundColor: color.ground, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 15 },
  voiceMic: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: color.accentSoft },
  waveform: { height: 42, flexDirection: 'row', alignItems: 'center', gap: 5 },
  waveBar: { width: 4, height: 32, borderRadius: 3, backgroundColor: color.accent },
  sourcePreview: { width: 224, height: 112, borderRadius: radius.m, borderWidth: 1, borderColor: color.edge, backgroundColor: color.ground, padding: 14, justifyContent: 'space-between', overflow: 'hidden' },
  sourceTop: { flexDirection: 'row', alignItems: 'center', gap: 9 }, sourceText: { flex: 1, gap: 6 },
  sourceLine: { height: 6, width: '84%', borderRadius: 3, backgroundColor: color.edgeStrong }, sourceShort: { width: '56%' },
  sourceRule: { height: StyleSheet.hairlineWidth, backgroundColor: color.edge },
  sourceBottom: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sourceLabel: { width: 66, height: 19, borderRadius: radius.pill, backgroundColor: color.accentSoft },
  sourceCheck: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: color.surface },
  sourceTap: { position: 'absolute', right: 17, bottom: 10, width: 30, height: 30, borderRadius: 15, borderWidth: 1.5, borderColor: color.accent },
  copy: { lineHeight: 21 }, bottom: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  dots: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: color.edgeStrong },
  activeDot: { width: 18, backgroundColor: color.accent },
  nextButton: { minWidth: 72, minHeight: 44, borderRadius: radius.pill, backgroundColor: color.accent, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16 },
}));
