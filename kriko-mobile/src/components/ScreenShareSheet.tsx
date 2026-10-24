import { useState } from 'react';
import { Modal, Pressable, StyleSheet, View } from 'react-native';

import { color, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { tr } from '../i18n';
import { ActivityDots, MotionView } from './Motion';
import { Divider } from './Chrome';
import { Button } from './Primitives';
import { ScanIcon, XIcon } from './Icon';
import { useOverlaySession } from './OverlaySession';

export function ScreenShareSheet({ onClose, onFallback }: { onClose: () => void; onFallback: () => void }) {
  const { active, available, start, stop } = useOverlaySession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const begin = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      if (active) await stop();
      else await start();
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : tr('Screen sharing could not start. Try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.wrap}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel={tr('Close screen sharing')} />
        <View style={styles.sheet}>
          <View style={styles.grab} />
          <MotionView delay={0} style={styles.head}>
            <View style={styles.mark}><ScanIcon size={21} color={color.accent} /></View>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">Share my screen</Txt>
              <Txt variant="bodyTight" tone="ink3">Scan products while you browse.</Txt>
            </View>
            <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close')} style={styles.close}>
              <XIcon size={20} color={color.ink2} />
            </Pressable>
          </MotionView>

          <MotionView delay={55} style={styles.steps}>
            <Step n="1" title="Allow Kriko over other apps." />
            <Divider inset={38} />
            <Step n="2" title="Approve Android’s screen sharing prompt." />
            <Divider inset={38} />
            <Step n="3" title="Browse and tap the floating Kriko button to scan." />
          </MotionView>

          <MotionView delay={105} style={styles.note}>
            <Txt variant="bodyTight" tone="ink3">
              Only frames you request are sent for reading. Stop from the floating panel or Android notification.
            </Txt>
            {!available ? (
              <Txt variant="bodyTight" tone="risk">
                {tr('The floating scanner needs the updated Android build. You can still upload a screenshot here.')}
              </Txt>
            ) : null}
            {error ? <Txt variant="bodyTight" tone="risk">{error}</Txt> : null}
            {busy ? <View style={styles.progress}><ActivityDots color={color.accent} /><Txt variant="bodyTight" tone="ink3">{active ? 'Stopping…' : 'Opening Android sharing…'}</Txt></View> : null}
          </MotionView>

          <View style={styles.actions}>
            <Button label={active ? 'Stop screen sharing' : 'Start floating scanner'} onPress={() => { void begin(); }} disabled={busy || !available} />
            <Button label="Choose a screenshot" variant="ghost" onPress={onFallback} disabled={busy} />
          </View>
        </View>
      </View>
    </Modal>
  );
}

function Step({ n, title }: { n: string; title: string }) {
  return (
    <View style={styles.step}>
      <View style={styles.number}><Txt variant="monoSm" tone="accent">{n}</Txt></View>
      <Txt variant="bodyTight" tone="ink" style={styles.stepText}>{title}</Txt>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, justifyContent: 'flex-end' },
  sheet: { backgroundColor: color.ground, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl, paddingHorizontal: gap[4], paddingTop: gap[2], paddingBottom: 28, gap: gap[4] },
  grab: { width: 38, height: 4, borderRadius: 2, backgroundColor: color.edge, alignSelf: 'center' },
  head: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  mark: { width: 42, height: 42, borderRadius: 21, backgroundColor: color.accentSoft, alignItems: 'center', justifyContent: 'center' },
  headText: { flex: 1, gap: 2 },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  steps: { paddingVertical: gap[1] },
  step: { minHeight: 50, flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  number: { width: 28, height: 28, borderRadius: 14, backgroundColor: color.accentSoft, alignItems: 'center', justifyContent: 'center' },
  stepText: { flex: 1 },
  note: { gap: gap[2] },
  progress: { minHeight: 36, flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  actions: { gap: gap[2] },
});
