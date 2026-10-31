import { useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { gap } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { tr } from '../i18n';
import { ActivityDots, MotionPressable, MotionView } from './Motion';
import { Divider } from './Chrome';
import { Button } from './Primitives';
import { ScanIcon, XIcon } from './Icon';
import { moveAppToBack } from '../engine/overlay';
import { useOverlaySession } from './OverlaySession';
import { AnimatedSheet } from './AnimatedSheet';

export function ScreenShareSheet({ onClose, onFallback }: { onClose: () => void; onFallback: () => void }) {
  const { active, available, start, stop } = useOverlaySession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const fallbackAfterClose = useRef(false);

  const color = useColors();
  const styles = useStyles();

  const begin = async (dismiss: () => void) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      if (active) {
        await stop();
        dismiss();
      } else {
        await start();
        dismiss();
        // Step aside once the sheet has folded, so the reader lands on the page
        // they meant to scan with the K already floating over it.
        setTimeout(() => { void moveAppToBack(); }, 380);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : tr('Screen sharing could not start. Try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatedSheet visible onClose={() => {
      onClose();
      if (fallbackAfterClose.current) {
        fallbackAfterClose.current = false;
        onFallback();
      }
    }} style={styles.panel}>
      {(dismiss) => (
        <View style={styles.content}>
          <MotionView delay={0} style={styles.head}>
            <View style={styles.mark}><ScanIcon size={21} color={color.accent} /></View>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">Share my screen</Txt>
              <Txt variant="bodyTight" tone="ink3">Scan products while you browse.</Txt>
            </View>
            <MotionPressable onPress={dismiss} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close')} style={styles.close}>
              <XIcon size={20} color={color.ink2} />
            </MotionPressable>
          </MotionView>

          <MotionView delay={55} style={styles.steps}>
            <Step n="1" title="Allow Kriko over other apps." />
            <Divider inset={38} />
            <Step n="2" title="Approve Android’s screen sharing prompt." />
            <Divider inset={38} />
            <Step n="3" title="Open the page you want, then tap the K to scan it. Press and hold for more." />
          </MotionView>

          <MotionView key={`${busy}-${active}-${error}`} delay={0} style={styles.note}>
            <Txt variant="bodyTight" tone="ink3">
              Only screens you scan are sent for reading. Stop by dropping the K on the ×, from its menu, or from the Android notification.
            </Txt>
            {!available ? (
              <Txt variant="bodyTight" tone="risk">
                {tr('The floating scanner needs the updated Android build. You can still upload a screenshot here.')}
              </Txt>
            ) : null}
            {error ? <Txt variant="bodyTight" tone="risk">{error}</Txt> : null}
            {busy ? <MotionView key="busy" style={styles.progress}><ActivityDots color={color.accent} /><Txt variant="bodyTight" tone="ink3">{active ? 'Stopping…' : 'Opening Android sharing…'}</Txt></MotionView> : null}
          </MotionView>

          <View style={styles.actions}>
            <Button label={active ? 'Stop screen sharing' : 'Start floating scanner'} onPress={() => { void begin(dismiss); }} disabled={busy || !available} />
            <Button label="Choose a screenshot" variant="ghost" onPress={() => { fallbackAfterClose.current = true; dismiss(); }} disabled={busy} />
          </View>
        </View>
      )}
    </AnimatedSheet>
  );
}

function Step({ n, title }: { n: string; title: string }) {
  const styles = useStyles();
  return (
    <View style={styles.step}>
      <View style={styles.number}><Txt variant="monoSm" tone="accent">{n}</Txt></View>
      <Txt variant="bodyTight" tone="ink" style={styles.stepText}>{title}</Txt>
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  panel: { paddingHorizontal: gap[4] },
  content: { gap: gap[4] },
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
}));
