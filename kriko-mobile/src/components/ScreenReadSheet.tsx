/**
 * "Read my screen" — the four-second version of a screenshot.
 *
 * Android's projection dialog is the only honest way an app can see another
 * app. The sheet says what will happen before it happens, then counts while the
 * reader switches to the listing; the native capture runs behind it.
 */

import { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { READ_SECONDS, readPhoneScreen, type CapturedImage } from '../engine/screen';
import { tr } from '../i18n';
import { gap } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { ScanIcon, XIcon } from './Icon';
import { Button } from './Primitives';
import { AnimatedSheet } from './AnimatedSheet';
import { ActivityDots, MotionPressable, MotionView } from './Motion';

type Phase = 'intro' | 'asking' | 'countdown' | 'reading' | 'error';

export function ScreenReadSheet({
  onClose,
  onShot,
  onFallback,
}: {
  onClose: () => void;
  onShot: (shot: CapturedImage) => void;
  onFallback: () => void;
}) {
  const [phase, setPhase] = useState<Phase>('intro');
  const [count, setCount] = useState(READ_SECONDS);
  const [error, setError] = useState('');
  const cancelled = useRef(false);
  const capture = useRef<AbortController | null>(null);
  const shotAfterDismiss = useRef<CapturedImage | null>(null);
  const fallbackAfterDismiss = useRef(false);

  useEffect(() => () => {
    cancelled.current = true;
    capture.current?.abort();
  }, []);

  useEffect(() => {
    if (phase !== 'countdown') return;
    const id = setInterval(() => {
      setCount((value) => Math.max(0, value - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [phase]);

  const color = useColors();
  const styles = useStyles();

  const close = (dismiss: () => void) => {
    cancelled.current = true;
    capture.current?.abort();
    dismiss();
  };

  const start = async (dismiss: () => void) => {
    if (capture.current) return;
    const controller = new AbortController();
    capture.current = controller;
    setError('');
    setCount(READ_SECONDS);
    setPhase('asking');
    try {
      const shot = await readPhoneScreen(() => {
        if (!cancelled.current) setPhase('countdown');
      }, controller.signal);
      if (!cancelled.current) {
        shotAfterDismiss.current = shot;
        dismiss();
      }
    } catch (caught) {
      if (cancelled.current) return;
      setError(
        caught instanceof Error
          ? caught.message
          : 'The screen could not be read. Try again, or use a screenshot.',
      );
      setPhase('error');
    } finally {
      capture.current = null;
    }
  };

  return (
    <AnimatedSheet visible onClose={() => {
      const shot = shotAfterDismiss.current;
      shotAfterDismiss.current = null;
      if (shot) onShot(shot);
      else {
        onClose();
        if (fallbackAfterDismiss.current) {
          fallbackAfterDismiss.current = false;
          onFallback();
        }
      }
    }} style={styles.panel}>
      {(dismiss) => (
          <View style={styles.content}>
          <View style={styles.head}>
            <View style={styles.mark}>
              <ScanIcon size={20} color={color.accentHi} />
            </View>
            <View style={styles.headText}>
              <Txt variant="cardTitle" tone="ink">
                Read my screen
              </Txt>
              <Txt variant="monoSm" tone="ink4" caps>
                android screen access · once per read
              </Txt>
            </View>
            <MotionPressable onPress={() => close(dismiss)} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close')}>
              <XIcon size={21} color={color.ink3} />
            </MotionPressable>
          </View>

          <MotionView key={phase} delay={0} style={styles.phase}>
          {phase === 'countdown' ? (
            count > 0 ? (
              <View style={styles.countBlock}>
                <Txt variant="monoSm" tone="ink3" caps>
                  Switch to the listing now
                </Txt>
                <MotionView key={count} delay={0} style={styles.countMotion}>
                <Txt variant="display" tone="ink" style={styles.count}>
                  {count}
                </Txt>
                </MotionView>
                <Txt variant="body" tone="ink2" style={styles.center}>
                  Kriko reads the screen when the count reaches zero. Stay on the listing until then.
                </Txt>
              </View>
            ) : (
              <View style={styles.countBlock}>
                <ActivityDots color={color.accentHi} />
                <Txt variant="body" tone="ink2" style={styles.center}>
                  Reading the screen…
                </Txt>
              </View>
            )
          ) : phase === 'asking' ? (
            <View style={styles.countBlock}>
              <ActivityDots color={color.accentHi} />
              <Txt variant="body" tone="ink2" style={styles.center}>
                {phase === 'asking' ? 'Waiting for Android…' : 'Reading the screen…'}
              </Txt>
            </View>
          ) : (
            <View style={styles.body}>
              <Txt variant="body" tone="ink2">
                {phase === 'error'
                  ? error
                  : 'Android will ask for screen access. Choose Entire screen, then switch to the product listing while Kriko counts four seconds.'}
              </Txt>
              <View style={styles.steps}>
                <Line n="1" text="Allow screen access." />
                <Line n="2" text="Switch to the listing; Kriko reads it four seconds later." />
                <Line n="3" text="The listing opens here for a check before you ask." />
              </View>
            </View>
          )}
          </MotionView>

          <View style={styles.footer}>
            {phase === 'intro' || phase === 'error' ? (
              <>
                <Button
                  label={phase === 'error' ? 'Try again' : 'Share my screen'}
                  icon={<ScanIcon size={17} color={color.onAccent} />}
                  onPress={() => { void start(dismiss); }}
                />
                <Button label="Use a screenshot" variant="ghost" onPress={() => { fallbackAfterDismiss.current = true; close(dismiss); }} />
              </>
            ) : (
              <Txt variant="monoSm" tone="ink4" style={styles.center}>
                Screen access can be cancelled in the Android dialog at any time.
              </Txt>
            )}
          </View>
          </View>
      )}
    </AnimatedSheet>
  );
}

function Line({ n, text }: { n: string; text: string }) {
  const styles = useStyles();
  return (
    <View style={styles.step}>
      <View style={styles.stepNumber}>
        <Txt variant="monoSm" tone="fill">
          {n}
        </Txt>
      </View>
      <Txt variant="bodyTight" tone="ink2" style={styles.stepText}>
        {text}
      </Txt>
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  panel: { paddingHorizontal: 18 },
  content: { gap: gap[5] },
  phase: { gap: gap[4] },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: gap[3] },
  mark: {
    width: 38,
    height: 38,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.accentSoft,
    borderWidth: 1,
    borderColor: color.edge,
  },
  headText: { flex: 1, gap: 3 },
  body: { gap: gap[4] },
  steps: { gap: gap[3] },
  step: { flexDirection: 'row', alignItems: 'flex-start', gap: gap[2] },
  stepNumber: {
    width: 22,
    height: 22,
    borderRadius: 11,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.inset,
  },
  stepText: { flex: 1, lineHeight: 20 },
  countBlock: { alignItems: 'center', gap: gap[3], paddingVertical: gap[5] },
  count: { fontSize: 64, lineHeight: 70, letterSpacing: -2 },
  countMotion: { alignItems: 'center' },
  center: { textAlign: 'center' },
  footer: { gap: gap[2] },
}));
