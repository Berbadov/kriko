/**
 * Where the phone's assistant gesture lands.
 *
 * Holding the power or home button summons Kriko as the phone's assistant. The
 * assistant window answers at once and saves the screenshot Android hands it,
 * then opens this route (`kriko://assist?shot=<file>`). It starts a fresh chat,
 * reads the picture and sends it, so the reader watches their own screen being
 * checked. A scan the floating K could not deliver (Kriko's screen had been
 * closed) arrives the same way.
 */

import * as FileSystem from 'expo-file-system/legacy';
import { router, useLocalSearchParams, type Href } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ProductCard } from '../components/ProductCard';
import { Button } from '../components/Primitives';
import { queueAssistantScan } from '../engine/assistflow';
import { AccessError, useStore } from '../engine/store';
import { discardFrame, keepThumbnail } from '../engine/thumbs';
import { tr } from '../i18n';
import { gap, PAGE_X } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

type Params = { shot?: string; error?: string; mode?: string; site?: string };

export default function Assist() {
  const params = useLocalSearchParams<Params>();
  const { hydrated, access, readShot, enqueueScan } = useStore();
  const color = useColors();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const shot = typeof params.shot === 'string' ? params.shot : '';
  // A failure belongs to the picture it happened to, so a second summoning with
  // a new picture starts without the last one's message.
  const [failed, setFailed] = useState<{ shot: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const handled = useRef('');
  const store = useRef({ readShot, enqueueScan });
  useEffect(() => {
    store.current = { readShot, enqueueScan };
  }, [readShot, enqueueScan]);
  const missing = hydrated && access.kind !== 'none' && !shot;
  const failure = missing
    ? tr('Kriko did not receive a screenshot. In your phone’s assistant settings, turn on “Use screenshot”.')
    : failed && failed.shot === shot ? failed.message : '';

  useEffect(() => {
    if (!hydrated) return undefined;
    // Without a way to ask, the front door is the right place to land.
    if (access.kind === 'none') {
      router.replace('/' as Href);
      return undefined;
    }
    if (!shot || handled.current === shot) return undefined;
    handled.current = shot;
    const controller = new AbortController();
    let queued = false;
    void (async () => {
      let base64 = '';
      try {
        base64 = await FileSystem.readAsStringAsync(shot, { encoding: 'base64' });
      } catch {
        if (controller.signal.aborted) return;
        setFailed({ shot, message: tr('Kriko could not read the screenshot your phone sent. Try again.') });
        return;
      }
      try {
        queued = await queueAssistantScan({
          signal: controller.signal,
          read: () => store.current.readShot(base64, 'image/jpeg', controller.signal, shot),
          keep: () => keepThumbnail(shot),
          enqueue: (reading, kept) => store.current.enqueueScan(reading, kept, undefined, {
            researchMode: params.mode === 'site_reviews' ? 'site_reviews' : 'research',
            reviewSite: typeof params.site === 'string' ? params.site : undefined,
          }),
        });
        if (!queued) return;
        router.replace('/queue' as Href);
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof AccessError) {
          router.replace('/' as Href);
          return;
        }
        setFailed({ shot, message: error instanceof Error ? error.message : 'The page could not be read.' });
      } finally {
        if (queued) await discardFrame(shot);
      }
    })();
    return () => {
      controller.abort();
      if (!queued && handled.current === shot) handled.current = '';
    };
  }, [hydrated, access.kind, shot, params.mode, params.site, attempt]);

  return (
    <View style={[styles.page, { paddingTop: insets.top + gap[6] }]}>
      {shot ? <ProductCard imageUri={shot} scanning={!failure} /> : null}
      <View style={styles.text}>
        <Txt variant="rowTitle" tone="ink">{failure ? 'Kriko could not finish' : 'Reading your screen'}</Txt>
        <Txt variant="bodyTight" tone="ink3">
          {failure || 'Research continues in the scan queue and is saved in History.'}
        </Txt>
      </View>
      {failure ? (
        <View style={styles.text}>
          {shot ? <Button label="Try again" onPress={() => {
            handled.current = '';
            setFailed(null);
            setAttempt((value) => value + 1);
          }} /> : null}
          <Button label="Back to chat" variant="ghost" onPress={() => router.replace('/' as Href)} />
        </View>
      ) : (
        <ActivityIndicator color={color.ink3} />
      )}
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: color.ground,
    paddingHorizontal: PAGE_X,
    gap: gap[4],
    alignItems: 'stretch',
  },
  text: { gap: 4 },
}));
